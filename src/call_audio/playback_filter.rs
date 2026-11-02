//! Remove resampling images from 16 kHz call audio before device playback.
//!
//! Linear interpolation leaves audible images above the source Nyquist limit.
//! Five Butterworth biquads retain the speech band and suppress those images.
//! State spans packets: no lookahead, extra sample queue or packet delay.
//! Coefficients follow the [W3C Audio EQ Cookbook](https://www.w3.org/TR/audio-eq-cookbook/).

const SECTIONS: usize = 5;
const SOURCE_RATE: u32 = 16_000;

#[derive(Clone, Copy, Default)]
struct State {
    z1: f64,
    z2: f64,
}

#[derive(Clone, Copy, Default)]
struct Coefficients {
    b0: f64,
    b1: f64,
    b2: f64,
    a1: f64,
    a2: f64,
}

/// One fixed-size filter per output channel, allocated once per device stream.
pub(super) struct PlaybackFilter {
    coefficients: Option<[Coefficients; SECTIONS]>,
    states: Vec<[State; SECTIONS]>,
}

impl PlaybackFilter {
    pub(super) fn new(device_rate: u32, channels: u16) -> Self {
        let coefficients = (device_rate > SOURCE_RATE).then(|| {
            let angle =
                std::f64::consts::TAU * (f64::from(SOURCE_RATE) * 0.45) / f64::from(device_rate);
            let (sin, cos) = angle.sin_cos();
            std::array::from_fn(|section| {
                let pole = (2 * section + 1) as f64 * std::f64::consts::PI / (4 * SECTIONS) as f64;
                let q = 1.0 / (2.0 * pole.cos());
                let alpha = sin / (2.0 * q);
                let a0 = 1.0 + alpha;
                Coefficients {
                    b0: (1.0 - cos) / (2.0 * a0),
                    b1: (1.0 - cos) / a0,
                    b2: (1.0 - cos) / (2.0 * a0),
                    a1: -2.0 * cos / a0,
                    a2: (1.0 - alpha) / a0,
                }
            })
        });
        Self {
            coefficients,
            states: vec![[State::default(); SECTIONS]; usize::from(channels.max(1))],
        }
    }

    pub(super) fn process(&mut self, interleaved: &mut [f32]) {
        let Some(coefficients) = &self.coefficients else {
            return;
        };
        for frame in interleaved.chunks_exact_mut(self.states.len()) {
            for (sample, states) in frame.iter_mut().zip(&mut self.states) {
                let mut value = f64::from(*sample);
                for (c, state) in coefficients.iter().zip(states) {
                    let out = c.b0 * value + state.z1;
                    state.z1 = c.b1 * value - c.a1 * out + state.z2;
                    state.z2 = c.b2 * value - c.a2 * out;
                    value = out;
                }
                *sample = value as f32;
            }
        }
        // Avoid subnormal arithmetic when a stream goes silent for a long time.
        for states in &mut self.states {
            for state in states {
                if state.z1.abs() < 1e-24 {
                    state.z1 = 0.0;
                }
                if state.z2.abs() < 1e-24 {
                    state.z2 = 0.0;
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::call_audio::resample;

    fn amplitude(samples: &[f32], rate: u32, hz: f64) -> f64 {
        let (mut re, mut im) = (0.0, 0.0);
        for (i, &sample) in samples.iter().enumerate() {
            let angle = std::f64::consts::TAU * hz * i as f64 / f64::from(rate);
            re += f64::from(sample) * angle.cos();
            im += f64::from(sample) * angle.sin();
        }
        2.0 * re.hypot(im) / samples.len() as f64
    }

    #[test]
    fn actual_call_resampling_no_longer_adds_audible_high_frequency_images() {
        for rate in [44_100, 48_000] {
            for hz in [1_000.0, 3_000.0, 6_000.0] {
                let source: Vec<f32> = (0..SOURCE_RATE)
                    .map(|i| {
                        (0.5 * (std::f64::consts::TAU * hz * f64::from(i) / f64::from(SOURCE_RATE))
                            .sin()) as f32
                    })
                    .collect();
                let mut output = resample(&source, SOURCE_RATE, rate);
                let mut filter = PlaybackFilter::new(rate, 1);
                filter.process(&mut output);
                let steady = &output[rate as usize / 10..rate as usize * 9 / 10];
                let voice = amplitude(steady, rate, hz);
                let image = amplitude(steady, rate, f64::from(SOURCE_RATE) - hz);
                let db = 20.0 * (image / voice).log10();
                println!("{rate} Hz device, {hz} Hz tone: image {db:.1} dB");
                assert!(db < -40.0, "resampling image is audible: {db:.1} dB");
                assert!(
                    voice > 0.29,
                    "speech-band signal was excessively attenuated"
                );
            }
        }
    }

    #[test]
    fn state_spans_packets_and_stereo_channels_are_independent() {
        let input: Vec<f32> = (0..9_600)
            .flat_map(|i| [(i as f32 * 0.07).sin() * 0.3, 0.0])
            .collect();
        let mut whole = input.clone();
        PlaybackFilter::new(48_000, 2).process(&mut whole);
        let mut chunks = input;
        let mut streaming = PlaybackFilter::new(48_000, 2);
        for chunk in chunks.chunks_mut(960) {
            streaming.process(chunk);
        }
        assert_eq!(whole, chunks, "packet boundaries must not reset the filter");
        assert!(chunks.chunks_exact(2).all(|frame| frame[1] == 0.0));
    }

    #[test]
    fn silence_stays_silent_and_native_rate_is_unchanged() {
        let mut silence = [0.0; 960];
        PlaybackFilter::new(48_000, 1).process(&mut silence);
        assert_eq!(silence, [0.0; 960]);
        let mut native = [0.2, -0.3, 0.6];
        PlaybackFilter::new(SOURCE_RATE, 1).process(&mut native);
        assert_eq!(native, [0.2, -0.3, 0.6]);
    }
}
