"""Reproducible frontend XPI and backend-only installer archives."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COMMON = ("backend.json", "LICENSE", "THIRD-PARTY-NOTICES.md")
PLATFORMS = {
    "linux": ("install.sh",),
    "windows-x64": ("Install.cmd", "Install.ps1"),
    "macos": ("Install.command", "Uninstall.command"),
}


def backend_files(platform):
    yield from (ROOT / name for name in (*COMMON, *PLATFORMS[platform]))
    yield from sorted((ROOT / "native-host").glob("*.py"))
    yield ROOT / "native-host/manifest.json"


def stage_backend(platform, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    for origin in backend_files(platform):
        target = destination / origin.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
    return destination


def write_archive(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for origin, name in entries:
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 3, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (origin.stat().st_mode & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(info, origin.read_bytes())


def build(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    version = json.loads((ROOT / "backend.json").read_text())["version"]
    checksums = []
    for platform in PLATFORMS:
        path = output / f"kitty-backend-v{version}-{platform}.zip"
        write_archive(path, ((file, "kitty-download-manager/" + file.relative_to(ROOT).as_posix())
                             for file in backend_files(platform)))
        checksums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    frontend = json.loads((ROOT / "extension/manifest.json").read_text())["version"]
    xpi = output / f"kitty-download-manager-v{frontend}-unsigned.xpi"
    write_archive(xpi, ((file, file.relative_to(ROOT / "extension").as_posix())
                       for file in sorted((ROOT / "extension").rglob("*"))
                       if file.is_file() and "__pycache__" not in file.parts))
    checksums.append(f"{hashlib.sha256(xpi.read_bytes()).hexdigest()}  {xpi.name}")
    (output / "SHA256SUMS").write_text("\n".join(checksums) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    build(args.output)
