# W2 — Brand Ad Assets substrate (flag-gated), 2026-08-26

Spec: `subsystems/clue-design/docs/brand-ad-assets-v1-spec.md` §4, §5 W2.
Base attested at `66b608686` (the W1 close-out). Local commits only; nothing pushed.

## Flag

`LUMEN_BRAND_AD_ASSETS` (`settings.lumen_brand_ad_assets`), default **off**. Named without an
`_ENABLED` suffix to match every other switch in `py_lumen_config` (`lumen_ingestion_describe`,
`lumen_agent_fast_loop`, …).

Flag off is zero behaviour change, and stronger than a 403: the two lane routes are **not
registered at all**, so their paths 404 like any unknown path and the OpenAPI schema does not
mention them. Nothing else in the app reads the lane's tables, so the new schema is untouched at
runtime. Proven by `test_with_the_flag_off_the_lane_has_no_surface_at_all`.

Credentials: `ADYNTEL_API_KEY` / `ADYNTEL_EMAIL`, environment only, never defaulted to a real
value, never logged. A provider without them raises `AdLibraryCredentialsMissing` at
construction — before a request body exists, because a page costs a vendor credit.

## Where things live

| Piece | Path |
|---|---|
| Provider seam + typed page/ad | `subsystems/clue-design/apps/api/lumen_ingestion/ad_library/provider.py` |
| Adyntel provider (the ONLY module that names the vendor) | `…/ad_library/adyntel.py` |
| Pagination, filter/dedupe, custody | `…/ad_library/harvest.py` |
| Ad-DNA distillation (vision pass) | `…/ad_library/distill.py` |
| Pre-generation (per visual system) | `…/ad_library/pregenerate.py` |
| The onboarding job | `…/ad_library/onboarding.py` |
| Sync store facade | `…/ad_library/store.py` |
| Governed tools | `…/lumen_api/toolbelt/ad_assets.py` (+ `IngestAdAssetsTool` in `toolbelt/ingestion.py`) |
| DAL | `subsystems/design/clue_design/ad_assets.py` |
| Migration | `alembic/versions/50ce19bf5ef7_brand_ad_assets_lane_w2.py` |
| Routes | `lumen_api/main.py` (`POST /brand-ad-assets/onboard`, `GET /brand-ad-assets/{brand_kit_id}`) |

## Schema decisions (and the pattern each follows)

Design tables live in the ROOT alembic chain (verified: `design_brand_kit`, `design_asset`,
`design_ingestion_job` are all there). `subsystems/clue-design/apps/api` has no migration system
of its own — the SQLite substrate was deleted at Part II D2.5B.

* `design_ad_creative` — follows `design_asset`: registry row, never bytes. PK
  `(creative_id, workspace_id)` because `creative_id` is content-derived from the creative URL
  (workspace-local ids, migration `cf4f80537c8e`'s ruling).
* `design_ad_dna_card` — follows `design_brand_kit`'s versioning, one step stronger: UPDATE and
  DELETE are refused by trigger (the `design_web_publish_revision` pattern). PK
  `(card_id, version, workspace_id)`.
* `design_ad_pregenerated_asset` — a link table, PK `(card_id, card_version, asset_id,
  workspace_id)`, cascading from the card version.
* `design_ingestion_kind` gains `ad_assets` — the lane's job rides `design_ingestion_job` rather
  than a private job table, inheriting fleet dispatch, the lease/generation fence, stage
  reporting and the stranded-work reaper. Enum change is rename-and-recreate in BOTH directions
  (`ALTER TYPE … ADD VALUE` has no inverse). Parity test asserts label ORDER lock-step, so the
  member is appended in `clue_design.enums` too.

Two findings worth keeping:

1. **asyncpg will not bind a string to a `timestamptz` parameter**, even through a SQL-level
   `CAST(:p AS timestamptz)` — it fails at encode time, before Postgres sees the cast. The DAL
   coerces with `_as_datetime` (naive → UTC).
2. **`ON DELETE SET NULL` cannot fire on an append-only table** — it is an UPDATE, and the card's
   trigger refuses UPDATEs. Both `harvest_job_id` columns are therefore recorded references with
   no FK: the job is execution-plane bookkeeping, the creatives and the card are durable brand
   knowledge, and a future job pruner must not delete a brand's references.
3. **`ingestion_job_dto` deliberately omits `evidence`** (and `request`). The lane's per-step
   outcome record therefore is NOT readable over `GET /brand-kits/ingest/{job_id}`; it lives on
   the row. That contract predates this lane and was left alone — the tests read the row. If an
   operator surface ever needs the harvest report, that is a deliberate DTO decision to make,
   not an oversight to patch.
4. **A default argument is not a seam.** `custody_creatives(fetch=download_creative_bytes)` bound
   the real fetcher at import time, so monkeypatching the module attribute did nothing and the
   suite was quietly fetching real LinkedIn CDN bytes. Fixed by resolving at call time AND by
   threading an explicit `fetch_creative` seam through the job; an autouse fixture now refuses
   `httpx.get/post/request/stream` in that suite so a missed stub fails loudly.

## Kit assets vs library assets — LIBRARY, decided

W1.1 landed `scene_turn_asset_library_manifest` and its docstring says outright that its recency
ordering exists for "the assets a scene turn wants … the ones the onboarding harvest /
pre-generation lane just wrote". So the channel the spec's §4.3 was worried about is already
open. Library assets also mean no brand-kit republication (which would mint an unreviewed kit
version and collide with the approval surface — D5 forbids new gates) and reuse of two already
governed tools: `design_register_captured_assets` for harvested creatives,
`design_register_generated_asset` for pre-generated imagery.

## Governance (D6)

Three genuinely-new writes → three new governed tools on a new `AdAssetsStore` facade, plus
`design_ingest_ad_assets` for the enqueue. Listed in the design-side no-bypass guard.

**C6 authority: all four granted to NO role.** The lane is driven by an onboarding job whose
worker invokes them directly (`actor="agent"`), and no model surface plans a harvest, distils a
card or decides to spend N image generations — the same shape `synthesize_entity_prose` and
`synthesize_value_narrative` already have. This also leaves the reviewed design profile
untouched; granting them is a profile version bump and therefore a founder decision.
`tests/agents/test_tool_authority_audit.py` now states the carve-out explicitly instead of
asserting a blanket "every `design_*` tool is DESIGN-granted".

## Step durability

Harvest + custody + creative rows land BEFORE distillation runs; the card lands before
pre-generation. A failed distill or pre-generate completes the job with a recorded reason and
loses nothing above it. Pre-generation consults the generation ledger before spending, so a
reaper re-offer re-uses the earlier attempt's assets instead of re-paying (every generated image
has different bytes, so byte-level dedup cannot save a retry — only the ledger key can).

## Running the suite against a shared development database

Two gotchas cost real time; both are properties of the shared dev DB, not of the code.

* **`fleet_task` is shared by every workspace and every past run.** A failed run leaves queued
  `ad_assets` tasks behind, and the NEXT test's embedded fleet worker — which lives only as long
  as one test — claims one of those orphans and spends its whole life on it while the current
  test's job waits in the queue and times out at 60s. Symptom: `status: 'queued', stage: None`
  with no `design_job.started` for your job id. Clear orphaned `ad_assets` jobs AND their
  `fleet_task` rows before re-running, or use a throwaway database.
* **`design_brand_kit`'s primary key is `(brand_kit_id, version)` — GLOBAL, not per-workspace.**
  Every suite that compiles the `valid_insight_health.styles` fixture races every other suite for
  one row. This lane's tests publish their kit under a per-test id instead.

## Residuals / open questions

* **W4 is not done here and the lane is not consumed yet.** Nothing pushes the card into a turn's
  frame payload or auto-attaches references — that is W4, and the `GET /brand-ad-assets/{kit}`
  read is the seam it will use.
* **The distillation prompt has not had a founder review.** D6 governs *skill* content, and this
  is a system prompt inside the job rather than a skill, but it is the same species of substance.
  Worth a look before the flag goes on.
* **`ASSETS_PER_SYSTEM` is 2, not the spec's "2–3".** Three shapes are defined
  (`16:9` / `1:1` / `4:5`); raising the constant is the only change needed.
* **Competitor ads (D2) are not built** — the request model has no competitor field at all, by
  design, and the opt-in is future work.
* Pre-existing, unrelated: `tests/api/test_toolbelt_wiring.py::test_out_of_order_matrix` fails at
  the base commit too (a `draft_account_research_directive` body-validation drift).
