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
            RenderTarget::Svg | RenderTarget::Png { .. } => match feature {
                EffectFeature::StrokeAlignment => EffectSupportLevel::Approximate,
                _ => EffectSupportLevel::Native,
            },
            RenderTarget::KonvaScene => match feature {
                EffectFeature::StrokeAlignment
                | EffectFeature::DropShadowSpread
                | EffectFeature::LayeredShadows => EffectSupportLevel::Approximate,
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
                | EffectFeature::LayeredShadows => EffectSupportLevel::Unsupported,
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
    if !node.effects.is_empty() {
        features.push(EffectFeature::DropShadow);
    }
    if node.effects.iter().any(|effect| {
        let EffectKind::DropShadow { spread, .. } = &effect.kind;
        *spread != 0.0
    }) {
        features.push(EffectFeature::DropShadowSpread);
    }
    if node.effects.len() > 1 {
        features.push(EffectFeature::LayeredShadows);
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
