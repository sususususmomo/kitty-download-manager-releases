"""Exercise the same backend-only files distributed on GitHub."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

spec = importlib.util.spec_from_file_location("kitty_packages", Path(__file__).with_name("build-packages.py"))
packages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packages)
platform = "macos" if sys.platform == "darwin" else "windows-x64" if sys.platform == "win32" else "linux"
with tempfile.TemporaryDirectory(prefix="kitty-backend-ci-") as directory:
    source = packages.stage_backend(platform, Path(directory) / "kitty-download-manager")
    assert not (source / "extension").exists()
    command = (["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(source / "Install.ps1")]
               if platform == "windows-x64" else ["/bin/bash", str(source / ("Install.command" if platform == "macos" else "install.sh"))])
    result = subprocess.run(command, cwd=source)
    sys.exit(result.returncode)
