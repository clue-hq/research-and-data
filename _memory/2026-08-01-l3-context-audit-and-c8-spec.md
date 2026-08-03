# 2026-08-01 — L3 context-budget failure: byte-level audit + PC-C8 Slice-1 spec (now v2)

## What happened
The Stage-0 trial `trial-63553478967758a6` bricked with `HTTP 422: required l3_project context exceeds its hard layer budget` around turn 18. Full audit performed against the code and the recorded artifacts; findings verified byte-level, then a reviewed external proposal was adversarially evaluated, then the Slice-1 spec was drafted as **`docs/specs/PC-C8-stage0-context-card.md`**. A second external review of that spec surfaced six blockers and one factual error in v1; all were verified and the spec was rewritten as **v2** (2026-08-01). DRAFT — no code changed; spec + this note are the only new files, uncommitted pending user review.

## CORRECTION (v1 error, fixed in spec v2)
v1 of the spec (and the first version of this note) claimed `platform/projections/clue_projections/stage0.py` **did not exist** and called the original proposal's citation "fabricated". **That was wrong** — the file exists (commit `08c1998`, `feat(stage0): implement governed Recipe 0`) with `ReconBriefView`/`Stage0ProgressView`/`Stage0ReadinessView` (incl. `verdict` vs `effective_verdict` + `readiness_override` join). The error came from checking with `ls … | head`, which truncated the directory listing at 10 entries — `stage0.py` sat below the cut. Lesson: never conclude non-existence from a truncated listing; use an exact test (`test -f` / un-truncated `ls`). Slice 1 **extends** `stage0.py` (brownfield), and the card's readiness selection must reuse `stage0_readiness`'s existing override/lineage logic.

## Verified findings (all with file:line evidence in the spec §1/§11)
- L3 required items at the failing turn: stage snapshot 32,178 B + readiness snapshot 15,889 B + budget envelope 140 B = **48,207 of 48,000** (over by 207 B).
- **Readiness ledger serialized twice** in L3: `stage0_trial.py:750` (inside `current_truth`) and `:760` (readiness artifact) — byte-identical, ~16KB.
- **Raw `to_jsonb(row)` dumps as model context** (`stage0_trial.py:1287,1297`); statement rows carry offsets+sha but **zero quote text** — the model cannot read what the user said.
- **Identity prompt physically injected twice** per model call: L1 candidate (`context.py:213` → `runtime.py:305`) + `create_deep_agent(system_prompt=…)` (`runtime.py:297`). Verified in recorded call `f304cf4a…` (14,705 B + 7,364 B messages).
- **Full recipe lifecycle per chat turn** (start → gate → complete, `stage0_trial.py:779–805, 914–922`) — deviates from PC-C4 §5's Recipe #0 shape (`↔ record_interview_answer` inside one recipe).
- Context candidates processed in `stable_key` sort order (`context.py:556`) → an optional item can starve a later required item.
- Growth loop: `_recompute_readiness` (`:927`) appends ~930 B/material turn; ledger always fully re-serialized twice → ~1.9KB/turn L3 growth independent of message content.
- Doc A Part III **already mandates** card-based L3 from the projection API and forbids full dumps ("havana's context-blowup lesson") — the implementation drifted from its own architecture.

## Evaluation of the external proposal (user attachment 2026-08-01 14:26)
Directionally right (~80% verified), NOT implementable as written:
- ~~"Fabricated citation: `clue_projections/stage0.py` does not exist"~~ — **RETRACTED, my error (see CORRECTION above): the file exists; the proposal's citation was accurate.**
- **Card schema holes** that would break routing: missing `current_turn_input` (onboarding_input_id required by `record_interview_answer`), missing `registered_client_claim_fields`, and no owner assigned for the load-bearing `stage_snapshot.instruction` prose (`stage0_trial.py:737–748`). (v2 note: turn identity ultimately moved to L7/engine-side rather than into the card — see below.)
- **Wrongly folded `budget_envelope_ref` into the card** — it is spend authority consumed by delegation (`specialist_wiring.py:364`, `agent_execution_wiring.py:1011,1780`); must stay a separate constitution field.
- **Understated blast radius:** `AgentConstitution` is a frozen C6 contract (`contracts.py:404,415–417`) built at three wiring sites (stage0_trial, specialist_wiring, account_research_turn_wiring) and journaled with role labels (`agent_turn_wiring.py:405–412`).
- Half-wrong claim: readiness recompute is already conditional on material routing (`stage0_trial.py:960`); only report export (`:932`) and KB refresh (`:923`) are unconditional.

## Second review round (user attachment 2026-08-01 14:54) → spec v2
All six blockers verified correct and adopted; my one disputed fact (`stage0.py`) resolved **against** me:
1. Card hard-bounded by explicit versioned size policy (`stage0-card-policy-v1`): 40-statement cap aligned with `MAX_PROJECT_STATEMENTS=40` (`icp_synthesis.py`), per-quote/aggregate/KB caps, 24,000-byte whole-card assertion.
2. `current_turn_input` OUT of the card → L7 envelope + engine-side trusted binding: model authors classification+offsets only; engine injects `onboarding_input_id`/`artifact_key`/answer bytes (extends the 2b injection seam; `RecordInterviewAnswerInput` at `stage0_tools.py:286` currently round-trips the byte-identical answer). Also fixes v1's self-defeat: card+turn-identity would have changed every turn, killing content-addressed reuse.
3. Trial restrictions → trial capability surface (profile variant / surface policy; registry resolves per-role at `registry.py:536`), NOT the shared skill. "Prompt prohibition is guidance, not governance."
4. Compiler gets an injected `StatementEvidenceReader` port (conn alone can't read artifact bytes/verify sha); ICP synthesis migrates onto the same port (DRY).
5. ICP proposals: confirmed-refs+staleness only in the card (proposals live in trial-local `.context` files, `stage0_trial.py:1317` — not a legal projection source).
6. DSAR in-slice (Slice 1 CREATES the derived copy): per-statement reverse bindings at persist, B2-pattern purge/tombstone, erase→no-resurrect test.
Also: `project_version` doesn't exist on `Project` (`clue_spine/spine.py:87`) → real lineage in `compiled_from`; omissions carry typed kinds+cursors, no tool names; `inspect_client_claim` deferred as a platform-level decision; readiness selection = lineage-current + override-applied, reusing `stage0_readiness`.

## The spec's key rulings (PC-C8 v2)
1. L3 = one hard-bounded `Stage0ProjectCard` (extends existing `clue_projections/stage0.py`) + the separately-owned budget-authority envelope; canonical JSON → deterministic content-addressed artifact.
2. Contract-delta: `stage_snapshot_ref` + `readiness_snapshot_ref` → one `project_card_ref`; **budget ref unchanged** (spend authority: `specialist_wiring.py:364`, `agent_execution_wiring.py:1011,1780`). Touch points in spec §10.
3. Model classifies the turn; engine supplies captured bytes + trusted identifiers (§6).
4. Trial restrictions enforced by capability surface (§8); shared skill keeps routing procedure only.
5. Two bounded/paginated inspection tools (`inspect_statement_history`, `inspect_readiness_history`); card omissions carry cursors, never tool names.
6. DSAR erasure for card copies in-slice (§9).
7. Explicitly deferred: identity single-injection + tokenizer + required-first ordering (Slice 2), long-lived Recipe #0 (Slice 3 — needs a design ruling on lease/checkpoint/idempotency), hot-path hygiene (Slice 4).

## Open questions / next steps
- User to review PC-C8 **v2** before any implementation. Work breakdown in spec §11 (1.0 evidence fixtures first).
- Impl must verify whether turn-ref role labels (`stage_snapshot` etc.) are a DB enum and whether `DbAgentReplayReader` matches on them.
- §6a (engine-side turn binding) is the one sub-slice with real regression surface (sha-verification semantics move engine-side); fallback to the L7-envelope minimum must be surfaced, not silent.
- User dissatisfaction with byte-based budgets acknowledged; the tokenizer swap is Slice 2, deliberately not smuggled into Slice 1. Card *content* caps stay byte-denominated by design.
- Note: `DbCompiledContextCardReader.read` itself does `model_dump_json(exclude_none=False)` full-object dumps (small today; worth tightening when L2/L5 cards are revisited in Slice 2+).
- Slices 2–4 have no repo-durable spec yet (only scope fences in PC-C8 + the chat-attachment proposals); Slice 3 needs its design questions written down before any spec.
