//! Embed the engine commit at build time for the W5 version handshake.
//! The editor compares this against the API's build-info endpoint and
//! downgrades to server-only mode on mismatch — never mixed-version
//! optimistic editing.

use std::process::Command;

fn main() {
    let commit = Command::new("git")
        .args(["rev-parse", "--short=12", "HEAD"])
        .output()
        .ok()
        .filter(|output| output.status.success())
        .and_then(|output| String::from_utf8(output.stdout).ok())
        .map(|stdout| stdout.trim().to_owned())
        .filter(|commit| !commit.is_empty())
        .unwrap_or_else(|| "unknown".to_owned());
    println!("cargo:rustc-env=LUMEN_ENGINE_COMMIT={commit}");

    // Re-run when HEAD moves so the embedded commit cannot go stale.
    if let Some(head_path) = Command::new("git")
        .args(["rev-parse", "--git-path", "HEAD"])
        .output()
        .ok()
        .filter(|output| output.status.success())
        .and_then(|output| String::from_utf8(output.stdout).ok())
    {
        let head_path = head_path.trim();
        if !head_path.is_empty() {
            println!("cargo:rerun-if-changed={head_path}");
        }
    }
}
