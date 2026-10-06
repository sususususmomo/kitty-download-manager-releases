"""Direct catalogue -> automatic -> existing worker -> real files, local HTTP."""
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import sys
import threading
import time
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('directfixtures',Path(__file__).with_name('test-direct-download.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
import download_planner as planner
worker,queue_store=fixture.worker,fixture.queue_store

class DirectAutomaticTests(fixture.DirectTests):
 @classmethod
 def setUpClass(cls):
  super().setUpClass()
  for name,height in [('master',1080),('low-master',720)]:
   (cls.media/(name+'.m3u8')).write_text('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=200000,RESOLUTION='+('1920x1080' if height==1080 else '1280x720')+',CODECS="avc1.42e01f,mp4a.40.2"\n'+('high' if height==1080 else 'low')+'/index.m3u8\n')
 def setUp(self):
  super().setUp();self.transfers=[]
  original=fixture.base.yt_dlp.YoutubeDL.process_ie_result
  def transfer(ydl,data,*args,**kwargs):
   if kwargs.get('download',True):self.transfers.append(data.get('id'))
   return original(ydl,data,*args,**kwargs)
  self.stack.enter_context(patch.object(fixture.base.yt_dlp.YoutubeDL,'process_ie_result',transfer))
 def automatic(self,sources,mode='1080'):
  active=dict(id='fixture',url=self.base+'/unsupported',mode=mode,output_dir=str(self.output),status='starting',started_at=time.time(),youtube_auth=False,automatic=True,media_fallbacks=sources)
  queue_store.atomic_json(worker.QUEUE_FILE,{**queue_store.default_state(),'active':active})
  with patch.object(sys,'argv',['worker.py','fixture']):code=worker.main()
  state=worker.get_state();self.assertIsNone(state['active']);self.assertEqual(len(state['history']),1)
  return code,state['history'][0]
 def finished(self,sources,kind='direct_video',height=720,mode='1080'):
  code,entry=self.automatic(sources,mode);self.assertEqual(code,0,entry);self.assertEqual(entry['status'],'finished',entry)
  self.assertEqual(entry['selected_source_type'],kind);self.assertEqual(len(self.transfers),1)
  streams=json.loads(fixture.subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',entry['filepath']],timeout=15))['streams']
  self.assertTrue(any(s['codec_type']=='audio' for s in streams))
  if height:self.assertEqual(next(s['height'] for s in streams if s['codec_type']=='video'),height)
  for step in ('candidate accepted by resolver: '+kind,'selected candidate: '+kind,'download plan created: '+kind,'downloader started: '+kind):self.assertIn(step,self.logs)
  return entry
 def manifest(self,path):
  return fixture.hls.validate_source(dict(type='hls',url=self.base+path,page_url=self.base+'/unsupported',tab_id=1,timestamp=time.time(),headers={},title='HLS local',manifest_kind='master'))
 def test_mp4_with_audio_and_history(self):self.finished([self.source()])
 def test_webm(self):self.finished([self.source('/direct.webm',mime='video/webm')])
 def test_mime_without_extension(self):self.finished([self.source('/direct-stream?id=123',mime='video/mp4')])
 def test_browser_range_not_replayed(self):
  entry=self.finished([self.source(metadata={'content_range':'bytes 1000-1999/999999','request_range':'bytes=1000-1999','status_code':206})])
  self.assertEqual(entry['media_source']['url'],self.base+'/direct.mp4')
  self.assertTrue(all(h.get('Range')!='bytes=1000-1999' for _,h in self.requests))
 def test_headers_tokens(self):
  self.finished([self.source('/protected-direct/video.mp4?signed=1&token=DO-NOT-LOG-DIRECT',headers={'Referer':self.base+'/unsupported','Origin':self.base,'User-Agent':'Firefox Direct QA'})])
  self.assertNotIn('DO-NOT-LOG-DIRECT','\n'.join(self.logs))
 def test_direct_1080_beats_hls_720(self):self.finished([self.manifest('/low-master.m3u8'),self.source('/clip_1080p.mp4')],height=1080)
 def test_hls_1080_beats_direct_720(self):self.finished([self.source(),self.manifest('/master.m3u8')],kind='hls',height=1080)
 def test_audio_native(self):self.finished([self.source('/direct.m4a',mime='audio/mp4',kind='direct_audio')],kind='direct_audio',height=None,mode='audio')
 def test_page_timeout_direct_ready(self):
  original=planner.extract_metadata
  def extract(opts,job,check_control,timeout):
   if not job.get('media_source'):raise planner.MetadataError('metadata_timeout','Timed out')
   return original(opts,job,check_control=check_control,timeout=timeout)
  def resolve(options,job,control,log):return planner.resolve_candidates(options,job,control,log,extractor=extract)
  self.stack.enter_context(patch.object(worker,'resolve_candidates',resolve));self.finished([self.source()]);self.assertIn('resolver timeout: ytdlp',self.logs)
 def test_all_fail_one_error_no_transfer(self):
  code,entry=self.automatic([self.source('/direct-missing.mp4')]);self.assertEqual(code,1);self.assertEqual(entry['status'],'error');self.assertEqual(self.transfers,[])
 def test_cancel_direct_transfer(self):
  type(self).transfer_slow=True
  original=worker.resolve_candidates;ready=threading.Event()
  def resolve(*args,**kwargs):
   result=original(*args,**kwargs);self.transfer_seen.clear();ready.set();return result
  self.stack.enter_context(patch.object(worker,'resolve_candidates',resolve))
  def cancel():
   if not ready.wait(15) or not self.transfer_seen.wait(10):return
   worker.CONTROL_DIR.mkdir(exist_ok=True);queue_store.atomic_json(worker.CONTROL_DIR/'fixture.json',{'action':'cancel'});os.kill(os.getpid(),signal.SIGTERM)
  thread=threading.Thread(target=cancel,daemon=True);thread.start()
  code,entry=self.automatic([self.source('/direct-transfer.mp4')]);thread.join(2)
  self.assertEqual(code,0);self.assertEqual(entry['status'],'cancelled');self.assertEqual(len(self.transfers),1);self.assertEqual(list(self.output.iterdir()),[])
  self.assertFalse(any('fallback to next candidate' in line for line in self.logs))

for name in dir(fixture.DirectTests):
 if name.startswith('test_') and name not in DirectAutomaticTests.__dict__:setattr(DirectAutomaticTests,name,None)
if __name__=='__main__':unittest.main(verbosity=2)
