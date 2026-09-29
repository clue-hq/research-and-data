# Native tab reuse repair — 2026-09-28

Continued the active website-quality goal on `codex/design-agent-v1` from
`ce48fa44`. Implemented the bounded runtime defect reproduced in the previous
audit. No new model generation, ingestion, live DB/page write, service restart,
push or standalone page. Goal remains incomplete; no-new-run restriction holds.

- Checked vocabulary repair derives internal tab dependencies from accepted
  nodes. Sanitized artifact identity/read validates owned roots, IDs and ARIA
  relationships. Ordinary captures remain v1; native payloads/packages use v2.
- Registry, pin admission, isolation, render packages and explicit helper action
  preserve dependencies. Runtime supplies approved tab CSS/JS and namespaces
  control IDs per pin; nested groups use local ownership. No foreign JS replay.
- Unsupported native dependencies refuse reusable mint; typed replacement is
  retained. Raw native-artifact replacement cannot silently erase dependency
  custody. Exact text/link variants preserve it.
- Interaction capture includes native groups inside fragments. Inspection
  separates a declared runtime from an observed behavior test. Source-readiness
  repair guidance documents the capability and current limits.
- Supervised read-only review found command-field, CSS-specificity and dialog
  polyfill ownership bugs; all corrected. Captured lookalikes remain unowned.
- Production-path offline browser fixtures cover four states at two widths,
  keyboard behavior, reduced motion, independent duplicate/nested tabs, custom
  spacing and unsupported native mint. Separate real registry custody test uses
  only a disposable database created for this session.

Verification: Rust workspace tests, release helper, wasm rebuild
and handshake passed. Full agent tests: 2,821 passed, one skipped, five failed.
Four failures were invocation-relative helper paths; absolute-path retry passed
31 selected tests. Remaining phrase assertion is unchanged at HEAD (confirmed
by AST docstring equality); do not report the full suite green. Final expanded
four-panel browser file passes five cases. Initial wasm tooling install was
sandbox-denied; normal escalated rebuild succeeded. No new runtime env flags.

Next: preserve source card geometry and control/media mapping with an offline
comparison, then apply trace-derived copy/media/type guidance. The last live
run deliberately chose a static fallback; do not attribute that historical
decision to the independently reproduced runtime-loss bug. Neither this repair
nor test success establishes an improved native account page.

API gate: 2,904 passed, six skipped, six failed. Four incomplete isolation
fixtures gained the payload field now consumed by the production path; the
isolation/font files plus new dependency/custody checks pass 39/39. Two remaining
capture-readiness tests fail for fake-agent `web_doc` absence; replaying the exact
HEAD method reproduces both failures. The method itself is unchanged. These and
the agent wording assertion remain known baseline test issues, not a fully
green-suite claim. Final fatal-error lint and whitespace checks pass.

Closing state: scoped local code/docs/tests/build checkpoint, no push. Source
and wasm/helper were rebuilt; live service processes were not restarted and
saved pages were not regenerated. Session-created disposable database removed
after tests. Preserve pre-existing unrelated account-test, import-note and older
audit edits. No raw traces, customer dossier or credentials recorded here.
