//! Embed the engine stamp at build time for the W5 version handshake.
//! The editor compares this against the API's build-info endpoint and
//! downgrades to server-only mode on mismatch — never mixed-version
//! optimistic editing.
//!
//! The stamp is a content hash of the shared engine sources (see
//! `crates/build_support/engine_stamp.rs`, `include!`d below and shared
//! verbatim with lumen-api-helper's build.rs): identical sources yield an
//! identical stamp, so commits alone can no longer desynchronize the two
//! sides. Class fix landed 2026-07-10.

include!("../build_support/engine_stamp.rs");

fn main() {
    emit_engine_stamp();
}
