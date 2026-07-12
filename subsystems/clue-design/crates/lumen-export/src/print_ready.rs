//! Print W6: the "print-ready-v1" preflight ruleset — chain link L4.
//!
//! Runs on every print-intent PDF export and returns a structured
//! [`PrintReadyReport`] in the export result: the editor surfaces it, the
//! agent loop reads it, and the bulk instance-export path HARD-FAILS on a
//! "fail" status — one bad page fails loudly instead of printing 400
//! white-edged brochures.
//!
//! Geometry rules are computed here; render/asset findings (font
//! fallbacks, dropped features, license, low PPI) are folded in from the
//! diagnostics the render pass already produced, so the report never
//! re-derives what the pipeline already knows.

use lumen_core::{
    render_box_for_node, Diagnostic, ExportRequest, Node, NodeId, NodeKind, Page, PdfIntent,
    PrintReadyReport, PrintReadyRule, Rect, Scene,
};

/// Distance (layout units ≈ pt) within which an art edge counts as
/// "touching" the trim edge, and therefore must extend to the bleed line.
const TRIM_TOUCH_EPSILON: f64 = 0.75;
/// Slack allowed when testing whether touching art reaches the bleed line.
const BLEED_REACH_EPSILON: f64 = 0.25;

const PASS: &str = "pass";
const WARN: &str = "warn";
const FAIL: &str = "fail";

pub fn is_print_ready_scope(request: &ExportRequest) -> bool {
    matches!(request.profile.pdf_intent, Some(PdfIntent::Print))
}

/// Build the print-ready-v1 report for a print-intent PDF export.
/// `collected` is every diagnostic the export pass produced so far
/// (guardrails, renderer, asset checks).
pub fn print_ready_report(
    scene: &Scene,
    page_ids: &[lumen_core::PageId],
    request: &ExportRequest,
    collected: &[Diagnostic],
) -> PrintReadyReport {
    let pages: Vec<&Page> = page_ids
        .iter()
        .filter_map(|page_id| scene.pages.get(page_id))
        .collect();

    let mut rules = vec![
        bleed_present_rule(&pages, request),
        edge_art_rule(scene, &pages),
        text_safe_area_rule(scene, &pages),
        geometry_consistent_rule(collected),
        diagnostics_rule(
            "fonts_resolved",
            collected,
            &["LUMS0100", "LUMS0101", "LUMS0104", "LUMS0105"],
            WARN,
            "every text family/weight resolved to a real face",
            "text fell back to a substitute face — print typography will not match the design",
        ),
        diagnostics_rule(
            "image_resolution",
            collected,
            &["LUME0220"],
            WARN,
            "all raster assets meet the print resolution floor",
            "raster assets render below the print PPI floor",
        ),
        diagnostics_rule(
            "no_feature_drops",
            collected,
            &["LUMX0002"],
            FAIL,
            "no scene features were dropped by the render target",
            "the render target dropped scene features — the print file is missing content",
        ),
        diagnostics_rule(
            "license",
            collected,
            &["LUME0212"],
            FAIL,
            "every embedded asset's license permits print export",
            "an embedded asset's license forbids print export",
        ),
    ];

    // Overall = worst rule status.
    let status = if rules.iter().any(|rule| rule.status == FAIL) {
        FAIL
    } else if rules.iter().any(|rule| rule.status == WARN) {
        WARN
    } else {
        PASS
    };
    rules.sort_by_key(|rule| match rule.status.as_str() {
        FAIL => 0,
        WARN => 1,
        _ => 2,
    });

    PrintReadyReport {
        ruleset: "print-ready-v1".to_owned(),
        status: status.to_owned(),
        rules,
    }
}

fn rule(id: &str, status: &str, detail: String) -> PrintReadyRule {
    PrintReadyRule {
        id: id.to_owned(),
        status: status.to_owned(),
        detail,
    }
}

/// L4 rule 1: a print run with bleed requested needs a bleed rect on every
/// page (fail — the export would silently ship trim-sized geometry);
/// printing without bleed at all is a warning (legitimate for documents
/// with deliberate white margins, fatal for full-bleed designs).
fn bleed_present_rule(pages: &[&Page], request: &ExportRequest) -> PrintReadyRule {
    let missing: Vec<&Page> = pages
        .iter()
        .copied()
        .filter(|page| page.bleed.is_none())
        .collect();
    if missing.is_empty() {
        return rule(
            "bleed_present",
            PASS,
            format!("all {} page(s) carry a bleed rect", pages.len()),
        );
    }
    let ids: Vec<String> = missing.iter().map(|page| page.id.to_string()).collect();
    if request.profile.include_bleed {
        rule(
            "bleed_present",
            FAIL,
            format!(
                "bleed was requested but page(s) {} have no bleed rect — the print file would ship trim-sized with no cutting tolerance",
                ids.join(", ")
            ),
        )
    } else {
        rule(
            "bleed_present",
            WARN,
            format!(
                "page(s) {} have no bleed rect and none was requested — acceptable only for deliberate white-margin layouts",
                ids.join(", ")
            ),
        )
    }
}

/// L4 rule 2 — the mechanical form of chain link L1: any filled node
/// touching a trim edge must extend to the bleed line on that side, or the
/// cut will expose paper. Only evaluated on pages that have a bleed rect.
fn edge_art_rule(scene: &Scene, pages: &[&Page]) -> PrintReadyRule {
    let mut violations: Vec<String> = Vec::new();
    let mut evaluated = false;

    for page in pages {
        let Some(bleed) = &page.bleed else { continue };
        evaluated = true;
        let trim = Rect {
            x: 0.0,
            y: 0.0,
            width: page.size.width,
            height: page.size.height,
        };
        let mut boxes: Vec<(NodeId, Rect)> = Vec::new();
        for child_id in &page.children {
            collect_filled_boxes(scene, child_id, (0.0, 0.0), None, &mut boxes);
        }
        for (node_id, node_box) in boxes {
            for side in touched_short_sides(&node_box, &trim, bleed) {
                violations.push(format!("{node_id} ({side} edge of page {})", page.id));
            }
        }
    }

    if !evaluated {
        return rule(
            "edge_art_reaches_bleed",
            PASS,
            "no pages carry a bleed rect; rule not applicable".to_owned(),
        );
    }
    if violations.is_empty() {
        rule(
            "edge_art_reaches_bleed",
            PASS,
            "every trim-touching fill extends to the bleed line".to_owned(),
        )
    } else {
        rule(
            "edge_art_reaches_bleed",
            FAIL,
            format!(
                "art touches the trim edge but stops short of the bleed line — cutting tolerance will expose paper: {}",
                violations.join("; ")
            ),
        )
    }
}

/// L4 rule 3: text belongs inside the safe area on print pages (warn —
/// tolerable for proofs, wrong for production).
fn text_safe_area_rule(scene: &Scene, pages: &[&Page]) -> PrintReadyRule {
    let mut violations: Vec<String> = Vec::new();
    let mut evaluated = false;

    for page in pages {
        let Some(safe) = &page.safe_area else { continue };
        evaluated = true;
        let mut boxes: Vec<(NodeId, Rect)> = Vec::new();
        for child_id in &page.children {
            collect_text_boxes(scene, child_id, (0.0, 0.0), None, &mut boxes);
        }
        for (node_id, node_box) in boxes {
            let inside = node_box.x >= safe.x - TRIM_TOUCH_EPSILON
                && node_box.y >= safe.y - TRIM_TOUCH_EPSILON
                && node_box.x + node_box.width <= safe.x + safe.width + TRIM_TOUCH_EPSILON
                && node_box.y + node_box.height <= safe.y + safe.height + TRIM_TOUCH_EPSILON;
            if !inside {
                violations.push(format!("{node_id} (page {})", page.id));
            }
        }
    }

    if !evaluated {
        return rule(
            "text_in_safe_area",
            WARN,
            "no pages carry a safe area — set page.safe_area before treating print output as production-ready".to_owned(),
        );
    }
    if violations.is_empty() {
        rule(
            "text_in_safe_area",
            PASS,
            "all text sits inside the safe area".to_owned(),
        )
    } else {
        rule(
            "text_in_safe_area",
            WARN,
            format!(
                "text outside the safe area may be cut or bound away: {}",
                violations.join(", ")
            ),
        )
    }
}

fn geometry_consistent_rule(collected: &[Diagnostic]) -> PrintReadyRule {
    if collected.iter().any(|diagnostic| diagnostic.code == "LUME0420") {
        rule(
            "page_geometry_consistent",
            WARN,
            "pages have mixed trim sizes — most print handoffs expect one consistent size".to_owned(),
        )
    } else {
        rule(
            "page_geometry_consistent",
            PASS,
            "all pages share one trim size".to_owned(),
        )
    }
}

fn diagnostics_rule(
    id: &str,
    collected: &[Diagnostic],
    codes: &[&str],
    hit_status: &str,
    pass_detail: &str,
    hit_detail: &str,
) -> PrintReadyRule {
    let hits: Vec<&Diagnostic> = collected
        .iter()
        .filter(|diagnostic| codes.contains(&diagnostic.code.as_str()))
        .collect();
    if hits.is_empty() {
        rule(id, PASS, pass_detail.to_owned())
    } else {
        rule(
            id,
            hit_status,
            format!("{hit_detail} ({} finding(s): {})", hits.len(), summarize(&hits)),
        )
    }
}

fn summarize(hits: &[&Diagnostic]) -> String {
    let mut lines: Vec<String> = hits
        .iter()
        .take(3)
        .map(|diagnostic| diagnostic.message.clone())
        .collect();
    if hits.len() > 3 {
        lines.push(format!("… and {} more", hits.len() - 3));
    }
    lines.join(" · ")
}

/// Which trim sides `node_box` touches without reaching the bleed line.
fn touched_short_sides(node_box: &Rect, trim: &Rect, bleed: &Rect) -> Vec<&'static str> {
    let mut sides = Vec::new();
    let left = node_box.x;
    let right = node_box.x + node_box.width;
    let top = node_box.y;
    let bottom = node_box.y + node_box.height;

    if left <= trim.x + TRIM_TOUCH_EPSILON && left > bleed.x + BLEED_REACH_EPSILON {
        sides.push("left");
    }
    if right >= trim.x + trim.width - TRIM_TOUCH_EPSILON
        && right < bleed.x + bleed.width - BLEED_REACH_EPSILON
    {
        sides.push("right");
    }
    if top <= trim.y + TRIM_TOUCH_EPSILON && top > bleed.y + BLEED_REACH_EPSILON {
        sides.push("top");
    }
    if bottom >= trim.y + trim.height - TRIM_TOUCH_EPSILON
        && bottom < bleed.y + bleed.height - BLEED_REACH_EPSILON
    {
        sides.push("bottom");
    }
    sides
}

fn collect_filled_boxes(
    scene: &Scene,
    node_id: &NodeId,
    parent_abs: (f64, f64),
    parent_computed_origin: Option<(f64, f64)>,
    boxes: &mut Vec<(NodeId, Rect)>,
) {
    walk_boxes(scene, node_id, parent_abs, parent_computed_origin, boxes, &|node| {
        !matches!(node.kind, NodeKind::Text(_))
            && (!node.fills.is_empty() || matches!(node.kind, NodeKind::Image(_)))
    });
}

fn collect_text_boxes(
    scene: &Scene,
    node_id: &NodeId,
    parent_abs: (f64, f64),
    parent_computed_origin: Option<(f64, f64)>,
    boxes: &mut Vec<(NodeId, Rect)>,
) {
    walk_boxes(scene, node_id, parent_abs, parent_computed_origin, boxes, &|node| {
        matches!(node.kind, NodeKind::Text(_))
    });
}

fn walk_boxes(
    scene: &Scene,
    node_id: &NodeId,
    parent_abs: (f64, f64),
    parent_computed_origin: Option<(f64, f64)>,
    boxes: &mut Vec<(NodeId, Rect)>,
    include: &dyn Fn(&Node) -> bool,
) {
    let Some(node) = scene.nodes.get(node_id) else {
        return;
    };
    let render_box = render_box_for_node(node, parent_computed_origin);
    let abs = Rect {
        x: parent_abs.0 + render_box.x,
        y: parent_abs.1 + render_box.y,
        width: render_box.width,
        height: render_box.height,
    };
    if include(node) {
        boxes.push((node.id.clone(), abs.clone()));
    }
    let child_origin = node
        .computed
        .as_ref()
        .map(|computed| (computed.layout_bounds.x, computed.layout_bounds.y));
    for child_id in &node.children {
        walk_boxes(scene, child_id, (abs.x, abs.y), child_origin, boxes, include);
    }
}
