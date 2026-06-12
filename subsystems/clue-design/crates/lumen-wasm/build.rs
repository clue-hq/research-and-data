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

    // Re-run when the commit changes. Watching the HEAD file alone is not
    // enough: on a branch, HEAD's content is the branch NAME, which does
    // not change on commit — the branch ref file does. Watch both.
    for args in [
        vec!["rev-parse", "--git-path", "HEAD"],
        vec!["rev-parse", "--git-path", "refs/heads"],
    ] {
        if let Some(path) = Command::new("git")
            .args(&args)
            .output()
            .ok()
            .filter(|output| output.status.success())
            .and_then(|output| String::from_utf8(output.stdout).ok())
        {
            let path = path.trim();
            if !path.is_empty() {
                println!("cargo:rerun-if-changed={path}");
            }
        }
    }
}
