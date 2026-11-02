#!/usr/bin/env python3
"""Benchmark the actual old/new playback converters without audio devices."""
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
source = (root / "src/call_audio.rs").read_text()


def block(start):
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


resample = block(source.index("pub fn resample("))
layout = source[source.index("#[derive(Clone, Copy, Debug, PartialEq, Eq)]\nstruct Layout"):source.index("// ---------------------------------------------------------------------------\n// Devices")]
folder = Path(os.environ.get("RUNNER_TEMP", str(root.parent))) / "audio-benchmark"
folder.mkdir(parents=True, exist_ok=True)
harness = r'''
pub fn bench() {
    use std::hint::black_box;
    use std::time::Instant;
    let frame: Vec<i16> = (0..960).map(|i| ((i as f32 * 0.17).sin() * 12_000.) as i16).collect();
    let layout = Layout { rate: 48_000, channels: 2 };
    let mut old = Vec::new();
    let mut new = Vec::new();
    for trial in 0..11 {
        for filtered in if trial % 2 == 0 { [false, true] } else { [true, false] } {
            let mut playback = Playback::new(layout);
            for _ in 0..50 {
                black_box(if filtered { playback.convert(&frame) } else { layout.convert(&frame) });
            }
            let start = Instant::now();
            for _ in 0..1_000 {
                black_box(if filtered { playback.convert(black_box(&frame)) } else { layout.convert(black_box(&frame)) });
            }
            let us = start.elapsed().as_secs_f64() * 1e6 / 1_000.;
            if filtered { new.push(us); } else { old.push(us); }
        }
    }
    old.sort_by(f64::total_cmp);
    new.sort_by(f64::total_cmp);
    let added = new[5] - old[5];
    println!("60ms stereo PCM block: old_median_us={:.2} filtered_median_us={:.2} added_us={:.2} one_core_percent={:.3}", old[5], new[5], added, added / 600.);
    assert!(added < 250., "Playback exceeds 0.25ms added CPU work per 60ms block");
}
'''
rust = folder / "bench.rs"
binary = folder / "bench"
rust.write_text('pub mod call_audio {\nconst RATE: u32 = 16_000;\n' + resample + layout
                + '#[path="' + str(root / "src/call_audio/playback_filter.rs")
                + '"] mod playback_filter;\n' + harness + '}\nfn main() {call_audio::bench();}\n')
subprocess.run(["rustc", "--edition=2024", "-O", str(rust), "-o", str(binary)], cwd=root, check=True)
result = subprocess.run([str(binary)], check=True, text=True, capture_output=True)
print(result.stdout, end="")
evidence = root / "personal-evidence"
evidence.mkdir(exist_ok=True)
(evidence / "audio-performance.txt").write_text(result.stdout)
