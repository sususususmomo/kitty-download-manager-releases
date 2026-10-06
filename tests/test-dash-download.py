"""Real DASH fixtures using the existing HLS fixture/worker/queue helpers."""
import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('hlsfixtures',Path(__file__).with_name('test-hls-download.py'))
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
import hls,host,worker,metadata_guard,queue_store


class DashTests(base.HlsTests):
 @classmethod
 def setUpClass(cls):
  super().setUpClass()
  for name,multi in [('dash',False),('dashmulti',True)]:
   folder=cls.media/name;folder.mkdir()
   cmd=['ffmpeg','-v','error','-f','lavfi','-i','color=c=red:s=1280x720:r=10',
    '-f','lavfi','-i','sine=frequency=500:sample_rate=44100','-t','2',
    '-map','0:v']
   if multi:cmd+=['-map','0:v']
   cmd+=['-map','1:a','-c:v','libx264','-threads','1','-preset','ultrafast',
    '-b:v:0','80k','-g','10','-sc_threshold','0','-c:a','aac']
   if multi:cmd+=['-filter:v:1','scale=1920:1080','-b:v:1','120k']
   cmd+=['-f','dash','-seg_duration','1','-use_template','1','-use_timeline','1',
    '-adaptation_sets','id=0,streams=v id=1,streams=a',(folder/'manifest.mpd').as_posix()]
   subprocess.run(cmd,check=True,timeout=30)
  cls.slow_manifest=threading.Event()
  import struct,zlib
  def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
  cls.cover=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0\x11\x22\x33\x11\x22\x33'*2))+chunk(b'IEND',b'')
 @classmethod
 def extra_response(cls,url,headers):
  path=urlsplit(url).path
  if not any(path.startswith(p) for p in ('/dash','/signed-dash','/protected-dash')):return None
  if path=='/dash-expired.mpd':return 410,'application/dash+xml',b'Gone'
  if path=='/dash-cover.png':return 200,'image/png',cls.cover
  if path=='/dash-image-page':return 200,'text/html',f'<html><head><title>Ordinary cover</title><meta property="og:image" content="{cls.base}/dash-cover.png"></head><body><video src="/normal.mp4" poster="{cls.base}/dash-cover.png"></video></body></html>'.encode()
  if path=='/dash-denied.mpd':return 403,'application/dash+xml',b'Forbidden'
  if path=='/dash-invalid.mpd':return 200,'application/dash+xml',b'<html>no MPD</html>'
  if path=='/dash-empty.mpd':return 200,'application/dash+xml',b'<MPD />'
  if path=='/dash-entity.mpd':return 200,'application/dash+xml',b'<!DOCTYPE MPD [<!ENTITY x "y">]><MPD />'
  if path=='/dash-utf16-entity.mpd':return 200,'application/dash+xml','<!DOCTYPE MPD [<!ENTITY x "y">]><MPD />'.encode('utf-16')
  if path=='/dash-drm.mpd':return 200,'application/dash+xml',b'<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period><AdaptationSet><ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"/><Representation id="v" /></AdaptationSet></Period></MPD>'
  if path=='/dash-slow.mpd':
   cls.slow_manifest.set();time.sleep(3);return 200,'application/dash+xml',(cls.media/'dash/manifest.mpd').read_bytes()
  if path.startswith('/protected-dash'):
   if headers.get('Referer')!=cls.base+'/page' or headers.get('Origin')!=cls.base or headers.get('User-Agent')!='Firefox DASH QA':return 403,'text/plain',b'Denied'
   path=path.removeprefix('/protected-dash')
  if path.startswith('/signed-dash'):
   if path.endswith('.mpd') and 'token=DO-NOT-LOG-DASH' not in url:return 403,'text/plain',b'Denied'
   path=path.removeprefix('/signed-dash')
  if path=='/dash-stream':return 200,'application/dash+xml',(cls.media/'dash/manifest.mpd').read_bytes().replace(b'initialization="init-',b'initialization="dash/init-').replace(b'media="chunk-',b'media="dash/chunk-')
  file=cls.media/path.lstrip('/')
  if not file.is_file():return 404,'text/plain',b'Missing'
  if file.suffix in ('.m4s','.mp4'):
   cls.segment_seen.set()
   if cls.slow:time.sleep(.6)
  return 200,'application/dash+xml' if file.suffix=='.mpd' else 'video/mp4',file.read_bytes()
 def source(self,path='/dash/manifest.mpd',headers=None,mime='application/dash+xml'):
  return hls.validate_source(dict(type='dash',url=self.base+path,page_url=self.base+'/page',tab_id=1,
      timestamp=time.time(),content_type=mime,headers=headers or {},title='DASH fixture'))
 def test_dash_simple_mpd(self):
  entry,streams=self.successful(source=self.source(),mode='720')
  self.assertEqual(entry['media_used'],'dash')
  self.assertEqual(next(s['height'] for s in streams['streams'] if s['codec_type']=='video'),720)
 def test_dash_separate_tracks_qualities_merge(self):
  source=self.source('/dashmulti/manifest.mpd')
  report=host.probe_hls(source)
  self.assertTrue(report['ok'],report);self.assertEqual(report['type'],'dash')
  self.assertEqual(report['heights'],[720,1080]);self.assertTrue(report['separate_av'])
  self.assertTrue(report['codecs'])
  self.assertTrue(report['has_audio']);self.assertTrue(report['has_video']);self.assertTrue(report['bitrates_kbps'])
  entry,streams=self.successful(source=source,mode='1080')
  self.assertEqual(next(s['height'] for s in streams['streams'] if s['codec_type']=='video'),1080)
  self.assertTrue(any('chunk-stream' in p for p,_ in self.requests))
 def test_dash_original_audio(self):
  result,entry=self.job(source=self.source(),mode='audio');self.assertEqual(result,0,entry)
  output=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',entry['filepath']],timeout=15))
  self.assertEqual({s['codec_type'] for s in output['streams']},{'audio'})
 def test_ordinary_image_with_supervised_metadata(self):
  result,entry=self.job(url=self.base+'/dash-image-page',mode='image')
  self.assertEqual(result,0,entry);self.assertEqual(Path(entry['filepath']).read_bytes(),self.cover)
 def test_dash_extensionless(self):self.successful(source=self.source('/dash-stream'),mode='720')
 def test_dash_headers_and_token(self):
  self.successful(source=self.source('/signed-dash/dash/manifest.mpd?token=DO-NOT-LOG-DASH&quality=720'),mode='720')
  self.assertNotIn('DO-NOT-LOG-DASH','\n'.join(self.logs))
  self.successful(source=self.source('/protected-dash/dash/manifest.mpd',{'Referer':self.base+'/page','Origin':self.base,'User-Agent':'Firefox DASH QA'}),mode='720')
 def test_dash_drm_invalid_unavailable(self):
  for path,code in [('/dash-missing.mpd','dash_unavailable'),('/dash-denied.mpd','dash_access_denied'),('/dash-expired.mpd','dash_expired'),('/dash-drm.mpd','dash_drm'),('/dash-invalid.mpd','dash_unavailable'),('/dash-entity.mpd','dash_unavailable'),('/dash-utf16-entity.mpd','dash_unavailable'),('/dash-empty.mpd','dash_no_formats')]:
   with self.subTest(path=path):
    report=host.probe_hls(self.source(path));self.assertFalse(report['ok']);self.assertEqual(report['code'],code,report)
  self.assertFalse(any('license' in p or '/key' in p for p,_ in self.requests))
 def test_dash_page_fallback(self):
  entry,_=self.successful(url=self.base+'/unsupported',fallbacks=[self.source()],mode='720')
  self.assertEqual(entry['media_used'],'dash');self.assertEqual(entry['url'],self.base+'/unsupported')
 def test_dash_metadata_timeout_and_next_job(self):
  original=worker.extract_metadata
  with patch.object(worker,'extract_metadata',lambda *a,**k:original(*a,**k,timeout=.6)):
   started=time.monotonic();code,entry=self.job(source=self.source('/dash-slow.mpd'))
   self.assertLess(time.monotonic()-started,2);self.assertEqual(code,1);self.assertEqual(entry['error_code'],'metadata_timeout',entry)
  self.successful(source=self.source(),mode='720')
 def test_dash_probe_timeout_keeps_raw_source(self):
  source=self.source('/dash-slow.mpd');before=dict(source)
  with patch.object(host,'PROBE_TIMEOUT',.6):report=host.probe_hls(source)
  self.assertEqual(report['code'],'metadata_timeout',report);self.assertEqual(source,before)
 def test_page_access_error_is_not_reclassified_as_dash(self):
  with self.assertRaises(metadata_guard.MetadataError) as caught:
   metadata_guard.extract_metadata({'quiet':True}, {'url':self.base+'/dash-denied.mpd','media_fallbacks':[self.source()]},timeout=10)
  self.assertEqual(caught.exception.code,'access_denied')
 def test_dash_duplicate_and_backend_restart(self):
  # A fresh Native Messaging process sees the same persistent queue/identity.
  import os,struct,tempfile
  with tempfile.TemporaryDirectory() as temp:
   env={**os.environ,'HOME':temp,'XDG_CACHE_HOME':temp+'/cache','XDG_CONFIG_HOME':temp+'/config'}
   installed=subprocess.run(['bash',str(ROOT/'install.sh')],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
   self.assertEqual(installed.returncode,0,installed.stderr)
   def request(message):
    body=json.dumps(message).encode();result=subprocess.run([sys.executable,str(ROOT/'native-host/host.py')],
      input=struct.pack('<I',len(body))+body,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,timeout=15)
    self.assertEqual(result.returncode,0,result.stderr);length=struct.unpack('<I',result.stdout[:4])[0]
    return json.loads(result.stdout[4:4+length])
   request({'action':'pause_queue'})
   first=request({'action':'download','url':self.source()['url'],'mode':'720','media_source':self.source()})
   self.assertTrue(first['ok'],first)
   second=request({'action':'download','url':self.source()['url'],'mode':'720','media_source':self.source()})
   self.assertEqual(second['code'],'already_queued',second)
   state=request({'action':'status'})['state'];self.assertEqual(len(state['queue']),1)
   self.assertEqual(state['queue'][0]['media_source']['type'],'dash')
 def test_dash_retry_preserves_detected_fallbacks(self):
  state=queue_store.default_state();state['history']=[{'id':'failed','status':'error','url':self.base+'/unsupported','mode':'720','media_fallbacks':[self.source()]}]
  with patch.object(host,'snapshot',lambda:state),patch.object(host,'enqueue',return_value={'ok':True}) as enqueue:
   self.assertTrue(host.retry_job('failed')['ok'])
   self.assertEqual(enqueue.call_args.kwargs['media_fallbacks'],state['history'][0]['media_fallbacks'])
 def test_dash_cancellation(self):
  self.slow_manifest.clear()
  def cancel():
   self.slow_manifest.wait(5);worker.CONTROL_DIR.mkdir(exist_ok=True)
   queue_store.atomic_json(worker.CONTROL_DIR/'fixture.json',{'action':'cancel'})
   import os
   os.kill(os.getpid(),signal.SIGTERM)
  thread=threading.Thread(target=cancel,daemon=True);thread.start()
  code,entry=self.job(source=self.source('/dash-slow.mpd'));thread.join(2)
  self.assertEqual(code,0,entry);self.assertEqual(entry['status'],'cancelled');self.assertEqual(list(self.output.iterdir()),[])
 def test_dash_cancel_during_media_transfer(self):
  base.HlsTests.test_cancel_cleans_partial(self)
  self.assertTrue(any('.m4s' in path for path,_ in self.requests),'Actual DASH transfer must start')

# The HLS suite is run separately, not duplicated by inheritance.
for name in base.HlsTests.__dict__:
 if name.startswith('test_') and name not in DashTests.__dict__:setattr(DashTests,name,None)

if __name__=='__main__':unittest.main(verbosity=2)
