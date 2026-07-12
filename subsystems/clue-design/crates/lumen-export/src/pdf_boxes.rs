//! Print box post-process — the L3 link of the no-color-cutoff chain.
//!
//! A print-ready page carries the full box set: MediaBox and BleedBox at
//! the bleed-expanded size, TrimBox at the finished size — the shop's
//! cutting equipment reads TrimBox for the blade line. The Skia renderers
//! only write a MediaBox (and quantize it to the raster-dpi grid), so this
//! portable post-process rewrites every page's boxes to the EXACT scene
//! geometry after rendering. It applies uniformly to any seam-rendered PDF
//! (flattened or vector).
//!
//! Deterministic: lopdf re-serialization is a pure function of the input
//! document — no timestamps or ids are introduced.

use lopdf::{Document, Object};
use lumen_core::{unit_to_points, Page};

/// Exact PDF box geometry for one page, in points, PDF coordinates
/// (origin bottom-left, y up). `media` == `bleed` always; `trim` sits
/// inside by the bleed offsets (or equals them when no bleed applies).
#[derive(Clone, Debug, PartialEq)]
pub struct PageBoxes {
    pub media: [f64; 4],
    pub trim: [f64; 4],
    pub bleed: [f64; 4],
}

/// Compute the box set for a page. Mirrors the render-region contract
/// (`page_region`): with `include_bleed` and a bleed rect present, the
/// bleed rect is the page box; the trim box is the page rect positioned
/// inside it. Layout space is y-down with the bleed origin at negative
/// offsets; PDF space is y-up, so the trim offsets flip vertically.
pub fn page_boxes_for(page: &Page, include_bleed: bool) -> PageBoxes {
    let scale = unit_to_points(1.0, &page.size.unit);
    let trim_width = page.size.width * scale;
    let trim_height = page.size.height * scale;

    match (&page.bleed, include_bleed) {
        (Some(bleed), true) => {
            let media = [0.0, 0.0, bleed.width * scale, bleed.height * scale];
            let trim_x0 = -bleed.x * scale;
            let trim_y0 = (bleed.y + bleed.height - page.size.height) * scale;
            PageBoxes {
                media,
                trim: [trim_x0, trim_y0, trim_x0 + trim_width, trim_y0 + trim_height],
                bleed: media,
            }
        }
        _ => {
            let media = [0.0, 0.0, trim_width, trim_height];
            PageBoxes {
                media,
                trim: media,
                bleed: media,
            }
        }
    }
}

fn box_array(values: [f64; 4]) -> Object {
    Object::Array(values.iter().map(|value| Object::Real(*value as f32)).collect())
}

/// Rewrite every page's MediaBox/TrimBox/BleedBox to the given exact
/// geometry. `boxes` must be in document page order and match the page
/// count — a mismatch is a caller bug and errors loudly rather than
/// shipping a half-boxed print file.
pub fn apply_print_boxes(bytes: &[u8], boxes: &[PageBoxes]) -> Result<Vec<u8>, String> {
    let mut document =
        Document::load_mem(bytes).map_err(|error| format!("PDF parse failed: {error}"))?;
    let pages = document.get_pages();
    if pages.len() != boxes.len() {
        return Err(format!(
            "box count {} does not match page count {}",
            boxes.len(),
            pages.len()
        ));
    }

    for ((_, page_id), page_boxes) in pages.iter().zip(boxes) {
        let page_dict = document
            .get_object_mut(*page_id)
            .and_then(Object::as_dict_mut)
            .map_err(|error| format!("page dictionary unavailable: {error}"))?;
        page_dict.set("MediaBox", box_array(page_boxes.media));
        page_dict.set("TrimBox", box_array(page_boxes.trim));
        page_dict.set("BleedBox", box_array(page_boxes.bleed));
    }

    let mut output = Vec::new();
    document
        .save_to(&mut output)
        .map_err(|error| format!("PDF serialize failed: {error}"))?;
    Ok(output)
}
