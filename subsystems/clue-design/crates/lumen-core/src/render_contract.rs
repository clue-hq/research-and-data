use crate::ids::PageId;
use serde::{Deserialize, Serialize};
use std::error::Error;
use std::fmt;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RenderIntent {
    EditorPreview,
    Export,
    AgentCritique,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum RenderTarget {
    Svg,
    Png { scale: f64 },
    Pdf,
    KonvaScene,
    FigmaManifest,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RenderManifest {
    pub target: RenderTarget,
    pub page_ids: Vec<PageId>,
    pub mime_type: String,
    pub bytes: Option<Vec<u8>>,
    pub sidecar_json: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RendererError {
    pub code: &'static str,
    pub message: String,
}

impl RendererError {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

impl fmt::Display for RendererError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl Error for RendererError {}

pub trait RendererAdapter {
    fn render(
        &self,
        scene: &crate::scene::Scene,
        target: RenderTarget,
        intent: RenderIntent,
        page_ids: &[PageId],
    ) -> Result<RenderManifest, RendererError>;
}
