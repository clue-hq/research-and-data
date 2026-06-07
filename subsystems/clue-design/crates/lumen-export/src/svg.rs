use crate::sidecar::{build_sidecar, node_output_id, page_output_id};
use lumen_core::scene::ColorStop;
use lumen_core::{
    Color, Diagnostic, DiagnosticSubject, Dimension, ExportAdapter, ExportArtifact, ExportError,
    ExportFormat, ExportRequest, ExportResult, Fill, Node, NodeId, NodeKind, Page, PageId, Paint,
    Phase, Scene, Stroke, TextAlign, Transform, Unit,
};

#[derive(Clone, Debug, Default)]
pub struct SvgExportAdapter;

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

            let mut renderer = SvgPageRenderer::new(scene, page);
            let svg = renderer.render_page();
            diagnostics.extend(renderer.diagnostics);

            let sidecar = build_sidecar(scene, &[page_id.clone()], &request.profile.name);
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
    defs: Vec<String>,
    body: String,
    diagnostics: Vec<Diagnostic>,
}

impl<'a> SvgPageRenderer<'a> {
    fn new(scene: &'a Scene, page: &'a Page) -> Self {
        Self {
            scene,
            page,
            defs: Vec::new(),
            body: String::new(),
            diagnostics: Vec::new(),
        }
    }

    fn render_page(&mut self) -> String {
        let (width, height, unit_suffix) = page_dimensions(self.page);

        self.body.push_str(&format!(
            "<g id=\"{}\" data-lumen-page-id=\"{}\">\n",
            escape_attr(&page_output_id(&self.page.id)),
            escape_attr(self.page.id.as_str())
        ));

        if !self.page.background.is_empty() {
            let attrs = self.page_paint_attrs(&self.page.background);
            self.body.push_str(&format!(
                "<rect x=\"0\" y=\"0\" width=\"{}\" height=\"{}\"{} />\n",
                fmt_num(width),
                fmt_num(height),
                attrs
            ));
        }

        for child_id in &self.page.children {
            self.render_node(child_id);
        }

        self.body.push_str("</g>\n");

        let defs = if self.defs.is_empty() {
            String::new()
        } else {
            format!("<defs>\n{}</defs>\n", self.defs.join(""))
        };

        format!(
            "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{}{}\" height=\"{}{}\" viewBox=\"0 0 {} {}\" data-lumen-document-id=\"{}\" data-lumen-page-id=\"{}\">\n{}{}{}</svg>\n",
            fmt_num(width),
            unit_suffix,
            fmt_num(height),
            unit_suffix,
            fmt_num(width),
            fmt_num(height),
            escape_attr(&self.scene.meta.id.to_string()),
            escape_attr(self.page.id.as_str()),
            defs,
            self.body,
            ""
        )
    }

    fn render_node(&mut self, node_id: &NodeId) {
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
        let (width, height) = node_size(node);
        let id_attrs = self.node_attrs(node);
        let transform = transform_attr(&node.transform);
        let opacity = if node.opacity < 1.0 {
            format!(" opacity=\"{}\"", fmt_num(node.opacity))
        } else {
            String::new()
        };

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
                self.body
                    .push_str(&format!("<g{}{}{}>\n", id_attrs, transform, opacity));
                let fill_attrs = self.paint_attrs(&node.fills, &node.strokes, Some(&node.id));
                if !node.fills.is_empty() || !node.strokes.is_empty() {
                    self.body.push_str(&format!(
                        "<rect x=\"0\" y=\"0\" width=\"{}\" height=\"{}\"{}{} />\n",
                        fmt_num(width),
                        fmt_num(height),
                        corner_attrs(node),
                        fill_attrs
                    ));
                }
                if let Some(clip_id) = clip_id {
                    self.body.push_str(&format!(
                        "<g clip-path=\"url(#{})\">\n",
                        escape_attr(&clip_id)
                    ));
                }
                for child_id in &node.children {
                    self.render_node(child_id);
                }
                if node.clip {
                    self.body.push_str("</g>\n");
                }
                self.body.push_str("</g>\n");
            }
            NodeKind::Group => {
                self.body
                    .push_str(&format!("<g{}{}{}>\n", id_attrs, transform, opacity));
                for child_id in &node.children {
                    self.render_node(child_id);
                }
                self.body.push_str("</g>\n");
            }
            NodeKind::Rect => {
                let paint_attrs = self.paint_attrs(&node.fills, &node.strokes, Some(&node.id));
                self.body.push_str(&format!(
                    "<rect{} x=\"0\" y=\"0\" width=\"{}\" height=\"{}\"{}{}{} />\n",
                    id_attrs,
                    fmt_num(width),
                    fmt_num(height),
                    corner_attrs(node),
                    transform,
                    opacity_with_paint(opacity, paint_attrs)
                ));
            }
            NodeKind::Ellipse => {
                let paint_attrs = self.paint_attrs(&node.fills, &node.strokes, Some(&node.id));
                self.body.push_str(&format!(
                    "<ellipse{} cx=\"{}\" cy=\"{}\" rx=\"{}\" ry=\"{}\"{}{} />\n",
                    id_attrs,
                    fmt_num(width / 2.0),
                    fmt_num(height / 2.0),
                    fmt_num(width / 2.0),
                    fmt_num(height / 2.0),
                    transform,
                    opacity_with_paint(opacity, paint_attrs)
                ));
            }
            NodeKind::Line(line) => {
                let paint_attrs = self.paint_attrs(&[], &node.strokes, Some(&node.id));
                self.body.push_str(&format!(
                    "<line{} x1=\"0\" y1=\"0\" x2=\"{}\" y2=\"{}\"{}{} />\n",
                    id_attrs,
                    fmt_num(line.x2),
                    fmt_num(line.y2),
                    transform,
                    opacity_with_paint(opacity, paint_attrs)
                ));
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
                self.body.push_str(&format!(
                    "<text{} x=\"{}\" y=\"{}\" font-family=\"{}\" font-size=\"{}\" font-weight=\"{}\" text-anchor=\"{}\"{}{}>{}</text>\n",
                    id_attrs,
                    fmt_num(x),
                    fmt_num(text.font_size),
                    escape_attr(&text.font_family),
                    fmt_num(text.font_size),
                    text.font_weight,
                    anchor,
                    transform,
                    opacity_with_paint(opacity, paint_attrs),
                    escape_text(&text.content)
                ));
            }
            NodeKind::Vector(vector) => {
                let paint_attrs = self.paint_attrs(&node.fills, &node.strokes, Some(&node.id));
                self.body.push_str(&format!(
                    "<path{} d=\"{}\"{}{} />\n",
                    id_attrs,
                    escape_attr(&vector.path_data),
                    transform,
                    opacity_with_paint(opacity, paint_attrs)
                ));
            }
            NodeKind::Image(image) => {
                self.diagnostics.push(Diagnostic::warning(
                    Phase::Export,
                    "LUME0202",
                    format!("image node {} references asset {} but no asset resolver is configured", node.id, image.asset_id),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                ).with_hint("Add an asset resolver in the asset pipeline workstream before treating image export as complete."));
                self.body.push_str(&format!(
                    "<g{}{}{} data-lumen-unsupported=\"image\" data-lumen-asset-id=\"{}\" />\n",
                    id_attrs,
                    transform,
                    opacity,
                    escape_attr(image.asset_id.as_str())
                ));
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

    fn paint_attrs(
        &mut self,
        fills: &[Fill],
        strokes: &[Stroke],
        node_id: Option<&NodeId>,
    ) -> String {
        let mut attrs = String::new();
        if let Some(fill) = fills.first() {
            attrs.push_str(&format!(
                " fill=\"{}\"",
                self.paint_ref(&fill.paint, &fill.id.to_string(), node_id)
            ));
            attrs.push_str(&format!(
                " data-lumen-fill-id=\"{}\"",
                escape_attr(fill.id.as_str())
            ));
        } else {
            attrs.push_str(" fill=\"none\"");
        }

        if let Some(stroke) = strokes.first() {
            attrs.push_str(&format!(
                " stroke=\"{}\"",
                self.paint_ref(&stroke.paint, &stroke.id.to_string(), node_id)
            ));
            attrs.push_str(&format!(" stroke-width=\"{}\"", fmt_num(stroke.width)));
            attrs.push_str(&format!(
                " data-lumen-stroke-id=\"{}\"",
                escape_attr(stroke.id.as_str())
            ));
        }

        if fills.len() > 1 || strokes.len() > 1 {
            if let Some(node_id) = node_id {
                self.diagnostics.push(Diagnostic::warning(
                    Phase::Export,
                    "LUME0204",
                    format!("node {} has multiple fills or strokes; SVG baseline uses the first fill and first stroke", node_id),
                    Some(DiagnosticSubject::Node(node_id.clone())),
                ));
            }
        }

        attrs
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
        if matches!(node.size.width, Dimension::Hug | Dimension::Fill { .. })
            || matches!(node.size.height, Dimension::Hug | Dimension::Fill { .. })
        {
            self.diagnostics.push(
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

        if let Some(token) = dimension_token(&node.size.width) {
            self.warn_unresolved_node_brand_token(node, "size.width", token);
        }
        if let Some(token) = dimension_token(&node.size.height) {
            self.warn_unresolved_node_brand_token(node, "size.height", token);
        }
        for stroke in &node.strokes {
            if let Some(token) = &stroke.width_token {
                self.warn_unresolved_node_brand_token(
                    node,
                    &format!("stroke {} width", stroke.id),
                    token,
                );
            }
        }
        if let Some(token) = &node.corner.token {
            self.warn_unresolved_node_brand_token(node, "corner radius", token);
        }
        if let Some(token) = &node.opacity_token {
            self.warn_unresolved_node_brand_token(node, "opacity", token);
        }
        if let Some(layout) = &node.layout {
            if let Some(token) = &layout.gap_token {
                self.warn_unresolved_node_brand_token(node, "layout gap", token);
            }
            if let Some(token) = &layout.padding_token {
                self.warn_unresolved_node_brand_token(node, "layout padding", token);
            }
        }
        if let NodeKind::Text(text) = &node.kind {
            if let Some(token) = &text.style_token {
                self.warn_unresolved_node_brand_token(node, "text style", token);
            }
        }
    }

    fn warn_unresolved_node_brand_token(&mut self, node: &Node, field: &str, token: &str) {
        self.diagnostics.push(
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

fn page_dimensions(page: &Page) -> (f64, f64, &'static str) {
    let suffix = match page.size.unit {
        Unit::Px => "",
        Unit::Mm => "mm",
        Unit::In => "in",
    };
    (page.size.width, page.size.height, suffix)
}

pub fn node_size(node: &Node) -> (f64, f64) {
    if let Some(computed) = &node.computed {
        return (computed.layout_bounds.width, computed.layout_bounds.height);
    }

    (
        dimension_value(&node.size.width),
        dimension_value(&node.size.height),
    )
}

fn dimension_value(dimension: &Dimension) -> f64 {
    match dimension {
        Dimension::Fixed(value) => *value,
        Dimension::Hug | Dimension::Fill { .. } | Dimension::Token { .. } => 0.0,
    }
}

fn dimension_token(dimension: &Dimension) -> Option<&str> {
    match dimension {
        Dimension::Token { token } => Some(token),
        Dimension::Fixed(_) | Dimension::Hug | Dimension::Fill { .. } => None,
    }
}

fn transform_attr(transform: &Transform) -> String {
    let mut parts = Vec::new();
    if transform.x != 0.0 || transform.y != 0.0 {
        parts.push(format!(
            "translate({} {})",
            fmt_num(transform.x),
            fmt_num(transform.y)
        ));
    }
    if transform.rotation != 0.0 {
        parts.push(format!("rotate({})", fmt_num(transform.rotation)));
    }
    if transform.skew_x != 0.0 {
        parts.push(format!("skewX({})", fmt_num(transform.skew_x)));
    }
    if transform.skew_y != 0.0 {
        parts.push(format!("skewY({})", fmt_num(transform.skew_y)));
    }
    if transform.flip_x || transform.flip_y {
        parts.push(format!(
            "scale({} {})",
            if transform.flip_x { "-1" } else { "1" },
            if transform.flip_y { "-1" } else { "1" }
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
