# 2026-08-27 — Phase F0 (clone capture substrate) COMPLETE

Plan: `docs/superpowers/plans/2026-08-27-clone-fidelity-master-plan.md` (status header updated).
Commits `7c11f0eb6..298abe98d` (19) on `integration/frontend-design-part-iv-v2`, LOCAL ONLY.
Process: SDD — Opus implementers, independent Opus review per task + scoped re-reviews, final
whole-phase review + ONE fix wave. Evidence trail preserved at
`.superpowers/sdd/2026-08-27-clone-fidelity-master-plan/` (ledger `progress.md` has every ruling).
NEW STANDING RULE (founder, mid-phase): review subagents are Opus-only from now on.

## What F0 delivered
- **F0.1/F0.4**: `design_site_snapshot` table (migration `4fb8a2ff791b`, design lane, single head,
  FK ON DELETE RESTRICT — clone source outlives job bookkeeping), `lumen_ingestion/site_snapshot.py`
  persist/read seam, bytes under `{ws}/design/{sha}` `source_key=design_site_snapshot`;
  `capture_website(page_urls=…)` multi-page provision (no producer yet). LUMI0512/0513.
- **F0.2**: unified collector `capture/candidates.py` (`AssetCandidate(url, origin, kind,
  dark_scheme, detail)`); budgets not caps (400 assets/100MB, LUMI0514) + loud drops (LUMI0515)
  + per-rung font failures (LUMI0516, `bound` key, bound-rungs-first-globally); slurp-<sha12>-<name>
  filenames; D-F2 fonts `embeddable: true` with basis in restrictions line (Rust FontLicense
  round-trip DROPS unknown keys — real `basis` field is an F1 obligation + publish exclusions
  manifest fix). `cap_and_summarize` + `short_url`/MAX_URL_CHARS=200 are the loud-but-bounded house
  patterns.
- **F0.3**: `capture/declared_roles.py` — declared CSS custom props → direct role assignment
  (`basis: declared`, 0.9, `custom-prop:<name>`) for surface.page/text.primary/surface.brand/
  surface.accent; qualify-by-name, rank by (light-hint, len(words), chroma tie-break); AA gate on
  declared text (LUMI0518) + neutrality gate on brand/accent (LUMI0519, NEAR_NEUTRAL_C=0.03);
  `BrandEvidence.state_styles` (StateStyle, cap 200, LUMI0517) + `.declared_roles`; dark-block
  custom props → `dark_colorway: captured`; var() cycle guard names the chain; resolvable alpha
  vars resolved.
- **Fix wave**: shared `capture/cssurl.py` (escaped-paren url() handling, all 3 copies);
  fetch-failure dedupe across all capture branches; ingest_failures capped.

## Acceptance (live walk, insighthealth.ai, report in SDD workspace)
All 4 criteria PASS: snapshot+screenshot durable (3.1MB screenshot, 24 stylesheets); 212/215
assets captured, 3 loud drops, 0 silent; Aeonik 6 faces with binaries + ToU stamp; mint #30D8A7 =
surface.brand from `--base-color-brand--green` (NOT the black/white family — the neutrality guard
working). 39.7s/40.9s per ingest; re-run dedups (113/114 shared digests).

## Suite verdict
Full apps/api: 1054 tests, 17 failures — ALL custom-component family, cause: missing `typescript`
node dep in this workspace's compiler worker (environmental, pre-existing). ZERO F0-owned
failures. `test_ad_assets_onboarding::test_an_empty_harvest_says_so_at_the_top_level` is a
PRE-EXISTING v4-lane RACE (embedded fleet worker vs `_run_job`'s direct drive over a route-offered
job) — flaky, passed on the second full run; owned by the colombo lane, not F0.

## Environment rules (hard-learned, binding for future phases)
- Dedicated throwaway DB per work stream (`clue_f0_*` pattern; DSN in .env is
  postgresql+asyncpg — strip `+asyncpg` for psql). Necessary but NOT sufficient: the ingestion-job
  suites tolerate NO concurrent pytest on the same DSN, including your own second session.
- colombo workspace's live uvicorn (8060) + fleet worker share the dev `clue` DB and steal
  ingestion jobs → spurious route-test failures. Founder asked-to-be-asked: whether that worker
  can be shut down during suite runs.
- Custom-component tests need `apps/custom-component-compiler` node deps (typescript) installed —
  absent here, hence the 17 environmental failures.
- Teardown: `clue_f0_task1/2/3/smoke/walk/full/wave` DBs dropped at close (walk artifacts /tmp/f0_walk
  removed after fix-wave verification).

## Carried forward (owners assigned in the final review's triage table, in the ledger)
- **F1**: Rust `FontLicense.basis` field + publish manifest stops discarding font exclusions;
  D-F2 restrictions-encoding pin through the real Rust round-trip.
- **F2**: library visibility of slurped assets (ruling: rehost-all stays, presentation is F2's);
  F0.4 page-list producer (+ cap + malformed-input warning + per-page failure diagnostics);
  light-preferred picture-rung selection; inlined data-URI font faces custody; LUMI0231 wording in
  the clone frame; dark-side declared-role names; `[data-theme]`/`html.dark` dark capture;
  unquoted hex-escape url() tokens (silently dropped — same as pre-F0).
- **UNOWNED, needs a name**: `logo_ladder.py:~400` fourth broken `url()` copy (escape gap +
  missing quoted branch) — the IDENTITY path; route through `capture/cssurl.iter_css_urls`.
- **FOUNDER FLAGS**: trial-font embeddability under ToU basis (AeonikTRIAL now embeddable:true
  live; PDF-lane fonts stamped too) — legal call; colombo worker shutdown question.
