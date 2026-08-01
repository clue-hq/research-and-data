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
            .match_typeface("Inter", weight, false)
            .unwrap_or_else(|| panic!("Inter weight {weight} resolves"));
        let second = fonts
            .match_typeface("Inter", weight, false)
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
    let first = fonts.match_typeface("Inter", 500, false).expect("resolves");
    let second = fonts.match_typeface("Inter", 500, false).expect("resolves");
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
        .match_typeface("Comic Sans MS", 700, false)
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
    let (fonts, errors) = FontManager::bundled_with(Vec::<(Vec<u8>, Option<String>)>::new());
    assert!(errors.is_empty());
    assert_eq!(
        fonts.family_weight_map(),
        FontManager::bundled().family_weight_map()
    );
}

#[test]
fn bundled_with_registers_extra_family_resolvable_without_fallback() {
    let (fonts, errors) = FontManager::bundled_with(vec![(distinct_family_font_bytes(), None)]);
    assert!(errors.is_empty());
    assert!(fonts.families().any(|family| family == "Xnter"));
    let resolution = fonts.resolve_family("Xnter");
    assert!(!resolution.fallback);
    assert!(resolution.diagnostic().is_none());
    let typeface = fonts.match_typeface("Xnter", 400, false).expect("extra face");
    assert_eq!(typeface.family_name(), "Xnter");
}

#[test]
fn bundled_with_skips_unparseable_bytes_and_keeps_bundled_set() {
    let (fonts, errors) = FontManager::bundled_with(vec![
        (vec![0xDE, 0xAD, 0xBE, 0xEF], None),
        (distinct_family_font_bytes(), None),
    ]);
    assert_eq!(errors.len(), 1);
    assert!(errors[0].message.contains("did not parse"));
    assert_eq!(fonts.weights("Inter"), vec![400, 600, 700, 800]);
    assert!(fonts.families().any(|family| family == "Xnter"));
    assert_eq!(fonts.default_family(), DEFAULT_FONT_FAMILY);
}

// --- Per-glyph fallback (LUMS0103): subset webfont glyph gaps -------------

/// Inter-Regular subset to only digits, ASCII letters, and space, renamed to
/// the family "SubsetFace". It deliberately LACKS "/", "×", and "—" — the exact
/// gaps a real subsetted brand webfont (Aeonik TRIAL) exhibits. Regenerate with
/// `crates/lumen-skia/tests/fixtures/make_subset_face.py`.
fn subset_face_bytes() -> Vec<u8> {
    std::fs::read(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/subset-face.ttf"))
        .expect("subset-face fixture reads")
}

#[test]
fn substituted_chars_reports_glyphs_missing_from_the_resolved_family() {
    let (fonts, errors) = FontManager::bundled_with(vec![(subset_face_bytes(), None)]);
    assert!(errors.is_empty(), "{errors:?}");
    // The subset face resolves as its own family (no whole-family fallback)...
    let resolution = fonts.resolve_family("SubsetFace");
    assert!(!resolution.fallback);
    // ...but lacks these three glyphs, which the bundled Inter supplies.
    let missing = fonts.substituted_chars("SubsetFace", 400, false, "1/10 ×2 —");
    assert_eq!(missing, vec!['/', '×', '—']);
}

#[test]
fn substituted_chars_is_empty_for_a_fully_covered_face() {
    let fonts = FontManager::bundled();
    // Bundled Inter covers "/", "×", and "—", so nothing is substituted.
    assert!(fonts
        .substituted_chars("Inter", 400, false, "1/10 ×2 —")
        .is_empty());
}

#[test]
fn bundled_with_alias_resolves_the_kit_declared_family() {
    // The web's @font-face aliasing: kit says "Aeonik", the trial bytes say
    // "Aeonik TRIAL". Scenes request the DECLARED name — it must resolve
    // without fallback, alongside the intrinsic name.
    let bytes = std::fs::read(repo_fonts_dir().join("Inter-Regular.ttf")).expect("font reads");
    let (fonts, errors) =
        FontManager::bundled_with(vec![(bytes, Some("Aeonik".to_owned()))]);
    assert!(errors.is_empty());
    let resolution = fonts.resolve_family("Aeonik");
    assert!(!resolution.fallback, "declared kit family must resolve");
    assert!(resolution.diagnostic().is_none());
    let typeface = fonts.match_typeface("Aeonik", 400, false).expect("aliased face");
    // The matched face is the aliased bytes (intrinsic name Inter here).
    assert_eq!(typeface.family_name(), "Inter");
}

// --- A7b: slant selection (upright + italic under one family) -------------

/// Instrument Serif Regular + Italic — two STATIC faces (both weight 400) that
/// share the family name "Instrument Serif". They register under the same
/// family key; the requested `FontStyle` slant disambiguates them. Copied from
/// the pinned google/fonts OFL clone.
fn instrument_serif_faces() -> Vec<(Vec<u8>, Option<String>)> {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures");
    let upright = std::fs::read(dir.join("instrument-serif-regular.ttf"))
        .expect("instrument-serif-regular fixture reads");
    let italic = std::fs::read(dir.join("instrument-serif-italic.ttf"))
        .expect("instrument-serif-italic fixture reads");
    vec![(upright, None), (italic, None)]
}

fn slant_is_italic(typeface: &skia_safe::Typeface) -> bool {
    typeface.font_style().slant() != skia_safe::font_style::Slant::Upright
}

#[test]
fn match_typeface_selects_italic_or_upright_face_by_slant() {
    let (fonts, errors) = FontManager::bundled_with(instrument_serif_faces());
    assert!(errors.is_empty(), "{errors:?}");
    // Both faces registered under one family, and the family reports an italic.
    let resolution = fonts.resolve_family("Instrument Serif");
    assert!(!resolution.fallback, "italic family must resolve directly");
    assert!(fonts.has_italic_face("Instrument Serif"));

    let italic = fonts
        .match_typeface("Instrument Serif", 400, true)
        .expect("italic face resolves");
    assert!(
        slant_is_italic(&italic),
        "italic=true must select the italic face, got {:?}",
        italic.font_style().slant()
    );

    let upright = fonts
        .match_typeface("Instrument Serif", 400, false)
        .expect("upright face resolves");
    assert!(
        !slant_is_italic(&upright),
        "italic=false must select the upright face, got {:?}",
        upright.font_style().slant()
    );

    // No slant advisory when the requested slant is available in either direction.
    assert!(fonts.resolved_slant("Instrument Serif", 400, true).is_none());
    assert!(fonts.resolved_slant("Instrument Serif", 400, false).is_none());
}

#[test]
fn requesting_italic_with_no_italic_face_snaps_to_upright_and_reports() {
    // Bundled Inter ships only upright static faces (400/600/700/800).
    let fonts = FontManager::bundled();
    assert!(!fonts.has_italic_face("Inter"));

    let face = fonts
        .match_typeface("Inter", 400, true)
        .expect("upright snap face resolves");
    assert!(
        !slant_is_italic(&face),
        "no synthetic slant: the request must snap to the upright face"
    );

    // resolved_slant reports the snap (actual upright != requested italic).
    assert_eq!(
        fonts.resolved_slant("Inter", 400, true),
        Some(false),
        "the italic→upright snap must be reported for LUMS0105"
    );
    // Upright request against the same family never reports.
    assert!(fonts.resolved_slant("Inter", 400, false).is_none());
}
