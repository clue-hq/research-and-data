# Native runtime reuse audit — 2026-09-28

Continued active goal from `905f8925` on `codex/design-agent-v1`. No new
generation, provider request, live DB/page write, ingestion, restart or push.
Existing unrelated working-tree edits preserved. Goal remains incomplete.

- Rechecked actual saved tool arguments/results with one supervised read-only
  agent. Earlier native-tab repair remained draft; typed nodes stayed on its
  page. Later independent run deliberately authored static replacement. No
  evidence that a fragment runtime-loss bug caused that historical fallback.
- Latest run explicitly read account/copy/source/media skills, but no explicit
  motion/repair skill read before choosing static. Injected descriptions may
  still have been present; do not claim no motion guidance existed.
- Offline counterexample uses native author/repair, actual helper render,
  sanitizer, slot detection and artifact builder with an in-memory registry.
  Authored tabs work; pinned repaired tabs omit approved runtime and base CSS.
  Adding only the known runtime restores one copy. With two pins, duplicate
  IDs plus global panel lookup changes the other copy's panel instead.
- Existing interaction capture inspects typed-native groups and CSS-radio
  fragment groups; native-tab markup in fragment leaves is not discovered.
  That last finding is code inspection, not a separate browser assertion.
- Expanded the cross-run audit with exact historical evidence, browser replay
  outcomes, causal limits and dependency/instance-identity acceptance criteria.
  Derived replay and checksums stay local under `.local-setup/native-account-skills/`
  `trace-audit-20260928/interaction-reuse/`. No production fix in this checkpoint.

Verification: four browser cases reproduced with all browser networking blocked;
asserted the before/after selections and panel visibility. Initial fixture had
wrong slot-manifest access, corrected; first Chromium launch sandbox-denied,
authorized offline retry completed. One trace-extract command used system Python
without selectolax; retried with repo venv. Styling loss independently checked
against saved rendered HTML. No broad suite needed for report-only changes.

Next: bounded native reconstruction preserving source geometry, approved
runtime/styles and independent repeated instances; include fragment behavior in
observations. Then copy/media/type corrections and offline comparison. Another
paid page remains subject to the user's no-new-run restriction. Do not equate
more measurement tooling or saved reports with improved native page quality.

Closing state: audit-only checkpoint; runtime and saved app pages unchanged.
