use crate::diagnostics::Diagnostic;
use crate::ids::{AssetId, PageId};
use crate::scene::Scene;
use serde::{Deserialize, Serialize};
use std::error::Error;
use std::fmt;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExportFormat {
    Svg,
    Png,
    Pdf,
    FigmaManifest,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PdfIntent {
    Preview,
    Print,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RasterScale {
    pub scale: f64,
    pub dpi: Option<u16>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ExportProfile {
    pub name: String,
    pub format: ExportFormat,
    pub pdf_intent: Option<PdfIntent>,
    pub raster: Option<RasterScale>,
    pub include_bleed: bool,
    pub embed_fonts: bool,
    /// Print W2/W3: draw crop marks in a margin outside the bleed and
    /// grow the MediaBox accordingly. Only meaningful with `include_bleed`
    /// on a PDF profile. Serialized only when true so pre-print scene
    /// fixtures stay byte-identical (the schema-compat contract).
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub include_marks: bool,
    /// Print W4 (D2): optional imposition mode for PDF exports. Reader-order
    /// single pages stay the default deliverable; `"booklet"` arranges pages
    /// 2-up onto duplex saddle-stitch sheets (front [N,1], back [2,3], …).
    /// Unknown values fail loudly at export. Serialized only when set.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub imposition: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExportPurpose {
    UserDownload,
    AgentCritique,
    BulkRender,
    FigmaRoundTrip,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ExportRequest {
    pub profile: ExportProfile,
    pub page_ids: Vec<PageId>,
    pub purpose: ExportPurpose,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ExportArtifact {
    pub format: ExportFormat,
    pub page_id: Option<PageId>,
    pub asset_id: Option<AssetId>,
    pub mime_type: String,
    pub bytes: Vec<u8>,
    pub sidecar_json: Option<String>,
}

/// One rule outcome inside a [`PrintReadyReport`].
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PrintReadyRule {
    pub id: String,
    /// "pass" | "warn" | "fail" — string, not an enum, so report consumers
    /// (editor, agent loop, bulk gate) stay decoupled from rule evolution.
    pub status: String,
    pub detail: String,
}

/// Print W6: the structured preflight verdict attached to print-intent PDF
/// exports. `status` is the worst rule status; a "fail" gates bulk runs.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PrintReadyReport {
    pub ruleset: String,
    pub status: String,
    pub rules: Vec<PrintReadyRule>,
}

impl PrintReadyReport {
    pub fn failed(&self) -> bool {
        self.status == "fail"
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ExportResult {
    pub artifacts: Vec<ExportArtifact>,
    pub diagnostics: Vec<Diagnostic>,
    /// Present on print-intent PDF exports (print W6 preflight).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub print_ready: Option<PrintReadyReport>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ExportError {
    pub code: &'static str,
    pub message: String,
    pub diagnostics: Vec<Diagnostic>,
}

impl ExportError {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            diagnostics: Vec::new(),
        }
    }

    pub fn with_diagnostics(mut self, diagnostics: Vec<Diagnostic>) -> Self {
        self.diagnostics = diagnostics;
        self
    }
}

impl fmt::Display for ExportError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl Error for ExportError {}

pub trait ExportAdapter {
    fn export(&self, scene: &Scene, request: &ExportRequest) -> Result<ExportResult, ExportError>;
}
