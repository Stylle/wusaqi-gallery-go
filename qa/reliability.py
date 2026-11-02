"""Real-service checks for resumable uploads and durable derivative repair.

Only isolated .qa-data is touched. Supports native and QA_DOCKER_IMAGE runs.
"""
import hashlib
import http.client
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from urllib.parse import urlsplit

import regression as qa


def wait_for(fn, predicate, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = fn()
        if predicate(value):
            return value
        time.sleep(.1)
    raise AssertionError(f"timeout waiting for work queue: {value}")


def suite(data):
    proc, log, call, env = qa.run(data)
    try:
        token = call('POST', '/api/auth/login', {'username':'owner','password':'qa-pass-123'})[1]['token']
        call('POST', '/api/users', {'username':'other','password':'other-pass'}, token)
        other = call('POST', '/api/auth/login', {'username':'other','password':'other-pass'})[1]['token']
        def create(payload, name='resumable.bmp', client=None, auth=token):
            body = {'clientId': client or os.urandom(16).hex(), 'filename':name, 'size':len(payload),
                    'tag':'resume', 'sha256':hashlib.sha256(payload).hexdigest()}
            status, row = call('POST', '/api/uploads', body, auth)
            assert status==200, row
            return row, body
        def chunk(row, payload, offset=0, auth=token, checksum=None):
            return call('PUT', f"/api/uploads/{row['id']}/chunk", payload, auth,
                        {'Upload-Offset':str(offset), 'X-Chunk-SHA256': checksum or hashlib.sha256(payload).hexdigest()})
        def status(row): return call('GET', '/api/uploads/'+row['id'], token=token)[1]
        def finish(row):
            result = call('POST', f"/api/uploads/{row['id']}/complete", token=token)
            assert result[0]==200, result
            return wait_for(lambda:status(row), lambda s:s['status'] in ('done','failed'))
        def send(payload, name='file.png'):
            row,_=create(payload,name)
            for offset in range(0,len(payload),row['chunkSize']):
                assert chunk(row,payload[offset:offset+row['chunkSize']],offset)[0]==200
            return row

        payload = qa.pic('BMP',(900,600))
        row, body = create(payload)
        qa.check('resumable initialization is authenticated', call('POST','/api/uploads',body)[0]==401)
        qa.check('repeated initialization returns same upload ID', call('POST','/api/uploads',body,token)[1]['id']==row['id'])
        qa.check('upload sessions are owner isolated', call('GET','/api/uploads/'+row['id'],token=other)[0]==404 and chunk(row,b'wrong',auth=other)[0]==404)
        qa.check('incomplete upload cannot commit or appear in gallery', call('POST',f"/api/uploads/{row['id']}/complete",token=token)[0]==409 and call('GET','/api/images')[1]['total']==0)

        # Deliberately close a TCP connection with a truncated request body.
        base=urlsplit('http://'+env['LISTEN_ADDR'])
        conn=http.client.HTTPConnection(base.hostname,base.port,timeout=10)
        conn.putrequest('PUT',f"/api/uploads/{row['id']}/chunk")
        for k,v in {'Authorization':'Bearer '+token,'Upload-Offset':'0','X-Chunk-SHA256':hashlib.sha256(payload[:row['chunkSize']]).hexdigest(),'Content-Length':str(row['chunkSize'])}.items(): conn.putheader(k,v)
        conn.endheaders(); conn.send(payload[:100]); conn.close()
        time.sleep(.2)
        qa.check('mid-chunk disconnect never advances acknowledged bytes', status(row)['received']==0 and call('GET','/api/images')[1]['total']==0)
        qa.check('invalid chunk checksum leaves progress unchanged', chunk(row,payload[:100],checksum='0'*64)[0]==400 and status(row)['received']==0)
        first=payload[:row['chunkSize']]
        qa.check('valid chunk is acknowledged after durable write', chunk(row,first)[1]['received']==len(first))
        qa.check('lost chunk response can safely repeat same offset', chunk(row,first)[1]['received']==len(first))
        qa.check('repeated offset with different bytes is rejected', chunk(row,b'x'*len(first))[0]==409)
        qa.check('forward offset is rejected without appending', chunk(row,b'x',len(first)+10)[0]==409)
        qa.check('chunked payload is not scanned as a local original', call('GET','/api/admin/local/scan',token=token)[1]['pendingCount']==0)

        # Crash after filesystem write but before acknowledgement in SQLite.
        proc.terminate();proc.wait(timeout=20);log.close()
        part=data/'.incoming'/row['id']/'original.part'
        with part.open('ab') as f: f.write(b'unacknowledged-tail')
        proc,log,call,env=qa.run(data)
        qa.check('receiving task and offset survive service restart', status(row)['received']==len(first))
        qa.check('next chunk truncates unacknowledged crash tail', chunk(row,payload[len(first):],len(first))[0]==200 and part.read_bytes()==payload)
        done=finish(row)
        qa.check('completed upload exposes all variants only after processing', done['status']=='done' and all(call('GET',done['item'][k],raw=True)[0]==200 for k in ('url','thumb','compressed')))
        qa.check('staging payload is removed after successful commit', not part.parent.exists())
        qa.check('lost completion response resolves to the same image', call('POST',f"/api/uploads/{row['id']}/complete",token=token)[1]['item']['id']==done['item']['id'] and call('POST','/api/uploads',body,token)[1]['item']['id']==done['item']['id'] and call('GET','/api/images')[1]['total']==1)
        proc.terminate();proc.wait(timeout=20);log.close();proc,log,call,env=qa.run(data)
        qa.check('completion receipt survives restart without duplicate image', status(row)['item']['id']==done['item']['id'] and call('GET','/api/images')[1]['total']==1)

        cancelled,_=create(qa.pic(), 'cancel.png')
        qa.check('cancel removes private payload without affecting committed image', call('DELETE','/api/uploads/'+cancelled['id'],token=token)[0]==200 and not (data/'.incoming'/cancelled['id']).exists() and call('GET','/api/images')[1]['total']==1)
        qa.check('cancelled upload cannot be committed', call('POST',f"/api/uploads/{cancelled['id']}/complete",token=token)[0]==410)
        qa.check('completed images cannot be deleted through upload cancellation', call('DELETE','/api/uploads/'+row['id'],token=token)[0]==409)
        bad=send(b'not an image','broken.png');bad_done=finish(bad)
        qa.check('codec failure is bounded to initial plus three retries', bad_done['status']=='failed' and bad_done['attempts']==4)
        qa.check('failed processing stays private and absent from gallery', call('GET','/api/images')[1]['total']==1 and not list((data/'thumbs').rglob('*broken*')) and (data/'.incoming'/bad['id']/'original.part').exists())
        call('DELETE','/api/uploads/'+bad['id'],token=token)

        mismatch,_=create(qa.pic(),'checksum.png')
        wrong=bytearray(qa.pic());wrong[-1]^=1
        assert chunk(mismatch,bytes(wrong))[0]==200
        result=finish(mismatch)
        qa.check('full file SHA256 detects incorrectly resumed content', result['status']=='failed' and 'SHA256' in result['error'] and call('GET','/api/images')[1]['total']==1)
        call('DELETE','/api/uploads/'+mismatch['id'],token=token)

        # A failed database insert must roll back files and the completion receipt.
        db=sqlite3.connect(data/'metadata.db')
        db.execute("CREATE TRIGGER qa_reject BEFORE INSERT ON images BEGIN SELECT RAISE(ABORT,'injected commit failure'); END");db.commit();db.close()
        pending=send(qa.pic(),'transaction.png')
        call('POST',f"/api/uploads/{pending['id']}/complete",token=token)
        wait_for(lambda:status(pending),lambda s:s['attempts']>=1 and s['status']=='queued')
        qa.check('database failure never acknowledges an uncommitted image', call('GET','/api/images')[1]['total']==1 and status(pending)['status'] in ('queued','processing'))
        db=sqlite3.connect(data/'metadata.db');db.execute('DROP TRIGGER qa_reject');db.commit();db.close()
        result=wait_for(lambda:status(pending),lambda s:s['status']=='done')
        qa.check('transient commit failure retries automatically with exactly one result', 2<=result['attempts']<=4 and call('GET','/api/images')[1]['total']==2)

        for n in range(4):
            item=send(qa.pic(),f'queue-{n}.png');assert finish(item)['status']=='done'
        call('POST','/api/admin/local/clear-derived',{'confirm':'clear-derived'},token)
        qa.check('repair queue requires admin', call('POST','/api/admin/local/repair',{'batchSize':2},other)[0]==403)
        qa.check('repair batch size is validated', call('POST','/api/admin/local/repair',{'batchSize':0},token)[0]==400)
        started=call('POST','/api/admin/local/repair',{'batchSize':2},token)[1]
        qa.check('one click queues entire missing library beyond one batch', started['counts']['total']==6 and started['job']['batch_size']==2)
        qa.check('duplicate repair start is rejected', call('POST','/api/admin/local/repair',{'batchSize':2},token)[0]==409)
        qa.check('clear and import cannot race running repair', call('POST','/api/admin/local/clear-derived',{'confirm':'clear-derived'},token)[0]==409 and call('POST','/api/admin/local/import',token=token)[0]==409)
        qa.check('restore cannot replace data while repair is running', call('POST','/api/admin/restore',{},token)[0]==409)
        call('POST','/api/admin/local/repair/pause',token=token)
        repair=lambda:call('GET','/api/admin/local/repair',token=token)[1]
        paused=wait_for(repair,lambda s:not s['counts']['processing'])
        time.sleep(.7)
        qa.check('pause retains remaining work without starting next batch', repair()['job']['status']=='paused' and repair()['counts']==paused['counts'])
        proc.terminate();proc.wait(timeout=20);log.close();proc,log,call,env=qa.run(data)
        qa.check('paused repair persists after restart', repair()['job']['status']=='paused' and repair()['counts']['total']==6)
        resumed=call('POST','/api/admin/local/repair/resume',{'batchSize':3},token)[1]
        qa.check('resuming queue applies the updated batch size', resumed['job']['batch_size']==3)
        completed=wait_for(repair,lambda s:s['job']['status']=='completed')
        qa.check('queue automatically drains all batches without another click', completed['counts']['done']==6 and completed['counts']['pending']==0)
        qa.check('queue repair restores all image variants', call('GET','/api/admin/local/index',token=token)[1]['missingCompressed']==0 and call('GET','/api/admin/local/index',token=token)[1]['missingThumbs']==0)

        images=call('GET','/api/images')[1]['items'];broken=images[0];source=data/'uploads'/broken['key'];saved=source.read_bytes()
        source.write_bytes(b'invalid image')
        call('POST','/api/admin/local/clear-derived',{'confirm':'clear-derived'},token)
        call('POST','/api/admin/local/repair',{'batchSize':2},token)
        finished=wait_for(repair,lambda s:s['job']['status']=='completed')
        qa.check('bad repair item retries three times then lets queue finish', finished['counts']['failed']==1 and finished['counts']['done']==5 and finished['failures'][0]['attempts']==4 and finished['counts']['retried']==3)
        source.write_bytes(saved)
        call('POST','/api/admin/local/repair/retry-failed',token=token)
        retried=wait_for(repair,lambda s:s['job']['status']=='completed')
        qa.check('explicit retry targets exhausted items after underlying issue is fixed', retried['counts']['done']==6 and retried['counts']['failed']==0)

        expiring,_=create(qa.pic(),'expired.png')
        proc.terminate();proc.wait(timeout=20);log.close()
        db=sqlite3.connect(data/'metadata.db');db.execute('UPDATE upload_sessions SET expires=0 WHERE id=?',(expiring['id'],));db.commit();db.close()
        proc,log,call,env=qa.run(data)
        qa.check('expired incomplete payload and receipt are cleaned on startup', call('GET','/api/uploads/'+expiring['id'],token=token)[0]==404 and not (data/'.incoming'/expiring['id']).exists())
        qa.check('restored upload history includes committed results', any(s.get('item',{}).get('id')==done['item']['id'] for s in call('GET','/api/uploads',token=token)[1]['items']))
        old_pending,_=create(qa.pic(),'old-pending.png')
        db=sqlite3.connect(data/'metadata.db')
        db.execute("UPDATE upload_sessions SET created_at='2000-01-01T00:00:00+00:00' WHERE id=?",(old_pending['id'],))
        for n in range(55):
            receipt=os.urandom(16).hex()
            db.execute("INSERT INTO upload_sessions(id,owner_id,client_id,filename,tag,size,sha256,received,status,image_id,key,created_at,updated_at,expires) SELECT ?,owner_id,?,filename,tag,size,sha256,received,status,image_id,key,created_at,updated_at,expires FROM upload_sessions WHERE id=?",(receipt,receipt,row['id']))
        db.commit();db.close()
        history=call('GET','/api/uploads',token=token)[1]['items']
        qa.check('unfinished uploads stay visible despite more than 50 newer receipts', len(history)==50 and history[0]['id']==old_pending['id'])
        print(f'\n{qa.passed} reliability checks passed',flush=True)
    finally:
        proc.terminate();proc.wait(timeout=20);log.close()


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='reliability-',dir=qa.TEMP) as tmp:
        suite(Path(tmp))
