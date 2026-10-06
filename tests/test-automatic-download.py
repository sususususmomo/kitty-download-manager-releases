"""Real supervised probes and one real yt-dlp/FFmpeg transfer, local HTTP only."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

spec=importlib.util.spec_from_file_location('dashfixtures',Path(__file__).with_name('test-dash-download.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
import worker,host,hls,queue_store,download_planner

class AutomaticTests(fixture.DashTests):
 @classmethod
 def setUpClass(cls):
  super().setUpClass()
  cls.runtime_expired=False
  subprocess.run(['ffmpeg','-v','error','-i',str(cls.media/'normal.mp4'),'-vn','-c:a','copy',str(cls.media/'native.m4a')],check=True,timeout=15)
  subprocess.run(['ffmpeg','-v','error','-i',str(cls.media/'normal.mp4'),'-an','-c:v','copy',str(cls.media/'silent.mp4')],check=True,timeout=15)
 @classmethod
 def extra_response(cls,url,headers):
  path=urlsplit(url).path
  if path.startswith('/runtime/'):
   if cls.runtime_expired:return 403,'application/vnd.apple.mpegurl',b'Expired token'
   if path=='/runtime/master.m3u8':
    return 200,'application/vnd.apple.mpegurl',b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=200000,RESOLUTION=1920x1080,CODECS="avc1.42e01f,mp4a.40.2"\nhigh/index.m3u8\n'
   file=cls.media/path.removeprefix('/runtime/')
   if file.is_file():return 200,'application/vnd.apple.mpegurl' if file.suffix=='.m3u8' else 'video/mp2t',file.read_bytes()
  if path=='/automatic-slow':
   time.sleep(2);return 200,'text/html',b'<html><title>Automatic local video</title><body>JS player</body></html>'
  if path=='/equal':return 200,'text/html',b'<html><title>Equal page</title><video src="/master.m3u8"></video></html>'
  if path=='/classic720':return 200,'text/html',b'<html><title>720p page</title><video src="/classic720.m3u8"></video></html>'
  if path=='/classic720.m3u8':return 200,'application/vnd.apple.mpegurl',b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100000,RESOLUTION=1280x720,CODECS="avc1.42e01f,mp4a.40.2"\nlow/index.m3u8\n'
  if path=='/native.m4a':return 200,'audio/mp4',(cls.media/'native.m4a').read_bytes()
  return super().extra_response(url,headers)
 def setUp(self):
  super().setUp();type(self).runtime_expired=False;self.transfers=[]
  original=fixture.base.yt_dlp.YoutubeDL.process_ie_result
  def transfer(ydl,data,*args,**kwargs):
   if kwargs.get('download',True):self.transfers.append(data.get('id'))
   return original(ydl,data,*args,**kwargs)
  self.stack.enter_context(patch.object(fixture.base.yt_dlp.YoutubeDL,'process_ie_result',transfer))
 def candidate_source(self,kind='hls',path='/master.m3u8',page='/normal'):
  return hls.validate_source(dict(type=kind,url=self.base+path,page_url=self.base+page,tab_id=1,
    timestamp=time.time(),headers={},title='Automatic local video',manifest_kind='master'))
 def automatic(self,sources=None,url='/normal',mode='1080'):
  active=dict(id='fixture',url=self.base+url,mode=mode,output_dir=str(self.output),status='starting',
    started_at=time.time(),youtube_auth=False,automatic=True,media_fallbacks=sources or [])
  queue_store.atomic_json(worker.QUEUE_FILE,{**queue_store.default_state(),'active':active})
  with patch.object(sys,'argv',['worker.py','fixture']):code=worker.main()
  state=worker.get_state();self.assertIsNone(state['active']);self.assertEqual(len(state['history']),1)
  return code,state['history'][0]
 def check_finished(self,sources,kind,url='/normal',mode='1080'):
  code,entry=self.automatic(sources,url,mode);self.assertEqual(code,0,entry);self.assertEqual(entry['status'],'finished',entry)
  self.assertEqual(entry['selected_source_type'],kind);self.assertEqual(len(self.transfers),1)
  streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',entry['filepath']],timeout=15))['streams']
  self.assertTrue(any(s['codec_type']=='audio' for s in streams));return entry,streams
 def test_hls_1080_beats_classic_720_one_transfer(self):
  entry,streams=self.check_finished([self.candidate_source(page='/classic720')],'hls',url='/classic720')
  self.assertEqual(next(s['height'] for s in streams if s['codec_type']=='video'),1080)
  self.assertEqual(entry['url'],self.base+'/classic720');self.assertEqual(entry['media_source']['url'],self.base+'/master.m3u8')
 def test_classic_wins_equal_720(self):
  self.check_finished([self.candidate_source(page='/equal')],'ytdlp',url='/equal',mode='720')
 def test_failed_classic_hls_no_red_error(self):
  self.check_finished([self.candidate_source(page='/unsupported')],'hls',url='/unsupported')
 def test_failed_classic_dash_merge(self):
  entry,streams=self.check_finished([self.candidate_source('dash','/dashmulti/manifest.mpd','/unsupported')],'dash',url='/unsupported')
  self.assertEqual(next(s['height'] for s in streams if s['codec_type']=='video'),1080)
 def test_failed_classic_direct_mp4(self):
  self.check_finished([self.candidate_source('direct_video','/normal.mp4','/unsupported')],'direct_video',url='/unsupported')
 def test_silent_video_preserves_historical_video_mode(self):
  code,entry=self.automatic([self.candidate_source('direct_video','/silent.mp4','/unsupported')],url='/unsupported')
  self.assertEqual(code,0,entry);self.assertEqual(entry['status'],'finished');self.assertEqual(len(self.transfers),1)
  streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',entry['filepath']],timeout=15))['streams']
  self.assertEqual({s['codec_type'] for s in streams},{'video'})
 def test_native_audio_avoids_video_transfer(self):
  entry,streams=self.check_finished([self.candidate_source('direct_audio','/native.m4a')],'direct_audio',mode='audio')
  self.assertEqual({s['codec_type'] for s in streams},{'audio'})
  self.assertEqual(entry['audio_original_codec'] if 'audio_original_codec' in entry else Path(entry['filepath']).suffix,'.m4a')
 def test_audio_lossless_extract_from_video(self):
  entry,streams=self.check_finished([],'ytdlp',mode='audio');self.assertEqual({s['codec_type'] for s in streams},{'audio'})
 def test_token_expires_after_probe_fallback_same_history(self):
  original=worker.resolve_candidates
  def expire(*args,**kwargs):
   result=original(*args,**kwargs);type(self).runtime_expired=True;return result
  self.stack.enter_context(patch.object(worker,'resolve_candidates',expire))
  code,entry=self.automatic([self.candidate_source(path='/runtime/master.m3u8')])
  self.assertEqual(code,0,entry);self.assertEqual(entry['status'],'finished');self.assertEqual(entry['selected_source_type'],'ytdlp')
  self.assertEqual(len(self.transfers),2);self.assertTrue(any('fallback to next candidate: ytdlp'==line for line in self.logs))
  self.assertTrue(any('candidate score:' in line for line in self.logs));self.assertNotIn('Expired token','\n'.join(self.logs))
  self.assertEqual(len(list(self.output.iterdir())),1)
 def test_cancel_stops_planner_without_transfer(self):
  original=worker.resolve_candidates
  def cancel(*args,**kwargs):worker.cancel_requested=True;return original(*args,**kwargs)
  self.stack.enter_context(patch.object(worker,'resolve_candidates',cancel))
  code,entry=self.automatic([self.candidate_source()]);self.assertEqual(code,0);self.assertEqual(entry['status'],'cancelled');self.assertEqual(self.transfers,[])
 def test_real_slow_page_timeout_keeps_ready_hls(self):
  def bounded(options,job,control,log):
   return download_planner.resolve_candidates(options,job,control,log,page_timeout=.4,network_timeout=5,ready_grace=1)
  self.stack.enter_context(patch.object(worker,'resolve_candidates',bounded))
  started=time.monotonic()
  self.check_finished([self.candidate_source(page='/automatic-slow')],'hls',url='/automatic-slow')
  self.assertLess(time.monotonic()-started,4)
  self.assertIn('resolver timeout: ytdlp',self.logs)
 def test_real_transfer_cancel_has_no_fallback_or_partial(self):
  type(self).slow=True
  def cancel():
   self.segment_seen.wait(10);worker.CONTROL_DIR.mkdir(exist_ok=True)
   queue_store.atomic_json(worker.CONTROL_DIR/'fixture.json',{'action':'cancel'});os.kill(os.getpid(),signal.SIGTERM)
  thread=threading.Thread(target=cancel,daemon=True);thread.start()
  code,entry=self.automatic([self.candidate_source()]);thread.join(2)
  self.assertEqual(code,0);self.assertEqual(entry['status'],'cancelled');self.assertEqual(len(self.transfers),1)
  self.assertEqual(list(self.output.iterdir()),[]);self.assertFalse(any('fallback to next candidate' in line for line in self.logs))
 def test_disk_failure_does_not_try_other_candidate(self):
  def failure(*args,**kwargs):self.transfers.append('disk');raise OSError(28,'No space left on device')
  self.stack.enter_context(patch.object(fixture.base.yt_dlp.YoutubeDL,'process_ie_result',failure))
  code,entry=self.automatic([self.candidate_source()]);self.assertEqual(code,1);self.assertEqual(entry['error_code'],'disk_full');self.assertEqual(self.transfers,['disk'])
 def test_paused_queue_and_history_destination(self):
  for attr in ('QUEUE_FILE','LOCK_FILE','CONTROL_DIR'):self.stack.enter_context(patch.object(host,attr,getattr(worker,attr)))
  self.stack.enter_context(patch.object(host,'spawn_active_job',lambda *args:None))
  self.stack.enter_context(patch.object(host,'get_output_dir',lambda:self.output))
  self.stack.enter_context(patch.object(host,'WORKER',Path(worker.__file__)))
  queue_store.atomic_json(worker.QUEUE_FILE,{**queue_store.default_state(),'queue_paused':True})
  with patch.object(host,'spawn_metadata',wraps=host.spawn_metadata) as metadata:
   result=host.enqueue(self.base+'/normal','1080',automatic=True,media_fallbacks=[self.candidate_source()]);self.assertTrue(result['ok'],result)
  state=worker.get_state();self.assertIsNone(state['active']);self.assertEqual(len(state['queue']),1)
  self.assertEqual(state['queue'][0]['download_request']['maxHeight'],1080);self.assertFalse(state['queue'][0].get('metadata_pid'))
  state['queue_paused']=False;queue_store.atomic_json(worker.QUEUE_FILE,state);job_id=host.start_next_if_idle()
  with patch.object(sys,'argv',['worker.py',job_id]):self.assertEqual(worker.main(),0)
  state=worker.get_state();self.assertEqual(len(state['history']),1);self.assertEqual(len(self.transfers),1)
  self.assertEqual(Path(state['history'][0]['filepath']).parent,self.output)
  self.assertEqual(state['history'][0]['selected_source_type'],'hls')

for name in dir(fixture.DashTests):
 if name.startswith('test_') and name not in AutomaticTests.__dict__:setattr(AutomaticTests,name,None)

if __name__=='__main__':unittest.main(verbosity=2)
