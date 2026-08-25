# 2026-08-24 — Fast Loop v1 P0.2 + P0.3 (backend): LUMV0820 repairability + export severity split

Base: `59b55793` (`docs(design): ratify deepagent fast-loop v1 spec + session forensics note`).
Spec: `subsystems/clue-design/docs/deepagent-fast-loop-v1-spec.md` §4 P0.2/P0.3, ruling R5.
Scope: backend only. `apps/frontend/` deliberately untouched (owned by the
small-bugs-lane agent, which landed the visible-failure UI as `15c713a2`).

## The defect, restated precisely

Preflight raised `LUMV0820` ("image-like slot needs an image policy") at ERROR
severity. Two independent failures followed:

1. **Unrepairable.** The DSL's only slot constructor is `Slot::text_short`, so
   every `image … slot(key)` line produced an Image slot with
   `image_policy: None` and an instant error — and no DSL operation could set a
   policy. The agent probed for a repair that did not exist.
2. **Unexportable.** The export gate refused on any error severity, so a scene
   that rendered previews cleanly all run had every export (PNG/SVG/PDF/preview)
   refused, while the run still finalized "succeeded".

Corroborating evidence found during the work: `validation.rs:464-473` already
emits `LUMV0503` — the *validation-phase twin* of the same condition — as a
**warning**. The engine itself had already judged this a lint; only the layout
phase escalated it to an error.

## What shipped

### P0.2 — real repair path (Rust, `crates/lumen-core`)
- `slots.rs`: `impl Default for ImagePolicy` — `fit: Cover`,
  `preserve_transparency: true`, everything else `None`. Matches the convention
  already documented in `grammar.md` ("default is `fit:cover`").
- `dsl.rs::emit_slot_binding`: image-like slots are **born** with that default.
  New scenes can no longer trip LUMV0820 at all. Text slots keep `None`.
- `editing.rs`: `SlotEditPatch` gains `image_policy: OptionalFieldPatch<ImagePolicy>`,
  applied in `build_slot_modify`. Undo/redo came free (`UpsertSlot`'s inverse
  already round-trips the prior slot).
- `dsl.rs`: new `DslProperty::SlotImagePolicy` + `parse_image_policy`, reachable as
  `#slot:key image_policy(cover)` / `image_policy(fit=…, focal_x=…, focal_y=…,
  min_dpi=…, aspect=…, preserve_transparency=…)` / `image_policy(none)` to clear.
  Unspecified members fall back to the default, so short forms are complete
  policies. Invalid values are refused at compile time under **`LUMD0276`**,
  mirroring the LUMV0821/0822 preflight rules so the author sees the problem on
  the line that wrote it.
  - **Code-collision caught in review:** first draft used `LUMD0222`, which is
    already "padding arity". `LUMD0276` verified free across `crates/ apps/ docs/`.

LUMV0820 was deliberately **left at error severity** in preflight: it is now
genuinely repairable, so it satisfies the spec's "no preflight error class
without a documented repair operation" without a demotion.

### P0.3 — export severity split (Python, `apps/api/lumen_api/export_policy.py`, new)
- `ADVISORY_EXPORT_DIAGNOSTIC_CODES` — explicit allowlist, currently **only
  `LUMV0820`**, each entry carrying a written justification.
- `is_blocking_export_diagnostic` is **fail-closed**: error severity blocks
  unless the code is explicitly classified advisory. Unknown codes, and
  malformed diagnostics with no code, block.
- `_REVIEWED_AND_LEFT_BLOCKING` documents codes considered and rejected
  (`LUMV0821`, `LUMV0822`, `LUMV0823`, `LUMV0810`) with reasoning, so the next
  reader does not re-derive it. `LUMV0823` (print min_dpi) is the most plausible
  future candidate — held back deliberately, wants a print stakeholder.
- Wired at both export gates in `main.py`: `/documents/{id}/export`
  (pre-render gate + post-render status) and `/export-preview`. Responses gain a
  top-level `warnings: [{code, message, severity: "advisory", engine_severity,
  subject, hint}]` and `preflight.advisory_warnings`.
- `preflight.has_errors` is no longer consulted at the gate. Verified safe: the
  helper computes it as `any(severity == Error)` over the *same* diagnostics list
  it returns (`lumen-api-helper/src/main.rs`, PreflightScene arm, after
  `extend(font_diagnostics)`), so it carries no extra information — and
  consulting it would have re-blocked the very codes the split exists to pass.
  It still rides the response as the raw engine signal.

### Finalize guard (`agent_runtime/lumen_agent/tools/substrate.py`)
- `preflight_design` now stashes the raw engine diagnostics on
  `self._latest_preflight_diagnostics`.
- `finalize_run` refuses `status == "accepted"` while a **blocking** export
  error stands, returning an actionable `REFUSED: …` string (the same pattern as
  the existing reference-fidelity guard). Advisory lints do **not** refuse — they
  are appended to the summary instead. Non-accepted finalizes are unaffected, so
  an honest failure can still record itself.

### Docs
Agent-facing (this is why the agent probed blindly — it had *zero* LUMV0820
documentation): `knowledge/lumen-dsl/grammar.md` (the new property + an explicit
note that node `AssetPlacement` is NOT the slot policy), `diagnostics.md`
(LUMV0820 + LUMD0276 rows, "one line fixes it, do not delete the slot"),
`directives.md` (slot-modify example; also corrected the `delete` row, which
undersold `delete(slot:key)`/`delete(page:id)`/etc).
Engine-side: `docs/slots-layout.md` (LUMV0820 row now names the repair + the
advisory classification), `docs/dsl-compiler.md` (the property list, plus an
explicit note that "rich slot metadata stays out of the DSL" is knowingly
excepted here, and why).

## Tests (all green)
- `cargo test -p lumen-core` (all targets except `visual_regression`): **487 passed**
- `cargo test -p lumen-api-helper -p lumen-agent -p lumen-export -p lumen-assets`: **215 passed**
- `pytest apps/api/tests/test_api.py apps/api/tests/test_export_policy.py`: **140 passed**
- `pytest apps/agent_runtime/tests`: **617 passed, 3 skipped**

New: 6 Rust DSL tests (born-correct, in-place repair clearing LUMV0820 on a
legacy slot, bare fit form, clear form, invalid-value refusals, text slots
unaffected); 8 `test_export_policy.py` unit tests (fail-closed default is
pinned); 2 API route tests (advisory-only exports with warnings / blocking
still refuses and reports no warnings); 4 finalize-guard tests.

## Consumer-compatibility check on the new `warnings` field (verified 2026-08-24)

The additive response fields cannot break any existing consumer. Verified
directly, not assumed:

- The **only** consumers of `/documents/{id}/export` and `/export-preview` are
  two copies of the same file — `apps/frontend/src/features/design-editor/engine/scene/exportRunner.ts`
  and the design subsystem's own editor at
  `subsystems/clue-design/apps/editor/src/engine/exportRunner.ts` (plus their
  `__tests__`). Both were read; both are **byte-identical in the relevant
  function** and equally tolerant.
- `exportResultFromUnknown` (line 256 platform / 250 subsystem) is hand-rolled
  and **allowlist-style**: it builds a fresh object picking only `status`,
  `diagnostics`, `export.artifacts`, `export.print_ready`. Unknown keys are
  silently dropped, never rejected — no `.strict()`, no throw on extra keys.
- No strict Zod schema is in the path. The `.strict()` call sites in the
  frontend live in `features/{projects,onboarding,session}/model/`, none of
  which touch the export response. (Had the export path been strict-parsed,
  `d1c9884db` would have failed every export on the day it shipped.)
- **The additive-payload rule is already house doctrine**, which is a stronger
  justification than either agent's own reasoning:
  `apps/frontend/src/features/onboarding/model/onboarding.ts:123` carries the
  comment *"Deliberately NOT .strict(): an additive backend field must never
  turn a successful provision into a client-side failure (review finding
  FE13)."* Cite FE13 when adding fields to an existing response.
- `status: payload.status === "ok" ? "ok" : "failed"` — so an `ok` status with
  non-empty `warnings` reads as `ok`, matching the intended semantics.

**Handoff for whoever builds the advisory UI** (frontend, not this slice): the
allowlist parser means `warnings` is dropped at the adapter boundary and never
reaches React. It has to be threaded in three places, not one —
(1) the `EditorExportResult` interface (`exportRunner.ts:42`); (2)
`exportResultFromUnknown` (`:256`), reading `payload.warnings` tolerantly like
its neighbours; (3) `SceneExportStatus` in `scene-export.ts` + `report(...)` in
`use-scene-export.ts`. Note the **two-copy** problem: the design subsystem's
editor has its own `exportRunner.ts` with the same shape (the two
`exportResultFromUnknown` bodies are byte-identical — verified by diff), so
decide deliberately whether it gets the same treatment.

**Dual-copy hazard runs in BOTH directions — check which before assuming.**
The root CLAUDE.md's AD4.C F9 residual set the expectation that the platform
copy gets fixed while the subsystem copy rots. The export UI is the *inverse*
case and it is worth knowing the shape can flip:

- *Advisory-UI threading* (the `warnings` field): genuinely **two-copy** — both
  `exportRunner.ts` files parse allowlist-style and both would need the field.
- *Export-failure visibility* (the sibling agent's bug): correctly **one-copy**,
  and now closed. The subsystem editor was **never broken** —
  `subsystems/clue-design/apps/editor/src/components/ExportPanel.tsx:88` has
  always rendered a plainly visible `<strong>Export failed</strong>`, and the
  only sr-only treatment anywhere in that tree is `WebRichTextToolbar.tsx`
  (both verified). The platform chat-shell copy was a **regression**: the
  re-lift into chat-shell dropped a visible failure state the standalone editor
  already had. Fixed on the platform side as `15c713a26`.

So "the subsystem copy is the stale one" is not a reliable prior. Read both.

## Residuals / follow-ups
- **`visual_regression` cannot compile at this base** — `crates/lumen-core/fixtures/visual_regression/baselines/*.png` are absent from the repo *and* from the pristine colombo workspace. Pre-existing, unrelated to this change; it is why `cargo test -p lumen-core` was run per-target.
- **Wasm handshake not re-verified in this worktree.** Engine sources changed, so AGENTS.md §1 requires `bash scripts/build_wasm_core.sh` + `node scripts/verify_handshake.mjs`. Both are impossible here: `apps/editor/node_modules` is not installed, so `wasm-pack` is missing (the build script exits 0 with a "not found" notice — quiet, worth knowing). The output dir is gitignored and untracked, so nothing was committable anyway. **Anyone running the editor against this branch must run `npm --prefix apps/editor install && bash scripts/build_wasm_core.sh` or the canvas will show "Canvas editing is disabled" on a stamp mismatch.**
- **Editor TS has no writer for `image_policy`** — `SlotInspector.tsx` displays it read-only and `operations.ts` hardcodes `image_policy: null` when constructing a slot. A human editing in the canvas can still create a policy-less image slot. Out of scope here (frontend), but it is the remaining hole in "born correct".
- `has_error_diagnostics` remains duplicated verbatim in `core.py:659` and `dto.py:486` (pre-existing). The new export policy lives in one module and is imported by both `lumen_api` and `agent_runtime`; the old helper is still used by the non-export paths, which is correct — those gates are about authoring health, not byte production.
- The `/documents/{id}/preflight` and `/preflight-preview` routes were deliberately **not** changed: their job is to report authoring health, where LUMV0820 should still read as an error the author can now fix.
