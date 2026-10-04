"""Release packaging, validated-source gate, and safe/resumable publication."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("kitty_release", ROOT / "tools/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
FRONTEND_VERSION, BACKEND_VERSION = release.versions()
PROOF = ROOT / f"docs/validation-frontend-v{FRONTEND_VERSION}.json"


def proof_api():
    proof = json.loads(PROOF.read_text())
    tree = []
    for path in release.tracked_files():
        if release.tested_path(path):
            file = ROOT / path
            data = file.read_bytes()
            tree.append({"path": path, "type": "blob", "mode": "100755" if file.stat().st_mode & 0o111 else "100644",
                         "sha": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()})

    def read(path):
        if path.startswith("git/trees/"):
            return {"tree": tree, "truncated": False}
        workflow_paths = {"windows_run": ".github/workflows/windows-validation.yml",
                          "macos_run": ".github/workflows/macos-validation.yml",
                          "publication_checks_run": ".github/workflows/backend-downloads.yml"}
        workflow_path = next(value for key, value in workflow_paths.items() if path.endswith(proof[key].split("/")[-1]))
        return {"head_sha": proof["tested_application_commit"], "conclusion": "success", "event": "push",
                "path": workflow_path,
                "head_repository": {"full_name": release.REPO}}
    return read


class FakeGitHub:
    """Record writes and expose the same digest fields as GitHub releases."""
    def __init__(self):
        self.releases = {}
        self.writes = []
        self.latest = "v8.18"
        self.corrupt_upload = False
        self.visibility_delay = 0
        self.remaining_hidden_reads = 0

    def api(self, path):
        if path == "releases/latest":
            return {"tag_name": self.latest}
        if path.startswith("releases/"):
            ident = int(path.split("/")[-1])
            return next(r for r in self.releases.values() if r["id"] == ident)
        raise AssertionError(path)

    def gh(self, *args):
        if args[0] == "api":
            if "--paginate" in args:
                # Include an old public release to exercise Latest preflight.
                old = {"tag_name": "v8.18", "draft": False, "prerelease": False}
                if self.remaining_hidden_reads:
                    self.remaining_hidden_reads -= 1
                    return json.dumps([[old]])
                return json.dumps([[old, *self.releases.values()]])
            if "matching-refs" in args[-1]:
                return "[]"
            raise AssertionError(args)
        self.writes.append(args)
        command, tag = args[1:3]
        if command == "create":
            self.remaining_hidden_reads = self.visibility_delay
            self.releases[tag] = {"id": len(self.releases) + 1, "tag_name": tag, "draft": True,
                                  "target_commitish": args[args.index("--target") + 1],
                                  "prerelease": False, "assets": [], "html_url": "https://github.com/" + release.REPO + "/releases/tag/" + tag}
        elif command == "upload":
            for path in args[3:args.index("--repo")]:
                item = release.asset(Path(path))
                self.releases[tag]["assets"].append({"name": item["name"], "size": item["size"],
                    "state": "uploaded", "digest": "sha256:" + ("0" * 64 if self.corrupt_upload else item["sha256"])})
        elif command == "edit":
            if "--draft=false" in args:
                self.releases[tag]["draft"] = False
            if "--target" in args:
                self.releases[tag]["target_commitish"] = args[args.index("--target") + 1]
            if "--latest=true" in args:
                self.latest = tag
        else:
            raise AssertionError(args)
        return ""


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "dist"

    def build(self, mode="publish", kind="both"):
        with patch.object(release, "verify_proof", return_value=PROOF), patch.dict(os.environ,
                {"GITHUB_REF": "refs/heads/main", "RELEASE_MODE": mode, "RELEASE_KIND": kind}, clear=False):
            with contextlib.redirect_stdout(io.StringIO()):
                return release.prepare(self.output)

    def publish(self, manifest, github):
        env = {"GITHUB_REF": "refs/heads/main", "GITHUB_SHA": manifest["source_commit"],
               "RELEASE_MODE": manifest["mode"]}
        with patch.dict(os.environ, env), patch.object(release, "gh", side_effect=github.gh), \
                patch.object(release, "api", side_effect=github.api), patch.object(release.time, "sleep"), \
                contextlib.redirect_stdout(io.StringIO()):
            release.publish(self.output)

    def test_backend_names_and_bytes_match_existing_updater(self):
        manifest = self.build()
        backend = next(r for r in manifest["releases"] if r["kind"] == "backend")
        self.assertEqual(backend["tag"], "v8.31")
        self.assertTrue(backend["latest"])
        expected = json.loads((ROOT / "tests/backend-download-checksums.json").read_text())
        for platform, suffix in (("linux", ""), ("windows-x64", "-windows-x64"), ("macos", "-macos")):
            path = self.output / "backend" / f"kitty-download-manager-v8.31{suffix}.zip"
            self.assertEqual(release.sha256(path), expected[f"kitty-backend-v8.31-{platform}.zip"])
            with zipfile.ZipFile(path) as archive:
                self.assertFalse(any("/extension/" in n or n.endswith(".xpi") for n in archive.namelist()))

    def test_frontend_is_separate_and_source_archive_uses_single_folder(self):
        media = ROOT / "release-test-private-media.mp3"
        try:
            media.write_bytes(b"private local file")
            manifest = self.build()
            frontend = next(r for r in manifest["releases"] if r["kind"] == "frontend")
            self.assertEqual(frontend["tag"], f"frontend-v{FRONTEND_VERSION}")
            self.assertFalse(frontend["latest"])
            with zipfile.ZipFile(self.output / f"frontend/kitty-download-manager-v{FRONTEND_VERSION}.zip") as archive:
                names = archive.namelist()
                self.assertTrue(all(n.startswith("kitty-download-manager/") for n in names))
                self.assertFalse(any(media.name in n or n.endswith("release-request.json") for n in names))
                self.assertEqual(names.count(f"kitty-download-manager/kitty-download-manager-v{FRONTEND_VERSION}-unsigned.xpi"), 1)
                self.assertTrue((archive.getinfo("kitty-download-manager/install.sh").external_attr >> 16) & 0o111)
            with zipfile.ZipFile(self.output / f"frontend/kitty-download-manager-v{FRONTEND_VERSION}-unsigned.xpi") as archive:
                self.assertEqual(json.loads(archive.read("manifest.json"))["version"], FRONTEND_VERSION)
                self.assertFalse(any("native-host" in n or "tests/" in n for n in archive.namelist()))
        finally:
            media.unlink(missing_ok=True)

    def test_branch_request_cannot_publish(self):
        with patch.dict(os.environ, {"GITHUB_REF": "refs/heads/release-automation-test", "RELEASE_MODE": "publish", "RELEASE_KIND": "both"}):
            self.assertEqual(release.request(), ("dry-run", "both"))
        with patch.dict(os.environ, {"GITHUB_REF": "refs/heads/main", "RELEASE_MODE": "invalid", "RELEASE_KIND": "both"}):
            with self.assertRaises(ValueError):
                release.request()

    def test_proof_accepts_only_successful_runs_for_unchanged_application(self):
        read = proof_api()
        with patch.object(release, "api", side_effect=read), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(release.verify_proof(FRONTEND_VERSION, "8.31"), PROOF)
        tree = read("git/trees/proof")
        tree["tree"][0]["sha"] = "0" * 40
        with patch.object(release, "api", side_effect=read):
            with self.assertRaisesRegex(ValueError, "Application changed"):
                release.verify_proof(FRONTEND_VERSION, "8.31")

    def test_proof_refuses_failed_or_different_commit_run(self):
        read = proof_api()
        for field, value in (("conclusion", "failure"), ("head_sha", "f" * 40),
                             ("event", "pull_request"), ("path", ".github/workflows/unrelated.yml")):
            def altered(path):
                data = read(path)
                if path.startswith("actions/"):
                    data = {**data, field: value}
                return data
            with self.subTest(field=field), patch.object(release, "api", side_effect=altered):
                with self.assertRaisesRegex(ValueError, "did not succeed"):
                    release.verify_proof(FRONTEND_VERSION, "8.31")

    def test_uploads_verified_before_publish_and_frontend_is_never_latest(self):
        manifest = self.build()
        github = FakeGitHub()
        self.publish(manifest, github)
        self.assertEqual(github.latest, "v8.31")
        for tag in (f"frontend-v{FRONTEND_VERSION}", "v8.31"):
            commands = [c for c in github.writes if c[2] == tag]
            self.assertEqual([c[1] for c in commands], ["create", "upload", "edit"])
            self.assertIn("--latest=false", commands[0])
            self.assertIn("--latest=" + str(tag == "v8.31").lower(), commands[-1])
            self.assertFalse(github.releases[tag]["draft"])
        github.writes.clear()
        self.publish(manifest, github)
        self.assertEqual(github.writes, [], "rerun must preserve existing public assets")

    def test_draft_can_resume_after_partial_upload(self):
        manifest = self.build(mode="draft")
        github = FakeGitHub()
        self.publish(manifest, github)
        self.assertTrue(all(r["draft"] for r in github.releases.values()))
        removed = github.releases["v8.31"]["assets"].pop()
        github.writes.clear()
        self.publish(manifest, github)
        uploads = [c for c in github.writes if c[1] == "upload"]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(Path(uploads[0][3]).name, removed["name"])
        self.assertFalse(any(c[1] == "edit" for c in github.writes))

    def test_delayed_draft_visibility_retries_reads_without_duplicate_creation(self):
        manifest = self.build()
        github = FakeGitHub()
        github.visibility_delay = 2
        self.publish(manifest, github)
        creates = [c for c in github.writes if c[1] == "create"]
        self.assertEqual(len(creates), 2)
        self.assertEqual(github.latest, "v8.31")

    def test_empty_draft_can_be_retargeted_after_fixing_release_tools(self):
        manifest = self.build(mode="draft", kind="frontend")
        github = FakeGitHub()
        github.gh("release", "create", f"frontend-v{FRONTEND_VERSION}", "--target", "0" * 40)
        github.writes.clear()
        self.publish(manifest, github)
        self.assertEqual(github.releases[f"frontend-v{FRONTEND_VERSION}"]["target_commitish"], manifest["source_commit"])
        self.assertTrue(github.releases[f"frontend-v{FRONTEND_VERSION}"]["draft"])
        self.assertFalse(any("--draft=false" in c for c in github.writes))

    def test_bad_remote_digest_keeps_release_in_draft(self):
        manifest = self.build()
        github = FakeGitHub()
        github.corrupt_upload = True
        with self.assertRaisesRegex(ValueError, "differs"):
            self.publish(manifest, github)
        self.assertTrue(all(r["draft"] for r in github.releases.values()))
        self.assertFalse(any(c[1] == "edit" for c in github.writes))

    def test_modified_local_asset_is_rejected_before_remote_write(self):
        manifest = self.build()
        (self.output / "backend/SHA256SUMS").write_text("changed")
        github = FakeGitHub()
        with self.assertRaisesRegex(ValueError, "Packaged asset changed"):
            self.publish(manifest, github)
        self.assertEqual(github.writes, [])

    def test_newer_latest_prevents_downgrade_and_frontend_only_does_not_touch_backend(self):
        manifest = self.build(kind="frontend")
        github = FakeGitHub()
        github.latest = "v8.40"
        with self.assertRaisesRegex(ValueError, "newer/unrecognized"):
            self.publish(manifest, github)
        self.assertEqual(github.writes, [])
        github.latest = "v8.31"
        self.publish(manifest, github)
        self.assertEqual(list(github.releases), [f"frontend-v{FRONTEND_VERSION}"])
        self.assertEqual(github.latest, "v8.31")


if __name__ == "__main__":
    unittest.main(verbosity=2)
