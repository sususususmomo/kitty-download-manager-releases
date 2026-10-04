"""Build verified Kitty releases; keep GitHub Latest reserved for the backend."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
REPO = "sususususmomo/kitty-download-manager-releases"
VERSION = re.compile(r"\d+(?:\.\d+){1,3}\Z")
MODES = ("dry-run", "draft", "publish")
KINDS = ("both", "frontend", "backend")
INSTALLERS = ("install.sh", "uninstall.sh", "update.sh", "Install.cmd",
              "Install.ps1", "Install.command", "Uninstall.command",
              "backend.json", "THIRD-PARTY-NOTICES.md")


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def gh(*args):
    return run("gh", *args)


def api(path):
    return json.loads(gh("api", f"repos/{REPO}/{path}"))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def versions():
    frontend = json.loads((ROOT / "extension/manifest.json").read_text())["version"]
    backend = json.loads((ROOT / "backend.json").read_text())["version"]
    if not VERSION.fullmatch(frontend) or not VERSION.fullmatch(backend):
        raise ValueError("Invalid release version")
    return frontend, backend


def tested_path(path):
    return (path in INSTALLERS or path.startswith(("extension/", "native-host/"))
            or (path.startswith("tests/") and path != "tests/test-releases.py")
            or path in ("test.sh", "tools/build-packages.py", "tools/install-backend-for-ci.py"))


def tracked_files():
    return subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")[:-1]


def verify_proof(frontend, backend):
    """Reuse OS validation only when every application and test blob is unchanged."""
    proof_path = ROOT / f"docs/validation-frontend-v{frontend}.json"
    proof = json.loads(proof_path.read_text())
    if (proof.get("frontend_version"), proof.get("backend_version")) != (frontend, backend):
        raise ValueError("Validation versions differ from packaged versions")
    commit = proof["tested_application_commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Validation needs a full commit SHA")
    tree = api(f"git/trees/{commit}?recursive=1")
    if tree.get("truncated"):
        raise ValueError("Incomplete validation tree")
    expected = {x["path"]: (x["sha"], x["mode"]) for x in tree["tree"]
                if x["type"] == "blob" and tested_path(x["path"])}
    actual = {}
    for path in tracked_files():
        if tested_path(path):
            file = ROOT / path
            data = file.read_bytes()
            digest = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            actual[path] = (digest, "100755" if file.stat().st_mode & 0o111 else "100644")
    if expected != actual:
        changed = sorted(p for p in expected.keys() | actual.keys() if expected.get(p) != actual.get(p))
        raise ValueError("Application changed since OS validation: " + ", ".join(changed))
    workflows = {"windows_run": ".github/workflows/windows-validation.yml",
                 "macos_run": ".github/workflows/macos-validation.yml",
                 "publication_checks_run": ".github/workflows/backend-downloads.yml"}
    for key, workflow_path in workflows.items():
        url = proof[key]
        match = re.fullmatch(rf"https://github.com/{re.escape(REPO)}/actions/runs/(\d+)", url)
        if not match:
            raise ValueError("Invalid validation workflow URL")
        workflow = api(f"actions/runs/{match[1]}")
        if (workflow["head_sha"] != commit or workflow["conclusion"] != "success"
                or workflow["event"] not in ("push", "workflow_dispatch")
                or workflow["path"] != workflow_path
                or workflow["head_repository"]["full_name"] != REPO):
            raise ValueError("OS/publication validation did not succeed for this source: " + url)
    print("Unchanged application matches successful Windows, macOS and publication checks.")
    return proof_path


def request():
    data = json.loads((ROOT / ".github/release-request.json").read_text())
    mode = os.environ.get("RELEASE_MODE") or data["mode"]
    kind = os.environ.get("RELEASE_KIND") or data["kind"]
    if mode not in MODES or kind not in KINDS:
        raise ValueError("Unknown release mode or component")
    # Branch builds can never create drafts, publish, or move Latest.
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        mode = "dry-run"
    return mode, kind


def asset(path):
    return {"name": path.name, "sha256": sha256(path), "size": path.stat().st_size}


def prepare(output):
    frontend, backend = versions()
    mode, kind = request()
    proof_path = verify_proof(frontend, backend)
    source = run("git", "-C", str(ROOT), "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("Source must be a full commit SHA")
    output = output.resolve()
    if output.exists():
        raise ValueError("Use a fresh output directory")
    output.mkdir(parents=True)
    spec = importlib.util.spec_from_file_location("packages", ROOT / "tools/build-packages.py")
    packages = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packages)
    packages.ROOT = ROOT
    manifest = {"repository": REPO, "source_commit": source, "mode": mode,
                "kind": kind, "backend_version": backend, "proof_verified": True, "releases": []}
    with tempfile.TemporaryDirectory() as directory:
        built = Path(directory)
        packages.build(built)
        for component, version in (("frontend", frontend), ("backend", backend)):
            if kind not in ("both", component):
                continue
            folder = output / component
            folder.mkdir()
            if component == "backend":
                for platform in packages.PLATFORMS:
                    suffix = "" if platform == "linux" else "-" + platform
                    origin = built / f"kitty-backend-v{version}-{platform}.zip"
                    shutil.copyfile(origin, folder / f"kitty-download-manager-v{version}{suffix}.zip")
            else:
                xpi = built / f"kitty-download-manager-v{version}-unsigned.xpi"
                shutil.copyfile(xpi, folder / xpi.name)
                # Keep the existing one-folder installation command. No generated
                # files, old ZIPs, local media, request switch, or private state.
                entries = []
                for path in sorted(tracked_files()):
                    file = ROOT / path
                    if (file.suffix.lower() in (".zip", ".xpi", ".pyc")
                            or path == ".github/release-request.json"):
                        continue
                    entries.append((file, "kitty-download-manager/" + path))
                entries.append((xpi, "kitty-download-manager/" + xpi.name))
                packages.write_archive(folder / f"kitty-download-manager-v{version}.zip", entries)
                shutil.copyfile(proof_path, folder / proof_path.name)
            files = sorted(folder.iterdir())
            (folder / "SHA256SUMS").write_text("".join(f"{sha256(f)}  {f.name}\n" for f in files))
            files = sorted(folder.iterdir())
            notes = ROOT / f"docs/releases/{component}-v{version}.md"
            shutil.copyfile(notes, folder / "NOTES.md")
            tag = f"frontend-v{version}" if component == "frontend" else f"v{version}"
            manifest["releases"].append({"kind": component, "tag": tag,
                "title": f"Kitty {'Firefox' if component == 'frontend' else 'Backend'} v{version}",
                "latest": component == "backend", "assets": [asset(f) for f in files]})
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    destination = os.environ.get("GITHUB_OUTPUT")
    if destination:
        with open(destination, "a") as stream:
            stream.write(f"mode={mode}\n")
    print(json.dumps(manifest, indent=2))
    return manifest


def check_assets(release, expected, allow_missing=False):
    actual = {a["name"]: a for a in release["assets"]}
    wanted = {a["name"]: a for a in expected}
    if actual.keys() - wanted.keys():
        raise ValueError("Unexpected assets in existing release; refusing to overwrite it")
    missing = []
    for name, file in wanted.items():
        remote = actual.get(name)
        if remote is None:
            missing.append(name)
        elif (remote["size"] != file["size"] or remote.get("digest") != "sha256:" + file["sha256"]
              or remote.get("state") != "uploaded"):
            raise ValueError("Release asset differs from verified build: " + name)
    if missing and not allow_missing:
        raise ValueError("Missing release assets: " + ", ".join(missing))
    return missing


def release_list():
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{REPO}/releases?per_page=100"))
    return {r["tag_name"]: r for page in pages for r in page}


def find_release(tag):
    # A successful draft creation can precede its visibility in the list API.
    # Retry reads, never the creation request, to avoid duplicate drafts.
    for attempt in range(10):
        remote = release_list().get(tag)
        if remote:
            return remote
        if attempt < 9:
            time.sleep(2)
    raise ValueError("Created draft is not yet visible in GitHub: " + tag)


def publish(output):
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("Release writes are restricted to main")
    manifest = json.loads((output / "manifest.json").read_text())
    mode = os.environ.get("RELEASE_MODE", "dry-run")
    if mode not in ("draft", "publish") or mode != manifest["mode"]:
        raise ValueError("Publication mode must match verified preparation")
    if manifest["repository"] != REPO or not manifest.get("proof_verified"):
        raise ValueError("Unverified release manifest")
    if manifest["source_commit"] != os.environ.get("GITHUB_SHA"):
        raise ValueError("Artifacts are not from the current workflow commit")
    releases = manifest["releases"]
    # Preflight every component before any remote mutation.
    remote_releases = release_list()
    for item in releases:
        if item["kind"] not in ("frontend", "backend") or item["latest"] != (item["kind"] == "backend"):
            raise ValueError("Only a backend release can become Latest")
        prefix = "frontend-v" if item["kind"] == "frontend" else "v"
        if not item["tag"].startswith(prefix) or not VERSION.fullmatch(item["tag"][len(prefix):]):
            raise ValueError("Invalid release tag")
        folder = output / item["kind"]
        for file in item["assets"]:
            name = file["name"]
            if Path(name).name != name or asset(folder / name) != file:
                raise ValueError("Packaged asset changed: " + name)
        remote = remote_releases.get(item["tag"])
        if remote:
            if remote.get("prerelease"):
                raise ValueError("Existing tag is a prerelease")
            check_assets(remote, item["assets"], allow_missing=remote["draft"])
    if mode == "publish":
        published = [r for r in remote_releases.values() if not r["draft"] and not r["prerelease"]]
        if published:
            latest = api("releases/latest")
            current = latest["tag_name"].removeprefix("v")
            proposed = manifest["backend_version"]
            if not VERSION.fullmatch(current) or tuple(map(int, current.split("."))) > tuple(map(int, proposed.split("."))):
                raise ValueError("Refusing to replace a newer/unrecognized Latest release")
    # Frontend first, backend last: publishing the UI never promotes it to Latest.
    for item in sorted(releases, key=lambda r: r["kind"] == "backend"):
        tag, folder = item["tag"], output / item["kind"]
        remote = remote_releases.get(tag)
        if remote is None:
            # A tag without a release is not silently reused or moved.
            tag_refs = json.loads(gh("api", f"repos/{REPO}/git/matching-refs/tags/{tag}"))
            if any(ref["ref"] == "refs/tags/" + tag for ref in tag_refs):
                raise ValueError("Existing tag without a release: " + tag)
            gh("release", "create", tag, "--repo", REPO, "--draft", "--latest=false",
               "--target", manifest["source_commit"], "--title", item["title"],
               "--notes-file", str(folder / "NOTES.md"))
            remote = find_release(tag)
        if remote["draft"]:
            if not remote["assets"] and remote.get("target_commitish") != manifest["source_commit"]:
                gh("release", "edit", tag, "--repo", REPO, "--draft", "--latest=false",
                   "--target", manifest["source_commit"], "--title", item["title"],
                   "--notes-file", str(folder / "NOTES.md"))
                remote = api(f"releases/{remote['id']}")
            missing = check_assets(remote, item["assets"], allow_missing=True)
            if missing:
                gh("release", "upload", tag, *[str(folder / name) for name in missing], "--repo", REPO)
            for attempt in range(5):
                remote = api(f"releases/{remote['id']}")
                try:
                    check_assets(remote, item["assets"])
                    break
                except ValueError:
                    if attempt == 4:
                        raise
                    time.sleep(2)
            if mode == "publish":
                gh("release", "edit", tag, "--repo", REPO, "--draft=false",
                   "--latest=" + str(item["latest"]).lower())
                remote = api(f"releases/{remote['id']}")
                if remote["draft"]:
                    raise ValueError("Release is still a draft after publication")
        else:
            print(f"{tag}: existing public assets verified; preserved.")
        print(remote["html_url"])
    if mode == "publish" and any(r["kind"] == "backend" for r in releases):
        latest = api("releases/latest")
        if latest["tag_name"] != "v" + manifest["backend_version"]:
            raise ValueError("Backend release is not Latest")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as stream:
            stream.write(f"Kitty releases: **{mode}**. Uploaded assets verified against local SHA-256.\n\n")
            for item in releases:
                stream.write(f"- [{item['title']}](https://github.com/{REPO}/releases/tag/{item['tag']})\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "publish"))
    parser.add_argument("--output", type=Path, default=Path("release-dist"))
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.output)
    else:
        publish(args.output)
