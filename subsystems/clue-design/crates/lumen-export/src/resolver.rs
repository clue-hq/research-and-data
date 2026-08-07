//! Asset byte resolution for export adapters.
//!
//! The Scene never carries asset bytes; `AssetRecord` is metadata plus an
//! opaque location reference. Export adapters that need real bytes (data URIs
//! in SVG, decoded pixels in PNG) resolve them through this trait. Storage
//! knowledge stays adapter-side: implementations may read fixtures, a local
//! content-addressed store, or a remote object store, but `lumen-core` never
//! learns about any of them.

use lumen_core::{AssetId, AssetRecord};
use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;

/// Bytes resolved for one asset, with the MIME type the bytes actually carry
/// (which may be sniffed at ingest rather than declared on the record).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResolvedAssetBytes {
    pub mime_type: String,
    pub bytes: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AssetResolveError {
    pub code: &'static str,
    pub message: String,
}

impl AssetResolveError {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

impl fmt::Display for AssetResolveError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl Error for AssetResolveError {}

/// Resolves the bytes behind an asset record. Implementations must never
/// panic on missing bytes: export surfaces resolution failures as
/// diagnostics, not crashes.
pub trait AssetByteResolver: fmt::Debug + Send + Sync {
    fn resolve(&self, asset: &AssetRecord) -> Result<ResolvedAssetBytes, AssetResolveError>;
}

/// In-memory resolver for fixtures and tests. Bytes register either against
/// an asset id or against a content digest value; digest entries let multiple
/// records that share bytes resolve without re-registration, mirroring the
/// content-addressed store.
#[derive(Clone, Debug, Default)]
pub struct FixtureAssetResolver {
    by_asset_id: BTreeMap<AssetId, ResolvedAssetBytes>,
    by_digest: BTreeMap<String, ResolvedAssetBytes>,
}

impl FixtureAssetResolver {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_asset_bytes(
        mut self,
        asset_id: impl Into<AssetId>,
        mime_type: impl Into<String>,
        bytes: impl Into<Vec<u8>>,
    ) -> Self {
        self.insert_asset_bytes(asset_id, mime_type, bytes);
        self
    }

    pub fn with_digest_bytes(
        mut self,
        digest_value: impl Into<String>,
        mime_type: impl Into<String>,
        bytes: impl Into<Vec<u8>>,
    ) -> Self {
        self.insert_digest_bytes(digest_value, mime_type, bytes);
        self
    }

    pub fn insert_asset_bytes(
        &mut self,
        asset_id: impl Into<AssetId>,
        mime_type: impl Into<String>,
        bytes: impl Into<Vec<u8>>,
    ) {
        self.by_asset_id.insert(
            asset_id.into(),
            ResolvedAssetBytes {
                mime_type: mime_type.into(),
                bytes: bytes.into(),
            },
        );
    }

    pub fn insert_digest_bytes(
        &mut self,
        digest_value: impl Into<String>,
        mime_type: impl Into<String>,
        bytes: impl Into<Vec<u8>>,
    ) {
        self.by_digest.insert(
            digest_value.into(),
            ResolvedAssetBytes {
                mime_type: mime_type.into(),
                bytes: bytes.into(),
            },
        );
    }
}

impl AssetByteResolver for FixtureAssetResolver {
    fn resolve(&self, asset: &AssetRecord) -> Result<ResolvedAssetBytes, AssetResolveError> {
        if let Some(found) = self.by_asset_id.get(&asset.id) {
            return Ok(found.clone());
        }
        if let Some(digest) = &asset.media.digest {
            if let Some(found) = self.by_digest.get(&digest.value) {
                return Ok(found.clone());
            }
        }
        Err(AssetResolveError::new(
            "asset.bytes_missing",
            format!("no fixture bytes registered for asset {}", asset.id),
        ))
    }
}
