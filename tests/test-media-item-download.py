"""Local gallery fixtures and real worker proof for item-scoped Automatic."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
import yt_dlp

spec=importlib.util.spec_from_file_location('automaticfixtures',Path(__file__).with_name('test-automatic-download.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
import host,media_item,queue_store,worker,download_planner,hls

class MediaItemTests(fixture.AutomaticTests):
 @unittest.skipUnless(shutil.which('node'),'Node is required for the frontend/native round trip')
 def test_pill_frontend_native_transfer_and_completion(self):
  root=Path(__file__).resolve().parents[1]
  script="""
   const {fixture,player}=require('./tests/test-pill-download.js');
   (async()=>{const f=fixture(process.argv[1]);
    f.setItems([player('a',process.argv[2],'First video'),player('b',process.argv[3],'Selected via pill')]);
    const ui={url:'moz-extension://kitty/popup.html'};
    const items=(await f.receive({type:'kitty-media-items',tabId:1},ui)).items;
    await f.receive({type:'kitty-download-settings',tabId:1,change:{itemId:items[1].id}},ui);
    const r=await f.receive({type:'kitty-add-download'});
    if(!r.ok)throw new Error(JSON.stringify(r));console.log(JSON.stringify(f.downloads().at(-1)));
   })().catch(e=>{console.error(e);process.exitCode=1});
  """
  payload=json.loads(subprocess.check_output(['node','-e',script,self.base+'/gallery',self.base+'/a_1080p.mp4',self.base+'/b_360p.mp4'],cwd=root,timeout=15))
  for attr in ('QUEUE_FILE','LOCK_FILE','CONTROL_DIR'):self.stack.enter_context(patch.object(host,attr,getattr(worker,attr)))
  self.stack.enter_context(patch.object(host,'spawn_active_job',lambda *args:None))
  self.stack.enter_context(patch.object(host,'get_output_dir',lambda:self.output))
  self.stack.enter_context(patch.object(host,'WORKER',Path(worker.__file__)))
  response=host.enqueue(**{key:value for key,value in payload.items() if key not in ('action','client')})
  self.assertTrue(response['ok'],response)
  with patch.object(fixture.sys,'argv',['worker.py',response['job_id']]):self.assertEqual(worker.main(),0)
  state=worker.get_state();entry=state['history'][0]
  self.assertEqual(entry['status'],'finished');self.assertEqual(entry['title'],'Selected via pill')
  self.assertEqual(entry['download_plan']['downloadUrls'],[self.base+'/b_360p.mp4']);self.assertEqual(len(self.transfers),1)
  streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',entry['filepath']],timeout=15))['streams']
  self.assertEqual(next(s['height'] for s in streams if s['codec_type']=='video'),360)
  self.assertTrue(any(s['codec_type']=='audio' for s in streams))
  ui="""
   const {fixture}=require('./tests/test-pill-ui.js'),fs=require('node:fs');
   (async()=>{const data=JSON.parse(fs.readFileSync(0,'utf8')),f=await fixture('cat','fr',process.argv[1]);
    f.player('video',process.argv[2]);
    f.setHandler(async m=>m.type==='kitty-add-download'?data.response:{ok:true,state:data.state});
    f.nodes.get('download').dispatch('click');await new Promise(r=>setImmediate(r));await f.poll();
    if(f.nodes.get('pill').dataset.state!=='finished')throw new Error('Native completion not reflected in pill');
    console.log('Native completion reflected in pill');
   })().catch(e=>{console.error(e);process.exitCode=1});
  """
  completed=subprocess.run(['node','-e',ui,self.base+'/gallery',self.base+'/b_360p.mp4'],cwd=root,input=json.dumps({'response':response,'state':state}),text=True,capture_output=True,timeout=15)
  self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
 @classmethod
 def setUpClass(cls):
  super().setUpClass()
  (cls.media/'a_1080p.mp4').write_bytes((cls.media/'clip-high.mp4').read_bytes()) if (cls.media/'clip-high.mp4').exists() else subprocess.run(['ffmpeg','-v','error','-i',str(cls.media/'high/index.m3u8'),'-c','copy',str(cls.media/'a_1080p.mp4')],check=True,timeout=20)
  subprocess.run(['ffmpeg','-v','error','-i',str(cls.media/'normal.mp4'),'-c:v','libvpx-vp9','-threads','1','-deadline','realtime','-cpu-used','8','-c:a','libopus',str(cls.media/'a_720p.webm')],check=True,timeout=20)
  subprocess.run(['ffmpeg','-v','error','-i',str(cls.media/'normal.mp4'),'-vf','scale=640:360','-c:v','libx264','-threads','1','-preset','ultrafast','-c:a','copy',str(cls.media/'b_360p.mp4')],check=True,timeout=20)
  subprocess.run(['ffmpeg','-v','error','-i',str(cls.media/'normal.mp4'),'-frames:v','1','-threads','1',str(cls.media/'poster.png')],check=True,timeout=15)
  cls.png=(cls.media/'poster.png').read_bytes()
 @classmethod
 def extra_response(cls,url,headers):
  path=urlsplit(url).path
  if path=='/gallery':
   body='''<!doctype html><html><head><meta charset="utf-8"><title>Wikimedia gallery fixture</title></head><body>
    <div class="gallerybox"><div class="thumb"><video id="a" resource="/wiki/File:Film_A.webm" controls preload="metadata" poster="/poster-a.png"><source src="/a_720p.webm" type="video/webm"><source src="/a_1080p.mp4" type="video/mp4"></video></div><div class="gallerytext">Éruption du volcan — premier film</div></div>
    <div class="gallerybox"><div class="thumb"><video id="b" resource="/wiki/File:Film_B.webm" controls preload="metadata" src="/b_360p.mp4" poster="/poster-b.png"></video></div><div class="gallerytext">Le second film : océan</div></div>
    <a href="https://www.youtube.com/watch?v=Recommended">Simple lien ignoré</a></body></html>'''
   return 200,'text/html',body.encode()
  if path.startswith('/poster-'):return 200,'image/png',cls.png
  if path=='/wiki/File:Film_A.webm':
   # Wikipedia File pages have a main player and another duplicate preview.
   # Generic extraction interprets them as a collection, not one logical file.
   return 200,'text/html',b'<html><title>File A</title><video src="/a_720p.webm"></video><video src="/a_720p.webm"></video></html>'
  if path=='/file-b':return 200,'text/html',b'<html><title>Only B</title><video src="/b_360p.mp4"></video></html>'
  if path in ('/a_720p.webm','/a_1080p.mp4','/b_360p.mp4'):
   return 200,'video/webm' if path.endswith('.webm') else 'video/mp4',(cls.media/path.lstrip('/')).read_bytes()
  return super().extra_response(url,headers)
 def item(self,title='Caption A'):
  return {'id':'item:fixture:a','page_url':self.base+'/gallery','title':title,'title_source':'caption','thumbnail':self.base+'/poster-a.png','explicit_sources':True}
 def test_provider_audio_uses_extractor_title_and_real_http_transfer(self):
  page='https://soundcloud.com/artist/track'
  source={**self.candidate_source('direct_audio','/native.m4a','/gallery'),'page_url':page,'title':'Média'}
  real_extract=worker.extract_metadata
  def extract(opts,job,**kwargs):
   if job['url']==page:
    return {'id':'track','title':'Actual song title','formats':[{'format_id':'native','url':self.base+'/native.m4a',
      'ext':'m4a','vcodec':'none','acodec':'aac','abr':128}]},None
   return real_extract(opts,job,**kwargs)
  resolve=download_planner.resolve_candidates
  def resolver(opts,job,*args,**kwargs):
   return resolve(opts,job,*args,extractor=extract,**kwargs)
  active=dict(id='fixture',url=page,source_page_url=page,mode='audio',output_dir=str(self.output),status='starting',
   started_at=time.time(),youtube_auth=False,automatic=True,media_fallbacks=[source],
   media_item={'id':'song','page_url':page,'title':'Média','title_source':'aria-label','prefer_extractor':True})
  queue_store.atomic_json(worker.QUEUE_FILE,{**queue_store.default_state(),'active':active})
  with patch.object(worker,'resolve_candidates',resolver),patch.object(fixture.sys,'argv',['worker.py','fixture']):
   self.assertEqual(worker.main(),0)
  entry=worker.get_state()['history'][0]
  self.assertEqual(entry['title'],'Actual song title');self.assertEqual(entry['download_plan']['sourceType'],'ytdlp')
  self.assertIn('Actual song title',Path(entry['filepath']).name)
  streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',entry['filepath']]))['streams']
  self.assertEqual({s['codec_type'] for s in streams},{'audio'})
 def run_item(self,sources,url='/wiki/File:Film_A.webm',item=None,mode='best',**preferences):
  active=dict(id='fixture',url=self.base+url,source_page_url=self.base+'/gallery',mode=mode,output_dir=str(self.output),status='starting',started_at=time.time(),youtube_auth=False,automatic=True,media_item=item or self.item(),media_fallbacks=sources,**preferences)
  queue_store.atomic_json(worker.QUEUE_FILE,{**queue_store.default_state(),'active':active})
  with patch.object(fixture.sys,'argv',['worker.py','fixture']):self.assertEqual(worker.main(),0)
  entry=worker.get_state()['history'][0];self.assertEqual(entry['status'],'finished',entry)
  streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',entry['filepath']],timeout=15))['streams']
  return entry,streams
 def test_wikipedia_duplicate_file_page_reproduces_old_error(self):
  with self.assertRaises(download_planner.MetadataError) as error:
   download_planner.resolve_candidates({},dict(url=self.base+'/wiki/File:Film_A.webm',mode='best'))
  self.assertEqual(error.exception.code,'format_unavailable');self.assertEqual(self.transfers,[])
 def test_selected_a_best_uses_own_mp4_webm_not_file_page(self):
  sources=[self.candidate_source('direct_video',path,'/gallery') for path in ('/a_720p.webm','/a_1080p.mp4')]
  self.stack.enter_context(patch.dict(os.environ,{'KITTY_TRACE_MEDIA_ITEMS':'1'}))
  entry,streams=self.run_item(sources)
  self.assertEqual(next(s['height'] for s in streams if s['codec_type']=='video'),1080)
  self.assertEqual(entry['title'],'Caption A');self.assertEqual(len(self.transfers),1)
  plan=entry['download_plan'];self.assertEqual(plan['mediaItemId'],self.item()['id']);self.assertEqual(plan['sourceType'],'direct_video')
  self.assertEqual(plan['downloadUrls'],[self.base+'/a_1080p.mp4']);self.assertTrue(plan['formatSelector'])
  self.assertFalse(any(p=='/wiki/File:Film_A.webm' for p,_ in self.requests))
  for event in ('selected:', 'candidates:', 'selected candidate:', 'download:', 'format selector generated:'):
   self.assertTrue(any('mediaItem trace '+event in line for line in self.logs),event)
 def test_selected_b_is_a_different_file_and_plan(self):
  item={**self.item('Caption B'),'id':'item:fixture:b'}
  entry,streams=self.run_item([self.candidate_source('direct_video','/b_360p.mp4','/gallery')],item=item)
  self.assertEqual(next(s['height'] for s in streams if s['codec_type']=='video'),360)
  self.assertEqual(entry['title'],'Caption B');self.assertEqual(entry['download_plan']['downloadUrls'],[self.base+'/b_360p.mp4']);self.assertEqual(len(self.transfers),1)
 def test_unresolved_item_resolves_own_file_before_plan(self):
  item={**self.item('Caption B'),'id':'item:fixture:b','explicit_sources':False}
  entry,streams=self.run_item([],url='/file-b',item=item)
  self.assertEqual(entry['download_plan']['sourceUrl'],self.base+'/file-b');self.assertEqual(entry['download_plan']['downloadUrls'],[self.base+'/b_360p.mp4'])
  self.assertEqual(next(s['height'] for s in streams if s['codec_type']=='video'),360)
 def test_common_request_failed_network_uses_only_selected_file_extractor(self):
  item={**self.item('Caption B'),'id':'item:fixture:b'}
  entry,streams=self.run_item([self.candidate_source('direct_video','/missing.mp4','/gallery')],
      url='/file-b',item=item,track_policy='prefer_available',track_selection={'subtitleLanguages':['de']})
  self.assertEqual(entry['download_plan']['sourceType'],'ytdlp')
  self.assertEqual(entry['download_plan']['downloadUrls'],[self.base+'/b_360p.mp4'])
  self.assertEqual(next(s['height'] for s in streams if s['codec_type']=='video'),360)
  self.assertEqual(entry['download_plan']['subtitleLanguages'],[])
  self.assertEqual(len(self.transfers),1)
 def test_item_hls_plan_uses_existing_downloader(self):
  entry,streams=self.run_item([self.candidate_source('hls','/master.m3u8','/gallery')])
  self.assertEqual(entry['download_plan']['sourceType'],'hls');self.assertEqual(next(s['height'] for s in streams if s['codec_type']=='video'),1080)
  self.assertTrue(any(s['codec_type']=='audio' for s in streams));self.assertEqual(len(self.transfers),1)
 def test_best_webm_with_poster_finishes_without_unsupported_cover_embedding(self):
  entry,streams=self.run_item([self.candidate_source('direct_video','/a_720p.webm','/gallery')])
  self.assertEqual(Path(entry['filepath']).suffix,'.webm');self.assertEqual(next(s['height'] for s in streams if s['codec_type']=='video'),720)
  self.assertTrue(any(s['codec_type']=='audio' for s in streams));self.assertEqual(entry['download_plan']['downloadUrls'],[self.base+'/a_720p.webm'])
 def test_item_webm_audio_modes_keep_existing_conversion_and_cover_pipeline(self):
  for mode in ('audio','mp3'):
   with self.subTest(mode=mode):
    entry,streams=self.run_item([self.candidate_source('direct_video','/a_720p.webm','/gallery')],mode=mode)
    audio=[s for s in streams if s['codec_type']=='audio'];self.assertEqual(len(audio),1)
    self.assertFalse(any(s['codec_type']=='video' and not s.get('disposition',{}).get('attached_pic') for s in streams))
    self.assertEqual(audio[0]['codec_name'],'opus' if mode=='audio' else 'mp3')
 def test_item_dash_plan_merges_own_video_audio(self):
  entry,streams=self.run_item([self.candidate_source('dash','/dashmulti/manifest.mpd','/gallery')])
  self.assertEqual(entry['download_plan']['sourceType'],'dash');self.assertEqual(len(entry['download_plan']['downloadUrls']),2)
  self.assertEqual(next(s['height'] for s in streams if s['codec_type']=='video'),1080);self.assertTrue(any(s['codec_type']=='audio' for s in streams));self.assertEqual(len(self.transfers),1)
 def test_best_plan_silent_high_variant_does_not_choose_lower_muxed_format(self):
  data={'id':'one','title':'One','formats':[
   {'format_id':'low','url':self.base+'/b_360p.mp4','vcodec':'h264','acodec':'aac','height':360,'ext':'mp4'},
   {'format_id':'high','url':self.base+'/a_1080p.mp4','vcodec':'h264','acodec':'none','height':1080,'ext':'mp4'}]}
  job={'url':self.base+'/gallery','mode':'best','media_item':self.item()}
  candidate=download_planner.candidate_from_info(data,None,job,download_planner.DownloadRequest.from_mode('best'))
  plan=download_planner.build_item_plan(candidate,job,worker.build_opts('best',lambda _:None,self.output))
  self.assertEqual(plan.formatSelector,'high');self.assertEqual(plan.downloadUrls,(self.base+'/a_1080p.mp4',));self.assertEqual(self.transfers,[])
  # A transfer context carrying the old global selector cannot undo the plan.
  with yt_dlp.YoutubeDL(dict(quiet=True,format=plan.select_formats)) as ydl:
   chosen=ydl.process_ie_result(data,download=False)
  self.assertEqual(chosen['format_id'],'high');self.assertEqual(chosen['url'],self.base+'/a_1080p.mp4')
 def test_batch_queue_builds_one_independent_plan_per_item(self):
  for attr in ('QUEUE_FILE','LOCK_FILE','CONTROL_DIR'):self.stack.enter_context(patch.object(host,attr,getattr(worker,attr)))
  self.stack.enter_context(patch.object(host,'spawn_active_job',lambda *args:None))
  self.stack.enter_context(patch.object(host,'get_output_dir',lambda:self.output))
  self.stack.enter_context(patch.object(host,'WORKER',Path(worker.__file__)))
  queue_store.atomic_json(worker.QUEUE_FILE,{**queue_store.default_state(),'queue_paused':True})
  for key,path in [('a','/a_1080p.mp4'),('b','/b_360p.mp4')]:
   item={**self.item('Caption '+key.upper()),'id':'item:fixture:'+key}
   source={**self.candidate_source('direct_video',path,'/gallery'),'media_item_id':item['id']}
   self.assertTrue(host.enqueue(self.base+path,'best',automatic=True,media_item=item,media_fallbacks=[source])['ok'])
  state=worker.get_state();self.assertEqual(len(state['queue']),2);state['queue_paused']=False;queue_store.atomic_json(worker.QUEUE_FILE,state)
  for _ in range(2):
   job_id=host.start_next_if_idle()
   with patch.object(fixture.sys,'argv',['worker.py',job_id]):self.assertEqual(worker.main(),0)
  history=worker.get_state()['history'];self.assertEqual(len(history),2);self.assertEqual(len(self.transfers),2)
  self.assertEqual({j['download_plan']['mediaItemId'] for j in history},{'item:fixture:a','item:fixture:b'})
  self.assertEqual({tuple(j['download_plan']['downloadUrls']) for j in history},{(self.base+'/a_1080p.mp4',),(self.base+'/b_360p.mp4',)})
 def test_host_rejects_cross_item_source_and_normal_limit_unchanged(self):
  own=self.item();other={**self.candidate_source('direct_video','/b_360p.mp4','/gallery'),'media_item_id':'item:fixture:b'}
  with self.assertRaises(ValueError):host.enqueue(self.base+'/gallery','best',automatic=True,media_item=own,media_fallbacks=[other])
  with self.assertRaises(ValueError):hls.validate_fallbacks([other]*4)
 def test_item_alternate_direct_quality_not_filtered_by_primary(self):
  active=dict(id='fixture',url=self.base+'/a_720p.webm',source_page_url=self.base+'/gallery',mode='1080',output_dir=str(self.output),status='starting',started_at=time.time(),youtube_auth=False,automatic=True,media_item=self.item(),media_fallbacks=[self.candidate_source('direct_video','/a_1080p.mp4','/gallery')])
  queue_store.atomic_json(worker.QUEUE_FILE,{**queue_store.default_state(),'active':active})
  with patch.object(fixture.sys,'argv',['worker.py','fixture']):self.assertEqual(worker.main(),0)
  entry=worker.get_state()['history'][0];self.assertEqual(entry['status'],'finished');self.assertEqual(entry['title'],'Caption A');self.assertEqual(len(self.transfers),1)
  streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',entry['filepath']],timeout=15))['streams']
  self.assertEqual(next(s['height'] for s in streams if s['codec_type']=='video'),1080)
  self.assertTrue(any(s['codec_type']=='audio' for s in streams));self.assertEqual(Path(entry['filepath']).stem,'Caption A')
 def test_display_metadata_priority_and_validation(self):
  info={'title':'Extractor title'};media_item.apply_item_metadata(info,{**self.item(),'title_source':'filename'});self.assertEqual(info['title'],'Extractor title')
  media_item.apply_item_metadata(info,self.item());self.assertEqual(info['title'],'Caption A')
  with self.assertRaises(ValueError):media_item.validate_item({**self.item(),'thumbnail':'javascript:alert(1)'})
  with self.assertRaises(ValueError):media_item.validate_item({**self.item(),'page_url':'blob:invalid'})

if __name__=='__main__':
 # Only the new tests; inherited Automatic cases run in their existing suite.
 suite=unittest.TestSuite(MediaItemTests(name) for name in sorted(MediaItemTests.__dict__) if name.startswith('test_'))
 raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
