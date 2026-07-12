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

use lopdf::{dictionary, Document, Object, Stream};
use lumen_core::{unit_to_points, Page};

/// Compact sRGB IEC61966-2.1 ICC profile (456 bytes, CC0 — from
/// saucecontrol/Compact-ICC-Profiles). The PDF/X OutputIntent's
/// DestOutputProfile: declares that DeviceRGB content is sRGB, the
/// standard pattern for RGB-workflow PDF/X-4 handed to digital presses.
const SRGB_ICC: &[u8] = include_bytes!("../assets/sRGB-v2-micro.icc");

/// Fixed, deterministic creation timestamp. PDF/X requires CreationDate;
/// a real clock would break the byte-determinism the export pipeline
/// guarantees (and tests byte-compare), so print exports carry this
/// constant instead. Revisit only if a print shop actually objects.
const DETERMINISTIC_DATE_PDF: &str = "D:20260101000000Z";
const DETERMINISTIC_DATE_XMP: &str = "2026-01-01T00:00:00Z";

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

/// Margin (points) added OUTSIDE the bleed for crop marks, and the gap
/// between the bleed line and the start of each mark stroke. Marks must
/// never enter the bleed area — ink there would survive the cut.
pub const MARK_MARGIN_PT: f64 = 14.0;
pub const MARK_GAP_PT: f64 = 3.0;

/// The mark margin a request implies: crop marks require both the marks
/// flag and bleed (marks indicate the trim line relative to the bleed
/// workflow; a marks request without bleed is a no-op, declared upstream).
pub fn marks_margin_pt(request: &lumen_core::ExportRequest) -> f64 {
    if request.profile.include_marks && request.profile.include_bleed {
        MARK_MARGIN_PT
    } else {
        0.0
    }
}

/// [`page_boxes_for`] plus a symmetric mark margin outside the bleed:
/// MediaBox grows by the margin, BleedBox/TrimBox shift inward by it. A
/// margin on a bleed-less page is ignored (mirrors the render region).
pub fn page_boxes_with_margin(page: &Page, include_bleed: bool, margin_pt: f64) -> PageBoxes {
    let base = page_boxes_for(page, include_bleed);
    if margin_pt <= 0.0 || !(include_bleed && page.bleed.is_some()) {
        return base;
    }
    let shift = |rect: [f64; 4]| {
        [
            rect[0] + margin_pt,
            rect[1] + margin_pt,
            rect[2] + margin_pt,
            rect[3] + margin_pt,
        ]
    };
    PageBoxes {
        media: [
            0.0,
            0.0,
            base.media[2] + 2.0 * margin_pt,
            base.media[3] + 2.0 * margin_pt,
        ],
        trim: shift(base.trim),
        bleed: shift(base.bleed),
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
    finalize_print_pdf(bytes, boxes, false)
}

/// One-pass print finalization: exact page boxes always; with `pdfx`, the
/// PDF/X-4 declaration set — sRGB OutputIntent (GTS_PDFX), XMP metadata
/// with GTS_PDFXVersion, Trapped/False, deterministic CreationDate, and
/// PDF version 1.6. The conformance target is declared, not externally
/// validated (veraPDF integration is a plan follow-up).
pub fn finalize_print_pdf(
    bytes: &[u8],
    boxes: &[PageBoxes],
    pdfx: bool,
) -> Result<Vec<u8>, String> {
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

    if pdfx {
        apply_pdfx_declarations(&mut document)?;
    }

    let mut output = Vec::new();
    document
        .save_to(&mut output)
        .map_err(|error| format!("PDF serialize failed: {error}"))?;
    Ok(output)
}

fn apply_pdfx_declarations(document: &mut Document) -> Result<(), String> {
    document.version = "1.6".to_owned();

    // Document ID: deterministic content-derived id (FNV-1a over the ICC +
    // object count — stable across runs, unique enough per document shape).
    let id_seed = fnv1a(SRGB_ICC) ^ (document.objects.len() as u64);

    // Info dictionary: Trapped + the deterministic dates PDF/X requires.
    let info = dictionary! {
        "Producer" => Object::string_literal("Lumen/Skia-PDF"),
        "CreationDate" => Object::string_literal(DETERMINISTIC_DATE_PDF),
        "ModDate" => Object::string_literal(DETERMINISTIC_DATE_PDF),
        "Trapped" => Object::Name(b"False".to_vec()),
    };
    let info_id = document.add_object(Object::Dictionary(info));
    document
        .trailer
        .set("Info", Object::Reference(info_id));

    // OutputIntent with the embedded sRGB profile.
    let icc_stream = Stream::new(
        dictionary! { "N" => Object::Integer(3) },
        SRGB_ICC.to_vec(),
    );
    let icc_id = document.add_object(Object::Stream(icc_stream));
    let intent = dictionary! {
        "Type" => Object::Name(b"OutputIntent".to_vec()),
        "S" => Object::Name(b"GTS_PDFX".to_vec()),
        "OutputConditionIdentifier" => Object::string_literal("sRGB IEC61966-2.1"),
        "Info" => Object::string_literal("sRGB IEC61966-2.1"),
        "RegistryName" => Object::string_literal("http://www.color.org"),
        "DestOutputProfile" => Object::Reference(icc_id),
    };
    let intent_id = document.add_object(Object::Dictionary(intent));

    // XMP metadata packet: the X-4 version claim lives here.
    let xmp = format!(
        r#"<?xpacket begin="{bom}" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:pdfxid="http://www.npes.org/pdfx/ns/id/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/"
    xmlns:pdf="http://ns.adobe.com/pdf/1.3/">
   <pdfxid:GTS_PDFXVersion>PDF/X-4</pdfxid:GTS_PDFXVersion>
   <pdf:Producer>Lumen/Skia-PDF</pdf:Producer>
   <pdf:Trapped>False</pdf:Trapped>
   <xmp:CreateDate>{date}</xmp:CreateDate>
   <xmp:ModifyDate>{date}</xmp:ModifyDate>
   <xmpMM:DocumentID>uuid:{id:016x}-0000-0000-0000-000000000000</xmpMM:DocumentID>
   <xmpMM:InstanceID>uuid:{id:016x}-0000-0000-0000-000000000001</xmpMM:InstanceID>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"#,
        bom = '\u{FEFF}',
        date = DETERMINISTIC_DATE_XMP,
        id = id_seed,
    );
    let mut metadata_stream = Stream::new(
        dictionary! {
            "Type" => Object::Name(b"Metadata".to_vec()),
            "Subtype" => Object::Name(b"XML".to_vec()),
        },
        xmp.into_bytes(),
    );
    // XMP must be scannable by tools that don't inflate streams.
    metadata_stream.allows_compression = false;
    let metadata_id = document.add_object(Object::Stream(metadata_stream));

    let catalog = document
        .catalog_mut()
        .map_err(|error| format!("PDF catalog unavailable: {error}"))?;
    catalog.set(
        "OutputIntents",
        Object::Array(vec![Object::Reference(intent_id)]),
    );
    catalog.set("Metadata", Object::Reference(metadata_id));
    Ok(())
}

fn fnv1a(bytes: &[u8]) -> u64 {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in bytes {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x1000_0000_01b3);
    }
    hash
}
