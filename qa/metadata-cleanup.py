"""Clean existing originals/variants with a durable admin queue and rollback."""
import io
from pathlib import Path
import sqlite3
import tempfile
import time
from urllib.parse import unquote, urlsplit

import regression as qa
from metadata import photo, inspect, MARKER


def suite(data):
    proc,log,call,env=qa.run(data)
    try:
        admin=call('POST','/api/auth/login',{'username':'owner','password':'qa-pass-123'})[1]['token']
        call('POST','/api/users',{'username':'member','password':'member-pass'},admin)
        user=call('POST','/api/auth/login',{'username':'member','password':'member-pass'})[1]['token']
        images=[]
        for n in range(5):
            b,h=qa.multipart([('files',f'old-{n}.jpg',qa.pic('JPEG'))])
            im=call('POST','/api/upload',b,user if n==0 else admin,h)[1]['results'][0]['item']
            paths=[data/'uploads'/im['key'],data/'thumbs'/(im['key']+'.webp'),data/'compressed'/unquote(urlsplit(im['compressed']).path).removeprefix('/compressed/')]
            paths[0].write_bytes(photo('JPEG'))
            paths[1].write_bytes(photo('WEBP'))
            paths[2].write_bytes(photo('WEBP'))
            images.append((im,paths))
        call('PATCH','/api/images/'+images[0][0]['id'],{'tag':'私密'},admin)
        corrupt=images[1][1][0];corrupt.write_bytes(b'broken-image-'+MARKER)
        images[4][1][1].unlink();images[4][1][2].unlink()
        db=sqlite3.connect(data/'metadata.db')
        db.execute('UPDATE images SET orig_name=?',('PRIVATE-camera-source.jpg',))
        snapshot={row[0]:row[1:] for row in db.execute('SELECT id,key,owner_id,tag,created_at FROM images')}
        blocked=images[2][0]['id']
        db.execute("CREATE TRIGGER qa_block_metadata BEFORE UPDATE OF size ON images WHEN OLD.id='"+blocked+"' BEGIN SELECT RAISE(ABORT,'qa reject metadata'); END")
        db.commit();db.close()
        old_bytes={im['id']:[p.read_bytes() if p.exists() else None for p in paths] for im,paths in images}
        before={it['id']:it for it in call('GET','/api/images?include_private=1',token=admin)[1]['items']}
        qa.check('metadata cleanup is admin only',call('POST','/api/admin/local/repair',{'batchSize':1,'mode':'metadata'},user)[0]==403)
        qa.check('metadata queue validates mode',call('POST','/api/admin/local/repair',{'batchSize':1,'mode':'bad'},admin)[0]==400)
        result=call('POST','/api/admin/local/repair',{'batchSize':1,'mode':'metadata'},admin)[1]
        qa.check('one click queues all existing images including private ones',result['counts']['total']==5 and result['job']['mode']=='metadata')
        call('POST','/api/admin/local/repair/pause',token=admin)
        qa.check('cleanup queue pauses without discarding work',call('GET','/api/admin/local/repair',token=admin)[1]['job']['status']=='paused')
        qa.check('paused cleanup cannot be accidentally replaced by another queue',call('POST','/api/admin/local/repair',{'batchSize':1},admin)[0]==409)
        proc.terminate();proc.wait(timeout=20);log.close()
        proc,log,call,env=qa.run(data)
        state=call('GET','/api/admin/local/repair',token=admin)[1]
        qa.check('cleanup mode, pause and pending work survive restart',state['job']['mode']=='metadata' and state['job']['status']=='paused' and state['counts']['pending']>0)
        call('DELETE','/api/images/'+images[3][0]['id'],token=admin)
        call('POST','/api/admin/local/repair/resume',{'batchSize':2},admin)
        def wait():
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                state=call('GET','/api/admin/local/repair',token=admin)[1]
                if state['job']['status']=='completed':return state
                time.sleep(.1)
            raise AssertionError(state)
        state=wait()
        qa.check('cleanup automatically drains batches and reports deleted records',state['counts']['done']==2 and state['counts']['failed']==2 and state['counts']['skipped']==1)
        qa.check('failed cleanup retries exactly three times',all(f['attempts']==4 for f in state['failures']))
        qa.check('corrupt source failure retains all original files',all(p.read_bytes()==raw for p,raw in zip(images[1][1],old_bytes[images[1][0]['id']])))
        qa.check('database commit failure rolls back every replaced variant',all(p.read_bytes()==raw for p,raw in zip(images[2][1],old_bytes[blocked])))
        for index in (0,4):
            im,paths=images[index]
            for p in paths:
                if not p.exists():continue
                value=p.read_bytes();inspect(value)
                qa.check('completed cleanup removes source records from existing '+p.parent.name,MARKER not in value)
        qa.check('cleanup does not create missing derivatives',not images[4][1][1].exists() and not images[4][1][2].exists())
        db=sqlite3.connect(data/'metadata.db');db.execute('DROP TRIGGER qa_block_metadata');db.commit();db.close()
        corrupt.write_bytes(photo('JPEG'))
        call('POST','/api/admin/local/repair/retry-failed',{'batchSize':1},admin)
        state=wait()
        qa.check('failed items can be retried without repeating successful work',state['counts']['done']==4 and state['counts']['failed']==0 and state['counts']['skipped']==1)
        db=sqlite3.connect(data/'metadata.db')
        current={row[0]:row[1:] for row in db.execute('SELECT id,key,owner_id,tag,created_at FROM images')};db.close()
        qa.check('cleanup preserves URLs, owners, labels and creation dates',all(row==snapshot[key] for key,row in current.items()))
        after={it['id']:it for it in call('GET','/api/images?include_private=1',token=admin)[1]['items']}
        qa.check('cleaned original URLs gain a new cache version without changing path',all(urlsplit(before[k]['url']).path==urlsplit(v['url']).path and before[k]['url']!=v['url'] for k,v in after.items()))
        qa.check('old public links now return cleaned bytes',MARKER not in call('GET',before[blocked]['url'],raw=True)[1])
        qa.check('cleanup retains private-image access restrictions',call('GET',after[images[0][0]['id']]['url'],raw=True)[0]==404 and call('GET',after[images[0][0]['id']]['viewUrl'],token=admin,raw=True)[0]==200)
        qa.check('database reflects cleaned sizes and hides historical source filenames',all(v['size']==len((data/'uploads'/v['key']).read_bytes()) and v['origName']==Path(v['key']).name for v in after.values()))
        qa.check('successful and rolled-back work leaves no temporary backups',not list(data.glob('.repair-*')))
        print(f'\n{qa.passed} existing-photo cleanup checks passed',flush=True)
    finally:
        proc.terminate();proc.wait(timeout=20);log.close()


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='metadata-cleanup-',dir=qa.TEMP) as tmp:suite(Path(tmp))
