# 2026-08-19 — genweb slice 0: design runtime enabled + substrate preflight PASSED (one blocker found)

Plan: `docs/superpowers/plans/2026-08-19-chat-driven-website-generation.md` §5 Slice 0.
Branch `integration/frontend-design-part-iv-v2`. Full drive report:
`.context/slice0-preflight-report.md` (gitignored scratch; durable facts here).

## THE WORKING LAUNCH RECIPE (supersedes the 2026-08-17 recipe for the generation era)

All from the istanbul repo root; port-check before every launch; long-running servers as
persistent background tasks (a `nohup &` inside a completing shell gets reaped — bit us
AGAIN this session, twice).

- Root `.env` now carries `CLUE_DESIGN_RUNTIME_ENABLED=1` (added slice 0; .env is
  gitignored — every fresh checkout must re-add it or export it).
- **Platform API 8030:** `set -a; source .env; set +a;` then
  `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES='["http://localhost:3020","http://localhost:3030"]'
  CLUE_DESIGN_API_BASE_URL=http://127.0.0.1:8010 CLUE_DESIGN_RUNTIME_ENABLED=1
  .venv/bin/python -m uvicorn clue_api.projections_main:app --host 127.0.0.1 --port 8030`
- **Design API 8010** (the script is kept at `/tmp/slice0-relaunch-8010.sh`; recreate
  from this list): source root `.env`, then export
  `CLUE_STORAGE_FS_ROOT=/tmp/lumen-dev-storage`, `LUMEN_INGESTION_VISION=1`,
  `LUMEN_INGESTION_DESCRIBE=1`, `OPENROUTER_API_KEY="$CLUE_OPENROUTER_API_KEY"`,
  `LUMEN_AGENT_API_KEY="$CLUE_OPENROUTER_API_KEY"` (does NOT flow from the CLUE_ var —
  the 2026-08-14 trap, re-confirmed), **`LUMEN_AGENT_BASE_URL=https://openrouter.ai/api/v1`
  (NEW TRAP, found this slice: `llm.py:121` hard-refuses without BOTH base URL and key —
  every turn fails in ~2s with `agent_runtime.failed`)**,
  `LUMEN_AGENT_MODEL=openai:anthropic/claude-opus-4.8`,
  `LUMEN_EMBEDDED_FLEET_WORKER=1` (the API drains its own `design_job` queue — claims
  within ~2s; no separate fleet worker needed for design turns),
  `LUMEN_CORE_HELPER=<repo>/subsystems/clue-design/target/release/lumen-api-helper`;
  then `uvicorn lumen_api.main:app --host 127.0.0.1 --port 8010`.
- **Frontend 3030:** unchanged (shell overrides `CLUE_API_BASE_URL=…8030`,
  `LUMEN_API_BASE_URL=…8010`).
- **Fleet caveat for slice 1+:** the only `clue_api.fleet_main` running on this machine
  belongs to the TUNIS worktree (another branch) — it serves the shared dev DB's chat
  turns with THAT branch's code and no design lane. Before slice 1's leg turns, run an
  ISTANBUL `fleet_main` with `CLUE_DESIGN_RUNTIME_ENABLED=1` (and mind double-claiming
  with tunis's worker).

## Preflight results

- **(a) PASSED.** `Settings().design_runtime_enabled` resolves True from the dev env;
  `tests/api/test_p34_design_leg_tool_db.py` 7/7 (covers both gate directions — the
  `design_leg_runtime_not_configured` refusal when off, clean pass-through when on).
- **(b) PASSED — the substrate is real end to end on this trunk.** Everything through
  the authenticated BFF from the page context: create scratch doc → `POST
  …/web/turns` (brief: "Harbor & Sage" coffee-roastery landing page) → embedded worker
  claimed in ~2s → the trio ran (37 events, 3 review iterations) → **committed v0→1 in
  6m29s** → doc `doc_feb8f81a6d2642ec82224b6d1610a49c` carries the generated page and
  the artifact route renders it in the shell (screenshot
  `.playwright-mcp/slice0-preflight-render.png`). Note: the artifact route opens a
  gallery-invisible doc fine by id (no design_leg row → no rail card, as designed).

## Findings (beyond the recipe)

1. **BLOCKER for realistic generations — reviewer previews have no size ceiling.**
   First attempt (doc A `doc_6b7db048…`): the author built an 84-node page; the
   reviewer's Playwright captures came out 1440×14325 / 768×8095 px; the vision model
   refused (`invalid_prompt … image dimensions exceed max allowed size: 8000 pixels`);
   the turn is transactional so ALL 84 nodes were discarded; and `result.diagnostics`
   was EMPTY (the reason only lives stringified in `summary`). `tools/view.py::
   _normalize_image_bytes` clamps only a 512px FLOOR — "already-large images pass
   through unchanged" — no ceiling/tiling. Threshold ≈ 3–4 sections, i.e. nearly every
   real landing-page brief. The short doc-B page (~1200px previews) sailed through.
   **Owned by the generation plan (amended, slice 1): downscale-to-ceiling fix + a
   diagnostics entry for review-call failures.**
2. **No-kit theming datapoint:** with no approved brand kit in the workspace, the born
   document's theme is ALL-NULL (`effective_brand_kit` all null, committed scene
   `"theme": {}`) — not a "platform default kit" — and the agent invents its own
   palette anchor. Matches the frozen creation contract; recorded so the brand-theming
   slice asserts the real fallback shape.
3. **Timing:** a successful generation is ~6.5 minutes — the plan's transcript wording
   ("takes a few minutes") is right; slice 3's refresh-on-completion design holds.
4. Asset search returns 0 in a bare workspace → generated pages are text+CSS-only until
   assets/brand logos exist (composes with the brand-kit pipeline later).

## Evidence docs (left in place, dev data)

`doc_feb8f81a6d2642ec82224b6d1610a49c` (v1, the committed generation),
`doc_6b7db04896744046b641ae5054e1e384` (v0, the blocked tall page), runs
`run_a178d2e6…` (success), `run_f0127607…` (the 8000px failure), `run_7fe79a40…`
(the missing-BASE_URL failure).

## Next

Slice 1 (web-turn dispatch branch) + the preview-ceiling fix; founder rulings F1–F5
still pending (F1 gates slice 1's scope confirmation, F5 gates slice 2).
