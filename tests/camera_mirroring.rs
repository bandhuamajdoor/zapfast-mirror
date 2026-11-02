use openh264::formats::YUVSource;
use zapfast::{camera, camera_mirror, settings::Settings};

#[test]
fn mirror_preference_survives_serialization_and_old_settings_enable_it() {
    let old: Settings = serde_json::from_str("{}").unwrap();
    assert!(old.mirror_camera_video);
    for enabled in [false, true] {
        let settings = Settings {
            mirror_camera_video: enabled,
            ..Settings::default()
        };
        let saved = serde_json::to_string(&settings).unwrap();
        let restored: Settings = serde_json::from_str(&saved).unwrap();
        assert_eq!(restored.mirror_camera_video, enabled);
    }
}

#[test]
fn mirroring_reaches_encoded_video_and_the_shared_preview_buffer() {
    let (width, height) = (64, 32);
    let raw: Vec<u8> = (0..height)
        .flat_map(|_| (0..width).map(|x| if x < width / 2 { 24 } else { 224 }))
        .collect();
    let picture = camera::to_i420(camera::Pixel::Gray, &raw, width, height).unwrap();
    let mut shared = vec![0; width * height * 3 / 2];
    picture.scale_into((width, height), &mut shared);
    camera_mirror::set_enabled(false);
    camera_mirror::apply_if_enabled(&mut shared, (width, height));
    assert_eq!(&shared[..width * height], raw);
    camera_mirror::set_enabled(true);
    camera_mirror::apply_if_enabled(&mut shared, (width, height));
    assert_eq!(shared[4], 224, "the shared preview input is mirrored");
    assert_eq!(shared[width - 5], 24);
    let yuv = openh264::formats::YUVBuffer::from_vec(shared, width, height);
    let mut encoder = openh264::encoder::Encoder::new().unwrap();
    let encoded = encoder.encode(&yuv).unwrap().to_vec();
    let mut decoder = openh264::decoder::Decoder::new().unwrap();
    let decoded = decoder.decode(&encoded).unwrap().unwrap();
    let stride = decoded.strides().0;
    assert!(decoded.y()[8 * stride + 4] > 180, "remote left is bright");
    assert!(
        decoded.y()[8 * stride + width - 5] < 60,
        "remote right is dark"
    );
}

#[test]
fn personal_updates_trust_only_the_personal_publisher() {
    let config = &zapfast::updates::CONFIG;
    assert_eq!(config.repository, "bandhuamajdoor/zapfast-mirror");
    assert!(config.additional_publisher_keys.is_empty());
    assert_eq!(
        config.publisher_key.unwrap().trim(),
        include_str!("../personal/update-public-key.hex").trim()
    );
    config.validate().unwrap();
}
