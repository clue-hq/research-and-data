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

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ExportResult {
    pub artifacts: Vec<ExportArtifact>,
    pub diagnostics: Vec<Diagnostic>,
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
