# 2026-08-23 — genad close-out: chat-driven ad creation SHIPPED; generation environment-blocked

Plan: `docs/superpowers/plans/2026-08-23-chat-driven-ad-creation.md` (rulings in
`_memory/2026-08-23-genad-rulings.md`). Executed subagent-driven (Opus implements /
Fable orchestrates + browser proofs), all 7 tasks complete, whole-branch review
verdict **"Ready to merge, with fixes"** — the fix wave + this note are those fixes.

## What shipped (commits `4ce4d7f0..` on `integration/frontend-design-part-iv-v4`, local only)

- `fdcd967d` DAL: scene births stamp the workspace's approved brand kit (web mirror; explicit kit authoritative; no-kit → honestly un-branded).
- `53f3219f` platform: `mint_empty_ad_document` + `AD_FORMAT_PRESETS` (square 1200² / portrait 1080×1350 / story 1080×1920 / landscape 1200×628) + `ad_birth_page` — engine-minted scene + one `add_page` op.
- `a5b2c561` `open_design_leg@3`: document-less `doc_kind="scene"` births an ad at a ratified format (custom escape `ad_width`/`ad_height`); v1 refusal superseded; ten DB tests + the trip-wire consciously rewritten.
- `45102e4d` Head-of-ABM v38 + prompt v6 (infer-and-STATE the format, no confirmation gate) + recipe rev 18 wave (the full ef4884d0-template 13-file bump).
- `8e7a7545`+`d1707b1c`+`4b77b1ab` scene-turn persist: LEG-ONLY, CAS under `document_base_version` (read fresh per turn — no birth-to-first-turn clobber window), replay-verify, asset-custody backstop, honest+legible conflict result. Non-leg (MVP editor) turns byte-identical (P3.7), proven by dict-equality test.
- `f0ecd069` F1 (found by the live walk): leg turns on an all-pages-empty scene get a steering block — the trio's from-scratch habit authors `page(...)` against the already-born artboard and thrashes to death; the block quotes engine-verified forms (`#page:<id> name("…")`). After F1, the page-thrash diagnostics vanished from live runs.
- `ed95c673` dated doc supersessions (seed script, genweb plan, ad-editor plan, frontend projects.md contract).

## Live-proven (browser walk, Fable-driven)

"Make me a LinkedIn ad…" in a fresh project chat → Head-of-ABM **stated** "square
LinkedIn feed ad" (no gate) → doc born `scene` v0, `square_ad`, approved kit
stamped (`brand_kit_ing_813df4f3@6`), page exactly the birth shape → leg pinned
guard 0, pin read back → gallery card (Edit/Export, honest empty) → auto-open
fired → editor rendered the empty 1200×1200 artboard cleanly (wasm zero-node
relayout fine; canvas schema showed "Linkedin square (1:1)"). Second format
proven: "Instagram story ad" → `story_ad` 1080×1920, kit stamped. No-kit and
refusal cases proven at the DB-test layer. Root `make check`: exactly the five
documented pre-existing reds.

## FOUNDER ITEMS (the durable list)

1. **Chat ad GENERATION is environment-blocked by design-runtime transport fragility.**
   7 live attempts, 2 upstream author models: after F1, every run dies on ONE heavy
   multimodal LLM call that grinds 240–262s and then gets upstream `server_error`;
   `lumen_agent` has **no retry/backoff** around trio calls, so one provider 500
   kills a 20-minute run (`orchestrator_did_not_finalize`). Pre-existing — also
   affects web generation and MVP editor turns on provider bad days. Fix: bounded
   retry in `lumen_agent`, or restructure/stream the heavy call. Highest-value next
   work; outside genad's scope. The first day the provider behaves, the same chat
   message fills the born artboard with zero further code changes.
2. **The engine's own DSL hints teach a broken form.** `dsl.rs` LUMD0402 + LUMD0206
   hints advertise bare `#page:<page_id>`, which `is_modification_line`
   (dsl.rs:5851, needs ≥2 tokens) parses as a COMMENT — following the hint
   literally reproduces the very error it answers. Design-engine owner's fix.
3. **Conflict routing:** a CAS-conflicted leg turn stays a typed failed turn (web
   parity, D1 contract) and the thread shows NO message; the legible
   both-versions prose exists in the durable run result. Rewiring conflict →
   AWAITING_INPUT-with-message changes the P3 finalization contract for BOTH
   kinds — founder decision.
4. **The WEB executor carries the same post-commit re-read defect the fix wave
   closed on the scene path** (`lumen_api/main.py:8519` — a non-CAS exception from
   the re-read after a committed `design_apply_web_operations` reports
   `agent_runtime.failed` for a website turn that committed). Found by the final
   scoped re-review; pre-existing, unowned; the fix is the same two-line shape as
   commit `ac36499d`'s scene fix.
5. Smaller: prose-summary of a *committed* scene turn still reads "proposed" and
   doesn't name the new version (plan-sanctioned; reads oddly now);
   `brand_kit=` param vs `meta.brand_kit` scene/columns divergence (exact web
   mirror, both-kinds decision).

## Adversarial-pass residuals (Fable's own final review, 2026-08-23)

- Birth + leg insert are genuinely ONE transaction (verified at
  `design_leg_tools.py:552/584/621`); the delegation-bundle artifact persists via
  its own connection just before it (pre-existing @2 shape) — a failed leg insert
  can orphan a bundle blob (harmless, audit-only).
- At-least-once window: a worker dying between the governed write and the run's
  terminal write replays the turn; the CAS pre-check then reports an honest
  CONFLICT for content that is actually present (bounded by `max_reoffers=1`;
  exact web parity; never a clobber).
- The persist composition has only ever executed against STUB proposals — every
  underlying function (`apply_operations` replay, `register_scene_asset_backstop`,
  `design_apply_operations`) is the same code the MVP editor's accept seam runs in
  production, but **watch the first live generation end-to-end** when the
  transport founder item is fixed.
- Editor-emptied ads (user deletes all nodes, then chats): a user-edited page
  name containing quotes/newlines makes `_quotable_page_name` suppress the F1
  steering block — honest degradation (the turn may thrash as pre-F1), never an
  injection.

## Incidents & environment (operational truths for the next session)

- **Missoula's fleet worker was killed** by an over-broad `pkill -f clue_api.fleet_main`
  during the walk and was NOT restarted (its env/DB — :5432 — is unrecoverable from
  colombo). That workspace's session must relaunch it. Lesson: PID-scoped kills only.
- Colombo stack relaunch recipe (all colombo-coherent now): source `../istanbul/.env`,
  PLUS `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES` must gain `http://localhost:3033`
  (.env only lists 3000/3020), PLUS `CLUE_AGENT_WORKSPACE_ROOT=/private/tmp/clue-agent-workspaces-colombo`
  (.env's value is empty; `/tmp` symlink is rejected), PLUS
  `CLUE_DESIGN_API_BASE_URL=http://127.0.0.1:8010`, PLUS
  `LUMEN_CORE_HELPER=<colombo>/subsystems/clue-design/target/release/lumen-api-helper`.
  The trio's `LUMEN_AGENT_API_KEY`/`LUMEN_AGENT_BASE_URL` are NOT in any .env — they
  lived only in the design-API process env (captured across restarts via `ps eww`).
  Design API :8010 now runs COLOMBO's checkout (was istanbul's).
- Shared 55040 dev DB carries stale `recipe0-stage0@2` rows → `tests/execution/test_recipes.py`
  promotion asserts red (pre-existing; rev 18 makes it likelier to bite). DB reset
  deliberately NOT done (would destroy the seeded walk fixtures). Also flaky:
  `tests/design/test_design_fleet_turns_db.py` (worker-claim timeouts, pre-existing).

## Where the full record lives

The SDD ledger (`.superpowers/sdd/2026-08-23-chat-driven-ad-creation/progress.md`,
gitignored) holds every ruling, fix round, review verdict, and deferred minor until
the workspace is deleted at finish; everything durable is in THIS note + the plan +
the commit bodies.

## ADDENDUM 2026-08-23 (later session) — generation UNBLOCKED; root cause CONFIRMED, earlier framing corrected

Systematic debug (forensics over 6 failed runs' traces + one single-variable live
experiment) **overturned the "transport fragility" framing**:

- **Root cause: the reviewer model `openai/gpt-5.6-luna` itself.** Every fatal call
  (5/5 runs) was the REVIEWER's late-session multimodal wrap-up; the author model
  never failed and swapping it changed nothing (my "two providers failed" claim was
  wrong — the reviewer stayed luna in both). Every POST returned HTTP 200; the
  `server_error` arrives ~240-284s in as an in-stream `response.failed` event —
  which is also why the SDK's existing `max_retries=2` (yes, retries DO exist —
  earlier claim corrected) never fires: nothing HTTP-shaped fails. Payload size
  exonerated (previews 8-124KB); client/gateway timeouts exonerated (streaming
  keep-alives defeat per-phase read timeouts); the same reviewer completed six
  quick calls incl. a full image critique seconds earlier in the same session.
- **Proof:** reviewer swapped (founder's choice: `openai:x-ai/grok-4.6` for both
  roles) → the very first run succeeded end-to-end: run_7c073f66, doc_da2edcb8
  v0→66, 13 nodes, split-panel LinkedIn ad live in the platform editor. FIRST
  successful chat-driven ad generation; the Task-5 persist path got its live proof
  (1 design_edit_envelope, undo_stack=1 — one intent one undo; version counts ops).
- **Founder item #1 REVISED:** not "add retry around a 4-min ceiling" — instead
  (a) avoid `gpt-5.6-luna` as the design reviewer until its /responses multimodal
  serving is fixed upstream (report to OpenRouter/OpenAI with request id
  req_1f6484cd373542e0a6241abb331ef25f); (b) the durable hardening is catching
  in-stream `response.failed` in the governed model layer and re-attempting that
  ONE call bounded — that class is invisible to HTTP-level retries.
- Ops: services now launch from **colombo's own `.env`** (founder created it;
  4 operational gaps filled in-session: workspace root, :3033 authorized party,
  design API base URL, LUMEN_CORE_HELPER). The F1 steering block + persist are
  proven live end-to-end.

## ADDENDUM 2026-08-23 (evening) — the birth-owns-the-page mechanism is SUPERSEDED (genad2)

Everything above about **format** is history, not current behavior. After the live evidence
(the F1 page-trap saga plus the registry-complexity discussion) the founder reversed genad
ruling 2: `open_design_leg` went to **`@4`**, which births a **ZERO-page** scene document
with **no format or dimension parameters**, and the design deepagent authors every page
itself from the user's own words (`size(w,h,pt|px|mm|in)` / `preset(...)`; the engine
normalizes). The format-preset machinery this note credits to commit `53f3219f` —
`AD_FORMAT_PRESETS` (square/portrait/story/landscape), `ad_birth_page`,
`mint_empty_ad_document`, and `tests/api/test_design_tools_ad_mint.py` — was **deleted**,
and `a5b2c561`'s `ad_format`/`ad_width`/`ad_height` input fields with it; Head-of-ABM v38 /
prompt v6's "infer-and-STATE the format" paragraph was replaced by v39 / v7's
route-and-delegate posture (it never resolves presets, units, or dimensions), and F1 is now
legacy support for the two already-seeded empty-page ads only — no new birth can reach it.
What SURVIVES from this lane, unchanged: scene-birth brand stamping, the one-transaction /
leg-derived-id / guard-0 / pin-read-back disciplines, the leg-only scene persist under CAS,
and the gallery → auto-open → editor loop. The live-proven walk above (and the
grok-4.6 reviewer finding in the addendum) remains valid evidence for those. Superseding
plan: `docs/superpowers/plans/2026-08-23-agent-authored-pages.md`; rulings:
`_memory/2026-08-23-genad-rulings.md` §ADDENDUM 2.
