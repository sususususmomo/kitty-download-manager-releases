"""Selection rules and concurrent metadata-only discovery; no external sites."""
import errno
import math
from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native-host'))
import download_planner as planner
from metadata_guard import MetadataError

PAGE = 'https://page.test/watch/one'

def source(kind='hls', suffix='one', **kwargs):
    ext = {'hls':'m3u8','dash':'mpd','direct_video':'mp4','direct_audio':'m4a'}[kind]
    return dict(type=kind, url=f'https://cdn.test/{suffix}.{ext}', page_url=PAGE,
                tab_id=1, timestamp=time.time(), headers={}, title='One video', **kwargs)

def info(height=1080, audio=True, native=False, container='mp4'):
    formats = []
    if height:
        formats.append(dict(format_id='v',url='https://cdn.test/video',height=height, vcodec='avc1',
                            acodec='none' if native or not audio else 'aac',ext=container))
    if native or (audio and not height):
        formats.append(dict(format_id='a',url='https://cdn.test/audio',vcodec='none',acodec='aac',ext='m4a',abr=128))
    return dict(id='one',title='One video',formats=formats)

class PlannerTests(unittest.TestCase):
    def candidate(self, kind='ytdlp', data=None, mode='1080'):
        return planner.candidate_from_info(data or info(), None if kind == 'ytdlp' else source(kind),
                                           {'url':PAGE}, planner.DownloadRequest.from_mode(mode))
    def winner(self, values, mode='1080'):
        request=planner.DownloadRequest.from_mode(mode)
        return max(values, key=lambda c:(planner.scoreCandidate(c,request), c.sourceType=='ytdlp'))
    def test_same_quality_page_tie(self):
        page=self.candidate();hls=self.candidate('hls')
        self.assertEqual(self.winner([hls,page]).sourceType,'ytdlp')
    def test_1080_beats_page_720(self):
        self.assertEqual(self.winner([self.candidate(data=info(720)),self.candidate('hls')]).sourceType,'hls')
    def test_limit_selects_highest_under_cap(self):
        data=info(1080);data['formats']+=info(720)['formats']
        self.assertEqual(self.candidate(data=data,mode='720').maxHeight,720)
    def test_audio_from_higher_muxed_quality_is_not_a_separate_audio_track(self):
        data=info(1080);data['formats']+=info(720,audio=False)['formats']
        self.assertFalse(self.candidate(data=data,mode='720').hasAudio)
    def test_best_does_not_cap_scoring_at_2160(self):
        self.assertEqual(self.winner([self.candidate(data=info(2160),mode='best'),self.candidate('hls',info(4320),mode='best')],'best').sourceType,'hls')
    def test_empty_formats_are_not_a_valid_candidate(self):
        with self.assertRaises(MetadataError):self.candidate(data={'id':'empty','formats':[]})
    def test_video_only_loses_to_dash_with_audio(self):
        self.assertEqual(self.winner([self.candidate('hls',info(audio=False)),self.candidate('dash',info(native=True))]).sourceType,'dash')
    def test_lower_resolution_with_audio_beats_silent_direct(self):
        from dataclasses import replace
        request=replace(planner.DownloadRequest.from_mode('1080'),audioRequired=True)
        direct=self.candidate('direct_video',info(audio=False));hls=self.candidate('hls',info(720))
        self.assertGreater(planner.scoreCandidate(hls,request),planner.scoreCandidate(direct,request))
    def test_explicit_audio_optional_request_allows_silent_video(self):
        from dataclasses import replace
        request=replace(planner.DownloadRequest.from_mode('1080'),audioRequired=False)
        self.assertGreater(planner.scoreCandidate(self.candidate('direct_video',info(audio=False)),request),planner.scoreCandidate(self.candidate('hls',info(720)),request))
    def test_native_direct_audio_preferred(self):
        choices=[self.candidate('hls',info(native=True),'audio'),self.candidate(data=info(native=True),mode='audio'),self.candidate('direct_audio',info(None),mode='audio')]
        self.assertEqual(self.winner(choices,'audio').sourceType,'direct_audio')
    def test_native_audio_beats_extracting_mp4(self):
        self.assertEqual(self.winner([self.candidate('direct_video',info(),mode='audio'),self.candidate('dash',info(native=True),mode='audio')],'audio').sourceType,'dash')
    def test_mp4_lossless_extraction_is_valid(self):
        self.assertTrue(math.isfinite(planner.scoreCandidate(self.candidate('direct_video',info(),mode='audio'),planner.DownloadRequest.from_mode('audio'))))
    def test_expiry_and_transcode_penalties(self):
        c=self.candidate();request=planner.DownloadRequest.from_mode('audio');base=planner.scoreCandidate(c,request)
        c.requiresTranscode=True;self.assertLess(planner.scoreCandidate(c,request),base)
        c.expiryTime=time.time()-1;self.assertEqual(planner.scoreCandidate(c,request),-math.inf)
    def test_master_beats_partial(self):
        master=self.candidate('hls');child=self.candidate('hls');child.isMaster=False;child.isPartial=True
        self.assertIs(self.winner([child,master]),master)
    def test_audio_master_is_complete_without_video_resolution(self):
        c=planner.candidate_from_info(info(None),source(manifest_kind='master'),{'url':PAGE},planner.DownloadRequest.from_mode('audio'))
        self.assertTrue(c.isMaster);self.assertFalse(c.isPartial);self.assertTrue(c.nativeAudio)
    def test_runtime_source_errors_only(self):
        for message in ['HTTP Error 403: Forbidden','HTTP Error 410: Gone','Requested format is not available']:
            self.assertTrue(planner.can_runtime_fallback(RuntimeError(message),0,False,1),message)
    def test_cancel_never_falls_back(self):
        error=type('DownloadCancelled',(Exception,),{})()
        self.assertFalse(planner.can_runtime_fallback(error,0,False,0))
    def test_disk_and_filesystem_never_fall_back(self):
        for n in (errno.ENOSPC,errno.EACCES,errno.EPERM,errno.EROFS,errno.EIO):
            self.assertFalse(planner.can_runtime_fallback(OSError(n,'HTTP 403'),0,False,0))
        for text in ['No space left on device','Permission denied','ffmpeg not found','Postprocessing: conversion failed']:
            self.assertFalse(planner.can_runtime_fallback(RuntimeError(text),0,False,0),text)
    def test_late_transfer_never_falls_back(self):
        error=RuntimeError('HTTP Error 403')
        self.assertFalse(planner.can_runtime_fallback(error,65537,False,1))
        self.assertFalse(planner.can_runtime_fallback(error,0,True,1))
        self.assertFalse(planner.can_runtime_fallback(error,0,False,11))
    def test_invalid_manifest_headers_rejected(self):
        raw=source();raw['headers']={'Cookie':'secret'}
        with self.assertRaises(ValueError):planner.resolve_candidates({},dict(url=PAGE,mode='1080',media_fallbacks=[raw]))
    def test_rejection_reasons_are_safe_and_explicit(self):
        from dataclasses import replace
        silent=self.candidate('direct_video',info(audio=False))
        required=replace(planner.DownloadRequest.from_mode('1080'),audioRequired=True)
        self.assertEqual(planner.rejection_reason(silent,required),'audio_required_but_absent')
        self.assertTrue(math.isfinite(planner.scoreCandidate(self.candidate('direct_video'),required)))
        over=self.candidate('direct_video',info(1080),mode='720')
        self.assertEqual(planner.rejection_reason(over,planner.DownloadRequest.from_mode('720')),'no_video_format_under_requested_cap')
    def test_models_match_existing_modes(self):
        for mode in ('720','1080','best','audio','mp3'):
            request=planner.DownloadRequest.from_mode(mode)
            self.assertEqual(request.allowTranscode,mode=='mp3')
            self.assertEqual(request.audioRequired,mode in ('audio','mp3'))
        with self.assertRaises(ValueError):planner.DownloadRequest.from_mode('image')

class ParallelProbeTests(unittest.TestCase):
    def test_item_attached_sources_never_probe_page_or_other_item(self):
        calls=[]
        def extract(options,job,**kwargs):
            calls.append(job['url']);return info(),job.get('media_source')
        own=source('direct_video', 'own', media_item_id='selected')
        other=source('direct_video', 'other', media_item_id='different')
        results=planner.resolve_candidates({},dict(url=PAGE,mode='best',media_item={'id':'selected'},media_fallbacks=[own,other]),extractor=extract)
        self.assertEqual(calls,[own['url']]);self.assertEqual(len(results),1)
    def test_item_unknown_original_is_not_dropped_after_three_transcodes(self):
        calls=[]
        def extract(options,job,**kwargs):
            calls.append(job['url']);return info(2160 if job['url'].endswith('original.mp4') else 720),job['media_source']
        sources=[source('direct_video',str(i)) for i in range(3)]+[source('direct_video','original')]
        results=planner.resolve_candidates({},dict(url=PAGE,mode='best',media_item={'id':'selected'},media_fallbacks=sources),extractor=extract)
        self.assertEqual(len(calls),4);self.assertEqual(results[0].maxHeight,2160)
    def test_item_best_quality_prefers_highest_video_over_small_audio_bonus(self):
        def extract(options,job,**kwargs):
            high=job['url'].endswith('high.mp4')
            return info(1080 if high else 1000,audio=not high),job['media_source']
        results=planner.resolve_candidates({},dict(url=PAGE,mode='best',media_item={'id':'selected'},media_fallbacks=[source('direct_video','low'),source('direct_video','high')]),extractor=extract)
        self.assertEqual(results[0].maxHeight,1080)
    def test_known_page_player_excludes_unrelated_higher_quality(self):
        def extract(options,job,**kwargs):
            current=job.get('media_source')
            data=info(4320 if current and current['url'].endswith('ad.m3u8') else 1080)
            if current and current['url'].endswith('ad.m3u8'):
                data['formats'][0]['url']='https://cdn.test/unrelated-ad'
            return data,current
        result=planner.resolve_candidates({},dict(url=PAGE,mode='best',media_fallbacks=[source(suffix='one'),source(suffix='ad')]),extractor=extract)
        self.assertEqual(len(result),2);self.assertFalse(any(c.url.endswith('ad.m3u8') for c in result))
    def test_canonical_page_keeps_original_observed_context(self):
        raw=source();raw['page_url']=PAGE+'?tracking=one'
        def extract(options,job,**kwargs):return info(),job.get('media_source')
        result=planner.resolve_candidates({},dict(url=PAGE,source_page_url=raw['page_url'],mode='1080',media_fallbacks=[raw]),extractor=extract)
        self.assertEqual(len(result),2);self.assertTrue(all(c.pageUrl==raw['page_url'] for c in result))
    def test_resolvers_really_overlap_and_download_disabled(self):
        barrier=threading.Barrier(4);calls=[]
        def extract(options,job,**kwargs):
            calls.append(job['url']);self.assertTrue(options['skip_download']);barrier.wait(timeout=2)
            return info(),job.get('media_source')
        result=planner.resolve_candidates({},dict(url=PAGE,mode='1080',media_fallbacks=[source(k) for k in ('hls','dash','direct_video')]),extractor=extract)
        self.assertEqual(len(calls),4);self.assertEqual(len(result),4)
    def test_page_failure_all_fallback_families(self):
        for kind in ('hls','dash','direct_video'):
            def extract(options,job,**kwargs):
                if not job.get('media_source'):raise MetadataError('unsupported_url','Page unsupported')
                return info(),job['media_source']
            result=planner.resolve_candidates({},dict(url=PAGE,mode='1080',media_fallbacks=[source(kind)]),extractor=extract)
            self.assertEqual(result[0].sourceType,kind)
    def test_page_timeout_cannot_hold_ready_hls(self):
        stopped=threading.Event();logs=[]
        def extract(options,job,check_control,**kwargs):
            if job.get('media_source'):return info(),job['media_source']
            try:
                while True:check_control();time.sleep(.01)
            finally:stopped.set()
        start=time.monotonic()
        result=planner.resolve_candidates({},dict(url=PAGE,mode='1080',media_fallbacks=[source()]),extractor=extract,ready_grace=.15,log=logs.append)
        self.assertEqual(result[0].sourceType,'hls');self.assertLess(time.monotonic()-start,.6);self.assertTrue(stopped.is_set());self.assertIn('resolver timeout: ytdlp',logs)
    def test_cancel_stops_every_probe(self):
        class Cancelled(Exception):pass
        finished=[];start=time.monotonic()
        def control():
            if time.monotonic()-start>.12:raise Cancelled()
        def extract(options,job,check_control,**kwargs):
            try:
                while True:check_control();time.sleep(.01)
            finally:finished.append(job['url'])
        with self.assertRaises(Cancelled):planner.resolve_candidates({},dict(url=PAGE,mode='1080',media_fallbacks=[source()]),check_control=control,extractor=extract)
        self.assertEqual(len(finished),2)
    def test_multiple_players_are_never_combined(self):
        def extract(options,job,**kwargs):
            data=info(audio=not job['url'].endswith('one.m3u8'));data['id']=job['url'];return data,job.get('media_source')
        unrelated=source('dash');unrelated['page_url']='https://other.test/watch'
        result=planner.resolve_candidates({},dict(url=PAGE,mode='1080',media_fallbacks=[source(suffix='one'),source(suffix='two'),unrelated]),extractor=extract)
        self.assertEqual(len(result),3)
        self.assertTrue(all(c.info['id']==c.url for c in result))
    def test_failure_only_when_every_resolver_fails(self):
        def extract(*args,**kwargs):raise MetadataError('unsupported_url','Safe error')
        with self.assertRaises(MetadataError):planner.resolve_candidates({},dict(url=PAGE,mode='1080',media_fallbacks=[source()]),extractor=extract)

if __name__=='__main__':unittest.main(verbosity=2)
