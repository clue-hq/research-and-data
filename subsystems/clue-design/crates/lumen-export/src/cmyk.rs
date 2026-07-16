//! Print W5 Stage B — CMYK conversion at export (D3: Ghostscript).
//!
//! Print-intent PDF exports may request `color: "cmyk"` on the profile:
//! the rendered (sRGB) PDF is post-processed through Ghostscript's
//! pdfwrite device with `-sColorConversionStrategy=CMYK` and a target
//! press ICC profile. Electronic-distribution PDFs (preview intent) never
//! convert — requesting CMYK there is a hard error, not a silent no-op.
//!
//! Black preservation — the classic fuzzy-text bug — needs paint-level
//! awareness, and it lives HERE, not in Ghostscript flags: gs's
//! `-dBlackText`/`-dBlackVector` turn out to force ALL text/vectors to
//! black (measured live: red text became K-only), and a blanket ICC
//! conversion turns RGB #000 into 4-color black (also measured: C=M=Y=K
//! inked under black glyphs — the fringe-on-misregistration bug). What
//! does hold: Ghostscript maps DeviceGray to the K channel only. So
//! before conversion we rewrite every achromatic DeviceRGB paint
//! (`r g b rg/RG` with r==g==b) in the content streams to DeviceGray
//! `g/G` — black text/rules/fills separate to pure K, neutral grays stay
//! CMY-cast-free, and every chromatic paint takes the full ICC path.
//! Declared v1 semantics: authored pure #000 stays K-only everywhere;
//! rich-black panels are authored as near-black (e.g. #0a0a0f), which
//! converts through the ICC to a rich CMYK mix within the profile's ink
//! limit.
//!
//! The target ICC resolves from `LUMEN_CMYK_ICC` (a shop-specific
//! profile, e.g. ISO Coated v2 / FOGRA39 from eci.org) or falls back to
//! the `default_cmyk.icc` shipped with the local Ghostscript install.
//! The same profile bytes become the PDF/X OutputIntent, so the file
//! declares exactly the condition it was separated for. No usable ICC or
//! no `gs` binary fails the export loudly.

use lumen_core::{ExportError, ExportRequest, PdfIntent};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};

/// SOURCE_DATE_EPOCH handed to Ghostscript so its own metadata writes are
/// reproducible; our finalize pass then strips/overwrites them anyway.
/// 2026-01-01T00:00:00Z — matches the pipeline's deterministic date.
const GS_SOURCE_DATE_EPOCH: &str = "1767225600";

/// Resolved CMYK conversion target: the press profile bytes (embedded as
/// the PDF/X OutputIntent), its human identifier (from the ICC `desc`
/// tag), and the on-disk path Ghostscript reads.
#[derive(Clone, Debug)]
pub struct CmykTarget {
    pub icc: Vec<u8>,
    pub identifier: String,
    pub icc_path: PathBuf,
    gs_bin: PathBuf,
}

/// Interpret the profile's `color` field. `None` → no conversion.
/// `Some("cmyk")` resolves the Ghostscript binary and target ICC now, so
/// a missing dependency fails before any rendering work; it also enforces
/// the print-intent gate. Unknown values fail loudly.
pub fn cmyk_target_for(request: &ExportRequest) -> Result<Option<CmykTarget>, ExportError> {
    let Some(color) = request.profile.color.as_deref() else {
        return Ok(None);
    };
    if color != "cmyk" {
        return Err(ExportError::new(
            "export.color_unknown",
            format!("unknown export color {color:?}; supported: \"cmyk\""),
        ));
    }
    if !matches!(request.profile.pdf_intent, Some(PdfIntent::Print)) {
        return Err(ExportError::new(
            "export.cmyk_requires_print_intent",
            "CMYK conversion applies only to print-intent PDF exports; electronic-distribution PDFs stay sRGB",
        ));
    }
    // Proof exports overlay an sRGB control strip and advertise it via
    // LUME0431; running that artifact through the CMYK conversion would
    // flatten the strip's neutral patches to K-only while the file still
    // claims an sRGB strip — a proof that lies to the press operator.
    // Hard error, never a silent partial conversion.
    if request.profile.proof {
        return Err(ExportError::new(
            "export.cmyk_proof_conflict",
            "proof exports carry an sRGB control strip (LUME0431) that CMYK conversion would falsify; export the proof without color:\"cmyk\", and convert the production file separately",
        ));
    }

    let gs_bin = resolve_ghostscript()?;
    let icc_path = resolve_target_icc(&gs_bin)?;
    let icc = std::fs::read(&icc_path).map_err(|error| {
        ExportError::new(
            "export.cmyk_icc_missing",
            format!("CMYK target ICC {} is not readable: {error}", icc_path.display()),
        )
    })?;
    let identifier = icc_description(&icc).unwrap_or_else(|| {
        icc_path
            .file_stem()
            .map(|stem| stem.to_string_lossy().into_owned())
            .unwrap_or_else(|| "CMYK".to_owned())
    });
    Ok(Some(CmykTarget {
        icc,
        identifier,
        icc_path,
        gs_bin,
    }))
}

/// Run the Ghostscript CMYK conversion on a rendered PDF. Returns the
/// converted bytes; any Ghostscript failure surfaces its stderr tail.
pub fn convert_pdf_to_cmyk(bytes: &[u8], target: &CmykTarget) -> Result<Vec<u8>, ExportError> {
    static SEQ: AtomicU64 = AtomicU64::new(0);
    let dir = std::env::temp_dir().join(format!(
        "lumen-cmyk-{}-{}",
        std::process::id(),
        SEQ.fetch_add(1, Ordering::Relaxed)
    ));
    std::fs::create_dir_all(&dir)
        .map_err(|error| ExportError::new("export.cmyk_failed", format!("temp dir: {error}")))?;
    let input = dir.join("in.pdf");
    let output = dir.join("out.pdf");
    let result = (|| -> Result<Vec<u8>, ExportError> {
        let normalized = normalize_achromatic_rgb(bytes)?;
        std::fs::write(&input, normalized)
            .map_err(|error| ExportError::new("export.cmyk_failed", format!("temp write: {error}")))?;

        let run = Command::new(&target.gs_bin)
            .env("SOURCE_DATE_EPOCH", GS_SOURCE_DATE_EPOCH)
            .args([
                "-dSAFER",
                "-dBATCH",
                "-dNOPAUSE",
                "-dQUIET",
                "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.6",
                "-sColorConversionStrategy=CMYK",
                // Black preservation happens BEFORE this call (achromatic
                // paints normalized to DeviceGray, which gs maps to pure
                // K). Do NOT add -dBlackText/-dBlackVector here: they
                // force ALL text/vector art to black, colored included.
                // Never degrade image data during conversion: no
                // downsampling, and lossless Flate instead of the DCT
                // re-encode that AutoFilter would pick.
                "-dDownsampleColorImages=false",
                "-dDownsampleGrayImages=false",
                "-dDownsampleMonoImages=false",
                "-dAutoFilterColorImages=false",
                "-dAutoFilterGrayImages=false",
                "-dColorImageFilter=/FlateEncode",
                "-dGrayImageFilter=/FlateEncode",
            ])
            .arg(format!("-sOutputICCProfile={}", target.icc_path.display()))
            .arg("-o")
            .arg(&output)
            .arg(&input)
            .output()
            .map_err(|error| {
                ExportError::new(
                    "export.cmyk_failed",
                    format!("Ghostscript spawn failed ({}): {error}", target.gs_bin.display()),
                )
            })?;
        if !run.status.success() {
            let stderr = String::from_utf8_lossy(&run.stderr);
            let tail: String = stderr
                .lines()
                .rev()
                .take(6)
                .collect::<Vec<_>>()
                .into_iter()
                .rev()
                .collect::<Vec<_>>()
                .join(" | ");
            return Err(ExportError::new(
                "export.cmyk_failed",
                format!("Ghostscript CMYK conversion failed ({}): {tail}", run.status),
            ));
        }
        std::fs::read(&output)
            .map_err(|error| ExportError::new("export.cmyk_failed", format!("temp read: {error}")))
    })();
    let _ = std::fs::remove_dir_all(&dir);
    result
}

/// Paint-level black preservation: rewrite every achromatic DeviceRGB
/// paint (`r g b rg`/`RG` with r==g==b) in the page content streams and
/// their Form XObjects to the equivalent DeviceGray `g`/`G`. Ghostscript
/// maps DeviceGray to the K channel only, so black text, hairline rules,
/// and neutral fills separate to pure K instead of the 4-color buildup a
/// blanket ICC conversion produces. Chromatic paints are untouched and
/// take the full ICC path (gradients ride their shading dictionaries).
///
/// The renderer under this pipeline is Skia's PDF backend, which emits
/// solid colors exclusively as `rg`/`RG` — a content stream that fails to
/// parse means a different producer and fails loudly rather than
/// silently shipping impure blacks.
fn normalize_achromatic_rgb(bytes: &[u8]) -> Result<Vec<u8>, ExportError> {
    use lopdf::{content::Content, Document, Object, ObjectId};
    use std::collections::BTreeSet;

    let mut document = Document::load_mem(bytes).map_err(|error| {
        ExportError::new("export.cmyk_failed", format!("pre-conversion PDF parse: {error}"))
    })?;

    // Collect page content streams plus Form XObjects (recursively).
    let mut targets: BTreeSet<ObjectId> = BTreeSet::new();
    let mut forms: Vec<ObjectId> = Vec::new();
    for (_, page_id) in document.get_pages() {
        for content_id in document.get_page_contents(page_id) {
            targets.insert(content_id);
        }
        let Ok((resources, resource_ids)) = document.get_page_resources(page_id) else {
            continue;
        };
        let mut resource_dicts: Vec<lopdf::Dictionary> =
            resources.into_iter().cloned().collect();
        for resource_id in resource_ids {
            if let Ok(dict) = document.get_dictionary(resource_id) {
                resource_dicts.push(dict.clone());
            }
        }
        for dict in resource_dicts {
            collect_form_xobjects(&document, &dict, &mut forms, &mut targets);
        }
    }
    while let Some(form_id) = forms.pop() {
        if let Ok(Object::Stream(stream)) = document.get_object(form_id) {
            if let Ok(resources) = stream.dict.get(b"Resources") {
                let resolved = match resources {
                    Object::Reference(reference) => {
                        document.get_dictionary(*reference).ok().cloned()
                    }
                    Object::Dictionary(dict) => Some(dict.clone()),
                    _ => None,
                };
                if let Some(dict) = resolved {
                    collect_form_xobjects(&document, &dict, &mut forms, &mut targets);
                }
            }
        }
    }

    for target in targets {
        let stream = document
            .get_object_mut(target)
            .and_then(Object::as_stream_mut)
            .map_err(|error| {
                ExportError::new("export.cmyk_failed", format!("content stream unavailable: {error}"))
            })?;
        let data = stream.decompressed_content().map_err(|error| {
            ExportError::new("export.cmyk_failed", format!("content stream decode: {error}"))
        })?;
        let mut content = Content::decode(&data).map_err(|error| {
            ExportError::new("export.cmyk_failed", format!("content stream parse: {error}"))
        })?;
        let mut changed = false;
        let mut has_inline_image = false;
        for operation in &mut content.operations {
            if operation.operator == "BI" {
                has_inline_image = true;
                continue;
            }
            let gray_operator = match operation.operator.as_str() {
                "rg" => "g",
                "RG" => "G",
                _ => continue,
            };
            let values: Vec<f32> = operation
                .operands
                .iter()
                .filter_map(|operand| operand.as_float().ok())
                .collect();
            if values.len() == 3
                && (values[0] - values[1]).abs() < 1e-4
                && (values[1] - values[2]).abs() < 1e-4
            {
                operation.operator = gray_operator.to_owned();
                operation.operands = vec![Object::Real(values[0])];
                changed = true;
            }
        }
        if changed {
            // lopdf parses an inline image (`BI … ID … EI`) into a "BI"
            // operation whose operand is a raw stream object, and its
            // `Content::encode` writes that operand back as
            // `<<dict>> stream…endstream` — malformed content, a silently
            // corrupt PDF. Skia's PDF backend emits image XObjects, never
            // inline images, so this is untriggered today; if a producer
            // change ever emits one into a stream we must rewrite, fail
            // loudly instead of shipping the corruption. Streams with an
            // inline image but no achromatic paint are left byte-untouched
            // and stay safe.
            if has_inline_image {
                return Err(ExportError::new(
                    "export.cmyk_failed",
                    "content stream contains an inline image (BI…EI) alongside achromatic paint; the pre-conversion rewrite cannot round-trip inline images — re-author the image as an XObject or export without color:\"cmyk\"",
                ));
            }
            let encoded = content.encode().map_err(|error| {
                ExportError::new("export.cmyk_failed", format!("content stream encode: {error}"))
            })?;
            stream.dict.remove(b"Filter");
            stream.dict.remove(b"DecodeParms");
            stream.set_content(encoded);
        }
    }

    let mut output = Vec::new();
    document.save_to(&mut output).map_err(|error| {
        ExportError::new("export.cmyk_failed", format!("pre-conversion PDF serialize: {error}"))
    })?;
    Ok(output)
}

/// Push every Form XObject referenced by a resources dictionary onto the
/// worklists (its content stream gets normalized; its own resources get
/// walked for nested forms).
fn collect_form_xobjects(
    document: &lopdf::Document,
    resources: &lopdf::Dictionary,
    forms: &mut Vec<lopdf::ObjectId>,
    targets: &mut std::collections::BTreeSet<lopdf::ObjectId>,
) {
    use lopdf::Object;
    let Ok(xobjects) = resources.get(b"XObject") else {
        return;
    };
    let resolved = match xobjects {
        Object::Reference(reference) => document.get_dictionary(*reference).ok(),
        Object::Dictionary(dict) => Some(dict),
        _ => None,
    };
    let Some(xobjects) = resolved else {
        return;
    };
    for (_, entry) in xobjects.iter() {
        let Object::Reference(xobject_id) = entry else {
            continue;
        };
        let Ok(Object::Stream(stream)) = document.get_object(*xobject_id) else {
            continue;
        };
        let is_form = stream
            .dict
            .get(b"Subtype")
            .and_then(Object::as_name)
            .is_ok_and(|name| name == b"Form");
        if is_form && targets.insert(*xobject_id) {
            forms.push(*xobject_id);
        }
    }
}

/// Locate the Ghostscript binary: `LUMEN_GHOSTSCRIPT` (explicit path)
/// else `gs` on PATH. Verified runnable so a missing dependency is a
/// clear, actionable error instead of a spawn failure mid-export.
fn resolve_ghostscript() -> Result<PathBuf, ExportError> {
    let candidate = std::env::var("LUMEN_GHOSTSCRIPT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("gs"));
    match Command::new(&candidate).arg("--version").output() {
        Ok(output) if output.status.success() => Ok(candidate),
        _ => Err(ExportError::new(
            "export.cmyk_unavailable",
            format!(
                "CMYK conversion requires Ghostscript; {} is not runnable — install ghostscript (e.g. `brew install ghostscript`) or set LUMEN_GHOSTSCRIPT to the gs binary",
                candidate.display()
            ),
        )),
    }
}

/// Resolve the target press ICC: `LUMEN_CMYK_ICC` wins (a characterized
/// print condition such as FOGRA39); otherwise the `default_cmyk.icc`
/// shipped with the local Ghostscript install (derived from its resource
/// search path). PDF/X needs the profile BYTES for the OutputIntent, so
/// "let gs use its internal default" is not enough — no readable ICC is
/// a hard error.
fn resolve_target_icc(gs_bin: &Path) -> Result<PathBuf, ExportError> {
    if let Ok(explicit) = std::env::var("LUMEN_CMYK_ICC") {
        let path = PathBuf::from(explicit);
        if path.is_file() {
            return Ok(path);
        }
        return Err(ExportError::new(
            "export.cmyk_icc_missing",
            format!("LUMEN_CMYK_ICC points at {} but no such file exists", path.display()),
        ));
    }

    for base in ghostscript_share_dirs(gs_bin) {
        let candidate = base.join("iccprofiles").join("default_cmyk.icc");
        if candidate.is_file() {
            return Ok(candidate);
        }
    }
    Err(ExportError::new(
        "export.cmyk_icc_missing",
        "no CMYK target ICC found: set LUMEN_CMYK_ICC to a press profile (e.g. ISO Coated v2 / FOGRA39 from eci.org) or install Ghostscript with its iccprofiles directory",
    ))
}

/// Ghostscript share directories, derived from the `Search path:` block
/// of `gs -h` (entries like `<prefix>/share/ghostscript/<ver>/Resource/Init`
/// on Linux, `<prefix>/share/ghostscript/Resource/Init` on Homebrew —
/// `iccprofiles/` sits beside `Resource/`).
fn ghostscript_share_dirs(gs_bin: &Path) -> Vec<PathBuf> {
    let Ok(output) = Command::new(gs_bin).arg("-h").output() else {
        return Vec::new();
    };
    let help = String::from_utf8_lossy(&output.stdout);
    let mut dirs = Vec::new();
    for token in help.split_whitespace() {
        let token = token.trim_end_matches(':');
        if let Some(base) = token.strip_suffix("/Resource/Init") {
            dirs.push(PathBuf::from(base));
        }
    }
    dirs
}

/// Minimal ICC profile description reader: v2 `desc` (textDescriptionType)
/// and v4 `mluc` (multiLocalizedUnicodeType). Used for the OutputIntent's
/// OutputConditionIdentifier so the PDF names the real press condition.
pub fn icc_description(icc: &[u8]) -> Option<String> {
    let read_u32 = |offset: usize| -> Option<u32> {
        icc.get(offset..offset + 4)
            .map(|bytes| u32::from_be_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
    };
    let tag_count = read_u32(128)? as usize;
    for index in 0..tag_count.min(1024) {
        let entry = 132 + index * 12;
        if icc.get(entry..entry + 4)? != b"desc" {
            continue;
        }
        let offset = read_u32(entry + 4)? as usize;
        let size = read_u32(entry + 8)? as usize;
        let tag = icc.get(offset..offset + size)?;
        match tag.get(0..4)? {
            b"desc" => {
                // 4 sig + 4 reserved + 4 ascii-count, then the ASCII string
                // (NUL-terminated).
                let count = u32::from_be_bytes([tag[8], tag[9], tag[10], tag[11]]) as usize;
                let raw = tag.get(12..12 + count)?;
                let text: String = raw
                    .iter()
                    .take_while(|byte| **byte != 0)
                    .map(|byte| *byte as char)
                    .collect();
                return (!text.is_empty()).then_some(text);
            }
            b"mluc" => {
                // 4 sig + 4 reserved + 4 record-count + 4 record-size,
                // first record: 2 lang + 2 country + 4 length + 4 offset
                // (offset relative to tag start), UTF-16BE.
                let length = u32::from_be_bytes([tag[20], tag[21], tag[22], tag[23]]) as usize;
                let string_offset = u32::from_be_bytes([tag[24], tag[25], tag[26], tag[27]]) as usize;
                let raw = tag.get(string_offset..string_offset + length)?;
                let units: Vec<u16> = raw
                    .chunks_exact(2)
                    .map(|pair| u16::from_be_bytes([pair[0], pair[1]]))
                    .collect();
                let text = String::from_utf16_lossy(&units);
                let text = text.trim_end_matches('\0').to_owned();
                return (!text.is_empty()).then_some(text);
            }
            _ => return None,
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use lumen_core::{ExportFormat, ExportProfile, ExportPurpose, ExportRequest};

    fn pdf_request(color: Option<&str>, intent: Option<PdfIntent>) -> ExportRequest {
        ExportRequest {
            profile: ExportProfile {
                name: "cmyk_gate_test".to_owned(),
                format: ExportFormat::Pdf,
                pdf_intent: intent,
                raster: None,
                include_bleed: false,
                embed_fonts: true,
                include_marks: false,
                imposition: None,
                proof: false,
                color: color.map(str::to_owned),
            },
            page_ids: Vec::new(),
            purpose: ExportPurpose::UserDownload,
        }
    }

    #[test]
    fn no_color_field_means_no_conversion() {
        let target = cmyk_target_for(&pdf_request(None, Some(PdfIntent::Preview))).unwrap();
        assert!(target.is_none());
    }

    #[test]
    fn cmyk_on_preview_intent_is_rejected() {
        let error =
            cmyk_target_for(&pdf_request(Some("cmyk"), Some(PdfIntent::Preview))).unwrap_err();
        assert_eq!(error.code, "export.cmyk_requires_print_intent");
    }

    #[test]
    fn cmyk_without_intent_is_rejected() {
        let error = cmyk_target_for(&pdf_request(Some("cmyk"), None)).unwrap_err();
        assert_eq!(error.code, "export.cmyk_requires_print_intent");
    }

    #[test]
    fn unknown_color_value_is_rejected() {
        let error =
            cmyk_target_for(&pdf_request(Some("rgb"), Some(PdfIntent::Print))).unwrap_err();
        assert_eq!(error.code, "export.color_unknown");
    }

    #[test]
    fn cmyk_on_proof_profile_is_rejected() {
        let mut request = pdf_request(Some("cmyk"), Some(PdfIntent::Print));
        request.profile.proof = true;
        let error = cmyk_target_for(&request).unwrap_err();
        assert_eq!(error.code, "export.cmyk_proof_conflict");
    }

    /// Minimal one-page PDF whose page content stream is exactly `content`.
    fn pdf_with_content(content: &[u8]) -> Vec<u8> {
        use lopdf::{dictionary, Document, Object, Stream};
        let mut document = Document::with_version("1.6");
        let pages_id = document.new_object_id();
        // The production path reads streams via decompressed_content(),
        // which requires a Filter entry — mirror Skia's FlateDecode output.
        // compress() only engages when it saves ≥19 bytes, so pad the tiny
        // fixture content with whitespace (insignificant in content syntax).
        let mut padded = content.to_vec();
        padded.extend_from_slice(&[b'\n'; 512]);
        let mut stream = Stream::new(dictionary! {}, padded);
        stream.compress().expect("fixture stream compresses");
        assert!(
            stream.dict.has(b"Filter"),
            "fixture stream must carry a Filter like production output"
        );
        let content_id = document.add_object(stream);
        let page_id = document.add_object(dictionary! {
            "Type" => "Page",
            "Parent" => pages_id,
            "MediaBox" => vec![0.into(), 0.into(), 100.into(), 100.into()],
            "Contents" => content_id,
        });
        document.objects.insert(
            pages_id,
            Object::Dictionary(dictionary! {
                "Type" => "Pages",
                "Kids" => vec![page_id.into()],
                "Count" => 1,
            }),
        );
        let catalog_id = document.add_object(dictionary! {
            "Type" => "Catalog",
            "Pages" => pages_id,
        });
        document.trailer.set("Root", catalog_id);
        let mut bytes = Vec::new();
        document.save_to(&mut bytes).expect("fixture PDF serializes");
        bytes
    }

    const INLINE_IMAGE: &[u8] = b"BI /W 1 /H 1 /CS /Gray /BPC 8 ID x EI";

    #[test]
    fn achromatic_rewrite_bails_loudly_on_inline_image() {
        // An inline image sharing a stream with achromatic paint would be
        // corrupted by lopdf's re-encode — the rewrite must refuse.
        let content = [INLINE_IMAGE, b"\n0 0 0 rg 0 0 10 10 re f"].concat();
        let error = normalize_achromatic_rgb(&pdf_with_content(&content)).unwrap_err();
        assert_eq!(error.code, "export.cmyk_failed");
        assert!(
            error.message.contains("inline image"),
            "error should name the inline image: {}",
            error.message
        );
    }

    #[test]
    fn inline_image_without_achromatic_paint_passes_through() {
        // No achromatic paint → the stream is never re-encoded, so the
        // inline image survives byte-identical and the rewrite succeeds.
        let content = [INLINE_IMAGE, b"\n1 0 0 rg 0 0 10 10 re f"].concat();
        let output = normalize_achromatic_rgb(&pdf_with_content(&content))
            .expect("untouched inline-image stream round-trips");
        assert!(!output.is_empty());
    }

    #[test]
    fn missing_ghostscript_is_a_clear_error() {
        // An explicit bogus binary path must produce the actionable
        // cmyk_unavailable error, not a raw spawn failure.
        let previous = std::env::var("LUMEN_GHOSTSCRIPT").ok();
        std::env::set_var("LUMEN_GHOSTSCRIPT", "/nonexistent/gs-binary");
        let result = cmyk_target_for(&pdf_request(Some("cmyk"), Some(PdfIntent::Print)));
        match previous {
            Some(value) => std::env::set_var("LUMEN_GHOSTSCRIPT", value),
            None => std::env::remove_var("LUMEN_GHOSTSCRIPT"),
        }
        assert_eq!(result.unwrap_err().code, "export.cmyk_unavailable");
    }
}
