use crate::ids::{AssetId, NodeId, PageId, SlotId};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DiagnosticSeverity {
    Error,
    Warning,
    Advice,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Phase {
    Contract,
    Operation,
    Validation,
    Brand,
    Dsl,
    Layout,
    Export,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "id", rename_all = "snake_case")]
pub enum DiagnosticSubject {
    Document,
    Page(PageId),
    Node(NodeId),
    Slot(SlotId),
    Asset(AssetId),
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Diagnostic {
    pub severity: DiagnosticSeverity,
    pub phase: Phase,
    pub code: String,
    pub message: String,
    pub subject: Option<DiagnosticSubject>,
    pub hint: Option<String>,
}

impl Diagnostic {
    pub fn error(
        phase: Phase,
        code: impl Into<String>,
        message: impl Into<String>,
        subject: Option<DiagnosticSubject>,
    ) -> Self {
        Self {
            severity: DiagnosticSeverity::Error,
            phase,
            code: code.into(),
            message: message.into(),
            subject,
            hint: None,
        }
    }

    pub fn warning(
        phase: Phase,
        code: impl Into<String>,
        message: impl Into<String>,
        subject: Option<DiagnosticSubject>,
    ) -> Self {
        Self {
            severity: DiagnosticSeverity::Warning,
            phase,
            code: code.into(),
            message: message.into(),
            subject,
            hint: None,
        }
    }

    pub fn with_hint(mut self, hint: impl Into<String>) -> Self {
        self.hint = Some(hint.into());
        self
    }
}
