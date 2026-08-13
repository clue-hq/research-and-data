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
- ~~**No env-backed override for `Stage0Policy` exists today.**~~ **RESOLVED in the final fix
  wave (2026-08-13, commit `aea52fba`).** The whole-branch review found the day-one envelope
  actually truncating onboarding (firecrawl ~1¢/fetch × 11 fields vs the 5¢ fast cap → the
  user released with checklist groups 3–4 annotated "stopped at the research budget"), so the
  mechanism landed: `Settings.stage0_fast_budget_cents` / `.stage0_background_budget_cents`
  (env `CLUE_STAGE0_FAST_BUDGET_CENTS` / `CLUE_STAGE0_BACKGROUND_BUDGET_CENTS`, `gt=0`),
  `clue_config.stage0_policy_from_settings`, and `build_toolbelt` composing the Stage-0 tools
  under it. **Production default fast = 25¢** (the whole eleven-field walk with headroom);
  `DEFAULT_STAGE0_POLICY` stays 5¢/100¢ as the library default many tests pin. Only the
  budgets are settings — dedupe TTL and readiness floors stay versioned constants. FI-4 §9
  item 6's phantom-var note is superseded by item 8.
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

## Final fix wave (2026-08-13, after the whole-branch review)

The review returned three Important findings; all three are closed, plus three minors.

1. **Stalled fast lane spun forever (frontend).** The poll hook bounded only consecutive `none`
   reads, but the durable input row makes `none` unreachable after start and a healthy fast lane
   lives its whole life in `starting` — so a dead backend driver left the screen spinning with no
   recovery controls. The stall decision is now a pure, unit-tested function
   (`model/setup-stall.ts`: `progressSignature` / `stallAdvance` / `isStalled`, 40 unchanged
   in-flight ticks = 60s, the same budget the `none` path uses) and the hook surfaces the same
   recoverable terminal. Commit `db9a1afd`.
2. **Sync LLM calls block the web process's event loop — RECORDED, not fixed** (the review's
   accepted alternative). `_drive_recon` runs on the serving loop; the waterfall calls
   `resolver.resolve` synchronously and the extractor's `LLMGateway.complete` is sync, so each
   extraction blocks every other request in the process — one completion per field. Gated today
   by `self_serve_provisioning_enabled` **and** a real `OPENROUTER_API_KEY`. Loud comment at the
   `asyncio.create_task` site + a `[slice3×stage0]` charter backlog bullet naming the owner (the
   flag-enablement PR) and the two options (fleet-driven recon; an `asyncio.to_thread` hop at the
   waterfall seam). The same wave folded the `exa_search`-as-second-consumer-of-`names_present`
   note into the charter's [M9.4×M9.6] bullet, cross-referenced the Exa snapshot gap from
   [B2×presign/frontend], and recorded the `src/`-path rot that makes three import-discipline
   static guards assert over an empty file set (`[tooling]`, deliberately not fixed here).
3. **Day-one envelope truncated onboarding.** See the resolved residual above (commit `aea52fba`).

Minors: the two Exa field guidance descriptions now quote the registry verbatim; `_field_truth`
reads `ReconLaneStatus.COMPLETED.value`; `ExaSearchConfig.query_templates` is `Mapping[str, str]`.

**Gates.** Backend `tests/stage0 tests/api tests/resolvers tests/sources` — **exactly the 15 known
pre-existing failures**, byte-identical to the pre-change baseline (the earlier 296-failure run in
this workspace was a stale dev DB; `make db-fresh && make migrate` restored it). `make lint`,
mypy (635 files) and `lint-imports` (25 contracts) clean. Frontend gate green, **214/214** (204 +
10 new stall tests).

## Remaining

Nothing on slice 3. Next: slice-3 close-out sign-off, then the phase-2 project-level flow.

## Close-out addendum (post final whole-branch review, 2026-08-13)

The final whole-branch review (verdict "with fixes") produced 3 cross-task Importants, all closed by
the final fix wave (`aea52fba` backend envelope mechanism + minors, `db9a1afd` frontend stall clause,
`3ce5d164` record-and-own + charter bullets), verified by a scoped re-review with zero open findings.
Two new minors were adjudicated PARKED at close-out:

1. **`stage0_policy@1` pin provenance drift** — `build_recipe_pin_registry` publishes
   `DEFAULT_STAGE0_POLICY` (5¢/100¢) while runs execute the settings-derived policy (25¢ default).
   Non-functional today (both sides read the same static catalog) but the journaled pin no longer
   describes the executed envelope. Owner: the pin/provenance owner (C6/M12 adjacency). Fix: thread
   `stage0_policy_from_settings` into `build_recipe_pin_registry`, or derive the pin version from the
   payload.
2. **"eleven fetches / ~11¢" fast-walk arithmetic overstates by two** — the tier-3-only fields are
   gate-skipped in the fast lane, so it is 9 fetches / 9 extractor completions. Stated in five
   doc/comment sites (settings.py, toolbelt_wiring.py, stage0_setup.py, onboarding.md, FI-4 §9).
   Errs loud/safe; 25¢ headroom unaffected. Sweep in the next doc pass.

Also recorded from the re-review: `estimate()` now declares 25¢ (agent-planner ceiling default
1,000,000 millicents — harmless unless a deployment tunes that below 25,000); the charter's
`[audit 2026-08-07]` composition to-do item (2) is stale (the scrape binder IS wired since slice 2).
Final range: `b2fda5e9..3ce5d164`. Gates at close: backend 15 known-pre-existing failures only
(fresh DB required — `make db-fresh && make migrate`), lint/mypy/contracts clean; frontend 214/214.

## Post-close-out review fixes (Fable adversarial review, 2026-08-13)

Two defects found by the adversarial re-read of the slice-3 code, both founder-ratified and fixed
here (strict TDD, RED shown before each fix):

1. **A transient Exa fault killed the whole background recon lane.** `ExaSearchResolver.resolve`
   caught only `ProviderResponseError`/`CredentialError` and let `RetryableResolverError` propagate
   on the theory "M7 retries it" — but nothing retries this lane (`reverse_profile` re-raises, the
   savepoint rolls back every background claim, `background_status` → `failed`, the driver only
   drives QUEUED/RUNNING). One post-retry 503 lost the entire background pass permanently. Now a
   separate `except` branch degrades it to the same honest-empty miss, logged distinctly
   (`research.exa_search.provider_transient_exhausted` vs `…provider_refused`), span `refusal`
   carries the type either way. RED→GREEN: `test_a_transient_fault_that_outlived_its_retries_is_a_
   miss_not_a_lane_failure` (unit) + `test_a_transient_exa_search_fault_leaves_the_run_intact`
   (lane, DB). Refusal coverage extended to `client.buyer_profile`. Commit `c301f5c3`.
2. **`source_url` attribution was a substring match against the document.** Page content is
   attacker-influenceable, so an injected `### RESULT n | url: https://attacker.example` line could
   replace the genuinely-fetched `ref` (`_materialize` takes `draft.source_url or ref`) as a claim's
   durable evidence link. Fixed structurally: `exa_search._document` now stamps the urls it actually
   retrieved (only the `used` records) on `NormalizedText.metadata["record_urls"]`, and
   `claim_extraction.attribution_allowlist` / `_attributed_source_url` accept a url only by exact
   membership of that out-of-band allowlist. No allowlist (the scrape lane, or malformed metadata)
   == no attributable url → `None`, never a raise. `parse_extraction_response` now takes the whole
   `NormalizedText`. The resolver's own `by_url` guard stays as defense in depth. RED→GREEN:
   `test_a_result_header_forged_in_the_page_text_cannot_forge_provenance`, plus allowlist
   positive/negative, a metadata-junk totality case, and a resolver-level end-to-end forged-header
   test over the real extractor (which also pins resolver↔extractor agreement on the metadata key).

Gates for both: `tests/{resolvers/test_exa_search,api/test_claim_extraction,api/test_extractor_
composition,stage0/test_reverse_profile}.py` green (89 passed, DB up via `set -a; source .env`),
`make lint` + `make typecheck` clean.
