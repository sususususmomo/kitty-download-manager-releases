"""TikTok frontend payload -> real host/worker -> verified media file.

The normal tests use a local direct fallback and a controlled page-extraction
failure. KITTY_TEST_PUBLIC_TIKTOK=1 adds an actual public TikTok download.
KITTY_TEST_SYSTEM_CA=1 uses system trust certificates only in this QA process.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('tiktokfixtures', ROOT / 'tests/test-hls-download.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
import host, worker, download_planner
from download_planner import MetadataError

PAGE = 'https://www.tiktok.com/@andreea_bostanica/video/7660560870455840021'

class TikTokNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.HlsTests.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):
        fixture.HlsTests.tearDownClass.__func__(cls)
    setUp = fixture.HlsTests.setUp

    def payload(self, mode='720', public=False):
        # Preload A is offscreen; B is the main selected player in a feed.
        script = '''
const {fixture,player}=require('./tests/test-pill-download.js');
(async()=>{const f=fixture(process.argv[1]);f.saved.selectedMode=process.argv[4];
 f.setItems([player('preload',null,'',{blob:true,resourceUrl:'https://www.tiktok.com/@_/video/7660560870455840022'}),
  player('active',process.argv[3],'',{resourceUrl:process.argv[2]})]);f.setFrameTarget({domId:'active'});
 const response=await f.receive({type:'kitty-add-download'});
 if(!response.ok)throw new Error(JSON.stringify(response));console.log(JSON.stringify(f.downloads().at(-1)));
})().catch(e=>{console.error(e);process.exitCode=1});'''
        source = self.base + ('/expired.mp4' if public else '/normal.mp4')
        return json.loads(subprocess.check_output(['node','-e',script,
            'https://www.tiktok.com/foryou', PAGE, source, mode], cwd=ROOT, timeout=15))

    def transfer(self, mode='720', public=False):
        payload = self.payload(mode, public)
        for attr in ('QUEUE_FILE','LOCK_FILE','CONTROL_DIR'):
            self.stack.enter_context(patch.object(host,attr,getattr(worker,attr)))
        self.stack.enter_context(patch.object(host,'spawn_active_job',lambda *args:None))
        self.stack.enter_context(patch.object(host,'get_output_dir',lambda:self.output))
        self.stack.enter_context(patch.object(host,'WORKER',Path(worker.__file__)))
        if not public:
            original = download_planner.extract_metadata
            def extractor(options, job, **kwargs):
                if not job.get('media_source'):
                    raise MetadataError('extraction_failed', 'Controlled TikTok page metadata failure')
                return original(options,job,**kwargs)
            resolve = worker.resolve_candidates
            self.stack.enter_context(patch.object(worker,'resolve_candidates',
                lambda *args,**kwargs:resolve(*args,**kwargs,extractor=extractor)))
        elif os.environ.get('KITTY_TEST_SYSTEM_CA') == '1':
            build = worker.build_opts
            def trusted_options(*args,**kwargs):
                options = build(*args,**kwargs)
                options['compat_opts'] = ['no-certifi']
                return options
            self.stack.enter_context(patch.object(worker,'build_opts',trusted_options))
        response=host.enqueue(**{k:v for k,v in payload.items() if k not in ('action','client')})
        self.assertTrue(response['ok'],response)
        with patch.object(sys,'argv',['worker.py',response['job_id']]):
            code=worker.main()
        entry=worker.get_state()['history'][0]
        self.assertEqual(code,0,{key:entry.get(key) for key in ('status','error','error_code','error_detail')})
        self.assertEqual(entry['status'],'finished',entry)
        self.assertEqual(payload['url'], PAGE)
        self.assertTrue(Path(entry['filepath']).is_file())
        streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',entry['filepath']],timeout=15))['streams']
        media=[s for s in streams if not s.get('disposition',{}).get('attached_pic')]
        self.assertTrue(any(s['codec_type']=='audio' for s in media))
        self.assertEqual(any(s['codec_type']=='video' for s in media),mode not in ('audio','mp3'))
        self.assertEqual(entry['selected_source_type'],'ytdlp' if public else 'direct_video')
        report={'ok':True,'mode':mode,'source':entry['selected_source_type'],'bytes':Path(entry['filepath']).stat().st_size,
                'streams':[{'type':s['codec_type'],'codec':s['codec_name'],'height':s.get('height')} for s in streams],
                'actual_public_tiktok':public,'tls_system_trust_qa_only':os.environ.get('KITTY_TEST_SYSTEM_CA')=='1'}
        out=Path(os.environ.get('KITTY_TIKTOK_NATIVE_REPORT',ROOT/'artifacts/tiktok/native'))
        out.mkdir(parents=True,exist_ok=True)
        (out/('public' if public else mode)).with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')

    def test_page_metadata_failure_falls_back_to_owned_video(self): self.transfer()
    def test_audio_uses_same_owned_video(self): self.transfer('audio')
    def test_mp3_uses_existing_conversion(self): self.transfer('mp3')
    @unittest.skipUnless(os.environ.get('KITTY_TEST_PUBLIC_TIKTOK')=='1','Opt-in public network test')
    def test_public_tiktok_with_expired_preloaded_cdn(self): self.transfer(public=True)

if __name__=='__main__': unittest.main(verbosity=2)
