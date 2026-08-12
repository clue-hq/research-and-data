# 2026-08-13 — FI-4 slice 3 SHIPPED: granular recon truth end to end

Branch `platform/onboarding-integration`, commits `b2fda5e9..20a30181` (plan `b2fda5e9`; nine
code tasks, each adversarially reviewed, four of them through one fix round). Plan:
`docs/superpowers/plans/2026-08-12-slice3-onboarding-granular-truth.md`. Ledger:
`.superpowers/sdd/2026-08-12-slice3-onboarding-granular-truth/progress.md`.

## What landed (per task)

1. `ae609d78` — named the event kinds (`RECON_FIELD_PROGRESS_KIND = "stage0.recon.field"`,
   `RECON_TRANSITION_KIND`) and the `FieldProgressStatus` vocabulary
   (`started|resolved|empty|failed`). `empty` is a CORRECT outcome, not a failure.
2. `5184dd4e`/`54bf26b6` — per-field emission from `reverse_profile`'s loop via an
   `on_field_progress` seam; `ReconFieldProgressEmitter` (`platform/api/clue_api/
   stage0_field_events.py`) writes the `run_event` outbox. Factory-less writes are contained
   in a savepoint.
3. `b5077e84`..`69b887c7` — `GET /stage0/setup/current` serves `fields[]` (server-reduced
   last-writer-wins by `seq`, **across lanes**, in `CLIENT_BASELINE_FIELDS` order) plus
   `fast_/background_budget_exhausted` (`null` = unknown, never a fabricated `false`);
   COMPLETED lane transitions now carry `budget_exhausted`; the **`starting` branch** serves
   per-field truth for a run whose `recon_run` row is not yet visible.
4. `9b922285`/`83997645` — the production `LlmClaimExtractor`
   (`platform/api/clue_api/claim_extraction.py`): grounded (span AND `source_url` must be
   literal substrings of the full normalized document), drop-never-raise.
5. `fa5f1426`/`f9405c83` — composed at BOTH roots through the single
   `build_stage0_claim_extractor(gateway)`, but each root sources its gateway per its OWN boot
   contract: `projections_main` (HTTP) uses the **degrading** `build_optional_platform_gateway`
   (no key → loud `stage0.claim_extraction_disabled_no_gateway` warn + empty extractor, never a
   raise); `fleet_main` (worker, `:465`) passes the **mandatory** `build_platform_gateway`
   gateway `_serve` already built (`:500`), which deliberately RAISES without a key — fail at
   boot is correct for a worker that cannot do its job otherwise. Do not "unify" these.
   The Lane-D2 guard's prose was narrowed to name the one HTTP-root exception.
6. `b77e7713` — `client.competitor` + `client.buyer_profile` registered (object-typed,
   `tier_plan=("exa_search",)`, THIRD_PARTY surface), **appended at the END** of
   `CLIENT_BASELINE_FIELDS` so no existing field's budget position moves. Baseline = 11.
7. `3de86bca`/`8ba0dfcc` — the tier-3 `exa_search` resolver (Exa search, structurally refuses
   any `deep` search type). Detail note: `_memory/2026-08-13-slice3-task7-exa-search-tier3.md`.
8. `b81fd02c`..`3d86868f` — the four-group D-6 checklist: groups as DATA
   (`apps/frontend/src/features/onboarding/data/setup-groups.ts`), pure reduction
   (`model/setup-items.ts`), lane-truth halting, one detail-line annotation per row,
   brand-kit dummy row.
9. `e05fc73e`..`20a30181` — the `SetupProgressSource` seam (`httpSetupProgressSource` +
   `createFixtureSetupProgressSource`, 14 wire-faithful frames ending at the `complete`
   release frame). Fixture-mode default is **still the static theatre**.
10. this commit — contract doc, FI-4 §9 ratification entry, this note.

## Gotchas a future agent will otherwise rediscover

- **The emitter's two paths are a deadlock design, not an accident.** With a `conn_factory` it
  commits on its OWN connection (a poller sees motion mid-lane); without one the event rides
  the lane connection inside `begin_nested()` (post-commit-visible). `field_progress_factory`
  **defaults to `None`** because an autonomous second checkout against a single-connection /
  lock-guarded test factory makes the lane wait on a connection it is itself holding.
- **The production wiring is an identity check**: `toolbelt_wiring.py` composes the autonomous
  path only when `conn_factory is transaction` (`clue_db.transaction`). Anything else falls
  back and **logs `toolbelt.stage0_field_progress_lane_bound`** — because the fallback is
  silent-shaped (the onboarding screen would show nothing for the whole fast lane). A future
  request-scoped or instrumented production factory would kill the feature with green tests;
  the log is the only tripwire. Both directions are pinned by tests.
- **The healthy fast lane never reports overall `running`.** It lives inside ONE transaction,
  so its `recon_run` row is invisible until it commits; `starting` is where all its motion is
  read. Any surface that treats `starting` as "nothing happening yet" is wrong.
- **Cross-lane LWW regresses on purpose.** The background lane re-runs `reverse_profile` over
  every baseline field, so a field goes `fast/resolved` → `background/started` after release.
  There is no re-research marker on the wire; the frontend explains it with the
  `" — deepening research"` annotation (withheld when the fast budget was exhausted, since a
  background `started` may then be first contact).
- **pydantic `Settings()` reads the repo `.env` FILE directly** — an untracked env line flips
  backend-selection and reasoning-trace tests. (Same trap as slice 2.)
- **Boot order: any `seed_source_manifests` caller must load BOTH packs.** Naming `client.*` in
  the `exa_search` manifest's `yields` made the client-knowledge pack a prerequisite of
  seeding; 14 call sites were patched (4 production — `exa_websets_materialization`,
  `contact_channel_enrichment`, `sumble_claim_materialization`, `exa_targeted_enrichment` —
  and 10 test harnesses).
- **`PAUSED` has no production writer today.** The frontend decodes it defensively for the
  enum contract (FE-M3 posture); do not "simplify" it away.

## Standing residuals (none blocking; carried forward)

- **[clue_db] Pool-checkout stall.** The autonomous emitter takes ~2 pool checkouts per field.
  Under pool exhaustion the lane BLOCKS for the checkout timeout (~30s) before the swallow, so
  observability can stall the lane it must never fail. A bounded `pool_timeout` on the
  progress factory is the suggested fix; owner is `clue_db`, not stage0.
- **Rollback-surviving events.** Events on the autonomous path survive a lane rollback by
  design. Lane truth (`recon_run` status) supersedes on the read side; nothing reconciles the
  orphaned field rows.
- **A paused FAST lane stops the spinner but explains nothing.** Slice 3 halts the checklist
  honestly (no fabricated motion), but overall status stays `running`, polling continues, and
  no paragraph says why. Closing it needs a 4th annotation or a hook change
  (`hooks/use-setup-progress.ts`). Deliberately deferred out of task 8/9 scope.
- **Import-discipline guards are unenforced repo-wide (PRE-EXISTING ROT).** Both
  `tests/resolvers/test_static.py` and `tests/sources/test_static_invariants.py` scan a `src/`
  path that no longer exists post-monorepo-move, so the guards assert over an EMPTY file set:
  `test_resolvers_never_branch_on_provider_name` (`tests/resolvers/test_static.py:95`) and
  `test_no_provider_subpackage_imports_another` (same file, `:107`) on the resolvers side, and
  `test_nothing_outside_sources_or_obs_branches_on_provider`
  (`tests/sources/test_static_invariants.py:18`) on the sources side. Slice-3 compliance was
  verified by inspection instead. Worth a dedicated fix.
- **Stale dev-DB rows.** The local dev DB carries committed `crm` source-manifest and
  `recipe0-stage0@2` recipe rows that conflict with current definitions → 8 pre-existing
  failures in `tests/{resolvers,sources}` (+2 in `tests/execution`). A dev DB reset clears
  them. Also 7 pre-existing `tests/api` failures from `CLUE_CHAT_REASONING_TRACE_MODE=raw`
  in `.env`.
- **A refused Exa call still charges 1¢**, engine-consistent but unasserted; the lane test
  does not pin `result.cost_cents`, and the refusal test covers `client.competitor` only, not
  `client.buyer_profile`.
- **Snapshot capture for Exa records is DEFERRED.**
  `subsystems/research/clue_research/resolvers/exa_search/__init__.py` has **zero**
  snapshot/artifact/storage wiring — unlike the snapshot-wrapped scrape lane, which captures
  sha-256'd bytes through the B2 storage seam. So `client.competitor` / `client.buyer_profile`
  claims cite a `source_url` + verbatim `evidence_span` with **no durable evidence blob**: if
  the cited page changes or vanishes, the span cannot be re-verified from our own bytes. Not a
  fabrication risk (the three fail-closed guards — attributable, span-grounded in the *cited*
  record, target-locked — still hold), but an evidence-*durability* gap, and a precondition for
  any evidence-serving surface (presign, review annotations) built over recon claims. Note this
  interacts with the [B2×presign] charter item: a claim citing no artifact at all is a
  different hole from one citing a workspace-scoped artifact.
- **No env-backed override for `Stage0Policy` exists today.** The 2026-08-13 ruling names
  `CLUE_STAGE0_FAST_BUDGET`, but that env var does not exist —
  `libs/clue-config/clue_config/stage0.py` is a frozen model of constants injected at the
  composition root (`toolbelt_wiring.py`, `DEFAULT_STAGE0_POLICY`). "Raise the envelope per
  deployment" is a code/composition change right now. Adding the override is the small
  follow-up that makes the ruling literally executable; recorded in FI-4 §9 item 6.
- **`recon_brief` reads at `fast_client_kb_version` only.** Background-lane facts — which is
  where `client.competitor` / `client.buyer_profile` necessarily land (tier 3 > the fast
  lane's tier-2 ceiling) — never appear in the brief, and `fact_count` on the setup read
  inherits that. The screen releases before the background lane finishes, so it is not a
  slice-3 defect, but any surface that reads the brief as "the Client KB" is under-reading.
- **Founder items pending review:** the four group labels + detail lines and the three
  annotation strings (`" — part of this hit a problem"`, `" — stopped at the research
  budget"`, `" — deepening research"`) are integration-authored copy; and the setting-up
  checklist grew from three rows to five (four groups + the brand-kit dummy).
- **[M9.1] One more ungated spend path.** Extractor LLM spend is now reachable in the WEB
  process (`POST /tools` → `start_recon`, one completion per supported field per scraped
  page) and is not routed through `PreSpendGate` — it joins the charter's standing [M9.1]
  composition-root list alongside Lane E's three paths. Out-of-envelope spend here is
  founder-ACCEPTED per the quality-before-cost / budget-unconstrained rulings (FI-4 §9,
  `184dcf2e` and `868cbde4`); reviewers must not raise budget strictness as a blocker.

## Gates at close-out

Backend `uv run pytest tests/stage0 tests/api tests/resolvers tests/sources tests/projections`
— 15 failures, all in the two known pre-existing sets (7 `tests/api` from the `.env`
reasoning-trace mode, 8 `tests/{resolvers,sources}` from the stale dev DB); no new failures.
`make lint` clean (1342 files), mypy clean. Frontend
`design-system:build && lint && build && test` — all green, **204/204**.

## Remaining

Final whole-branch adversarial review over `b2fda5e9^..HEAD`.
