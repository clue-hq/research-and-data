//! Export-time asset checks: licensing enforcement, effective print DPI,
//! and logo safe-area rules (Phase E slice E6, Decision 5).
//!
//! Licensing is recorded at ingest and enforced here: print/publish
//! exports (user download, bulk render, or an explicit print intent)
//! fail with LUME0212 when an embedded asset's license forbids export;
//! agent-critique previews degrade the same finding to a warning so the
//! critic can see and report it without blocking iteration.

use lumen_core::{
    render_box_for_node, AssetRecord, Diagnostic, DiagnosticSubject, ExportPurpose, ExportRequest,
    Node, NodeId, NodeKind, Page, PdfIntent, Phase, Scene, Unit,
};

/// Effective DPI below this threshold on a print export is flagged.
pub const MIN_EFFECTIVE_PRINT_DPI: f64 = 150.0;
const CSS_PX_PER_INCH: f64 = 96.0;
const MM_PER_INCH: f64 = 25.4;

/// Run asset export checks over every page in the request scope.
/// Returns diagnostics; LUME0212 entries are errors when the request is
/// enforced (print/publish) and warnings otherwise.
pub fn asset_export_checks(
    scene: &Scene,
    request: &ExportRequest,
    page_ids: &[lumen_core::PageId],
) -> Vec<Diagnostic> {
    let mut diagnostics = Vec::new();
    for page_id in page_ids {
        let Some(page) = scene.pages.get(page_id) else {
            continue;
        };
        let mut walker = CheckWalker {
            scene,
            page,
            request,
            enforce_license: license_enforced(request),
            print_intent: is_print_intent(request),
            diagnostics: &mut diagnostics,
        };
        for child_id in &page.children {
            walker.walk(child_id, (0.0, 0.0), None);
        }
    }
    diagnostics
}

/// Whether the request must reject license-forbidden assets (Decision 5):
/// user-facing and bulk outputs are enforced; agent critique and Figma
/// round-trips surface warnings instead.
pub fn license_enforced(request: &ExportRequest) -> bool {
    matches!(
        request.purpose,
        ExportPurpose::UserDownload | ExportPurpose::BulkRender
    ) || is_print_intent(request)
}

fn is_print_intent(request: &ExportRequest) -> bool {
    matches!(request.profile.pdf_intent, Some(PdfIntent::Print))
}

struct CheckWalker<'a> {
    scene: &'a Scene,
    page: &'a Page,
    request: &'a ExportRequest,
    enforce_license: bool,
    print_intent: bool,
    diagnostics: &'a mut Vec<Diagnostic>,
}

impl CheckWalker<'_> {
    fn walk(
        &mut self,
        node_id: &NodeId,
        parent_abs: (f64, f64),
        parent_computed_origin: Option<(f64, f64)>,
    ) {
        let Some(node) = self.scene.nodes.get(node_id) else {
            return;
        };
        let render_box = render_box_for_node(node, parent_computed_origin);
        let abs_x = parent_abs.0 + render_box.x;
        let abs_y = parent_abs.1 + render_box.y;

        if let Some(record) = node_asset_record(self.scene, node) {
            self.check_license(node, record);
            if self.print_intent {
                self.check_effective_dpi(node, record, render_box.width);
            }
            self.check_logo_safe_area(
                node,
                record,
                abs_x,
                abs_y,
                render_box.width,
                render_box.height,
            );
        }

        let child_origin = node
            .computed
            .as_ref()
            .map(|computed| (computed.layout_bounds.x, computed.layout_bounds.y));
        for child_id in &node.children {
            self.walk(child_id, (abs_x, abs_y), child_origin);
        }
    }

    fn check_license(&mut self, node: &Node, record: &AssetRecord) {
        if record.allows_export() {
            return;
        }
        let license_name = record
            .license
            .as_ref()
            .map(|license| license.name.as_str())
            .unwrap_or("unknown");
        let message = format!(
            "node {} embeds asset {} whose license {:?} forbids export (profile {}, purpose {:?})",
            node.id, record.id, license_name, self.request.profile.name, self.request.purpose
        );
        let diagnostic = if self.enforce_license {
            Diagnostic::error(
                Phase::Export,
                "LUME0212",
                message,
                Some(DiagnosticSubject::Asset(record.id.clone())),
            )
            .with_hint("Replace the asset or obtain an export-permitting license before print/publish export.")
        } else {
            Diagnostic::warning(
                Phase::Export,
                "LUME0212",
                message,
                Some(DiagnosticSubject::Asset(record.id.clone())),
            )
            .with_hint("This preview is allowed, but a print/publish export of this document will be rejected.")
        };
        self.diagnostics.push(diagnostic);
    }

    fn check_effective_dpi(&mut self, node: &Node, record: &AssetRecord, rendered_width: f64) {
        let Some(raster) = &record.raster else {
            return;
        };
        if raster.pixel_width == 0 || rendered_width <= 0.0 {
            return;
        }
        let rendered_inches = match self.page.size.unit {
            Unit::Mm => rendered_width / MM_PER_INCH,
            Unit::In => rendered_width,
            Unit::Px => rendered_width / CSS_PX_PER_INCH,
        };
        if rendered_inches <= 0.0 {
            return;
        }
        let effective_dpi = f64::from(raster.pixel_width) / rendered_inches;
        if effective_dpi < MIN_EFFECTIVE_PRINT_DPI {
            self.diagnostics.push(
                Diagnostic::warning(
                    Phase::Export,
                    "LUME0220",
                    format!(
                        "node {} renders asset {} at {:.0} effective DPI on a print export ({} px over {:.1}{} ); at least {:.0} DPI is expected",
                        node.id,
                        record.id,
                        effective_dpi,
                        raster.pixel_width,
                        rendered_width,
                        unit_suffix(self.page.size.unit.clone()),
                        MIN_EFFECTIVE_PRINT_DPI,
                    ),
                    Some(DiagnosticSubject::Asset(record.id.clone())),
                )
                .with_hint("Use a higher-resolution asset or render it smaller for print."),
            );
        }
    }

    fn check_logo_safe_area(
        &mut self,
        node: &Node,
        record: &AssetRecord,
        abs_x: f64,
        abs_y: f64,
        width: f64,
        height: f64,
    ) {
        if !matches!(record.kind, lumen_core::AssetKind::Logo) {
            return;
        }
        let clearspace = record
            .logo
            .as_ref()
            .and_then(|logo| logo.clearspace)
            .unwrap_or(0.0);
        let (bound_x, bound_y, bound_w, bound_h) = match &self.page.safe_area {
            Some(area) => (area.x, area.y, area.width, area.height),
            None => (0.0, 0.0, self.page.size.width, self.page.size.height),
        };
        let fits = abs_x - clearspace >= bound_x
            && abs_y - clearspace >= bound_y
            && abs_x + width + clearspace <= bound_x + bound_w
            && abs_y + height + clearspace <= bound_y + bound_h;
        if !fits {
            let bound_label = if self.page.safe_area.is_some() {
                "safe area"
            } else {
                "page bounds"
            };
            self.diagnostics.push(
                Diagnostic::warning(
                    Phase::Export,
                    "LUME0221",
                    format!(
                        "logo node {} (asset {}) violates the {} of page {}{}",
                        node.id,
                        record.id,
                        bound_label,
                        self.page.id,
                        if clearspace > 0.0 {
                            format!(" including its {clearspace} clearspace requirement")
                        } else {
                            String::new()
                        }
                    ),
                    Some(DiagnosticSubject::Node(node.id.clone())),
                )
                .with_hint(
                    "Move or shrink the logo so it and its clearspace sit inside the safe area.",
                ),
            );
        }
    }
}

fn unit_suffix(unit: Unit) -> &'static str {
    match unit {
        Unit::Px => "px",
        Unit::Mm => "mm",
        Unit::In => "in",
    }
}

fn node_asset_record<'a>(scene: &'a Scene, node: &Node) -> Option<&'a AssetRecord> {
    let asset_id = match &node.kind {
        NodeKind::Image(image) => Some(&image.asset_id),
        _ => node.source_asset_id.as_ref(),
    }?;
    scene.assets.get(asset_id)
}
