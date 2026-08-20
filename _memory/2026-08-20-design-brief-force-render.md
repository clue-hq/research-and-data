# 2026-08-20 — website ingestion always force-renders + the embedded-worker ImportError

Branch `integration/frontend-design-part-iv-v2`, worked directly. Brief:
`.superpowers/sdd/2026-08-20-brand-design-brief/force-render-brief.md`. Report:
`.superpowers/sdd/2026-08-20-brand-design-brief/force-render-report.md`. Fixes findings 1
and 3 of the slice-4 walk (`_memory/2026-08-20-design-brief-slice4-acceptance.md`).

| # | hash | subject |
|---|---|---|
| 1 | `c9bf2859` | `fix(design): brand-kit website ingestion always force-renders (founder ruling)` |
| 2 | `b1ab25e5` | `fix(design): geometry evidence imports cleanly in the embedded fleet worker` |
| 3 | this note + the report | docs |

## Part 1 — always render, enforced server-side

`lumen_ingestion/pipeline.py::_ingest` no longer reads `request["force_render"]`; it passes
`force_render=True`. That one function is the choke point for EVERY website ingestion — the
HTTP route, the `design_ingest_website` tool, the platform proxy, and a re-offered envelope
replayed by a worker — so a client that sends no flag still gets geometry ("geometry needs a
live page by definition", founder 2026-08-20). `IngestWebsiteRequest.force_render` survives as
redundant-but-harmless and says so at the field; it can no longer turn rendering OFF. PDF and
upload ingestion are untouched. The honest cost (a ~10s static ingest becomes minutes) is
stated at the call site, together with why it is affordable (the job is offered and drained
asynchronously).

**Static-tier evidence check (the brief's explicit ask).** How the tiers merge today: the
rendered snapshot SUPERSEDES the static one — even on the escalation path, only static's fetch
diagnostics survive, never its snapshot. So "follow the existing design" = supersede. Auditing
what the static tier actually contributed: assets, meta and inline CSS are all reproduced by
the rendered tier (it reuses `_collect_assets` / `_extract_meta` on the post-JS DOM and reads
inline rules from the CSSOM, which is strictly better) — with ONE exception. Static follows one
level of `@import`; the rendered tier did not, because `document.styleSheets` exposes an
imported sheet only as the parent's one-line `@import` rule text. Harmless while rendering was
a rare escalation, a real loss once every ingestion renders: a brand whose `@font-face` or
palette lives behind an import would silently stop being read. Closed by extracting
`static.fetch_imported_sheets` and calling it from both tiers; the rendered tier's stylesheet
assembly is now `rendered.collect_stylesheets`, testable without a browser.

## Part 2 — the `GeometryEvidence` ImportError: root cause (NOT a circular import)

**A mixed-version module graph inside a stale process.** Chain of evidence:

1. The full message (from the job row, not the walk's paraphrase) is
   `cannot import name 'GeometryEvidence' from 'lumen_ingestion.evidence' (/…/evidence.py)` —
   with the file path, and WITHOUT "partially initialized module … most likely due to a
   circular import". That message shape means the module was in `sys.modules`, fully
   initialized, from the right file, and simply did not have the attribute.
2. `LUMEN_EMBEDDED_FLEET_WORKER` **defaults to True** (`py_lumen_config/config.py:74`), and the
   fleet leases by work KIND, not by which process offered the job. Every design API pointed at
   one database therefore competes for the same `design_job` rows; the winner is whoever polls
   first (0.1s).
3. The culprit was pid 19882 — a design API on **8011**, cwd = istanbul, started 18:40Z, i.e.
   **three hours before** `GeometryEvidence` was committed (`bef817cd`, 21:44Z). It had
   `lumen_ingestion.evidence` in memory from its own start-up; `capture/geometry.py` did not
   exist then and was read FRESH off disk at job time, because the capture tiers are imported
   lazily, only once a rendered capture is already running. Old module, new importer.
4. Reproduced today at 00:34Z: a `force_render` ingestion failed in 0.2s with the identical
   message, `leased_by=lumen-api-embedded:00afb68e…` — the SAME worker id as the walk's two
   failures, still alive.
5. Attributed decisively: with 19882 suspended (`kill -STOP`), the identical job was claimed by
   the live 8010 worker (`a162a49a…`) and **succeeded in 36.9s**. So `00afb68e` was not 8010's
   worker, and 19882 was the only other `lumen_api` process on the machine.
6. Mechanism re-created in isolation: faking a stale `lumen_ingestion.evidence` in `sys.modules`
   and re-importing `lumen_ingestion.capture.rendered` reproduces the message byte for byte,
   file path included.

This explains the two facts the walk could not: static ingests on that worker succeeded (the
static tier never imports `geometry`), and the identical call always worked out of process.

**No import restructuring was done, deliberately.** The laziness is what made the version skew
LOUD. Eagerly importing the rendered tier at package import would have left that process quietly
running yesterday's capture instead of failing — strictly worse. The genuinely missing thing was
a TEST: nothing in the suite ever executed the rendered tier's import edge, so a real circular
import or a renamed symbol there would have shipped exactly as far.
`test_the_rendered_tier_imports_cleanly_in_a_worker_shaped_process` (in `test_ingestion_capture.py`,
beside the existing fresh-interpreter hygiene test) runs a clean interpreter in the worker's
import ORDER — `lumen_api.main` first, then the capture chain the job reaches later — and asserts
`capture.geometry.GeometryEvidence IS lumen_ingestion.evidence.GeometryEvidence` (the identity a
half-old graph fails) plus that importing the rendered tier still pulls no playwright.

### DEV-DISCIPLINE TRAP (read this before any ingestion verification)

**Never leave an old design API running.** `LUMEN_EMBEDDED_FLEET_WORKER` defaults ON, the design
job queue is shared Postgres, and leasing is by kind — so ANY stale `lumen_api.main` process on
the machine silently executes today's jobs with yesterday's modules, from a window nobody is
watching. Before verifying anything through the UI:

```
lsof -nP -iTCP -sTCP:LISTEN | grep -E ':(801[0-9]|8030|3030)'
ps -eo pid,lstart,command | grep '[l]umen_api.main'     # exactly ONE, started after your commit
```

The canonical istanbul stack is: **8010** (design API + embedded worker), **8030** (platform),
**3030** (frontend), the istanbul `clue_api.fleet_main`. Nothing references 801x beyond 8010
(`CLUE_DESIGN_API_BASE_URL=http://127.0.0.1:8010`). During this session two extra design APIs
existed (8011 and 8013, both from the orchestrating session); 8011 was stopped outright on the
coordinator's decision, and 8013 — started after the fix, so carrying it — is the worker that
actually executed the verification. Recorded at the code site too:
`lumen_api/main.py::_build_embedded_fleet_worker`.

**Durable fix is NOT built (deliberate — a real design decision, not a drive-by):** a staleness
guard on the lease path, e.g. workers stamp a code/schema version when they lease and refuse
kinds newer than their build, or the job carries a minimum module version. Proposed as a
design-lane follow-up in the report's concerns.

## Live verification (the real UI, 8010 restarted onto the commits)

- Preflight: `design_agent_run WHERE status='running'` → empty, twice.
- Re-extract pressed on `/brand-context` (real button, Playwright MCP, logged-in shell).
- Durable request row: `force_render: false` — the frontend's `ReExtractRequest` is
  `{url, brand_kit_id}` and sends no flag. The job's stage went to **"Taking a closer look…"**,
  which only `capture/rendered.py::fetch_rendered` emits. Server-side enforcement, with zero
  frontend change.
- **149.8s** (vs the walk's 10s static ingest), published **v7 DRAFT**.
- v7 geometry provenance: **28 `website:`-provenanced tokens + 15 `derived:`** — identical yield
  to v6 (the manual out-of-process forced render), against **v5 = 40 derived / 0 website / no
  brief**, which is what the UI produced before this fix.
- v7 carries a real `BrandBrief@1`: characterization `stadium, product-polished, precise`,
  9 constraints, 13 component recipes, 10 palette-application rules, 6 signature compositions,
  6 honest diagnostics; `ratio_summary` = "6 white canvas bands : 1 deep navy statement : 1 cool
  muted footer".
- `Design.md` renders `version 7 · Draft` with the brief. **NOTHING WAS APPROVED** — v7 is left
  a draft and v6 remains the approved kit.
- Screenshots (gitignored): `.playwright-mcp/forcerender-01-brand-context-midrun.png`,
  `-02-brand-context-midrun-preparing.png`, `-03-design-md-v7-draft.png`.

## Gates (no platform `.env` sourced for the test runs)

| gate | result |
|---|---|
| `apps/agent_runtime/tests` | **612 passed, 2 skipped** |
| ingestion set (capture / routes / brief / geometry / normalizer / jobs / ui_api / describe / font_metrics / raster / deployment_config / pdf ×2 / uploads ×2) | **231 passed, 4 skipped** (+6 new) |
| adjacent (`test_api`, `test_write_path_governance`, `test_workspace_seam` ×2, `test_phase_g_conformance`) | **149 passed, 2 skipped** |

Red-proofed before implementing: all three force-render tests failed on the pre-fix pipeline,
and the rendered-`@import` test fails if the shared follow is removed.

## Discipline

Local commits only, never pushed. No AI-attribution trailers. No `git stash`. No `.env` or
secrets committed (DB URL read from env, never echoed). No subagents. Browser work via
Playwright MCP only. Processes touched: istanbul's own 8010 (restarted, sanctioned), the stale
8011 (stopped — root cause, then the coordinator's ruling). tunis / missoula / milan /
port-of-spain untouched.
