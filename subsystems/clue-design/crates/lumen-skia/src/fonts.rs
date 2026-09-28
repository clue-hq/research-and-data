//! Deterministic font loading for server-side Skia text shaping.
//!
//! Fonts load from bytes only — never from system font lookup — so the
//! server, CI, and (in Wave 3) the CanvasKit editor shape text identically.
//! The font files under the repo `fonts/` directory are the cross-runtime
//! parity contract; `FontManager::bundled()` embeds them at compile time so
//! every binary built from this workspace carries exactly those bytes.

use lumen_core::{Diagnostic, Phase};
use skia_safe::textlayout::{FontCollection, TypefaceFontProvider};
use skia_safe::{FontMgr, Typeface};
use std::cell::RefCell;
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::fmt;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

/// The family every unresolvable font request falls back to. This is the
/// explicit fallback policy: deterministic, single, and always loaded by
/// `FontManager::bundled()`.
pub const DEFAULT_FONT_FAMILY: &str = "Inter";

/// Inter static TTFs embedded from the repo `fonts/` directory (weights
/// 400/600/700/800, SIL OFL 1.1 — see `fonts/LICENSE-OFL.txt`).
const BUNDLED_FONTS: &[&[u8]] = &[
    include_bytes!("../../../fonts/Inter-Regular.ttf"),
    include_bytes!("../../../fonts/Inter-SemiBold.ttf"),
    include_bytes!("../../../fonts/Inter-Bold.ttf"),
    include_bytes!("../../../fonts/Inter-ExtraBold.ttf"),
];

#[derive(Clone, Debug)]
pub struct FontLoadError {
    pub message: String,
}

impl fmt::Display for FontLoadError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "font load failed: {}", self.message)
    }
}

impl std::error::Error for FontLoadError {}

/// One loaded font face: raw bytes plus the metadata Skia parsed from them.
/// `alias` is the caller-declared family (a brand kit's `font-family` name —
/// e.g. "Aeonik" for bytes whose intrinsic name is "Aeonik TRIAL"): the web's
/// `@font-face` aliasing is the norm, so scenes request the DECLARED name and
/// the face must resolve under both.
#[derive(Clone)]
pub(crate) struct LoadedFace {
    pub(crate) bytes: Arc<Vec<u8>>,
    pub(crate) family: String,
    pub(crate) alias: Option<String>,
    pub(crate) weight: i32,
    /// A7b: whether this face is an italic (or oblique) style, parsed from the
    /// bytes' `font_style().slant()` at registration. Upright + italic faces of
    /// one family register under the SAME family key; the requested `FontStyle`
    /// slant disambiguates them at shape time (`match_typeface`).
    pub(crate) italic: bool,
}

/// Outcome of resolving a requested font family against the loaded set.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FamilyResolution {
    pub requested: String,
    /// The family that will actually shape/paint. Equal to `requested`
    /// unless `fallback` is true, in which case it is the default family.
    pub family: String,
    pub fallback: bool,
}

impl FamilyResolution {
    /// Warning diagnostic for the missing-font fallback policy. `None` when
    /// the requested family resolved directly.
    pub fn diagnostic(&self) -> Option<Diagnostic> {
        if !self.fallback {
            return None;
        }
        Some(
            Diagnostic::warning(
                Phase::Layout,
                "LUMS0100",
                format!(
                    "font family \"{}\" is not loaded; shaping and painting fall back to \"{}\"",
                    self.requested, self.family
                ),
                None,
            )
            .with_hint(
                "Add the family's TTF files to the repo fonts/ directory (bytes are the parity contract) or use a loaded family.",
            ),
        )
    }
}

static NEXT_MANAGER_ID: AtomicU64 = AtomicU64::new(1);

thread_local! {
    /// Per-thread FontCollection cache. Skia textlayout handles are not
    /// Sync, so each thread builds its own collection from the manager's
    /// bytes on first use. The helper binary is short-lived and effectively
    /// single-threaded; tests build at most one collection per test thread.
    static COLLECTIONS: RefCell<HashMap<u64, FontCollection>> = RefCell::new(HashMap::new());
}

/// Owns the deterministic font set. Cheap to clone-share via `Arc`; safe to
/// move across threads (it holds bytes, not Skia handles — Skia handles are
/// constructed lazily per thread).
pub struct FontManager {
    id: u64,
    faces: Vec<LoadedFace>,
    families: BTreeSet<String>,
    default_family: String,
}

impl fmt::Debug for FontManager {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("FontManager")
            .field("families", &self.families)
            .field("default_family", &self.default_family)
            .field("face_count", &self.faces.len())
            .finish()
    }
}

impl FontManager {
    /// The bundled deterministic font set: Inter 400/600/700/800 embedded
    /// from the repo `fonts/` directory at compile time.
    pub fn bundled() -> Self {
        Self::from_bytes(
            BUNDLED_FONTS.iter().map(|bytes| bytes.to_vec()),
            DEFAULT_FONT_FAMILY,
        )
        .expect("bundled Inter faces must parse")
    }

    /// The bundled deterministic set plus additional font faces (brand-kit
    /// fonts read from the asset store), each with an optional DECLARED
    /// family alias — the kit's `font-family` name, which is what scenes
    /// request and is routinely different from the bytes' intrinsic name
    /// (`@font-face` aliasing: "Aeonik" kit family over "Aeonik TRIAL"
    /// bytes). Faces whose bytes do not parse are skipped and reported —
    /// the bundled fallback set must never be lost to one bad kit font, so
    /// this constructor cannot fail.
    pub fn bundled_with(
        extra: impl IntoIterator<Item = (Vec<u8>, Option<String>)>,
    ) -> (Self, Vec<FontLoadError>) {
        let parser = FontMgr::new();
        let mut manager = Self::bundled();
        let mut errors = Vec::new();
        for (bytes, alias) in extra {
            let Some(typeface) = parser.new_from_data(&bytes, None) else {
                errors.push(FontLoadError {
                    message: "brand font bytes did not parse as a typeface".to_owned(),
                });
                continue;
            };
            let family = typeface.family_name();
            let weight = *typeface.font_style().weight();
            let italic = typeface.font_style().slant()
                != skia_safe::font_style::Slant::Upright;
            manager.families.insert(family.clone());
            let alias = alias.filter(|alias| !alias.is_empty() && *alias != family);
            if let Some(alias) = &alias {
                manager.families.insert(alias.clone());
            }
            manager.faces.push(LoadedFace {
                bytes: Arc::new(bytes),
                family,
                alias,
                weight,
                italic,
            });
        }
        // Fresh identity: the thread-local FontCollection cache keys on it,
        // and this manager's face set differs from plain bundled().
        manager.id = NEXT_MANAGER_ID.fetch_add(1, Ordering::Relaxed);
        (manager, errors)
    }

    /// Load every `.ttf`/`.otf` in `dir` (sorted by file name for
    /// deterministic registration order). The default fallback family must
    /// be among the loaded families.
    pub fn from_dir(dir: &Path, default_family: &str) -> Result<Self, FontLoadError> {
        let mut paths = std::fs::read_dir(dir)
            .map_err(|error| FontLoadError {
                message: format!("cannot read font dir {}: {error}", dir.display()),
            })?
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .filter(|path| {
                matches!(
                    path.extension().and_then(|ext| ext.to_str()),
                    Some("ttf") | Some("otf")
                )
            })
            .collect::<Vec<_>>();
        paths.sort();

        if paths.is_empty() {
            return Err(FontLoadError {
                message: format!("no .ttf/.otf files in {}", dir.display()),
            });
        }

        let mut all_bytes = Vec::new();
        for path in paths {
            let bytes = std::fs::read(&path).map_err(|error| FontLoadError {
                message: format!("cannot read {}: {error}", path.display()),
            })?;
            all_bytes.push(bytes);
        }
        Self::from_bytes(all_bytes, default_family)
    }

    /// Build from raw font bytes only. This is the single constructor every
    /// other constructor funnels through: no path or platform lookup below
    /// this point.
    pub fn from_bytes(
        fonts: impl IntoIterator<Item = Vec<u8>>,
        default_family: &str,
    ) -> Result<Self, FontLoadError> {
        // FontMgr::new() is used strictly as a byte parser to introspect
        // family name and weight; no system family lookup happens here or
        // anywhere else in this crate.
        let parser = FontMgr::new();
        let mut faces = Vec::new();
        let mut families = BTreeSet::new();

        for bytes in fonts {
            let typeface = parser
                .new_from_data(&bytes, None)
                .ok_or_else(|| FontLoadError {
                    message: "font bytes did not parse as a typeface".to_owned(),
                })?;
            let family = typeface.family_name();
            let weight = *typeface.font_style().weight();
            let italic = typeface.font_style().slant()
                != skia_safe::font_style::Slant::Upright;
            families.insert(family.clone());
            faces.push(LoadedFace {
                bytes: Arc::new(bytes),
                family,
                alias: None,
                weight,
                italic,
            });
        }

        if !families.contains(default_family) {
            return Err(FontLoadError {
                message: format!(
                    "default family \"{default_family}\" is not among loaded families {families:?}"
                ),
            });
        }

        Ok(Self {
            id: NEXT_MANAGER_ID.fetch_add(1, Ordering::Relaxed),
            faces,
            families,
            default_family: default_family.to_owned(),
        })
    }

    pub fn default_family(&self) -> &str {
        &self.default_family
    }

    pub fn families(&self) -> impl Iterator<Item = &str> {
        self.families.iter().map(String::as_str)
    }

    /// Loaded weights per family, for diagnostics and tests.
    pub fn weights(&self, family: &str) -> Vec<i32> {
        let mut weights = self
            .faces
            .iter()
            .filter(|face| face.family == family)
            .map(|face| face.weight)
            .collect::<Vec<_>>();
        weights.sort_unstable();
        weights
    }

    /// A7b: whether `family` (or its alias) has at least one italic face loaded.
    /// Reads the slant parsed at registration — the byte-driven source of truth
    /// for whether requesting italic will find a real face or snap to upright
    /// (LUMS0105). For diagnostics, teaching, and tests.
    pub fn has_italic_face(&self, family: &str) -> bool {
        self.faces.iter().any(|face| {
            face.italic
                && (face.family == family || face.alias.as_deref() == Some(family))
        })
    }

    /// Resolve a requested family against the loaded set. Missing families
    /// fall back to the default family — explicitly and deterministically —
    /// and the resolution carries the warning diagnostic for callers that
    /// surface diagnostics.
    pub fn resolve_family(&self, requested: &str) -> FamilyResolution {
        if self.families.contains(requested) {
            FamilyResolution {
                requested: requested.to_owned(),
                family: requested.to_owned(),
                fallback: false,
            }
        } else {
            FamilyResolution {
                requested: requested.to_owned(),
                family: self.default_family.clone(),
                fallback: true,
            }
        }
    }

    /// Run `f` with this manager's thread-local Skia `FontCollection`. The
    /// collection is backed exclusively by the loaded bytes, never system fonts.
    pub fn with_collection<R>(&self, f: impl FnOnce(&mut FontCollection) -> R) -> R {
        COLLECTIONS.with(|cache| {
            let mut cache = cache.borrow_mut();
            let collection = cache
                .entry(self.id)
                .or_insert_with(|| self.build_collection());
            f(collection)
        })
    }

    /// Match a typeface by family + weight + slant through the same collection
    /// the shaper uses. Returns `None` only if the fallback family itself has no
    /// faces (impossible for a constructed manager). A7b: `italic` requests the
    /// `Slant::Italic` face; with no italic face loaded Skia snaps to the
    /// upright (the LUMS0105 advisory reports the snap).
    pub fn match_typeface(&self, family: &str, weight: i32, italic: bool) -> Option<Typeface> {
        let resolution = self.resolve_family(family);
        self.with_collection(|collection| {
            let style = skia_safe::FontStyle::new(
                weight.into(),
                skia_safe::font_style::Width::NORMAL,
                if italic {
                    skia_safe::font_style::Slant::Italic
                } else {
                    skia_safe::font_style::Slant::Upright
                },
            );
            collection
                .find_typefaces(&[resolution.family.as_str()], style)
                .into_iter()
                .next()
        })
    }

    /// The actual weight of the face the shaper resolves for `family` at the
    /// requested `weight`/`italic` (A6a D6.2). `Some(actual)` only when it
    /// differs from the request — the silent within-family weight snap
    /// `find_typefaces` performs — so callers can surface it as the LUMS0104
    /// advisory. `None` when the face matches exactly or no face resolves.
    pub fn resolved_weight(&self, family: &str, weight: i32, italic: bool) -> Option<i32> {
        let actual = *self
            .match_typeface(family, weight, italic)?
            .font_style()
            .weight();
        (actual != weight).then_some(actual)
    }

    /// A7b D2: the actual slant of the face the shaper resolves for `family` at
    /// the requested `weight`/`italic`. `Some(actual_is_italic)` only when it
    /// differs from the requested slant — the silent italic→upright snap
    /// `find_typefaces` performs when the family has no italic face — so callers
    /// surface it as the LUMS0105 advisory. `None` when the slant matches or no
    /// face resolves. Mirrors `resolved_weight`.
    pub fn resolved_slant(&self, family: &str, weight: i32, italic: bool) -> Option<bool> {
        let actual = self.match_typeface(family, weight, italic)?.font_style().slant()
            != skia_safe::font_style::Slant::Upright;
        (actual != italic).then_some(actual)
    }

    fn build_collection(&self) -> FontCollection {
        let parser = FontMgr::new();
        let mut provider = TypefaceFontProvider::new();
        for face in &self.faces {
            let typeface = parser
                .new_from_data(face.bytes.as_slice(), None)
                .expect("bytes parsed at construction time");
            if let Some(alias) = &face.alias {
                provider.register_typeface(typeface.clone(), Some(alias.as_str()));
            }
            provider.register_typeface(typeface, Some(face.family.as_str()));
        }

        let mut collection = FontCollection::new();
        let provider_mgr: FontMgr = provider.into();
        collection.set_asset_font_manager(Some(provider_mgr.clone()));
        // Keep fallback confined to loaded bytes. TypefaceFontProvider has no
        // character-match implementation, so enabling fallback alone cannot
        // supply missing glyphs: build_paragraph uses fallback_families below.
        collection.set_default_font_manager(Some(provider_mgr), Some(self.default_family.as_str()));
        collection.enable_font_fallback();
        collection
    }

    /// Explicit shaping chain shared with CanvasKit: primary, then the loaded
    /// default. Other loaded brand families are not implicit fallback choices.
    pub(crate) fn fallback_families<'a>(&'a self, primary: &'a str) -> Vec<&'a str> {
        let mut families = vec![primary];
        if primary != self.default_family {
            families.push(self.default_family.as_str());
        }
        families
    }

    /// Unique, non-whitespace/control characters missing from the primary face.
    pub(crate) fn missing_chars(
        &self,
        requested: &str,
        weight: i32,
        italic: bool,
        content: &str,
    ) -> Vec<char> {
        let resolution = self.resolve_family(requested);
        let style = skia_safe::FontStyle::new(
            weight.into(),
            skia_safe::font_style::Width::NORMAL,
            if italic {
                skia_safe::font_style::Slant::Italic
            } else {
                skia_safe::font_style::Slant::Upright
            },
        );
        let Some(primary) = self.with_collection(|collection| {
            collection
                .find_typefaces(&[resolution.family.as_str()], style)
                .into_iter()
                .next()
        }) else {
            return Vec::new();
        };

        // Unique gap characters the resolved family cannot supply directly.
        let mut seen = BTreeSet::new();
        let mut candidates = Vec::new();
        for ch in content.chars() {
            if ch.is_control() || ch.is_whitespace() || !seen.insert(ch) {
                continue;
            }
            if primary.unichar_to_glyph(ch as i32) == 0 {
                candidates.push(ch);
            }
        }
        candidates
    }

    /// Primary-face gaps covered by another loaded face, for SVG embedding.
    /// This is byte coverage, not proof of successful paragraph substitution;
    /// shaping diagnostics must also check the paragraph's unresolved glyphs.
    pub fn substituted_chars(
        &self,
        requested: &str,
        weight: i32,
        italic: bool,
        content: &str,
    ) -> Vec<char> {
        let candidates = self.missing_chars(requested, weight, italic, content);
        if candidates.is_empty() {
            return Vec::new();
        }
        let parser = FontMgr::new();
        let faces: Vec<Typeface> = self
            .faces
            .iter()
            .filter_map(|face| parser.new_from_data(face.bytes.as_slice(), None))
            .collect();
        candidates
            .into_iter()
            .filter(|ch| {
                faces
                    .iter()
                    .any(|face| face.unichar_to_glyph(*ch as i32) != 0)
            })
            .collect()
    }

    /// The loaded faces in registration order for SVG supplier coverage.
    /// Native shaping has the narrower explicit primary/default family chain.
    pub(crate) fn loaded_faces(&self) -> &[LoadedFace] {
        &self.faces
    }

    /// The loaded bytes behind the face `match_typeface` resolves for this
    /// request, with the face's actual identity (intrinsic family, weight,
    /// slant). SVG font embedding ships exactly these bytes, so the SVG
    /// viewer renders the face the painter used — parity by construction.
    /// `None` only when no face resolves at all (an unconstructable
    /// manager) or when the matched typeface cannot be traced back to a
    /// loaded face — both invariant breaches the caller must fail loudly on.
    pub fn matched_face_bytes(
        &self,
        family: &str,
        weight: i32,
        italic: bool,
    ) -> Option<(Arc<Vec<u8>>, String, i32, bool)> {
        let resolution = self.resolve_family(family);
        let typeface = self.match_typeface(family, weight, italic)?;
        let actual_weight = *typeface.font_style().weight();
        let actual_italic =
            typeface.font_style().slant() != skia_safe::font_style::Slant::Upright;
        // Trace back within the faces registered under the RESOLVED family
        // (intrinsic name or declared alias) — the same candidate set
        // `find_typefaces` matched among. Matching on intrinsic name alone
        // would confuse an aliased face with a same-named face from another
        // registration (e.g. a kit font whose bytes share the intrinsic
        // family of a bundled face).
        self.faces
            .iter()
            .find(|face| {
                (face.family == resolution.family
                    || face.alias.as_deref() == Some(resolution.family.as_str()))
                    && face.weight == actual_weight
                    && face.italic == actual_italic
            })
            .map(|face| {
                (
                    Arc::clone(&face.bytes),
                    face.family.clone(),
                    actual_weight,
                    actual_italic,
                )
            })
    }

    /// Deduplicated grouping used by tests: family -> sorted weights.
    pub fn family_weight_map(&self) -> BTreeMap<String, Vec<i32>> {
        let mut map: BTreeMap<String, Vec<i32>> = BTreeMap::new();
        for face in &self.faces {
            map.entry(face.family.clone())
                .or_default()
                .push(face.weight);
        }
        for weights in map.values_mut() {
            weights.sort_unstable();
        }
        map
    }
}
