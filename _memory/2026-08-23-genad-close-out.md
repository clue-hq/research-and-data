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
4. Smaller: prose-summary of a *committed* scene turn still reads "proposed" and
   doesn't name the new version (plan-sanctioned; reads oddly now);
   `brand_kit=` param vs `meta.brand_kit` scene/columns divergence (exact web
   mirror, both-kinds decision).

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
