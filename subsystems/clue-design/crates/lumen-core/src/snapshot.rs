use crate::scene::Scene;
use std::error::Error;
use std::fmt;

pub type SnapshotResult<T> = Result<T, SnapshotError>;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SnapshotError {
    pub code: &'static str,
    pub message: String,
}

impl SnapshotError {
    fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

impl fmt::Display for SnapshotError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl Error for SnapshotError {}

impl Scene {
    pub fn to_canonical_json(&self) -> SnapshotResult<String> {
        serde_json::to_string_pretty(self)
            .map_err(|error| SnapshotError::new("snapshot.serialize", error.to_string()))
    }

    pub fn from_json(source: &str) -> SnapshotResult<Self> {
        serde_json::from_str(source)
            .map_err(|error| SnapshotError::new("snapshot.deserialize", error.to_string()))
    }
}
