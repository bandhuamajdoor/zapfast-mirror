#!/usr/bin/env python3
"""Measure the real scaler with mirroring off/on, without opening a camera."""
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
source = (root / "src/camera.rs").read_text()
start = source.index('#[derive(Debug, PartialEq)]\npub struct I420')
end = source.index("/// Converts one camera frame", start)
scaler = source[start:end]
folder = Path(os.environ.get("RUNNER_TEMP", str(root.parent))) / "mirror-benchmark"
folder.mkdir(parents=True, exist_ok=True)
harness = r'''
use std::hint::black_box;
use std::time::Instant;
fn main() {
    for (source_size, size) in [((1280,720),(1280,720)), ((1920,1080),(1280,720)), ((720,1280),(720,1280))] {
        let (sw,sh)=source_size;
        let picture=I420 {width:sw,height:sh,y:(0..sw*sh).map(|v|(v%251) as u8).collect(),u:vec![80;sw*sh/4],v:vec![170;sw*sh/4]};
        let mut out=vec![0;size.0*size.1*3/2];
        let mut off=Vec::new(); let mut on=Vec::new();
        for trial in 0..11 {
            for enabled in if trial%2==0 {[false,true]} else {[true,false]} {
                camera_mirror::set_enabled(enabled);
                for _ in 0..50 {picture.scale_into(size,&mut out);camera_mirror::apply_if_enabled(&mut out,size);black_box(&out);}
                let start=Instant::now();
                for _ in 0..400 {black_box(&picture).scale_into(black_box(size),black_box(&mut out));camera_mirror::apply_if_enabled(black_box(&mut out),black_box(size));black_box(&out);}
                let us=start.elapsed().as_secs_f64()*1e6/400.;
                if enabled {on.push(us)} else {off.push(us)}
            }
        }
        off.sort_by(f64::total_cmp);on.sort_by(f64::total_cmp);
        let added=on[5]-off[5];
        println!("source={}x{} output={}x{} off_median_us={:.3} on_median_us={:.3} added_us={:.3} single_core_percent_at_25fps={:.4}",sw,sh,size.0,size.1,off[5],on[5],added,added/400.);
        assert!(added<250.,"Mirroring exceeds the 0.25ms/frame added-processing budget");
    }
}
'''
rust = folder / "bench.rs"
binary = folder / "bench"
rust.write_text('#[path="' + str(root / "src/camera_mirror.rs") + '"]\nmod camera_mirror;\n' + scaler + harness)
subprocess.run(["rustc", "--edition=2024", "-O", str(rust), "-o", str(binary)], cwd=root, check=True)
result = subprocess.run([str(binary)], check=True, text=True, capture_output=True)
print(result.stdout, end="")
evidence = root / "personal-evidence"
evidence.mkdir(exist_ok=True)
(evidence / "performance.txt").write_text(result.stdout)
