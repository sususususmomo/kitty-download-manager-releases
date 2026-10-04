"""Verify the public files used by the extension's Download button."""
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://github.com/sususususmomo/kitty-download-manager-releases/raw/refs/heads/backend-installers-v8.32/"
checksums = json.loads((ROOT / "tests/backend-download-checksums.json").read_text())
with tempfile.TemporaryDirectory(prefix="kitty-download-test-") as directory:
    for filename, expected in checksums.items():
        request = Request(BASE + filename, headers={"User-Agent": "Kitty-backend-validation"})
        with urlopen(request, timeout=60) as response:
            data = response.read(2 * 1024 * 1024)
            if response.read(1):
                raise RuntimeError("Archive inattendue ou trop grande")
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError("Archive GitHub différente : " + filename)
        path = Path(directory) / filename
        path.write_bytes(data)
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("Archive corrompue")
            names = archive.namelist()
            if any("/extension/" in name or name.endswith(".xpi") for name in names):
                raise RuntimeError("L’archive backend contient une extension")
            metadata = json.loads(archive.read("kitty-download-manager/backend.json"))
            if metadata != {"version": "8.32", "protocol": 1}:
                raise RuntimeError("Métadonnées backend inattendues")
        print(f"Téléchargement public vérifié : {filename} · {len(data)} octets · SHA-256 OK", flush=True)
