"""Real HTTP media, Range, yt-dlp, worker controls and ffprobe verification."""
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import struct
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('hlsfixtures',Path(__file__).with_name('test-hls-download.py'))
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
import hls,host,worker,metadata_guard,queue_store,direct_media


class DirectTests(base.HlsTests):
 @classmethod
 def setUpClass(cls):
  super().setUpClass()
  cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=2)
  def ff(*args):subprocess.run(['ffmpeg','-v','error',*args],check=True,timeout=30)
  ff('-i',str(cls.media/'normal.mp4'),'-c','copy','-movflags','+faststart',str(cls.media/'direct.mp4'))
  ff('-i',str(cls.media/'normal.mp4'),'-c','copy','-movflags','+faststart',
     '-encryption_scheme','cenc-aes-ctr','-encryption_key','00112233445566778899aabbccddeeff',
     '-encryption_kid','ffeeddccbbaa99887766554433221100',str(cls.media/'direct-protected.mp4'))
  ff('-i',str(cls.media/'normal.mp4'),'-c:v','libvpx-vp9','-threads','1','-deadline','realtime','-cpu-used','8','-c:a','libopus',str(cls.media/'direct.webm'))
  for ext,codec in [('mp3','libmp3lame'),('m4a','aac'),('opus','libopus')]:
   ff('-f','lavfi','-i','sine=frequency=500:sample_rate=44100','-t','2','-c:a',codec,str(cls.media/('direct.'+ext)))
  ff('-i',str(cls.media/'direct.mp4'),'-vf','scale=640:360','-c:v','libx264','-threads','1','-preset','ultrafast','-c:a','copy',str(cls.media/'clip_360p.mp4'))
  (cls.media/'clip_720p.mp4').write_bytes((cls.media/'direct.mp4').read_bytes())
  ff('-i',str(cls.media/'high/index.m3u8'),'-c','copy','-movflags','+faststart',str(cls.media/'clip_1080p.mp4'))
  body=(cls.media/'direct.mp4').read_bytes();cls.large=body+struct.pack('>I4s',1048584,b'free')+b'\0'*1048576
  cls.slow_seen=threading.Event();cls.transfer_seen=threading.Event();cls.transfer_slow=False;cls.interrupt_enabled=False
  class Handler(BaseHTTPRequestHandler):
   def do_GET(self):
    with cls.lock:cls.requests.append((self.path,dict(self.headers)))
    path=urlsplit(self.path).path;status=200;mime='video/mp4';headers={}
    if path=='/unsupported':data=b'<html><title>Direct player</title><body>JS-only player</body></html>';mime='text/html'
    elif path=='/normal':data=b'<html><title>Normal video page</title><video src="/direct.mp4"></video></html>';mime='text/html'
    elif path=='/direct-missing.mp4':status=404;data=b'Missing'
    elif path=='/direct-expired.mp4':status=410;data=b'Gone'
    elif path=='/direct-denied.mp4':status=403;data=b'Denied'
    elif path=='/direct-slow.mp4':cls.slow_seen.set();time.sleep(3);data=(cls.media/'direct.mp4').read_bytes()
    elif path=='/direct-partial.mp4':status=206;data=cls.large[1000:2000];headers['Content-Range']=f'bytes 1000-1999/{len(cls.large)}'
    elif path=='/direct-fake.mp4':data=b'<html>not media</html>';mime='text/html'
    elif path in ('/direct-transfer.mp4','/direct-interrupted.mp4'):data=cls.large
    elif path.startswith('/protected-direct/'):
     if self.headers.get('Referer')!=cls.base+'/unsupported' or self.headers.get('Origin')!=cls.base or self.headers.get('User-Agent')!='Firefox Direct QA':status=403;data=b'Denied'
     else:data=(cls.media/'direct.mp4').read_bytes()
    elif path=='/browser-referer.mp4':
     if self.headers.get('Referer')!=cls.base+'/unsupported':status=403;data=b'Denied'
     else:data=(cls.media/'direct.mp4').read_bytes()
    elif path=='/direct-stream':data=(cls.media/'direct.mp4').read_bytes()
    else:
     file=cls.media/path.lstrip('/')
     if not file.is_file():status=404;data=b'Missing'
     else:
      data=file.read_bytes();mime={'.webm':'video/webm','.mp3':'audio/mpeg','.m4a':'audio/mp4','.opus':'audio/ogg','.mpd':'application/dash+xml','.m3u8':'application/vnd.apple.mpegurl','.ts':'video/mp2t'}.get(file.suffix,'video/mp4')
    if 'signed' in self.path and 'token=DO-NOT-LOG-DIRECT' not in self.path:status=403;data=b'Denied'
    if path=='/direct.mp4':headers['Content-Disposition']='inline; filename="Useful name.mp4"'
    full=len(data);match=re.fullmatch(r'bytes=(\d+)-(\d*)',self.headers.get('Range',''))
    if match and status==200 and mime!='text/html':
     start=int(match[1]);end=min(int(match[2]) if match[2] else full-1,full-1)
     if start>=full:status=416;data=b''
     else:status=206;data=data[start:end+1];headers['Content-Range']=f'bytes {start}-{end}/{full}'
    self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.send_header('Accept-Ranges','bytes')
    for name,value in headers.items():self.send_header(name,value)
    self.end_headers()
    try:
     if path=='/direct-interrupted.mp4' and cls.interrupt_enabled:
      self.wfile.write(data[:4096]);self.wfile.flush();self.close_connection=True;return
     for offset in range(0,len(data),4096):
      self.wfile.write(data[offset:offset+4096]);self.wfile.flush()
      if path=='/direct-transfer.mp4' and cls.transfer_slow:
       cls.transfer_seen.set();time.sleep(.01)
    except (BrokenPipeError,ConnectionResetError):pass
   def log_message(self,*args):pass
  cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);cls.base=f'http://127.0.0.1:{cls.server.server_port}'
  cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
 def setUp(self):
  super().setUp();type(self).transfer_slow=False;type(self).interrupt_enabled=False;self.slow_seen.clear();self.transfer_seen.clear()
 def source(self,path='/direct.mp4',headers=None,mime='video/mp4',kind='direct_video',title='Readable page title',metadata=None):
  return hls.validate_source(dict(type=kind,url=self.base+path,page_url=self.base+'/unsupported',tab_id=1,timestamp=time.time(),content_type=mime,headers=headers or {},title=title,metadata=metadata or {}))
 def test_direct_mp4(self):
  entry,streams=self.successful(source=self.source(),mode='720');self.assertEqual(entry['media_used'],'direct_video')
  self.assertEqual(next(s['height'] for s in streams['streams'] if s['codec_type']=='video'),720);self.assertEqual(Path(entry['filepath']).stem,'Readable page title')
 def test_direct_webm(self):self.successful(source=self.source('/direct.webm',mime='video/webm'),mode='best')
 def test_direct_audio(self):
  for ext,mime in [('mp3','audio/mpeg'),('m4a','audio/mp4'),('opus','audio/ogg')]:
   with self.subTest(ext=ext):
    result,entry=self.job(source=self.source('/direct.'+ext,mime=mime,kind='direct_audio'),mode='audio');self.assertEqual(result,0,entry)
    streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',entry['filepath']],timeout=15))['streams']
    self.assertEqual({s['codec_type'] for s in streams},{'audio'})
 def test_direct_mime_only(self):self.successful(source=self.source('/direct-stream'),mode='720')
 def test_direct_tokens(self):
  self.successful(source=self.source('/direct.mp4?signed=1&token=DO-NOT-LOG-DIRECT&cdn=KEEP'),mode='720')
  self.assertTrue(any('cdn=KEEP' in url for url,_ in self.requests));self.assertNotIn('DO-NOT-LOG-DIRECT','\n'.join(self.logs))
 def test_direct_referer_origin_user_agent(self):
  headers={'Referer':self.base+'/unsupported','Origin':self.base,'User-Agent':'Firefox Direct QA'}
  self.successful(source=self.source('/protected-direct/video.mp4',headers),mode='720')
  requests=[h for url,h in self.requests if url.startswith('/protected-direct/')]
  self.assertTrue(requests);self.assertTrue(all(all(h.get(k)==v for k,v in headers.items()) for h in requests))
 def test_range_context_is_not_replayed(self):
  self.successful(source=self.source(metadata={'content_range':'bytes 0-999/1000000','request_range':'bytes=0-999','size':1000000}),mode='720')
  self.assertFalse(any(h.get('Range')=='bytes=0-999' for _,h in self.requests))
 def test_direct_quality_group(self):
  source=self.source('/clip_1080p.mp4');source['variants']=[self.source('/clip_'+str(h)+'p.mp4') for h in (1080,720,360)]
  source=hls.validate_source(source);report=host.probe_hls(source);self.assertTrue(report['ok'],report);self.assertEqual(report['heights'],[360,720,1080])
  self.assertEqual(report['format_count'],3);self.assertTrue(report['size'])
  entry,streams=self.successful(source=source,mode='720');self.assertEqual(next(s['height'] for s in streams['streams'] if s['codec_type']=='video'),720)
  self.assertTrue(all(not v['headers'] for v in entry['media_source']['variants']))
 def test_classic_url_keeps_priority(self):
  entry,_=self.successful(url=self.base+'/normal',fallbacks=[self.source('/direct-expired.mp4')],mode='720');self.assertFalse(entry.get('media_used'));self.assertFalse(any('/direct-expired' in url for url,_ in self.requests))
 def test_classic_and_direct_same_resource_no_duplicate(self):
  entry,_=self.successful(url=self.base+'/normal',mode='720');self.assertTrue(entry['network_resource_ids'])
  source={**self.source(),'page_url':self.base+'/normal'}
  with patch.object(host,'QUEUE_FILE',worker.QUEUE_FILE),patch.object(host,'LOCK_FILE',worker.LOCK_FILE),patch.object(host,'WORKER',ROOT/'native-host/worker.py'),patch.object(host,'get_output_dir',lambda:self.output):
   result=host.enqueue(source['url'],'720',media_source=source)
  self.assertEqual(result['code'],'already_downloaded',result)
 def test_direct_page_fallback(self):
  entry,_=self.successful(url=self.base+'/unsupported',fallbacks=[self.source()],mode='720');self.assertEqual(entry['url'],self.base+'/unsupported');self.assertEqual(entry['media_used'],'direct_video')
 def test_direct_failures(self):
  for path,code in [('/direct-missing.mp4','direct_unavailable'),('/direct-expired.mp4','direct_expired'),('/direct-denied.mp4','direct_access_denied'),('/direct-partial.mp4','direct_partial'),('/direct-fake.mp4','direct_unavailable')]:
   with self.subTest(path=path):
    result=host.probe_hls(self.source(path));self.assertFalse(result['ok']);self.assertEqual(result['code'],code,result)
 def test_direct_slow_metadata_timeout(self):
  with patch.object(host,'PROBE_TIMEOUT',.6):
   started=time.monotonic();result=host.probe_hls(self.source('/direct-slow.mp4'));self.assertEqual(result['code'],'metadata_timeout',result);self.assertLess(time.monotonic()-started,2)
  self.successful(source=self.source(),mode='720')
 def test_optional_probe_timeout_keeps_raw(self):
  with patch.object(direct_media.subprocess,'run',side_effect=subprocess.TimeoutExpired('ffprobe',.1)):
   self.assertEqual(direct_media._probe(self.base+'/direct.mp4',{}),{})
 def test_direct_probe_uses_windows_hidden_launcher(self):
  import platform_support
  fake=subprocess.CompletedProcess([],0,stdout=b'{"streams":[]}',stderr=b'')
  with patch.object(platform_support,'WINDOWS',True),patch.object(subprocess,'CREATE_NO_WINDOW',0x08000000,create=True),patch.object(subprocess,'run',return_value=fake) as run:
   self.assertEqual(direct_media._probe('https://example.test/direct.mp4',{}),{})
  self.assertEqual(run.call_args.kwargs['creationflags'],0x08000000)
  self.assertEqual(run.call_args.kwargs['timeout'],metadata_guard.FFPROBE_TIMEOUT)
  self.assertIn('-tls_verify',run.call_args.args[0])
 def test_direct_drm_classification(self):
  fake=subprocess.CompletedProcess([],0,stdout=json.dumps({'streams':[{'codec_tag_string':'encv'}]}).encode(),stderr=b'')
  with patch.object(direct_media.subprocess,'run',return_value=fake):
   with self.assertRaises(hls.HlsError) as caught:direct_media._probe(self.base+'/direct.mp4',{})
   self.assertEqual(caught.exception.code,'direct_drm')
  result=host.probe_hls(self.source('/direct-protected.mp4'))
  self.assertFalse(result['ok']);self.assertEqual(result['code'],'direct_drm',result)
 def test_direct_disposition_filename(self):
  entry,_=self.successful(source=self.source(title='DIRECT_VIDEO stream'),mode='720')
  self.assertEqual(Path(entry['filepath']).stem,'Useful name')
 def test_direct_input_validation(self):
  for change in [{'url':'blob:https://example.test/id'},{'url':self.base+'/chunk0001.mp4'},{'headers':{'Range':'bytes=0-9'}},{'headers':{'Cookie':'private'}},{'metadata':{'size':True}},{'metadata':{'height':float('inf')}}]:
   with self.subTest(change=change),self.assertRaises(ValueError):hls.validate_source({**self.source(),**change})
  source=self.source('/clip_720p.mp4');source['variants']=[self.source('/direct.webm',mime='video/webm')]
  with self.assertRaises(ValueError):hls.validate_source(source)
 def enable_after_metadata(self,flag):
  original=worker.extract_metadata
  def wrapped(*a,**kw):
   result=original(*a,**kw);setattr(type(self),flag,True);return result
  return patch.object(worker,'extract_metadata',wrapped)
 def test_direct_progress_history_destination(self):
  updates=[];original=worker.update_active
  def capture(**fields):updates.append(dict(fields));return original(**fields)
  with self.enable_after_metadata('transfer_slow'),patch.object(worker,'update_active',capture):entry,_=self.successful(source=self.source('/direct-transfer.mp4'),mode='720')
  progress=[u for u in updates if u.get('downloaded',0)>0 and u.get('total',0)>0]
  self.assertTrue(progress);self.assertTrue(any(u.get('speed',0) for u in progress));self.assertTrue(any(u.get('eta') is not None for u in progress))
  self.assertEqual(Path(entry['filepath']).parent,self.output);self.assertEqual(entry['status'],'finished');self.assertEqual(entry['media_source']['headers'],{})
 def test_direct_interrupted(self):
  original=worker.build_opts
  def opts(*a,**kw):value=original(*a,**kw);value['retries']=0;return value
  with self.enable_after_metadata('interrupt_enabled'),patch.object(worker,'build_opts',opts):result,entry=self.job(source=self.source('/direct-interrupted.mp4'),mode='720')
  self.assertEqual(result,1,entry);self.assertEqual(entry['status'],'error');self.assertFalse(Path(entry['filepath']).is_file())
 def test_direct_cancel_transfer(self):
  def cancel():
   self.transfer_seen.wait(10);worker.CONTROL_DIR.mkdir(exist_ok=True);queue_store.atomic_json(worker.CONTROL_DIR/'fixture.json',{'action':'cancel'});os.kill(os.getpid(),signal.SIGTERM)
  thread=threading.Thread(target=cancel,daemon=True);thread.start()
  with self.enable_after_metadata('transfer_slow'):result,entry=self.job(source=self.source('/direct-transfer.mp4'),mode='720')
  thread.join(2);self.assertEqual(result,0,entry);self.assertEqual(entry['status'],'cancelled');self.assertEqual(list(self.output.iterdir()),[])

for name in base.HlsTests.__dict__:
 if name.startswith('test_') and name not in DirectTests.__dict__:setattr(DirectTests,name,None)

if __name__=='__main__':unittest.main(verbosity=2)
