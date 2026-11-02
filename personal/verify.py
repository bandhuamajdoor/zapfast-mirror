#!/usr/bin/env python3
"""Fail closed when a build loses the preference, frame hook or private updater."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
required = {
    "src/lib.rs": ["pub mod camera_mirror;"],
    "src/camera.rs": ["crate::camera_mirror::apply_if_enabled(out, size);"],
    "src/camera_mirror.rs": ["AtomicBool", "row.reverse();", "Ordering::Relaxed"],
    "src/settings.rs": ["pub mirror_camera_video: bool,", "mirror_camera_video: true,"],
    "src/main.rs": ["camera_mirror::set_enabled(settings.mirror_camera_video)"],
    "src/app.rs": ["camera_mirror::set_enabled(self.settings.mirror_camera_video)"],
    "src/ui/settings.rs": ["Mirror outgoing camera video", "settings.mirror_camera_video"],
    "src/updates.rs": [
        '"bandhuamajdoor/zapfast-mirror"',
        'include_str!("../personal/update-public-key.hex")',
        "additional_publisher_keys: &[],",
    ],
    "tests/camera_mirroring.rs": [
        "mirroring_reaches_encoded_video_and_the_shared_preview_buffer",
        "personal_updates_trust_only_the_personal_publisher",
    ],
}
for name, fragments in required.items():
    text = (root / name).read_text()
    for fragment in fragments:
        if fragment not in text:
            raise SystemExit(f"Personal build contract missing in {name}: {fragment}")
key = (root / "personal/update-public-key.hex").read_text().strip()
assert len(bytes.fromhex(key)) == 32
print("Mirroring preference, outgoing capture hook, regression tests and publisher trust verified")
