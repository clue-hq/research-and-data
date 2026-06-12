//! Store-backed implementation of the export asset byte resolver.
//!
//! This is the composition point between `lumen-assets` (storage) and
//! `lumen-export` (byte resolution for embedding): the two crates do not
//! depend on each other, the helper wires them together.

use lumen_assets::{digest_relative_path, AssetStore, LocalAssetStore};
use lumen_core::AssetRecord;
use lumen_export::{AssetByteResolver, AssetResolveError, ResolvedAssetBytes};
use std::path::PathBuf;

pub const LOCAL_STORE_PROVIDER: &str = "local-store";

#[derive(Debug)]
pub struct StoreBackedResolver {
    store: LocalAssetStore,
}

impl StoreBackedResolver {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self {
            store: LocalAssetStore::new(root),
        }
    }
}

impl AssetByteResolver for StoreBackedResolver {
    fn resolve(&self, asset: &AssetRecord) -> Result<ResolvedAssetBytes, AssetResolveError> {
        let relative_path = match &asset.media.location {
            Some(location) if location.provider == LOCAL_STORE_PROVIDER => {
                location.opaque_ref.clone()
            }
            _ => match &asset.media.digest {
                // Digest fallback: content-addressing means any record that
                // knows its sha256 can resolve regardless of provider label.
                Some(digest) if digest.algorithm.eq_ignore_ascii_case("sha256") => {
                    digest_relative_path(&digest.value).map_err(|error| {
                        AssetResolveError::new("asset.invalid_digest", error.to_string())
                    })?
                }
                _ => {
                    return Err(AssetResolveError::new(
                        "asset.unresolvable_location",
                        format!(
                            "asset {} has neither a local-store location nor a sha256 digest",
                            asset.id
                        ),
                    ))
                }
            },
        };

        let bytes = self
            .store
            .get(&relative_path)
            .map_err(|error| AssetResolveError::new("asset.bytes_missing", error.to_string()))?;

        let mime_type = asset
            .media
            .mime_type
            .clone()
            .or_else(|| lumen_assets::sniff_mime(&bytes).map(str::to_owned))
            .unwrap_or_else(|| "application/octet-stream".to_owned());

        Ok(ResolvedAssetBytes { mime_type, bytes })
    }
}
