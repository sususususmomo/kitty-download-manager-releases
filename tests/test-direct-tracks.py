"""Direct containers: embedded language selection is local stream copy."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

spec=importlib.util.spec_from_file_location('directfixtures',Path(__file__).with_name('test-direct-download.py'))
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
import host,worker,queue_store

class DirectTracks(base.DirectTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        caption=cls.media/'caption.srt';caption.write_text('1\n00:00:00,000 --> 00:00:01,500\nEmbedded French Kitty caption\n')
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=640x360:r=10',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-f','lavfi','-i','sine=frequency=880:sample_rate=44100',
            '-i',str(caption),'-t','2','-map','0:v','-map','1:a','-map','2:a','-map','3:s','-c:v','libx264',
            '-threads','1','-preset','ultrafast','-c:a','aac','-c:s','mov_text','-metadata:s:a:0','language=eng',
            '-metadata:s:a:1','language=fra','-metadata:s:s:0','language=fra','-disposition:a:0','default+original',
            '-disposition:a:1','0',str(cls.media/'direct-tracks.mp4')],check=True,timeout=25)
        subprocess.run(['ffmpeg','-v','error','-i',str(cls.media/'direct-tracks.mp4'),'-map','0:a',
            '-c:a','copy',str(cls.media/'direct-tracks.m4a')],check=True,timeout=20)
    @classmethod
    def extra_response(cls,url,headers):
        if urlsplit(url).path=='/direct-tracks.mp4':return 200,'video/mp4',(cls.media/'direct-tracks.mp4').read_bytes()
        if urlsplit(url).path=='/direct-tracks.m4a':return 200,'audio/mp4',(cls.media/'direct-tracks.m4a').read_bytes()
        return super().extra_response(url,headers)
    def run_selected(self,mode,language,subtitle=False):
        source=self.source('/direct-tracks.mp4')
        prefs={'audioLanguage':language}
        if subtitle:prefs['subtitleLanguages']=['fra']
        active=dict(id='fixture',url=source['url'],mode=mode,media_source=source,
            track_selection=prefs,output_dir=str(self.output),status='starting',started_at=time.time(),youtube_auth=False)
        queue_store.atomic_json(worker.QUEUE_FILE,{**queue_store.default_state(),'active':active})
        with patch.object(sys,'argv',['worker.py','fixture']):code=worker.main()
        entry=worker.get_state()['history'][0];self.assertEqual(code,0,entry);self.assertEqual(entry['status'],'finished',entry)
        streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',entry['filepath']]))['streams']
        return entry,streams
    def track_direct_catalogue_preserves_all_embedded_metadata(self):
        report=host.probe_hls(self.source('/direct-tracks.mp4'));self.assertTrue(report['ok'],report)
        self.assertEqual([t['language'] for t in report['audioTracks']],['eng','fra'])
        self.assertEqual([t['audioIndex'] for t in report['audioTracks']],[0,1])
        # MP4 does not retain FFmpeg's "original" disposition. Unknown must
        # remain unknown rather than inventing an original-language flag.
        self.assertIsNone(report['audioTracks'][0]['original']);self.assertTrue(report['audioTracks'][0]['default'])
        self.assertEqual(report['subtitleTracks'][0]['language'],'fra');self.assertTrue(report['subtitleTracks'][0]['embedded'])
    def track_direct_original_audio_selected_language_copy(self):
        entry,streams=self.run_selected('audio','fra')
        self.assertEqual({s['codec_type'] for s in streams},{'audio'})
        self.assertEqual(streams[0]['codec_name'],'aac');self.assertEqual(streams[0]['tags']['language'],'fra')
        self.assertEqual(entry['download_plan']['embeddedAudioIndex'],1)
        def packets(file,index):
            return subprocess.check_output(['ffmpeg','-v','error','-i',str(file),'-map',f'0:a:{index}',
                '-c:a','copy','-f','data','pipe:1'])
        self.assertEqual(packets(self.media/'direct-tracks.mp4',1),packets(entry['filepath'],0),
            'Native AAC packet bytes must remain unchanged')
    def track_direct_video_language_and_optional_caption(self):
        entry,streams=self.run_selected('best','fra',subtitle=True)
        self.assertEqual({s['codec_type'] for s in streams},{'video','audio'})
        audio=[s for s in streams if s['codec_type']=='audio'];self.assertEqual(len(audio),1);self.assertEqual(audio[0]['tags']['language'],'fra')
        caption=list(self.output.glob('*.fra.srt'));self.assertEqual(len(caption),1)
        self.assertIn('Embedded French Kitty caption',caption[0].read_text())
    def track_direct_mp3_uses_selected_embedded_audio(self):
        entry,streams=self.run_selected('mp3','fra')
        self.assertEqual({s['codec_type'] for s in streams},{'audio'});self.assertEqual(streams[0]['codec_name'],'mp3')
        # Decode a short sample: frequency verifies the selected French stream,
        # rather than metadata copied from the first English audio track.
        import array,math
        pcm=subprocess.check_output(['ffmpeg','-v','error','-i',entry['filepath'],'-t','1','-f','f32le','-ac','1','-ar','8000','pipe:1'])
        samples=array.array('f');samples.frombytes(pcm)
        def power(freq):return abs(sum(value*complex(math.cos(2*math.pi*freq*i/8000),math.sin(2*math.pi*freq*i/8000)) for i,value in enumerate(samples)))
        self.assertGreater(power(880),power(440)*5)
    def track_direct_best_video_plus_other_native_language(self):
        video={**self.source('/direct-tracks.mp4'),'id':'video-own','media_item_id':'item:direct'}
        audio={**self.source('/direct-tracks.m4a',kind='direct_audio',mime='audio/mp4'),'id':'audio-own','media_item_id':'item:direct'}
        active=dict(id='fixture',url=video['url'],mode='best',automatic=True,source_page_url=video['page_url'],
            media_item={'id':'item:direct','page_url':video['page_url'],'title':'Mixed native tracks'},
            media_fallbacks=[video,audio],track_selection={'audioLanguage':'fra'},output_dir=str(self.output),
            status='starting',started_at=time.time(),youtube_auth=False)
        queue_store.atomic_json(worker.QUEUE_FILE,{**queue_store.default_state(),'active':active})
        with patch.object(sys,'argv',['worker.py','fixture']):code=worker.main()
        entry=worker.get_state()['history'][0];self.assertEqual(code,0,entry)
        streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',entry['filepath']]))['streams']
        audios=[s for s in streams if s['codec_type']=='audio'];self.assertEqual(len(audios),1)
        self.assertEqual(audios[0]['tags']['language'],'fra')
        self.assertEqual(entry['download_plan']['downloadUrls'],[video['url'],audio['url']])
        self.assertEqual(entry['download_plan']['audioLanguage'],'fra')
        def packets(file,index):return subprocess.check_output(['ffmpeg','-v','error','-i',str(file),'-map',f'0:a:{index}','-c:a','copy','-f','data','pipe:1'])
        self.assertEqual(packets(self.media/'direct-tracks.m4a',1),packets(entry['filepath'],0))

if __name__=='__main__':
    suite=unittest.TestSuite(DirectTracks(name) for name in dir(DirectTracks) if name.startswith('track_'))
    result=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not result.wasSuccessful())
