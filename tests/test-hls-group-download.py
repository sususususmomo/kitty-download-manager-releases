"""Separate-audio Vimeo-like HLS, using the existing real worker fixtures."""
import importlib.util
import json
from pathlib import Path
import os
import signal
import subprocess
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

spec=importlib.util.spec_from_file_location('hlsfixtures',Path(__file__).with_name('test-hls-download.py'))
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
import host,worker,queue_store

class HlsGroupTests(base.HlsTests):
 @classmethod
 def setUpClass(cls):
  super().setUpClass()
  folder=cls.media/'vimeo';folder.mkdir()
  for height in (360,720,1080):
   target=folder/'video'/str(height);target.mkdir(parents=True)
   subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'color=c=green:s={height*16//9}x{height}:r=10',
    '-t','2','-an','-c:v','libx264','-threads','1','-preset','ultrafast','-g','10','-sc_threshold','0',
    '-f','hls','-hls_time','1','-hls_list_size','0','-hls_segment_type','fmp4','-hls_fmp4_init_filename','init.mp4',
    '-hls_segment_filename',(target/'seg%03d.m4s').as_posix(),(target/'media.m3u8').as_posix()],check=True,timeout=25)
  target=folder/'audio';target.mkdir()
  subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=550:sample_rate=44100','-t','2',
   '-vn','-c:a','aac','-f','hls','-hls_time','1','-hls_list_size','0','-hls_segment_type','fmp4',
   '-hls_fmp4_init_filename','init.mp4','-hls_segment_filename',(target/'seg%03d.m4s').as_posix(),(target/'media.m3u8').as_posix()],check=True,timeout=25)
  target=folder/'subtitles';target.mkdir()
  (target/'media.m3u8').write_text('#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2,\ncaption.vtt\n#EXT-X-ENDLIST\n')
  (target/'caption.vtt').write_text('WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nKitty HLS fixture\n')
  cls.group_master='#EXTM3U\n#EXT-X-VERSION:7\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio-low",NAME="Original",LANGUAGE="en",DEFAULT=YES,AUTOSELECT=YES,URI="audio/media.m3u8?token=AUDIO%2BSECRET&asset=one"\n#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="French",LANGUAGE="fr",DEFAULT=NO,AUTOSELECT=YES,URI="subtitles/media.m3u8?token=SUB&asset=one"\n'
  for height,width,bandwidth in [(1080,1920,5000000),(720,1280,2500000),(360,640,900000)]:
   cls.group_master+=f'#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},AVERAGE-BANDWIDTH={bandwidth-10000},FRAME-RATE=10,RESOLUTION={width}x{height},CODECS="avc1.42e01f,mp4a.40.2",AUDIO="audio-low",SUBTITLES="subs"\nvideo/{height}/media.m3u8?token=VIDEO{height}&asset=one\n'
  (folder/'master.m3u8').write_text(cls.group_master)
  target=folder/'standalone';target.mkdir()
  subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','2',
   '-c:a','aac','-f','segment','-segment_time','1','-segment_format','adts','-segment_list_type','m3u8',
   '-segment_list',str(target/'audio.m3u8'),str(target/'audio%03d.aac')],check=True,timeout=25)
 @classmethod
 def extra_response(cls,url,headers):
  path=urlsplit(url).path
  if not path.startswith('/vimeo/'):return None
  file=cls.media/path.lstrip('/')
  if not file.is_file():return 404,'text/plain',b'Missing'
  if file.suffix in ('.m4s','.aac'):
   cls.segment_seen.set()
   if cls.slow:time.sleep(.6)
  mime={'.m3u8':'application/vnd.apple.mpegurl','.m4s':'video/mp4','.mp4':'video/mp4','.vtt':'text/vtt','.aac':'audio/aac'}[file.suffix]
  return 200,mime,file.read_bytes()
 def source(self,path='/vimeo/master.m3u8?token=MASTER%2BSECRET&asset=one',**kwargs):
  return super().source(path,**kwargs)
 def test_separate_audio_master_1080_and_history(self):
  entry,info=self.successful(source=self.source(),mode='1080')
  self.assertEqual(next(s['height'] for s in info['streams'] if s['codec_type']=='video'),1080)
  self.assertEqual(entry['media_source']['url'],self.source()['url'])
  self.assertEqual(entry['media_source']['headers'],{})
  self.assertTrue(any('/video/1080/media.m3u8?token=VIDEO1080&asset=one' in p for p,_ in self.requests))
  self.assertTrue(any('/audio/media.m3u8?token=AUDIO%2BSECRET&asset=one' in p for p,_ in self.requests))
  self.assertNotIn('SECRET','\n'.join(self.logs))
 def test_master_formats_and_subtitles(self):
  report=host.probe_hls(self.source());self.assertTrue(report['ok'],report)
  self.assertEqual(report['heights'],[360,720,1080]);self.assertTrue(report['separate_av'],report)
  with base.yt_dlp.YoutubeDL(base.hls.apply_options({'quiet':True,'skip_download':True,'socket_timeout':8},self.source())) as ydl:
   info=base.hls.extract_manifest(ydl,self.source())
  self.assertIn('fr',info['subtitles']);self.assertEqual(len(info['formats']),4)
 def test_master_720_and_page_fallback(self):
  entry,info=self.successful(url=self.base+'/unsupported',fallbacks=[self.source()],mode='720')
  self.assertEqual(next(s['height'] for s in info['streams'] if s['codec_type']=='video'),720)
  self.assertEqual(entry['media_used'],'hls');self.assertEqual(entry['media_source']['url'],self.source()['url'])
 def test_standalone_video_and_audio_downloadable(self):
  code,entry=self.job(source=self.source('/vimeo/video/720/media.m3u8'),mode='720');self.assertEqual(code,0,entry)
  streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',entry['filepath']],timeout=15))['streams']
  self.assertEqual({s['codec_type'] for s in streams},{'video'})
  code,entry=self.job(source=self.source('/vimeo/standalone/audio.m3u8'),mode='audio');self.assertEqual(code,0,entry)
  streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',entry['filepath']],timeout=15))['streams']
  self.assertEqual({s['codec_type'] for s in streams},{'audio'})
 def test_separate_audio_cancel_cleans_all_partials(self):
  type(self).slow=True
  def cancel():
   self.segment_seen.wait(10);worker.CONTROL_DIR.mkdir(exist_ok=True)
   queue_store.atomic_json(worker.CONTROL_DIR/'fixture.json',{'action':'cancel'});os.kill(os.getpid(),signal.SIGTERM)
  thread=threading.Thread(target=cancel,daemon=True);thread.start()
  code,entry=self.job(source=self.source());thread.join(2)
  self.assertEqual(code,0,entry);self.assertEqual(entry['status'],'cancelled');self.assertEqual(list(self.output.iterdir()),[])
 def test_master_queue_pause_resume_context(self):
  for attr in ('QUEUE_FILE','LOCK_FILE','CONTROL_DIR'):
   self.stack.enter_context(patch.object(host,attr,getattr(worker,attr)))
  self.stack.enter_context(patch.object(host,'spawn_metadata',lambda *a:None))
  self.stack.enter_context(patch.object(host,'spawn_active_job',lambda *a:None))
  self.stack.enter_context(patch.object(host,'get_output_dir',lambda:self.output))
  self.stack.enter_context(patch.object(host,'WORKER',Path(__file__).resolve().parents[1]/'native-host/worker.py'))
  queue_store.atomic_json(worker.QUEUE_FILE,{**queue_store.default_state(),'queue_paused':True})
  result=host.enqueue(self.source()['url'],'1080',media_source=self.source())
  self.assertTrue(result['ok'],result);state=host.snapshot();self.assertIsNone(state['active']);self.assertEqual(len(state['queue']),1)
  self.assertEqual(state['queue'][0]['media_source']['url'],self.source()['url'])
  state['queue_paused']=False;queue_store.atomic_json(worker.QUEUE_FILE,state)
  job_id=host.start_next_if_idle();self.assertEqual(job_id,result['job_id'])
  with patch.object(base.sys,'argv',['worker.py',job_id]):self.assertEqual(worker.main(),0)
  state=host.snapshot();self.assertIsNone(state['active']);self.assertEqual(state['queue'],[])
  self.assertEqual(state['history'][0]['status'],'finished');self.assertEqual(state['history'][0]['media_source']['url'],self.source()['url'])

# Keep this suite focused. Existing TS/fMP4/classic/error cases run unchanged
# from test-hls-download.py instead of being inherited and duplicated here.
for name in dir(base.HlsTests):
 if name.startswith('test_') and name not in HlsGroupTests.__dict__:setattr(HlsGroupTests,name,None)

if __name__=='__main__':unittest.main(verbosity=2)
