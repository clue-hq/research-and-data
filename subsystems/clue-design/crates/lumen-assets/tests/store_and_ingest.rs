use lumen_assets::{
    digest_relative_path, ingest, sha256_hex, AssetStore, IngestRequest, LocalAssetStore,
};
use lumen_core::AssetKind;

const LOGO_PNG: &[u8] = include_bytes!("../../lumen-export/fixtures/assets/acme-logo-8x8-red.png");

fn temp_store() -> (tempfile::TempDir, LocalAssetStore) {
    let dir = tempfile::tempdir().expect("tempdir");
    let store = LocalAssetStore::new(dir.path().to_path_buf());
    (dir, store)
}

#[test]
fn put_stores_bytes_under_digest_key() {
    let (_dir, store) = temp_store();

    let stored = store.put(LOGO_PNG).expect("put");

    assert_eq!(stored.digest_value, sha256_hex(LOGO_PNG));
    assert_eq!(
        stored.relative_path,
        format!(
            "sha256/{}/{}",
            &stored.digest_value[..2],
            stored.digest_value
        )
    );
    assert!(!stored.deduplicated);
    assert!(store.contains_digest(&stored.digest_value));
    assert_eq!(store.get(&stored.relative_path).expect("get"), LOGO_PNG);
}

#[test]
fn duplicate_put_dedups_bytes() {
    let (dir, store) = temp_store();

    let first = store.put(LOGO_PNG).expect("first put");
    let second = store.put(LOGO_PNG).expect("second put");

    assert!(!first.deduplicated);
    assert!(second.deduplicated);
    assert_eq!(first.relative_path, second.relative_path);

    let stored_files: Vec<_> = walkdir(dir.path());
    assert_eq!(
        stored_files.len(),
        1,
        "exactly one stored file: {stored_files:?}"
    );
}

#[test]
fn delete_digest_removes_bytes_once() {
    let (_dir, store) = temp_store();
    let stored = store.put(LOGO_PNG).expect("put");

    assert!(store.delete_digest(&stored.digest_value).expect("delete"));
    assert!(!store.contains_digest(&stored.digest_value));
    assert!(!store.delete_digest(&stored.digest_value).expect("redelete"));
    assert!(store.get(&stored.relative_path).is_err());
}

#[test]
fn traversal_paths_are_rejected() {
    let (_dir, store) = temp_store();

    let error = store.get("../outside").expect_err("traversal must fail");
    assert_eq!(error.code, "store.invalid_path");
    let error = store.get("/etc/passwd").expect_err("absolute must fail");
    assert_eq!(error.code, "store.invalid_path");
    assert!(digest_relative_path("not-a-digest").is_err());
}

#[test]
fn ingest_sniffs_and_accepts_compatible_declarations() {
    let output = ingest(&IngestRequest {
        declared_mime: Some("image/png"),
        filename: Some("logo.png"),
        kind_hint: Some(AssetKind::Logo),
        ..IngestRequest::new(LOGO_PNG)
    })
    .expect("ingest");

    assert_eq!(output.sniffed_mime, "image/png");
    assert_eq!(output.kind, AssetKind::Logo);
    assert_eq!(output.bytes, LOGO_PNG);
}

#[test]
fn ingest_rejects_mime_mismatch() {
    let error = ingest(&IngestRequest {
        declared_mime: Some("image/jpeg"),
        ..IngestRequest::new(LOGO_PNG)
    })
    .expect_err("mismatch must reject");

    assert_eq!(error.code, "ingest.mime_mismatch");
    assert_eq!(error.diagnostic.code, "LUMA0600");
}

#[test]
fn ingest_enforces_size_limit() {
    let error = ingest(&IngestRequest {
        max_bytes: 16,
        ..IngestRequest::new(LOGO_PNG)
    })
    .expect_err("oversize must reject");

    assert_eq!(error.code, "ingest.too_large");
    assert_eq!(error.diagnostic.code, "LUMA0601");
}

#[test]
fn ingest_flags_unknown_content_as_other() {
    let output =
        ingest(&IngestRequest::new(b"just some text")).expect("unknown content still ingests");

    assert_eq!(output.sniffed_mime, "application/octet-stream");
    assert_eq!(output.kind, AssetKind::Other);
    assert!(output
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMA0602"));
}

#[test]
fn incompatible_kind_hint_downgrades_with_warning() {
    let output = ingest(&IngestRequest {
        kind_hint: Some(AssetKind::Font),
        ..IngestRequest::new(LOGO_PNG)
    })
    .expect("ingest");

    assert_eq!(output.kind, AssetKind::RasterImage);
    assert!(output
        .diagnostics
        .iter()
        .any(|diagnostic| diagnostic.code == "LUMA0602"));
}

fn walkdir(root: &std::path::Path) -> Vec<std::path::PathBuf> {
    let mut files = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        for entry in std::fs::read_dir(&dir).expect("read_dir") {
            let path = entry.expect("entry").path();
            if path.is_dir() {
                stack.push(path);
            } else {
                files.push(path);
            }
        }
    }
    files
}
