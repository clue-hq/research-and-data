//! Slice A1 gates: deterministic font loading, typeface resolution, and the
//! missing-font fallback policy.

use lumen_skia::{FontManager, DEFAULT_FONT_FAMILY};
use std::path::PathBuf;

fn repo_fonts_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fonts")
}

#[test]
fn bundled_fonts_load_inter_static_weights() {
    let fonts = FontManager::bundled();
    assert_eq!(fonts.default_family(), DEFAULT_FONT_FAMILY);
    assert_eq!(fonts.families().collect::<Vec<_>>(), vec!["Inter"]);
    assert_eq!(fonts.weights("Inter"), vec![400, 600, 700, 800]);
}

#[test]
fn from_dir_loads_the_same_set_as_bundled() {
    let from_dir =
        FontManager::from_dir(&repo_fonts_dir(), DEFAULT_FONT_FAMILY).expect("fonts dir loads");
    let bundled = FontManager::bundled();
    assert_eq!(from_dir.family_weight_map(), bundled.family_weight_map());
}

#[test]
fn typeface_resolution_is_deterministic_per_weight() {
    let fonts = FontManager::bundled();
    for weight in [400, 600, 700, 800] {
        let first = fonts
            .match_typeface("Inter", weight)
            .unwrap_or_else(|| panic!("Inter weight {weight} resolves"));
        let second = fonts
            .match_typeface("Inter", weight)
            .unwrap_or_else(|| panic!("Inter weight {weight} resolves twice"));
        assert_eq!(first.family_name(), "Inter");
        assert_eq!(
            *first.font_style().weight(),
            weight,
            "weight {weight} must resolve to the exact static face"
        );
        assert_eq!(
            first.unique_id(),
            second.unique_id(),
            "resolution is stable"
        );
    }
}

#[test]
fn intermediate_weight_resolves_to_nearest_loaded_face_stably() {
    let fonts = FontManager::bundled();
    let first = fonts.match_typeface("Inter", 500).expect("resolves");
    let second = fonts.match_typeface("Inter", 500).expect("resolves");
    assert_eq!(first.unique_id(), second.unique_id());
    // The resolved face must be one of the loaded static weights.
    assert!(
        [400, 600, 700, 800].contains(&*first.font_style().weight()),
        "weight 500 resolved to unloaded weight {:?}",
        first.font_style().weight()
    );
}

#[test]
fn missing_family_falls_back_to_default_with_warning_diagnostic() {
    let fonts = FontManager::bundled();
    let resolution = fonts.resolve_family("Comic Sans MS");
    assert!(resolution.fallback);
    assert_eq!(resolution.family, DEFAULT_FONT_FAMILY);
    assert_eq!(resolution.requested, "Comic Sans MS");

    let diagnostic = resolution.diagnostic().expect("fallback carries a warning");
    assert_eq!(diagnostic.code, "LUMS0100");
    assert!(diagnostic.message.contains("Comic Sans MS"));
    assert!(diagnostic.message.contains(DEFAULT_FONT_FAMILY));

    // Matching still produces a usable typeface (the fallback family's).
    let typeface = fonts
        .match_typeface("Comic Sans MS", 700)
        .expect("fallback face");
    assert_eq!(typeface.family_name(), "Inter");
}

#[test]
fn loaded_family_resolution_carries_no_diagnostic() {
    let fonts = FontManager::bundled();
    let resolution = fonts.resolve_family("Inter");
    assert!(!resolution.fallback);
    assert!(resolution.diagnostic().is_none());
}

#[test]
fn from_dir_rejects_missing_default_family() {
    let error = FontManager::from_dir(&repo_fonts_dir(), "Helvetica")
        .expect_err("unknown default family must fail closed");
    assert!(error.message.contains("Helvetica"));
}
