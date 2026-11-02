#!/usr/bin/env python3
"""Exercise the updater's no-op, failure and signature paths without network calls."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("prepare", HERE / "prepare.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class UpdatePipeline(unittest.TestCase):
    def test_dirty_checkout_is_never_overwritten(self):
        with patch.object(prepare, "git", return_value=" M src/camera.rs"):
            with self.assertRaisesRegex(SystemExit, "local changes"):
                prepare.main()

    def test_prereleases_are_not_imported(self):
        with patch.object(prepare, "git", return_value=""), patch.object(
            prepare, "api", return_value={"tag_name": "v0.22.0-rc1"}
        ):
            with self.assertRaisesRegex(SystemExit, "stable"):
                prepare.main()

    def test_current_complete_release_does_not_rebuild_or_reset_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "personal").mkdir()
            (root / "personal/config.json").write_text('{"mirror_revision":1}')
            (root / "personal/video-mirror.patch").write_text("fixture patch")
            state = {
                "tag": "v0.21.0-mirror.1", "upstream_tag": "v0.21.0",
                "upstream_commit": "abc123",
                "patch_sha256": hashlib.sha256(b"fixture patch").hexdigest(),
            }
            (root / "personal/upstream.json").write_text(json.dumps(state))
            calls = []

            def git(*args):
                calls.append(args)
                return "abc123" if args[0] == "rev-parse" else ""

            def api(path):
                if path.startswith("repos/crmne/"):
                    return {"tag_name": "v0.21.0", "draft": False, "prerelease": False}
                return {"draft": False, "assets": [
                    {"name": "zapfast-v0.21.0-mirror.1-x86_64-unknown-linux-gnu.tar.gz"},
                    {"name": "checksums.txt"}, {"name": "checksums.txt.sig"},
                ]}

            output = root / "output"
            with patch.object(prepare, "ROOT", root), patch.object(prepare, "git", side_effect=git), patch.object(prepare, "api", side_effect=api), patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                prepare.main()
            self.assertIn("changed=false", output.read_text())
            self.assertFalse(any(args[0] in {"read-tree", "apply"} for args in calls))

    def test_patch_conflict_stops_before_recording_a_successful_update(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "personal").mkdir()
            (root / "personal/config.json").write_text('{"mirror_revision":1}')
            (root / "personal/video-mirror.patch").write_text("conflicting patch")
            workflow = root / prepare.WORKFLOW
            workflow.parent.mkdir(parents=True)
            workflow.write_text("fixture workflow")

            def git(*args):
                if args[0] == "apply":
                    raise subprocess.CalledProcessError(1, ["git", *args])
                return "abc123" if args[0] == "rev-parse" else ""

            def api(path):
                if path.startswith("repos/crmne/"):
                    return {"tag_name": "v0.22.0", "draft": False, "prerelease": False}
                raise urllib.error.HTTPError(path, 404, "Not found", None, None)

            with patch.object(prepare, "ROOT", root), patch.object(prepare, "git", side_effect=git), patch.object(prepare, "api", side_effect=api):
                with self.assertRaises(subprocess.CalledProcessError):
                    prepare.main()
            self.assertFalse((root / "personal/upstream.json").exists())

    def test_signer_uses_raw_ed25519_and_refuses_a_different_publisher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "personal").mkdir()
            (root / "dist").mkdir()
            (root / "personal/sign.py").write_bytes((HERE / "sign.py").read_bytes())
            (root / "dist/fixture.tar.gz").write_bytes(b"fixture bundle")
            private = root / "key.pem"
            subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)], check=True, capture_output=True)
            public = subprocess.check_output(["openssl", "pkey", "-in", str(private), "-pubout", "-outform", "DER"])
            (root / "personal/update-public-key.hex").write_text(public[-32:].hex())
            env = dict(os.environ, ZAPFAST_UPDATE_SIGNING_KEY=private.read_text())
            subprocess.run(["python3", str(root / "personal/sign.py")], env=env, check=True, capture_output=True)
            self.assertEqual((root / "dist/checksums.txt.sig").stat().st_size, 64)
            self.assertIn(hashlib.sha256(b"fixture bundle").hexdigest(), (root / "dist/checksums.txt").read_text())
            (root / "personal/update-public-key.hex").write_text("00" * 32)
            result = subprocess.run(["python3", str(root / "personal/sign.py")], env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
