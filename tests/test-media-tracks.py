"""Track catalogue and pinned plans over real yt-dlp format selection."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native-host'))
import download_planner as planner
from media_tracks import catalogue, validate_selection, annotate_manifest
from metadata_guard import MetadataError

PAGE = 'https://page.test/one'

def media_info():
    formats = [dict(format_id='v720', url='https://cdn.test/video720', ext='mp4',
        height=720, vcodec='avc1', acodec='none'), dict(format_id='v1080',
        url='https://cdn.test/video1080', ext='mp4', height=1080, vcodec='avc1', acodec='none')]
    for lang, original, bitrate in [('en', True, 64), ('en', True, 128), ('fr', False, 256)]:
        formats.append(dict(format_id=f'{lang}{bitrate}', url=f'https://cdn.test/{lang}{bitrate}',
            ext='m4a', vcodec='none', acodec='mp4a.40.2', language=lang, abr=bitrate,
            format_note=('English (original)' if original else 'French') + (', low' if bitrate == 64 else ', high'),
            is_default=original))
    return dict(id='one', title='One media', formats=formats,
        subtitles={'fr': [dict(url='https://cdn.test/fr.vtt', ext='vtt')]},
        automatic_captions={'en': [dict(url='https://cdn.test/en.vtt', ext='vtt')]})

def candidate(data=None, source=None, mode='best'):
    return planner.candidate_from_info(data or media_info(), source, {'url': PAGE}, planner.DownloadRequest.from_mode(mode))

def plan(data=None, selection=None, mode='best', source=None, cohort=None):
    return planner.build_item_plan(candidate(data, source, mode),
        dict(mode=mode, url=PAGE, media_item={'id':'item:1'}, track_selection=selection or {}),
        dict(format='ba/b' if mode in ('audio','mp3') else 'bv*+ba/b', quiet=True, no_warnings=True), cohort)

class TrackTests(unittest.TestCase):
    def test_ytdlp_metadata_and_quality_grouping(self):
        tracks = catalogue(media_info(), 'extractor', 'ytdlp')
        self.assertEqual(len(tracks['videoTracks']), 2)
        self.assertEqual(len(tracks['audioTracks']), 2)
        en = tracks['audioTracks'][0]
        self.assertEqual(en['formatIds'], ['en64','en128'])
        self.assertEqual((en['language'], en['codec'], en['bitrate'], en['default'], en['original']),
            ('en','mp4a.40.2',128,True,True))
        self.assertTrue(all(t['sourceId']=='extractor' for kind in tracks.values() for t in kind))
        self.assertNotIn('https://',json.dumps(tracks))
    def test_ids_survive_async_quality_url_and_metadata_changes(self):
        original = catalogue(media_info(), 'extractor','ytdlp')['audioTracks']
        data=media_info();data['title']='Updated';data['thumbnail']='https://cdn.test/new.jpg'
        for f in data['formats']:f['url']+='?token=NEW_SECRET'
        self.assertEqual([t['id'] for t in original], [t['id'] for t in catalogue(data,'extractor','ytdlp')['audioTracks']])
    def test_best_video_and_requested_language(self):
        selected=plan(selection={'audioLanguage':'fr','subtitleLanguages':['fr']})
        self.assertEqual(selected.formatSelector,'v1080+fr256')
        self.assertEqual(selected.audioLanguage,'fr')
        self.assertEqual(selected.subtitleLanguages,('fr',))
        self.assertEqual(set(selected.preparedInfo['subtitles']),{'fr'})
        self.assertEqual(selected.preparedInfo['automatic_captions'],{})
    def test_default_original_over_higher_bitrate_dub(self):
        self.assertEqual(plan().formatSelector,'v1080+en128')
    def test_requested_track_id(self):
        track=candidate().audioTracks[1]
        selected=plan(selection={'audioTrackId':track['id']})
        self.assertEqual(selected.audioTrackId,track['id']);self.assertEqual(selected.audioLanguage,'fr')
    def test_audio_original_only_native(self):
        selected=plan(mode='audio')
        self.assertEqual(selected.formatSelector,'en128')
        self.assertEqual(selected.videoTrackIds,())
        self.assertEqual(selected.downloadUrls,('https://cdn.test/en128',))
    def test_audio_requested_language(self):
        self.assertEqual(plan(mode='audio',selection={'audioLanguage':'fr'}).formatSelector,'fr256')
    def test_mp3_still_selects_native_audio_before_conversion(self):
        self.assertEqual(plan(mode='mp3',selection={'audioLanguage':'fr'}).formatSelector,'fr256')
    def test_subtitles_optional_and_automatic_explicit(self):
        self.assertEqual(plan().subtitleTrackIds,())
        selected=plan(selection={'subtitleLanguages':['en']})
        self.assertEqual(set(selected.preparedInfo['subtitles']),{'en'})
        self.assertEqual(len(selected.subtitleTrackIds),1)
    def test_missing_language_never_silently_uses_other(self):
        with self.assertRaises(MetadataError) as error:plan(selection={'audioLanguage':'de'})
        self.assertEqual(error.exception.code,'track_unavailable')
    def test_missing_subtitle_and_foreign_track_rejected(self):
        for selection in ({'subtitleLanguages':['de']},{'audioTrackId':'another-item:audio'}):
            with self.subTest(selection=selection), self.assertRaises(MetadataError):plan(selection=selection)
    def test_native_audio_from_separate_item_owned_candidate(self):
        source=dict(type='direct_audio',id='audio-source',url='https://audio.test/original.m4a',page_url=PAGE,
                    headers={},request_context={'version':1,'source_url':'https://audio.test/original.m4a','headers':{'Referer':PAGE}})
        info=dict(id='audio',title='One media',formats=[dict(format_id='a',url=source['url'],ext='m4a',vcodec='none',acodec='aac',language='de',abr=192)])
        audio=candidate(info,source);video=candidate()
        selected=planner.build_item_plan(video,dict(mode='best',media_item={'id':'one'},track_selection={'audioTrackId':audio.audioTracks[0]['id']}),
            dict(format='bv+ba',quiet=True),[video,audio])
        self.assertEqual(selected.downloadUrls,('https://cdn.test/video1080',source['url']))
        self.assertEqual(selected.audioLanguage,'de');self.assertEqual(selected.auxiliarySources,(source,))
    def test_muxed_audio_fallback_when_no_native(self):
        data=dict(id='one',title='Muxed',formats=[dict(format_id='muxed',url='https://cdn.test/m.mp4',ext='mp4',height=720,vcodec='avc1',acodec='aac')])
        selected=plan(data,mode='audio');self.assertEqual(selected.formatSelector,'muxed')
        self.assertEqual(selected.audioLanguage,None)
    def test_direct_native_metadata(self):
        data=dict(id='a',formats=[dict(format_id='a',url='https://cdn.test/a.opus',ext='opus',vcodec='none',acodec='opus',language='fr',abr=96,is_default=True)])
        track=catalogue(data,'direct','direct_audio')['audioTracks'][0]
        self.assertEqual((track['language'],track['codec'],track['bitrate'],track['native']),('fr','opus',96,True))
    def test_hls_flags_use_existing_attribute_parser(self):
        info=dict(formats=[dict(format_id='en',url='https://cdn.test/audio.m3u8?token=old',ext='m4a',vcodec='none',acodec='aac',language='en')])
        annotate_manifest(info,b'#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="Original",LANGUAGE="en",DEFAULT=YES,URI="audio.m3u8?token=new"\n','https://cdn.test/master.m3u8','hls')
        track=catalogue(info,'hls','hls')['audioTracks'][0]
        self.assertTrue(track['default']);self.assertTrue(track['original'])
    def test_dash_roles_labels_and_language(self):
        info=dict(formats=[dict(format_id='dash-en',url='https://cdn.test/a',ext='m4a',vcodec='none',acodec='aac',language='en')])
        annotate_manifest(info,b'<MPD><Period><AdaptationSet id="audio" lang="en"><Role value="main"/><Role value="original"/><Label>English</Label><Representation id="en"/></AdaptationSet></Period></MPD>','https://cdn.test/manifest.mpd','dash')
        track=catalogue(info,'dash','dash')['audioTracks'][0]
        self.assertEqual(track['label'],'English');self.assertTrue(track['default']);self.assertTrue(track['original'])
    def test_selection_validation(self):
        for value in ([],{'audioLanguage':'en\nCookie: secret'},{'preferOriginal':'yes'},{'subtitleTrackIds':['a']*21},{'headers':{}}):
            with self.subTest(value=value),self.assertRaises(ValueError):validate_selection(value)
    def test_immutable_plan_cannot_reinterpret_global_selector(self):
        selected=plan(selection={'audioLanguage':'fr'})
        actual=list(selected.select_formats({'formats':[{'url':'https://another.test/video'}]}))[0]
        self.assertEqual([f['url'] for f in actual['requested_formats']],list(selected.downloadUrls))
    def test_stale_extractor_video_selection_removed_before_audio_plan(self):
        data=media_info();data['requested_formats']=[data['formats'][1],data['formats'][-1]]
        data['requested_downloads']=[{'format_id':'v1080+fr256'}]
        selected=plan(data,mode='audio')
        self.assertEqual(selected.downloadUrls,('https://cdn.test/en128',))
        self.assertEqual(selected.formatSelector,'en128')
    def test_resolver_keeps_audio_only_candidate_for_item_video_plan(self):
        video=dict(type='direct_video',id='video-own',url='https://cdn.test/v.mp4',page_url=PAGE,headers={},media_item_id='one',tab_id=1,timestamp=1)
        audio=dict(type='direct_audio',id='audio-own',url='https://cdn.test/a.m4a',page_url=PAGE,headers={},media_item_id='one',tab_id=1,timestamp=1)
        def extract(_opts,job,**_kwargs):
            s=job['media_source'];is_audio=s['type']=='direct_audio'
            return dict(id='one',title='One',formats=[dict(format_id='a' if is_audio else 'v',url=s['url'],
                ext='m4a' if is_audio else 'mp4',vcodec='none' if is_audio else 'avc1',
                acodec='aac' if is_audio else 'none',height=None if is_audio else 1080,
                language='fr' if is_audio else None)]),s
        for preferences in ({'audioLanguage':'fr'},{}):
            job=dict(url=PAGE,source_page_url=PAGE,mode='best',media_item={'id':'one'},
                media_fallbacks=[video,audio],track_selection=preferences)
            resolved=planner.resolve_candidates({},job,extractor=extract)
            selected=planner.build_item_plan(resolved[0],job,dict(format='bv+ba',quiet=True))
            self.assertEqual(selected.downloadUrls,(video['url'],audio['url']))
            self.assertEqual(selected.audioLanguage,'fr')

if __name__ == '__main__':unittest.main(verbosity=2)
