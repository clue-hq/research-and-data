use crate::raster::ScenePdfRenderer;
use crate::resolver::AssetByteResolver;
use crate::sidecar::build_sidecar;
use crate::svg::{fmt_num, measurer_as_dyn, resolve_page_ids, FALLBACK_MEASURER};
use lumen_core::{
    effect_support_diagnostics, page_size_points, paints_out_of_tree, pinned_paint_pass,
    render_box_for_node, unit_to_points, AssetKind, Diagnostic, DiagnosticSubject, ExportAdapter,
    ExportArtifact, ExportError, ExportFormat, ExportRequest, ExportResult, Node, NodeId, NodeKind,
    Page, Paint, PdfIntent, Phase, Rect, RenderTarget, Scene, SharedTextMeasurer, TextAlign,
    TextDirection, TextMeasureInput, TextMeasurer, valign_offset,
};
use std::sync::Arc;

/// Raster density for flattened PDF pages when the export profile does not
/// request one — the BINDING B3 print default (300 dpi).
const DEFAULT_FLATTEN_DPI: u16 = 300;

#[derive(Clone, Debug, Default)]
pub struct PdfExportAdapter {
    measurer: Option<SharedTextMeasurer>,
    renderer: Option<Arc<dyn ScenePdfRenderer>>,
    resolver: Option<Arc<dyn AssetByteResolver>>,
}

impl PdfExportAdapter {
    pub fn new() -> Self {
        Self::default()
    }

    /// Inject a shaping text measurer (Wave 1 Track A) so PDF overflow
    /// diagnostics and line layout agree with layout-engine measurement.
    pub fn with_measurer(mut self, measurer: SharedTextMeasurer) -> Self {
        self.measurer = Some(measurer);
        self
    }

    /// Inject a scene PDF renderer (print W0 raster-flattened or W2 vector
    /// Skia-PDF). PDF export then rides the same Skia paint as PNG — full
    /// fidelity by construction — instead of the early vector writer below.
    pub fn with_pdf_renderer(mut self, renderer: Arc<dyn ScenePdfRenderer>) -> Self {
        self.renderer = Some(renderer);
        self
    }

    /// Resolver handed to the injected renderer so image nodes embed real
    /// asset bytes (the early vector writer never draws images and ignores it).
    pub fn with_resolver(mut self, resolver: Arc<dyn AssetByteResolver>) -> Self {
        self.resolver = Some(resolver);
        self
    }
}

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

        if let Some(renderer) = self.renderer.clone() {
            return self.export_via_renderer(scene, request, renderer.as_ref(), resolved);
        }

        let mut diagnostics = resolved.diagnostics;
        // LUMS0102: no shaping measurer injected (or a non-shaping one), so PDF
        // line layout is geometry-approximate. Emitted once per export; server
        // paths inject SkiaTextMeasurer and never reach this branch.
        if !self
            .measurer
            .as_deref()
            .is_some_and(|measurer| measurer.shaping())
        {
            diagnostics.push(lumen_core::heuristic_measurement_diagnostic());
        }
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
        // Renderer support matrix (Effects Contract V0 Decision 4): PDF is
        // solid-paint-only, so every non-native effect feature in use gets
        // an explicit LUMX verdict before the per-node fallback warnings.
        diagnostics.extend(effect_support_diagnostics(
            scene,
            &page_ids,
            &RenderTarget::Pdf,
        ));
        diagnostics.extend(print_document_guardrails(scene, &page_ids, request));
        for page_id in &page_ids {
            let Some(page) = scene.pages.get(page_id) else {
                continue;
            };
            diagnostics.extend(print_page_guardrails(scene, page, request));
            let page_box = PdfPageBox::for_page(page, request.profile.include_bleed);
            let mut renderer = PdfPageRenderer::new(
                scene,
                page,
                page_box,
                self.measurer.as_deref().map(measurer_as_dyn),
            );
            let stream = renderer.render_page();
            diagnostics.extend(renderer.diagnostics);
            writer.add_page(page_box, stream);
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
            print_ready: None,
        })
    }
}

impl PdfExportAdapter {
    /// Seam path (print W0 flattened / W2 vector): pages render through the
    /// injected Skia-backed renderer — full fidelity by construction, same
    /// paint code as PNG. The early vector writer's fidelity warnings
    /// (LUME0401/0402) and its PDF-target feature-drop verdicts do not apply;
    /// each renderer declares its own mode (LUME0426 raster-flattened,
    /// LUME0427 vector) in the diagnostics it returns. Print guardrails
    /// (safe area, bleed presence, pagination) are geometry checks
    /// independent of the paint path and still run here.
    fn export_via_renderer(
        &self,
        scene: &Scene,
        request: &ExportRequest,
        renderer: &dyn ScenePdfRenderer,
        resolved: crate::svg::PageResolution,
    ) -> Result<ExportResult, ExportError> {
        let mut diagnostics = resolved.diagnostics;
        let page_ids = resolved.page_ids;

        diagnostics.extend(print_document_guardrails(scene, &page_ids, request));
        for page_id in &page_ids {
            if let Some(page) = scene.pages.get(page_id) {
                diagnostics.extend(print_page_guardrails(scene, page, request));
            }
        }

        // The profile's raster block is authoritative when present (its
        // `scale` is a pixel-density concept with no meaning for fixed
        // point-sized PDF pages and is ignored; only dpi applies — raster
        // density for the flattened renderer, effect-rasterization density
        // for the vector one).
        let dpi = request
            .profile
            .raster
            .as_ref()
            .and_then(|raster| raster.dpi)
            .unwrap_or(DEFAULT_FLATTEN_DPI);

        // Print W4 (D2): reader-order pages are the default deliverable;
        // "booklet" is the one recognized imposition mode. Unknown modes
        // fail loudly — never a silently different arrangement.
        let booklet = match request.profile.imposition.as_deref() {
            None => false,
            Some("booklet") => true,
            Some(other) => {
                return Err(ExportError::new(
                    "export.imposition_unknown",
                    format!("unknown imposition mode {other:?}; supported: \"booklet\""),
                )
                .with_diagnostics(diagnostics));
            }
        };
        if booklet {
            diagnostics.extend(booklet_scope_diagnostics(scene, &page_ids, request)?);
        }

        let options = crate::raster::PdfRenderOptions {
            dpi,
            include_bleed: request.profile.include_bleed && !booklet,
            include_marks: request.profile.include_marks && !booklet,
            booklet,
        };
        let rendered = renderer
            .render_pdf(scene, &page_ids, &options, self.resolver.as_deref())
            .map_err(|error| {
                ExportError::new(error.code, error.message).with_diagnostics(diagnostics.clone())
            })?;
        diagnostics.extend(rendered.diagnostics);

        // L3: rewrite every page's MediaBox/TrimBox/BleedBox to the exact
        // scene geometry — the renderers only write a (dpi-grid-quantized)
        // MediaBox. The box set is what the shop's cutter reads; failing to
        // write it is a failed export, never a silent omission. Print
        // intent additionally gets the PDF/X-4 declaration set (sRGB
        // OutputIntent, XMP version claim, Trapped, deterministic dates).
        // Imposed sheets don't map to scene pages: their exact geometry is
        // the renderer's per-sheet accounting (trim = bleed = sheet).
        let boxes: Vec<crate::pdf_boxes::PageBoxes> = if booklet {
            rendered
                .pages
                .iter()
                .map(|sheet| {
                    let media = [0.0, 0.0, f64::from(sheet.width_pt), f64::from(sheet.height_pt)];
                    crate::pdf_boxes::PageBoxes {
                        media,
                        trim: media,
                        bleed: media,
                    }
                })
                .collect()
        } else {
            let marks_margin = crate::pdf_boxes::marks_margin_pt(request);
            page_ids
                .iter()
                .filter_map(|page_id| scene.pages.get(page_id))
                .map(|page| {
                    crate::pdf_boxes::page_boxes_with_margin(
                        page,
                        request.profile.include_bleed,
                        marks_margin,
                    )
                })
                .collect()
        };
        let pdfx = matches!(request.profile.pdf_intent, Some(PdfIntent::Print));
        let bytes = crate::pdf_boxes::finalize_print_pdf(&rendered.bytes, &boxes, pdfx).map_err(
            |message| {
                ExportError::new("export.pdf_boxes_failed", message)
                    .with_diagnostics(diagnostics.clone())
            },
        )?;

        let sidecar = build_sidecar(scene, &page_ids, &request.profile.name);
        let sidecar_json = serde_json::to_string_pretty(&sidecar).ok();

        // W6/L4: print-intent exports carry the structured preflight
        // verdict; the bulk path hard-fails on it, the editor and agent
        // loop surface it.
        let print_ready = crate::print_ready::is_print_ready_scope(request).then(|| {
            crate::print_ready::print_ready_report(scene, &page_ids, request, &diagnostics)
        });

        Ok(ExportResult {
            artifacts: vec![ExportArtifact {
                format: ExportFormat::Pdf,
                page_id: None,
                asset_id: None,
                mime_type: "application/pdf".to_owned(),
                bytes,
                sidecar_json,
            }],
            diagnostics,
            print_ready,
        })
    }
}

/// Print W4: booklet-scoped validation + declarations. Imposition needs a
/// uniform trim size (a folded stack with mixed leaf sizes is nonsense —
/// hard error), and v1 deliberately renders trim-only sheets (no bleed, no
/// marks, creep 0) — declared, never silent.
fn booklet_scope_diagnostics(
    scene: &Scene,
    page_ids: &[lumen_core::PageId],
    request: &ExportRequest,
) -> Result<Vec<Diagnostic>, ExportError> {
    let pages: Vec<&Page> = page_ids
        .iter()
        .filter_map(|page_id| scene.pages.get(page_id))
        .collect();
    if let Some(first) = pages.first() {
        let (first_width, first_height) = page_size_points(first);
        for page in pages.iter().skip(1) {
            let (width, height) = page_size_points(page);
            if (width - first_width).abs() > f64::EPSILON
                || (height - first_height).abs() > f64::EPSILON
            {
                return Err(ExportError::new(
                    "export.imposition_mixed_sizes",
                    format!(
                        "booklet imposition requires one uniform trim size; page {} is {width:.2}x{height:.2}pt but page {} is {first_width:.2}x{first_height:.2}pt",
                        page.id, first.id
                    ),
                ));
            }
        }
    }

    let (sides, padding) = crate::imposition::booklet_sheet_sides(page_ids.len());
    let mut diagnostics = vec![Diagnostic::advice(
        Phase::Export,
        "LUME0428",
        format!(
            "booklet imposition: {} reader page(s){} arranged onto {} duplex sheet side(s), 2-up saddle-stitch (front [N|1], back [2|N-1]); print duplex, turning the sheet about its vertical axis, then fold and stitch",
            page_ids.len(),
            if padding > 0 {
                format!(" (+{padding} trailing blank(s) to reach a multiple of 4)")
            } else {
                String::new()
            },
            sides.len(),
        ),
        Some(DiagnosticSubject::Document),
    )];
    if request.profile.include_bleed || request.profile.include_marks {
        diagnostics.push(
            Diagnostic::advice(
                Phase::Export,
                "LUME0430",
                "booklet v1 imposes trim-only sheets: per-page bleed and crop marks are skipped (self-print fold workflow); creep is 0",
                Some(DiagnosticSubject::Document),
            )
            .with_hint("For shop-cut output with bleed and marks, export reader-order pages instead — most shops impose themselves (D2)."),
        );
    }
    Ok(diagnostics)
}

struct PdfPageRenderer<'a> {
    scene: &'a Scene,
    page: &'a Page,
    page_box: PdfPageBox,
    scale: f64,
    page_height: f64,
    measurer: &'a dyn TextMeasurer,
    stream: String,
    diagnostics: Vec<Diagnostic>,
}

enum PaintResult<'a> {
    Applied,
    Unsupported,
    Token(&'a str),
}

impl<'a> PdfPageRenderer<'a> {
    fn new(
        scene: &'a Scene,
        page: &'a Page,
        page_box: PdfPageBox,
        measurer: Option<&'a dyn TextMeasurer>,
    ) -> Self {
        let scale = unit_to_points(1.0, &page.size.unit);
        Self {
            scene,
            page,
            page_box,
            scale,
            page_height: page_box.height * scale,
            measurer: measurer.unwrap_or(&FALLBACK_MEASURER),
            stream: String::new(),
            diagnostics: Vec::new(),
        }
    }

    fn render_page(&mut self) -> String {
        self.draw_page_background();
        for child_id in &self.page.children {
            if self.skips_inline_render(child_id) {
                continue;
            }
            self.render_node(child_id, 0.0, 0.0, None);
        }
        // Phase 1d freehand: pinned nodes paint in a page-level pass above
        // the in-flow content, mirroring the Skia and SVG renderers' z
        // order (vector PDF never masks, so only stacking parity matters).
        for node_id in pinned_paint_pass(self.scene, self.page) {
            self.render_node(&node_id, 0.0, 0.0, None);
        }
        self.stream.clone()
    }

    /// Pinned nodes never render inside their parent's tree — see
    /// [`pinned_paint_pass`].
    fn skips_inline_render(&self, node_id: &NodeId) -> bool {
        self.scene
            .nodes
            .get(node_id)
            .is_some_and(paints_out_of_tree)
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
                    if self.skips_inline_render(child_id) {
                        continue;
                    }
                    self.render_node(child_id, x, y, child_parent_origin);
                }
            }
            NodeKind::Rect => self.draw_rect(node, x, y, width, height),
            NodeKind::Ellipse => self.warn_unsupported(node, "ellipse"),
            NodeKind::Line(line) => {
                if self.apply_stroke(node) {
                    self.stream.push_str(&format!(
                        "{} {} m {} {} l S\n",
                        fmt_num(self.pdf_x(x)),
                        fmt_num(self.pdf_y(y)),
                        fmt_num(self.pdf_x(x + line.x2)),
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
                // A6a D2/D5: PDF V0 renders neither text decoration nor text
                // strokes, and paints the first fill only — degrade LOUDLY
                // rather than silently, matching the SVG/Skia doctrine. (The D1
                // case transform and D3/D4 ellipsis + paragraph spacing ride the
                // measured lines PDF already consumes, so they need no advisory.)
                if text.underline || text.strikethrough {
                    self.diagnostics.push(
                        Diagnostic::warning(
                            Phase::Export,
                            "LUME0421",
                            format!(
                                "text node {} requests underline/strikethrough; PDF export does not render text decoration",
                                node.id
                            ),
                            Some(DiagnosticSubject::Node(node.id.clone())),
                        )
                        .with_hint("Export through SVG/PNG for text decoration, or remove it for PDF."),
                    );
                }
                if !node.strokes.is_empty() {
                    self.diagnostics.push(
                        Diagnostic::warning(
                            Phase::Export,
                            "LUME0422",
                            format!(
                                "text node {} has a text stroke; PDF export does not render text strokes",
                                node.id
                            ),
                            Some(DiagnosticSubject::Node(node.id.clone())),
                        )
                        .with_hint("Export through SVG/PNG for text strokes, or remove the stroke for PDF."),
                    );
                }
                if node.fills.len() > 1 {
                    self.diagnostics.push(
                        Diagnostic::advice(
                            Phase::Export,
                            "LUME0423",
                            format!(
                                "text node {} has multiple fills; PDF export renders the first fill only for text",
                                node.id
                            ),
                            Some(DiagnosticSubject::Node(node.id.clone())),
                        )
                        .with_hint("Stacked text fills are out of scope for PDF; use a single text fill."),
                    );
                }
                // A6b D7: PDF renders base text only — spans (per-run fill /
                // weight / decoration) are not represented. The text content
                // renders complete; only the span styling is dropped, loudly.
                if !text.spans.is_empty() {
                    self.diagnostics.push(
                        Diagnostic::warning(
                            Phase::Export,
                            "LUME0424",
                            format!(
                                "text node {} has rich-text spans; PDF export renders the text without per-span styling",
                                node.id
                            ),
                            Some(DiagnosticSubject::Node(node.id.clone())),
                        )
                        .with_hint("Export through SVG/PNG for two-color / weighted spans; PDF renders the full text in the base style."),
                    );
                }
                // A7b D6: PDF has no font differentiation (single /F1 Helvetica),
                // so italic — block-level OR any span override — cannot be
                // represented. Sibling of LUME0424: the text renders complete but
                // upright, loudly, never a silent divergence from SVG/PNG.
                // Fires when the node requests italic anywhere: block-level,
                // or any span(italic(true)). A span(italic(false)) on an
                // upright block resolves fully upright — exactly what PDF
                // produces — so it must not warn. Known accepted over-fire: a
                // block-italic node whose spans de-italicize EVERY byte also
                // resolves upright but still warns (a harmless advisory in a
                // pathological authoring case; full coverage analysis is not
                // worth the complexity).
                let has_italic = text.italic
                    || text.spans.iter().any(|span| span.italic == Some(true));
                if has_italic {
                    self.diagnostics.push(
                        Diagnostic::warning(
                            Phase::Export,
                            "LUME0425",
                            format!(
                                "text node {} is italic; PDF export renders it upright (no italic face in the PDF font model)",
                                node.id
                            ),
                            Some(DiagnosticSubject::Node(node.id.clone())),
                        )
                        .with_hint("Export through SVG/PNG for italic text; PDF renders the full text upright in the base style."),
                    );
                }
                let measured =
                    self.measurer
                        .measure(&TextMeasureInput::from_text_node(text).with_bounds(&Rect {
                            x: 0.0,
                            y: 0.0,
                            width,
                            height,
                        }));
                // R1 (audit fold): surface measurement-time font diagnostics
                // (LUMS0100/0103/0104) on direct PDF exports too.
                for diagnostic in &measured.diagnostics {
                    let diagnostic = Diagnostic {
                        subject: Some(DiagnosticSubject::Node(node.id.clone())),
                        ..diagnostic.clone()
                    };
                    if !self.diagnostics.contains(&diagnostic) {
                        self.diagnostics.push(diagnostic);
                    }
                }
                if measured.overflow_x || measured.overflow_y || measured.exceeds_max_lines {
                    self.diagnostics.push(
                        Diagnostic::warning(
                            Phase::Export,
                            "LUME0418",
                            format!(
                                "PDF text node {} overflows its render box ({})",
                                node.id,
                                text_overflow_reason(
                                    measured.overflow_x,
                                    measured.overflow_y,
                                    measured.exceeds_max_lines
                                )
                            ),
                            Some(DiagnosticSubject::Node(node.id.clone())),
                        )
                        .with_hint("Resize the text frame, reduce copy/font size, or run layout/text-fit repair before approving PDF output."),
                    );
                }
                // A7a: clamped vertical slack added in top-down page space
                // BEFORE the pdf_y axis flip (same measured total + formula the
                // raster/SVG paths use).
                let valign_shift = valign_offset(height, measured.height, text.valign);
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
                        fmt_num(self.pdf_x(text_x)),
                        fmt_num(self.pdf_y(y + valign_shift + line.baseline)),
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
                    fmt_num(self.page_box.width * self.scale),
                    fmt_num(self.page_box.height * self.scale)
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
                fmt_num(self.pdf_x(x)),
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
        self.page_height - ((y - self.page_box.y) * self.scale)
    }

    fn pdf_x(&self, x: f64) -> f64 {
        (x - self.page_box.x) * self.scale
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

    fn add_page(&mut self, page_box: PdfPageBox, stream: String) {
        self.pages.push((
            page_box.width * page_box.scale,
            page_box.height * page_box.scale,
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

#[derive(Clone, Copy, Debug)]
struct PdfPageBox {
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    scale: f64,
}

impl PdfPageBox {
    fn for_page(page: &Page, include_bleed: bool) -> Self {
        let scale = unit_to_points(1.0, &page.size.unit);
        let rect = if include_bleed {
            page.bleed.clone().unwrap_or(Rect {
                x: 0.0,
                y: 0.0,
                width: page.size.width,
                height: page.size.height,
            })
        } else {
            Rect {
                x: 0.0,
                y: 0.0,
                width: page.size.width,
                height: page.size.height,
            }
        };

        Self {
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
            scale,
        }
    }
}

fn print_document_guardrails(
    scene: &Scene,
    page_ids: &[lumen_core::PageId],
    request: &ExportRequest,
) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    if !matches!(request.profile.pdf_intent, Some(PdfIntent::Print)) {
        return diagnostics;
    }

    let pages = page_ids
        .iter()
        .filter_map(|page_id| scene.pages.get(page_id))
        .collect::<Vec<_>>();

    if pages.len() > 1 {
        diagnostics.push(
            Diagnostic::warning(
                Phase::Export,
                "LUME0419",
                format!(
                    "print PDF export contains {} explicit pages; automatic flowed pagination is not performed",
                    pages.len()
                ),
                Some(DiagnosticSubject::Document),
            )
            .with_hint("Review each page/artboard explicitly before print handoff; split or paginate flowed content upstream."),
        );
    }

    if let Some(first_page) = pages.first() {
        let has_mixed_sizes = pages
            .iter()
            .skip(1)
            .any(|page| !same_page_size(first_page, page));

        if has_mixed_sizes {
            diagnostics.push(
                Diagnostic::warning(
                    Phase::Export,
                    "LUME0420",
                    "print PDF export contains mixed page sizes".to_owned(),
                    Some(DiagnosticSubject::Document),
                )
                .with_hint("Many print handoffs expect a consistent trim size; verify mixed custom artboards before approving the PDF."),
            );
        }
    }

    diagnostics
}

fn print_page_guardrails(scene: &Scene, page: &Page, request: &ExportRequest) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    let is_print_pdf = matches!(request.profile.pdf_intent, Some(PdfIntent::Print));

    if is_print_pdf && page.safe_area.is_none() {
        diagnostics.push(
            Diagnostic::warning(
                Phase::Export,
                "LUME0411",
                format!(
                    "print PDF export requested page {} but the page has no safe area",
                    page.id
                ),
                Some(DiagnosticSubject::Page(page.id.clone())),
            )
            .with_hint("Set page.safe_area before treating print output as production-ready."),
        );
    }

    if request.profile.include_bleed && page.bleed.is_none() {
        diagnostics.push(
            Diagnostic::warning(
                Phase::Export,
                "LUME0412",
                format!(
                    "export profile includes bleed but page {} has no bleed rect",
                    page.id
                ),
                Some(DiagnosticSubject::Page(page.id.clone())),
            )
            .with_hint("Set page.bleed to expand the print PDF MediaBox beyond the trim size."),
        );
    }

    if is_print_pdf {
        for child_id in &page.children {
            collect_print_node_guardrails(scene, child_id, &mut diagnostics);
        }
        if let Some(safe_area) = &page.safe_area {
            collect_required_slot_safe_area_guardrails(scene, page, safe_area, &mut diagnostics);
        }
    }

    diagnostics
}

fn same_page_size(left: &Page, right: &Page) -> bool {
    let (left_width, left_height) = page_size_points(left);
    let (right_width, right_height) = page_size_points(right);
    (left_width - right_width).abs() <= f64::EPSILON
        && (left_height - right_height).abs() <= f64::EPSILON
}

fn collect_required_slot_safe_area_guardrails(
    scene: &Scene,
    page: &Page,
    safe_area: &Rect,
    diagnostics: &mut Vec<Diagnostic>,
) {
    for slot in scene.slots.values().filter(|slot| slot.required) {
        for node_id in &slot.bound_nodes {
            let Some(bounds) = absolute_render_box_for_page_node(scene, page, node_id) else {
                continue;
            };
            if !rect_contains(safe_area, &bounds) {
                diagnostics.push(
                    Diagnostic::warning(
                        Phase::Export,
                        "LUME0417",
                        format!(
                            "required slot {} node {} falls outside page {} safe area for print PDF export",
                            slot.key, node_id, page.id
                        ),
                        Some(DiagnosticSubject::Slot(slot.id.clone())),
                    )
                    .with_hint("Move the slotted node inside page.safe_area before treating print output as production-ready."),
                );
            }
        }
    }
}

fn absolute_render_box_for_page_node(scene: &Scene, page: &Page, target: &NodeId) -> Option<Rect> {
    for child_id in &page.children {
        if let Some(bounds) = absolute_render_box_for_node(scene, child_id, target, 0.0, 0.0, None)
        {
            return Some(bounds);
        }
    }
    None
}

fn absolute_render_box_for_node(
    scene: &Scene,
    node_id: &NodeId,
    target: &NodeId,
    parent_x: f64,
    parent_y: f64,
    parent_computed_origin: Option<(f64, f64)>,
) -> Option<Rect> {
    let node = scene.nodes.get(node_id)?;
    let render_box = render_box_for_node(node, parent_computed_origin);
    let (x, y) = absolute_xy(
        node,
        parent_x,
        parent_y,
        render_box.x,
        render_box.y,
        parent_computed_origin,
    );
    let bounds = Rect {
        x,
        y,
        width: render_box.width,
        height: render_box.height,
    };
    if node_id == target {
        return Some(bounds);
    }

    let child_parent_origin = node
        .computed
        .as_ref()
        .map(|computed| (computed.layout_bounds.x, computed.layout_bounds.y));
    for child_id in &node.children {
        if let Some(child_bounds) =
            absolute_render_box_for_node(scene, child_id, target, x, y, child_parent_origin)
        {
            return Some(child_bounds);
        }
    }
    None
}

fn rect_contains(container: &Rect, child: &Rect) -> bool {
    child.x >= container.x
        && child.y >= container.y
        && child.x + child.width <= container.x + container.width
        && child.y + child.height <= container.y + container.height
}

fn collect_print_node_guardrails(
    scene: &Scene,
    node_id: &NodeId,
    diagnostics: &mut Vec<Diagnostic>,
) {
    let Some(node) = scene.nodes.get(node_id) else {
        return;
    };

    match &node.kind {
        NodeKind::Text(text) => {
            if text.direction != TextDirection::Ltr {
                diagnostics.push(
                    Diagnostic::warning(
                        Phase::Export,
                        "LUME0413",
                        format!(
                            "print PDF text node {} uses {:?} direction, but early PDF export does not support bidi shaping",
                            node.id, text.direction
                        ),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    )
                    .with_hint("Use the text-shaping/font track before treating RTL/bidi PDF output as final."),
                );
            }
            if contains_non_latin_letters(&text.content) {
                diagnostics.push(
                    Diagnostic::warning(
                        Phase::Export,
                        "LUME0414",
                        format!(
                            "print PDF text node {} contains non-Latin text, but early PDF export uses built-in Latin PDF fonts",
                            node.id
                        ),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    )
                    .with_hint("Use the text-shaping/font track for non-Latin glyph coverage and embedding."),
                );
            }
        }
        NodeKind::Image(image) => {
            let Some(asset) = scene.assets.get(&image.asset_id) else {
                diagnostics.push(
                    Diagnostic::warning(
                        Phase::Export,
                        "LUME0415",
                        format!(
                            "print PDF image node {} references asset {} but asset metadata is missing",
                            node.id, image.asset_id
                        ),
                        Some(DiagnosticSubject::Node(node.id.clone())),
                    )
                    .with_hint("Attach asset metadata with DPI before treating print output as production-ready."),
                );
                return;
            };

            if matches!(asset.kind, AssetKind::RasterImage | AssetKind::Logo) {
                match asset.min_dpi() {
                    Some(dpi) if dpi < 300.0 => diagnostics.push(
                        Diagnostic::warning(
                            Phase::Export,
                            "LUME0416",
                            format!(
                                "print PDF image node {} uses asset {} at {:.0} DPI; 300 DPI is recommended for print",
                                node.id, image.asset_id, dpi
                            ),
                            Some(DiagnosticSubject::Asset(image.asset_id.clone())),
                        )
                        .with_hint("Use a higher-resolution image asset for print export."),
                    ),
                    None => diagnostics.push(
                        Diagnostic::warning(
                            Phase::Export,
                            "LUME0415",
                            format!(
                                "print PDF image node {} uses asset {} without DPI metadata",
                                node.id, image.asset_id
                            ),
                            Some(DiagnosticSubject::Asset(image.asset_id.clone())),
                        )
                        .with_hint("Probe image DPI before treating print output as production-ready."),
                    ),
                    Some(_) => {}
                }
            }
        }
        _ => {}
    }

    for child_id in &node.children {
        collect_print_node_guardrails(scene, child_id, diagnostics);
    }
}

fn contains_non_latin_letters(value: &str) -> bool {
    value.chars().any(|ch| ch.is_alphabetic() && !ch.is_ascii())
}

fn text_overflow_reason(overflow_x: bool, overflow_y: bool, exceeds_max_lines: bool) -> String {
    let mut reasons = Vec::new();
    if overflow_x {
        reasons.push("width");
    }
    if overflow_y {
        reasons.push("height");
    }
    if exceeds_max_lines {
        reasons.push("max lines");
    }
    reasons.join(", ")
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
