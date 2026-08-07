//! The FontManager-backed [`FontFaceResolver`]: SVG font embedding with the
//! exact bytes the painter used.
//!
//! Resolution mirrors the paint path step for step. A requested family goes
//! through `resolve_family` (loaded, or the deterministic default-family
//! fallback), the face through `match_typeface` (the same CSS3 weight/slant
//! match the shaper performs), and characters the matched face lacks through
//! the same coverage scan `substituted_chars` reports as LUMS0103 — default
//! family first, then registration order. Every face that painted comes back
//! as an `@font-face`-ready subset; fallback-supplier faces carry a CSS
//! `unicode-range` scoped to exactly the characters they supplied, so a
//! browser's composite-font matching reproduces the painter's per-glyph
//! supplier choice.
//!
//! Two hard gates, both fail-loud by the export-parity contract:
//! - **fsType** (OS/2 embedding permissions): restricted-license faces
//!   (`0x0002`) and bitmap-embedding-only faces (`0x0200`) abort the export
//!   with an error naming the font. The no-subsetting bit (`0x0100`) is
//!   honored by embedding the complete face instead of a subset.
//! - **Subsetting failures** abort the export; a name-only SVG never ships
//!   from an embedding profile.

use crate::fonts::FontManager;
use lumen_export::{EmbeddedFontFace, FontEmbedError, FontFaceResolver, FontUsage};
use skia_safe::FontMgr;
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::sync::Arc;

/// OS/2 fsType bit: restricted license embedding — must not embed.
const FS_TYPE_RESTRICTED: u16 = 0x0002;
/// OS/2 fsType bit: no subsetting — embed the complete face only.
const FS_TYPE_NO_SUBSETTING: u16 = 0x0100;
/// OS/2 fsType bit: bitmap embedding only — outline embedding forbidden.
const FS_TYPE_BITMAP_ONLY: u16 = 0x0200;

pub struct SkiaFontFaceResolver {
    fonts: Arc<FontManager>,
}

impl fmt::Debug for SkiaFontFaceResolver {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("SkiaFontFaceResolver")
            .field("fonts", &self.fonts)
            .finish()
    }
}

impl SkiaFontFaceResolver {
    pub fn new(fonts: Arc<FontManager>) -> Self {
        Self { fonts }
    }
}

/// A physical face selected for embedding under one CSS identity. Whether
/// the rule is unicode-range-scoped is NOT stored here — it is owned by
/// which map the plan lives in (`primaries` vs `fallbacks`), passed to
/// `embed_rule` by the loop that owns the invariant.
struct RulePlan {
    bytes: Arc<Vec<u8>>,
    /// Intrinsic face family, for error messages and face identity checks.
    face_family: String,
    chars: BTreeSet<char>,
}

/// A loaded face parsed ONCE for supplier-coverage probes, shared across
/// every substituted character of one `resolve_embeds` call.
struct SupplierCandidate {
    bytes: Arc<Vec<u8>>,
    family: String,
    weight: i32,
    italic: bool,
    typeface: skia_safe::Typeface,
}

impl FontFaceResolver for SkiaFontFaceResolver {
    fn fallback_family(&self) -> String {
        self.fonts.default_family().to_owned()
    }

    fn resolve_embeds(&self, usages: &[FontUsage]) -> Result<Vec<EmbeddedFontFace>, FontEmbedError> {
        // Primary rules key by CSS identity (requested family + actual
        // weight/slant). Fallback rules key by the SUPPLIER FACE identity
        // (intrinsic family + weight/slant): two different physical faces
        // may supply gap glyphs at the same weight/style, and each must ship
        // its own bytes as its own range-scoped rule — keying by CSS
        // identity would silently drop the second face's bytes.
        let mut primaries: BTreeMap<(String, i32, bool), RulePlan> = BTreeMap::new();
        let mut fallbacks: BTreeMap<(String, i32, bool), RulePlan> = BTreeMap::new();
        let default_family = self.fonts.default_family().to_owned();
        // Supplier-coverage candidates parse lazily, ONCE per call, shared
        // by every substituted character (never built on the common
        // fully-covered path).
        let mut candidates: Option<Vec<SupplierCandidate>> = None;

        for usage in usages {
            if usage.chars.is_empty() {
                continue;
            }
            let requested = if usage.family.trim().is_empty() {
                default_family.as_str()
            } else {
                usage.family.trim()
            };
            let Some((bytes, face_family, actual_weight, actual_italic)) =
                self.fonts
                    .matched_face_bytes(requested, usage.weight, usage.italic)
            else {
                return Err(FontEmbedError::new(
                    "export.font_embed_face_missing",
                    format!(
                        "no loaded face resolves for font family \"{}\" (weight {}, italic {}) — the painter cannot have rendered this text; refusing to export an SVG that cannot embed it",
                        requested, usage.weight, usage.italic
                    ),
                ));
            };

            // Primary rule: declared under the REQUESTED family name (scene
            // truth; when the whole family fell back, the fallback bytes
            // embed under the requested name so the SVG renders exactly what
            // the raster painted) at the face's ACTUAL weight/slant, so a
            // browser's CSS matching snaps requests the same way the
            // shaper's find_typefaces did.
            let plan = primaries
                .entry((requested.to_owned(), actual_weight, actual_italic))
                .or_insert_with(|| RulePlan {
                    bytes: Arc::clone(&bytes),
                    face_family: face_family.clone(),
                    chars: BTreeSet::new(),
                });
            if plan.face_family != face_family {
                // Two usages with the same CSS identity resolved different
                // physical faces — impossible while matching is
                // deterministic; refuse rather than embed ambiguity.
                return Err(FontEmbedError::new(
                    "export.font_embed_face_conflict",
                    format!(
                        "font family \"{}\" (weight {}, italic {}) resolved two different faces (\"{}\" and \"{}\")",
                        requested, actual_weight, actual_italic, plan.face_family, face_family
                    ),
                ));
            }
            plan.chars.extend(usage.chars.iter().copied());

            // Per-glyph fallback: the characters the matched face cannot
            // supply but another loaded face can — exactly the set the
            // measurer reports as LUMS0103 substitutions. Group them by the
            // supplying face and embed each under the DEFAULT family name
            // (the chain tail every embedding <text> carries), scoped by
            // unicode-range to the supplied characters.
            let content: String = usage.chars.iter().collect();
            let substituted =
                self.fonts
                    .substituted_chars(requested, usage.weight, usage.italic, &content);
            if substituted.is_empty() {
                continue;
            }
            let candidates =
                candidates.get_or_insert_with(|| self.parse_supplier_candidates());
            for ch in substituted {
                let Some(supplier) =
                    self.supplier_for(candidates, ch, usage.weight, usage.italic)
                else {
                    // substituted_chars only reports chars some loaded face
                    // covers; not finding one is an invariant breach.
                    return Err(FontEmbedError::new(
                        "export.font_embed_face_missing",
                        format!(
                            "character U+{:04X} was reported as substituted but no loaded face supplies it",
                            ch as u32
                        ),
                    ));
                };
                fallbacks
                    .entry((
                        supplier.family.clone(),
                        supplier.weight,
                        supplier.italic,
                    ))
                    .or_insert_with(|| RulePlan {
                        bytes: Arc::clone(&supplier.bytes),
                        face_family: supplier.family.clone(),
                        chars: BTreeSet::new(),
                    })
                    .chars
                    .insert(ch);
            }
        }

        // Primary rules first, fallback rules after: for a codepoint covered
        // by rules of the same CSS identity, later rules win, so the
        // range-scoped supplier faces override exactly their gap characters.
        let mut faces = Vec::new();
        for ((css_family, weight, italic), plan) in primaries {
            faces.push(embed_rule(css_family, weight, italic, plan, false)?);
        }
        for ((_face_family, weight, italic), plan) in fallbacks {
            // Every fallback rule declares the DEFAULT family (the chain
            // tail each embedding <text> carries); distinct supplier faces
            // at the same weight/style coexist through their disjoint
            // unicode-ranges.
            faces.push(embed_rule(default_family.clone(), weight, italic, plan, true)?);
        }
        Ok(faces)
    }
}

impl SkiaFontFaceResolver {
    /// Parse every loaded face once, in registration order — the shared
    /// candidate list for supplier-coverage probes.
    fn parse_supplier_candidates(&self) -> Vec<SupplierCandidate> {
        let parser = FontMgr::new();
        self.fonts
            .loaded_faces()
            .iter()
            .filter_map(|face| {
                parser
                    .new_from_data(face.bytes.as_slice(), None)
                    .map(|typeface| SupplierCandidate {
                        bytes: Arc::clone(&face.bytes),
                        family: face.family.clone(),
                        weight: face.weight,
                        italic: face.italic,
                        typeface,
                    })
            })
            .collect()
    }

    /// The face that supplies `ch` when the primary face lacks it: the
    /// default family's style-matched face first (the painter's declared
    /// fallback), then the loaded faces in registration order — the same
    /// deterministic byte-backed scan `substituted_chars` uses for coverage.
    fn supplier_for<'a>(
        &self,
        candidates: &'a [SupplierCandidate],
        ch: char,
        weight: i32,
        italic: bool,
    ) -> Option<&'a SupplierCandidate> {
        if let Some((_, family, actual_weight, actual_italic)) =
            self.fonts
                .matched_face_bytes(self.fonts.default_family(), weight, italic)
        {
            if let Some(candidate) = candidates.iter().find(|candidate| {
                candidate.family == family
                    && candidate.weight == actual_weight
                    && candidate.italic == actual_italic
            }) {
                if candidate.typeface.unichar_to_glyph(ch as i32) != 0 {
                    return Some(candidate);
                }
            }
        }
        candidates
            .iter()
            .find(|candidate| candidate.typeface.unichar_to_glyph(ch as i32) != 0)
    }
}

/// Gate a face's fsType, subset it to `plan.chars` (or keep the whole face
/// when fsType forbids subsetting), and package the `@font-face` inputs.
/// `range_restricted` scopes the rule by unicode-range (fallback-supplier
/// rules only); it is passed by the caller loop that owns that invariant.
fn embed_rule(
    css_family: String,
    weight: i32,
    italic: bool,
    plan: RulePlan,
    range_restricted: bool,
) -> Result<EmbeddedFontFace, FontEmbedError> {
    let fs_type = parse_fs_type(&plan.bytes).map_err(|error| {
        FontEmbedError::new(
            "export.font_embed_unsupported_container",
            format!(
                "font \"{}\" cannot be license-checked for embedding: {} — refusing to embed bytes whose fsType cannot be read",
                plan.face_family, error
            ),
        )
    })?;
    // Bit test, not masked equality: real-world fonts combine the
    // restricted-license bit with other usage/reserved bits; any set
    // restricted bit forbids embedding.
    if fs_type & FS_TYPE_RESTRICTED != 0 {
        return Err(FontEmbedError::new(
            "export.font_embed_restricted_license",
            format!(
                "font \"{}\" declares restricted-license embedding (OS/2 fsType 0x{:04X}); its license forbids embedding it in exported files — use a font licensed for embedding",
                plan.face_family, fs_type
            ),
        ));
    }
    if fs_type & FS_TYPE_BITMAP_ONLY != 0 {
        return Err(FontEmbedError::new(
            "export.font_embed_bitmap_only",
            format!(
                "font \"{}\" permits bitmap embedding only (OS/2 fsType 0x{:04X}); its outlines cannot be embedded in an SVG",
                plan.face_family, fs_type
            ),
        ));
    }

    let bytes = if fs_type & FS_TYPE_NO_SUBSETTING != 0 {
        plan.bytes.as_ref().clone()
    } else {
        subset_face(&plan.bytes, &plan.chars).map_err(|error| {
            FontEmbedError::new(
                "export.font_embed_subset_failed",
                format!(
                    "subsetting font \"{}\" to {} character(s) failed: {}",
                    plan.face_family,
                    plan.chars.len(),
                    error
                ),
            )
        })?
    };

    let mime_type = if bytes.get(0..4) == Some(b"OTTO") {
        "font/otf"
    } else {
        "font/ttf"
    };
    let unicode_range = range_restricted.then(|| unicode_range_value(&plan.chars));

    Ok(EmbeddedFontFace {
        css_family,
        weight,
        italic,
        bytes,
        mime_type: mime_type.to_owned(),
        unicode_range,
    })
}

/// Subset `bytes` to the glyph closure of `chars` (cmap mapping plus GSUB
/// closure over the default layout features), keeping a working Unicode
/// cmap — the property SVG viewers require and PDF-oriented subsetters
/// drop. Pure-Rust klippa (HarfBuzz's subsetter ported to fontations);
/// a C HarfBuzz cannot link here because skia-safe already carries its own.
fn subset_face(bytes: &[u8], chars: &BTreeSet<char>) -> Result<Vec<u8>, String> {
    use fontcull_klippa::{subset_font, Plan, SubsetFlags, DEFAULT_LAYOUT_FEATURES};
    use fontcull_skrifa::FontRef;
    use fontcull_write_fonts::read::collections::IntSet;
    use fontcull_write_fonts::types::{GlyphId, NameId, Tag};

    let font = FontRef::new(bytes).map_err(|error| format!("font parse failed: {error:?}"))?;
    let mut unicodes: IntSet<u32> = IntSet::empty();
    for ch in chars {
        unicodes.insert(*ch as u32);
    }
    let empty_gids: IntSet<GlyphId> = IntSet::empty();
    let empty_tags: IntSet<Tag> = IntSet::empty();
    // Keep the standard name IDs (0-6: copyright through postscript name),
    // matching hb-subset's default — an unnamed face confuses every tool
    // that introspects the embedded bytes.
    let mut name_ids: IntSet<NameId> = IntSet::empty();
    for id in 0..=6u16 {
        name_ids.insert(NameId::new(id));
    }
    // Name records are also filtered by language: keep Mac English (0) and
    // Windows US English (0x0409), hb-subset's effective default.
    let mut name_languages: IntSet<u16> = IntSet::empty();
    name_languages.insert(0);
    name_languages.insert(0x0409);
    let layout_scripts: IntSet<Tag> = IntSet::all();
    let layout_features: IntSet<Tag> =
        IntSet::from_iter(DEFAULT_LAYOUT_FEATURES.iter().copied());
    let plan = Plan::new(
        &empty_gids,
        &unicodes,
        &font,
        SubsetFlags::default(),
        &empty_tags,
        &layout_scripts,
        &layout_features,
        &name_ids,
        &name_languages,
    );
    subset_font(&font, &plan).map_err(|error| format!("{error:?}"))
}

/// The OS/2 `fsType` field of a single sfnt font. A recognized font with no
/// OS/2 table is installable (`0`, the spec's least-restrictive default).
/// An unrecognized container (TrueType Collections, WOFF, garbage) is an
/// `Err` — the license gate must never be bypassed by bytes it cannot read.
fn parse_fs_type(bytes: &[u8]) -> Result<u16, String> {
    let read_u16 = |offset: usize| -> Option<u16> {
        Some(u16::from_be_bytes(bytes.get(offset..offset + 2)?.try_into().ok()?))
    };
    let read_u32 = |offset: usize| -> Option<u32> {
        Some(u32::from_be_bytes(bytes.get(offset..offset + 4)?.try_into().ok()?))
    };

    let version = read_u32(0).ok_or_else(|| "fewer than 4 bytes".to_owned())?;
    // 0x00010000 = TrueType, 'OTTO' = CFF OpenType, 'true' = legacy Apple.
    if version != 0x0001_0000 && version != 0x4F54_544F && version != 0x7472_7565 {
        return Err(format!(
            "unsupported font container (magic 0x{version:08X}; single TTF/OTF required)"
        ));
    }
    let num_tables = read_u16(4).ok_or_else(|| "truncated table directory".to_owned())? as usize;
    for index in 0..num_tables {
        let record = 12 + index * 16;
        let tag = bytes
            .get(record..record + 4)
            .ok_or_else(|| "truncated table record".to_owned())?;
        if tag == b"OS/2" {
            let offset = read_u32(record + 8)
                .ok_or_else(|| "truncated OS/2 record".to_owned())?
                as usize;
            return read_u16(offset + 8)
                .ok_or_else(|| "truncated OS/2 table".to_owned());
        }
    }
    Ok(0)
}

/// Format a character set as a CSS `unicode-range` value, collapsing
/// consecutive codepoints into ranges.
fn unicode_range_value(chars: &BTreeSet<char>) -> String {
    let mut parts: Vec<String> = Vec::new();
    let mut iter = chars.iter().map(|ch| *ch as u32).peekable();
    while let Some(start) = iter.next() {
        let mut end = start;
        while iter.peek() == Some(&(end + 1)) {
            end = iter.next().expect("peeked");
        }
        if start == end {
            parts.push(format!("U+{start:04X}"));
        } else {
            parts.push(format!("U+{start:04X}-{end:04X}"));
        }
    }
    parts.join(", ")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn bundled_resolver() -> SkiaFontFaceResolver {
        SkiaFontFaceResolver::new(Arc::new(FontManager::bundled()))
    }

    fn usage(family: &str, weight: i32, italic: bool, text: &str) -> FontUsage {
        FontUsage {
            family: family.to_owned(),
            weight,
            italic,
            chars: text.chars().collect(),
        }
    }

    #[test]
    fn subsets_are_valid_fonts_with_working_cmap_and_much_smaller() {
        let resolver = bundled_resolver();
        let faces = resolver
            .resolve_embeds(&[usage("Inter", 400, false, "Hello parity")])
            .expect("embed");
        assert_eq!(faces.len(), 1);
        let face = &faces[0];
        assert_eq!(face.css_family, "Inter");
        assert_eq!(face.weight, 400);
        assert!(!face.italic);
        assert_eq!(face.mime_type, "font/ttf");
        assert!(face.unicode_range.is_none());
        // Vastly smaller than the 400KB full face.
        assert!(
            face.bytes.len() < 20_000,
            "subset should be small, got {} bytes",
            face.bytes.len()
        );
        // The subset parses as a real typeface and its cmap maps the used
        // characters — the property PDF-oriented subsetters break and SVG
        // viewers require.
        let parser = FontMgr::new();
        let typeface = parser
            .new_from_data(&face.bytes, None)
            .expect("subset parses");
        for ch in "Hello parity".chars().filter(|ch| !ch.is_whitespace()) {
            assert_ne!(
                typeface.unichar_to_glyph(ch as i32),
                0,
                "subset cmap must map '{ch}'"
            );
        }
        // And characters outside the subset are gone.
        assert_eq!(typeface.unichar_to_glyph('Z' as i32), 0);
    }

    #[test]
    fn weight_snap_declares_actual_face_weight() {
        let resolver = bundled_resolver();
        // 750 snaps UP to Inter 800 in the shaper (the live-probed CSS3
        // semantics the editor pins: 450/500→400, 550→600, 750→800); the
        // rule must declare the face's actual weight so browser matching
        // snaps the same way.
        let faces = resolver
            .resolve_embeds(&[usage("Inter", 750, false, "x")])
            .expect("embed");
        assert_eq!(faces.len(), 1);
        assert_eq!(faces[0].weight, 800);
    }

    #[test]
    fn unknown_family_embeds_fallback_bytes_under_requested_name() {
        let resolver = bundled_resolver();
        let faces = resolver
            .resolve_embeds(&[usage("No Such Family", 400, false, "abc")])
            .expect("embed");
        assert_eq!(faces.len(), 1);
        assert_eq!(faces[0].css_family, "No Such Family");
        let parser = FontMgr::new();
        let typeface = parser
            .new_from_data(&faces[0].bytes, None)
            .expect("parses");
        assert_ne!(typeface.unichar_to_glyph('a' as i32), 0);
    }

    #[test]
    fn same_face_usages_merge_into_one_rule() {
        let resolver = bundled_resolver();
        let faces = resolver
            .resolve_embeds(&[
                usage("Inter", 400, false, "abc"),
                usage("Inter", 400, false, "def"),
            ])
            .expect("embed");
        assert_eq!(faces.len(), 1);
        let parser = FontMgr::new();
        let typeface = parser
            .new_from_data(&faces[0].bytes, None)
            .expect("parses");
        for ch in "abcdef".chars() {
            assert_ne!(typeface.unichar_to_glyph(ch as i32), 0);
        }
    }

    #[test]
    fn empty_family_resolves_to_default() {
        let resolver = bundled_resolver();
        let faces = resolver
            .resolve_embeds(&[usage("  ", 400, false, "hi")])
            .expect("embed");
        assert_eq!(faces.len(), 1);
        assert_eq!(faces[0].css_family, "Inter");
    }

    #[test]
    fn restricted_license_face_fails_the_export() {
        // Take bundled Inter bytes and patch OS/2 fsType to 0x0002
        // (restricted license embedding).
        let inter = FontManager::bundled();
        let (bytes, ..) = inter
            .matched_face_bytes("Inter", 400, false)
            .expect("inter face");
        let mut patched = bytes.as_ref().clone();
        let fs_type_offset = os2_fs_type_offset(&patched).expect("OS/2 table");
        patched[fs_type_offset] = 0x00;
        patched[fs_type_offset + 1] = 0x02;
        let (manager, errors) =
            FontManager::bundled_with([(patched, Some("Restricted Sans".to_owned()))]);
        assert!(errors.is_empty());
        let resolver = SkiaFontFaceResolver::new(Arc::new(manager));
        let error = resolver
            .resolve_embeds(&[usage("Restricted Sans", 400, false, "abc")])
            .expect_err("restricted face must fail");
        assert_eq!(error.code, "export.font_embed_restricted_license");
    }

    #[test]
    fn no_subsetting_bit_embeds_the_full_face() {
        let inter = FontManager::bundled();
        let (bytes, ..) = inter
            .matched_face_bytes("Inter", 400, false)
            .expect("inter face");
        let full_len = bytes.len();
        let mut patched = bytes.as_ref().clone();
        let fs_type_offset = os2_fs_type_offset(&patched).expect("OS/2 table");
        // Preview & Print usage (allowed) + no-subsetting bit.
        patched[fs_type_offset] = 0x01;
        patched[fs_type_offset + 1] = 0x04;
        let (manager, errors) =
            FontManager::bundled_with([(patched, Some("NoSubset Sans".to_owned()))]);
        assert!(errors.is_empty());
        let resolver = SkiaFontFaceResolver::new(Arc::new(manager));
        let faces = resolver
            .resolve_embeds(&[usage("NoSubset Sans", 400, false, "abc")])
            .expect("embed full face");
        assert_eq!(faces.len(), 1);
        assert_eq!(faces[0].bytes.len(), full_len);
    }

    #[test]
    fn substituted_chars_get_a_range_scoped_fallback_rule() {
        // Build a family that lacks "→" while bundled Inter supplies it, by
        // subsetting Inter 400 down to plain ASCII and aliasing it.
        let inter = FontManager::bundled();
        let (bytes, ..) = inter
            .matched_face_bytes("Inter", 400, false)
            .expect("inter face");
        let narrow = subset_face(&bytes, &"abc".chars().collect()).expect("subset");
        let (manager, errors) =
            FontManager::bundled_with([(narrow, Some("Narrow Sans".to_owned()))]);
        assert!(errors.is_empty());
        let resolver = SkiaFontFaceResolver::new(Arc::new(manager));
        let faces = resolver
            .resolve_embeds(&[usage("Narrow Sans", 400, false, "abc→")])
            .expect("embed");
        assert_eq!(faces.len(), 2, "primary + fallback supplier");
        let primary = &faces[0];
        assert_eq!(primary.css_family, "Narrow Sans");
        assert!(primary.unicode_range.is_none());
        let fallback = &faces[1];
        assert_eq!(fallback.css_family, "Inter");
        assert_eq!(fallback.unicode_range.as_deref(), Some("U+2192"));
        let parser = FontMgr::new();
        let typeface = parser
            .new_from_data(&fallback.bytes, None)
            .expect("parses");
        assert_ne!(typeface.unichar_to_glyph('→' as i32), 0);
    }

    #[test]
    fn unicode_range_collapses_consecutive_codepoints() {
        let chars: BTreeSet<char> = "abcx".chars().collect();
        assert_eq!(unicode_range_value(&chars), "U+0061-0063, U+0078");
    }

    #[test]
    fn restricted_bit_combined_with_other_usage_bits_still_fails() {
        // Real-world fonts combine fsType bits; 0x000A = restricted (0x0002)
        // + editable (0x0008). A masked-equality check would let it through.
        let inter = FontManager::bundled();
        let (bytes, ..) = inter
            .matched_face_bytes("Inter", 400, false)
            .expect("inter face");
        let mut patched = bytes.as_ref().clone();
        let fs_type_offset = os2_fs_type_offset(&patched).expect("OS/2 table");
        patched[fs_type_offset] = 0x00;
        patched[fs_type_offset + 1] = 0x0A;
        let (manager, errors) =
            FontManager::bundled_with([(patched, Some("Combined Restricted".to_owned()))]);
        assert!(errors.is_empty());
        let resolver = SkiaFontFaceResolver::new(Arc::new(manager));
        let error = resolver
            .resolve_embeds(&[usage("Combined Restricted", 400, false, "abc")])
            .expect_err("restricted bit must fail regardless of other bits");
        assert_eq!(error.code, "export.font_embed_restricted_license");
    }

    #[test]
    fn unknown_container_fails_the_license_gate_loudly() {
        // 'ttcf' collections (and any unrecognized container) cannot be
        // license-checked; treating them as installable would bypass the
        // fsType gate entirely.
        let mut ttc = b"ttcf".to_vec();
        ttc.extend_from_slice(&[0u8; 32]);
        let error = parse_fs_type(&ttc).expect_err("ttcf must not parse as installable");
        assert!(error.contains("unsupported font container"), "{error}");
    }

    #[test]
    fn distinct_supplier_faces_at_same_weight_each_ship_their_own_rule() {
        // Two different physical faces supply gap glyphs at the SAME
        // weight/slant: each must emit its own range-scoped rule with its
        // own bytes. Keying fallbacks by CSS identity alone silently
        // dropped the second face's bytes (glyphs became tofu).
        let inter = FontManager::bundled();
        let (bytes, ..) = inter
            .matched_face_bytes("Inter", 400, false)
            .expect("inter face");
        let primary = subset_face(&bytes, &"abc".chars().collect()).expect("subset");
        let arrow_supplier = rename_family_bytes(
            &subset_face(&bytes, &"→".chars().collect()).expect("subset"),
            "Inter",
            "Intex",
        );
        let times_supplier = rename_family_bytes(
            &subset_face(&bytes, &"×".chars().collect()).expect("subset"),
            "Inter",
            "Intey",
        );
        let manager =
            FontManager::from_bytes([primary, arrow_supplier, times_supplier], "Inter")
                .expect("manager");
        let families: Vec<_> = manager.families().map(str::to_owned).collect();
        assert!(
            families.iter().any(|family| family == "Intex")
                && families.iter().any(|family| family == "Intey"),
            "rename technique must hold: {families:?}"
        );
        let resolver = SkiaFontFaceResolver::new(Arc::new(manager));
        let faces = resolver
            .resolve_embeds(&[usage("Inter", 400, false, "a→×")])
            .expect("embed");
        let fallback_rules: Vec<_> = faces
            .iter()
            .filter(|face| face.unicode_range.is_some())
            .collect();
        assert_eq!(
            fallback_rules.len(),
            2,
            "one rule per supplier face: {faces:?}"
        );
        let parser = FontMgr::new();
        for rule in fallback_rules {
            assert_eq!(rule.css_family, "Inter", "fallback rules declare the chain tail");
            let typeface = parser
                .new_from_data(&rule.bytes, None)
                .expect("rule bytes parse");
            let expected = if rule.unicode_range.as_deref() == Some("U+2192") {
                '→'
            } else {
                assert_eq!(rule.unicode_range.as_deref(), Some("U+00D7"));
                '×'
            };
            assert_ne!(
                typeface.unichar_to_glyph(expected as i32),
                0,
                "each rule's bytes must cover its own range"
            );
        }
    }

    /// Same-length family rename by byte substitution (latin-1 and UTF-16BE
    /// name-table records) — builds distinct-family fixtures from one face.
    fn rename_family_bytes(bytes: &[u8], from: &str, to: &str) -> Vec<u8> {
        assert_eq!(from.len(), to.len());
        let mut out = bytes.to_vec();
        replace_all_bytes(&mut out, from.as_bytes(), to.as_bytes());
        let from_wide: Vec<u8> = from.encode_utf16().flat_map(u16::to_be_bytes).collect();
        let to_wide: Vec<u8> = to.encode_utf16().flat_map(u16::to_be_bytes).collect();
        replace_all_bytes(&mut out, &from_wide, &to_wide);
        out
    }

    fn replace_all_bytes(haystack: &mut [u8], needle: &[u8], replacement: &[u8]) {
        assert_eq!(needle.len(), replacement.len());
        let mut index = 0;
        while index + needle.len() <= haystack.len() {
            if &haystack[index..index + needle.len()] == needle {
                haystack[index..index + needle.len()].copy_from_slice(replacement);
                index += needle.len();
            } else {
                index += 1;
            }
        }
    }

    /// Locate the OS/2 fsType byte offset in an sfnt font (test helper for
    /// patching permissions).
    fn os2_fs_type_offset(bytes: &[u8]) -> Option<usize> {
        let num_tables = u16::from_be_bytes(bytes.get(4..6)?.try_into().ok()?) as usize;
        for index in 0..num_tables {
            let record = 12 + index * 16;
            if bytes.get(record..record + 4)? == b"OS/2" {
                let offset =
                    u32::from_be_bytes(bytes.get(record + 8..record + 12)?.try_into().ok()?)
                        as usize;
                return Some(offset + 8);
            }
        }
        None
    }
}
