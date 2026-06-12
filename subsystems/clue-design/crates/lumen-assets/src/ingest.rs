//! Asset ingest pipeline: size limit, MIME sniff/validation, and (in the
//! processing slice) sanitization, probing, and thumbnail derivation.
//!
//! Ingest is pure with respect to storage: it validates and transforms
//! bytes and reports metadata; callers store the returned bytes and build
//! the `AssetRecord`. This keeps the pipeline reusable for uploads and for
//! generated assets alike.

use crate::mime::{default_kind_for_mime, mime_compatible, sniff_mime};
use lumen_core::{AssetKind, Diagnostic, Phase, RasterAssetMetadata, VectorAssetMetadata};
use std::error::Error;
use std::fmt;

pub const DEFAULT_MAX_BYTES: u64 = 10 * 1024 * 1024;

#[derive(Clone, Debug)]
pub struct IngestRequest<'a> {
    pub bytes: &'a [u8],
    pub declared_mime: Option<&'a str>,
    pub filename: Option<&'a str>,
    pub kind_hint: Option<AssetKind>,
    pub max_bytes: u64,
}

impl<'a> IngestRequest<'a> {
    pub fn new(bytes: &'a [u8]) -> Self {
        Self {
            bytes,
            declared_mime: None,
            filename: None,
            kind_hint: None,
            max_bytes: DEFAULT_MAX_BYTES,
        }
    }
}

#[derive(Clone, Debug)]
pub struct IngestOutput {
    /// Bytes to store; differs from the input when sanitization rewrites
    /// the content (SVG).
    pub bytes: Vec<u8>,
    pub sniffed_mime: String,
    pub kind: AssetKind,
    pub raster: Option<RasterAssetMetadata>,
    pub vector: Option<VectorAssetMetadata>,
    pub diagnostics: Vec<Diagnostic>,
}

#[derive(Clone, Debug)]
pub struct IngestError {
    pub code: &'static str,
    pub message: String,
    pub diagnostic: Diagnostic,
}

impl IngestError {
    fn new(code: &'static str, diagnostic_code: &str, message: String) -> Self {
        Self {
            code,
            message: message.clone(),
            diagnostic: Diagnostic::error(Phase::Validation, diagnostic_code, message, None),
        }
    }
}

impl fmt::Display for IngestError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl Error for IngestError {}

/// Validate and normalize incoming asset bytes.
///
/// Rejections (errors): empty payload, payload over `max_bytes`
/// (LUMA0601), declared MIME contradicting the sniffed type (LUMA0600).
/// Unknown content sniffs to no supported type and ingests as
/// `AssetKind::Other` with warning LUMA0602.
pub fn ingest(request: &IngestRequest) -> Result<IngestOutput, Box<IngestError>> {
    if request.bytes.is_empty() {
        return Err(Box::new(IngestError::new(
            "ingest.empty",
            "LUMA0601",
            "asset upload contained zero bytes".to_owned(),
        )));
    }
    if request.bytes.len() as u64 > request.max_bytes {
        return Err(Box::new(IngestError::new(
            "ingest.too_large",
            "LUMA0601",
            format!(
                "asset payload of {} bytes exceeds the {}-byte limit",
                request.bytes.len(),
                request.max_bytes
            ),
        )));
    }

    let mut diagnostics = Vec::new();
    let sniffed = sniff_mime(request.bytes);

    if let (Some(declared), Some(sniffed)) = (request.declared_mime, sniffed) {
        if !mime_compatible(declared, sniffed) {
            return Err(Box::new(IngestError::new(
                "ingest.mime_mismatch",
                "LUMA0600",
                format!(
                    "declared MIME type {declared:?} contradicts sniffed type {sniffed:?}{}",
                    request
                        .filename
                        .map(|name| format!(" for {name}"))
                        .unwrap_or_default()
                ),
            )));
        }
    }

    let sniffed_mime = match sniffed {
        Some(mime) => mime.to_owned(),
        None => {
            diagnostics.push(Diagnostic::warning(
                Phase::Validation,
                "LUMA0602",
                format!(
                    "asset bytes match no supported signature; stored as application/octet-stream{}",
                    request
                        .filename
                        .map(|name| format!(" ({name})"))
                        .unwrap_or_default()
                ),
                None,
            ));
            "application/octet-stream".to_owned()
        }
    };

    let default_kind = default_kind_for_mime(&sniffed_mime);
    let kind = match &request.kind_hint {
        // A hint may narrow raster/vector content (e.g. logo) but cannot
        // contradict the sniffed family.
        Some(hint) if kind_hint_allowed(hint, &default_kind) => hint.clone(),
        Some(hint) => {
            diagnostics.push(Diagnostic::warning(
                Phase::Validation,
                "LUMA0602",
                format!(
                    "requested asset kind {hint:?} is incompatible with sniffed type {sniffed_mime}; using {default_kind:?}"
                ),
                None,
            ));
            default_kind
        }
        None => default_kind,
    };

    Ok(IngestOutput {
        bytes: request.bytes.to_vec(),
        sniffed_mime,
        kind,
        raster: None,
        vector: None,
        diagnostics,
    })
}

fn kind_hint_allowed(hint: &AssetKind, default_kind: &AssetKind) -> bool {
    if hint == default_kind {
        return true;
    }
    matches!(
        (default_kind, hint),
        (AssetKind::RasterImage, AssetKind::Logo)
            | (AssetKind::Vector, AssetKind::Logo)
            | (_, AssetKind::Other)
    )
}
