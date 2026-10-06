#!/usr/bin/env python3
"""Real yt-dlp + FFmpeg against deterministic local TS and fMP4 HLS fixtures."""
import contextlib
import importlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'native-host'))
import hls,queue_store,worker,host,yt_dlp

class HlsTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory(prefix='kitty-hls-');cls.root=Path(cls.tmp.name)
  cls.media=cls.root/'media';cls.media.mkdir()
  for kind,height in [('low',720),('high',1080),('fmp4',180)]:
   directory=cls.media/kind;directory.mkdir()
   cmd=['ffmpeg','-v','error','-f','lavfi','-i',f'color=c=blue:s={height*16//9}x{height}:r=10',
    '-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','2','-c:v','libx264',
    '-threads','1','-preset','ultrafast','-g','10','-sc_threshold','0','-c:a','aac','-f','hls',
    '-hls_time','1','-hls_list_size','0']
   if kind=='fmp4':cmd+=['-hls_segment_type','fmp4','-hls_fmp4_init_filename','init.mp4']
   cmd+=['-hls_segment_filename',(directory/('seg%03d.m4s' if kind=='fmp4' else 'seg%03d.ts')).as_posix(),(directory/'index.m3u8').as_posix()]
   subprocess.run(cmd,check=True,timeout=25)
  cls.requests=[];cls.lock=threading.Lock();cls.segment_seen=threading.Event();cls.manifest_seen=threading.Event();cls.slow=False
  class Handler(BaseHTTPRequestHandler):
   def do_GET(self):
    with cls.lock:cls.requests.append((self.path,dict(self.headers)))
    path=urlsplit(self.path).path
    status=200;mime='application/vnd.apple.mpegurl';data=b''
    extra=cls.extra_response(self.path,dict(self.headers)) if hasattr(cls,'extra_response') else None
    if extra is not None:status,mime,data=extra
    elif path.startswith('/protected/') and (self.headers.get('Referer')!=cls.base+'/page' or self.headers.get('Origin')!=cls.base or self.headers.get('User-Agent')!='Firefox HLS QA'):
     status=403;data=b'Forbidden'
    elif path=='/expired.m3u8':status=410;data=b'Gone'
    elif path=='/drm.m3u8':data=b'#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://secret",KEYFORMAT="com.apple.streamingkeydelivery"\n#EXTINF:2,\nlow/seg000.ts\n#EXT-X-ENDLIST\n'
    elif path=='/empty.m3u8':data=b'#EXTM3U\n#EXT-X-ENDLIST\n'
    elif path=='/unsupported':mime='text/html';data=b'<html><title>Unsupported local player</title><body>JavaScript-only player</body></html>'
    elif path=='/normal':mime='text/html';data=b'<html><title>Normal supported page</title><video src="/normal.mp4"></video></html>'
    else:
     rel=path.removeprefix('/protected').removeprefix('/signed').removeprefix('/slow')
     if path.startswith('/slow/'):
      cls.manifest_seen.set();time.sleep(.6)
     if rel=='/master.m3u8':
      if path.startswith('/signed') and 'token=DO-NOT-LOG-ME' not in self.path:status=403;data=b'Forbidden'
      else:data=b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100000,RESOLUTION=1280x720,CODECS="avc1.42e01f,mp4a.40.2"\nlow/index.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=200000,RESOLUTION=1920x1080,CODECS="avc1.42e01f,mp4a.40.2"\nhigh/index.m3u8\n'
     elif rel=='/stream':data=(cls.media/'low/index.m3u8').read_bytes().replace(b'seg',b'low/seg')
     elif rel=='/normal.mp4':data=(cls.media/'normal.mp4').read_bytes();mime='video/mp4'
     else:
      file=cls.media/rel.lstrip('/')
      if not file.is_file():status=404;data=b'Missing'
      else:
       data=file.read_bytes();mime='application/vnd.apple.mpegurl' if file.suffix=='.m3u8' else 'video/mp4' if file.suffix in ('.mp4','.m4s') else 'video/mp2t'
       if file.suffix in ('.ts','.m4s'):
        cls.segment_seen.set()
        if cls.slow:time.sleep(.6)
    self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.end_headers()
    try:self.wfile.write(data)
    except (BrokenPipeError,ConnectionResetError):pass
   def log_message(self,*args):pass
  subprocess.run(['ffmpeg','-v','error','-i',str(cls.media/'low/index.m3u8'),'-c','copy',str(cls.media/'normal.mp4')],check=True,timeout=15)
  cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);cls.base=f'http://127.0.0.1:{cls.server.server_port}'
  cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
 @classmethod
 def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.tmp.cleanup()
 def setUp(self):
  self.output=self.root/('output-'+self._testMethodName);self.output.mkdir()
  self.cache=self.root/('cache-'+self._testMethodName);self.cache.mkdir()
  self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
  for attr,value in [('QUEUE_FILE',self.cache/'queue.json'),('LOCK_FILE',self.cache/'queue.lock'),('CONTROL_DIR',self.cache/'controls'),('DEFAULT_OUTPUT_DIR',self.output)]:
   self.stack.enter_context(patch.object(worker,attr,value))
  self.logs=[];self.stack.enter_context(patch.object(worker,'log',self.logs.append))
  self.stack.enter_context(patch.object(worker,'start_next_if_any',lambda:None))
  worker.cancel_requested=False;worker.external_stop_requested=False
  self.requests.clear();self.segment_seen.clear();self.manifest_seen.clear();type(self).slow=False
 def source(self,path='/master.m3u8',headers=None,mime='application/vnd.apple.mpegurl'):
  return hls.validate_source(dict(type='hls',url=self.base+path,page_url=self.base+'/page',tab_id=1,timestamp=time.time(),content_type=mime,headers=headers or {},title='HLS fixture'))
 def job(self,source=None,mode='1080',url=None,fallbacks=None):
  active=dict(id='fixture',url=url or source['url'],mode=mode,output_dir=str(self.output),status='starting',started_at=time.time(),youtube_auth=False)
  if source:active['media_source']=source
  if fallbacks:active['hls_fallbacks']=fallbacks
  queue_store.atomic_json(worker.QUEUE_FILE,{**queue_store.default_state(),'active':active})
  with patch.object(sys,'argv',['worker.py','fixture']):result=worker.main()
  final=worker.get_state();self.assertIsNone(final['active']);return result,final['history'][0]
 def successful(self,**kwargs):
  result,entry=self.job(**kwargs);self.assertEqual(result,0,entry);self.assertEqual(entry['status'],'finished',entry)
  file=Path(entry['filepath']);self.assertTrue(file.is_file());self.assertGreater(file.stat().st_size,100)
  info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(file)],timeout=15))
  self.assertTrue(any(s['codec_type']=='audio' for s in info['streams']))
  self.assertTrue(any(s['codec_type']=='video' for s in info['streams']))
  return entry,info
 def test_master_and_quality(self):
  entry,info=self.successful(source=self.source(),mode='720')
  self.assertEqual(next(s['height'] for s in info['streams'] if s['codec_type']=='video'),720)
  report=host.probe_hls(self.source());self.assertTrue(report['ok'],report);self.assertEqual(report['heights'],[720,1080])
 def test_direct_media_ts(self):self.successful(source=self.source('/low/index.m3u8'))
 def test_fmp4(self):
  self.successful(source=self.source('/fmp4/index.m3u8'))
  self.assertTrue(any('.m4s' in p for p,_ in self.requests));self.assertTrue(any('/init.mp4' in p for p,_ in self.requests))
 def test_signed_query(self):
  self.successful(source=self.source('/signed/master.m3u8?token=DO-NOT-LOG-ME&quality=original'))
  self.assertTrue(any('?token=DO-NOT-LOG-ME&quality=original' in p for p,_ in self.requests));self.assertNotIn('DO-NOT-LOG-ME','\n'.join(self.logs))
 def test_extensionless_manifest(self):self.successful(source=self.source('/stream',mime='audio/x-mpegurl'))
 def test_referer_origin_ua_for_manifest_and_segments(self):
  headers={'Referer':self.base+'/page','Origin':self.base,'User-Agent':'Firefox HLS QA'}
  self.successful(source=self.source('/protected/master.m3u8',headers))
  protected=[h for p,h in self.requests if p.startswith('/protected/')]
  self.assertTrue(protected);self.assertTrue(all(h.get('Referer')==headers['Referer'] for h in protected))
  self.assertNotIn(headers['User-Agent'],'\n'.join(self.logs))
 def test_page_failure_uses_same_job_fallback(self):
  entry,_=self.successful(url=self.base+'/unsupported',fallbacks=[self.source()]);self.assertTrue(entry['hls_used']);self.assertEqual(entry['url'],self.base+'/unsupported')
 def test_normal_supported_page_does_not_use_fallback(self):
  entry,_=self.successful(url=self.base+'/normal',fallbacks=[self.source('/expired.m3u8')]);self.assertFalse(entry.get('hls_used'));self.assertFalse(any('/expired' in p for p,_ in self.requests))
 def test_expired_denied_empty_drm(self):
  for path,code in [('/expired.m3u8','hls_expired'),('/protected/master.m3u8','hls_access_denied'),('/empty.m3u8','hls_no_formats'),('/drm.m3u8','drm_protected')]:
   with self.subTest(path=path):
    result,entry=self.job(source=self.source(path));self.assertEqual(result,1,entry);self.assertEqual(entry['error_code'],code,entry)
  self.assertFalse(any('skd://' in p for p,_ in self.requests))
 def test_cancel_cleans_partial(self):
  type(self).slow=True
  def cancel():
   self.segment_seen.wait(10);worker.CONTROL_DIR.mkdir(exist_ok=True);queue_store.atomic_json(worker.CONTROL_DIR/'fixture.json',{'action':'cancel'});os.kill(os.getpid(),signal.SIGTERM)
  thread=threading.Thread(target=cancel,daemon=True);thread.start()
  result,entry=self.job(source=self.source());thread.join(2)
  self.assertEqual(result,0,entry);self.assertEqual(entry['status'],'cancelled');self.assertEqual(list(self.output.iterdir()),[])
 def test_cancel_during_manifest_request(self):
  def cancel():
   self.manifest_seen.wait(10);worker.CONTROL_DIR.mkdir(exist_ok=True);queue_store.atomic_json(worker.CONTROL_DIR/'fixture.json',{'action':'cancel'});os.kill(os.getpid(),signal.SIGTERM)
  thread=threading.Thread(target=cancel,daemon=True);thread.start()
  result,entry=self.job(source=self.source('/slow/master.m3u8'));thread.join(2)
  self.assertEqual(result,0,entry);self.assertEqual(entry['status'],'cancelled');self.assertEqual(list(self.output.iterdir()),[])
 def test_validation_and_sensitive_errors(self):
  for change in [{'url':'file:///tmp/master.m3u8'},{'url':self.base+'/seg.ts'},{'headers':{'Cookie':'secret'}},{'headers':{'Referer':'https://a.test/\r\nInjected: yes'}},{'timestamp':float('nan')},{'tab_id':True}]:
   with self.subTest(change=change):
    value={**self.source(),**change}
    with self.assertRaises(ValueError):hls.validate_source(value)
  self.assertEqual(hls.identity(self.base+'/master.m3u8?token=a&quality=720',self.base+'/page'),hls.identity(self.base+'/master.m3u8?token=b&quality=720',self.base+'/page'))
  self.assertNotEqual(hls.identity(self.base+'/master.m3u8?quality=720',self.base+'/page'),hls.identity(self.base+'/master.m3u8?quality=1080',self.base+'/page'))
  self.assertNotIn('SECRET',json.dumps(hls.error_info(Exception('HTTP Error 403 https://host.test/master.m3u8?token=SECRET'))))

if __name__=='__main__':unittest.main(verbosity=2)
