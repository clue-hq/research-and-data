use crate::raster::ScenePdfRenderer;
use crate::resolver::AssetByteResolver;
use crate::sidecar::build_sidecar;
use crate::svg::resolve_page_ids;
use lumen_core::{
    page_size_points, render_box_for_node, AssetKind, Diagnostic, DiagnosticSubject,
    ExportAdapter, ExportArtifact, ExportError, ExportFormat, ExportRequest, ExportResult, Node,
    NodeId, NodeKind, Page, PdfIntent, Phase, Rect, Scene,
};
use std::sync::Arc;

/// Raster density for flattened PDF pages when the export profile does not
/// request one — the BINDING B3 print default (300 dpi).
const DEFAULT_FLATTEN_DPI: u16 = 300;

#[derive(Clone, Debug, Default)]
pub struct PdfExportAdapter {
    renderer: Option<Arc<dyn ScenePdfRenderer>>,
    resolver: Option<Arc<dyn AssetByteResolver>>,
}

impl PdfExportAdapter {
    pub fn new() -> Self {
        Self::default()
    }

    /// Inject a scene PDF renderer (print W0 raster-flattened or W2 vector
    /// Skia-PDF). PDF export rides the same Skia paint as PNG — full
    /// fidelity by construction. Shaping happens inside the renderer, so no
    /// text measurer is threaded here.
    pub fn with_pdf_renderer(mut self, renderer: Arc<dyn ScenePdfRenderer>) -> Self {
        self.renderer = Some(renderer);
        self
    }

    /// Resolver handed to the injected renderer so image nodes embed real
    /// asset bytes.
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

        let Some(renderer) = self.renderer.clone() else {
            // D5 (2026-07-13): the early hand-rolled vector writer is gone —
            // it drew Helvetica-only text, no images, no gradients, no
            // effects, and survived only as a comparison baseline until the
            // Skia renderers burned in. An adapter without an injected
            // renderer is a composition bug, and it fails the same loud way
            // the PNG path does.
            return Err(ExportError::new(
                "export.pdf_renderer_missing",
                "PDF export requires a scene PDF renderer; compose one (e.g. lumen-skia's SkiaVectorPdfRenderer) via with_pdf_renderer",
            )
            .with_diagnostics(resolved.diagnostics));
        };
        self.export_via_renderer(scene, request, renderer.as_ref(), resolved)
    }
}

impl PdfExportAdapter {
    /// Pages render through the injected Skia-backed renderer (W0 flattened
    /// baseline / W2 vector default) — full fidelity by construction, same
    /// paint code as PNG. Each renderer declares its own mode (LUME0426
    /// raster-flattened, LUME0427 vector) in the diagnostics it returns.
    /// Print guardrails (safe area, bleed presence, pagination) are
    /// geometry checks independent of the paint path and run here.
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

        // Print W5 stage B: resolve the CMYK conversion target up front —
        // the print-intent gate, the Ghostscript binary, and the target
        // ICC all fail loudly here, before any rendering work. Electronic
        // (preview-intent) PDFs can never reach the conversion.
        let cmyk_target = crate::cmyk::cmyk_target_for(request)
            .map_err(|error| error.with_diagnostics(diagnostics.clone()))?;
        if let Some(target) = &cmyk_target {
            diagnostics.push(
                Diagnostic::advice(
                    Phase::Export,
                    "LUME0432",
                    format!(
                        "CMYK conversion (Ghostscript): colors separated for \"{}\"; black text and vector art preserved as pure K",
                        target.identifier
                    ),
                    Some(DiagnosticSubject::Document),
                )
                .with_hint("Pure #000 stays K-only (crisp on press). For a rich-black panel, author a near-black fill (e.g. #0a0a0f) so the ICC builds a CMYK mix. Set LUMEN_CMYK_ICC to your shop's profile (e.g. FOGRA39) for brand-critical work."),
            );
        }

        // Print W7: proof mode decorates every page with marks, a slug
        // line, and an sRGB control strip in a margin — a physical-proof
        // artifact, never a production file. Imposed sheets skip it in v1.
        let proof_label = (request.profile.proof && !booklet).then(|| {
            format!("{} · {}", scene.meta.title, request.profile.name)
        });
        if request.profile.proof {
            diagnostics.push(
                Diagnostic::advice(
                    Phase::Export,
                    "LUME0431",
                    if booklet {
                        "proof mode is not applied to imposed booklet sheets in v1; export reader-order pages for a slugged proof".to_owned()
                    } else {
                        "proof export: crop marks, slug line, and sRGB control strip drawn in the page margin — NOT for production runs".to_owned()
                    },
                    Some(DiagnosticSubject::Document),
                )
                .with_hint("Soft-proof on a calibrated display, then approve one physical proof on the actual stock before a bulk run (docs/print-proofing.md)."),
            );
        }

        let options = crate::raster::PdfRenderOptions {
            dpi,
            include_bleed: request.profile.include_bleed && !booklet,
            include_marks: request.profile.include_marks && !booklet,
            booklet,
            proof_label,
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
            // Margin is a PER-PAGE decision (marks need the page's bleed
            // rect; a mixed document gets different boxes per page) — the
            // same `print_margin_for_page` the renderer sizes its canvas
            // with, so painted and declared geometry agree by construction.
            page_ids
                .iter()
                .filter_map(|page_id| scene.pages.get(page_id))
                .map(|page| {
                    let margin = crate::pdf_boxes::print_margin_for_page(
                        page,
                        request.profile.include_bleed,
                        request.profile.include_marks,
                        request.profile.proof,
                    );
                    crate::pdf_boxes::page_boxes_with_margin(
                        page,
                        request.profile.include_bleed,
                        margin,
                    )
                })
                .collect()
        };

        // Tripwire: the canvas the renderer painted and the boxes we are
        // about to declare must describe the same page. A mismatch means
        // the two sides of the print-geometry contract diverged — that
        // file would carry a TrimBox cutting into the art (shipped live
        // 2026-07-15 as a phantom 14pt margin), so it is never emitted.
        if rendered.pages.len() != boxes.len() {
            return Err(ExportError::new(
                "export.pdf_geometry_mismatch",
                format!(
                    "renderer painted {} page(s) but {} box set(s) were computed",
                    rendered.pages.len(),
                    boxes.len()
                ),
            )
            .with_diagnostics(diagnostics.clone()));
        }
        for (rendered_page, page_boxes) in rendered.pages.iter().zip(&boxes) {
            let media_width = page_boxes.media[2] - page_boxes.media[0];
            let media_height = page_boxes.media[3] - page_boxes.media[1];
            if (f64::from(rendered_page.width_pt) - media_width).abs() > 0.01
                || (f64::from(rendered_page.height_pt) - media_height).abs() > 0.01
            {
                return Err(ExportError::new(
                    "export.pdf_geometry_mismatch",
                    format!(
                        "page {} painted at {:.2}x{:.2}pt but its MediaBox would declare {media_width:.2}x{media_height:.2}pt — renderer and box finalizer disagree on print geometry",
                        rendered_page.page_id, rendered_page.width_pt, rendered_page.height_pt
                    ),
                )
                .with_diagnostics(diagnostics.clone()));
            }
        }
        // W5 stage B: color conversion runs between render and finalize,
        // so the finalize pass owns the box/metadata contract on the
        // converted bytes (Ghostscript does not preserve either reliably)
        // and the OutputIntent names the press profile actually used.
        let rendered_bytes = match &cmyk_target {
            Some(target) => crate::cmyk::convert_pdf_to_cmyk(&rendered.bytes, target)
                .map_err(|error| error.with_diagnostics(diagnostics.clone()))?,
            None => rendered.bytes,
        };
        let pdfx = matches!(request.profile.pdf_intent, Some(PdfIntent::Print)).then(|| {
            crate::pdf_boxes::PdfxDeclarations {
                title: scene.meta.title.as_str(),
                cmyk: cmyk_target.as_ref(),
            }
        });
        let bytes = crate::pdf_boxes::finalize_print_pdf(&rendered_bytes, &boxes, pdfx).map_err(
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
        NodeKind::Text(_) => {}
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

