# Lane D mini-slice "dev-lens" — implementation brief: raw reasoning toggle + turn context inspector

**Founder-approved 2026-08-09.** Two halves, one purpose: tuning prompts and skills by seeing
what the model was given and how it reacted. Both are **dev-only by construction** — the
production contract ("what streams as reasoning is a safe activity summary, never private
chain-of-thought"; raw context bytes never reach a wire) stays fully intact, enforced by
startup refusals in the pattern of the dev principal and `local_header` mode.
**Sequencing:** starts only after the Lane D closing agent's commits land (it is inside
`turn_stream.py`/`conversation_turns.py`); rebase on its work, never revert it.
Read first: charter §§3.1–3.4 (the ratified part/vocabulary contracts you are amending
dev-only), D3's `chat/turn_stream.py` + `chat/turn_events.py` + `chat/finalize_stream.py`
(the tap handler that today discards all non-finalize chunks), the closing agent's fresh
`_memory/` entry, `libs/clue-gateway` (how chunks and provider reasoning content surface),
and the C6 receipt tables (`agent_context_*`, `agent_model_call`, `agent_plan`,
`agent_plan_operation`, `agent_tool_result` — migration `7e9269ed8a81`).

## Half 1 — raw reasoning trace toggle

1. **Setting:** `chat_reasoning_trace_mode: "summary" | "raw"` (env
   `CLUE_CHAT_REASONING_TRACE_MODE`), default `summary`. `raw` outside the dev/local guard
   (same predicate family as the dev principal) **fails startup** — production can never carry
   it. Optional companion `chat_reasoning_thinking_budget_tokens: int | None` (default None).
2. **Request-thinking gateway knob:** in `raw` mode, turns request extended thinking from the
   provider where the pinned model supports it (Anthropic thinking blocks; o-series summaries;
   plain models: nothing). Wire through the existing gateway config seams — do not fork the
   gateway; if the gateway cannot express it without structural change, STOP and report.
   Document per-provider reality honestly in code comments: the toggle streams whatever the
   provider exposes, which may be a summary or nothing.
3. **Emission:** the tap handler routes provider reasoning deltas (in `raw` mode only) onto the
   turn's `reasoning` part as streamed text. **Vocabulary decision (mine, follow it): reuse
   `text.delta` frames targeting the reasoning part's id** — the outbox CHECKs
   (`delta_index` iff `text.delta`) and the frontend's per-part delta accumulation already
   support this shape, so no DB CHECK/enum change and no migration. No byte-equality
   reconciliation for reasoning (there is deliberately no durable final reasoning message);
   the part closes with its accumulated text marked ephemeral. `summary` mode is byte-for-byte
   today's behavior.
4. **Frontend:** the `reasoning` part schema gains an optional streamed `text`; the vendored
   `Reasoning` disclosure renders it incrementally when present (no frontend flag — payload
   presence decides). Fixture path untouched.
5. **Tests:** the §5 leak assertions get SHARPENED, not weakened — raw reasoning reaches the
   wire **iff** mode=raw under the dev guard; the production negative (summary mode leaks
   nothing) stays a hard test and must still pass verbatim; startup refusal test; a streamed
   reasoning accumulation test in the reducer suite (frontend).

## Half 2 — the turn context inspector (dev drawer)

1. **Backend — dev-flagged read endpoints, zero new storage.** Setting
   `chat_dev_inspector_enabled: bool` default False, refused at production startup. Under the
   chat surface (same principal seam, `thread.read`), per assistant turn: (a) the seven-layer
   context receipt — per layer: name, ordinal, token_count vs token_budget, and the exact
   included bytes hydrated from the content-addressed artifacts (bounded by a byte budget per
   response; over-budget bodies return refs + a truncation marker, never silently); (b) the
   model rounds (`agent_model_call`: model id, tokens, cost, status, timing); (c) the authored
   plan JSON + per-operation validation outcome (admitted/refused + reason codes); (d) tool
   invocations with arguments, result receipts, and refusals. Reuse existing projections
   wherever they exist; add read helpers beside them; never duplicate queries.
2. **Frontend — the inspector drawer.** Dev-only affordance on each assistant turn (rendered
   only when the transport reports the inspector routes available — probe or config prop, no
   hardcoded env reads in components), opening a side panel with four tabs: **Context**
   (collapsible L1–L7, token/budget bars, exact bytes, which items were dropped by budget if
   the receipts record it), **Rounds** (model calls; inline raw reasoning per round when Half 1
   is in raw mode), **Plan** (pretty-printed JSON + validation verdicts), **Tools**
   (args/results/refusals). Repository + fixture + HTTP adapters per the house seam; keep the
   panel outside the production bundle path if the toolchain supports it cheaply (dynamic
   import), otherwise flag-gated rendering is acceptable — report which.
3. **Tests:** endpoint suites incl. cross-workspace refusal + production-refusal; byte-budget
   truncation behavior; drawer component tests over fixtures; toolchain gate green.

## Rules

Backend + frontend both in scope this once; the file set is: `chat/` stream/emission modules,
gateway config seams, `clue_projections` read helpers, `settings.py`, and
`apps/frontend/src/features/projects/**` + `src/components/ai-elements` — nothing else. Never
touch: `platform/auth/**`, FI-2 territory, `api-contracts/*.md` (report deviations),
migrations (none should be needed — STOP if you disagree). All existing Lane D suites stay
green (dedicated DB localhost:55040, never 5432; frontend gate
`npm run design-system:build && npm run lint && npm run build`). Commit locally by explicit
path; NEVER push; no AI attribution; `_memory/` entry at the end.

Final report: files; the exact per-provider reasoning behavior observed; the emission shape;
endpoint shapes + payload budgets; how production-unreachability is proven for BOTH halves;
test + toolchain results; open items.
