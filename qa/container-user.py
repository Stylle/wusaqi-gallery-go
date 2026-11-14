"""Verify the default image bootstrap and actual non-root PID 1."""
import json, os, secrets, subprocess, time, urllib.request
name='gallery-user-check-'+str(os.getpid())
image=os.environ.get('QA_DOCKER_IMAGE','wusaqi-gallery:ci')
environment={**os.environ,'ADMIN_PASSWORD':secrets.token_urlsafe(24)}
def command(*args):return subprocess.check_output(['docker',*args],env=environment,text=True).strip()
try:
 command('run','-d','--name',name,'--tmpfs','/data','-p','127.0.0.1::80','--env','ADMIN_PASSWORD',image)
 port=command('port',name,'80/tcp').rsplit(':',1)[1]
 for attempt in range(60):
  try:
   with urllib.request.urlopen('http://127.0.0.1:'+port+'/api/health',timeout=2) as response: assert json.load(response)['ok']
   break
  except Exception:
   if attempt==59:raise RuntimeError('Container did not become healthy')
   time.sleep(.25)
 uid=command('exec',name,'python','-c',"from pathlib import Path;print(next(line.split()[1] for line in Path('/proc/1/status').read_text().splitlines() if line.startswith('Uid:')))")
 assert uid=='10001','Application PID 1 is not UID 10001'
 command('exec',name,'test','-f','/usr/share/licenses/wusaqi-gallery/LICENSE')
 print('Default container health, non-root PID 1 and MIT license passed')
finally:
 subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
