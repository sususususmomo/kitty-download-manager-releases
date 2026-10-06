"""Shared request policy against real protected MP4, HLS and DASH fixtures."""
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('contextfixtures',Path(__file__).with_name('test-dash-download.py'))
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
import hls, host, worker, request_context, download_planner, queue_store


class ContextTests(base.DashTests):
 @classmethod
 def setUpClass(cls):
  super().setUpClass()
  subprocess.run(['ffmpeg','-v','error','-i',str(cls.media/'high/index.m3u8'),'-c','copy',str(cls.media/'context_1080p.mp4')],check=True,timeout=20)
 @classmethod
 def extra_response(cls,url,headers):
  path=urlsplit(url).path
  if path.startswith('/context-variant/'):
   height='1080' if '1080p' in path else '720'
   if headers.get('Cookie')!='variant='+height or headers.get('X-Variant')!=height:
    return 403,'text/plain',b'Wrong variant context'
   return 200,'video/mp4',(cls.media/('context_1080p.mp4' if height=='1080' else 'normal.mp4')).read_bytes()
  if not path.startswith('/context/'):

   return super().extra_response(url,headers)
  required={'Referer':cls.base+'/page','Origin':cls.base,'User-Agent':'Firefox Context QA',
            'Cookie':'session=PRIVATE-SESSION','Authorization':'Bearer PRIVATE-AUTH','X-Media-Key':'PRIVATE-KEY'}
  if any(headers.get(k)!=v for k,v in required.items()):
   return 403,'text/plain',b'Context required'
  rel=path.removeprefix('/context/')
  if rel=='master.m3u8':
   return 200,'application/vnd.apple.mpegurl',b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100000,RESOLUTION=1280x720,CODECS="avc1.42e01f,mp4a.40.2"\nlow/index.m3u8\n'
  file=cls.media/rel
  if not file.is_file():return 404,'text/plain',b'Absent'
  return 200,{'m3u8':'application/vnd.apple.mpegurl','mpd':'application/dash+xml','ts':'video/mp2t'}.get(file.suffix[1:],'video/mp4'),file.read_bytes()

 def context_source(self,kind,path,headers=None):
  url=self.base+path
  context={'version':1,'source_url':url,'headers':headers or {
   'Referer':self.base+'/page','Origin':self.base,'User-Agent':'Firefox Context QA',
   'Authorization':'Bearer PRIVATE-AUTH','X-Media-Key':'PRIVATE-KEY'},'cookies':'session=PRIVATE-SESSION'}
  return hls.validate_source(dict(type=kind,url=url,page_url=self.base+'/page',tab_id=1,timestamp=time.time(),
        request_context=context,metadata={'height':720} if kind.startswith('direct_') else {},title='Protected context'))

 def assert_private(self,entry):
  text='\n'.join(self.logs)+json.dumps(request_context.public_state(entry))
  for secret in ['PRIVATE-SESSION','PRIVATE-AUTH','PRIVATE-KEY']:
   self.assertNotIn(secret,text)
  self.assertIsNone(entry['media_source']['request_context'])

 def test_context_hls_manifest_and_segments(self):
  entry,_=self.successful(source=self.context_source('hls','/context/master.m3u8'),mode='720')
  self.assertTrue(any(p.endswith('.ts') for p,_ in self.requests))
  self.assert_private(entry)

 def test_context_dash_manifest_and_fragments(self):
  entry,_=self.successful(source=self.context_source('dash','/context/dash/manifest.mpd'),mode='720')
  self.assertTrue(any('.m4s' in p for p,_ in self.requests))
  self.assert_private(entry)

 def test_context_direct_metadata_and_transfer(self):
  entry,_=self.successful(source=self.context_source('direct_video','/context/normal.mp4'),mode='720')
  self.assert_private(entry)
  seen=[h for p,h in self.requests if p.startswith('/context/')]
  self.assertTrue(seen);self.assertTrue(all(h.get('Authorization')=='Bearer PRIVATE-AUTH' for h in seen))

 def test_context_missing_is_denied(self):
  for kind,path in [('hls','/context/master.m3u8'),('dash','/context/dash/manifest.mpd'),('direct_video','/context/normal.mp4')]:
   source=self.context_source(kind,path);source['request_context']=None;source['headers']={}
   result=host.probe_hls(source);self.assertFalse(result['ok']);self.assertIn('access_denied',result['code'])

 def test_context_referer_origin_only(self):
  source=self.source('/protected-dash/dash/manifest.mpd',{'Referer':self.base+'/page','Origin':self.base,'User-Agent':'Firefox DASH QA'})
  self.assertFalse(source['request_context'].get('cookies'))
  self.successful(source=source,mode='720')

 def test_context_validation_and_redaction(self):
  source=self.context_source('hls','/context/master.m3u8')
  for change in [{'source_url':self.base+'/other.m3u8'},{'version':True},{'headers':{'Range':'bytes=1-2'}},
      {'headers':{'Authorization':'PRIVATE\r\nBad: yes'}},{'cookies':'secret\nBad: yes'}]:
   with self.subTest(change=change):
    with self.assertRaises(ValueError):hls.validate_source({**source,'request_context':{**source['request_context'],**change}})
  model=request_context.from_source(source);self.assertNotIn('PRIVATE',repr(model));self.assertNotIn('PRIVATE',json.dumps(model.summary()))
  clean=request_context.public_state({'queue':[{'media_source':source}]})
  self.assertNotIn('request_context',json.dumps(clean))
  self.assertEqual(model.for_url('https://other.test/segment.ts'),{})

 def test_context_quality_variants_keep_their_headers(self):
  contexts=[]
  for height in (720,1080):
   url=self.base+f'/clip_{height}p.mp4'
   # Known direct metadata/transport fixture tested separately; inspect independent policy selection.
   contexts.append(hls.validate_source(dict(type='direct_video',url=url,page_url=self.base+'/page',tab_id=1,timestamp=time.time(),
      request_context={'version':1,'source_url':url,'headers':{'X-Variant':str(height)}})))
  source={**contexts[0],'variants':contexts}
  opts=hls.apply_options({},hls.validate_source(source))
  self.assertEqual([c['headers']['x-variant'] for c in opts['kitty_variant_contexts']],['720','1080'])

 def test_context_alternate_track_directory_has_its_own_session(self):
  # Real urllib transport, same CDN, two sessions: fragment URL is not the
  # original manifest URL, so origin-only routing would use the video session.
  seen=[]
  class Handler(BaseHTTPRequestHandler):
   def do_GET(server):
    seen.append((server.path,server.headers.get('Cookie'),server.headers.get('X-Track')))
    server.send_response(200);server.end_headers();server.wfile.write(b'segment')
   def log_message(*args):pass
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   root=f'http://127.0.0.1:{server.server_port}'
   contexts=[dict(version=1,source_url=root+f'/{kind}/media.m3u8',headers={'X-Track':kind},cookies='track='+kind) for kind in ('video','audio')]
   with request_context.youtube_dl({'quiet':True,'kitty_request_context':contexts[0],'kitty_variant_contexts':contexts[1:]}) as ydl:
    for kind in ('audio','video'):
     with ydl.urlopen(root+f'/{kind}/segment001.m4s') as response:self.assertEqual(response.read(),b'segment')
   self.assertEqual(seen,[('/audio/segment001.m4s','track=audio','audio'),('/video/segment001.m4s','track=video','video')])
  finally:server.shutdown();server.server_close()

 def test_context_real_variants_use_independent_sessions(self):
  variants=[]
  for height in (720,1080):
   url=self.base+f'/context-variant/clip_{height}p.mp4'
   variants.append(hls.validate_source(dict(type='direct_video',url=url,page_url=self.base+'/page',tab_id=1,timestamp=time.time(),title='Independent variants',metadata={'height':height},
    request_context={'version':1,'source_url':url,'headers':{'X-Variant':str(height)},'cookies':'variant='+str(height)})))
  source=hls.validate_source({**variants[0],'variants':variants})
  entry,actual=self.successful(source=source,mode='best')
  self.assertEqual(next(s['height'] for s in actual['streams'] if s['codec_type']=='video'),1080)
  seen=[(p,h) for p,h in self.requests if p.startswith('/context-variant/')]
  self.assertTrue(seen)
  for p,h in seen:
   height='1080' if '1080p' in p else '720'
   self.assertEqual(h.get('Cookie'),'variant='+height);self.assertEqual(h.get('X-Variant'),height)

 def test_context_metadata_and_automatic_preserve_context(self):
  source=self.context_source('hls','/context/master.m3u8')
  job={'url':source['page_url'],'mode':'720','media_fallbacks':[source]}
  candidates=download_planner.resolve_candidates({},job)
  self.assertTrue(candidates);self.assertEqual(candidates[0].requestContext['cookies'],'session=PRIVATE-SESSION')
  self.assertNotIn('PRIVATE',repr(candidates[0]))

 def test_context_same_origin_redirect_and_session_renewal(self):
  seen=[]
  class Handler(BaseHTTPRequestHandler):
   def do_GET(self):
    seen.append((self.path,self.headers.get('Cookie'),self.headers.get('Authorization')))
    if self.path=='/start':
     self.send_response(302);self.send_header('Location','/final');self.send_header('Set-Cookie','session=RENEWED; Path=/');self.end_headers()
    else:
     self.send_response(200);self.end_headers();self.wfile.write(b'OK')
   def log_message(self,*args):pass
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
  threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   url=f'http://127.0.0.1:{server.server_port}/start'
   context={'version':1,'source_url':url,'headers':{'Authorization':'Bearer PRIVATE-AUTH'},'cookies':'session=INITIAL'}
   with request_context.youtube_dl({'quiet':True,'kitty_request_context':context}) as ydl:
    with ydl.urlopen(url) as response:self.assertEqual(response.read(),b'OK')
   self.assertEqual(seen,[('/start','session=INITIAL','Bearer PRIVATE-AUTH'),('/final','session=RENEWED','Bearer PRIVATE-AUTH')])
  finally:server.shutdown();server.server_close()

 def test_context_redirect_never_leaks_session_to_other_origin(self):
  seen=[]
  class Target(BaseHTTPRequestHandler):
   def do_GET(self):
    seen.append(dict(self.headers));self.send_response(200);self.end_headers();self.wfile.write(b'OK')
   def log_message(self,*args):pass
  target=ThreadingHTTPServer(('127.0.0.1',0),Target)
  threading.Thread(target=target.serve_forever,daemon=True).start()
  class Start(BaseHTTPRequestHandler):
   def do_GET(self):
    self.send_response(302);self.send_header('Location',f'http://127.0.0.1:{target.server_port}/target');self.end_headers()
   def log_message(self,*args):pass
  start=ThreadingHTTPServer(('127.0.0.1',0),Start)
  threading.Thread(target=start.serve_forever,daemon=True).start()
  try:
   url=f'http://127.0.0.1:{start.server_port}/start'
   context={'version':1,'source_url':url,'headers':{'Authorization':'Bearer PRIVATE-AUTH','X-Media-Key':'PRIVATE-KEY','Referer':self.base+'/page'},'cookies':'session=PRIVATE-SESSION'}
   with request_context.youtube_dl({'quiet':True,'kitty_request_context':context}) as ydl:
    with ydl.urlopen(url) as response:self.assertEqual(response.read(),b'OK')
   self.assertTrue(seen)
   for name in ['Cookie','Authorization','X-Media-Key','Referer']:self.assertIsNone(seen[0].get(name),name)
  finally:
   start.shutdown();start.server_close();target.shutdown();target.server_close()


if __name__=='__main__':
 suite=unittest.TestSuite(ContextTests(n) for n in unittest.defaultTestLoader.getTestCaseNames(ContextTests) if n.startswith('test_context_'))
 result=unittest.TextTestRunner(verbosity=2).run(suite)
 sys.exit(not result.wasSuccessful())
