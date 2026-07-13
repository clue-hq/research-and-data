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

/// The print margin a request implies: crop marks require both the marks
/// flag and bleed (marks indicate the trim line relative to the bleed
/// workflow; a marks request without bleed is a no-op, declared upstream).
/// Proof mode (W7) always gets the margin — its slug and control strip
/// live there, bleed or not.
pub fn print_margin_pt(request: &lumen_core::ExportRequest) -> f64 {
    let marks = request.profile.include_marks && request.profile.include_bleed;
    if marks || request.profile.proof {
        MARK_MARGIN_PT
    } else {
        0.0
    }
}

/// [`page_boxes_for`] plus a symmetric print margin outside the page box
/// (bleed when applicable, trim otherwise — proof mode uses the margin on
/// bleed-less pages too): MediaBox grows by the margin, BleedBox/TrimBox
/// shift inward by it.
pub fn page_boxes_with_margin(page: &Page, include_bleed: bool, margin_pt: f64) -> PageBoxes {
    let base = page_boxes_for(page, include_bleed);
    if margin_pt <= 0.0 {
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

/// PDF/X declaration inputs for [`finalize_print_pdf`]. The output intent
/// defaults to the embedded sRGB profile (the honest description of the
/// RGB pipeline); a CMYK-converted export carries the press target it was
/// actually separated for instead (print W5 stage B).
pub struct PdfxDeclarations<'a> {
    pub title: &'a str,
    pub cmyk: Option<&'a crate::cmyk::CmykTarget>,
}

/// Rewrite every page's MediaBox/TrimBox/BleedBox to the given exact
/// geometry. `boxes` must be in document page order and match the page
/// count — a mismatch is a caller bug and errors loudly rather than
/// shipping a half-boxed print file.
pub fn apply_print_boxes(bytes: &[u8], boxes: &[PageBoxes]) -> Result<Vec<u8>, String> {
    finalize_print_pdf(bytes, boxes, None)
}

/// One-pass print finalization: exact page boxes always; with `pdfx`, the
/// PDF/X-4 declaration set — OutputIntent (GTS_PDFX; sRGB, or the CMYK
/// press profile a converted export was separated for), XMP metadata
/// with GTS_PDFXVersion, Trapped/False, deterministic CreationDate, and
/// PDF version 1.6. The conformance target is declared, not externally
/// validated (veraPDF integration is a plan follow-up).
pub fn finalize_print_pdf(
    bytes: &[u8],
    boxes: &[PageBoxes],
    pdfx: Option<PdfxDeclarations<'_>>,
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

    if let Some(declarations) = pdfx {
        apply_pdfx_declarations(&mut document, &declarations)?;
    }

    let mut output = Vec::new();
    document
        .save_to(&mut output)
        .map_err(|error| format!("PDF serialize failed: {error}"))?;
    Ok(output)
}

fn apply_pdfx_declarations(
    document: &mut Document,
    declarations: &PdfxDeclarations<'_>,
) -> Result<(), String> {
    let title = declarations.title;
    document.version = "1.6".to_owned();

    // The output intent this file is honest about: the sRGB pipeline
    // profile, or — after the W5 CMYK stage — the press profile the
    // colors were actually separated for.
    let (icc_bytes, icc_components, condition): (&[u8], i64, &str) = match declarations.cmyk {
        Some(target) => (&target.icc, 4, target.identifier.as_str()),
        None => (SRGB_ICC, 3, "sRGB IEC61966-2.1"),
    };

    // A converted file arrives with Ghostscript's own Info/Metadata/
    // OutputIntents. We own those contracts (deterministic dates, exact
    // intent); replacing the references would leave the old objects as
    // orphans carrying whatever gs wrote — delete them outright.
    strip_document_metadata(document);

    // Document ID: deterministic content-derived id (FNV-1a over the ICC,
    // the title, and object count — stable across runs, unique enough per
    // document shape).
    let id_seed = fnv1a(icc_bytes) ^ fnv1a(title.as_bytes()) ^ (document.objects.len() as u64);

    // File identifiers: REQUIRED by every PDF/X part (ISO 15930; surfaced
    // by veraPDF's structural pass 2026-07-13 — the one A-profile failure
    // that was also an X failure). Deterministic, permanent == changing
    // for a first-generation file.
    let id_bytes = format!("{id_seed:016x}{:016x}", id_seed.rotate_left(32)).into_bytes();
    document.trailer.set(
        "ID",
        Object::Array(vec![
            Object::String(id_bytes.clone(), lopdf::StringFormat::Hexadecimal),
            Object::String(id_bytes, lopdf::StringFormat::Hexadecimal),
        ]),
    );

    // Info dictionary: Title + Trapped + the deterministic dates PDF/X
    // requires.
    let info = dictionary! {
        "Title" => Object::string_literal(title),
        "Producer" => Object::string_literal("Lumen/Skia-PDF"),
        "CreationDate" => Object::string_literal(DETERMINISTIC_DATE_PDF),
        "ModDate" => Object::string_literal(DETERMINISTIC_DATE_PDF),
        "Trapped" => Object::Name(b"False".to_vec()),
    };
    let info_id = document.add_object(Object::Dictionary(info));
    document
        .trailer
        .set("Info", Object::Reference(info_id));

    // OutputIntent with the embedded profile the file was produced for.
    let icc_stream = Stream::new(
        dictionary! { "N" => Object::Integer(icc_components) },
        icc_bytes.to_vec(),
    );
    let icc_id = document.add_object(Object::Stream(icc_stream));
    let intent = dictionary! {
        "Type" => Object::Name(b"OutputIntent".to_vec()),
        "S" => Object::Name(b"GTS_PDFX".to_vec()),
        "OutputConditionIdentifier" => Object::string_literal(condition),
        "Info" => Object::string_literal(condition),
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
    xmlns:pdf="http://ns.adobe.com/pdf/1.3/"
    xmlns:dc="http://purl.org/dc/elements/1.1/">
   <dc:title><rdf:Alt><rdf:li xml:lang="x-default">{title}</rdf:li></rdf:Alt></dc:title>
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
        title = xml_escape(title),
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

/// Delete any pre-existing Info dictionary, XMP metadata stream, and
/// OutputIntents (both the references and the referenced objects). The
/// finalize pass writes its own deterministic set; leaving the old
/// objects orphaned would carry nondeterministic bytes (Ghostscript
/// stamps dates and instance UUIDs) into the saved file.
fn strip_document_metadata(document: &mut Document) {
    let mut stale: Vec<lopdf::ObjectId> = Vec::new();
    if let Ok(&Object::Reference(info_id)) = document.trailer.get(b"Info") {
        stale.push(info_id);
        document.trailer.remove(b"Info");
    }
    if let Ok(catalog) = document.catalog() {
        if let Ok(&Object::Reference(metadata_id)) = catalog.get(b"Metadata") {
            stale.push(metadata_id);
        }
        if let Ok(intents) = catalog.get(b"OutputIntents") {
            if let Ok(intents) = intents.as_array() {
                for intent in intents {
                    if let Object::Reference(intent_id) = intent {
                        stale.push(*intent_id);
                        // The intent's embedded profile stream goes too.
                        if let Ok(Object::Dictionary(dict)) = document.get_object(*intent_id) {
                            if let Ok(&Object::Reference(profile_id)) =
                                dict.get(b"DestOutputProfile")
                            {
                                stale.push(profile_id);
                            }
                        }
                    }
                }
            }
        }
    }
    if let Ok(catalog) = document.catalog_mut() {
        catalog.remove(b"Metadata");
        catalog.remove(b"OutputIntents");
    }
    for object_id in stale {
        document.objects.remove(&object_id);
    }
}

fn xml_escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

fn fnv1a(bytes: &[u8]) -> u64 {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in bytes {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x1000_0000_01b3);
    }
    hash
}
