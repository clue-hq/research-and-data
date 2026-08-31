# 2026-08-19 — genweb slice 1: design legs dispatch web turns (B1) + the preview ceiling

Plan: `docs/superpowers/plans/2026-08-19-chat-driven-website-generation.md` §5 Slice 1.
Brief/report: `.superpowers/sdd/2026-08-19-chat-driven-website-generation/slice1-{brief,report}.md`.
Branch `integration/frontend-design-part-iv-v2`. Commits `79dac699` (design), `a27440fa` (platform).

## What shipped

- **`DesignLegTurnRunner._envelope` branches on the leg document's `doc_kind`.** `web` →
  `kind="web_turn"` + `config.request = {prompt, base_version}` (WebTurnRequest-shaped);
  `scene`/no-document → the shipped `agent_turn` request byte-for-byte. The runner already
  loaded the whole document row for the scene path; it now threads the ROW (`pinned_document`)
  instead of just `.scene`, so `doc_kind`/`current_version` cost no extra read.
- **`design_agent_run.kind` now mirrors the envelope discriminant** (`create_run(kind=…)`).
  Nothing dispatches on that column (the fleet dispatches on the envelope's `kind`), so this is
  observability, not routing.
- **`_assistant_summary` has a web branch.** The web result shape has **no `stop_reason`** — it
  carries `status` (`applied`/`failed`/`conflicted`), `summary`, and `current_version` on the
  applied path — so the web sentence reads
  `Design turn applied on website document <id> (now version N): <runtime summary>`.
- **`_normalize_image_bytes` clamps into a BAND** (`_VISION_MIN_PX` 512 floor, NEW
  `_VISION_MAX_PX` 7500 ceiling; NEAREST up, LANCZOS down, in-band bytes untouched). The web
  reviewer's `view` imports the same `_image_block`, so both harnesses are covered.
- **`execute_web_turn_job` synthesizes a `web_turn.no_result` diagnostic** from the runtime's own
  summary whenever a non-applied result carries no diagnostics — the web twin of the scene path's
  `agent_runtime.no_proposal`.

## Facts worth keeping

- **The design turn runs INSIDE the platform fleet worker**, not the design API: the lane is
  `InlineDesignLaneDriver` (`platform/api/clue_api/design_fleet.py`). So an istanbul
  `clue_api.fleet_main` that must serve design legs needs the design runtime env too —
  `LUMEN_AGENT_BASE_URL`, `LUMEN_AGENT_API_KEY`, `LUMEN_AGENT_MODEL`, `LUMEN_CORE_HELPER`,
  `OPENROUTER_API_KEY` — plus `CLUE_AGENT_WORKSPACE_ROOT` as an **absolute, 0700** directory.
  Without the agent vars the turn fails in seconds with `agent_runtime.failed`.
- **Do NOT override `CLUE_STORAGE_FS_ROOT` on the platform worker.** The platform's artifacts
  (user message bodies) live under the repo's `.artifacts`; pointing the worker at the design
  API's `/tmp/lumen-dev-storage` makes every turn die with `RequiredTurnArtifactMissing:
  required turn context is no longer available`.
- A conflicted CAS is already honest without new code: `execute_web_turn_job` marks the run
  `failed` for any non-`applied` status, and the runner's failed-run path fails the turn with
  `design_leg_turn_failed`, commits no finalization, writes no assistant message, and leaves the
  leg `open_awaiting_user`.
- The **exit judge fails open in this dev env** (`agent model timeout must be positive and no
  greater than gateway policy` → `design_leg.exit_judgment_fail_safe`). Unrelated to this slice;
  the fail-safe behaved as designed (a broken judge can only continue the leg).
- A successful web turn took **~13 minutes** here (07:00→07:13 UTC), longer than slice 0's 6.5min
  — the reviewer looped once to repair an unstyled section. Slice 3's refresh-on-completion
  design should not assume ~6min.

## Live verification (dev data, left in place)

Thread `thr_genweb_slice1_a1`, leg `015d89ac-64fe-480c-ab02-0de54bcded72`, document
`doc_feb8f81a6d2642ec82224b6d1610a49c` v1 → **v2**, run
`run_96cbbc52b3ad5d4b919d6597863aa35d` (`kind=web_turn`, `status=succeeded`,
payload request `{"prompt": …, "base_version": 1}`). Thread sequence 4 = the assistant summary
naming the document and version. The leg was hand-opened and the message submitted through the
platform's own durable path (`persist_user_turn` → `insert_submission` →
`dispatch_next_thread_turn`) rather than the Clerk-authenticated BFF; the script is
`/tmp/slice1_live_open_leg.py` (scratch, not committed).

## Test state

- New: `tests/api/test_genweb_web_turn_dispatch_db.py` (6 DB-gated tests) — all pass.
- `tests/api/test_p3{4,5,6,7}*` design-leg suites: 38 passed, **1 pre-existing red**
  (`test_p36…::test_a_gate_answer_queued_behind_a_leg_opening_still_reaches_head_of_abm` —
  `insert_gate_answer() missing … expected_subject_sha256`, another lane's signature drift;
  fails identically on stashed HEAD).
- Design subsystem: `apps/agent_runtime/tests` 100% green (520+); `apps/api/tests` 17 reds, ALL
  pre-existing custom-component **compiler/publish/runtime** tests (no local esbuild/node worker) —
  reproduced identically with the slice's design changes stashed.

## Open concerns for the reviewer

1. The leg path applies **no draft/published gate**. The design API's own `POST
   /documents/{id}/web/turns` calls `require_draft_document` before starting a turn; the leg
   dispatch (both kinds, pre-existing for scene) does not. A leg pinned to a published web
   document would let the agent edit it. Needs a founder/plan ruling, not a silent policy.
2. `account_card` is not carried on the leg's web envelope (v1 per plan). A derived,
   account-stamped document turned through chat therefore runs **un-personalized**, because the
   executor reads `account_card` only from the envelope — the design API's route resolves it from
   the document row before enqueue. Worth naming when personalization enters the chat path.
3. The vision ceiling is a downscale, not a tile: a 14000px page is judged at ~7500px, so the
   reviewer sees smaller text than the user will. If review quality degrades on long pages, the
   tiling option in the slice brief is the follow-up.
