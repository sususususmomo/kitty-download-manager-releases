"""Signed URL expiry after real partial transfers, plus fail-closed identity tests."""
import importlib.util
import io
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'native-host'))
from source_refresh import SourceRefresh, hls_snapshot, dash_snapshot, resource
from hls import HlsError, validate_source
from yt_dlp.networking import Request, Response
from yt_dlp.networking.exceptions import HTTPError
import host, worker, queue_store

spec = importlib.util.spec_from_file_location('dashfixtures', Path(__file__).with_name('test-dash-download.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


class IdentityTests(unittest.TestCase):
    def info(self, url='http://local.test/clip.mp4?token=old'):
        return {'id': 'one', 'formats': [{'url': url, 'protocol': 'http', 'format_id': '720', 'height': 720}]}

    def controller(self, checkpoint=None):
        old = self.info()
        fresh = self.info('http://local.test/clip.mp4?token=new')
        return SourceRefresh(old, None, lambda *_: (fresh, None), checkpoint=checkpoint)

    def response(self, req, etag='"one"', total=1000, status=206, start=500):
        return Response(io.BytesIO(b'x' * 500), req.url,
                        {'ETag': etag, 'Content-Length': str(total - start),
                         'Content-Range': f'bytes {start}-{total-1}/{total}'}, status)

    def test_same_validator_resumes_exact_offset(self):
        ctrl = self.controller()
        ctrl.ledger['direct'][resource(self.info()['formats'][0]['url'])] = ['"one"', 1000]
        calls = []
        def send(req):
            calls.append(req)
            if 'token=old' in req.url:
                raise HTTPError(Response(io.BytesIO(), req.url, {}, 403))
            if req.method == 'HEAD':
                self.assertNotIn('Range', req.headers)
                return Response(io.BytesIO(), req.url, {'ETag': '"one"', 'Content-Length': '1000'})
            self.assertEqual(req.headers['Range'], 'bytes=500-')
            self.assertEqual(req.headers['If-Range'], '"one"')
            return self.response(req)
        result = ctrl.open(Request(self.info()['formats'][0]['url'], headers={'Range': 'bytes=500-'}), send, lambda *_: None)
        self.assertEqual(len(result.read()), 500)
        self.assertEqual([c.method for c in calls], ['GET', 'HEAD', 'GET'])

    def test_changed_or_missing_validator_never_appends(self):
        from source_refresh import resource
        for etag,total in (('"other"',1000), ('W/"one"',1000), ('',1000), ('"one"',1001)):
            with self.subTest(etag=etag,total=total):
                ctrl = self.controller()
                ctrl.ledger['direct'][resource(self.info()['formats'][0]['url'])] = ['"one"', 1000]
                calls = []
                def send(req):
                    calls.append(req.method)
                    if req.method == 'HEAD':
                        return Response(io.BytesIO(), req.url, {'ETag': etag, 'Content-Length': str(total)})
                    raise HTTPError(Response(io.BytesIO(), req.url, {}, 410))
                with self.assertRaises(HlsError):
                    ctrl.open(Request(self.info()['formats'][0]['url'], headers={'Range': 'bytes=500-'}), send, lambda *_: None)
                self.assertEqual(calls, ['GET', 'HEAD'])

    def test_range_ignored_or_wrong_offset_stops(self):
        from source_refresh import resource
        for status, offset in ((200, 500), (206, 0)):
            ctrl = self.controller()
            key = resource(self.info()['formats'][0]['url'])
            ctrl.ledger['direct'][key] = ['"one"', 1000]
            ctrl.refreshed_direct.add(key)
            with self.assertRaises(HlsError):
                ctrl.open(Request(self.info()['formats'][0]['url'], headers={'Range': 'bytes=500-'}),
                          lambda req: self.response(req, status=status, start=offset), lambda *_: None)

    def test_checkpoint_revalidates_after_worker_restart(self):
        from source_refresh import resource
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ledger.json'
            ctrl = self.controller(path)
            ctrl.ledger['direct'][resource(self.info()['formats'][0]['url'])] = ['"one"', 1000]
            ctrl.save()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            resumed = self.controller(path)
            with self.assertRaises(HlsError):
                resumed.open(Request(self.info()['formats'][0]['url'], headers={'Range': 'bytes=500-'}),
                             lambda req: self.response(req, etag='"different"'), lambda *_: None)

    def test_hls_signed_addresses_only(self):
        old = '#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:9\n#EXTINF:1,\na.ts?token=old\n#EXTINF:1,\nb.ts?token=old\n#EXT-X-ENDLIST\n'
        fresh = old.replace('old', 'new')
        self.assertEqual(hls_snapshot(old, 'http://local.test/index.m3u8')[0],
                         hls_snapshot(fresh, 'http://local.test/index.m3u8')[0])
        for changed in (fresh.replace('SEQUENCE:9', 'SEQUENCE:10'), fresh.replace('EXTINF:1', 'EXTINF:2'), fresh.replace('b.ts', 'other.ts')):
            self.assertNotEqual(hls_snapshot(old, 'http://local.test/index.m3u8')[0],
                                hls_snapshot(changed, 'http://local.test/index.m3u8')[0])

    def test_live_or_key_rotation_requires_resolution(self):
        for text in ('#EXTM3U\n#EXTINF:1,\na.ts', '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key"\n#EXTINF:1,\na.ts\n#EXT-X-ENDLIST'):
            with self.assertRaises(HlsError):
                hls_snapshot(text, 'http://local.test/index.m3u8')

    def test_restarted_hls_checks_completed_segment_without_get(self):
        url='http://local.test/index.m3u8?token=new'
        text='#EXTM3U\n#EXTINF:1,\na.ts?token=new\n#EXTINF:1,\nb.ts?token=new\n#EXT-X-ENDLIST\n'
        with tempfile.TemporaryDirectory() as directory:
            ledger=Path(directory)/'ledger.json'
            atomic={'direct':{},'dash':{},'hls':{resource(url):hls_snapshot(text,url)[0]},
                    'segments':{resource('http://local.test/a.ts'):['"segment-one"',1000]}}
            queue_store.atomic_json(ledger,atomic)
            info={'formats':[{'url':url,'protocol':'m3u8_native','format_id':'hls'}]}
            ctrl=SourceRefresh(info,None,lambda *_:None,checkpoint=ledger)
            calls=[]
            def send(req):
                calls.append((req.method,urlsplit(req.url).path))
                if req.method=='HEAD':return Response(io.BytesIO(),req.url,{'ETag':'"changed"','Content-Length':'1000'})
                return Response(io.BytesIO(text.encode()),req.url,{'Content-Length':str(len(text))})
            with self.assertRaises(HlsError):ctrl.open(Request(url),send,lambda *_:None)
            self.assertEqual(calls,[('GET','/index.m3u8'),('HEAD','/a.ts')])

    def test_dash_timeline_representation_and_range_identity(self):
        old = b'<MPD><Period><Representation id="v" codecs="avc1"><SegmentTemplate timescale="10" media="chunk-$Number$.m4s?token=old"><SegmentTimeline><S t="0" d="10" r="2"/></SegmentTimeline></SegmentTemplate></Representation></Period></MPD>'
        fresh = old.replace(b'old', b'new')
        self.assertEqual(dash_snapshot(old, 'http://local.test/index.mpd'), dash_snapshot(fresh, 'http://local.test/index.mpd'))
        for changed in (fresh.replace(b'd="10"', b'd="11"'), fresh.replace(b'id="v"', b'id="other"'), fresh.replace(b'avc1', b'avc2')):
            self.assertNotEqual(dash_snapshot(old, 'http://local.test/index.mpd'), dash_snapshot(changed, 'http://local.test/index.mpd'))

    def test_foreign_video_never_refreshes_selected_item(self):
        ctrl = SourceRefresh(self.info(), None, lambda *_: (self.info('http://local.test/other.mp4'), None))
        def send(req):
            raise HTTPError(Response(io.BytesIO(), req.url, {}, 403))
        with self.assertRaises(HlsError):
            ctrl.open(Request(self.info()['formats'][0]['url']), send, lambda *_: None)

    def test_native_refresh_updates_candidate_only_and_rejects_wrong_item(self):
        from copy import deepcopy
        with tempfile.TemporaryDirectory() as directory:
            queue,lock=Path(directory)/'queue.json',Path(directory)/'queue.lock'
            old=validate_source({'type':'direct_video','url':'http://local.test/clip.mp4?token=old',
                'page_url':'http://local.test/page','tab_id':1,'timestamp':time.time(),
                'content_type':'video/mp4','headers':{},'id':'candidate-one','media_item_id':'item-one'})
            job={'id':'job-one','media_source':old,'downloaded':500,'total':1000,'mode':'best',
                 'output_stem':'selected','status':'downloading',
                 'source_refresh_request':{'nonce':'request-one','candidate_id':'candidate-one'}}
            queue_store.atomic_json(queue,{**queue_store.default_state(),'active':job})
            fresh=deepcopy(old);fresh['url']=fresh['url'].replace('old','new')
            fresh['request_context']['source_url']=fresh['url']
            with patch.object(host,'QUEUE_FILE',queue),patch.object(host,'LOCK_FILE',lock):
                wrong=dict(fresh,media_item_id='other-item')
                self.assertFalse(host.refresh_source('job-one','request-one',wrong)['ok'])
                self.assertFalse(host.refresh_source('job-one','stale',fresh)['ok'])
                self.assertTrue(host.refresh_source('job-one','request-one',fresh)['ok'])
            result=queue_store.read_state(queue,lock)['active']
            self.assertEqual({k:v for k,v in result.items() if k not in ('media_source','source_refresh_ack')},
                             {k:v for k,v in job.items() if k!='media_source'})
            self.assertEqual(result['media_source']['url'],fresh['url'])

    def test_expired_renewed_url_keeps_resolution_error(self):
        ctrl=self.controller()
        def send(req):raise HTTPError(Response(io.BytesIO(),req.url,{},403))
        with self.assertRaises(HlsError) as failure:
            ctrl.open(Request(self.info()['formats'][0]['url']),send,lambda *_:None)
        self.assertEqual(failure.exception.code,'source_identity_unconfirmed')


class TransferTests(base.DashTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()
        cls.large = (cls.media/'normal.mp4').read_bytes() + struct.pack('>I4s', 1048584, b'free') + b'\0'*1048576
        class Handler(BaseHTTPRequestHandler):
            def do_HEAD(self): self.serve(True)
            def do_GET(self): self.serve(False)
            def serve(self, head):
                with cls.lock: cls.requests.append((self.path, dict(self.headers, _method=self.command)))
                parsed = urlsplit(self.path); path = parsed.path
                status = 200; mime = 'video/mp4'; headers = {}; data = b''
                if path == '/refresh-page':
                    token = 'new' if cls.expired else 'old'
                    src = '/signed.mp4' if cls.kind == 'direct' else '/low/index.m3u8' if cls.kind == 'hls' else '/dash/manifest.mpd'
                    data = f'<html><title>One selected video</title><video src="{src}?token={token}"></video></html>'.encode(); mime = 'text/html'
                elif path == '/signed.mp4':
                    data = cls.large; headers['ETag'] = '"different"' if cls.changed and 'new' in parsed.query else '"same-video"'
                    if cls.context_protected and self.headers.get('Cookie')!=('session=new' if cls.expired else 'session=old'):
                        status=401;data=b'Session expired'
                else:
                    file = cls.media / path.lstrip('/')
                    if not file.is_file(): status=404; data=b'Missing'
                    else:
                        data=file.read_bytes()
                        if file.suffix in ('.mp4','.m4s','.ts'):
                            headers['ETag']='"'+hashlib.sha256(data).hexdigest()+'"'
                        if path.endswith('.m3u8'):
                            mime='application/vnd.apple.mpegurl'
                            token='new' if 'new' in parsed.query else 'old'
                            data=re.sub(rb'(seg\d+\.ts)', lambda m:m[1]+b'?token='+token.encode(), data)
                            if cls.changed and token=='new':data=data.replace(b'#EXTINF:1.000000', b'#EXTINF:2.000000')
                        elif path.endswith('.mpd'):
                            mime='application/dash+xml'
                            token='new' if 'new' in parsed.query else 'old'
                            data=re.sub(rb'(initialization|media)="([^"]+)"', lambda m:m[1]+b'="'+m[2]+b'?token='+token.encode()+b'"', data)
                            if cls.changed and token=='new':data=data.replace(b'startNumber="1"',b'startNumber="2"')
                if cls.armed and not head and 'old' in parsed.query:
                    should_expire = (cls.expired and not cls.context_protected) or (path.endswith('seg001.ts')) or ('chunk-' in path and '00002' in path)
                    if should_expire:
                        cls.expired=True; status=403; data=b'Expired'
                full=len(data); match=re.fullmatch(r'bytes=(\d+)-(\d*)',self.headers.get('Range',''))
                if match and status==200:
                    start=int(match[1]); end=min(int(match[2]) if match[2] else full-1, full-1)
                    status=206; data=data[start:end+1]; headers['Content-Range']=f'bytes {start}-{end}/{full}'
                self.send_response(status); self.send_header('Content-Type',mime); self.send_header('Content-Length',str(len(data)))
                for k,v in headers.items(): self.send_header(k,v)
                self.end_headers()
                if head:return
                try:
                    if cls.armed and cls.kind=='direct' and 'old' in parsed.query and status==200:
                        self.wfile.write(data[:131072]);self.wfile.flush();cls.expired=True;self.close_connection=True
                    else:self.wfile.write(data)
                except (BrokenPipeError,ConnectionResetError):pass
            def log_message(self,*_):pass
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);cls.base=f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()

    def setUp(self):
        super().setUp()
        type(self).armed=False;type(self).expired=False;type(self).changed=False;type(self).kind='direct'
        type(self).context_protected=False
        original=worker.extract_metadata
        def metadata(*args,**kwargs):
            value=original(*args,**kwargs)
            if (args[1].get('media_source') or {}).get('url','').endswith('token=old'):
                type(self).armed=True
            if args[1].get('url','').endswith('/refresh-page'):
                type(self).armed=True
            return value
        self.stack.enter_context(patch.object(worker,'extract_metadata',metadata))
        original_options=worker.build_opts
        def options(*args,**kwargs):
            result=original_options(*args,**kwargs);result['postprocessors']=[];result['writethumbnail']=False
            return result
        self.stack.enter_context(patch.object(worker,'build_opts',options))

    def signed_source(self, kind):
        type(self).kind=kind
        path,mime,source_type={'direct':('/signed.mp4','video/mp4','direct_video'),
                              'hls':('/low/index.m3u8','application/vnd.apple.mpegurl','hls'),
                              'dash':('/dash/manifest.mpd','application/dash+xml','dash')}[kind]
        return validate_source({'type':source_type,'url':self.base+path+'?token=old',
            'page_url':self.base+'/refresh-page','tab_id':1,'timestamp':time.time(),
            'title':'Selected video','headers':{},'content_type':mime})

    def test_direct_expiry_after_128k_keeps_job_and_bytes(self):
        updates=[]; original=worker.update_active
        def update(**fields):updates.append(fields);return original(**fields)
        with patch.object(worker,'update_active',update):
            entry,_=self.successful(source=self.signed_source('direct'),mode='720')
        self.assertEqual(entry['id'],'fixture');self.assertEqual(entry['source_refresh_count'],1)
        self.assertEqual(Path(entry['filepath']).read_bytes(),self.large)
        ranges=[h['Range'] for p,h in self.requests if p.startswith('/signed.mp4?token=new') and h.get('_method')=='GET']
        self.assertEqual(ranges,['bytes=131072-'])
        self.assertFalse(any(u.get('downloaded') is None and 'downloaded' in u for u in updates))
        self.assertEqual(entry['url'],self.base+'/signed.mp4?token=old')

    def test_direct_changed_identity_preserves_partial(self):
        type(self).changed=True
        result,entry=self.job(source=self.signed_source('direct'),mode='720')
        self.assertEqual(result,1);self.assertEqual(entry['error_code'],'source_identity_unconfirmed')
        parts=list(self.output.glob('*.part'));self.assertEqual(len(parts),1)
        self.assertEqual(parts[0].read_bytes(),self.large[:131072])
        self.assertFalse(any('token=new' in p and h.get('_method')=='GET' and p.startswith('/signed.mp4') for p,h in self.requests))

    def test_ordinary_page_expiry_keeps_original_job(self):
        entry,_=self.successful(url=self.base+'/refresh-page',mode='720')
        self.assertEqual(entry['id'],'fixture');self.assertEqual(entry['source_refresh_count'],1)
        self.assertEqual(entry['url'],self.base+'/refresh-page')
        self.assertEqual(Path(entry['filepath']).read_bytes(),self.large)

    def test_hls_replaced_segment_with_same_timeline_is_rejected(self):
        original=SourceRefresh.validator
        def validator(response):
            value=original(response)
            if 'seg000.ts?token=new' in response.url:value[0]='"replaced"'
            return value
        with patch.object(SourceRefresh,'validator',staticmethod(validator)):
            result,entry=self.job(source=self.signed_source('hls'),mode='720')
        self.assertEqual(result,1);self.assertEqual(entry['error_code'],'source_identity_unconfirmed')
        self.assertTrue(list(self.output.glob('*.part')))
        self.assertFalse(any('seg001.ts?token=new' in p and h['_method']=='GET' for p,h in self.requests))

    def test_browser_refresh_same_url_new_session_keeps_job(self):
        type(self).context_protected=True
        source=self.signed_source('direct');source.update(id='candidate-one',media_item_id='item-one')
        source['request_context']['cookies']='session=old'
        stop=threading.Event();results=[]
        def browser():
            while not stop.wait(.05):
                current=worker.get_state().get('active') or {}
                pending=current.get('source_refresh_request')
                if pending:
                    from copy import deepcopy
                    fresh=deepcopy(source);fresh['request_context']['cookies']='session=new'
                    results.append(host.refresh_source(current['id'],pending['nonce'],fresh))
                    return
        with patch.object(host,'QUEUE_FILE',worker.QUEUE_FILE),patch.object(host,'LOCK_FILE',worker.LOCK_FILE):
            thread=threading.Thread(target=browser);thread.start()
            try:entry,_=self.successful(source=source,mode='720')
            finally:stop.set();thread.join(2)
        self.assertTrue(results and results[0]['ok'],results)
        self.assertEqual(entry['id'],'fixture');self.assertEqual(entry['source_refresh_count'],1)
        self.assertEqual(Path(entry['filepath']).read_bytes(),self.large)
        self.assertTrue(any(h.get('Cookie')=='session=new' and h.get('Range')=='bytes=131072-' for _,h in self.requests))
        self.assertNotIn('session=', '\n'.join(self.logs))

    def test_hls_expiry_preserves_completed_segment(self):
        entry,_=self.successful(source=self.signed_source('hls'),mode='720')
        self.assertEqual(entry['id'],'fixture');self.assertEqual(entry['source_refresh_count'],1)
        self.assertEqual(sum('seg000.ts' in p and h['_method']=='GET' for p,h in self.requests),1)
        self.assertEqual(sum('seg001.ts?token=new' in p for p,_ in self.requests),1)

    def test_hls_changed_timeline_preserves_partial_and_ledger(self):
        type(self).changed=True
        result,entry=self.job(source=self.signed_source('hls'),mode='720')
        self.assertEqual(result,1);self.assertEqual(entry['error_code'],'source_identity_unconfirmed')
        self.assertTrue(list(self.output.glob('*.part')));self.assertTrue(list(self.output.glob('*.ytdl')))
        self.assertEqual(sum('seg000.ts' in p for p,_ in self.requests),1)
        self.assertFalse(any('seg001.ts?token=new' in p for p,_ in self.requests))

    def test_dash_expiry_preserves_video_audio_segments(self):
        entry,_=self.successful(source=self.signed_source('dash'),mode='720')
        self.assertEqual(entry['id'],'fixture');self.assertEqual(entry['source_refresh_count'],1)
        first=[p for p,h in self.requests if h['_method']=='GET' and ('init-' in p or 'chunk-' in p and '00001' in p)]
        self.assertTrue(first)
        self.assertEqual(len(first),len({urlsplit(p).path for p in first}))
        self.assertTrue(any('chunk-' in p and '00002' in p and 'token=new' in p for p,_ in self.requests))

    def test_dash_changed_timeline_does_not_append(self):
        type(self).changed=True
        result,entry=self.job(source=self.signed_source('dash'),mode='720')
        self.assertEqual(result,1);self.assertEqual(entry['error_code'],'source_identity_unconfirmed')
        self.assertTrue(list(self.output.glob('*.part')))
        self.assertFalse(any('chunk-' in p and 'token=new' in p for p,_ in self.requests))


for name in base.DashTests.__dict__:
    if name.startswith('test_') and name not in TransferTests.__dict__:setattr(TransferTests,name,None)

if __name__=='__main__':unittest.main(verbosity=2)
