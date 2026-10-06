"""Production metadata supervisor and FFmpeg/ffprobe timeout adapters."""
import importlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'native-host'))
import metadata_guard
handlers={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
import worker
for signum,handler in handlers.items():signal.signal(signum,handler)


class ProductionTimeoutTests(unittest.TestCase):
 @unittest.skipUnless(os.name=='posix','POSIX process group')
 def test_metadata_supervisor_stops_its_descendants(self):
  original=subprocess.Popen
  with tempfile.TemporaryDirectory() as temp:
   heartbeat=Path(temp)/'heartbeat'
   child=('import time; from pathlib import Path; '
          f'p=Path({str(heartbeat)!r}); end=time.monotonic()+3; '
          '\nwhile time.monotonic()<end: p.write_text(str(time.monotonic())); time.sleep(.03)')
   parent=f'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",{child!r}]); time.sleep(60)'
   processes=[]
   def spawn(_command,**kwargs):
    process=original([sys.executable,'-c',parent],**kwargs);processes.append(process);return process
   with patch.object(metadata_guard.subprocess,'Popen',spawn):
    with self.assertRaises(metadata_guard.MetadataError) as caught:
     metadata_guard.extract_metadata({}, {'url':'https://example.test'},timeout=.6)
   self.assertEqual(caught.exception.code,'metadata_timeout')
   self.assertIsNotNone(processes[0].returncode)
   self.assertTrue(heartbeat.is_file(),'The descendant must actually start')
   stopped_at=heartbeat.stat().st_mtime_ns;time.sleep(.3)
   self.assertEqual(heartbeat.stat().st_mtime_ns,stopped_at,'A metadata descendant survived timeout')
 def test_yt_dlp_ffmpeg_postprocessor_is_bounded(self):
  from yt_dlp.postprocessor import ffmpeg
  metadata_guard.install_ffmpeg_timeouts()
  with patch.object(metadata_guard,'FFMPEG_TIMEOUT',.2):
   started=time.monotonic()
   with self.assertRaises(metadata_guard.MetadataError) as caught:
    ffmpeg.Popen.run([sys.executable,'-c','import time;time.sleep(60)'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
   self.assertEqual(caught.exception.code,'processing_timeout');self.assertLess(time.monotonic()-started,2)
 @unittest.skipUnless(os.name=='posix','Executable shell fixture requires POSIX')
 def test_local_ffprobe_is_bounded(self):
  with tempfile.TemporaryDirectory() as temp:
   executable=Path(temp)/'ffprobe';executable.write_text('#!'+sys.executable+'\nimport time\ntime.sleep(60)\n');executable.chmod(0o755)
   with patch.object(worker.shutil,'which',lambda name:str(executable)),patch.object(worker,'FFPROBE_TIMEOUT',.2):
    started=time.monotonic()
    with self.assertRaises(metadata_guard.MetadataError) as caught:worker.probe_media_streams(Path(temp)/'video.mp4')
    self.assertEqual(caught.exception.code,'processing_timeout');self.assertLess(time.monotonic()-started,2)
 @unittest.skipUnless(os.name=='posix','Executable shell fixture requires POSIX')
 def test_version_detection_is_bounded(self):
  metadata_guard.install_ffmpeg_timeouts()
  from yt_dlp.utils import _utils
  with tempfile.TemporaryDirectory() as temp:
   executable=Path(temp)/'ffmpeg';executable.write_text('#!'+sys.executable+'\nimport time\ntime.sleep(60)\n');executable.chmod(0o755)
   with patch.object(metadata_guard,'FFPROBE_TIMEOUT',.2):
    started=time.monotonic()
    with self.assertRaises(subprocess.TimeoutExpired):_utils.Popen.run([str(executable),'-version'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    self.assertLess(time.monotonic()-started,2)
 def test_metadata_options_cannot_serialize_callbacks(self):
  result=metadata_guard._json_options({'format':'best','logger':object(),'progress_hooks':[lambda:None],'compat_opts':set()})
  self.assertEqual(result,{'format':'best'})
 def test_metadata_budget_validation(self):
  for timeout in (0,-1,float('nan'),float('inf')):
   with self.assertRaises(ValueError):metadata_guard.extract_metadata({}, {'url':'https://example.test'},timeout=timeout)


if __name__=='__main__':unittest.main(verbosity=2)
