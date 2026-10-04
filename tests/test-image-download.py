"""Real yt-dlp against a local fixture: only image requests, no media bytes.

Set KITTY_IMAGE_NATIVE_DIR to exercise an installed private backend. All state,
files and HTTP traffic are isolated; no external site or user queue is used.
"""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get("KITTY_IMAGE_NATIVE_DIR", str(ROOT / "native-host")))
handlers = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
import worker
for signum, handler in handlers.items():
    signal.signal(signum, handler)
import image_download
import queue_store
import yt_dlp
from yt_dlp.extractor.common import InfoExtractor


def png(width=3, height=2):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\x00" + b"\x20\x80\xc0" * width) * height))
            + chunk(b"IEND", b""))


class ImageDownloadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="kitty-image-tests-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.output = self.root / "sortie française & 100% !"
        self.output.mkdir()
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests.append(self.path)
                status, data, mime = 200, png(), "image/png"
                if self.path == "/missing.png":
                    status, data = 404, b"missing"
                elif self.path == "/bad.png":
                    data, mime = b"<html>Not an image</html>", "text/html"
                elif self.path.startswith("/media"):
                    status, data = 500, b"MEDIA MUST NEVER BE REQUESTED"
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

        class FixtureIE(InfoExtractor):
            _VALID_URL = r"http://127\.0\.0\.1:\d+/kitty/(?P<id>[a-z-]+)"
            IE_NAME = "kitty-image-fixture"

            def _real_extract(self, url):
                kind = self._match_id(url)
                info = {"id": kind, "title": "Pochette française & 100%", "ext": "webm",
                        "formats": [{"url": owner.base + "/media.webm", "ext": "webm",
                                     "vcodec": "vp9", "acodec": "opus"}],
                        "thumbnails": [{"url": owner.base + "/cover.png", "width": 600, "height": 400}]}
                if kind == "audio-only":
                    info["formats"][0]["vcodec"] = "none"
                elif kind == "missing":
                    info["thumbnails"] = []
                elif kind == "bad":
                    info["thumbnails"] = [{"url": owner.base + "/bad.png"}]
                elif kind == "fallback":
                    info["thumbnails"].append({"url": owner.base + "/missing.png", "width": 1200})
                elif kind == "wrong-extension":
                    info["thumbnails"] = [{"url": owner.base + "/cover.jpg"}]
                elif kind == "cover-only":
                    info["formats"] = []
                elif kind == "collection":
                    info["_type"] = "playlist"
                    info["entries"] = [{"_type": "url", "url": owner.base + "/media.webm"}]
                return info

        original = yt_dlp.YoutubeDL

        class FixtureYDL(original):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, auto_init=False, **kwargs)
                self.add_info_extractor(FixtureIE())

        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(yt_dlp, "YoutubeDL", FixtureYDL))
        for name, value in {"QUEUE_FILE": self.root / "queue.json", "LOCK_FILE": self.root / "queue.lock",
                            "CONTROL_DIR": self.root / "controls", "AUTH_JOB_DIR": self.root / "auth",
                            "log": lambda *_args: None, "configure_worker_job": lambda: None,
                            "watch_worker_controls": lambda *_args: threading.Event(),
                            "start_next_if_any": lambda: None, "cancel_requested": False,
                            "external_stop_requested": False}.items():
            self.stack.enter_context(patch.object(worker, name, value))

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def run_job(self, kind="normal", *, mode="image"):
        state = queue_store.default_state()
        state["queue_paused"] = True
        state["active"] = {"id": "fixture", "url": self.base + "/kitty/" + kind,
                           "mode": mode, "status": "starting", "output_dir": str(self.output)}
        queue_store.atomic_json(worker.QUEUE_FILE, state)
        with patch.object(sys, "argv", ["worker.py", "fixture"]):
            result = worker.main()
        final = worker.get_state()
        self.assertIsNone(final["active"])
        self.assertFalse(any(path.startswith("/media") for path in self.requests), self.requests)
        return result, final["history"][0]

    def assert_image(self, kind="normal"):
        result, entry = self.run_job(kind)
        self.assertEqual(result, 0, entry)
        self.assertEqual(entry["status"], "finished", entry)
        self.assertEqual(entry["mode"], "image")
        self.assertFalse(entry.get("already_present"), entry)
        self.assertEqual(entry["title"], "Pochette française & 100%")
        image = Path(entry["filepath"])
        self.assertEqual(image.suffix, ".png")
        self.assertEqual(image.read_bytes(), png())
        self.assertEqual(entry["downloaded"], len(png()))
        self.assertEqual(list(self.output.iterdir()), [image])
        return image

    def test_image_only_no_audio_or_video_bytes(self):
        self.assert_image()
        self.assertEqual(self.requests, ["/cover.png"])

    def test_audio_only_media_still_has_a_cover(self):
        self.assert_image("audio-only")

    def test_thumbnail_without_downloadable_formats(self):
        self.assert_image("cover-only")

    def test_collection_cover_without_reading_entries(self):
        self.assert_image("collection")

    def test_highest_resolution_missing_falls_back(self):
        self.assert_image("fallback")
        self.assertEqual(self.requests, ["/missing.png", "/cover.png"])

    def test_original_format_detected_when_url_extension_is_wrong(self):
        self.assert_image("wrong-extension")

    def test_no_thumbnail_is_a_clear_error_and_writes_nothing(self):
        result, entry = self.run_job("missing")
        self.assertEqual(result, 1)
        self.assertEqual(entry["error_code"], "image_unavailable")
        self.assertEqual(self.requests, [])
        self.assertEqual(list(self.output.iterdir()), [])

    def test_html_response_is_rejected_and_removed(self):
        result, entry = self.run_job("bad")
        self.assertEqual(result, 1)
        self.assertEqual(entry["error_code"], "image_invalid")
        self.assertEqual(list(self.output.iterdir()), [])

    def test_existing_file_is_kept_and_new_image_has_unique_name(self):
        old = self.output / "Pochette française & 100%.png"
        old.write_bytes(b"existing file")
        result, entry = self.run_job()
        self.assertEqual(result, 0, entry)
        self.assertEqual(old.read_bytes(), b"existing file")
        self.assertTrue(Path(entry["filepath"]).stem.endswith(" (2)"), entry)

    def test_cancel_during_image_transfer_removes_only_job_files(self):
        original = yt_dlp.YoutubeDL._write_thumbnails

        def cancel_after_write(ydl, *args, **kwargs):
            result = original(ydl, *args, **kwargs)
            worker.CONTROL_DIR.mkdir(exist_ok=True)
            queue_store.atomic_json(worker.control_path("fixture"), {"action": "cancel"})
            return result

        unrelated = self.output / "unrelated.png"
        unrelated.write_bytes(png())
        with patch.object(yt_dlp.YoutubeDL, "_write_thumbnails", cancel_after_write):
            result, entry = self.run_job()
        self.assertEqual(result, 0, entry)
        self.assertEqual(entry["status"], "cancelled")
        self.assertEqual(list(self.output.iterdir()), [unrelated])

    def test_thumbnail_urls_are_limited_to_http_and_https(self):
        for url in ["file:///etc/passwd", "data:image/png;base64,abc", "javascript:alert(1)", "https://[broken"]:
            self.assertEqual(image_download.image_thumbnails({"thumbnail": url}), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
