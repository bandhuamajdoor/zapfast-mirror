#!/usr/bin/env python3
"""Import the latest stable source, then require the personal patch to apply.

Run only in a clean, disposable CI checkout. Published history is never rewritten.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "bandhuamajdoor/zapfast-mirror"
WORKFLOW = ".github/workflows/personal-update.yml"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def api(path):
    request = urllib.request.Request(
        "https://api.github.com/" + path,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main():
    if git("status", "--porcelain"):
        raise SystemExit("Refusing to prepare over local changes; use a clean CI checkout")
    release = api("repos/crmne/zapfast/releases/latest")
    upstream_tag = release["tag_name"]
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", upstream_tag):
        raise SystemExit("Upstream latest release is not a stable vMAJOR.MINOR.PATCH tag")
    if release["draft"] or release["prerelease"]:
        raise SystemExit("Refusing an upstream draft or prerelease")
    git("fetch", "--no-tags", "https://github.com/crmne/zapfast.git", "refs/tags/" + upstream_tag)
    upstream_commit = git("rev-parse", "FETCH_HEAD^{commit}")
    patch_hash = hashlib.sha256((ROOT / "personal/video-mirror.patch").read_bytes()).hexdigest()
    revision = json.loads((ROOT / "personal/config.json").read_text())["mirror_revision"]
    assert isinstance(revision, int) and revision >= 1
    version = upstream_tag[1:] + f"-mirror.{revision}"
    tag = "v" + version
    state = {"tag": tag, "upstream_tag": upstream_tag, "upstream_commit": upstream_commit, "patch_sha256": patch_hash}
    state_path = ROOT / "personal/upstream.json"
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    try:
        published = api("repos/" + REPOSITORY + "/releases/tags/" + tag)
        assets = {item["name"] for item in published["assets"]}
        complete = not published["draft"] and {
            f"zapfast-{tag}-x86_64-unknown-linux-gnu.tar.gz",
            "checksums.txt", "checksums.txt.sig",
        } <= assets
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        error.close()
        complete = False
    changed = previous != state or not complete
    if not changed:
        print("Already published the current upstream release with the mirroring patch")
    else:
        with tempfile.TemporaryDirectory(prefix="zapfast-overlay-") as folder:
            saved = Path(folder)
            shutil.copytree(ROOT / "personal", saved / "personal")
            shutil.copyfile(ROOT / WORKFLOW, saved / "workflow.yml")
            # This is an isolated checkout, not the user's working directory.
            # Replacing the index imports the upstream tree while keeping our
            # existing main as the parent of the next ordinary commit.
            git("read-tree", "--reset", "-u", upstream_commit)
            if (ROOT / "personal").exists():
                shutil.rmtree(ROOT / "personal")
            shutil.copytree(saved / "personal", ROOT / "personal")
            # Only our reviewed workflow runs in the fork. Upstream release,
            # deployment and scheduled workflows are deliberately not enabled.
            shutil.rmtree(ROOT / ".github/workflows", ignore_errors=True)
            (ROOT / ".github/workflows").mkdir(parents=True)
            shutil.copyfile(saved / "workflow.yml", ROOT / WORKFLOW)
        # A conflict stops this isolated build. Never publish the unpatched app.
        git("apply", "--3way", "--index", "personal/video-mirror.patch")
        cargo = (ROOT / "Cargo.toml").read_text()
        if f'version = "{upstream_tag[1:]}"' not in cargo:
            raise SystemExit("Upstream tag and package version disagree")
        cargo, count = re.subn(r'^version = "[^"]+"', f'version = "{version}"', cargo, count=1, flags=re.M)
        assert count == 1
        (ROOT / "Cargo.toml").write_text(cargo)
        lock = (ROOT / "Cargo.lock").read_text()
        lock, count = re.subn(r'(\[\[package\]\]\nname = "zapfast"\nversion = ")[^"]+("\n)', rf'\g<1>{version}\2', lock)
        assert count == 1
        (ROOT / "Cargo.lock").write_text(lock)
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        print("Prepared", tag, "from", upstream_commit, "with mirroring")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"changed={str(changed).lower()}\ntag={tag}\n")


if __name__ == "__main__":
    main()
