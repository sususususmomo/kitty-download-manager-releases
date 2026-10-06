"""Regression: known media pages must keep their extractor and real title."""
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native-host'))
import download_planner as planner
import media_item
import host
from metadata_guard import MetadataError
from errors import redact_error_detail

PAGE = 'https://www.youtube.com/watch?v=jNQXAC9IVRw'
SOURCE = dict(type='direct_video', url='https://cdn.test/rendition.mp4', page_url=PAGE,
              headers={}, id='network-source', title='Média',tab_id=1,timestamp=time.time())


def info(title='Actual title', height=720):
    return dict(id='one', title=title, formats=[dict(format_id='one', url='https://cdn.test/actual.mp4',
            ext='mp4', height=height, vcodec='avc1', acodec='aac')])


class ProviderTests(unittest.TestCase):
    def test_metadata_error_preserves_safe_technical_detail(self):
        raw='Requested format 137 is not available at https://cdn.test/file?token=SECRET\nCookie: sid=SECRET\nAuthorization: Bearer SECRET'
        detail=redact_error_detail(raw)
        self.assertIn('Requested format 137',detail)
        self.assertNotIn('SECRET',detail);self.assertNotIn('cdn.test',detail)
        error=MetadataError('format_unavailable','Format demandé indisponible',detail)
        self.assertEqual(error.detail,detail)
        self.assertEqual(str(error),'Format demandé indisponible')
    def test_known_media_pages_exclude_profiles_feeds_and_galleries(self):
        for value in [PAGE, 'https://youtu.be/jNQXAC9IVRw', 'https://m.youtube.com/shorts/jNQXAC9IVRw',
                      'https://soundcloud.com/artist/track']:
            self.assertTrue(media_item.provider_media_page(value), value)
        for value in ['https://www.youtube.com/results?search_query=x', 'https://www.youtube.com/@artist',
                      'https://soundcloud.com/artist', 'https://soundcloud.com/artist/sets',
                      'https://soundcloud.com/artist/likes', 'https://soundcloud.com/discover/sets',
                      'https://youtube.com.attacker.test/watch?v=jNQXAC9IVRw', 'https://gallery.test/page']:
            self.assertFalse(media_item.provider_media_page(value), value)

    def test_known_page_is_probed_despite_attached_network_sources(self):
        seen=[]
        def extract(opts, job, **kwargs):
            seen.append(job['url'])
            return (info('CDN name', 1080) if job.get('media_source') else info()), job.get('media_source')
        # Also covers existing frontend 8.51 without the new explicit flag.
        job=dict(url=PAGE, mode='1080', source_page_url=PAGE,
                 media_item={'id':'item-one', 'explicit_sources':True}, media_fallbacks=[SOURCE])
        results=planner.resolve_candidates({},job,extractor=extract)
        self.assertIn(PAGE, seen)
        self.assertEqual(results[0].sourceType, 'ytdlp')
        self.assertEqual(results[0].title, 'Actual title')
        self.assertEqual(results[0]._track_cohort, [results[0]])
        self.assertEqual(len(results), 2)

    def test_failed_extractor_retains_network_fallback(self):
        def extract(opts, job, **kwargs):
            if not job.get('media_source'):
                raise MetadataError('unsupported_url', 'No extractor')
            return info(),job['media_source']
        results=planner.resolve_candidates({},dict(url=PAGE,mode='1080',media_item={'id':'one'},
                        source_page_url=PAGE,media_fallbacks=[SOURCE]),extractor=extract)
        self.assertEqual(results[0].sourceType,'direct_video')

    def test_drm_and_access_failures_are_not_replaced_by_network_fallback(self):
        for code in ('drm_protected','login_required'):
            def extract(opts,job,**kwargs):
                if not job.get('media_source'):raise MetadataError(code,'Blocked')
                return info(),job['media_source']
            with self.subTest(code=code), self.assertRaises(MetadataError):
                planner.resolve_candidates({},dict(url=PAGE,mode='1080',media_item={'id':'one'},
                    source_page_url=PAGE,media_fallbacks=[SOURCE]),extractor=extract)
            with patch.object(host,'extract_metadata',side_effect=MetadataError(code,'Blocked')), \
                 patch.object(host,'_prepare_playlist_auth_cookie_copy',return_value=None), \
                 patch.object(host,'probe_hls',side_effect=AssertionError('must not fallback')):
                result=host.probe_media_item(PAGE,dict(id='one',page_url=PAGE),[SOURCE])
            self.assertFalse(result['ok']);self.assertEqual(result['code'],code)

    def test_gallery_still_uses_only_its_own_sources(self):
        page='https://gallery.test/page'
        seen=[]
        def extract(opts,job,**kwargs):
            seen.append(job['url']);return info(),job.get('media_source')
        planner.resolve_candidates({},dict(url=SOURCE['url'],source_page_url=page,mode='1080',
            media_item={'id':'one','explicit_sources':True},media_fallbacks=[{**SOURCE,'page_url':page}]),extractor=extract)
        self.assertEqual(seen,[SOURCE['url']])

    def test_provider_metadata_title_wins_over_player_label(self):
        data=info()
        item=media_item.validate_item(dict(id='one',page_url=PAGE,title='YouTube video player',
                                          title_source='aria-label',prefer_extractor=True))
        media_item.apply_item_metadata(data,item)
        self.assertEqual(data['title'],'Actual title')
        item['prefer_extractor']=False
        item['title_source']='caption';item['title']='Gallery caption'
        media_item.apply_item_metadata(data,item)
        self.assertEqual(data['title'],'Gallery caption')

    def test_metadata_probe_uses_page_before_cdn_and_returns_extractor_tracks(self):
        item=dict(id='one',page_url=PAGE,prefer_extractor=True)
        with patch.object(host,'extract_metadata',return_value=(info(),None)) as extract, \
             patch.object(host,'probe_hls',side_effect=AssertionError('CDN probe before page')), \
             patch.object(host,'_prepare_playlist_auth_cookie_copy',return_value=None):
            result=host.probe_media_item(PAGE,item,[SOURCE])
        self.assertTrue(result['ok'])
        self.assertEqual(result['title'],'Actual title')
        self.assertEqual(extract.call_args.args[1]['url'],PAGE)
        self.assertTrue(all(t['sourceId']=='item-extractor' for t in result['audioTracks']))

    def test_metadata_probe_retains_network_fallback(self):
        with patch.object(host,'extract_metadata',side_effect=MetadataError('unsupported_url','No extractor')), \
             patch.object(host,'_prepare_playlist_auth_cookie_copy',return_value=None), \
             patch.object(host,'probe_hls',return_value={'ok':True,'title':'Network fallback',
                            'videoTracks':[],'audioTracks':[],'subtitleTracks':[]}):
            result=host.probe_media_item(PAGE,dict(id='one',page_url=PAGE),[SOURCE])
        self.assertTrue(result['ok']);self.assertEqual(result['title'],'Network fallback')


if __name__ == '__main__':
    unittest.main(verbosity=2)
