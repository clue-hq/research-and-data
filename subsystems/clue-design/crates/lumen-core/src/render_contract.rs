use crate::diagnostics::{Diagnostic, DiagnosticSubject, Phase};
use crate::ids::PageId;
use crate::scene::{EffectKind, Node, Paint, Scene, StrokeAlign};
use serde::{Deserialize, Serialize};
use std::error::Error;
use std::fmt;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RenderIntent {
    EditorPreview,
    Export,
    AgentCritique,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum RenderTarget {
    Svg,
    Png { scale: f64 },
    Pdf,
    KonvaScene,
    FigmaManifest,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RenderManifest {
    pub target: RenderTarget,
    pub page_ids: Vec<PageId>,
    pub mime_type: String,
    pub bytes: Option<Vec<u8>>,
    pub sidecar_json: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RendererError {
    pub code: &'static str,
    pub message: String,
}

impl RendererError {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

impl fmt::Display for RendererError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl Error for RendererError {}

pub trait RendererAdapter {
    fn render(
        &self,
        scene: &crate::scene::Scene,
        target: RenderTarget,
        intent: RenderIntent,
        page_ids: &[PageId],
    ) -> Result<RenderManifest, RendererError>;
}

/// Effects Contract V0 feature vocabulary: the renderable surface the
/// support matrix speaks about. Scanned from scenes by
/// `effect_features_for_node`.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EffectFeature {
    MultiFill,
    MultiStroke,
    LinearGradientPaint,
    RadialGradientPaint,
    StrokeDash,
    StrokeCapJoin,
    StrokeAlignment,
    DropShadow,
    DropShadowSpread,
    LayeredShadows,
    Glow,
    LayerBlur,
    InnerShadow,
    /// A6a text features (D8).
    TextStroke,
    TextDecoration,
    TextTransform,
    TextEllipsis,
    ParagraphSpacing,
}

impl EffectFeature {
    pub fn label(&self) -> &'static str {
        match self {
            Self::MultiFill => "multiple fills",
            Self::MultiStroke => "multiple strokes",
            Self::LinearGradientPaint => "linear gradient paint",
            Self::RadialGradientPaint => "radial gradient paint",
            Self::StrokeDash => "stroke dash pattern",
            Self::StrokeCapJoin => "stroke cap/join",
            Self::StrokeAlignment => "inside/outside stroke alignment",
            Self::DropShadow => "drop shadow",
            Self::DropShadowSpread => "drop shadow spread",
            Self::LayeredShadows => "layered drop shadows",
            Self::Glow => "glow",
            Self::LayerBlur => "layer blur",
            Self::InnerShadow => "inner shadow",
            Self::TextStroke => "text stroke",
            Self::TextDecoration => "text underline/strikethrough",
            Self::TextTransform => "text case transform",
            Self::TextEllipsis => "text ellipsis truncation",
            Self::ParagraphSpacing => "paragraph spacing",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EffectSupportLevel {
    /// The format represents the feature faithfully.
    Native,
    /// The format renders something close but not exact; an explicit
    /// diagnostic must accompany the output.
    Approximate,
    /// The format cannot represent the feature; the renderer must degrade
    /// loudly (diagnostic), never silently wrong.
    Unsupported,
}

/// The per-format support matrix (Decision 4: code, not prose). Exporters
/// and preflight consult this table and emit `LUMX` diagnostics for
/// anything not `Native`.
pub struct RendererEffectSupport;

impl RendererEffectSupport {
    pub fn level(target: &RenderTarget, feature: EffectFeature) -> EffectSupportLevel {
        match target {
            // PNG raster paints the scene directly through Skia (Wave 1
            // Track A); it matches the SVG verdicts, with stroke alignment
            // kept Approximate (native for rect/ellipse only).
            // SVG text decoration is the CSS presentation attribute; its
            // underline metrics vary slightly across viewers, so it is
            // Approximate here (Native on the Skia raster). Every other text
            // feature is Native on both.
            RenderTarget::Svg => match feature {
                EffectFeature::StrokeAlignment => EffectSupportLevel::Approximate,
                EffectFeature::TextDecoration => EffectSupportLevel::Approximate,
                _ => EffectSupportLevel::Native,
            },
            RenderTarget::Png { .. } => match feature {
                EffectFeature::StrokeAlignment => EffectSupportLevel::Approximate,
                _ => EffectSupportLevel::Native,
            },
            RenderTarget::KonvaScene => match feature {
                EffectFeature::StrokeAlignment
                | EffectFeature::DropShadowSpread
                | EffectFeature::LayeredShadows
                // Legacy Konva preview: blur/glow approximate the merged
                // filter; inner shadow has no native Konva form.
                | EffectFeature::Glow
                | EffectFeature::LayerBlur => EffectSupportLevel::Approximate,
                EffectFeature::InnerShadow
                // A6a text features are not represented by the legacy Konva
                // preview (no CanvasKit contract target in A6a — §9 debt).
                | EffectFeature::TextStroke
                | EffectFeature::TextDecoration
                | EffectFeature::TextTransform
                | EffectFeature::TextEllipsis
                | EffectFeature::ParagraphSpacing => EffectSupportLevel::Unsupported,
                _ => EffectSupportLevel::Native,
            },
            // PDF V0 is solid-paint-only: the first solid fill/stroke
            // renders, everything else degrades with diagnostics.
            RenderTarget::Pdf => match feature {
                EffectFeature::MultiFill
                | EffectFeature::MultiStroke
                | EffectFeature::StrokeDash
                | EffectFeature::StrokeCapJoin
                | EffectFeature::StrokeAlignment => EffectSupportLevel::Approximate,
                EffectFeature::LinearGradientPaint
                | EffectFeature::RadialGradientPaint
                | EffectFeature::DropShadow
                | EffectFeature::DropShadowSpread
                | EffectFeature::LayeredShadows
                | EffectFeature::Glow
                | EffectFeature::LayerBlur
                | EffectFeature::InnerShadow
                // PDF renders neither text strokes nor decoration (loud
                // per-node advisories emitted at export, D2/D5).
                | EffectFeature::TextStroke
                | EffectFeature::TextDecoration => EffectSupportLevel::Unsupported,
                // Case transform, ellipsis, and paragraph spacing are carried
                // by the measured lines PDF already consumes — string-level /
                // measurer-owned, so Native.
                EffectFeature::TextTransform
                | EffectFeature::TextEllipsis
                | EffectFeature::ParagraphSpacing => EffectSupportLevel::Native,
            },
            // The Figma manifest is a structural sidecar, not a visual
            // render; it does not represent the effect surface.
            RenderTarget::FigmaManifest => EffectSupportLevel::Unsupported,
        }
    }
}

/// Scan one node for the V0 effect features it uses, in stable order.
pub fn effect_features_for_node(node: &Node) -> Vec<EffectFeature> {
    let mut features = Vec::new();
    if node.fills.len() > 1 {
        features.push(EffectFeature::MultiFill);
    }
    if node.strokes.len() > 1 {
        features.push(EffectFeature::MultiStroke);
    }
    let paints = node
        .fills
        .iter()
        .map(|fill| &fill.paint)
        .chain(node.strokes.iter().map(|stroke| &stroke.paint));
    let mut linear = false;
    let mut radial = false;
    for paint in paints {
        match paint {
            Paint::LinearGradient { .. } => linear = true,
            Paint::RadialGradient { .. } => radial = true,
            Paint::Solid { .. } | Paint::Token { .. } => {}
        }
    }
    if linear {
        features.push(EffectFeature::LinearGradientPaint);
    }
    if radial {
        features.push(EffectFeature::RadialGradientPaint);
    }
    if node
        .strokes
        .iter()
        .any(|stroke| stroke.dash.as_ref().is_some_and(|dash| !dash.is_empty()))
    {
        features.push(EffectFeature::StrokeDash);
    }
    if node.strokes.iter().any(|stroke| {
        stroke.cap != crate::scene::StrokeCap::default()
            || stroke.join != crate::scene::StrokeJoin::default()
    }) {
        features.push(EffectFeature::StrokeCapJoin);
    }
    if node
        .strokes
        .iter()
        .any(|stroke| stroke.align != StrokeAlign::Center)
    {
        features.push(EffectFeature::StrokeAlignment);
    }
    let mut drop_shadows = 0usize;
    let mut has_drop_shadow_spread = false;
    let mut has_glow = false;
    let mut has_layer_blur = false;
    let mut has_inner_shadow = false;
    for effect in &node.effects {
        match &effect.kind {
            EffectKind::DropShadow { spread, .. } => {
                drop_shadows += 1;
                if *spread != 0.0 {
                    has_drop_shadow_spread = true;
                }
            }
            EffectKind::Glow { .. } => has_glow = true,
            EffectKind::LayerBlur { .. } => has_layer_blur = true,
            EffectKind::InnerShadow { .. } => has_inner_shadow = true,
        }
    }
    if drop_shadows > 0 {
        features.push(EffectFeature::DropShadow);
    }
    if has_drop_shadow_spread {
        features.push(EffectFeature::DropShadowSpread);
    }
    if drop_shadows > 1 {
        features.push(EffectFeature::LayeredShadows);
    }
    if has_glow {
        features.push(EffectFeature::Glow);
    }
    if has_layer_blur {
        features.push(EffectFeature::LayerBlur);
    }
    if has_inner_shadow {
        features.push(EffectFeature::InnerShadow);
    }
    // A6a text features (D8): only text nodes carry them, and each fires from
    // the authored property, in stable order after the shared effect surface.
    if let crate::scene::NodeKind::Text(text) = &node.kind {
        if !node.strokes.is_empty() {
            features.push(EffectFeature::TextStroke);
        }
        if text.underline || text.strikethrough {
            features.push(EffectFeature::TextDecoration);
        }
        if text.text_transform != crate::scene::TextTransform::None {
            features.push(EffectFeature::TextTransform);
        }
        if text.truncate {
            features.push(EffectFeature::TextEllipsis);
        }
        if text.paragraph_spacing > 0.0 {
            features.push(EffectFeature::ParagraphSpacing);
        }
    }
    features
}

/// Matrix verdicts for every node on the requested pages (all pages when
/// empty): one `LUMX0001` (approximate) or `LUMX0002` (unsupported)
/// diagnostic per non-native feature in use. This is the explicit-fallback
/// surface exporters and preflight share — silence always means Native.
pub fn effect_support_diagnostics(
    scene: &Scene,
    page_ids: &[PageId],
    target: &RenderTarget,
) -> Vec<Diagnostic> {
    let mut node_ids = Vec::new();
    let pages: Vec<_> = if page_ids.is_empty() {
        scene.pages.keys().cloned().collect()
    } else {
        page_ids.to_vec()
    };
    for page_id in &pages {
        let Some(page) = scene.pages.get(page_id) else {
            continue;
        };
        for child_id in &page.children {
            node_ids.push(child_id.clone());
            node_ids.extend(scene.descendants_of(child_id));
        }
    }

    let mut diagnostics = Vec::new();
    for node_id in node_ids {
        let Some(node) = scene.nodes.get(&node_id) else {
            continue;
        };
        for feature in effect_features_for_node(node) {
            match RendererEffectSupport::level(target, feature) {
                EffectSupportLevel::Native => {}
                EffectSupportLevel::Approximate => diagnostics.push(
                    Diagnostic::warning(
                        Phase::Export,
                        "LUMX0001",
                        format!(
                            "node {} uses {} which {:?} only approximates",
                            node.id,
                            feature.label(),
                            target
                        ),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    )
                    .with_hint(
                        "Review the rendered output for this node; the approximation is intentional and recorded in the renderer support matrix.",
                    ),
                ),
                EffectSupportLevel::Unsupported => diagnostics.push(
                    Diagnostic::warning(
                        Phase::Export,
                        "LUMX0002",
                        format!(
                            "node {} uses {} which {:?} cannot represent; the feature is dropped from this output",
                            node.id,
                            feature.label(),
                            target
                        ),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    )
                    .with_hint(
                        "Export through SVG/PNG for full effect fidelity, or remove the feature for this format.",
                    ),
                ),
            }
        }
    }
    diagnostics
}
