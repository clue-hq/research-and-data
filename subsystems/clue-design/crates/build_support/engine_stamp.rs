// Shared engine-stamp derivation for the W5 version handshake.
//
// This file is `include!`d verbatim from BOTH `crates/lumen-wasm/build.rs`
// and `crates/lumen-api-helper/build.rs` so the two artifacts can never
// compute the stamp by different logic. It requires a `sha2` build-dependency
// in each including crate. (Plain `//` comments, not `//!`: an included
// fragment cannot carry inner doc comments.)
//
// The stamp is a *content hash of the shared engine sources*, not a git
// commit. The handshake exists to catch the editor's in-browser WASM engine
// diverging from the API helper's engine; the only local crate BOTH artifacts
// compile — and thus the crate whose divergence would make optimistic
// client-side edits disagree with the server — is `lumen-core`. Its `src/`
// tree plus `Cargo.toml` is the shared-semantics closure. Identical sources
// therefore always yield an identical stamp regardless of commit choreography,
// so commits alone can no longer desynchronize the two sides.

use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};

/// Crates whose sources define the *shared* engine semantics both artifacts
/// execute. Paths are relative to the including crate's `CARGO_MANIFEST_DIR`
/// (`crates/<name>`), so `../lumen-core` resolves identically from either side.
const SHARED_ENGINE_CRATES: &[&str] = &["../lumen-core"];

/// Compute the engine stamp and emit it as `LUMEN_ENGINE_COMMIT`, plus a
/// `cargo:rerun-if-changed` line for every hashed file so a source edit can
/// never leave a stale stamp baked into the artifact.
fn emit_engine_stamp() {
    let manifest_dir = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap());

    // Collect (relative-key, absolute-path) for every hashed input.
    let mut files: Vec<(String, PathBuf)> = Vec::new();
    for crate_rel in SHARED_ENGINE_CRATES {
        let crate_root = manifest_dir.join(crate_rel);
        let crate_key = crate_rel.trim_start_matches("./");

        // Cargo.toml governs dependency + feature semantics — hash it too.
        let cargo_toml = crate_root.join("Cargo.toml");
        if cargo_toml.is_file() {
            files.push((format!("{crate_key}/Cargo.toml"), cargo_toml));
        }

        // Every `src/**/*.rs` — the compiled library sources. `tests/` are
        // deliberately excluded: they do not affect either shipped artifact.
        let src_root = crate_root.join("src");
        collect_rs_files(&src_root, &src_root, crate_key, &mut files);
    }

    // Deterministic order: sort by the forward-slash relative key.
    files.sort_by(|a, b| a.0.cmp(&b.0));

    let mut hasher = Sha256::new();
    for (key, path) in &files {
        let content = std::fs::read(path)
            .unwrap_or_else(|e| panic!("engine-stamp: cannot read {}: {e}", path.display()));
        // Hash path AND content so a rename changes the stamp.
        hasher.update(key.as_bytes());
        hasher.update([0u8]);
        hasher.update(&content);
        hasher.update([0u8]);
        println!("cargo:rerun-if-changed={}", path.display());
    }
    let digest = hasher.finalize();

    // First 12 hex chars — same width the old git `--short=12` stamp used, so
    // downstream consumers that only compare for equality are unaffected.
    let stamp: String = digest.iter().take(6).map(|b| format!("{b:02x}")).collect();

    println!("cargo:rustc-env=LUMEN_ENGINE_COMMIT={stamp}");
}

/// Recursively collect `*.rs` files under `dir`, keying each by its path
/// relative to the crate root with forward slashes.
fn collect_rs_files(dir: &Path, src_root: &Path, crate_key: &str, out: &mut Vec<(String, PathBuf)>) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    // Sort entries so traversal (and thus rerun-if-changed emission) is stable.
    let mut entries: Vec<PathBuf> = entries.filter_map(|e| e.ok().map(|e| e.path())).collect();
    entries.sort();
    for path in entries {
        if path.is_dir() {
            collect_rs_files(&path, src_root, crate_key, out);
        } else if path.extension().and_then(|e| e.to_str()) == Some("rs") {
            let rel = path
                .strip_prefix(src_root.parent().unwrap())
                .unwrap()
                .to_string_lossy()
                .replace('\\', "/");
            out.push((format!("{crate_key}/{rel}"), path));
        }
    }
}
