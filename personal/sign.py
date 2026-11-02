#!/usr/bin/env python3
"""Sign the exact manifest bytes using the native updater's Ed25519 format."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
dist = root / "dist"
packages = sorted(dist.glob("*.tar.gz"))
assert len(packages) == 1, "Expected exactly the tested Linux bundle"
manifest = dist / "checksums.txt"
manifest.write_text("".join(
    hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n"
    for path in packages
))
with tempfile.TemporaryDirectory(prefix="zapfast-sign-") as directory:
    key = Path(directory) / "key.pem"
    public = Path(directory) / "public.der"
    key.write_text(os.environ["ZAPFAST_UPDATE_SIGNING_KEY"])
    key.chmod(0o600)
    subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout", "-outform", "DER", "-out", str(public)], check=True)
    expected = bytes.fromhex((root / "personal/update-public-key.hex").read_text().strip())
    assert public.read_bytes() == bytes.fromhex("302a300506032b6570032100") + expected, "Signing key differs from embedded publisher"
    subprocess.run(["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(key), "-in", str(manifest), "-out", str(dist / "checksums.txt.sig")], check=True)
    subprocess.run(["openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(public), "-keyform", "DER", "-in", str(manifest), "-sigfile", str(dist / "checksums.txt.sig")], check=True)
assert (dist / "checksums.txt.sig").stat().st_size == 64
print("Signed manifest verified against the public key embedded in the personal build")
