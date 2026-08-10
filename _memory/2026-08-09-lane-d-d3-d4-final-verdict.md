# 2026-08-09 — Lane D D3+D4 FINAL verdict (Fable adversarial review): both ACCEPTED

## Verdict

D3 (complete streaming; commits `c7d23ce9`…`7793f7c4` + close-out `95ec3210`/`14520885`) and
D4 (Option-B kickoff; `3afd47e5`…`bbd71742` + close-out `e1d3be13`/`5f2850ea`) are COMPLETE and
ACCEPTED. Alembic single head `2a4206f616fd` (merge committed `ed2ec0d2`, linted).
Independently verified by me on the merged head (55040):
**tests/api + projections + fleet + execution + agents + auth = 1,271 passed, 1 skipped,
2 failed — both documented pre-existing** (C6.1 `…c61_backend`, root-caused by D4 as
stage0-interview v9-materialized/v10-pinned drift predating Lane D; the order-dependent
`test_b4_composed_run_db::…deep_quarantines` flake, green in isolation — re-confirmed today).
db-smoke green via plain `upgrade head`. mypy 611 files clean; lint-imports 25/0; ruff clean.

## What is now true (the lane's promise, delivered)

Production chat: durable claude.ai-style threads (D0) → real receipts (D1) → async worker
turns with two-phase identity (D2+B1-join) → genuine token streaming with byte-equality
reconciliation, attempt isolation, stop/retry, reconnect/rehydration (D3) → the full Option-B
kickoff: immutable gate + insert-once answer, one-source max-spend, structured gate-response
turns, and the MODEL-PLANNED path proven (agent plans `open_directive_confirmation_gate@1`,
human confirms via the production route, agent plans `launch_account_research@1`; receipts
byte-identical to the launcher-driven acceptance) (D4 + recipe0-stage0-v6).

Review highlights already recorded in the two earlier D3/D4 memos; close-out additions
reviewed and accepted: route-transactional `turn.accepted` (announce-once incl. off-route
fallback); `?include=bodies` single implementation (sibling route deleted); `running` via the
submissions-union anti-join; the answered-gate → `running` correction to D4's sidebar test with
the pinned status precedence (`archived > approval > needs-input > running > idle`) — the
truthful composition; recipe v6 minted as an immutable new revision with pins mirrored into
both requirement surfaces (load-fails if they disagree); the `account_research_selection`
declared-absent pin idiom (required pin would deadlock against the object launch creates).

## Residuals / next decisions (carry into D5 planning)

1. **[decision needed] `draft_account_research_directive@2` cannot ride a model plan** — the
   C5 graph's pre-existing `_RAW_BODY_KEYS` refusal (`raw_body_key`) fires on its `body` field.
   Gate + launch (the authority carriers) are unaffected; the draft step currently arrives via
   the toolbelt/route path. Fix options (both outside catalog/pin seams, correctly STOPped):
   body-as-artifact-ref, or renaming a frozen field (schema-digest + profile re-pin cascade).
   Founder call on which, and when.
2. **[bug, not ours] C6.1 root cause found:** `test_resolved_snapshot_materializes_through_c61_backend`
   materializes `stage0-interview@v9` while head-of-abm has pinned v10 since v22. Belongs to
   the C6.1/catalog owner.
3. Deliberate deferrals: LISTEN/NOTIFY live tail (polling now); no background micro-batch
   flusher (bounded, documented); `emission_failures` metric; `task`/`plan`/`sources`/`gate`
   parts wired-but-dark until a launch happens inside a turn on a live surface;
   `entity_research_runtime_enabled` default off (rollout step); gate substrate generic but
   only `directive_confirmation` answerable.
4. Lane D remaining: **D5 — frontend rebuild** (joins Lane B B3); phase-2 items per charter.

## State

Branch pushed to origin (`platform/platformlane-d-chat-launch`) through this memo per the
founder's standing push instruction. Lane D backend (D0–D4 + B1-join) is COMPLETE, reviewed,
and green.
