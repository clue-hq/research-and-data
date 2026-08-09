# 2026-08-09 — FI Lane D **dev-lens** mini-slice: raw reasoning toggle + turn-context inspector

Branch: `platform/platformlane-d-chat-launch` worktree `damascus`. Backend **and**
frontend (the one slice where both are in scope). Brief:
`docs/specs/FI-lane-D-dev-lens-implementation-brief.md` (founder-approved
2026-08-09, commit `f1f0a545`). Rebased on the D5-close agent's work
(`d98541cb`/`ae61faca`) — nothing of it reverted.

Commits: `98d0f251` (backend), `c61ad609` (frontend).
**No Alembic migration** — and none was needed; see §2.

## 1. What it is

Two developer lenses onto a conversation turn, for tuning prompts and skills:
see what the model was given, and how it reacted. Both are **dev-only by
construction**, and the production contract they would relax is left intact and
its test *sharpened*, not weakened.

## 2. Half 1 — the raw reasoning trace

**Setting.** `chat_reasoning_trace_mode: "summary" | "raw"`
(`CLUE_CHAT_REASONING_TRACE_MODE`, default `summary`) + optional
`chat_reasoning_thinking_budget_tokens`.

**Gateway seam (no fork).** `GatewayConfig` gained `agent_reasoning:
ReasoningRequest | None`; `default_gateway_config()` is the *only* place that
sets it, from the setting. `agent_model._reasoning_request(config, model_id)`
replaced the inline `{"effort": "none"} if gpt-5.6` line: config wins when
present, the per-model baseline survives when absent. The override deliberately
replaces GPT-5.6's governed `effort: none` — a model told to spend no reasoning
effort has no reasoning to expose, so keeping the baseline would make the lens a
no-op on exactly the pinned model.

**Emission (decided in the brief, followed).** `text.delta` frames carrying the
round's **reasoning** part id and `part_kind='reasoning'`. Verified against the
schema before writing a line: `98a5ddafa21b`'s CHECKs are
`(event_type='text.delta') = (delta_index IS NOT NULL)`, `text.%` requires
`part_id`+`generation_attempt_id`, and `part_kind` must be in the part
vocabulary — `reasoning` already is. **So no CHECK, enum or migration change.**
The frames carry **no `message_id`** (this text belongs to no message), and
`reconcile_text` is scoped to the *text* part's id, so §3.3(5) byte-equality is
untouched. `ReasoningPart` gained `text` + `text_ephemeral`, both `None` by
default and excluded by `wire()`'s `exclude_none` → a `summary`-mode payload is
byte-identical to what it always was.

**Where the gate lives.** On the emitter (`TurnStreamPolicy.reasoning_trace`),
not only on the callback handler, so *every* path to a reasoning delta passes one
check. `fleet_main` composes it from the setting (one line).

**One structural change made during implementation:** the handler's reasoning
extraction was moved *above* the `extractor is None` guard in
`on_llm_new_token`. A provider can stream reasoning in a round that never
produces a finalize call; the two surfaces are unrelated. (Found by a test that
failed for the right reason.)

### Per-provider reality (documented honestly in `_reasoning_request`'s docstring)

Everything ships through OpenRouter's Responses API
(`ChatOpenAI(use_responses_api=True, output_version="responses/v1")`), so:

- **OpenAI o-series / GPT-5.x** — the API *never* returns the private
  chain-of-thought. With `summary` requested it returns a model-written
  **summary** of it, as `response.reasoning_summary_text.delta` chunks that
  `langchain_openai` surfaces as `reasoning` content blocks. Without `summary`
  the model still reasons and emits nothing observable — which is why the lens
  asks for `effort` **and** `summary`.
- **Anthropic (via OpenRouter)** — thinking blocks, mapped onto the same
  reasoning items, so the lens shows thinking text rather than a summary.
  `max_tokens` is the budget these actually read.
- **Plain models** — nothing. The block is accepted-and-ignored or dropped; the
  card stays exactly the `summary`-mode status card.

**Not verified against a live provider**: no `.env`, no model key in this
worktree. The extractor is tested against all three *normalized LangChain*
shapes; the provider behaviour above is from the shipped `langchain_openai`
1.4.1 source (`_convert_responses_chunk_to_generation_chunk`), not guessed.

## 3. Half 2 — the turn-context inspector

Four dev-flagged read routes + a capability probe, **zero new storage**:

```
GET …/projects/{p}/threads/{t}/inspector                       → capability
GET …/threads/{t}/turns/{turn}/inspector/context               → 7-layer receipt + included bytes
GET …/threads/{t}/turns/{turn}/inspector/rounds                → agent_model_call
GET …/threads/{t}/turns/{turn}/inspector/plan                  → authored vs validated + both ledgers
GET …/threads/{t}/turns/{turn}/inspector/tools                 → args + receipts
```

Joins live in the new `clue_projections/turn_inspector.py`; wire shapes +
hydration in the new `clue_api/chat/inspector.py`, reusing D3's
`hydrate_message_bodies` for the byte budget. Scoping is the surface's existing
404-not-403 rule (`TURN_NOT_FOUND` / `THREAD_NOT_FOUND`).

**Byte budget** — `chat_dev_inspector_budget_bytes`, default 512,000, cumulative
per response. Over-budget bodies return **address + `omitted_reason:"budget"`**;
there is no shortened-text path, because a half-rendered prompt is worse than an
absent one (a developer would tune against text the model never saw).
`truncated: true` says so at the top of the response.

### The one honest gap (reported at three sites, not papered over)

A plan the validator **rejects** raises inside `validate_plan` *before*
`record_validated`, so there is **no `agent_plan` row and no per-operation
"refused" record** to project. The brief's "(admitted/refused + reason codes)"
is therefore served as: admitted operations from `agent_plan_operation` (each
stamped `validation: "admitted"`), plus the plan event ledger, plus the **turn's
own `agent_turn_event` ledger**, which is where a rejection's `reason_code`
actually lives. Manufacturing a refused-operation row from an exception would be
exactly the fabrication this platform exists not to do.

## 4. Production-unreachability — how each half is proven

Both flags are refused by **one settings validator**,
`Settings._refuse_dev_lens_in_production`, on the same predicate
(`auth_environment == "production"`) and in the same place as the two refusals
that already guard that object (local-fixture auth, local-header projections).

- **Half 1:** a production process holding `raw` **does not construct**. There is
  no running deployment in which the emitter could be reached with the lens on,
  so there is no request-time check to get wrong.
- **Half 2:** the same startup refusal, *plus* the routes are only registered
  under `settings.chat_dev_inspector_enabled` — so the paths 404 in a process
  that would not have started with the flag set. Two structural layers.
- **Frontend:** the drawer's affordance renders from a **capability probe**, not
  from an env var. A production deployment 404s the probe → `available: false` →
  no button, and the `next/dynamic` panel chunk is never requested.

Tests: `test_a_production_process_refuses_to_start_with_either_dev_lens_flag`
(parametrised over both flags, and asserts each flag *is* accepted in a dev
deployment so the refusal is about production, not about the flag being unusable)
and `test_the_inspector_routes_do_not_exist_unless_the_dev_flag_is_on`.

## 5. The leak negatives — sharpened, and the old one verbatim

- `test_summary_mode_puts_no_provider_reasoning_on_the_wire` — a provider that
  leaks on every chunk, both leak paths exercised (the handler *and* a direct
  `reasoning_delta` call), default policy: **zero** `text.delta` frames exist,
  the bait string appears nowhere in the outbox, and the reasoning payloads carry
  neither `text` nor `text_ephemeral`.
- D3's own `test_no_provider_content_or_surrounding_json_reaches_the_wire` still
  passes **unchanged**, as does the `"text" not in payload` assertion in
  `test_a_repaired_finalize_call_resets_the_superseded_text_part`.
- `test_a_reasoning_trace_never_enters_the_assistant_message_reconciliation` —
  a trace streamed in the same attempt cannot break §3.3(5).
- `reasoning_deltas_from_chunk` negatives: ordinary prose, `{"type":"text"}`
  blocks and tool-call chunks all return `()`.

## 6. Files

**Backend** — `libs/clue-config/clue_config/{settings,gateway,__init__}.py`;
`libs/clue-gateway/clue_gateway/agent_model.py`;
`platform/api/clue_api/chat/{turn_parts,turn_stream,inspector,router}.py`;
`platform/api/clue_api/fleet_main.py` (1 line);
`platform/projections/clue_projections/{turn_inspector.py,__init__.py}`;
`tests/api/test_lane_d_dev_lens_db.py` (new, 12 tests).

**Frontend** — `model/{chat-parts,chat-transcript,chat-inspector}.ts` (+2 test
files); `data/{chat-repositories,chat.fixture,chat-inspector.repository}.ts`;
`hooks/use-turn-inspector.ts`;
`components/{chat-agent-activity,chat-transcript,conversation-pane,project-workspace-view,chat-turn-inspector,chat-turn-inspector-panel}.tsx`;
`components/project-flow.module.css`.

## 7. Verification

- New backend suite 12/12. Full gate re-run **237 tests green**: every Lane D
  suite (D1, D2 ×2, D3 ×2, D4 ×4, D5-close, B1 join, chat surface, dev-lens) +
  `tests/projections` + `tests/test_config_settings.py`.
- `ruff format --check` (1301 files) + `ruff check` clean; `mypy` **621 files,
  no issues**; `uv run lint-imports` **25 contracts kept**.
- DB: dedicated `clue-pg-damascus` on **localhost:55040**. Never 5432.
- Frontend gate: `design-system:build` ✓, `eslint` ✓ (0 problems),
  `next build` ✓, `npm test` **108/108** (13 new).

## 8. Deviations from the brief's file list (both reported, neither silent)

1. **`platform/api/clue_api/fleet_main.py` — one line.** `TurnStreamPolicy` is
   constructed there from settings; without it the toggle cannot reach the
   emitter at all. It is the chat stream's composition root and already reads the
   four sibling `chat_turn_stream_*` settings. The alternative (a
   `default_factory` reading `load_settings()` inside `turn_stream.py`) would put
   an implicit env read in a hot constructor — rejected.
2. **Three frontend files outside `features/projects/**` … none.** All frontend
   edits are inside `apps/frontend/src/features/projects/**`; `ai-elements` was
   only *imported*, not modified. No `api-contracts/*.md`, no `platform/auth/**`,
   no FI-2 file, no migration touched.

## 9. Open items / caveats

1. **No live-provider pass.** The per-provider account in §2 is derived from the
   pinned `langchain_openai` source, not observed against a real key. First
   `raw`-mode run should confirm what an OpenRouter→Anthropic route actually
   surfaces, and whether both a `summary` delta *and* a `content` delta ever
   arrive for one item (the extractor would emit both; a dev lens can live with
   that, a product surface could not).
2. **The Rounds tab carries no reasoning text.** A round's trace is a stream
   artefact with no durable counterpart, so joining it into a *read* would mean
   storing it — which the slice's zero-storage rule forbids. Today the trace is
   visible on the transcript's reasoning card only, and only live.
3. **`agent_turn_event_stream` is pruned at 24h**, so the transcript-side trace
   is gone after that. The inspector's four tabs are unaffected (they read
   permanent C6 tables).
4. **The inspector shows tool *refusals* only via the Plan tab's turn ledger.**
   A `plan_rejected` refusal's per-issue reasons exist on the stream's tool card,
   not in a durable table. If per-issue refusal reasons are wanted durably, that
   is a new receipt and therefore a new decision, not a read change.
5. **`next/dynamic` is now used in this app for the first time.** Confirmed the
   panel lands in its own 7.7 KB chunk. If the codebase later adopts a different
   lazy-loading convention, this is the one site to align.
6. No browser pass with the flags on (inherited: no `.env`, no model key, no
   Clerk credentials in this worktree).
