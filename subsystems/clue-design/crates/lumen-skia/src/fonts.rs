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
#[derive(Clone)]
struct LoadedFace {
    bytes: Arc<Vec<u8>>,
    family: String,
    weight: i32,
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
    /// fonts read from the asset store). Faces whose bytes do not parse are
    /// skipped and reported — the bundled fallback set must never be lost to
    /// one bad kit font, so this constructor cannot fail.
    pub fn bundled_with(extra: impl IntoIterator<Item = Vec<u8>>) -> (Self, Vec<FontLoadError>) {
        let parser = FontMgr::new();
        let mut all: Vec<Vec<u8>> = BUNDLED_FONTS.iter().map(|bytes| bytes.to_vec()).collect();
        let mut errors = Vec::new();
        for bytes in extra {
            if parser.new_from_data(&bytes, None).is_some() {
                all.push(bytes);
            } else {
                errors.push(FontLoadError {
                    message: "brand font bytes did not parse as a typeface".to_owned(),
                });
            }
        }
        let manager = Self::from_bytes(all, DEFAULT_FONT_FAMILY)
            .expect("bundled Inter faces must parse");
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
            families.insert(family.clone());
            faces.push(LoadedFace {
                bytes: Arc::new(bytes),
                family,
                weight,
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
    /// collection is backed exclusively by the loaded bytes: no default font
    /// manager, font fallback disabled.
    pub fn with_collection<R>(&self, f: impl FnOnce(&mut FontCollection) -> R) -> R {
        COLLECTIONS.with(|cache| {
            let mut cache = cache.borrow_mut();
            let collection = cache
                .entry(self.id)
                .or_insert_with(|| self.build_collection());
            f(collection)
        })
    }

    /// Match a typeface by family + weight through the same collection the
    /// shaper uses. Returns `None` only if the fallback family itself has no
    /// faces (impossible for a constructed manager).
    pub fn match_typeface(&self, family: &str, weight: i32) -> Option<Typeface> {
        let resolution = self.resolve_family(family);
        self.with_collection(|collection| {
            let style = skia_safe::FontStyle::new(
                weight.into(),
                skia_safe::font_style::Width::NORMAL,
                skia_safe::font_style::Slant::Upright,
            );
            collection
                .find_typefaces(&[resolution.family.as_str()], style)
                .into_iter()
                .next()
        })
    }

    fn build_collection(&self) -> FontCollection {
        let parser = FontMgr::new();
        let mut provider = TypefaceFontProvider::new();
        for face in &self.faces {
            let typeface = parser
                .new_from_data(face.bytes.as_slice(), None)
                .expect("bytes parsed at construction time");
            provider.register_typeface(typeface, Some(face.family.as_str()));
        }

        let mut collection = FontCollection::new();
        let provider_mgr: FontMgr = provider.into();
        collection.set_asset_font_manager(Some(provider_mgr));
        // No default font manager and no fallback: resolution is exactly
        // the registered byte-backed faces, nothing else.
        collection.disable_font_fallback();
        collection
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
