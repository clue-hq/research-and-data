//! Content-addressed asset byte storage.
//!
//! Decision 2 of the Phase E plan: storage is a trait with a local adapter
//! first. Keys are SHA-256 digests of the bytes; the canonical layout is
//! `{root}/sha256/{first-two-hex}/{digest}` and `relative_path` in
//! [`StoredObject`] is exactly that relative path, so byte serving never
//! needs a second source of path truth. Bytes are stored exactly once per
//! digest (dedup); writes are atomic-by-rename so a crashed ingest never
//! leaves a half-written digest path.

use sha2::{Digest, Sha256};
use std::error::Error;
use std::fmt;
use std::fs;
use std::path::{Component, Path, PathBuf};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StoredObject {
    /// SHA-256 of the bytes, lowercase hex.
    pub digest_value: String,
    pub byte_length: u64,
    /// Path relative to the store root, e.g. `sha256/ab/abcd...`.
    pub relative_path: String,
    /// True when the digest already existed and no bytes were written.
    pub deduplicated: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AssetStoreError {
    pub code: &'static str,
    pub message: String,
}

impl AssetStoreError {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
}

impl fmt::Display for AssetStoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl Error for AssetStoreError {}

/// Content-addressed byte storage. Implementations must be safe to call
/// from multiple processes serving the same root.
pub trait AssetStore: fmt::Debug + Send + Sync {
    fn put(&self, bytes: &[u8]) -> Result<StoredObject, AssetStoreError>;
    fn get(&self, relative_path: &str) -> Result<Vec<u8>, AssetStoreError>;
    fn contains_digest(&self, digest_value: &str) -> bool;
    /// Remove the bytes for a digest. Returns true when bytes existed and
    /// were removed. Reference counting is the caller's responsibility
    /// (Decision 4: bytes leave the store only when no record references
    /// the digest).
    fn delete_digest(&self, digest_value: &str) -> Result<bool, AssetStoreError>;
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    let digest = hasher.finalize();
    let mut out = String::with_capacity(64);
    for byte in digest {
        use fmt::Write;
        let _ = write!(out, "{byte:02x}");
    }
    out
}

/// Canonical relative path for a digest inside any store implementation.
pub fn digest_relative_path(digest_value: &str) -> Result<String, AssetStoreError> {
    if digest_value.len() != 64 || !digest_value.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(AssetStoreError::new(
            "store.invalid_digest",
            format!("digest {digest_value:?} is not a 64-char hex sha256 value"),
        ));
    }
    let normalized = digest_value.to_ascii_lowercase();
    Ok(format!("sha256/{}/{}", &normalized[..2], normalized))
}

/// Local-filesystem content-addressed store.
#[derive(Clone, Debug)]
pub struct LocalAssetStore {
    root: PathBuf,
}

impl LocalAssetStore {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    fn absolute_path(&self, relative_path: &str) -> Result<PathBuf, AssetStoreError> {
        let relative = Path::new(relative_path);
        let traversal_safe = relative
            .components()
            .all(|component| matches!(component, Component::Normal(_)));
        if relative_path.is_empty() || !traversal_safe {
            return Err(AssetStoreError::new(
                "store.invalid_path",
                format!("relative path {relative_path:?} is not a safe store path"),
            ));
        }
        Ok(self.root.join(relative))
    }
}

impl AssetStore for LocalAssetStore {
    fn put(&self, bytes: &[u8]) -> Result<StoredObject, AssetStoreError> {
        let digest_value = sha256_hex(bytes);
        let relative_path = digest_relative_path(&digest_value)?;
        let path = self.absolute_path(&relative_path)?;

        if path.is_file() {
            return Ok(StoredObject {
                digest_value,
                byte_length: bytes.len() as u64,
                relative_path,
                deduplicated: true,
            });
        }

        let parent = path.parent().ok_or_else(|| {
            AssetStoreError::new("store.invalid_path", "digest path has no parent directory")
        })?;
        fs::create_dir_all(parent).map_err(|error| {
            AssetStoreError::new(
                "store.io",
                format!(
                    "could not create store directory {}: {error}",
                    parent.display()
                ),
            )
        })?;

        // Atomic-by-rename: write a unique temp file next to the target and
        // rename it into place. A concurrent identical put either wins the
        // rename or loses to identical bytes; both outcomes are correct.
        let temp_path = parent.join(format!(
            ".tmp-{}-{}",
            std::process::id(),
            &digest_value[..16]
        ));
        fs::write(&temp_path, bytes).map_err(|error| {
            AssetStoreError::new(
                "store.io",
                format!("could not write {}: {error}", temp_path.display()),
            )
        })?;
        fs::rename(&temp_path, &path).map_err(|error| {
            let _ = fs::remove_file(&temp_path);
            AssetStoreError::new(
                "store.io",
                format!("could not commit {}: {error}", path.display()),
            )
        })?;

        Ok(StoredObject {
            digest_value,
            byte_length: bytes.len() as u64,
            relative_path,
            deduplicated: false,
        })
    }

    fn get(&self, relative_path: &str) -> Result<Vec<u8>, AssetStoreError> {
        let path = self.absolute_path(relative_path)?;
        fs::read(&path).map_err(|error| {
            AssetStoreError::new(
                "store.bytes_missing",
                format!("could not read {}: {error}", path.display()),
            )
        })
    }

    fn contains_digest(&self, digest_value: &str) -> bool {
        digest_relative_path(digest_value)
            .and_then(|relative| self.absolute_path(&relative))
            .map(|path| path.is_file())
            .unwrap_or(false)
    }

    fn delete_digest(&self, digest_value: &str) -> Result<bool, AssetStoreError> {
        let relative = digest_relative_path(digest_value)?;
        let path = self.absolute_path(&relative)?;
        if !path.is_file() {
            return Ok(false);
        }
        fs::remove_file(&path).map_err(|error| {
            AssetStoreError::new(
                "store.io",
                format!("could not delete {}: {error}", path.display()),
            )
        })?;
        Ok(true)
    }
}
