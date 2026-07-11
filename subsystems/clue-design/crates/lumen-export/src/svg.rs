use crate::resolver::{AssetByteResolver, ResolvedAssetBytes};
use crate::sidecar::{build_sidecar, node_output_id, page_output_id};
use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use lumen_core::scene::{ColorStop, PhysicalUnit};
use lumen_core::{
    is_canonical_page_size, node_render_size, page_geometry, paints_out_of_tree, pinned_paint_pass,
    render_box_for_node, Color, Diagnostic, DiagnosticSubject, Dimension, EffectKind,
    ExportAdapter, ExportArtifact, ExportError, ExportFormat, ExportRequest, ExportResult, Fill,
    ImageFitMode, ImageNode, Node, NodeId, NodeKind, Page, PageId, Paint, Phase, Rect, Scene,
    Stroke, StrokeAlign, StrokeCap, StrokeJoin, TextAlign, TextDirection, Unit,
};
use lumen_core::{valign_offset, HeuristicTextMeasurer, SharedTextMeasurer, TextMeasureInput, TextMeasurer};
use std::sync::Arc;

/// Heuristic fallback used when no measurer is injected, preserving
/// pre-injection behavior for portable consumers.
pub(crate) static FALLBACK_MEASURER: HeuristicTextMeasurer = HeuristicTextMeasurer;

#[derive(Clone, Debug, Default)]
pub struct SvgExportAdapter {
    resolver: Option<Arc<dyn AssetByteResolver>>,
    measurer: Option<SharedTextMeasurer>,
}

impl SvgExportAdapter {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_resolver(resolver: Arc<dyn AssetByteResolver>) -> Self {
        Self {
            resolver: Some(resolver),
            measurer: None,
        }
    }

    /// Inject a shaping text measurer (Wave 1 Track A). Text line breaks in
    /// the exported markup then come from the same measurement source the
    /// layout engine used.
    pub fn with_measurer(mut self, measurer: SharedTextMeasurer) -> Self {
        self.measurer = Some(measurer);
        self
    }
}

#[derive(Clone, Debug)]
pub struct PageResolution {
    pub page_ids: Vec<PageId>,
    pub diagnostics: Vec<Diagnostic>,
}

impl ExportAdapter for SvgExportAdapter {
    fn export(&self, scene: &Scene, request: &ExportRequest) -> Result<ExportResult, ExportError> {
        let resolved = resolve_page_ids(scene, &request.page_ids);
        if resolved
            .diagnostics
            .iter()
            .any(|diagnostic| matches!(diagnostic.severity, lumen_core::DiagnosticSeverity::Error))
        {
            return Err(ExportError::new(
                "export.invalid_pages",
                "export request references missing pages",
            )
            .with_diagnostics(resolved.diagnostics));
        }

        let mut diagnostics = resolved.diagnostics;
        // LUMS0102: this export shapes text with the heuristic fallback (no
        // measurer injected, or a non-shaping one), so line breaks in the SVG
        // markup are geometry-approximate. Emitted once per export; server
        // paths inject SkiaTextMeasurer and never reach this branch.
        if !self
            .measurer
            .as_deref()
            .is_some_and(|measurer| measurer.shaping())
        {
            diagnostics.push(lumen_core::heuristic_measurement_diagnostic());
        }
        let mut artifacts = Vec::new();

        for page_id in &resolved.page_ids {
            let page = scene.pages.get(page_id).ok_or_else(|| {
                ExportError::new(
                    "export.page_missing",
                    format!("page {} is missing after export page resolution", page_id),
                )
            })?;

            let (svg, page_diagnostics) = render_page_svg(
                scene,
                page,
                self.resolver.as_deref(),
                self.measurer.as_deref().map(measurer_as_dyn),
            );
            diagnostics.extend(page_diagnostics);

            let sidecar =
                build_sidecar(scene, std::slice::from_ref(page_id), &request.profile.name);
            let sidecar_json = serde_json::to_string_pretty(&sidecar).ok();

            artifacts.push(ExportArtifact {
                format: ExportFormat::Svg,
                page_id: Some(page_id.clone()),
                asset_id: None,
                mime_type: "image/svg+xml".to_owned(),
                bytes: svg.into_bytes(),
                sidecar_json,
            });
        }

        Ok(ExportResult {
            artifacts,
            diagnostics,
        })
    }
}

pub(crate) fn measurer_as_dyn(measurer: &(dyn TextMeasurer + Send + Sync)) -> &dyn TextMeasurer {
    measurer
}

pub(crate) fn render_page_svg(
    scene: &Scene,
    page: &Page,
    resolver: Option<&dyn AssetByteResolver>,
    measurer: Option<&dyn TextMeasurer>,
) -> (String, Vec<Diagnostic>) {
    let mut renderer = SvgPageRenderer::new(scene, page, resolver, measurer);
    let svg = renderer.render_page();
    (svg, renderer.diagnostics)
}

pub fn resolve_page_ids(scene: &Scene, requested: &[PageId]) -> PageResolution {
    if requested.is_empty() {
        return PageResolution {
            page_ids: scene.pages.keys().cloned().collect(),
            diagnostics: Vec::new(),
        };
    }

    let mut page_ids = Vec::new();
    let mut diagnostics = Vec::new();
    for page_id in requested {
        if scene.pages.contains_key(page_id) {
            page_ids.push(page_id.clone());
        } else {
            diagnostics.push(Diagnostic::error(
                Phase::Export,
                "LUME0101",
                format!("export request references missing page {}", page_id),
                Some(DiagnosticSubject::Page(page_id.clone())),
            ));
        }
    }

    PageResolution {
        page_ids,
        diagnostics,
    }
}

struct SvgPageRenderer<'a> {
    scene: &'a Scene,
    page: &'a Page,
    resolver: Option<&'a dyn AssetByteResolver>,
    measurer: &'a dyn TextMeasurer,
    defs: Vec<String>,
    body: String,
    diagnostics: Vec<Diagnostic>,
}

impl<'a> SvgPageRenderer<'a> {
    fn new(
        scene: &'a Scene,
        page: &'a Page,
        resolver: Option<&'a dyn AssetByteResolver>,
        measurer: Option<&'a dyn TextMeasurer>,
    ) -> Self {
        Self {
            scene,
            page,
            resolver,
            measurer: measurer.unwrap_or(&FALLBACK_MEASURER),
            defs: Vec::new(),
            body: String::new(),
            diagnostics: Vec::new(),
        }
    }

    fn render_page(&mut self) -> String {
        let dimensions = page_dimensions(self.page);

        self.body.push_str(&format!(
            "<g id=\"{}\" data-lumen-page-id=\"{}\">\n",
            escape_attr(&page_output_id(&self.page.id)),
            escape_attr(self.page.id.as_str())
        ));

        if self.page.background.len() > 1 {
            for fill in &self.page.background.clone() {
                self.warn_page_paint_tokens(&fill.paint);
                let attrs = self.fill_attrs(fill, None);
                self.body.push_str(&format!(
                    "<rect x=\"0\" y=\"0\" width=\"{}\" height=\"{}\"{} />\n",
                    fmt_num(dimensions.view_width),
                    fmt_num(dimensions.view_height),
                    attrs
                ));
            }
        } else if !self.page.background.is_empty() {
            let attrs = self.page_paint_attrs(&self.page.background);
            self.body.push_str(&format!(
                "<rect x=\"0\" y=\"0\" width=\"{}\" height=\"{}\"{} />\n",
                fmt_num(dimensions.view_width),
                fmt_num(dimensions.view_height),
                attrs
            ));
        }

        for child_id in &self.page.children {
            if self.skips_inline_render(child_id) {
                continue;
            }
            self.render_node(child_id, None);
        }

        // Phase 1d freehand: pinned nodes escape every ancestor mask (only
        // the page clips — the Moda model). Skipped inline above; emitted
        // here in document order, above the in-flow content, from page
        // space. Mirrors the Skia painter exactly.
        for node_id in pinned_paint_pass(self.scene, self.page) {
            self.render_node(&node_id, None);
        }

        self.body.push_str("</g>\n");

        let defs = if self.defs.is_empty() {
            String::new()
        } else {
            format!("<defs>\n{}</defs>\n", self.defs.join(""))
        };

        format!(
            "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{}{}\" height=\"{}{}\" viewBox=\"0 0 {} {}\" data-lumen-document-id=\"{}\" data-lumen-page-id=\"{}\">\n{}{}{}</svg>\n",
            fmt_num(dimensions.attr_width),
            dimensions.unit_suffix,
            fmt_num(dimensions.attr_height),
            dimensions.unit_suffix,
            fmt_num(dimensions.view_width),
            fmt_num(dimensions.view_height),
            escape_attr(&self.scene.meta.id.to_string()),
            escape_attr(self.page.id.as_str()),
            defs,
            self.body,
            ""
        )
    }

    /// Pinned nodes never render inside their parent's tree — see
    /// [`pinned_paint_pass`].
    fn skips_inline_render(&self, node_id: &NodeId) -> bool {
        self.scene
            .nodes
            .get(node_id)
            .is_some_and(paints_out_of_tree)
    }

    fn render_node(&mut self, node_id: &NodeId, parent_computed_origin: Option<(f64, f64)>) {
        let Some(node) = self.scene.nodes.get(node_id) else {
            self.diagnostics.push(Diagnostic::error(
                Phase::Export,
                "LUME0102",
                format!("page {} references missing node {}", self.page.id, node_id),
                Some(DiagnosticSubject::Page(self.page.id.clone())),
            ));
            return;
        };

        self.warn_if_unresolved_brand_tokens(node);
        let render_box = render_box_for_node(node, parent_computed_origin);
        let width = render_box.width;
        let height = render_box.height;
        let id_attrs = self.node_attrs(node);
        let transform = transform_attr(node, render_box.x, render_box.y);
        let opacity = if node.opacity < 1.0 {
            format!(" opacity=\"{}\"", fmt_num(node.opacity))
        } else {
            String::new()
        };
        let child_parent_origin = node
            .computed
            .as_ref()
            .map(|computed| (computed.layout_bounds.x, computed.layout_bounds.y));

        let filter = self.effect_filter_attr(node);
        let stacked = node.fills.len() > 1 || node.strokes.len() > 1;

        match &node.kind {
            NodeKind::Frame | NodeKind::AutoLayout(_) => {
                if matches!(node.kind, NodeKind::AutoLayout(_)) && node.computed.is_none() {
                    self.diagnostics.push(Diagnostic::warning(
                        Phase::Export,
                        "LUME0201",
                        format!("auto-layout node {} exported using fixed or zero size because computed geometry is missing", node.id),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    ).with_hint("Run the layout workstream before export when hug/fill or auto-layout sizing matters."));
                }

                let clip_id = if node.clip {
                    Some(self.clip_rect(node, width, height))
                } else {
                    None
                };
                self.body.push_str(&format!(
                    "<g{}{}{}{}>\n",
                    id_attrs, transform, opacity, filter
                ));
                let (shape, geometry) = rect_shape(node, width, height);
                if stacked {
                    for layer in self.paint_layer_attrs(&node.fills, &node.strokes, Some(&node.id))
                    {
                        self.body
                            .push_str(&format!("<{shape} {geometry}{layer} />\n"));
                    }
                } else if !node.fills.is_empty() || !node.strokes.is_empty() {
                    let fill_attrs = self.paint_attrs(&node.fills, &node.strokes, Some(&node.id));
                    self.body
                        .push_str(&format!("<{shape} {geometry}{fill_attrs} />\n"));
                }
                if let Some(clip_id) = clip_id {
                    self.body.push_str(&format!(
                        "<g clip-path=\"url(#{})\">\n",
                        escape_attr(&clip_id)
                    ));
                }
                for child_id in &node.children {
                    if self.skips_inline_render(child_id) {
                        continue;
                    }
                    self.render_node(child_id, child_parent_origin);
                }
                if node.clip {
                    self.body.push_str("</g>\n");
                }
                self.body.push_str("</g>\n");
            }
            NodeKind::Group => {
                self.body.push_str(&format!(
                    "<g{}{}{}{}>\n",
                    id_attrs, transform, opacity, filter
                ));
                for child_id in &node.children {
                    if self.skips_inline_render(child_id) {
                        continue;
                    }
                    self.render_node(child_id, child_parent_origin);
                }
                self.body.push_str("</g>\n");
            }
            NodeKind::Rect => {
                let (shape, geometry) = rect_shape(node, width, height);
                if stacked {
                    self.body.push_str(&format!(
                        "<g{}{}{}{}>\n",
                        id_attrs, transform, opacity, filter
                    ));
                    for layer in self.paint_layer_attrs(&node.fills, &node.strokes, Some(&node.id))
                    {
                        self.body
                            .push_str(&format!("<{shape} {geometry}{layer} />\n"));
                    }
                    self.body.push_str("</g>\n");
                } else {
                    let paint_attrs = self.paint_attrs(&node.fills, &node.strokes, Some(&node.id));
                    self.body.push_str(&format!(
                        "<{}{} {}{}{}{} />\n",
                        shape,
                        id_attrs,
                        geometry,
                        transform,
                        filter,
                        opacity_with_paint(opacity, paint_attrs)
                    ));
                }
            }
            NodeKind::Ellipse => {
                let geometry = format!(
                    "cx=\"{}\" cy=\"{}\" rx=\"{}\" ry=\"{}\"",
                    fmt_num(width / 2.0),
                    fmt_num(height / 2.0),
                    fmt_num(width / 2.0),
                    fmt_num(height / 2.0)
                );
                if stacked {
                    self.body.push_str(&format!(
                        "<g{}{}{}{}>\n",
                        id_attrs, transform, opacity, filter
                    ));
                    for layer in self.paint_layer_attrs(&node.fills, &node.strokes, Some(&node.id))
                    {
                        self.body
                            .push_str(&format!("<ellipse {geometry}{layer} />\n"));
                    }
                    self.body.push_str("</g>\n");
                } else {
                    let paint_attrs = self.paint_attrs(&node.fills, &node.strokes, Some(&node.id));
                    self.body.push_str(&format!(
                        "<ellipse{} {}{}{}{} />\n",
                        id_attrs,
                        geometry,
                        transform,
                        filter,
                        opacity_with_paint(opacity, paint_attrs)
                    ));
                }
            }
            NodeKind::Line(line) => {
                let geometry = format!(
                    "x1=\"0\" y1=\"0\" x2=\"{}\" y2=\"{}\"",
                    fmt_num(line.x2),
                    fmt_num(line.y2)
                );
                if node.strokes.len() > 1 {
                    self.body.push_str(&format!(
                        "<g{}{}{}{}>\n",
                        id_attrs, transform, opacity, filter
                    ));
                    for layer in self.paint_layer_attrs(&[], &node.strokes, Some(&node.id)) {
                        self.body.push_str(&format!("<line {geometry}{layer} />\n"));
                    }
                    self.body.push_str("</g>\n");
                } else {
                    let paint_attrs = self.paint_attrs(&[], &node.strokes, Some(&node.id));
                    self.body.push_str(&format!(
                        "<line{} {}{}{}{} />\n",
                        id_attrs,
                        geometry,
                        transform,
                        filter,
                        opacity_with_paint(opacity, paint_attrs)
                    ));
                }
            }
            NodeKind::Text(text) => {
                let paint_attrs = self.text_paint_attrs(node);
                // A6b D7: a spanned node emits one tspan PER RUN with an absolute
                // precomputed x, so `text-anchor` must NOT re-shift the runs —
                // anchor stays `start` and x is 0 on the <text> element. A
                // spanless node keeps the pre-A6b anchor + single per-line tspan.
                let spanned = !text.spans.is_empty();
                let anchor = if spanned {
                    "start"
                } else {
                    match text.align {
                        TextAlign::Left | TextAlign::Justify => "start",
                        TextAlign::Center => "middle",
                        TextAlign::Right => "end",
                    }
                };
                let x = if spanned {
                    0.0
                } else {
                    match text.align {
                        TextAlign::Left | TextAlign::Justify => 0.0,
                        TextAlign::Center => width / 2.0,
                        TextAlign::Right => width,
                    }
                };
                let direction = match text.direction {
                    TextDirection::Ltr => "ltr",
                    TextDirection::Rtl => "rtl",
                    TextDirection::Auto => "auto",
                };
                let measured =
                    self.measurer
                        .measure(&TextMeasureInput::from_text_node(text).with_bounds(&Rect {
                            x: 0.0,
                            y: 0.0,
                            width,
                            height,
                        }));
                // R1 (audit fold): surface measurement-time font diagnostics
                // (LUMS0100/0103/0104) on direct exports too, re-subjected to
                // this node and deduped against anything layout already folded.
                for diagnostic in &measured.diagnostics {
                    let diagnostic = Diagnostic {
                        subject: Some(DiagnosticSubject::Node(node.id.clone())),
                        ..diagnostic.clone()
                    };
                    if !self.diagnostics.contains(&diagnostic) {
                        self.diagnostics.push(diagnostic);
                    }
                }
                // A7a: shift every line's baseline down by the clamped vertical
                // slack (measured content height is THE total the raster path
                // lays out; `valign_offset` clamps overflow to 0). One formula
                // across all backends.
                let valign_shift = valign_offset(height, measured.height, text.valign);
                // A6a D2: underline/strike via the presentation attribute; the
                // measured line text already carries the D1 case transform.
                let decoration = match (text.underline, text.strikethrough) {
                    (true, true) => " text-decoration=\"underline line-through\"",
                    (true, false) => " text-decoration=\"underline\"",
                    (false, true) => " text-decoration=\"line-through\"",
                    (false, false) => "",
                };
                // A7b D6: block-level italic via the presentation attribute.
                // Absent when upright so pre-A7b markup is byte-identical.
                // D2 gate (adversarial-gate finding): emitted only when a REAL
                // italic face exists — otherwise the raster deliberately renders
                // upright (LUMS0105) and an italic attr here would make every
                // SVG viewer synthesize the fake oblique the raster refused.
                let italic_renderable =
                    text.italic && self.measurer.has_italic_face(&text.font_family);
                let italic = if italic_renderable {
                    " font-style=\"italic\""
                } else {
                    ""
                };
                // A6b D7: per-run tspans (absolute x within the line) when spans
                // exist; otherwise the pre-A6b single-tspan-per-line markup.
                let tspans = if spanned {
                    measured
                        .lines
                        .iter()
                        .map(|line| {
                            // Runs carry x relative to the line's left edge; the
                            // line's left edge depends on alignment (the whole
                            // line is anchored, runs are absolutely placed in it).
                            let line_left = match text.align {
                                TextAlign::Left | TextAlign::Justify => 0.0,
                                TextAlign::Center => (width - line.width) / 2.0,
                                TextAlign::Right => width - line.width,
                            };
                            line.runs
                                .iter()
                                .map(|run| {
                                    let run_attrs = self.text_run_attrs(node, text, run);
                                    format!(
                                        "<tspan x=\"{}\" y=\"{}\"{}>{}</tspan>",
                                        fmt_num(line_left + run.x),
                                        fmt_num(line.baseline + valign_shift),
                                        run_attrs,
                                        escape_text(&run.text)
                                    )
                                })
                                .collect::<String>()
                        })
                        .collect::<String>()
                } else {
                    measured
                        .lines
                        .iter()
                        .map(|line| {
                            format!(
                                "<tspan x=\"{}\" y=\"{}\">{}</tspan>",
                                fmt_num(x),
                                fmt_num(line.baseline + valign_shift),
                                escape_text(&line.text)
                            )
                        })
                        .collect::<String>()
                };
                if node.fills.len() > 1 {
                    self.diagnostics.push(
                        Diagnostic::advice(
                            Phase::Export,
                            "LUME0211",
                            format!(
                                "text node {} has multiple fills; SVG export renders the first fill only for text",
                                node.id
                            ),
                            Some(DiagnosticSubject::Node(node.id.clone())),
                        )
                        .with_hint("Stacked text fills are out of V0 scope; use a single text fill."),
                    );
                }
                self.body.push_str(&format!(
                    "<text{} x=\"{}\" y=\"{}\" font-family=\"{}\" font-size=\"{}\" font-weight=\"{}\" text-anchor=\"{}\" letter-spacing=\"{}\" direction=\"{}\"{}{}{}{}{}>{}</text>\n",
                    id_attrs,
                    fmt_num(x),
                    fmt_num(text.font_size),
                    escape_attr(&svg_font_family(&text.font_family)),
                    fmt_num(text.font_size),
                    text.font_weight,
                    anchor,
                    fmt_num(text.letter_spacing),
                    direction,
                    decoration,
                    italic,
                    transform,
                    filter,
                    opacity_with_paint(opacity, paint_attrs),
                    tspans
                ));
            }
            NodeKind::Vector(vector) => {
                let geometry = format!("d=\"{}\"", escape_attr(&vector.path_data));
                // A library icon carries a source viewBox: the node transform positions the
                // box, and an inner group scales the path uniformly (centered) into it — so
                // the icon renders at the node's size, not its intrinsic 24px. Hand-authored
                // vectors (view_box None) draw at raw node-local coordinates, unchanged.
                let fit = icon_fit_transform(vector.view_box, width, height);
                if stacked || fit.is_some() {
                    self.body.push_str(&format!(
                        "<g{}{}{}{}>\n",
                        id_attrs, transform, opacity, filter
                    ));
                    if let Some(fit) = &fit {
                        self.body.push_str(&format!("<g transform=\"{fit}\">\n"));
                    }
                    for layer in self.paint_layer_attrs(&node.fills, &node.strokes, Some(&node.id))
                    {
                        self.body.push_str(&format!("<path {geometry}{layer} />\n"));
                    }
                    if fit.is_some() {
                        self.body.push_str("</g>\n");
                    }
                    self.body.push_str("</g>\n");
                } else {
                    let paint_attrs = self.paint_attrs(&node.fills, &node.strokes, Some(&node.id));
                    self.body.push_str(&format!(
                        "<path{} {}{}{}{} />\n",
                        id_attrs,
                        geometry,
                        transform,
                        filter,
                        opacity_with_paint(opacity, paint_attrs)
                    ));
                }
            }
            NodeKind::Image(image) => {
                self.render_image_node(node, image, width, height, &id_attrs, &transform, &opacity);
            }
            NodeKind::Instance { source_node_id } => {
                self.diagnostics.push(Diagnostic::warning(
                    Phase::Export,
                    "LUME0203",
                    format!("instance node {} references source {} but instance expansion is not implemented", node.id, source_node_id),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                ).with_hint("Expand instances in core or provide an instance resolver before export."));
                self.body.push_str(&format!(
                    "<g{}{}{} data-lumen-unsupported=\"instance\" data-lumen-source-node-id=\"{}\" />\n",
                    id_attrs,
                    transform,
                    opacity,
                    escape_attr(source_node_id.as_str())
                ));
            }
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn render_image_node(
        &mut self,
        node: &Node,
        image: &ImageNode,
        width: f64,
        height: f64,
        id_attrs: &str,
        transform: &str,
        opacity: &str,
    ) {
        if let Some(resolved) = self.resolve_image_bytes(node, image) {
            let href = format!(
                "data:{};base64,{}",
                resolved.mime_type,
                BASE64.encode(&resolved.bytes)
            );
            let alt_attr = image
                .alt
                .as_ref()
                .map(|alt| format!(" data-lumen-alt=\"{}\"", escape_attr(alt)))
                .unwrap_or_default();

            // Focal-point crops compute an explicit window from the asset's
            // natural aspect ratio; plain fits map onto preserveAspectRatio.
            let record = self.scene.assets.get(&image.asset_id);
            if let Some(crop) = focal_crop_geometry(node, record, width, height) {
                let clip_id = format!("lumen-image-clip-{}", escape_attr(node.id.as_str()));
                self.defs.push(format!(
                    "<clipPath id=\"{}\">{}</clipPath>\n",
                    clip_id,
                    clip_shape_element(node, width, height)
                ));
                self.body.push_str(&format!(
                    "<g{} clip-path=\"url(#{})\" data-lumen-asset-id=\"{}\" data-lumen-image-fit=\"focal-crop\"{}{}{}>\n<image x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\" preserveAspectRatio=\"none\" href=\"{}\" />\n</g>\n",
                    id_attrs,
                    escape_attr(&clip_id),
                    escape_attr(image.asset_id.as_str()),
                    alt_attr,
                    transform,
                    opacity,
                    fmt_num(crop.x),
                    fmt_num(crop.y),
                    fmt_num(crop.width),
                    fmt_num(crop.height),
                    escape_attr(&href)
                ));
                return;
            }

            self.body.push_str(&format!(
                "<image{} x=\"0\" y=\"0\" width=\"{}\" height=\"{}\" preserveAspectRatio=\"{}\" data-lumen-asset-id=\"{}\"{}{}{} href=\"{}\" />\n",
                id_attrs,
                fmt_num(width),
                fmt_num(height),
                image_preserve_aspect_ratio(node),
                escape_attr(image.asset_id.as_str()),
                alt_attr,
                transform,
                opacity,
                escape_attr(&href)
            ));
            return;
        }

        self.body.push_str(&format!(
            "<g{}{}{} data-lumen-unsupported=\"image\" data-lumen-asset-id=\"{}\" />\n",
            id_attrs,
            transform,
            opacity,
            escape_attr(image.asset_id.as_str())
        ));
    }

    /// Resolve the bytes behind an image node, emitting diagnostics instead
    /// of failing the export when the resolver is missing, the asset record
    /// is missing, or resolution errors.
    fn resolve_image_bytes(
        &mut self,
        node: &Node,
        image: &ImageNode,
    ) -> Option<ResolvedAssetBytes> {
        let Some(resolver) = self.resolver else {
            self.diagnostics.push(Diagnostic::warning(
                Phase::Export,
                "LUME0202",
                format!(
                    "image node {} references asset {} but no asset resolver is configured",
                    node.id, image.asset_id
                ),
                Some(DiagnosticSubject::Node(node.id.clone())),
            ).with_hint("Configure an asset byte resolver on the export adapter before treating image export as complete."));
            return None;
        };

        let Some(record) = self.scene.assets.get(&image.asset_id) else {
            self.diagnostics.push(
                Diagnostic::warning(
                    Phase::Export,
                    "LUME0211",
                    format!(
                        "image node {} references asset {} but the scene carries no asset record to resolve bytes from",
                        node.id, image.asset_id
                    ),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                )
                .with_hint("Upsert the asset record into the scene before export."),
            );
            return None;
        };

        match resolver.resolve(record) {
            Ok(resolved) => Some(resolved),
            Err(error) => {
                self.diagnostics.push(
                    Diagnostic::warning(
                        Phase::Export,
                        "LUME0210",
                        format!(
                            "image node {} could not resolve bytes for asset {}: {}",
                            node.id, image.asset_id, error
                        ),
                        Some(DiagnosticSubject::Asset(image.asset_id.clone())),
                    )
                    .with_hint("Verify the asset bytes exist in the configured asset store."),
                );
                None
            }
        }
    }

    fn node_attrs(&self, node: &Node) -> String {
        let mut attrs = format!(
            " id=\"{}\" data-lumen-node-id=\"{}\"",
            escape_attr(&node_output_id(&node.id)),
            escape_attr(node.id.as_str())
        );
        if let Some(name) = &node.name {
            attrs.push_str(&format!(" data-lumen-node-name=\"{}\"", escape_attr(name)));
        }

        let slot_keys = self
            .scene
            .slots
            .values()
            .filter(|slot| slot.bound_nodes.contains(&node.id))
            .map(|slot| slot.key.as_str().to_owned())
            .collect::<Vec<_>>();
        if !slot_keys.is_empty() {
            attrs.push_str(&format!(
                " data-lumen-slot-keys=\"{}\"",
                escape_attr(&slot_keys.join(" "))
            ));
        }

        attrs
    }

    fn page_paint_attrs(&mut self, fills: &[Fill]) -> String {
        for fill in fills {
            self.warn_page_paint_tokens(&fill.paint);
        }

        self.paint_attrs(fills, &[], None)
    }

    fn text_paint_attrs(&mut self, node: &Node) -> String {
        // A6a D5: the first solid text stroke renders behind the fill via
        // `paint-order="stroke fill"`. First-stroke-only + solid-only; extras,
        // gradient stroke paint, and dashes advise (LUME0215) and are dropped.
        let stroke_attrs = self.text_stroke_attrs(node);

        let fill_attrs = if !node.fills.is_empty() {
            self.paint_attrs(&node.fills, &[], Some(&node.id))
        } else {
            self.diagnostics.push(
                Diagnostic::warning(
                    Phase::Export,
                    "LUME0207",
                    format!(
                        "text node {} has no fill; SVG export used the default visible text fill",
                        node.id
                    ),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                )
                .with_hint(
                    "Set an explicit text fill before final export if this fallback is not intended.",
                ),
            );
            " fill=\"#000000\" data-lumen-default-fill=\"text\"".to_owned()
        };

        format!("{fill_attrs}{stroke_attrs}")
    }

    /// A6b D7: per-run SVG attrs — `fill`/`font-weight`/`text-decoration` only
    /// when they differ from the node (base runs inherit the `<text>` attrs).
    /// Decoration is the union node∪span. A base run (`span == None`) inherits
    /// everything, so it emits no attrs.
    fn text_run_attrs(
        &mut self,
        node: &Node,
        text: &lumen_core::TextNode,
        run: &lumen_core::TextRunBox,
    ) -> String {
        let Some(span) = run.span.and_then(|index| text.spans.get(index)) else {
            return String::new();
        };
        let mut attrs = String::new();
        if let Some(paint) = &span.fill {
            // Span fills are Solid/Token only (gradients rejected at validation);
            // resolve like a node fill. An unresolved token diagnoses + renders
            // "none" through paint_ref, same as the node path.
            let color = self.paint_ref(paint, &format!("{}-span-fill", node.id), Some(&node.id));
            attrs.push_str(&format!(" fill=\"{color}\""));
        }
        if let Some(weight) = span.font_weight {
            if weight != text.font_weight {
                attrs.push_str(&format!(" font-weight=\"{weight}\""));
            }
        }
        let run_underline = text.underline || span.underline.unwrap_or(false);
        let run_strike = text.strikethrough || span.strikethrough.unwrap_or(false);
        if (run_underline, run_strike) != (text.underline, text.strikethrough) {
            let decoration = match (run_underline, run_strike) {
                (true, true) => "underline line-through",
                (true, false) => "underline",
                (false, true) => "line-through",
                (false, false) => "none",
            };
            attrs.push_str(&format!(" text-decoration=\"{decoration}\""));
        }
        // A7b D6: per-run italic is an OVERRIDE (`span.italic.unwrap_or(block)`),
        // unlike the union-merged decorations above. Emit `font-style` only when
        // the run's resolved italic differs from the block — BOTH directions: an
        // italic run in an upright block (`italic`) AND an upright run in an
        // italic block via `italic(false)` (`normal`). D2 gate: with no real
        // italic face EVERY run renders upright (the raster's synthesis gate),
        // so both effective values collapse to upright and no attr is emitted.
        let has_face = self.measurer.has_italic_face(&text.font_family);
        let run_italic = span.italic.unwrap_or(text.italic) && has_face;
        if run_italic != (text.italic && has_face) {
            let style = if run_italic { "italic" } else { "normal" };
            attrs.push_str(&format!(" font-style=\"{style}\""));
        }
        attrs
    }

    /// The SVG stroke attributes for the first solid text stroke, plus
    /// `paint-order="stroke fill"`; empty when the node has no stroke. Advises
    /// LUME0215 for the un-rendered extras (additional strokes, gradient stroke
    /// paint, dashes).
    fn text_stroke_attrs(&mut self, node: &Node) -> String {
        let Some(stroke) = node.strokes.first() else {
            return String::new();
        };
        let gradient_or_dash = matches!(
            stroke.paint,
            Paint::LinearGradient { .. } | Paint::RadialGradient { .. }
        ) || stroke.dash.as_ref().is_some_and(|dash| !dash.is_empty());
        if node.strokes.len() > 1 || gradient_or_dash {
            self.diagnostics.push(
                Diagnostic::advice(
                    Phase::Export,
                    "LUME0215",
                    format!(
                        "text node {} renders the first solid stroke only; extra strokes, gradient stroke paint, and dashes on text strokes are ignored",
                        node.id
                    ),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                )
                .with_hint("Use a single solid text stroke; gradient/dash/multi-stroke text outlines are out of Typography v1 scope."),
            );
        }
        // Solid stroke color: the solid value, or the first stop of a gradient.
        let resolved = match &stroke.paint {
            Paint::Solid { color } => self.color_ref(color, Some(&node.id)),
            Paint::LinearGradient { stops, .. } | Paint::RadialGradient { stops } => stops
                .first()
                .map(|stop| self.color_ref(&stop.color, Some(&node.id)))
                .unwrap_or_else(|| "none".to_owned()),
            Paint::Token { token } => {
                self.diagnostics
                    .push(unresolved_token_diag(&node.id, token));
                "none".to_owned()
            }
        };
        let (color, opacity) = split_hex_stop_alpha(&resolved);
        let mut attrs = format!(
            " stroke=\"{}\" stroke-width=\"{}\" paint-order=\"stroke fill\"",
            color,
            fmt_num(stroke.width)
        );
        if let Some(opacity) = opacity {
            attrs.push_str(&format!(" stroke-opacity=\"{}\"", fmt_num(opacity)));
        }
        attrs
    }

    /// Combined attrs for the single-layer fast path (at most one fill and
    /// one stroke). Stacked paints go through `paint_layer_attrs`.
    fn paint_attrs(
        &mut self,
        fills: &[Fill],
        strokes: &[Stroke],
        node_id: Option<&NodeId>,
    ) -> String {
        let mut attrs = String::new();
        if let Some(fill) = fills.first() {
            attrs.push_str(&self.fill_attrs(fill, node_id));
        } else {
            attrs.push_str(" fill=\"none\"");
        }

        if let Some(stroke) = strokes.first() {
            attrs.push_str(&self.stroke_attrs(stroke, node_id));
        }

        attrs
    }

    /// One attrs string per geometry copy, painting the full stacks in
    /// order: fills bottom-to-top, then strokes on top.
    fn paint_layer_attrs(
        &mut self,
        fills: &[Fill],
        strokes: &[Stroke],
        node_id: Option<&NodeId>,
    ) -> Vec<String> {
        let mut layers = Vec::new();
        for fill in fills {
            layers.push(self.fill_attrs(fill, node_id));
        }
        for stroke in strokes {
            layers.push(format!(
                " fill=\"none\"{}",
                self.stroke_attrs(stroke, node_id)
            ));
        }
        layers
    }

    fn fill_attrs(&mut self, fill: &Fill, node_id: Option<&NodeId>) -> String {
        format!(
            " fill=\"{}\" data-lumen-fill-id=\"{}\"",
            self.paint_ref(&fill.paint, &fill.id.to_string(), node_id),
            escape_attr(fill.id.as_str())
        )
    }

    fn stroke_attrs(&mut self, stroke: &Stroke, node_id: Option<&NodeId>) -> String {
        let mut attrs = format!(
            " stroke=\"{}\" stroke-width=\"{}\"",
            self.paint_ref(&stroke.paint, &stroke.id.to_string(), node_id),
            fmt_num(stroke.width)
        );
        if let Some(dash) = &stroke.dash {
            if !dash.is_empty() {
                attrs.push_str(&format!(
                    " stroke-dasharray=\"{}\"",
                    dash.iter()
                        .map(|value| fmt_num(*value))
                        .collect::<Vec<_>>()
                        .join(" ")
                ));
            }
        }
        match stroke.cap {
            StrokeCap::Butt => {}
            StrokeCap::Round => attrs.push_str(" stroke-linecap=\"round\""),
            StrokeCap::Square => attrs.push_str(" stroke-linecap=\"square\""),
        }
        match stroke.join {
            StrokeJoin::Miter => {}
            StrokeJoin::Round => attrs.push_str(" stroke-linejoin=\"round\""),
            StrokeJoin::Bevel => attrs.push_str(" stroke-linejoin=\"bevel\""),
        }
        if stroke.align != StrokeAlign::Center {
            if let Some(node_id) = node_id {
                self.diagnostics.push(
                    Diagnostic::advice(
                        Phase::Export,
                        "LUME0210",
                        format!(
                            "node {} stroke {} requests {:?} alignment; SVG has no native stroke alignment so it renders centered",
                            node_id, stroke.id, stroke.align
                        ),
                        Some(DiagnosticSubject::Node(node_id.clone())),
                    )
                    .with_hint("Path-offset approximation is out of V0 scope; adjust geometry if exact alignment matters."),
                );
            }
        }
        attrs.push_str(&format!(
            " data-lumen-stroke-id=\"{}\"",
            escape_attr(stroke.id.as_str())
        ));
        attrs
    }

    /// Register a deterministic `<filter>` for the node's effect stack and
    /// return the `filter` attribute. A pure drop-shadow stack keeps the exact
    /// pre-A4 markup (feDropShadow / feMorphology fast paths). A stack that
    /// mixes in glow, layer blur, or inner shadow uses the A4 general pipeline,
    /// which honors the D1 stacking contract (source → layer blurs →
    /// shadows/glows beneath the blurred result → inner shadows over it).
    fn effect_filter_attr(&mut self, node: &Node) -> String {
        if node.effects.is_empty() {
            return String::new();
        }

        let has_new = node.effects.iter().any(|effect| {
            matches!(
                effect.kind,
                EffectKind::Glow { .. }
                    | EffectKind::LayerBlur { .. }
                    | EffectKind::InnerShadow { .. }
            )
        });

        let body = if has_new {
            self.general_effect_body(node)
        } else {
            self.drop_shadow_body(node)
        };
        let Some(body) = body else {
            return String::new();
        };

        let filter_id = format!("lumen-effect-{}", escape_attr(node.id.as_str()));
        self.defs.push(format!(
            "<filter id=\"{filter_id}\" x=\"-50%\" y=\"-50%\" width=\"200%\" height=\"200%\">\n{body}</filter>\n"
        ));
        format!(" filter=\"url(#{filter_id})\"")
    }

    /// The pre-A4 drop-shadow-only filter body (byte-identical markup).
    fn drop_shadow_body(&mut self, node: &Node) -> Option<String> {
        let mut shadows = Vec::new();
        for effect in &node.effects {
            if let EffectKind::DropShadow {
                color,
                opacity,
                x,
                y,
                blur,
                spread,
                ..
            } = &effect.kind
            {
                if let Color::Token { token } = color {
                    self.diagnostics.push(unresolved_token_diag(&node.id, token));
                    continue;
                }
                shadows.push(ResolvedEffect {
                    color: self.color_ref(color, Some(&node.id)),
                    opacity: *opacity,
                    x: *x,
                    y: *y,
                    blur: *blur,
                    spread: *spread,
                });
            }
        }
        if shadows.is_empty() {
            return None;
        }

        let mut body = String::new();
        if shadows.iter().all(|shadow| shadow.spread == 0.0) {
            for shadow in &shadows {
                body.push_str(&format!(
                    "<feDropShadow dx=\"{}\" dy=\"{}\" stdDeviation=\"{}\" flood-color=\"{}\" flood-opacity=\"{}\" />\n",
                    fmt_num(shadow.x),
                    fmt_num(shadow.y),
                    fmt_num(shadow.blur / 2.0),
                    shadow.color,
                    fmt_num(shadow.opacity)
                ));
            }
        } else {
            for (index, shadow) in shadows.iter().enumerate() {
                let blur_input = if shadow.spread != 0.0 {
                    body.push_str(&format!(
                        "<feMorphology in=\"SourceAlpha\" operator=\"{}\" radius=\"{}\" result=\"lumen-spread-{index}\" />\n",
                        if shadow.spread > 0.0 { "dilate" } else { "erode" },
                        fmt_num(shadow.spread.abs())
                    ));
                    format!("lumen-spread-{index}")
                } else {
                    "SourceAlpha".to_owned()
                };
                body.push_str(&format!(
                    "<feGaussianBlur in=\"{blur_input}\" stdDeviation=\"{}\" result=\"lumen-blur-{index}\" />\n",
                    fmt_num(shadow.blur / 2.0)
                ));
                body.push_str(&format!(
                    "<feOffset in=\"lumen-blur-{index}\" dx=\"{}\" dy=\"{}\" result=\"lumen-offset-{index}\" />\n",
                    fmt_num(shadow.x),
                    fmt_num(shadow.y)
                ));
                body.push_str(&format!(
                    "<feFlood flood-color=\"{}\" flood-opacity=\"{}\" result=\"lumen-flood-{index}\" />\n",
                    shadow.color,
                    fmt_num(shadow.opacity)
                ));
                body.push_str(&format!(
                    "<feComposite in=\"lumen-flood-{index}\" in2=\"lumen-offset-{index}\" operator=\"in\" result=\"lumen-shadow-{index}\" />\n"
                ));
            }
            body.push_str("<feMerge>\n");
            for index in (0..shadows.len()).rev() {
                body.push_str(&format!("<feMergeNode in=\"lumen-shadow-{index}\" />\n"));
            }
            body.push_str("<feMergeNode in=\"SourceGraphic\" />\n</feMerge>\n");
        }
        Some(body)
    }

    /// The A4 general pipeline body honoring the D1 stacking contract. Result
    /// names are stable and deterministic. See the module-level parity test.
    fn general_effect_body(&mut self, node: &Node) -> Option<String> {
        let mut layer_blurs: Vec<f64> = Vec::new();
        let mut outers: Vec<ResolvedEffect> = Vec::new();
        let mut inners: Vec<ResolvedEffect> = Vec::new();
        for effect in &node.effects {
            match &effect.kind {
                EffectKind::LayerBlur { radius } => layer_blurs.push(*radius),
                EffectKind::DropShadow {
                    color,
                    opacity,
                    x,
                    y,
                    blur,
                    spread,
                    ..
                } => {
                    if let Some(e) = self.resolve_effect(node, color, *opacity, *x, *y, *blur, *spread)
                    {
                        outers.push(e);
                    }
                }
                EffectKind::Glow {
                    color,
                    opacity,
                    blur,
                    spread,
                    ..
                } => {
                    if let Some(e) =
                        self.resolve_effect(node, color, *opacity, 0.0, 0.0, *blur, *spread)
                    {
                        outers.push(e);
                    }
                }
                EffectKind::InnerShadow {
                    color,
                    opacity,
                    x,
                    y,
                    blur,
                    spread,
                    ..
                } => {
                    if let Some(e) = self.resolve_effect(node, color, *opacity, *x, *y, *blur, *spread)
                    {
                        inners.push(e);
                    }
                }
            }
        }

        let mut body = String::new();

        // 1. Blurred base graphic (and its alpha, for shadow/glow/inner geometry).
        let mut base = "SourceGraphic".to_owned();
        let mut base_alpha = "SourceAlpha".to_owned();
        // The blurred-alpha chain feeds shadow/glow/inner geometry only; on a
        // blur-only stack it must not be emitted — the filter's output is the
        // LAST primitive's result, and a trailing alpha blur would replace the
        // node with its black silhouette.
        let needs_alpha = !outers.is_empty() || !inners.is_empty();
        for (i, radius) in layer_blurs.iter().enumerate() {
            let sigma = fmt_num(radius / 2.0);
            if needs_alpha {
                let next_alpha = format!("lumen-lba-{i}");
                body.push_str(&format!(
                    "<feGaussianBlur in=\"{base_alpha}\" stdDeviation=\"{sigma}\" result=\"{next_alpha}\" />\n"
                ));
                base_alpha = next_alpha;
            }
            let next = format!("lumen-lb-{i}");
            body.push_str(&format!(
                "<feGaussianBlur in=\"{base}\" stdDeviation=\"{sigma}\" result=\"{next}\" />\n"
            ));
            base = next;
        }

        // 2. Outer shadows/glows computed from the blurred alpha, beneath base.
        let mut outer_results = Vec::new();
        for (i, o) in outers.iter().enumerate() {
            let spread_input = if o.spread != 0.0 {
                let r = format!("lumen-ospread-{i}");
                body.push_str(&format!(
                    "<feMorphology in=\"{base_alpha}\" operator=\"{}\" radius=\"{}\" result=\"{r}\" />\n",
                    if o.spread > 0.0 { "dilate" } else { "erode" },
                    fmt_num(o.spread.abs())
                ));
                r
            } else {
                base_alpha.clone()
            };
            body.push_str(&format!(
                "<feGaussianBlur in=\"{spread_input}\" stdDeviation=\"{}\" result=\"lumen-oblur-{i}\" />\n",
                fmt_num(o.blur / 2.0)
            ));
            body.push_str(&format!(
                "<feOffset in=\"lumen-oblur-{i}\" dx=\"{}\" dy=\"{}\" result=\"lumen-ooff-{i}\" />\n",
                fmt_num(o.x),
                fmt_num(o.y)
            ));
            body.push_str(&format!(
                "<feFlood flood-color=\"{}\" flood-opacity=\"{}\" result=\"lumen-oflood-{i}\" />\n",
                o.color,
                fmt_num(o.opacity)
            ));
            body.push_str(&format!(
                "<feComposite in=\"lumen-oflood-{i}\" in2=\"lumen-ooff-{i}\" operator=\"in\" result=\"lumen-outer-{i}\" />\n"
            ));
            outer_results.push(format!("lumen-outer-{i}"));
        }

        // 3. Inner shadows computed from the blurred alpha, over base, clipped
        //    to base alpha. Spread erodes the shape inward first.
        let mut inner_results = Vec::new();
        for (i, s) in inners.iter().enumerate() {
            let shape = if s.spread > 0.0 {
                let r = format!("lumen-ispread-{i}");
                body.push_str(&format!(
                    "<feMorphology in=\"{base_alpha}\" operator=\"erode\" radius=\"{}\" result=\"{r}\" />\n",
                    fmt_num(s.spread)
                ));
                r
            } else {
                base_alpha.clone()
            };
            body.push_str(&format!(
                "<feOffset in=\"{shape}\" dx=\"{}\" dy=\"{}\" result=\"lumen-ioff-{i}\" />\n",
                fmt_num(s.x),
                fmt_num(s.y)
            ));
            body.push_str(&format!(
                "<feGaussianBlur in=\"lumen-ioff-{i}\" stdDeviation=\"{}\" result=\"lumen-iblur-{i}\" />\n",
                fmt_num(s.blur / 2.0)
            ));
            // Inside the shape but outside the offset/blurred alpha = the inner
            // shadow ring; clip keeps it within the (blurred) base alpha.
            body.push_str(&format!(
                "<feComposite in=\"{base_alpha}\" in2=\"lumen-iblur-{i}\" operator=\"out\" result=\"lumen-iring-{i}\" />\n"
            ));
            body.push_str(&format!(
                "<feFlood flood-color=\"{}\" flood-opacity=\"{}\" result=\"lumen-iflood-{i}\" />\n",
                s.color,
                fmt_num(s.opacity)
            ));
            body.push_str(&format!(
                "<feComposite in=\"lumen-iflood-{i}\" in2=\"lumen-iring-{i}\" operator=\"in\" result=\"lumen-inner-{i}\" />\n"
            ));
            inner_results.push(format!("lumen-inner-{i}"));
        }

        // 4. Merge bottom-up: outers (first = topmost outer) beneath the
        //    blurred base, inner shadows (first = topmost) over it.
        if outer_results.is_empty() && inner_results.is_empty() {
            // Nothing survived (e.g. every effect was a token-colored shadow
            // that got skipped) and there was no layer blur: no filter at all.
            if body.is_empty() {
                return None;
            }
            // Layer-blur only: the last blur result is already the output.
            return Some(body);
        }
        body.push_str("<feMerge>\n");
        for result in outer_results.iter().rev() {
            body.push_str(&format!("<feMergeNode in=\"{result}\" />\n"));
        }
        body.push_str(&format!("<feMergeNode in=\"{base}\" />\n"));
        for result in inner_results.iter().rev() {
            body.push_str(&format!("<feMergeNode in=\"{result}\" />\n"));
        }
        body.push_str("</feMerge>\n");
        Some(body)
    }

    /// Resolve one shadow/glow/inner effect's paint; token colors emit the
    /// unresolved-token diagnostic and are skipped (as the pre-A4 path did).
    fn resolve_effect(
        &mut self,
        node: &Node,
        color: &Color,
        opacity: f64,
        x: f64,
        y: f64,
        blur: f64,
        spread: f64,
    ) -> Option<ResolvedEffect> {
        if let Color::Token { token } = color {
            self.diagnostics.push(unresolved_token_diag(&node.id, token));
            return None;
        }
        Some(ResolvedEffect {
            color: self.color_ref(color, Some(&node.id)),
            opacity,
            x,
            y,
            blur,
            spread,
        })
    }

    fn paint_ref(&mut self, paint: &Paint, paint_id: &str, node_id: Option<&NodeId>) -> String {
        match paint {
            Paint::Solid { color } => self.color_ref(color, node_id),
            Paint::LinearGradient { angle, stops } => {
                let id = format!("lumen-gradient-{}", escape_attr(paint_id));
                let rendered_stops = gradient_stops(stops, |color| self.color_ref(color, node_id));
                self.defs.push(format!(
                    "<linearGradient id=\"{}\" gradientTransform=\"rotate({})\">\n{}</linearGradient>\n",
                    id,
                    fmt_num(*angle),
                    rendered_stops
                ));
                format!("url(#{})", id)
            }
            Paint::RadialGradient { stops } => {
                let id = format!("lumen-gradient-{}", escape_attr(paint_id));
                let rendered_stops = gradient_stops(stops, |color| self.color_ref(color, node_id));
                self.defs.push(format!(
                    "<radialGradient id=\"{}\">\n{}</radialGradient>\n",
                    id, rendered_stops
                ));
                format!("url(#{})", id)
            }
            Paint::Token { token } => {
                if let Some(node_id) = node_id {
                    self.diagnostics.push(unresolved_token_diag(node_id, token));
                }
                "none".to_owned()
            }
        }
    }

    fn warn_page_paint_tokens(&mut self, paint: &Paint) {
        match paint {
            Paint::Token { token } => self
                .diagnostics
                .push(unresolved_page_token_diag(&self.page.id, token)),
            Paint::Solid {
                color: Color::Token { token },
            } => self
                .diagnostics
                .push(unresolved_page_token_diag(&self.page.id, token)),
            Paint::LinearGradient { stops, .. } | Paint::RadialGradient { stops } => {
                for stop in stops {
                    if let Color::Token { token } = &stop.color {
                        self.diagnostics
                            .push(unresolved_page_token_diag(&self.page.id, token));
                    }
                }
            }
            Paint::Solid { .. } => {}
        }
    }

    fn color_ref(&mut self, color: &Color, node_id: Option<&NodeId>) -> String {
        match color {
            Color::Hex { value } => normalize_hex(value),
            Color::Oklch { l, c, h, alpha } => {
                format!(
                    "oklch({}% {} {} / {})",
                    fmt_num(*l * 100.0),
                    fmt_num(*c),
                    fmt_num(*h),
                    fmt_num(*alpha)
                )
            }
            Color::Token { token } => {
                if let Some(node_id) = node_id {
                    self.diagnostics.push(unresolved_token_diag(node_id, token));
                }
                "none".to_owned()
            }
        }
    }

    fn warn_if_unresolved_brand_tokens(&mut self, node: &Node) {
        self.diagnostics
            .extend(unresolved_brand_token_diagnostics(node));
    }

    fn clip_rect(&mut self, node: &Node, width: f64, height: f64) -> String {
        let clip_id = format!("lumen-clip-{}", escape_attr(node.id.as_str()));
        self.defs.push(format!(
            "<clipPath id=\"{}\">{}</clipPath>\n",
            clip_id,
            clip_shape_element(node, width, height)
        ));
        clip_id
    }
}

/// A resolved shadow/glow/inner-shadow ready for filter emission (paint
/// already resolved to an SVG color string).
struct ResolvedEffect {
    color: String,
    opacity: f64,
    x: f64,
    y: f64,
    blur: f64,
    spread: f64,
}

/// Explicit crop window for cover/crop placements with a focal point.
/// The drawn image covers the node box at the asset's natural aspect
/// ratio, shifted so the focal point sits as close to the box center as
/// the image allows. Shared with the native rasterizer (lumen-skia) so
/// SVG and PNG focal crops can never drift apart.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct FocalCropGeometry {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

pub fn focal_crop_geometry(
    node: &Node,
    record: Option<&lumen_core::AssetRecord>,
    box_width: f64,
    box_height: f64,
) -> Option<FocalCropGeometry> {
    let placement = node.asset_placement.as_ref()?;
    let focal = placement.focal_point.as_ref()?;
    if !matches!(
        placement.fit,
        Some(ImageFitMode::Cover) | Some(ImageFitMode::Crop)
    ) {
        return None;
    }
    if box_width <= 0.0 || box_height <= 0.0 {
        return None;
    }
    let ratio = record?.natural_aspect_ratio()?;
    if !(ratio.is_finite() && ratio > 0.0) {
        return None;
    }

    let (drawn_width, drawn_height) = if box_width / box_height < ratio {
        (box_height * ratio, box_height)
    } else {
        (box_width, box_width / ratio)
    };
    let focal_x = focal.x.clamp(0.0, 1.0);
    let focal_y = focal.y.clamp(0.0, 1.0);
    let offset_x =
        (focal_x * drawn_width - box_width / 2.0).clamp(0.0, (drawn_width - box_width).max(0.0));
    let offset_y = (focal_y * drawn_height - box_height / 2.0)
        .clamp(0.0, (drawn_height - box_height).max(0.0));

    Some(FocalCropGeometry {
        x: -offset_x,
        y: -offset_y,
        width: drawn_width,
        height: drawn_height,
    })
}

/// Map the node's asset placement fit mode onto SVG preserveAspectRatio.
/// Contain letterboxes (`meet`); cover and crop fill the box (`slice`).
/// Focal-point crops take the explicit window path instead.
fn image_preserve_aspect_ratio(node: &Node) -> &'static str {
    match node
        .asset_placement
        .as_ref()
        .and_then(|placement| placement.fit.as_ref())
    {
        Some(ImageFitMode::Cover) | Some(ImageFitMode::Crop) => "xMidYMid slice",
        Some(ImageFitMode::Contain) | None => "xMidYMid meet",
    }
}

/// Per-node export warnings shared by the SVG renderer and the native
/// rasterizer: hug/fill without computed geometry (LUME0205) and unresolved
/// brand tokens on sizing/stroke/corner/opacity/layout/text-style fields
/// (LUME0209).
pub fn unresolved_brand_token_diagnostics(node: &Node) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    if matches!(node.size.width, Dimension::Hug | Dimension::Fill { .. })
        || matches!(node.size.height, Dimension::Hug | Dimension::Fill { .. })
    {
        diagnostics.push(
            Diagnostic::warning(
                Phase::Export,
                "LUME0205",
                format!(
                    "node {} uses hug/fill sizing without resolved export geometry",
                    node.id
                ),
                Some(DiagnosticSubject::Node(node.id.clone())),
            )
            .with_hint("Run layout before export or provide fixed/computed dimensions."),
        );
    }

    let mut field_token = |field: &str, token: &str| {
        diagnostics.push(
            Diagnostic::warning(
                Phase::Export,
                "LUME0209",
                format!(
                    "node {} uses unresolved brand token {} for {}",
                    node.id, token, field
                ),
                Some(DiagnosticSubject::Node(node.id.clone())),
            )
            .with_hint("Run the brand/token resolver before exporting tokenized scene fields."),
        );
    };

    if let Some(token) = dimension_token(&node.size.width) {
        field_token("size.width", token);
    }
    if let Some(token) = dimension_token(&node.size.height) {
        field_token("size.height", token);
    }
    for stroke in &node.strokes {
        if let Some(token) = &stroke.width_token {
            field_token(&format!("stroke {} width", stroke.id), token);
        }
    }
    if let Some(token) = &node.corner.token {
        field_token("corner radius", token);
    }
    if let Some(token) = &node.opacity_token {
        field_token("opacity", token);
    }
    if let Some(layout) = &node.layout {
        if let Some(token) = &layout.gap_token {
            field_token("layout gap", token);
        }
        if let Some(token) = &layout.padding_token {
            field_token("layout padding", token);
        }
    }
    if let NodeKind::Text(text) = &node.kind {
        if let Some(token) = &text.style_token {
            field_token("text style", token);
        }
    }
    diagnostics
}

/// Page-background token warnings (LUME0208) shared by both renderers.
pub fn page_background_token_diagnostics(page: &Page) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    for fill in &page.background {
        match &fill.paint {
            Paint::Token { token } => {
                diagnostics.push(unresolved_page_token_diag(&page.id, token));
            }
            Paint::Solid {
                color: Color::Token { token },
            } => {
                diagnostics.push(unresolved_page_token_diag(&page.id, token));
            }
            Paint::LinearGradient { stops, .. } | Paint::RadialGradient { stops } => {
                for stop in stops {
                    if let Color::Token { token } = &stop.color {
                        diagnostics.push(unresolved_page_token_diag(&page.id, token));
                    }
                }
            }
            Paint::Solid { .. } => {}
        }
    }
    diagnostics
}

#[derive(Clone, Copy, Debug)]
struct SvgPageDimensions {
    attr_width: f64,
    attr_height: f64,
    view_width: f64,
    view_height: f64,
    unit_suffix: &'static str,
}

fn page_dimensions(page: &Page) -> SvgPageDimensions {
    let geometry = page_geometry(page);
    if is_canonical_page_size(&page.size) {
        if let Some(physical) = geometry.physical {
            let unit_suffix = match physical.unit {
                PhysicalUnit::Mm => "mm",
                PhysicalUnit::In => "in",
            };
            return SvgPageDimensions {
                attr_width: physical.width,
                attr_height: physical.height,
                view_width: geometry.layout.width,
                view_height: geometry.layout.height,
                unit_suffix,
            };
        }

        return SvgPageDimensions {
            attr_width: geometry.layout.width,
            attr_height: geometry.layout.height,
            view_width: geometry.layout.width,
            view_height: geometry.layout.height,
            unit_suffix: "",
        };
    }

    let unit_suffix = match page.size.unit {
        Unit::Pt | Unit::Px => "",
        Unit::Mm => "mm",
        Unit::In => "in",
    };
    SvgPageDimensions {
        attr_width: page.size.width,
        attr_height: page.size.height,
        view_width: page.size.width,
        view_height: page.size.height,
        unit_suffix,
    }
}

pub fn node_size(node: &Node) -> (f64, f64) {
    node_render_size(node)
}

fn dimension_token(dimension: &Dimension) -> Option<&str> {
    match dimension {
        Dimension::Token { token } => Some(token),
        Dimension::Fixed(_) | Dimension::Hug | Dimension::Fill { .. } => None,
    }
}

/// The inner transform that fits a vector node's source viewBox uniformly (centered)
/// into its rendered box, so a library icon renders at the node's size. `None` when the
/// node has no viewBox (a hand-authored vector path → draw at raw coordinates).
fn icon_fit_transform(view_box: Option<[f64; 2]>, width: f64, height: f64) -> Option<String> {
    let [vbw, vbh] = view_box?;
    if vbw <= 0.0 || vbh <= 0.0 {
        return None;
    }
    let scale = (width / vbw).min(height / vbh);
    let tx = (width - vbw * scale) / 2.0;
    let ty = (height - vbh * scale) / 2.0;
    Some(format!(
        "translate({} {}) scale({})",
        fmt_num(tx),
        fmt_num(ty),
        fmt_num(scale)
    ))
}

fn transform_attr(node: &Node, x: f64, y: f64) -> String {
    let mut parts = Vec::new();
    if x != 0.0 || y != 0.0 {
        parts.push(format!("translate({} {})", fmt_num(x), fmt_num(y)));
    }
    if node.transform.rotation != 0.0 {
        parts.push(format!("rotate({})", fmt_num(node.transform.rotation)));
    }
    if node.transform.skew_x != 0.0 {
        parts.push(format!("skewX({})", fmt_num(node.transform.skew_x)));
    }
    if node.transform.skew_y != 0.0 {
        parts.push(format!("skewY({})", fmt_num(node.transform.skew_y)));
    }
    if node.transform.flip_x || node.transform.flip_y {
        parts.push(format!(
            "scale({} {})",
            if node.transform.flip_x { "-1" } else { "1" },
            if node.transform.flip_y { "-1" } else { "1" }
        ));
    }

    if parts.is_empty() {
        String::new()
    } else {
        format!(" transform=\"{}\"", escape_attr(&parts.join(" ")))
    }
}

/// True when all four corner radii are equal (the plain-`rx` fast path).
fn corners_uniform(node: &Node) -> bool {
    node.corner.top_left == node.corner.top_right
        && node.corner.top_left == node.corner.bottom_right
        && node.corner.top_left == node.corner.bottom_left
}

/// CSS overlap-algorithm clamp: scale every radius down by the single factor
/// that keeps each pair of adjacent radii within their shared side length.
/// Generalizes the uniform `min(w/2, h/2)` clamp (which is the equal-radii
/// special case). Returns `[tl, tr, br, bl]`.
fn clamped_corners(node: &Node, width: f64, height: f64) -> [f64; 4] {
    let c = &node.corner;
    let mut radii = [
        c.top_left.max(0.0),
        c.top_right.max(0.0),
        c.bottom_right.max(0.0),
        c.bottom_left.max(0.0),
    ];
    let [tl, tr, br, bl] = radii;
    // side length / sum of the two radii sharing that side.
    let ratios = [
        (width, tl + tr),   // top
        (height, tr + br),  // right
        (width, br + bl),   // bottom
        (height, tl + bl),  // left
    ];
    let mut factor = 1.0_f64;
    for (side, sum) in ratios {
        if sum > 0.0 {
            factor = factor.min(side / sum);
        }
    }
    if factor < 1.0 {
        for r in radii.iter_mut() {
            *r *= factor;
        }
    }
    radii
}

/// Rounded-rect `<path>` `d` with per-corner (circular) radii, clockwise from
/// the top-left corner. A zero-radius corner degenerates to a lineto per SVG
/// arc semantics. Origin is (0,0); size is `width`×`height`.
fn rounded_rect_path(width: f64, height: f64, radii: [f64; 4]) -> String {
    let [tl, tr, br, bl] = radii;
    let n = |v: f64| fmt_num(v);
    format!(
        "M {} 0 L {} 0 A {} {} 0 0 1 {} {} L {} {} A {} {} 0 0 1 {} {} L {} {} A {} {} 0 0 1 {} {} L 0 {} A {} {} 0 0 1 {} 0 Z",
        n(tl),
        n(width - tr),
        n(tr), n(tr), n(width), n(tr),
        n(width), n(height - br),
        n(br), n(br), n(width - br), n(height),
        n(bl), n(height),
        n(bl), n(bl), n(0.0), n(height - bl),
        n(tl),
        n(tl), n(tl), n(tl),
    )
}

/// The inner element of a rounded-rect clipPath: a plain `<rect>` on the
/// uniform fast path, a per-corner `<path>` when corners are mixed.
fn clip_shape_element(node: &Node, width: f64, height: f64) -> String {
    let (shape, geometry) = rect_shape(node, width, height);
    format!("<{shape} {geometry} />")
}

/// Geometry for a rect-like body element: `("rect", attrs)` on the uniform
/// fast path (keeps `rx`/`ry`), or `("path", d-attr)` when corners are mixed.
fn rect_shape(node: &Node, width: f64, height: f64) -> (&'static str, String) {
    if corners_uniform(node) {
        (
            "rect",
            format!(
                "x=\"0\" y=\"0\" width=\"{}\" height=\"{}\"{}",
                fmt_num(width),
                fmt_num(height),
                corner_attrs(node, width, height)
            ),
        )
    } else {
        (
            "path",
            format!(
                "d=\"{}\"",
                rounded_rect_path(width, height, clamped_corners(node, width, height))
            ),
        )
    }
}

fn corner_attrs(node: &Node, width: f64, height: f64) -> String {
    if node.corner.top_left == 0.0
        && node.corner.top_right == 0.0
        && node.corner.bottom_right == 0.0
        && node.corner.bottom_left == 0.0
    {
        return String::new();
    }

    if corners_uniform(node) {
        // Clamp like Skia: an oversized radius saturates at half the SMALLER
        // dimension, keeping a stadium shape. Emitting the raw value lets the
        // SVG renderer clamp rx/ry per-axis independently (rx→w/2, ry→h/2),
        // which turns pill buttons and badges into full ellipses on export
        // while the canvas shows stadiums.
        let radius = node
            .corner
            .top_left
            .min(width / 2.0)
            .min(height / 2.0)
            .max(0.0);
        return format!(" rx=\"{}\" ry=\"{}\"", fmt_num(radius), fmt_num(radius));
    }

    String::new()
}

fn opacity_with_paint(opacity: String, paint_attrs: String) -> String {
    format!("{}{}", opacity, paint_attrs)
}

fn svg_font_family(family: &str) -> String {
    let trimmed = family.trim();
    if trimmed.is_empty() {
        return "Arial, Helvetica, sans-serif".to_owned();
    }

    let lower = trimmed.to_ascii_lowercase();
    if trimmed.contains(',')
        || matches!(
            lower.as_str(),
            "serif" | "sans-serif" | "monospace" | "cursive" | "fantasy" | "system-ui"
        )
    {
        return trimmed.to_owned();
    }

    if lower == "inter" || lower == "inter variable" {
        return format!("{trimmed}, Arial, Helvetica, sans-serif");
    }

    trimmed.to_owned()
}

fn gradient_stops<F>(stops: &[ColorStop], mut color: F) -> String
where
    F: FnMut(&Color) -> String,
{
    stops
        .iter()
        .map(|stop| {
            let resolved = color(&stop.color);
            // Max-compat alpha (A4): an 8-digit #RRGGBBAA stop splits into a
            // 6-digit stop-color plus a stop-opacity, instead of relying on
            // CSS Color-4-only 8-digit hex parsing.
            let (stop_color, alpha) = split_hex_stop_alpha(&resolved);
            match alpha {
                Some(a) => format!(
                    "<stop offset=\"{}%\" stop-color=\"{}\" stop-opacity=\"{}\" />\n",
                    fmt_num(stop.position * 100.0),
                    stop_color,
                    fmt_num(a)
                ),
                None => format!(
                    "<stop offset=\"{}%\" stop-color=\"{}\" />\n",
                    fmt_num(stop.position * 100.0),
                    stop_color
                ),
            }
        })
        .collect()
}

/// Split a resolved `#RRGGBBAA` color into `(#RRGGBB, Some(alpha 0..=1))`.
/// Non-8-digit-hex colors (including oklch, which carries its own alpha)
/// return `(color, None)` unchanged.
fn split_hex_stop_alpha(resolved: &str) -> (String, Option<f64>) {
    if let Some(hex) = resolved.strip_prefix('#') {
        if hex.len() == 8 && hex.bytes().all(|b| b.is_ascii_hexdigit()) {
            if let Ok(a) = u8::from_str_radix(&hex[6..8], 16) {
                return (format!("#{}", &hex[0..6]), Some(a as f64 / 255.0));
            }
        }
    }
    (resolved.to_owned(), None)
}

// LUME0214 (text strokes dropped) RETIRED in A6a — text strokes now render
// (see `text_stroke_attrs`). The code number stays allocated in the
// diagnostics ledger as retired history; its emission sites are deleted.

fn unresolved_token_diag(node_id: &NodeId, token: &str) -> Diagnostic {
    Diagnostic::warning(
        Phase::Export,
        "LUME0206",
        format!("node {} references unresolved token {}", node_id, token),
        Some(DiagnosticSubject::Node(node_id.clone())),
    )
    .with_hint("Wire a brand/token resolver before treating tokenized export as final.")
}

fn unresolved_page_token_diag(page_id: &PageId, token: &str) -> Diagnostic {
    Diagnostic::warning(
        Phase::Export,
        "LUME0208",
        format!(
            "page {} references unresolved background token {}",
            page_id, token
        ),
        Some(DiagnosticSubject::Page(page_id.clone())),
    )
    .with_hint("Wire a brand/token resolver before treating tokenized page export as final.")
}

fn normalize_hex(value: &str) -> String {
    if value.starts_with('#') {
        value.to_owned()
    } else {
        format!("#{value}")
    }
}

pub fn fmt_num(value: f64) -> String {
    if value == 0.0 {
        return "0".to_owned();
    }
    let mut text = format!("{value:.4}");
    while text.contains('.') && text.ends_with('0') {
        text.pop();
    }
    if text.ends_with('.') {
        text.pop();
    }
    text
}

pub fn escape_attr(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('"', "&quot;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

pub fn escape_text(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}
