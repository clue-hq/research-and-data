use serde::{Deserialize, Serialize};
use std::error::Error;
use std::fmt;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IdError {
    value: String,
}

impl IdError {
    fn new(value: impl Into<String>) -> Self {
        Self {
            value: value.into(),
        }
    }
}

impl fmt::Display for IdError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "invalid stable id: {}", self.value)
    }
}

impl Error for IdError {}

fn validate_stable_id(value: &str) -> Result<(), IdError> {
    if value.is_empty() {
        return Err(IdError::new(value));
    }

    let valid = value
        .bytes()
        .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-'));

    if valid {
        Ok(())
    } else {
        Err(IdError::new(value))
    }
}

macro_rules! stable_id_type {
    ($name:ident) => {
        #[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize, Deserialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            pub fn new(value: impl Into<String>) -> Result<Self, IdError> {
                let value = value.into();
                validate_stable_id(&value)?;
                Ok(Self(value))
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl From<&str> for $name {
            fn from(value: &str) -> Self {
                Self(value.to_owned())
            }
        }

        impl From<String> for $name {
            fn from(value: String) -> Self {
                Self(value)
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str(&self.0)
            }
        }
    };
}

stable_id_type!(DocumentId);
stable_id_type!(PageId);
stable_id_type!(NodeId);
stable_id_type!(SlotId);
stable_id_type!(PaintId);
stable_id_type!(AssetId);
stable_id_type!(BrandKitId);
stable_id_type!(TemplateRevisionId);
stable_id_type!(OperationId);

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct SlotKey(String);

impl SlotKey {
    pub fn new(value: impl Into<String>) -> Result<Self, IdError> {
        let value = value.into();
        if value.is_empty() {
            return Err(IdError::new(value));
        }

        let valid = value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-' | b'.'));

        if valid {
            Ok(Self(value))
        } else {
            Err(IdError::new(value))
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl From<&str> for SlotKey {
    fn from(value: &str) -> Self {
        Self(value.to_owned())
    }
}

impl From<String> for SlotKey {
    fn from(value: String) -> Self {
        Self(value)
    }
}

impl fmt::Display for SlotKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
