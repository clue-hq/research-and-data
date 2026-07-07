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

// --- K3: bundled_with (brand-kit font faces) ------------------------------

/// Inter-Regular bytes with every "Inter" inside the `name` table rewritten
/// to "Xnter" — a same-length patch, so offsets stay valid — yielding a real
/// parseable face whose intrinsic family differs from the bundled set.
fn distinct_family_font_bytes() -> Vec<u8> {
    let mut bytes = std::fs::read(repo_fonts_dir().join("Inter-Regular.ttf")).expect("font reads");
    let num_tables = u16::from_be_bytes([bytes[4], bytes[5]]) as usize;
    let (mut name_off, mut name_len) = (0usize, 0usize);
    for i in 0..num_tables {
        let rec = 12 + i * 16;
        if &bytes[rec..rec + 4] == b"name" {
            name_off = u32::from_be_bytes(bytes[rec + 8..rec + 12].try_into().unwrap()) as usize;
            name_len = u32::from_be_bytes(bytes[rec + 12..rec + 16].try_into().unwrap()) as usize;
        }
    }
    assert!(name_len > 0, "Inter-Regular must carry a name table");
    let table = &mut bytes[name_off..name_off + name_len];
    for pattern in [&b"Inter"[..], &[0, b'I', 0, b'n', 0, b't', 0, b'e', 0, b'r'][..]] {
        let replacement: Vec<u8> = pattern
            .iter()
            .map(|&b| if b == b'I' { b'X' } else { b })
            .collect();
        let mut i = 0;
        while i + pattern.len() <= table.len() {
            if &table[i..i + pattern.len()] == pattern {
                table[i..i + pattern.len()].copy_from_slice(&replacement);
                i += pattern.len();
            } else {
                i += 1;
            }
        }
    }
    bytes
}

#[test]
fn bundled_with_no_extras_matches_bundled() {
    let (fonts, errors) = FontManager::bundled_with(Vec::<Vec<u8>>::new());
    assert!(errors.is_empty());
    assert_eq!(
        fonts.family_weight_map(),
        FontManager::bundled().family_weight_map()
    );
}

#[test]
fn bundled_with_registers_extra_family_resolvable_without_fallback() {
    let (fonts, errors) = FontManager::bundled_with(vec![distinct_family_font_bytes()]);
    assert!(errors.is_empty());
    assert!(fonts.families().any(|family| family == "Xnter"));
    let resolution = fonts.resolve_family("Xnter");
    assert!(!resolution.fallback);
    assert!(resolution.diagnostic().is_none());
    let typeface = fonts.match_typeface("Xnter", 400).expect("extra face");
    assert_eq!(typeface.family_name(), "Xnter");
}

#[test]
fn bundled_with_skips_unparseable_bytes_and_keeps_bundled_set() {
    let (fonts, errors) = FontManager::bundled_with(vec![
        vec![0xDE, 0xAD, 0xBE, 0xEF],
        distinct_family_font_bytes(),
    ]);
    assert_eq!(errors.len(), 1);
    assert!(errors[0].message.contains("did not parse"));
    assert_eq!(fonts.weights("Inter"), vec![400, 600, 700, 800]);
    assert!(fonts.families().any(|family| family == "Xnter"));
    assert_eq!(fonts.default_family(), DEFAULT_FONT_FAMILY);
}
