"""Real HTTP privacy and revocable-link regression, using disposable data only."""
import hashlib
import json
from pathlib import Path
import tempfile
import urllib.error
import urllib.request
from urllib.parse import quote

import regression as qa


def suite(data):
    proc, log, call, env = qa.run(data)
    try:
        base = 'http://' + env['LISTEN_ADDR']

        def request(method, path, token='', cookie='', headers=None, value=None):
            h = dict(headers or {})
            if token: h['Authorization'] = 'Bearer ' + token
            if cookie: h['Cookie'] = cookie
            body = None if value is None else json.dumps(value).encode()
            if body is not None: h['Content-Type'] = 'application/json'
            req = urllib.request.Request(base + path, data=body, headers=h, method=method)
            try: res = qa.opener.open(req, timeout=60)
            except urllib.error.HTTPError as e: res = e
            with res: return res.status, res.read(), res.headers

        login = request('POST', '/api/auth/login', value={'username':'owner','password':'qa-pass-123'})
        admin = json.loads(login[1])['token']
        admin_cookie = login[2]['Set-Cookie'].split(';')[0]
        qa.check('login issues HttpOnly same-site media cookie', 'HttpOnly' in login[2]['Set-Cookie'] and 'SameSite=Strict' in login[2]['Set-Cookie'] and 'Path=/media/' in login[2]['Set-Cookie'])
        call('POST','/api/users',{'username':'member','password':'member-pass'},admin)
        member = call('POST','/api/auth/login',{'username':'member','password':'member-pass'})[1]['token']
        def upload(name, tag='', token=admin):
            b,h = qa.multipart([('files',name,qa.pic())],{'tag':tag})
            result = call('POST','/api/upload',b,token,h)[1]['results'][0]
            assert result['ok'],result
            return result['item']
        public = upload('public.png','cats')
        secret = upload('secret.png','私密')
        owned = upload('owned.png','owned',member)
        qa.check('private image has no share links', secret['private'] and secret['shareUrls']=={})
        qa.check('admin gallery hides private images until opted in', call('GET','/api/images',token=admin)[1]['total']==2 and call('GET','/api/images?include_private=1',token=admin)[1]['total']==3)
        qa.check('guests and members cannot opt into private images', all(call('GET','/api/images?include_private=1',token=t)[1]['total']==2 for t in ('',member)))
        qa.check('private tag is hidden from public tag counts', all('私密' not in [x['name'] for x in call('GET','/api/tags?include_private=1',token=t)[1]['tags']] for t in ('',member)))
        qa.check('admin can opt into private tag counts', '私密' in [x['name'] for x in call('GET','/api/tags?include_private=1',token=admin)[1]['tags']])
        qa.check('tag policy management is admin only', call('GET','/api/admin/tags',token=member)[0]==403)
        for key, view in [('url','viewUrl'),('thumb','viewThumb'),('compressed','viewCompressed')]:
            qa.check('private '+key+' share is always blocked', all(request('GET',secret[key],token=t)[0]==404 for t in ('',member,admin)))
            qa.check('private '+view+' requires admin', request('GET',secret[view],token=member)[0]==404 and request('GET',secret[view],cookie=admin_cookie)[0]==200)
        qa.check('private media requires a live session, not a token in URL', request('GET',secret['viewUrl']+'?token='+admin)[0]==404)
        qa.check('media cookie cannot authorize an API mutation', request('PUT','/api/admin/settings',cookie=admin_cookie,value={'site_title':'bad'})[0]==401)
        qa.check('private image cannot be batch-downloaded by member', call('POST','/api/images/batch/download',{'ids':[secret['id']]},member)[0]==404)
        qa.check('private image can be batch-downloaded by admin', call('POST','/api/images/batch/download',{'ids':[secret['id']]},admin,raw=True)[0]==200)
        qa.check('member cannot assign private tag singly or in batch', call('PATCH','/api/images/'+owned['id'],{'tag':'私密'},member)[0]==403 and call('PATCH','/api/images/batch',{'ids':[owned['id']],'tag':'私密'},member)[0]==403)
        payload=qa.pic()
        qa.check('resumable upload rejects private label for member', call('POST','/api/uploads',{'clientId':'privacy-client-0001','filename':'test.png','size':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),'tag':'私密'},member)[0]==403)
        call('PUT','/api/admin/settings',{'random_public':'1'},admin)
        qa.check('public random never exposes private tag', call('GET','/api/random?tag='+quote('私密'))[0]==404)
        qa.check('member random cannot opt into private tag', call('GET','/api/random?include_private=1&tag='+quote('私密'),token=member)[0]==404)
        guest = request('GET','/api/public/settings')[2]['Set-Cookie'].split(';')[0]
        qa.check('internal viewing URL is not an anonymous share link', request('GET',public['viewUrl'])[0]==404 and request('GET',public['viewUrl'],cookie=guest)[0]==200)
        call('PUT','/api/admin/settings',{'external_links_enabled':'0'},admin)
        for key in ('url','thumb','compressed'):
            qa.check('global sharing switch revokes old '+key+' links', request('GET',public[key],headers={'If-Modified-Since':'Wed, 01 Jan 2031 00:00:00 GMT','Range':'bytes=0-2'})[0]==404 and request('HEAD',public[key])[0]==404)
        qa.check('global sharing closure preserves guest gallery', request('GET',public['viewUrl'],cookie=guest)[0]==200)
        qa.check('public random respects global sharing closure', call('GET','/api/random')[0]==403)
        qa.check('authenticated random still works internally', call('GET','/api/random',token=admin)[0]==200)
        qa.check('sharing closure removes copy targets', call('GET','/api/images?tag=cats',token=admin)[1]['items'][0]['shareUrls']=={})
        call('PUT','/api/admin/settings',{'external_links_enabled':'1','external_disabled_tags':json.dumps(['cats'])},admin)
        qa.check('tag sharing rule revokes old links but preserves other tags', request('GET',public['url'])[0]==404 and request('GET',owned['url'])[0]==200)
        qa.check('tag sharing rule covers random', call('GET','/api/random?tag=cats')[0]==404)
        qa.check('tag sharing rule covers all variants', all(request('GET',public[k])[0]==404 for k in ('thumb','compressed')))
        call('PATCH','/api/images/'+public['id'],{'tag':'open'},admin)
        qa.check('retagging immediately uses the new policy', request('GET',public['url'])[0]==200)
        call('PATCH','/api/images/'+owned['id'],{'tag':'私密'},admin)
        qa.check('previous owner cannot retag or delete newly private image', call('PATCH','/api/images/'+owned['id'],{'tag':'owned'},member)[0]==404 and call('DELETE','/api/images/'+owned['id'],token=member)[0]==404)
        qa.check('previous public URL stops working after private retag', request('GET',owned['url'])[0]==404)
        for value in ['null','{}','[1]','["'+('x'*41)+'"]']:
            qa.check('invalid tag rules rejected',call('PUT','/api/admin/settings',{'external_disabled_tags':value},admin)[0]==400)
        call('PUT','/api/admin/settings',{'site_tags':'私密,open','upload_default_tags':'私密,open','copyright_notice':'如有侵权请联系 <script>unsafe</script>','copyright_contact':'rights@example.test','site_public':'0'},admin)
        settings = call('GET','/api/public/settings')[1]
        qa.check('public settings expose contact but never secret or private upload defaults', settings['copyright_contact']=='rights@example.test' and settings['site_tags']=='open' and settings['upload_default_tags']=='open' and '_viewer_secret' not in settings)
        for path in ('/api/images','/api/tags','/api/random','/api/random/image'):
            qa.check('closed site rejects anonymous '+path,call('GET',path)[0]==401)
        qa.check('site closure revokes existing guest media cookie', request('GET',public['viewUrl'],cookie=guest)[0]==404)
        qa.check('closed site disables all public share links', request('GET',public['url'])[0]==404)
        qa.check('closed site retains logged-in browsing', request('GET',public['viewUrl'],token=member)[0]==200 and call('GET','/api/images',token=member)[0]==200)
        qa.check('closed site preserves login and health', call('POST','/api/auth/login',{'username':'owner','password':'qa-pass-123'})[0]==200 and call('GET','/api/health')[0]==200)
        qa.check('policy-protected media is never cacheable', 'no-store' in request('GET',secret['viewUrl'],cookie=admin_cookie)[2]['Cache-Control'])
        call('POST','/api/auth/logout',token=admin)
        qa.check('logout revokes the media cookie immediately', request('GET',secret['viewUrl'],cookie=admin_cookie)[0]==404)
        proc.terminate(); proc.wait(timeout=20); log.close()
        proc,log,call,env=qa.run(data)
        qa.check('privacy settings survive restart',call('GET','/api/images')[0]==401 and call('GET','/api/public/settings')[1]['copyright_contact']=='rights@example.test')
        print(f'\n{qa.passed} privacy HTTP checks passed',flush=True)
    finally:
        proc.terminate(); proc.wait(timeout=20); log.close()


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='privacy-',dir=qa.TEMP) as tmp: suite(Path(tmp))
