"""Actual private CPython, Win32 locks, Firefox and frontend round trips in CI.

Only touches a disposable copy of the CI installation, never user data.
"""
import ctypes
from ctypes import wintypes
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE/'native-host'))
import windows_install
import platform_support

@unittest.skipUnless(sys.platform=='win32' and os.environ.get('KITTY_WINDOWS_AUDIT')=='1' and os.environ.get('GITHUB_ACTIONS')=='true','Dedicated Windows CI only')
class NativeWindowsAudit(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  platform_support.configure_worker_job()
  cls.temp=tempfile.TemporaryDirectory(prefix='kitty-native-audit-')
  cls.root=Path(cls.temp.name)/'Kitty français & 100% !'
  cls.root.mkdir()
  installed=windows_install.app_root()
  current=windows_install.checked_version_path(installed,windows_install.current_install(installed))
  version=json.loads((SOURCE/'backend.json').read_text())['version']
  prepared=cls.root/'versions'/(version+'-'+uuid.uuid4().hex)
  prepared.mkdir(parents=True)
  for directory in ('runtime','packages','bin','backend'):
   shutil.copytree(current/directory,prepared/directory)
  windows_install.commit_install(cls.root,prepared,version,register_host=False)
  cls.current=prepared

 @classmethod
 def tearDownClass(cls): cls.temp.cleanup()

 def query(self,action,**values):
  message={'action':action,'client':{'version':json.loads((SOURCE/'extension/manifest.json').read_text())['version'],'protocol':1},**values}
  payload=json.dumps(message,ensure_ascii=False).encode('utf-8')
  env={**os.environ,'MOZ_HEADLESS':'1'}
  proc=subprocess.run([str(Path(os.environ['SystemRoot'])/'System32/cmd.exe'),'/d','/s','/c',r'.\native-host.bat'],cwd=self.root,
      input=struct.pack('<I',len(payload))+payload,capture_output=True,timeout=45,env=env)
  self.assertEqual(proc.returncode,0,proc.stderr.decode('utf-8','replace'))
  self.assertGreaterEqual(len(proc.stdout),4,proc.stderr)
  self.assertEqual(struct.unpack('<I',proc.stdout[:4])[0],len(proc.stdout)-4)
  return json.loads(proc.stdout[4:])

 def node(self,mode):
  proc=subprocess.run(['node',str(SOURCE/'tests/test-windows-native-bridge.js'),str(self.root),mode],capture_output=True,text=True,encoding='utf-8',timeout=120)
  self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
  print(proc.stdout,flush=True)

 def test_01_real_private_packages_and_frontend_round_trips(self):
  report=self.query('runtime_check')
  self.assertTrue(report['ok'],report)
  psutil_report=next(item for item in report['modules'] if item['name']=='psutil')
  self.assertTrue(psutil_report['process_smoke']['liveness_checked'])
  self.assertTrue(report['process_integrity']['ok'])
  self.assertGreater(report['process_integrity']['checked'],1)
  self.node('healthy')

 def test_02_corrupt_psutil_is_detected_and_never_archives_active_job(self):
  init=self.current/'packages/psutil/__init__.py'
  original=init.read_bytes()
  queue=self.root/'cache/queue.json'
  prior=queue.read_bytes()
  try:
   state=json.loads(prior)
   state['active']={'id':'audit-active','status':'downloading','worker_pid':os.getpid(),
                    'url':'https://example.test/fixture','mode':'audio','started_at':time.time()-10}
   queue.write_text(json.dumps(state),encoding='utf-8')
   protected=queue.read_bytes()
   init.write_bytes(original+b'\ndel process_iter\n')
   report=self.query('runtime_check')
   self.assertFalse(report['ok'])
   self.assertFalse(report['process_integrity']['ok'])
   self.assertTrue(any('process_iter' in issue for issue in report['issues']),report)
   self.node('corrupt')
   self.assertEqual(queue.read_bytes(),protected)
  finally:
   init.write_bytes(original)
   queue.write_bytes(prior)
  self.assertTrue(self.query('runtime_check')['ok'])

 def test_03_percent_directory_uses_real_ytdlp_template(self):
  script=self.root/'check-template.py'
  script.write_text('''import sys
from pathlib import Path
import worker
from yt_dlp import YoutubeDL
out=Path(sys.argv[1]);opts=worker.build_opts('audio',lambda _:None,out)
with YoutubeDL(opts) as ydl:
 path=Path(ydl.prepare_filename({'id':'fixture','title':'Titre français 100% !','ext':'opus'}))
 assert path.parent==out, (path,out)
 assert '100%' in path.name
 opts['outtmpl']=worker.output_template_for_stem(out,'Titre 100% !')
with YoutubeDL(opts) as ydl:
 assert Path(ydl.prepare_filename({'id':'fixture','title':'unused','ext':'opus'})).parent==out
''',encoding='utf-8')
  env={**os.environ,'PATH':str(self.current/'bin')+os.pathsep+os.environ['PATH']}
  proc=subprocess.run([str(self.current/'runtime/python.exe'),'-I','-B',str(script),str(self.root/'destination 100% !')],capture_output=True,timeout=30,env=env)
  self.assertEqual(proc.returncode,0,proc.stderr.decode('utf-8','replace'))

 def open_without_delete_sharing(self,path):
  kernel=ctypes.WinDLL('kernel32',use_last_error=True)
  kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
  kernel.CreateFileW.restype=wintypes.HANDLE
  kernel.CloseHandle.argtypes=[wintypes.HANDLE]
  handle=kernel.CreateFileW(str(path),0x80000000,3,None,3,0,None)
  if handle==ctypes.c_void_p(-1).value: raise ctypes.WinError(ctypes.get_last_error())
  return lambda: kernel.CloseHandle(handle)

 def test_04_native_write_recovers_from_real_sharing_lock(self):
  settings=self.root/'config/settings.json'
  old=settings.read_bytes()
  close=self.open_without_delete_sharing(settings)
  try:
   with ThreadPoolExecutor(max_workers=1) as pool:
    future=pool.submit(self.query,'set_output_dir',output_dir=str(self.root/'nouveau dossier'))
    time.sleep(.15)
    self.assertEqual(settings.read_bytes(),old)
    close();close=None
    result=future.result(timeout=10)
   self.assertTrue(result['ok'],result)
   self.assertEqual(json.loads(settings.read_text())['output_dir'],str(self.root/'nouveau dossier'))
  finally:
   if close:close()

 def test_05_real_firefox_profile_lifecycle_and_readonly_cleanup(self):
  import psutil
  started=self.query('youtube_auth_start')
  self.assertTrue(started['ok'],started)
  pending=json.loads((self.root/'cache/youtube-auth-pending.json').read_text())
  session=self.root/'cache/youtube-auth-sessions'/pending['token']
  profile=session/'profile'
  processes=[]
  try:
   end=time.monotonic()+20
   while time.monotonic()<end:
    processes=[p for p in psutil.process_iter(['name','cmdline']) if str(p.info['name']).lower()=='firefox.exe'
      and any(str(profile).casefold()==str(arg).casefold() for arg in (p.info['cmdline'] or []))]
    if processes:break
    time.sleep(.1)
   self.assertTrue(processes,'Dedicated Firefox process must really start')
   self.assertEqual(self.query('youtube_auth_status')['state'],'browser_open')
   children=[]
   for proc in processes:
    try: children.extend(proc.children(recursive=True))
    except psutil.NoSuchProcess: pass
   for proc in children+processes:
    try: proc.terminate()
    except psutil.NoSuchProcess: pass
   _,remaining=psutil.wait_procs(children+processes,timeout=10)
   for proc in remaining:
    try: proc.kill()
    except psutil.NoSuchProcess: pass
   psutil.wait_procs(remaining,timeout=5)
   for filename in ('cookies.sqlite','cookies.sqlite-wal','cookies.sqlite-shm'):
    (profile/filename).unlink(missing_ok=True)
   conn=sqlite3.connect(profile/'cookies.sqlite')
   with conn:
    conn.execute('PRAGMA user_version=16')
    conn.execute('CREATE TABLE moz_cookies(host TEXT,name TEXT,value TEXT,path TEXT,expiry INTEGER,isSecure INTEGER)')
    conn.executemany('INSERT INTO moz_cookies VALUES(?,?,?,?,?,?)',[
      ('.youtube.com','SAPISID','fixture-only','/',1893456000000,1),('.google.com','SID','excluded','/',1893456000000,1)])
   conn.close()
   readonly=profile/'readonly.fixture';readonly.write_text('fixture');readonly.chmod(0o400)
   # Allow the startup grace period to elapse before testing closed detection.
   pending['created_at']=time.time()-3
   (self.root/'cache/youtube-auth-pending.json').write_text(json.dumps(pending))
   completed=self.query('youtube_auth_status')
   self.assertTrue(completed['ok'],completed)
   self.assertTrue(completed['enabled'])
   self.assertFalse(session.exists())
   snapshot=(self.root/'config/youtube-auth/cookies.txt').read_text()
   self.assertIn('.youtube.com',snapshot);self.assertNotIn('.google.com',snapshot)
   self.assertTrue(self.query('youtube_auth_delete')['ok'])
  finally:
   for proc in processes:
    try:
     if proc.is_running():proc.kill()
    except psutil.NoSuchProcess:pass

 def test_06_native_concurrent_settings_preserve_session_and_destination(self):
  cookie=self.root/'config/youtube-auth/cookies.txt'
  cookie.parent.mkdir(parents=True,exist_ok=True)
  cookie.write_text('# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t1893456000\tSAPISID\tfixture-only\n')
  destination=str(self.root/'simultaneous 100% !')
  with ThreadPoolExecutor(max_workers=8) as pool:
   futures=[pool.submit(self.query,'set_output_dir',output_dir=destination) if i%2 else
            pool.submit(self.query,'youtube_auth_set_enabled',enabled=True) for i in range(24)]
   for future in futures:self.assertTrue(future.result(timeout=45)['ok'])
  saved=json.loads((self.root/'config/settings.json').read_text())
  self.assertEqual(saved['output_dir'],destination)
  self.assertTrue(saved['youtube_auth_enabled'])
  self.assertEqual(list((self.root/'config').glob('*.tmp')),[])
  self.assertTrue(self.query('youtube_auth_delete')['ok'])


if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8',errors='replace')
 sys.stderr.reconfigure(encoding='utf-8',errors='replace')
 unittest.main(verbosity=2)
