use crate::resolver::{AssetByteResolver, ResolvedAssetBytes};
use crate::sidecar::{build_sidecar, node_output_id, page_output_id};
use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use lumen_core::scene::{ColorStop, PhysicalUnit};
use lumen_core::{
    is_canonical_page_size, node_render_size, page_geometry, render_box_for_node, Color,
    Diagnostic, DiagnosticSubject, Dimension, EffectKind, ExportAdapter, ExportArtifact,
    ExportError, ExportFormat, ExportRequest, ExportResult, Fill, ImageFitMode, ImageNode, Node,
    NodeId, NodeKind, Page, PageId, Paint, Phase, Rect, Scene, Stroke, StrokeAlign, StrokeCap,
    StrokeJoin, TextAlign, TextDirection, Unit,
};
use lumen_core::{HeuristicTextMeasurer, SharedTextMeasurer, TextMeasureInput, TextMeasurer};
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
            self.render_node(child_id, None);
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
                let geometry = format!(
                    "x=\"0\" y=\"0\" width=\"{}\" height=\"{}\"{}",
                    fmt_num(width),
                    fmt_num(height),
                    corner_attrs(node)
                );
                if stacked {
                    for layer in self.paint_layer_attrs(&node.fills, &node.strokes, Some(&node.id))
                    {
                        self.body.push_str(&format!("<rect {geometry}{layer} />\n"));
                    }
                } else if !node.fills.is_empty() || !node.strokes.is_empty() {
                    let fill_attrs = self.paint_attrs(&node.fills, &node.strokes, Some(&node.id));
                    self.body
                        .push_str(&format!("<rect {geometry}{fill_attrs} />\n"));
                }
                if let Some(clip_id) = clip_id {
                    self.body.push_str(&format!(
                        "<g clip-path=\"url(#{})\">\n",
                        escape_attr(&clip_id)
                    ));
                }
                for child_id in &node.children {
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
                    self.render_node(child_id, child_parent_origin);
                }
                self.body.push_str("</g>\n");
            }
            NodeKind::Rect => {
                let geometry = format!(
                    "x=\"0\" y=\"0\" width=\"{}\" height=\"{}\"{}",
                    fmt_num(width),
                    fmt_num(height),
                    corner_attrs(node)
                );
                if stacked {
                    self.body.push_str(&format!(
                        "<g{}{}{}{}>\n",
                        id_attrs, transform, opacity, filter
                    ));
                    for layer in self.paint_layer_attrs(&node.fills, &node.strokes, Some(&node.id))
                    {
                        self.body.push_str(&format!("<rect {geometry}{layer} />\n"));
                    }
                    self.body.push_str("</g>\n");
                } else {
                    let paint_attrs = self.paint_attrs(&node.fills, &node.strokes, Some(&node.id));
                    self.body.push_str(&format!(
                        "<rect{} {}{}{}{} />\n",
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
                let anchor = match text.align {
                    TextAlign::Left | TextAlign::Justify => "start",
                    TextAlign::Center => "middle",
                    TextAlign::Right => "end",
                };
                let x = match text.align {
                    TextAlign::Left | TextAlign::Justify => 0.0,
                    TextAlign::Center => width / 2.0,
                    TextAlign::Right => width,
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
                let tspans = measured
                    .lines
                    .iter()
                    .map(|line| {
                        format!(
                            "<tspan x=\"{}\" y=\"{}\">{}</tspan>",
                            fmt_num(x),
                            fmt_num(line.baseline),
                            escape_text(&line.text)
                        )
                    })
                    .collect::<String>();
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
                    "<text{} x=\"{}\" y=\"{}\" font-family=\"{}\" font-size=\"{}\" font-weight=\"{}\" text-anchor=\"{}\" letter-spacing=\"{}\" direction=\"{}\"{}{}{}>{}</text>\n",
                    id_attrs,
                    fmt_num(x),
                    fmt_num(text.font_size),
                    escape_attr(&text.font_family),
                    fmt_num(text.font_size),
                    text.font_weight,
                    anchor,
                    fmt_num(text.letter_spacing),
                    direction,
                    transform,
                    filter,
                    opacity_with_paint(opacity, paint_attrs),
                    tspans
                ));
            }
            NodeKind::Vector(vector) => {
                let geometry = format!("d=\"{}\"", escape_attr(&vector.path_data));
                if stacked {
                    self.body.push_str(&format!(
                        "<g{}{}{}{}>\n",
                        id_attrs, transform, opacity, filter
                    ));
                    for layer in self.paint_layer_attrs(&node.fills, &node.strokes, Some(&node.id))
                    {
                        self.body.push_str(&format!("<path {geometry}{layer} />\n"));
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
                    "<clipPath id=\"{}\"><rect x=\"0\" y=\"0\" width=\"{}\" height=\"{}\"{} /></clipPath>\n",
                    clip_id,
                    fmt_num(width),
                    fmt_num(height),
                    corner_attrs(node)
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
        if !node.fills.is_empty() {
            return self.paint_attrs(&node.fills, &[], Some(&node.id));
        }

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

    /// Register a deterministic `<filter>` for the node's drop-shadow stack
    /// and return the `filter` attribute. The first effect in the stack
    /// renders as the topmost shadow (CSS box-shadow convention).
    fn effect_filter_attr(&mut self, node: &Node) -> String {
        if node.effects.is_empty() {
            return String::new();
        }

        struct ResolvedShadow {
            color: String,
            opacity: f64,
            x: f64,
            y: f64,
            blur: f64,
            spread: f64,
        }

        let mut shadows = Vec::new();
        for effect in &node.effects {
            let EffectKind::DropShadow {
                color,
                opacity,
                x,
                y,
                blur,
                spread,
                ..
            } = &effect.kind;
            if let Color::Token { token } = color {
                self.diagnostics
                    .push(unresolved_token_diag(&node.id, token));
                continue;
            }
            shadows.push(ResolvedShadow {
                color: self.color_ref(color, Some(&node.id)),
                opacity: *opacity,
                x: *x,
                y: *y,
                blur: *blur,
                spread: *spread,
            });
        }
        if shadows.is_empty() {
            return String::new();
        }

        let filter_id = format!("lumen-effect-{}", escape_attr(node.id.as_str()));
        let mut body = String::new();
        if shadows.iter().all(|shadow| shadow.spread == 0.0) {
            // Chained feDropShadow keeps each later shadow underneath the
            // accumulated result, so stack order is preserved.
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
            // Spread needs a morphology composite per shadow, merged with
            // the source on top.
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

        self.defs.push(format!(
            "<filter id=\"{filter_id}\" x=\"-50%\" y=\"-50%\" width=\"200%\" height=\"200%\">\n{body}</filter>\n"
        ));
        format!(" filter=\"url(#{filter_id})\"")
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
            "<clipPath id=\"{}\"><rect x=\"0\" y=\"0\" width=\"{}\" height=\"{}\"{} /></clipPath>\n",
            clip_id,
            fmt_num(width),
            fmt_num(height),
            corner_attrs(node)
        ));
        clip_id
    }
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

fn corner_attrs(node: &Node) -> String {
    if node.corner.top_left == 0.0
        && node.corner.top_right == 0.0
        && node.corner.bottom_right == 0.0
        && node.corner.bottom_left == 0.0
    {
        return String::new();
    }

    if node.corner.top_left == node.corner.top_right
        && node.corner.top_left == node.corner.bottom_right
        && node.corner.top_left == node.corner.bottom_left
    {
        return format!(
            " rx=\"{}\" ry=\"{}\"",
            fmt_num(node.corner.top_left),
            fmt_num(node.corner.top_left)
        );
    }

    String::new()
}

fn opacity_with_paint(opacity: String, paint_attrs: String) -> String {
    format!("{}{}", opacity, paint_attrs)
}

fn gradient_stops<F>(stops: &[ColorStop], mut color: F) -> String
where
    F: FnMut(&Color) -> String,
{
    stops
        .iter()
        .map(|stop| {
            format!(
                "<stop offset=\"{}%\" stop-color=\"{}\" />\n",
                fmt_num(stop.position * 100.0),
                color(&stop.color)
            )
        })
        .collect()
}

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
