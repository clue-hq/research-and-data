use crate::sidecar::build_sidecar;
use crate::svg::{fmt_num, resolve_page_ids};
use lumen_core::{
    measure_text, render_box_for_node, Diagnostic, DiagnosticSubject, ExportAdapter,
    ExportArtifact, ExportError, ExportFormat, ExportRequest, ExportResult, Node, NodeId, NodeKind,
    Page, Paint, Phase, Rect, Scene, TextAlign, TextMeasureInput, Unit,
};

#[derive(Clone, Debug, Default)]
pub struct PdfExportAdapter;

impl ExportAdapter for PdfExportAdapter {
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
        diagnostics.push(
            Diagnostic::warning(
                Phase::Export,
                "LUME0401",
                "early PDF export uses built-in PDF fonts and does not embed or subset brand fonts",
                Some(DiagnosticSubject::Document),
            )
            .with_hint("Use the text-shaping/font spike before treating PDF typography as final."),
        );

        if request.profile.embed_fonts {
            diagnostics.push(Diagnostic::warning(
                Phase::Export,
                "LUME0402",
                "export profile requested font embedding, but early PDF export cannot embed fonts yet",
                Some(DiagnosticSubject::Document),
            ));
        }

        let mut writer = PdfWriter::new();
        let page_ids = resolved.page_ids;
        for page_id in &page_ids {
            let Some(page) = scene.pages.get(page_id) else {
                continue;
            };
            let mut renderer = PdfPageRenderer::new(scene, page);
            let stream = renderer.render_page();
            diagnostics.extend(renderer.diagnostics);
            writer.add_page(page, stream);
        }

        let sidecar = build_sidecar(scene, &page_ids, &request.profile.name);
        let sidecar_json = serde_json::to_string_pretty(&sidecar).ok();

        Ok(ExportResult {
            artifacts: vec![ExportArtifact {
                format: ExportFormat::Pdf,
                page_id: None,
                asset_id: None,
                mime_type: "application/pdf".to_owned(),
                bytes: writer.finish(),
                sidecar_json,
            }],
            diagnostics,
        })
    }
}

struct PdfPageRenderer<'a> {
    scene: &'a Scene,
    page: &'a Page,
    scale: f64,
    page_height: f64,
    stream: String,
    diagnostics: Vec<Diagnostic>,
}

enum PaintResult<'a> {
    Applied,
    Unsupported,
    Token(&'a str),
}

impl<'a> PdfPageRenderer<'a> {
    fn new(scene: &'a Scene, page: &'a Page) -> Self {
        let scale = unit_to_points(&page.size.unit);
        Self {
            scene,
            page,
            scale,
            page_height: page.size.height * scale,
            stream: String::new(),
            diagnostics: Vec::new(),
        }
    }

    fn render_page(&mut self) -> String {
        self.draw_page_background();
        for child_id in &self.page.children {
            self.render_node(child_id, 0.0, 0.0, None);
        }
        self.stream.clone()
    }

    fn render_node(
        &mut self,
        node_id: &NodeId,
        parent_x: f64,
        parent_y: f64,
        parent_computed_origin: Option<(f64, f64)>,
    ) {
        let Some(node) = self.scene.nodes.get(node_id) else {
            self.diagnostics.push(Diagnostic::error(
                Phase::Export,
                "LUME0102",
                format!("page {} references missing node {}", self.page.id, node_id),
                Some(DiagnosticSubject::Page(self.page.id.clone())),
            ));
            return;
        };

        let render_box = render_box_for_node(node, parent_computed_origin);
        let (x, y) = absolute_xy(
            node,
            parent_x,
            parent_y,
            render_box.x,
            render_box.y,
            parent_computed_origin,
        );
        let width = render_box.width;
        let height = render_box.height;
        let child_parent_origin = node
            .computed
            .as_ref()
            .map(|computed| (computed.layout_bounds.x, computed.layout_bounds.y));

        if node.transform.rotation != 0.0
            || node.transform.skew_x != 0.0
            || node.transform.skew_y != 0.0
            || node.transform.flip_x
            || node.transform.flip_y
        {
            self.diagnostics.push(Diagnostic::warning(
                Phase::Export,
                "LUME0403",
                format!(
                    "PDF export currently ignores non-translation transform details on node {}",
                    node.id
                ),
                Some(DiagnosticSubject::Node(node.id.clone())),
            ));
        }

        match &node.kind {
            NodeKind::Frame | NodeKind::Group | NodeKind::AutoLayout(_) => {
                if !node.fills.is_empty() || !node.strokes.is_empty() {
                    self.draw_rect(node, x, y, width, height);
                }
                for child_id in &node.children {
                    self.render_node(child_id, x, y, child_parent_origin);
                }
            }
            NodeKind::Rect => self.draw_rect(node, x, y, width, height),
            NodeKind::Ellipse => self.warn_unsupported(node, "ellipse"),
            NodeKind::Line(line) => {
                if self.apply_stroke(node) {
                    self.stream.push_str(&format!(
                        "{} {} m {} {} l S\n",
                        fmt_num(x * self.scale),
                        fmt_num(self.pdf_y(y)),
                        fmt_num((x + line.x2) * self.scale),
                        fmt_num(self.pdf_y(y + line.y2))
                    ));
                } else {
                    self.diagnostics.push(Diagnostic::warning(
                        Phase::Export,
                        "LUME0407",
                        format!(
                            "line node {} has no supported stroke for PDF export",
                            node.id
                        ),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    ));
                }
            }
            NodeKind::Text(text) => {
                self.apply_text_fill(node);
                let measured =
                    measure_text(&TextMeasureInput::from_text_node(text).with_bounds(&Rect {
                        x: 0.0,
                        y: 0.0,
                        width,
                        height,
                    }));
                self.stream.push_str(&format!(
                    "BT /F1 {} Tf {} Tc\n",
                    fmt_num(text.font_size * self.scale),
                    fmt_num(text.letter_spacing * self.scale)
                ));
                for line in &measured.lines {
                    let text_x = match text.align {
                        TextAlign::Left | TextAlign::Justify => x,
                        TextAlign::Center => x + ((width - line.width) / 2.0),
                        TextAlign::Right => x + width - line.width,
                    };
                    self.stream.push_str(&format!(
                        "1 0 0 1 {} {} Tm ({}) Tj\n",
                        fmt_num(text_x * self.scale),
                        fmt_num(self.pdf_y(y + line.baseline)),
                        escape_pdf_text(&line.text)
                    ));
                }
                self.stream.push_str("ET\n");
            }
            NodeKind::Vector(_) => self.warn_unsupported(node, "vector path"),
            NodeKind::Image(_) => self.warn_unsupported(node, "image"),
            NodeKind::Instance { .. } => self.warn_unsupported(node, "instance"),
        }
    }

    fn draw_page_background(&mut self) {
        for fill in &self.page.background {
            let has_fill = self.apply_page_background_fill(fill);
            if has_fill {
                self.stream.push_str(&format!(
                    "0 0 {} {} re f\n",
                    fmt_num(self.page.size.width * self.scale),
                    fmt_num(self.page.size.height * self.scale)
                ));
            }
        }
    }

    fn draw_rect(&mut self, node: &Node, x: f64, y: f64, width: f64, height: f64) {
        let has_fill = self.apply_fill(node);
        let has_stroke = self.apply_stroke(node);

        if has_fill || has_stroke {
            self.stream.push_str(&format!(
                "{} {} {} {} re {}\n",
                fmt_num(x * self.scale),
                fmt_num(self.pdf_y(y + height)),
                fmt_num(width * self.scale),
                fmt_num(height * self.scale),
                match (has_fill, has_stroke) {
                    (true, true) => "B",
                    (true, false) => "f",
                    (false, true) => "S",
                    (false, false) => unreachable!("guarded by has_fill || has_stroke"),
                }
            ));
        }
    }

    fn apply_fill(&mut self, node: &Node) -> bool {
        let Some(fill) = node.fills.first() else {
            return false;
        };

        match self.apply_fill_paint(&fill.paint) {
            PaintResult::Applied => true,
            PaintResult::Unsupported => {
                self.warn_unsupported_fill(node);
                false
            }
            PaintResult::Token(token) => {
                self.warn_unresolved_token(Some(node), token);
                false
            }
        }
    }

    fn apply_page_background_fill(&mut self, fill: &lumen_core::Fill) -> bool {
        match self.apply_fill_paint(&fill.paint) {
            PaintResult::Applied => true,
            PaintResult::Unsupported => {
                self.diagnostics.push(Diagnostic::warning(
                    Phase::Export,
                    "LUME0408",
                    format!(
                        "PDF export only supports solid hex page backgrounds for page {}",
                        self.page.id
                    ),
                    Some(DiagnosticSubject::Page(self.page.id.clone())),
                ));
                false
            }
            PaintResult::Token(token) => {
                self.warn_unresolved_token(None, token);
                false
            }
        }
    }

    fn apply_text_fill(&mut self, node: &Node) {
        let Some(fill) = node.fills.first() else {
            self.stream.push_str("0 0 0 rg\n");
            self.diagnostics.push(Diagnostic::warning(
                Phase::Export,
                "LUME0409",
                format!("text node {} has no fill; PDF export used black", node.id),
                Some(DiagnosticSubject::Node(node.id.clone())),
            ));
            return;
        };

        match self.apply_fill_paint(&fill.paint) {
            PaintResult::Applied => {}
            PaintResult::Unsupported => {
                self.stream.push_str("0 0 0 rg\n");
                self.warn_unsupported_fill(node);
            }
            PaintResult::Token(token) => {
                self.stream.push_str("0 0 0 rg\n");
                self.warn_unresolved_token(Some(node), token);
            }
        }
    }

    fn apply_fill_paint<'b>(&mut self, paint: &'b Paint) -> PaintResult<'b> {
        match paint {
            Paint::Solid { color } => {
                if let Some((r, g, b)) = pdf_rgb(color) {
                    self.stream.push_str(&format!("{} {} {} rg\n", r, g, b));
                    PaintResult::Applied
                } else {
                    match color {
                        lumen_core::Color::Token { token } => PaintResult::Token(token),
                        _ => PaintResult::Unsupported,
                    }
                }
            }
            Paint::Token { token } => PaintResult::Token(token),
            Paint::LinearGradient { .. } | Paint::RadialGradient { .. } => PaintResult::Unsupported,
        }
    }

    fn apply_stroke(&mut self, node: &Node) -> bool {
        let Some(stroke) = node.strokes.first() else {
            return false;
        };

        match &stroke.paint {
            Paint::Solid { color } => {
                if let Some((r, g, b)) = pdf_rgb(color) {
                    self.stream.push_str(&format!("{} {} {} RG\n", r, g, b));
                    self.stream
                        .push_str(&format!("{} w\n", fmt_num(stroke.width * self.scale)));
                    true
                } else {
                    self.warn_unsupported_stroke(node);
                    false
                }
            }
            _ => {
                self.warn_unsupported_stroke(node);
                false
            }
        }
    }

    fn warn_unsupported_fill(&mut self, node: &Node) {
        self.diagnostics.push(Diagnostic::warning(
            Phase::Export,
            "LUME0404",
            format!(
                "PDF export only supports solid hex fills for node {}",
                node.id
            ),
            Some(DiagnosticSubject::Node(node.id.clone())),
        ));
    }

    fn warn_unsupported_stroke(&mut self, node: &Node) {
        self.diagnostics.push(Diagnostic::warning(
            Phase::Export,
            "LUME0406",
            format!(
                "PDF export only supports solid hex strokes for node {}",
                node.id
            ),
            Some(DiagnosticSubject::Node(node.id.clone())),
        ));
    }

    fn warn_unresolved_token(&mut self, node: Option<&Node>, token: &str) {
        self.diagnostics.push(Diagnostic::warning(
            Phase::Export,
            "LUME0410",
            format!("PDF export cannot resolve token {}", token),
            node.map(|node| DiagnosticSubject::Node(node.id.clone()))
                .or_else(|| Some(DiagnosticSubject::Page(self.page.id.clone()))),
        ));
    }

    fn warn_unsupported(&mut self, node: &Node, feature: &str) {
        self.diagnostics.push(Diagnostic::warning(
            Phase::Export,
            "LUME0405",
            format!(
                "early PDF export does not yet render {} node {}",
                feature, node.id
            ),
            Some(DiagnosticSubject::Node(node.id.clone())),
        ));
    }

    fn pdf_y(&self, y: f64) -> f64 {
        self.page_height - (y * self.scale)
    }
}

fn absolute_xy(
    node: &Node,
    parent_x: f64,
    parent_y: f64,
    local_x: f64,
    local_y: f64,
    parent_computed_origin: Option<(f64, f64)>,
) -> (f64, f64) {
    if node.computed.is_some() && parent_computed_origin.is_none() {
        return (local_x, local_y);
    }

    (parent_x + local_x, parent_y + local_y)
}

struct PdfWriter {
    pages: Vec<(f64, f64, String)>,
}

impl PdfWriter {
    fn new() -> Self {
        Self { pages: Vec::new() }
    }

    fn add_page(&mut self, page: &Page, stream: String) {
        self.pages.push((
            page.size.width * unit_to_points(&page.size.unit),
            page.size.height * unit_to_points(&page.size.unit),
            stream,
        ));
    }

    fn finish(self) -> Vec<u8> {
        let page_count = self.pages.len();
        let font_id = 3 + page_count * 2;
        let mut objects = Vec::new();

        objects.push("<< /Type /Catalog /Pages 2 0 R >>".to_owned());

        let kids = (0..page_count)
            .map(|idx| format!("{} 0 R", 3 + idx * 2))
            .collect::<Vec<_>>()
            .join(" ");
        objects.push(format!(
            "<< /Type /Pages /Kids [{}] /Count {} >>",
            kids, page_count
        ));

        for (idx, (width, height, stream)) in self.pages.iter().enumerate() {
            let page_obj_id = 3 + idx * 2;
            let content_obj_id = page_obj_id + 1;
            objects.push(format!(
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {} {}] /Resources << /Font << /F1 {} 0 R >> >> /Contents {} 0 R >>",
                fmt_num(*width),
                fmt_num(*height),
                font_id,
                content_obj_id
            ));
            objects.push(format!(
                "<< /Length {} >>\nstream\n{}endstream",
                stream.len(),
                stream
            ));
        }

        objects.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>".to_owned());

        let mut bytes = b"%PDF-1.4\n".to_vec();
        let mut offsets = Vec::new();
        offsets.push(0usize);

        for (idx, object) in objects.iter().enumerate() {
            offsets.push(bytes.len());
            bytes.extend_from_slice(format!("{} 0 obj\n{}\nendobj\n", idx + 1, object).as_bytes());
        }

        let xref_start = bytes.len();
        bytes.extend_from_slice(format!("xref\n0 {}\n", objects.len() + 1).as_bytes());
        bytes.extend_from_slice(b"0000000000 65535 f \n");
        for offset in offsets.iter().skip(1) {
            bytes.extend_from_slice(format!("{offset:010} 00000 n \n").as_bytes());
        }
        bytes.extend_from_slice(
            format!(
                "trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{}\n%%EOF\n",
                objects.len() + 1,
                xref_start
            )
            .as_bytes(),
        );
        bytes
    }
}

fn unit_to_points(unit: &Unit) -> f64 {
    match unit {
        Unit::Px => 1.0,
        Unit::Mm => 72.0 / 25.4,
        Unit::In => 72.0,
    }
}

fn pdf_rgb(color: &lumen_core::Color) -> Option<(String, String, String)> {
    match color {
        lumen_core::Color::Hex { value } => {
            let value = value.trim_start_matches('#');
            if value.len() < 6 {
                return None;
            }
            let r = u8::from_str_radix(&value[0..2], 16).ok()? as f64 / 255.0;
            let g = u8::from_str_radix(&value[2..4], 16).ok()? as f64 / 255.0;
            let b = u8::from_str_radix(&value[4..6], 16).ok()? as f64 / 255.0;
            Some((fmt_num(r), fmt_num(g), fmt_num(b)))
        }
        _ => None,
    }
}

fn escape_pdf_text(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('(', "\\(")
        .replace(')', "\\)")
}
