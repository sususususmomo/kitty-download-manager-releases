"""Real worker/FFmpeg transfers: language, native audio, captions and queue."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

def fixture(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

hls_fixture=fixture('test-hls-group-download')
dash_fixture=fixture('test-dash-download')
import host,worker,queue_store,hls
from request_context import youtube_dl

class TransferMixin:
    def run_tracks(self,mode='best',selection=None,page=False):
        source=self.source(self.track_path)
        active=dict(id='fixture',url=self.base+'/page' if page else source['url'],mode=mode,
            output_dir=str(self.output),status='starting',started_at=time.time(),youtube_auth=False,
            track_selection=selection or {},automatic=not page,
            source_page_url=self.base+'/page',media_item={'id':'item:tracks','title':'Track fixture','page_url':self.base+'/page'})
        active['media_fallbacks']=[{**source,'id':'tracks-source','media_item_id':'item:tracks'}]
        queue_store.atomic_json(worker.QUEUE_FILE,{**queue_store.default_state(),'active':active})
        # Native yt-dlp extractor metadata with the exact same real downloads.
        if page:
            with youtube_dl(hls.apply_options({'quiet':True,'skip_download':True},source)) as ydl:
                info=hls.extract_manifest(ydl,source)
            active.pop('media_fallbacks');active.pop('media_item');queue_store.atomic_json(worker.QUEUE_FILE,{**queue_store.default_state(),'active':active})
            self.stack.enter_context(patch.object(worker,'extract_metadata',lambda *a,**kw:(info,None)))
        with patch.object(sys,'argv',['worker.py','fixture']):code=worker.main()
        entry=worker.get_state()['history'][0]
        self.assertEqual(code,0,entry);self.assertEqual(entry['status'],'finished',entry)
        streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',entry['filepath']]))['streams']
        return entry,streams
    def track_language_video_subtitles(self):
        entry,streams=self.run_tracks(selection={'audioLanguage':'fr','subtitleLanguages':['fr']})
        self.assertEqual(entry['download_plan']['audioLanguage'],'fr')
        self.assertEqual(next(s['height'] for s in streams if s['codec_type']=='video'),1080)
        self.assertEqual({s['codec_type'] for s in streams},{'video','audio'})
        self.assertTrue(any('/french/' in p for p,_ in self.requests if p.endswith(('.m4s','.mp4'))))
        self.assertFalse(any('/english/' in p for p,_ in self.requests if p.endswith(('.m4s','.mp4'))))
        captions=list(self.output.glob('*.fr.vtt'));self.assertEqual(len(captions),1)
        self.assertIn('Kitty French caption',captions[0].read_text())
    def track_audio_original_no_video(self):
        entry,streams=self.run_tracks(mode='audio')
        self.assertEqual({s['codec_type'] for s in streams},{'audio'})
        self.assertEqual(streams[0]['codec_name'],'aac')
        self.assertEqual(entry['download_plan']['audioLanguage'],'en')
        self.assertFalse(any('/video/' in p and p.endswith(('.mp4','.m4s')) for p,_ in self.requests))
        self.assertFalse(any('/french/' in p and p.endswith(('.mp4','.m4s')) for p,_ in self.requests))
        self.assertFalse(list(self.output.glob('*.vtt')))
    def track_audio_language_no_video(self):
        entry,streams=self.run_tracks(mode='audio',selection={'audioLanguage':'fr'})
        self.assertEqual({s['codec_type'] for s in streams},{'audio'})
        self.assertEqual(entry['download_plan']['audioLanguage'],'fr')
        self.assertFalse(any('/video/' in p and p.endswith(('.mp4','.m4s')) for p,_ in self.requests))
    def track_ytdlp_metadata_path(self):
        entry,streams=self.run_tracks(mode='audio',selection={'audioLanguage':'fr','subtitleLanguages':['fr']},page=True)
        self.assertEqual(entry['download_plan']['sourceType'],'ytdlp')
        self.assertEqual(entry['download_plan']['audioLanguage'],'fr')
        self.assertEqual({s['codec_type'] for s in streams},{'audio'})
        self.assertTrue(list(self.output.glob('*.fr.vtt')))
    def track_probe_preserves_languages_and_source(self):
        source={**self.source(self.track_path),'id':'tracks-source'}
        report=host.probe_hls(source);self.assertTrue(report['ok'],report)
        self.assertEqual({t['language'] for t in report['audioTracks']},{'en','fr'})
        self.assertTrue(all(t['sourceId']=='tracks-source' for t in report['audioTracks']))
        self.assertEqual([t['language'] for t in report['subtitleTracks']],['fr'])
        self.assertTrue(next(t for t in report['audioTracks'] if t['language']=='en')['original'])
    def track_batch_queue_retains_independent_preferences_and_retry(self):
        for attr in ('QUEUE_FILE','LOCK_FILE','CONTROL_DIR'):self.stack.enter_context(patch.object(host,attr,getattr(worker,attr)))
        self.stack.enter_context(patch.object(host,'spawn_metadata',lambda *a:None))
        self.stack.enter_context(patch.object(host,'spawn_active_job',lambda *a:None))
        self.stack.enter_context(patch.object(host,'get_output_dir',lambda:self.output))
        self.stack.enter_context(patch.object(host,'WORKER',Path(worker.__file__)))
        queue_store.atomic_json(worker.QUEUE_FILE,{**queue_store.default_state(),'queue_paused':True})
        for index,lang in enumerate(('fr','en')):
            source={**self.source(self.track_path),'media_item_id':f'item:{index}'}
            result=host.enqueue(source['url'],'audio',automatic=True,media_fallbacks=[source],
                media_item={'id':f'item:{index}','title':f'Track {index}','page_url':source['page_url']},track_selection={'audioLanguage':lang})
            self.assertTrue(result['ok'],result)
        state=host.snapshot();self.assertEqual([j['track_selection']['audioLanguage'] for j in state['queue']],['fr','en'])
        previous={**state['queue'][0],'status':'error'};state['history']=[previous];state['queue']=[]
        queue_store.atomic_json(worker.QUEUE_FILE,state)
        self.assertTrue(host.retry_job(previous['id'])['ok'])
        self.assertEqual(host.snapshot()['queue'][0]['track_selection'],{'audioLanguage':'fr'})

class HlsTracks(TransferMixin,hls_fixture.HlsGroupTests):
    track_path='/vimeo/tracks.m3u8'
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        folder=cls.media/'vimeo'
        for name,freq in [('english',440),('french',880)]:
            target=folder/name;target.mkdir()
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency={freq}:sample_rate=44100','-t','2',
                '-vn','-c:a','aac','-f','hls','-hls_time','1','-hls_list_size','0','-hls_segment_type','fmp4',
                '-hls_fmp4_init_filename','init.mp4','-hls_segment_filename',str(target/'seg%03d.m4s'),str(target/'media.m3u8')],check=True,timeout=25)
        (folder/'subtitles/caption.vtt').write_text('WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nKitty French caption\n')
        master=cls.group_master.replace('audio/media.m3u8?token=AUDIO%2BSECRET&asset=one','english/media.m3u8')
        master=master.replace('#EXT-X-VERSION:7','#EXT-X-VERSION:7\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio-low",NAME="French",LANGUAGE="fr",DEFAULT=NO,AUTOSELECT=YES,URI="french/media.m3u8"')
        (folder/'tracks.m3u8').write_text(master)

class DashTracks(TransferMixin,dash_fixture.DashTests):
    track_path='/dashtracks/manifest.mpd'
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        folder=cls.media/'dashtracks';folder.mkdir()
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=green:s=1920x1080:r=10',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-f','lavfi','-i','sine=frequency=880:sample_rate=44100',
            '-t','2','-map','0:v','-map','1:a','-map','2:a','-c:v','libx264','-threads','1','-preset','ultrafast','-g','10',
            '-c:a','aac','-metadata:s:a:0','language=en','-metadata:s:a:1','language=fr','-f','dash','-seg_duration','1',
            '-adaptation_sets','id=0,streams=v id=1,streams=1 id=2,streams=2',str(folder/'manifest.mpd')],check=True,timeout=30)
        tree=ET.parse(folder/'manifest.mpd');root=tree.getroot();ns='{urn:mpeg:dash:schema:mpd:2011}'
        for adaptation in root.iter(ns+'AdaptationSet'):
            lang=adaptation.get('lang')
            if lang:
                ET.SubElement(adaptation,ns+'Role',value='original' if lang=='en' else 'dub')
                ET.SubElement(adaptation,ns+'Label').text='Original' if lang=='en' else 'French'
                rep=adaptation.find(ns+'Representation');index=rep.get('id');name='english' if lang=='en' else 'french'
                target=folder/name;target.mkdir()
                for file in folder.glob(f'*stream{index}*'):file.rename(target/file.name)
                ET.SubElement(adaptation,ns+'BaseURL').text=name+'/'
            elif adaptation.get('contentType')=='video':
                rep=adaptation.find(ns+'Representation');index=rep.get('id');target=folder/'video';target.mkdir()
                for file in folder.glob(f'*stream{index}*'):file.rename(target/file.name)
                ET.SubElement(adaptation,ns+'BaseURL').text='video/'
        period=root.find(ns+'Period')
        adaptation=ET.SubElement(period,ns+'AdaptationSet',contentType='text',mimeType='text/vtt',lang='fr')
        rep=ET.SubElement(adaptation,ns+'Representation',id='sub-fr',bandwidth='256')
        ET.SubElement(rep,ns+'BaseURL').text='fr.vtt'
        (folder/'fr.vtt').write_text('WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nKitty French caption\n')
        tree.write(folder/'manifest.mpd',encoding='utf-8',xml_declaration=True)

if __name__=='__main__':
    suite=unittest.TestSuite(cls(name) for cls in (HlsTracks,DashTracks) for name in dir(TransferMixin) if name.startswith('track_'))
    result=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not result.wasSuccessful())
