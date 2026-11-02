//! Personal camera mirroring, shared by the outgoing encoder and self-preview.
//!
//! One relaxed atomic read per delivered frame, no allocation, queue or extra thread.

use std::sync::atomic::{AtomicBool, Ordering};

static ENABLED: AtomicBool = AtomicBool::new(true);

/// Applies the saved preference without reopening the camera or encoder.
pub fn set_enabled(enabled: bool) {
    ENABLED.store(enabled, Ordering::Relaxed);
}

/// Mirrors only captured local frames, before either consumer reads them.
pub fn apply_if_enabled(frame: &mut [u8], size: (usize, usize)) {
    if ENABLED.load(Ordering::Relaxed) {
        mirror_i420(frame, size);
    }
}

/// Reverses columns independently in the tightly packed Y, U and V planes.
///
/// The capture module supplies nonzero, even dimensions and an exact-size buffer.
/// No row changes position, and chroma uses half the luma width and height.
pub fn mirror_i420(frame: &mut [u8], (width, height): (usize, usize)) {
    assert!(width > 0 && height > 0 && width.is_multiple_of(2) && height.is_multiple_of(2));
    let luma_len = width * height;
    let chroma_len = luma_len / 4;
    assert_eq!(frame.len(), luma_len + 2 * chroma_len);
    let (y, chroma) = frame.split_at_mut(luma_len);
    let (u, v) = chroma.split_at_mut(chroma_len);
    for row in y.chunks_exact_mut(width) {
        row.reverse();
    }
    for plane in [u, v] {
        for row in plane.chunks_exact_mut(width / 2) {
            row.reverse();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mirrors_all_three_planes_without_flipping_rows_or_swapping_chroma() {
        let mut frame: Vec<u8> = (0..24).collect();
        let pointer = frame.as_ptr();
        mirror_i420(&mut frame, (4, 4));
        assert_eq!(
            frame,
            [
                3, 2, 1, 0, 7, 6, 5, 4, 11, 10, 9, 8, 15, 14, 13, 12, 17, 16, 19, 18, 21, 20, 23,
                22
            ]
        );
        assert_eq!(frame.as_ptr(), pointer, "the existing buffer is reused");
    }

    #[test]
    fn mirroring_twice_restores_landscape_portrait_and_minimum_frames() {
        for (width, height) in [(2, 2), (2, 6), (8, 2), (640, 480), (720, 1280)] {
            let original: Vec<u8> = (0..width * height * 3 / 2)
                .map(|value| (value % 251) as u8)
                .collect();
            let mut frame = original.clone();
            mirror_i420(&mut frame, (width, height));
            mirror_i420(&mut frame, (width, height));
            assert_eq!(frame, original);
        }
    }
}
