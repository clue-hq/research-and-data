use crate::brand::BrandKit;
use crate::diagnostics::{Diagnostic, DiagnosticSubject, Phase};
use crate::ids::{AssetId, NodeId, SlotId};
use crate::scene::{Node, NodeKind, Scene};
use crate::slots::{ContentType, FocalPoint, ImageFitMode};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

const ASPECT_RATIO_TOLERANCE: f64 = 0.02;

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct AssetManifest {
    #[serde(default)]
    pub assets: BTreeMap<AssetId, AssetRecord>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AssetRecord {
    pub id: AssetId,
    pub label: String,
    pub kind: AssetKind,
    pub status: AssetStatus,
    pub source: AssetSource,
    #[serde(default)]
    pub media: AssetMediaMetadata,
    #[serde(default)]
    pub raster: Option<RasterAssetMetadata>,
    #[serde(default)]
    pub vector: Option<VectorAssetMetadata>,
    #[serde(default)]
    pub font: Option<FontAssetMetadata>,
    #[serde(default)]
    pub logo: Option<LogoAssetMetadata>,
    #[serde(default)]
    pub license: Option<AssetLicense>,
    #[serde(default)]
    pub provenance: AssetProvenance,
    #[serde(default)]
    pub tags: Vec<String>,
}

impl AssetRecord {
    pub fn is_image_compatible(&self) -> bool {
        matches!(
            self.kind,
            AssetKind::RasterImage | AssetKind::Vector | AssetKind::Logo
        )
    }

    pub fn is_logo_compatible(&self) -> bool {
        matches!(
            self.kind,
            AssetKind::Logo | AssetKind::Vector | AssetKind::RasterImage
        )
    }

    pub fn natural_aspect_ratio(&self) -> Option<f64> {
        self.logo
            .as_ref()
            .and_then(LogoAssetMetadata::aspect_ratio)
            .or_else(|| {
                self.raster
                    .as_ref()
                    .and_then(RasterAssetMetadata::aspect_ratio)
            })
            .or_else(|| {
                self.vector
                    .as_ref()
                    .and_then(VectorAssetMetadata::aspect_ratio)
            })
    }

    pub fn min_dpi(&self) -> Option<f64> {
        self.logo
            .as_ref()
            .and_then(LogoAssetMetadata::min_dpi)
            .or_else(|| self.raster.as_ref().and_then(RasterAssetMetadata::min_dpi))
    }

    pub fn has_transparency(&self) -> Option<bool> {
        self.logo
            .as_ref()
            .and_then(|metadata| metadata.has_transparency)
            .or_else(|| self.raster.as_ref().and_then(|metadata| metadata.has_alpha))
            .or_else(|| {
                self.vector
                    .as_ref()
                    .and_then(|metadata| metadata.has_transparency)
            })
    }

    pub fn allows_export(&self) -> bool {
        self.license
            .as_ref()
            .map(|license| license.allow_export)
            .unwrap_or(true)
    }

    pub fn allows_modification(&self) -> bool {
        self.license
            .as_ref()
            .map(|license| license.allow_modification)
            .unwrap_or(true)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AssetKind {
    RasterImage,
    Vector,
    Font,
    Logo,
    Document,
    Other,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AssetStatus {
    Pending,
    Ready,
    Failed,
    Archived,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum AssetSource {
    Uploaded {
        asset_id: Option<AssetId>,
        filename: Option<String>,
        uploaded_by: Option<String>,
    },
    Generated {
        request_id: Option<String>,
        model: String,
    },
    /// A model-edited derivative of an existing asset (Phase 3b image edit /
    /// remove-background). `source_asset_id` chains provenance to the parent.
    Edited {
        request_id: Option<String>,
        model: String,
        source_asset_id: AssetId,
    },
    Vectorized {
        source_asset_id: AssetId,
        tool: Option<String>,
    },
    Website {
        url: String,
        captured_at: Option<String>,
    },
    BrandGuide {
        source_asset_id: Option<AssetId>,
        label: String,
    },
    Manual {
        label: String,
    },
    Workspace {
        asset_id: AssetId,
    },
    Url {
        url: String,
    },
    System {
        family: String,
    },
    Unknown,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct AssetMediaMetadata {
    pub mime_type: Option<String>,
    pub filename: Option<String>,
    pub byte_length: Option<u64>,
    pub digest: Option<AssetDigest>,
    pub location: Option<AssetLocation>,
    /// Optional derived preview reference. Metadata only: thumbnail bytes
    /// live in the asset store like any other bytes, never in the Scene.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub thumbnail: Option<AssetThumbnail>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AssetThumbnail {
    pub location: AssetLocation,
    pub mime_type: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pixel_width: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pixel_height: Option<u32>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AssetDigest {
    pub algorithm: String,
    pub value: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AssetLocation {
    pub provider: String,
    pub opaque_ref: String,
    pub url: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RasterAssetMetadata {
    pub pixel_width: u32,
    pub pixel_height: u32,
    pub dpi_x: Option<f64>,
    pub dpi_y: Option<f64>,
    pub has_alpha: Option<bool>,
    pub color_profile: Option<String>,
    pub aspect_ratio: Option<f64>,
}

impl RasterAssetMetadata {
    pub fn aspect_ratio(&self) -> Option<f64> {
        self.aspect_ratio.or_else(|| {
            if self.pixel_height == 0 {
                None
            } else {
                Some(self.pixel_width as f64 / self.pixel_height as f64)
            }
        })
    }

    pub fn min_dpi(&self) -> Option<f64> {
        match (self.dpi_x, self.dpi_y) {
            (Some(x), Some(y)) => Some(x.min(y)),
            (Some(x), None) => Some(x),
            (None, Some(y)) => Some(y),
            (None, None) => None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct VectorAssetMetadata {
    pub width: Option<f64>,
    pub height: Option<f64>,
    pub view_box: Option<[f64; 4]>,
    pub has_transparency: Option<bool>,
    pub path_data: Option<String>,
}

impl VectorAssetMetadata {
    pub fn aspect_ratio(&self) -> Option<f64> {
        match (self.width, self.height) {
            (Some(width), Some(height)) if height > 0.0 => Some(width / height),
            _ => self
                .view_box
                .and_then(|[_x, _y, width, height]| (height > 0.0).then_some(width / height)),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct FontAssetMetadata {
    pub family: String,
    pub postscript_name: Option<String>,
    #[serde(default)]
    pub weights: Vec<u16>,
    #[serde(default)]
    pub styles: Vec<String>,
    #[serde(default)]
    pub scripts: Vec<String>,
    pub embeddable: bool,
    pub subsettable: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LogoAssetMetadata {
    pub pixel_width: Option<u32>,
    pub pixel_height: Option<u32>,
    pub width: Option<f64>,
    pub height: Option<f64>,
    pub dpi_x: Option<f64>,
    pub dpi_y: Option<f64>,
    pub has_transparency: Option<bool>,
    pub color_mode: Option<String>,
    pub clearspace: Option<f64>,
}

impl LogoAssetMetadata {
    pub fn aspect_ratio(&self) -> Option<f64> {
        match (self.width, self.height) {
            (Some(width), Some(height)) if height > 0.0 => Some(width / height),
            _ => match (self.pixel_width, self.pixel_height) {
                (Some(width), Some(height)) if height > 0 => Some(width as f64 / height as f64),
                _ => None,
            },
        }
    }

    pub fn min_dpi(&self) -> Option<f64> {
        match (self.dpi_x, self.dpi_y) {
            (Some(x), Some(y)) => Some(x.min(y)),
            (Some(x), None) => Some(x),
            (None, Some(y)) => Some(y),
            (None, None) => None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AssetLicense {
    pub name: String,
    #[serde(default)]
    pub allow_export: bool,
    #[serde(default)]
    pub allow_modification: bool,
    #[serde(default)]
    pub allow_embedding: bool,
    #[serde(default)]
    pub allow_subsetting: bool,
    pub source_url: Option<String>,
    #[serde(default)]
    pub restrictions: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct AssetProvenance {
    pub created_by: Option<String>,
    pub created_at: Option<String>,
    pub source_label: Option<String>,
    pub confidence: Option<f64>,
    #[serde(default)]
    pub notes: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct AssetPlacement {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub fit: Option<ImageFitMode>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub focal_point: Option<FocalPoint>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub preserve_transparency: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub alt_text: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AssetGenerationRequest {
    pub request_id: String,
    pub prompt: String,
    pub output_kind: AssetKind,
    pub target_node_id: Option<NodeId>,
    pub target_slot_id: Option<SlotId>,
    pub constraints: AssetGenerationConstraints,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct AssetGenerationConstraints {
    pub width: Option<u32>,
    pub height: Option<u32>,
    pub mime_type: Option<String>,
    pub transparent_background: Option<bool>,
    #[serde(default)]
    pub brand_notes: Vec<String>,
    /// Target aspect ratio hint matched to the frame (e.g. "16:9"); the provider
    /// translates it to width/height when explicit dimensions are absent, so a
    /// 1:1 frame is never stretched into 16:9. Mirrors Brilliant `aspectRatio`.
    #[serde(default)]
    pub aspect_ratio: Option<String>,
    /// Role-appropriate resolution tier ("1k"/"2k"/"4k"); the provider maps it to a
    /// long-edge pixel size. Mirrors Brilliant `imageSize`.
    #[serde(default)]
    pub image_size: Option<String>,
    /// Reference assets to condition generation on (style/subject). The field lands
    /// now for forward-compat; reference-image *use* is Slice 1. Mirrors Brilliant
    /// `referenceElementIds`.
    #[serde(default)]
    pub reference_asset_ids: Vec<AssetId>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AssetGenerationResult {
    pub request_id: String,
    pub asset: AssetRecord,
    #[serde(default)]
    pub provider_metadata: BTreeMap<String, String>,
    #[serde(default)]
    pub diagnostics: Vec<Diagnostic>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AssetVectorizationRequest {
    pub request_id: String,
    pub source_asset_id: AssetId,
    pub target_node_id: Option<NodeId>,
    pub target_slot_id: Option<SlotId>,
    pub preserve_colors: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AssetVectorizationResult {
    pub request_id: String,
    pub source_asset_id: AssetId,
    pub asset: AssetRecord,
    #[serde(default)]
    pub provider_metadata: BTreeMap<String, String>,
    #[serde(default)]
    pub diagnostics: Vec<Diagnostic>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AssetValidationOptions {
    pub strict_references: bool,
    pub validate_slot_policies: bool,
    pub validate_licensing: bool,
}

impl AssetValidationOptions {
    pub fn strict() -> Self {
        Self {
            strict_references: true,
            validate_slot_policies: true,
            validate_licensing: true,
        }
    }
}

impl Default for AssetValidationOptions {
    fn default() -> Self {
        Self {
            strict_references: false,
            validate_slot_policies: true,
            validate_licensing: true,
        }
    }
}

pub fn validate_asset_manifest(manifest: &AssetManifest) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    validate_asset_records(&manifest.assets, &mut diagnostics);
    diagnostics
}

pub fn validate_scene_assets(scene: &Scene, options: AssetValidationOptions) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();

    validate_asset_records(&scene.assets, &mut diagnostics);
    validate_node_asset_refs(scene, options, &mut diagnostics);
    if options.validate_slot_policies {
        validate_slot_asset_bindings(scene, options, &mut diagnostics);
    }

    diagnostics
}

pub fn validate_brand_asset_references(scene: &Scene, brand_kit: &BrandKit) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();

    for (font_id, font) in &brand_kit.assets.fonts {
        for face in &font.faces {
            let Some(asset_id) = &face.asset_id else {
                continue;
            };
            match scene.assets.get(asset_id) {
                Some(asset) if matches!(&asset.kind, AssetKind::Font) => {}
                Some(asset) => diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMA0501",
                    format!(
                        "brand font {} face references asset {} with incompatible kind {:?}",
                        font_id, asset_id, asset.kind
                    ),
                    Some(DiagnosticSubject::Asset(asset_id.clone())),
                )),
                None => diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMA0500",
                    format!(
                        "brand font {} face references missing asset {}",
                        font_id, asset_id
                    ),
                    Some(DiagnosticSubject::Document),
                )),
            }
        }
    }

    for (logo_id, logo) in &brand_kit.assets.logos {
        for variant in &logo.variants {
            match scene.assets.get(&variant.asset_id) {
                Some(asset) if asset.is_logo_compatible() => {}
                Some(asset) => diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMA0511",
                    format!(
                        "brand logo {} variant {} references asset {} with incompatible kind {:?}",
                        logo_id, variant.name, variant.asset_id, asset.kind
                    ),
                    Some(DiagnosticSubject::Asset(variant.asset_id.clone())),
                )),
                None => diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMA0510",
                    format!(
                        "brand logo {} variant {} references missing asset {}",
                        logo_id, variant.name, variant.asset_id
                    ),
                    Some(DiagnosticSubject::Document),
                )),
            }
        }
    }

    for (image_id, image) in &brand_kit.assets.images {
        match scene.assets.get(&image.asset_id) {
            Some(asset) if asset.is_image_compatible() => {}
            Some(asset) => diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMA0521",
                format!(
                    "brand image {} references asset {} with incompatible kind {:?}",
                    image_id, image.asset_id, asset.kind
                ),
                Some(DiagnosticSubject::Asset(image.asset_id.clone())),
            )),
            None => diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMA0520",
                format!(
                    "brand image {} references missing asset {}",
                    image_id, image.asset_id
                ),
                Some(DiagnosticSubject::Document),
            )),
        }
    }

    diagnostics
}

fn validate_asset_records(
    assets: &BTreeMap<AssetId, AssetRecord>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    for (asset_id, asset) in assets {
        if asset_id != &asset.id {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMA0100",
                format!(
                    "asset map key {} does not match embedded asset id {}",
                    asset_id, asset.id
                ),
                Some(DiagnosticSubject::Asset(asset_id.clone())),
            ));
        }

        if asset.label.trim().is_empty() {
            diagnostics.push(Diagnostic::warning(
                Phase::Validation,
                "LUMA0101",
                format!("asset {} has an empty label", asset.id),
                Some(DiagnosticSubject::Asset(asset.id.clone())),
            ));
        }

        if let Some(byte_length) = asset.media.byte_length {
            if byte_length == 0 {
                diagnostics.push(Diagnostic::warning(
                    Phase::Validation,
                    "LUMA0102",
                    format!("asset {} has zero byte_length metadata", asset.id),
                    Some(DiagnosticSubject::Asset(asset.id.clone())),
                ));
            }
        }

        match &asset.kind {
            AssetKind::RasterImage => {
                if asset.raster.is_none() {
                    diagnostics.push(Diagnostic::warning(
                        Phase::Validation,
                        "LUMA0110",
                        format!("raster asset {} has no raster metadata", asset.id),
                        Some(DiagnosticSubject::Asset(asset.id.clone())),
                    ));
                }
            }
            AssetKind::Vector => {
                if asset.vector.is_none() {
                    diagnostics.push(Diagnostic::warning(
                        Phase::Validation,
                        "LUMA0111",
                        format!("vector asset {} has no vector metadata", asset.id),
                        Some(DiagnosticSubject::Asset(asset.id.clone())),
                    ));
                }
            }
            AssetKind::Font => {
                if asset.font.is_none() {
                    diagnostics.push(Diagnostic::warning(
                        Phase::Validation,
                        "LUMA0112",
                        format!("font asset {} has no font metadata", asset.id),
                        Some(DiagnosticSubject::Asset(asset.id.clone())),
                    ));
                }
            }
            AssetKind::Logo => {
                if asset.logo.is_none() && asset.raster.is_none() && asset.vector.is_none() {
                    diagnostics.push(Diagnostic::warning(
                        Phase::Validation,
                        "LUMA0113",
                        format!(
                            "logo asset {} has no logo, raster, or vector metadata",
                            asset.id
                        ),
                        Some(DiagnosticSubject::Asset(asset.id.clone())),
                    ));
                }
            }
            AssetKind::Document | AssetKind::Other => {}
        }
    }
}

fn validate_node_asset_refs(
    scene: &Scene,
    options: AssetValidationOptions,
    diagnostics: &mut Vec<Diagnostic>,
) {
    for node in scene.nodes.values() {
        if let NodeKind::Image(image) = &node.kind {
            validate_node_asset_ref(
                scene,
                &node.id,
                &image.asset_id,
                AssetNodeExpectation::Image,
                options,
                diagnostics,
            );
        }

        if let Some(asset_id) = &node.source_asset_id {
            let expectation = match node.kind {
                NodeKind::Vector(_) => AssetNodeExpectation::Vector,
                NodeKind::Text(_) => AssetNodeExpectation::Font,
                NodeKind::Image(_) => AssetNodeExpectation::Image,
                _ => AssetNodeExpectation::Any,
            };
            validate_node_asset_ref(scene, &node.id, asset_id, expectation, options, diagnostics);
        } else if options.strict_references && matches!(node.kind, NodeKind::Vector(_)) {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMA0203",
                format!("vector node {} has no source_asset_id", node.id),
                Some(DiagnosticSubject::Node(node.id.clone())),
            ));
        }
    }
}

fn validate_node_asset_ref(
    scene: &Scene,
    node_id: &NodeId,
    asset_id: &AssetId,
    expectation: AssetNodeExpectation,
    options: AssetValidationOptions,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let Some(asset) = scene.assets.get(asset_id) else {
        if options.strict_references {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMA0200",
                format!("node {} references missing asset {}", node_id, asset_id),
                Some(DiagnosticSubject::Node(node_id.clone())),
            ));
        }
        return;
    };

    let compatible = match expectation {
        AssetNodeExpectation::Any => true,
        AssetNodeExpectation::Image => asset.is_image_compatible(),
        AssetNodeExpectation::Vector => matches!(&asset.kind, AssetKind::Vector),
        AssetNodeExpectation::Font => matches!(&asset.kind, AssetKind::Font),
    };

    if !compatible {
        diagnostics.push(Diagnostic::error(
            Phase::Validation,
            "LUMA0201",
            format!(
                "node {} references asset {} with incompatible kind {:?}",
                node_id, asset_id, asset.kind
            ),
            Some(DiagnosticSubject::Node(node_id.clone())),
        ));
    }
}

fn validate_slot_asset_bindings(
    scene: &Scene,
    options: AssetValidationOptions,
    diagnostics: &mut Vec<Diagnostic>,
) {
    for slot in scene.slots.values() {
        let image_like = matches!(slot.content_type, ContentType::Image | ContentType::Logo);
        if !image_like {
            continue;
        }

        for node_id in &slot.bound_nodes {
            let Some(node) = scene.nodes.get(node_id) else {
                continue;
            };
            if !node_can_carry_image_asset(node) {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMA0300",
                    format!(
                        "image-like slot {} binds non-image node {}",
                        slot.key, node_id
                    ),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
                continue;
            }

            let Some(asset_id) = node_asset_id(node) else {
                if options.strict_references {
                    diagnostics.push(Diagnostic::error(
                        Phase::Validation,
                        "LUMA0301",
                        format!(
                            "image-like slot {} binds node {} without an asset reference",
                            slot.key, node_id
                        ),
                        Some(DiagnosticSubject::Slot(slot.id.clone())),
                    ));
                }
                continue;
            };

            let Some(asset) = scene.assets.get(asset_id) else {
                if options.strict_references {
                    diagnostics.push(Diagnostic::error(
                        Phase::Validation,
                        "LUMA0302",
                        format!(
                            "image-like slot {} binds node {} with missing asset {}",
                            slot.key, node_id, asset_id
                        ),
                        Some(DiagnosticSubject::Slot(slot.id.clone())),
                    ));
                }
                continue;
            };

            let compatible = match slot.content_type {
                ContentType::Image => asset.is_image_compatible(),
                ContentType::Logo => asset.is_logo_compatible(),
                _ => true,
            };
            if !compatible {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMA0303",
                    format!(
                        "slot {} expects {:?} but asset {} is {:?}",
                        slot.key, slot.content_type, asset.id, asset.kind
                    ),
                    Some(DiagnosticSubject::Slot(slot.id.clone())),
                ));
            }

            if let Some(policy) = &slot.image_policy {
                validate_asset_against_policy(
                    slot.id.clone(),
                    &slot.key.to_string(),
                    asset,
                    policy,
                    diagnostics,
                );
            }

            if options.validate_licensing {
                validate_placed_asset_license(
                    slot.id.clone(),
                    &slot.key.to_string(),
                    asset,
                    slot.image_policy.as_ref().map(|policy| policy.fit.clone()),
                    diagnostics,
                );
            }
        }
    }
}

fn validate_asset_against_policy(
    slot_id: SlotId,
    slot_key: &str,
    asset: &AssetRecord,
    policy: &crate::slots::ImagePolicy,
    diagnostics: &mut Vec<Diagnostic>,
) {
    if let (Some(expected), Some(actual)) = (policy.aspect_ratio, asset.natural_aspect_ratio()) {
        if (expected - actual).abs() > ASPECT_RATIO_TOLERANCE {
            diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMA0310",
                format!(
                    "slot {} expects aspect ratio {:.3} but asset {} is {:.3}",
                    slot_key, expected, asset.id, actual
                ),
                Some(DiagnosticSubject::Slot(slot_id.clone())),
            ));
        }
    }

    if let Some(min_dpi) = policy.min_dpi {
        match asset.min_dpi() {
            Some(actual) if actual < f64::from(min_dpi) => {
                diagnostics.push(Diagnostic::error(
                    Phase::Validation,
                    "LUMA0311",
                    format!(
                        "slot {} requires at least {} DPI but asset {} is {:.1} DPI",
                        slot_key, min_dpi, asset.id, actual
                    ),
                    Some(DiagnosticSubject::Slot(slot_id.clone())),
                ));
            }
            None => diagnostics.push(Diagnostic::warning(
                Phase::Validation,
                "LUMA0312",
                format!(
                    "slot {} requires DPI metadata but asset {} has none",
                    slot_key, asset.id
                ),
                Some(DiagnosticSubject::Slot(slot_id.clone())),
            )),
            _ => {}
        }
    }

    if policy.preserve_transparency {
        match asset.has_transparency() {
            Some(true) => {}
            Some(false) => diagnostics.push(Diagnostic::error(
                Phase::Validation,
                "LUMA0313",
                format!(
                    "slot {} requires preserved transparency but asset {} is opaque",
                    slot_key, asset.id
                ),
                Some(DiagnosticSubject::Slot(slot_id.clone())),
            )),
            None => diagnostics.push(Diagnostic::warning(
                Phase::Validation,
                "LUMA0314",
                format!(
                    "slot {} requires transparency metadata but asset {} has none",
                    slot_key, asset.id
                ),
                Some(DiagnosticSubject::Slot(slot_id.clone())),
            )),
        }
    }

    if matches!(policy.fit, ImageFitMode::Crop) && policy.focal_point.is_none() {
        diagnostics.push(Diagnostic::warning(
            Phase::Validation,
            "LUMA0315",
            format!("slot {} crops images without a focal point", slot_key),
            Some(DiagnosticSubject::Slot(slot_id)),
        ));
    }
}

fn validate_placed_asset_license(
    slot_id: SlotId,
    slot_key: &str,
    asset: &AssetRecord,
    fit: Option<ImageFitMode>,
    diagnostics: &mut Vec<Diagnostic>,
) {
    if !asset.allows_export() {
        diagnostics.push(Diagnostic::error(
            Phase::Validation,
            "LUMA0400",
            format!(
                "slot {} uses asset {} that is not exportable",
                slot_key, asset.id
            ),
            Some(DiagnosticSubject::Slot(slot_id.clone())),
        ));
    }

    if matches!(fit, Some(ImageFitMode::Crop)) && !asset.allows_modification() {
        diagnostics.push(Diagnostic::error(
            Phase::Validation,
            "LUMA0401",
            format!(
                "slot {} crops asset {} but its license does not allow modification",
                slot_key, asset.id
            ),
            Some(DiagnosticSubject::Slot(slot_id)),
        ));
    }
}

fn node_can_carry_image_asset(node: &Node) -> bool {
    matches!(node.kind, NodeKind::Image(_) | NodeKind::Vector(_))
}

fn node_asset_id(node: &Node) -> Option<&AssetId> {
    if let NodeKind::Image(image) = &node.kind {
        return Some(&image.asset_id);
    }
    node.source_asset_id.as_ref()
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum AssetNodeExpectation {
    Any,
    Image,
    Vector,
    Font,
}

#[cfg(test)]
mod generation_constraints_tests {
    use super::AssetGenerationConstraints;

    #[test]
    fn back_compat_defaults_for_missing_step7_fields() {
        // Pre-Step-7 payloads lack the new fields → serde-default (None / empty).
        let old = r#"{"width":1024,"height":768,"brand_notes":["navy"]}"#;
        let parsed: AssetGenerationConstraints = serde_json::from_str(old).unwrap();
        assert_eq!(parsed.width, Some(1024));
        assert_eq!(parsed.brand_notes, vec!["navy".to_owned()]);
        assert_eq!(parsed.aspect_ratio, None);
        assert_eq!(parsed.image_size, None);
        assert!(parsed.reference_asset_ids.is_empty());
    }

    #[test]
    fn round_trip_preserves_aspect_size_and_references() {
        let json = r#"{"aspect_ratio":"16:9","image_size":"2k","reference_asset_ids":["asset_ref_a","asset_ref_b"]}"#;
        let parsed: AssetGenerationConstraints = serde_json::from_str(json).unwrap();
        assert_eq!(parsed.aspect_ratio.as_deref(), Some("16:9"));
        assert_eq!(parsed.image_size.as_deref(), Some("2k"));
        assert_eq!(parsed.reference_asset_ids.len(), 2);

        let reserialized = serde_json::to_string(&parsed).unwrap();
        let again: AssetGenerationConstraints = serde_json::from_str(&reserialized).unwrap();
        assert_eq!(parsed, again);
    }
}

#[cfg(test)]
mod asset_source_tests {
    use super::{AssetId, AssetSource};

    #[test]
    fn edited_variant_serde_round_trip() {
        // Phase 3b: an edited derivative tags "edited" and chains the parent via
        // snake_case `source_asset_id`, matching the API's persisted `source`.
        let source = AssetSource::Edited {
            request_id: Some("asset_gen_abc123".to_owned()),
            model: "google/gemini-2.5-flash-image".to_owned(),
            source_asset_id: AssetId::from("asset_parent_0001"),
        };

        let json = serde_json::to_value(&source).unwrap();
        assert_eq!(json["kind"], "edited");
        assert_eq!(json["request_id"], "asset_gen_abc123");
        assert_eq!(json["model"], "google/gemini-2.5-flash-image");
        assert_eq!(json["source_asset_id"], "asset_parent_0001");

        let back: AssetSource = serde_json::from_value(json).unwrap();
        assert_eq!(back, source);
    }

    #[test]
    fn edited_variant_parses_from_stored_shape() {
        let stored = r#"{"kind":"edited","request_id":null,"model":"m","source_asset_id":"asset_p"}"#;
        let parsed: AssetSource = serde_json::from_str(stored).unwrap();
        assert_eq!(
            parsed,
            AssetSource::Edited {
                request_id: None,
                model: "m".to_owned(),
                source_asset_id: AssetId::from("asset_p"),
            }
        );
    }
}
