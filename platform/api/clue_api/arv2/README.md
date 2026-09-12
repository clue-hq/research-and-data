# `clue_api.arv2` — the ARV2 research lane

Master plan §9 Track R. Two rules bind every module here: it **imports nothing quarantined**
(Global Constraint 7, enforced by `tests/arv2/test_import_guard.py`), and **every provider call
goes through `ProviderCaller`** — no module opens a socket of its own.

## Step 0 — the shared foundation (this task)

| Module | What it owns |
|---|---|
| `errors.py` | The lane's typed failures: `Arv2Error`, `ProviderHalted`, `ProviderTransportError`, `RawParseError`. |
| `transport.py` | The HTTP boundary — `HttpRequest` / `HttpResponse`, `HttpxTransport` (live), `ScriptedTransport` (the lane's one test double), `json_request`, `BROWSER_USER_AGENT`. |
| `sinks.py` | Where a call's evidence goes — header/URL redaction, `RawRecord` + `RawSink` (`FileRawSink`, `MemoryRawSink`), `LedgerRow` + `LedgerSink` (`JsonlLedger`, `MemoryLedger`), `SpendTotals`. |
| `calls.py` | **The wrapper.** `ProviderCaller.call` implements Appendix A laws 1 and 2 once: estimate row before the wire, raw record before any parse, `Retry-After` / `12·(n+1)` s / `2·(n+1)` s backoffs, halt latching, the result row. |
| `text.py` | Verbatim-matching primitives (`normalize_for_match`, `substring_verdict`) shared by the media and structuring clients — Appendix A law 6. |
| `openrouter.py` | The thin OpenRouter HTTP helpers both LLM clients share: request builders, the cost reader, the message-text reader. No SDK. |

## The six provider clients (Tasks 2–7)

| Module | Provider |
|---|---|
| `ai_ark_client.py` | AI Ark — company and people enrichment, paced by `arv2_ai_ark_min_gap_s`, credit-metered. |
| `exa_client.py` | Exa — search, contents and deep research; cost from `costDollars.total`. |
| `ats_client.py` | The ATS job boards (Ashby and kin) — open requisitions, read from the careers page's own slug, never guessed. |
| `media_feeds_client.py` | Podcast RSS and YouTube discovery — resolving an episode or video to a fetchable media URL and its duration. |
| `gemini_media_client.py` | Native Gemini media understanding and transcription — the one ARV2 call that bypasses OpenRouter. |
| `structuring_client.py` | The OpenRouter structuring pass: prose → claims against the field catalog, one subject per call. |
| `exa_client.py::ExaClient.agent_run` | Exa Agent (`/agent/runs`) — async deep research: create, poll every 4 s, settle on the completed body; fixed-effort prices reserved on the create leg; failures/timeouts returned, never raised. |

## Where the output goes

Raw records and the ledger are written under `Settings.arv2_raw_root` (default `.artifacts/arv2`,
git-ignored): raw records in `.artifacts/arv2/raw/<provider>/`, the ledger in
`.artifacts/arv2/ledger.jsonl`. Nothing under `.artifacts/` is ever committed.

The `provider_call_ledger` table and the `artifact`-backed raw sink land with D1/A7; R1 ships the
sinks' protocols and the file/memory implementations.

## Cost per request

**Every value a client method returns carries `cost: CallCost` for the request that produced it.**
Cost tracking is not a per-client courtesy; it is a uniform provision, so no caller ever has to
ask "did this one report its cost?".

`CallCost` (`calls.py`) is the settled money view of one request: `cost_usd`, `credits` and
`media_seconds` **as the ledger holds them** (the estimate has already stood in for anything the
provider did not report), plus `cost_source`, `provider`, `operation`, `raw_ref` and
`ledger_row_id`. `cost.ledger_row_id` is that request's `result`-phase ledger row — the join back
to the full trail. `ProviderCaller.totals()` is the running sum across every call one caller made.

`cost_source` labels how well the numbers are known, and it is written on **every** result row's
`extras["cost_source"]` as well as onto the `CallCost`:

| value | meaning | where it appears |
|---|---|---|
| `metered` | the provider's own metering answered — the cost reader supplied at least one number | every paid call: AI Ark, Exa, OpenRouter, native Gemini `generateContent` |
| `free` | nothing was ever going to be charged — the spec declared no cost reader **and** reserved nothing | the public sources: ATS boards, careers pages, RSS feeds, YouTube watch pages, enclosure `GET`/`HEAD`, the Files API upload/poll legs |
| `estimate` | a cost reader existed but reported nothing, so the pre-spend estimate stands in | the fallback only — this is the one value that means *we do not actually know* |

The `free`/`estimate` split is the point of the change: before it, a free ATS fetch and a paid call
whose provider went silent were both unlabelled, so "what did this account really cost" could not
be answered without knowing which providers meter. The test is on the **spec**, not on the amounts
— a metered call that happened to cost zero is still `metered`.

A `cost` field typed `CallCost | None` means the value can also be built **without a call**, and
`None` says so honestly rather than fabricating a ledger reference:

- pure mappers and parsers — `company_from_record`, `email_export_from_record`, `parse_feed`,
  `parse_structured_transcript`, `read_structured_reply`;
- `YouTubeWords.cost`, because the page text comes from a caller-supplied `PageTextFetcher`: only
  the caller knows what its own provider charged, so `youtube_words` takes `cost` as a kwarg and
  passes it through;
- `EmbeddedTranscript.cost`, in the one case where a transcript has no lines to chunk and **no
  call is made at all**.

Calls that return a *set* carry the cost on the set, never on each member — one request bought the
whole page, so charging it per item would multiply the run's real spend. That is why
`people_by_name` returns `AiArkPeople`, `mine_quotes` returns `MinedQuotes` and `embed_chunks`
returns `EmbeddedTranscript`; all three iterate and `len()` like the lists they replaced.
`Transcript.upload_costs` keeps the long path's free Files API legs as their own rows rather than
summing them into `Transcript.cost`, because three or four requests were made and the ledger has
three or four rows.

The D1/A7 `provider_call_ledger` table receives exactly these rows — `cost_source` included — when
the database `LedgerSink` lands; nothing above the sink protocol changes then.

## Onboarding templates and mappers (O2)

`onboarding_requests.py` holds the fixed request templates of ARV2-ONBOARDING-PLAN.md §4 —
company overview (contract-verbatim, live-validated), customer reviews, per-product research
(Agent requests) and persona evidence (a `/search` deep-reasoning request within the depth-2 /
ten-property limits). Behaviour is in the system prompt, shape in the schema; the driver never
authors a schema.

`onboarding_documents.py` turns a response into a `KnowledgeDocument` (YAML front matter = the
machine contract; markdown body under fixed headings; `not_found` always rendered). The mappers
are pure, so `KnowledgeDocument.cost` is the settling call's `CallCost` when built from a call and
`None` otherwise — the guard's documented exception.

The Agent surface is synchronous like the rest of R1: the onboarding driver (O3) calls
`agent_run` through `asyncio.to_thread`, one `ProviderCaller` per worker task.

## The onboarding run driver (O3)

`onboarding_driver.py` is one fleet work handler (`FleetTaskKind.ONBOARDING_RUN`) that runs one
`onboarding_run` end to end: the fast recon lane (overview ∥ lineup ∥ reviews) in parallel, then
the catalog sync, then the synthesis turns — through the `SynthesisLauncher` seam O4 fills: one ICP
turn, then one persona turn per ICP it registered — running alongside the per-product background
fan-out, personas and products sharing the one cap (`onboarding_max_parallel_runs`).

Three rules it exists to keep:

- **Every provider call goes through `asyncio.to_thread`, one `ProviderCaller` per step.** R1's
  caller is synchronous and its Agent poll loop blocks; a step's raw records and ledger live under
  `arv2_raw_root/onboarding/<run_id>/<step_label>/`, so "what did this step cost" needs no
  de-interleaving.
- **The failure law.** A provider failure, timeout or empty answer is a *step outcome*, never an
  exception: the step lands `failed`/`empty` with its reason, its document is closed without a
  body, and the run keeps going. Everything else is contained inside `handle`, which fails the run
  row rather than letting the fleet strand it on `running`.
- **The driver holds at most one connection at a time.** Its row writes are small ordered facts
  about one run and the parallelism that matters is off the loop entirely, so they are serialized
  behind one lock — which also lets a caller inject a single-connection factory.

The lineup step runs the *same* question twice (own domain, then the open web) and appends the
open web's new names to the own-domain answer. Only the own-domain pass's `grounding` survives the
merge, and the merge is shaped around that: grounding field paths are indexed (`products[i]`) and
the catalog mapper attaches citations by index, so **every own-domain entry keeps its original
position and none is ever collapsed** — not even a pair that normalizes to the same name, because
dropping one would shift every later own entry left and hand it the wrong citations. (The catalog
synchronizer resolves a same-named pair honestly, as `alias_reused`.) An open-web entry is
appended only when its normalized name is new, always after every own index, so **open-web-only
entries reach the catalog with no per-entry sources** — honest, where a wrong citation would not
be.

Two things keep a re-run from re-minting products it already has. The synchronizer's comparison key
(`normalize_identity`) strips the `™®©℠` marks *before* NFKC (which would otherwise turn `™` into
the letters `tm`), folds case, and keeps every word — no stoplist, because a one-company heuristic
would silently merge distinct products elsewhere (founder ruling 2026-09-08). And on a re-run the
lineup *query* — never the system prompt or the schema, which the catalog contract fixes — names
the brand's products already on file through the `known_products` seam, so the model reuses an
existing spelling instead of inventing a near-miss of it.

### The catalog identity ladder

Four live re-runs on one workspace grew its product rows from 19 to 28, so `synchronize_catalog`
resolves each lineup entry down four rungs and stops at the first that answers: the lineage row
already written for this `(document, ordinal)`; a prior lineage row binding the same entry
fingerprint (`lineage_reused`, replaying whichever rung made that binding — a model one included);
the entry's spelling key against the names *and aliases* on file (one hit `alias_reused`, several
`unresolved_ambiguous`); then **one batched model call per run** over everything left over
(`onboarding_reconcile.py`), shown each entry's `official_url` and description as evidence.

Only `high`-confidence model matches merge (`model_reused`); anything less mints a row and records
it `model_unsure` with the model's confidence and reason, for the human gate — a duplicate is
recoverable, a wrong merge silently retargets a campaign. Every rung-3/rung-4 match writes the
*observed* spelling back as an alias, so the next run resolves deterministically what this one had
to reason about. That is also why `LINEUP_SYSTEM_PROMPT` asks Exa for the page each offering is
presented on and for that page's own spelling of the name, and to omit `official_url` rather than
cite the homepage: a homepage on every entry is evidence that reads as "all one offering".

The model stage is composed as a **factory of one reconciler per run** —
`fleet_main._build_catalog_reconciler_factory`, behind `CLUE_ONBOARDING_CATALOG_RECONCILE_ENABLED`
with `CLUE_ONBOARDING_RECONCILE_MODEL` — because the call spends through a `ProviderCaller` writing
under that run's own `arv2_raw_root/onboarding/<run_id>/catalog-reconcile/` folder. Unlike the Exa
key, a missing `CLUE_OPENROUTER_API_KEY` does **not** cost the lane its handler: the run composes
without a factory, logs `onboarding.reconciler_not_composed` once, and the ladder stops after its
deterministic rungs — what it did before the stage existed.

### The step graph

One `onboarding_run` task is one run, in this order:

```
  mark_run_running          overview ────────────────┐   synthesis ─→ persona ×ICPs ──┐
  + bind the client  ─→     lineup ─→ catalog_sync ──┼─→                              ├─→ finish_run
                            reviews ─────────────────┘   product_research ×N ─────────┘
                                    (fast lane, concurrent)      (background, capped)
```

Every step the run can open:

| kind | phase | subject_ref | how many |
|---|---|---|---|
| `overview` | `fast` | — | one |
| `lineup` | `fast` | — | one |
| `catalog_sync` | `fast` | — | one (only if the lineup found products) |
| `reviews` | `fast` or `background` | — | one (`CLUE_ONBOARDING_REVIEWS_PHASE` moves it) |
| `synthesis` | `fast` | — | one — the ICP turn |
| `persona` | `background` | the ICP key | one per registered ICP |
| `product_research` | `background` | the product id | one per synchronized product |

The fast lane runs its steps concurrently; the lineup's two passes are merged and handed straight
to `catalog_sync` inside the same step branch, which mints or reuses the product rows over the
artifact-keyed `onboarding_product_lineage`. The ICP turn reads what the fast lane published and
does not wait for the per-product reports, so it runs *alongside* the background fan-out. Its
persona turns are opened the moment it returns — never after the product reports finish — and they
queue on the same `onboarding_max_parallel_runs` semaphore as those reports, so the cap counts both
fan-outs together. An ICP turn that ends anything but `completed` hands over no profiles, so no
persona step is opened at all. `finish_run` settles the run `completed` or `completed_with_gaps`
from the steps' own statuses and sums their cost — a run with a failed or empty step still
finishes, it just says so.

Both launcher calls are wrapped in `asyncio.wait_for(..., SYNTHESIS_TURN_HARD_TIMEOUT_S)` (1800 s).
That is containment, not an agent cap — the profile has its own 1200 s turn timeout — because a
governed tool call refused under the recipe gate can leave `RecipeExecutor.execute` spinning
forever, and a launcher call that never returns would strand the run on `running`. A trip lands
that one step `failed` with `turn_hung`; every other step and the run itself keep going.

`CLUE_ONBOARDING_REVIEWS_PHASE` moves the reviews step between the fast lane and the background
lane without changing anything else; every other flag in the lane (`_OVERVIEW_EFFORT`,
`_REVIEWS_EFFORT`, `_PRODUCT_EFFORT`, `_PERSONA_EVIDENCE_ENABLED`) is read at the step that spends.

### The two injected seams

Neither seam may live inside this package, and both are optional so the lane composes without
them:

- **`ClientEntityBinder`** — production implementation `clue_api.onboarding_client_binding
  .Stage0ClientEntityBinder`, **outside** `arv2/` because it imports `clue_research.stage0`, which
  the import guard (`tests/arv2/test_import_guard.py`) forbids in the lane. It reuses Stage-0's
  *client-entity resolution only*: an existing `workspace_client_binding` wins outright, otherwise
  `prepare_client_kb_run` resolves/mints the entity and binds it, and the run's
  `client_entity_id` is stamped write-once. **It reads and writes no Client-KB version, no
  readiness decision and no Stage-0 run pin** — the standing rule that no old-lane gate may block
  this lane (`_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`). Composed without a
  binder the run still produces every document: they are brand-scoped and need no client entity.
- **`SynthesisLauncher`** — O4's `build_onboarding_synthesis_launcher`, supplied at the merge, with
  two calls: `launch_icps` (the ICP turn, which returns the `IcpRef`s it registered) and
  `launch_persona` (one per ICP). The driver keeps its own `IcpRef`/`IcpSynthesisOutcome` rather
  than importing O4's types — the lane may not import the synthesis wiring — so `fleet_main
  ._SynthesisSeam` copies the four fields across in both directions. Composed `synthesis=None`, the
  `synthesis` step settles `empty` with "synthesis agent not composed (O4)" rather than pretending
  it ran, and no persona step is opened.

### Composition on the fleet

`clue_api.fleet_main._build_onboarding_handler` builds the handler behind
`CLUE_ONBOARDING_V2_ENABLED` and passes it to `build_multi_work_worker(onboarding_handler=…)`; the
route (`clue_api.onboarding_routes`, mounted in `projections_app` behind the same flag) is what
enqueues the task. Ruling: **the flag on with no `CLUE_EXA_API_KEY` composes NO handler** — a loud
`onboarding.handler_not_composed` warning naming the variable, and the enqueued runs wait in the
queue for a correctly-credentialed worker. Refusing the boot would take every other kind of work
on the process down with it; a keyless handler would fail each run at its first provider call.

### Where the evidence lands, and what replaces it

A step's raw records and ledger are files today —
`arv2_raw_root/onboarding/<run_id>/<step_label>/raw/` and `…/ledger.jsonl`. When D1's
`provider_call_ledger` table gets its database `LedgerSink` (and the `artifact`-backed raw sink),
`build_onboarding_provider_caller` swaps the two sinks at composition and nothing above the sink
protocol changes. The documents themselves are already durable: each is persisted through the
artifact store and published as a `brand_knowledge_document` row.

## D1 — the display substrate, the lenient writer, the answer-key loader

D1 is the step that gives the lane a place to put things. It lands as one Alembic revision plus
four modules here.

**The migration** (`65fb2128c904`) adds, in one reversible revision: three `claim` columns —
`signal_priority smallint NOT NULL DEFAULT 3` (1 active buying intent, 2 qualifying fact, 3
context), `outreach_safe boolean NOT NULL DEFAULT true` (appropriateness, not accuracy) and
`write_markers jsonb NULL` (the write-time annotations); the two `account_entity` owner columns
(`owner_user_id`, `created_by_user_id`); `workspace_field_definition.presentation`
(`text|badge|score`); and the four new tables `display_block`, `display_section_recipe`,
`provider_call_ledger` and `account_activity_event`. It also carries the persona vocabulary
data-fix: `Persona` is not a Postgres enum but an `enum` list inside three registered value
schemas, so adding `user` means rewriting those `field_definition.value_schema` rows or a
re-loaded pack raises `FieldRedefinitionError`. Two shapes worth knowing: the three new `claim`
columns are deliberately **outside** the append-only immutable-column guard (they are governance
annotations whose change is a display-invalidation event, not provenance), and
`display_section_recipe`'s system row is keyed by an **empty-string** `workspace_id`, not NULL — a
NULL cannot sit in a primary key.

**The five flags** (all in `.env.example`, all `Settings` fields):
`CLUE_CLAIM_WRITE_LENIENT=true` · `CLUE_EVIDENCE_VERBATIM_CHECK=off` ·
`CLUE_UNEVIDENCED_ROW_PURGE_ENABLED=false` · `CLUE_INTERVIEW_ENTAILMENT_CHECK=off` ·
`CLUE_SENSITIVITY_FLOOR_ENABLED=true`. When a check is on it records a marker on the claim; it
never refuses a write.

**`catalog_seed.py`** holds `ARV2_PACK` — 38 registered field rows (35 answer-key keys plus the
three keys the section recipes need), each a `SeedField` with its value schema, field class and
reuse scope. They are data, not code: no pipeline is forked to add a field. `ARV2_FIELD_KEYS` is
the key set, `load_arv2_pack(conn)` is the loader. **`clue_api/arv2_wiring.py`** —
deliberately outside this package, because the lane may not import `clue_api` modules outside
itself — appends that loader to `clue_api.composition.RESEARCH_PACK_LOADERS`; the fleet and
projections entrypoints call `register_arv2_wiring()` unconditionally, since packs load under
either flag.

**`claim_writer.py`** is the lenient write gate (master plan §2 principle 2). `ClaimDraft` is what
a writer knows; `LenientClaimWriter.write` fills in everything it did not say and returns a
`WriteReceipt`. It **stamps**: `source_tier` from `extraction_method` via `TIER_FOR_METHOD` (tier 4
⟺ `llm_synthesis`, never chosen by the caller), `reuse_scope=tenant_private` with the workspace id,
and — for a `contact.facet.*` claim — `identity_binding=WEAK` + `use_class=professional-public`
when the draft is silent. It **marks** rather than refuses: a value that fails its registered
schema is stored with `schema_valid=false`; an unregistered key is registered as a proposed field
and marked `proposed_field`; an `api`/`scrape`/`llm_synthesis` claim with no `source_url` is stored
and marked `source_missing`; a defaulted governance value is marked
`identity_binding_defaulted` / `use_class_defaulted`. Every marker lands in `claim.write_markers`.
Constructed with `lenient=False` the same writer restores the store's strict refusals — the
leniency is a flag, not a fork. The URL rule itself moved from construction to promotion in D1:
`clue_core.Claim` now admits a URL-less research claim and `can_be_promoted` refuses it, so such a
row exists honestly and is never served as verified truth.

**The answer key.** `answer_key.py` is pure mapping — it turns the two proof-of-concept JSON files
(the Zafran one-account run, 174 rows; the ten-person depth run, 119 rows) into `ClaimDraft`s and a
manifest, with no database in sight: the persona map (`executive_sponsor` → `economic_buyer`,
`adjacent_buyer` → `user`), the priority table, the source-bundle map, the media wrap and the
pipe-joined-key split all live there, and `ANSWER_KEY_NAMESPACE` is the uuid5 namespace every
deterministic id in the load hangs off. `answer_key_loader.py` writes them: workspace → brand →
product → project, the pack loaders, four account entities and twelve contacts, the project run
(no Stage-0 pins), two `run_lineage` rows, three transcript artifacts, every draft through
`LenientClaimWriter`, then the ARV2 research run and job and the activity feed.
`scripts/load_arv2_answer_key.py` is the thin argparse wrapper:

```
uv run python scripts/load_arv2_answer_key.py \
    --database-url postgresql+asyncpg://clue:clue@localhost:55060/clue
```

(`--dry-run` runs the whole load in one transaction, prints the report and rolls back;
`--context-root` defaults to `.context`, `--storage-root` to `.artifacts/answer-key`.
`--repair-emails` loads nothing: it supersedes the already-loaded `core.work_email` claims that
still hold a bare address string with the `{address, status, checked_at}` value D4-b's registry
declares, taking the verdict from the answer key's own AI Ark `verification` block, and is
idempotent — a second pass finds no bare strings. `--repair-research-rows` loads nothing either: it
writes the `arv2_research_run` + `arv2_research_job` pair a fresh load now writes, for a database
loaded back when D1 wrote the old lane's terminal rows instead.) **The load is one-shot per database**: it is keyed on a deterministic run id, and a second run raises
`AlreadyLoaded` rather than duplicating rows. A database that already carries it must be reset, not
re-loaded.

**Three constraints this places on R2 and R3:**

- **R2's `write_claims` goes through `LenientClaimWriter`.** The structuring pass does not build
  `Claim` objects of its own and does not call `insert_claim` directly; the gate is the lane's only
  write path, so the stamping and the markers are uniform whatever produced the fact.
- **The loader writes ARV2 rows, and only ARV2 rows.** Founder ruling 2026-09-09: *ARV2's own
  rows are the only truth; nothing about the old research lane matters.* So the answer key ends in
  one `arv2_research_run` and one `arv2_research_job` for Zafran — created, begun and finished
  through `account_research_store` exactly as R2's driver does it, pinned to the project's brand
  and project run, to a stand-in ICP artifact the loader stores (`icp_key = answer-key-standin`:
  the 2026-09-02 run predates the ICP gate, so there is no confirmed document it was launched
  against), to the `arv2-account/v1` profile ref and sha, and finalized `completed` with
  `{"claims_written": …, "source": "answer-key"}`. The other three accounts get **no** job: "never
  researched" is a fact about a missing row, and `arv2_research_status_for` reads it that way. The
  legacy `entity_research_run` / `entity_research_job` / `entity_research_account_coverage` /
  `entity_research_account_fleet` writes D1 shipped are **deleted** — nothing reads those tables on
  the ARV2 path (`tests/api/test_frontend_read_arv2_only_guard.py` now passes with no allowlist),
  and the Phase-6 PR drops them. A database loaded before this change keeps its dead legacy rows
  and gains the ARV2 pair through `scripts/load_arv2_answer_key.py --repair-research-rows`, which
  is idempotent on the deterministic run and job ids.
- **R3's person mapper writes `core.work_email` as the verdict object, never a bare address.** The
  registered value is `{"address", "status", "checked_at"?}` with `status` in
  `verified_smtp | catch_all_valid | invalid | unknown | unverified` (D4-b decision 6): the address
  with the provider grading that makes it usable, which is exactly the pair `AiArkEmailExport`
  keeps whole. The email chip serves an address only for the first two verdicts, so an R3 person
  claim that flattens the address away from its verdict reads as *look this up* on every screen.
  `answer_key.work_email_value(address, verification)` is the one mapping — the AI Ark
  `verification` block in, the claim value out — and it is what R3's own AI Ark email export should
  call rather than re-deriving the grading.

## D2 — the display module (`clue_api/arv2/display/`)

Master plan §7 and `docs/specs/ARV2-DATA-SOURCE-MAP.md` §4. D1 gave the lane a place to put
claims; D2 turns those claims into the three pages a marketer reads — **account overview**,
**insights** and a **contact page** — one Luna call per section, every sentence carrying the claim
ids it used. It adds **no migration**: `display_block` and `display_section_recipe` are D1 tables.

### The module map

| Module | Owner | What it owns |
|---|---|---|
| `recipes.py` | **S4 content (Shashank)** | `SectionRecipe`, the 17 `SYSTEM_RECIPES` (which field keys feed which section of which page), `RECIPE_VERSION`, `RESTRICTED_SECTION_KEYS`, `recipes_for`, the `load_display_recipes` upsert seeder and the `read_recipes` reader (system row overridden by a same-`(page, section_key)` workspace row). |
| `prompts.py` | **S4 content (Shashank)** | `PROMPT_VERSION`, `SYSTEM_PROMPT`, the 17 `SECTION_INSTRUCTIONS`, `build_messages`, `RESPONSE_FORMAT`. The three fixed lines live here: no aliases in prose, dates in words, the personal-hobby hook at most once per page. |
| `render.py` | A4 machinery | `render_value_text` (a claim value as display text, reading `.text` on a media-wrapped value), `DisplayClaim`, `alias_table` (the `c1…cN` payload + the alias→uuid map), `dedupe_near_duplicates`. |
| `gather.py` | A4 machinery | `resolve_subject`, `client_context`, `committee_members`, and `gather_section_inputs` — the filter that reads the subject's live claims **once** and hands each section exactly the rows its recipe allows. |
| `runner.py` | A4 machinery | `LunaSectionRunner` (one section = one `ProviderCaller` call, retried once on an unusable reply), the tolerant reply models, and the pure `materialise` that turns a reply into the wire shape and counts everything it removed. |
| `floor.py` | A4 machinery | The one hard rule: `check_floor` / `forbidden_aliases_for` / `apply_floor`, plus the flag-gated `verbatim_annotations`. |
| `blocks.py` | A4 machinery | `block_body`, `live_blocks`, `insert_block`, `supersede_blocks`, the recipe-scoped `stale_sections`, `compose_display_block`, `insight_summary`. |
| `evidence.py` | A4 machinery | `EvidenceRef`, `resolve_evidence`, `evidence_for_ids`, `source_domain`, `favicon_url` — the source drawer, pure and network-free. |
| `page.py` | A4 machinery | `ensure_page` (decide, write concurrently, persist sequentially), `default_runner_factory`, `record_page_written`, `PageResult`. |

`scripts/generate_arv2_display.py` is the operator command; `tests/arv2/display/` is the suite.

### The decisions (the plan's twelve, condensed)

1. **Display reads live claims, not the merge.** `current_values` collapses `(entity, field)` to one
   winner; a page shows *everything the research found*. Eligibility mirrors the merge posture
   without the cardinality collapse (verification on ⇒ unverified tier-4 excluded).
2. **Short aliases in the prompt.** Claims reach the model as `c1…cN` in a stable order; the runner
   maps them back. A uuid never reaches the model, so "ids typed in prose" cannot surface one.
3. **Section keys are contract v1** (kebab-case, fixed) — insights `buying-signals`,
   `money-and-momentum`, `tools-they-already-use`, `how-they-sell`, `contact-insights`,
   `context-only`; overview `what-they-do`, `why-they-fit`, `why-now`, `buying-committee`,
   `how-to-approach`, `watch-outs`; contact `why-this-person`, `problem-right-now`, `openers`,
   `angles`, `do-not-mention`.
4. **Restricted-section input** = every `outreach_safe=false` live claim of the subject (a contact
   page: the contact **and** its account) ∪ the recipe's keys regardless of flag. Non-restricted
   input = the recipe's keys, `outreach_safe=true` only. A `use_class = sensitive` claim enters no
   section at all, fail-closed.
5. **Account pages expand to the committee** — the latest coverage row's `committee_member_ids`,
   else every contact under the account with ≥1 live claim. Each claim payload carries `subject`.
6. **Near-duplicate dedupe is per flag group**, and folds *within* one subject only: two people who
   share a certification both keep their row. A safe/unsafe twin pair is kept as two rows.
7. **Client context is a setting for now** — `CLUE_ARV2_DISPLAY_CLIENT_PITCH` is
   `client.what_we_sell`; `client.name` is the workspace's brand. Track O's company-overview
   artifact replaces the setting when O3 lands.
8. **The evidence resolver is pure** — domain/favicon/title/quote/`researchExcerpt`/dates all from
   the claim's own columns and value. `verificationKind = "record"` iff `extraction_method = api`
   **and** `source_url IS NULL`. No network call.
9. **The block body stores the section plus its checks** — `{intro, items, checks, cited_flags,
   cost_usd, call}`. `cited_flags` is the point: it remembers each cited claim's `outreach_safe`
   *at write time*, which is the only way a later read can see that appropriateness was revoked.
10. **Off-recipe and unknown citations are annotations**, not failures: the id is dropped from
    `claimIds` and counted; an uncited sentence is kept and counted. Only unsafe-outside-restricted
    triggers the regenerate rule.
11. **The regenerate call is the same prompt plus one line** naming the forbidden aliases, sent with
    the *same* section input so the alias table is byte-identical.
12. **Activity** — one `account_activity_event` per *page* write (`kind='summary'`, actor `clue`),
    against the account; a contact page names the person in `ref_json`.

### Rulings taken during D2 execution

- **Near-duplicate containment is token-set containment**, not substring: a terse claim whose every
  token appears in a fuller same-field claim folds into the fuller one, so no fact is lost.
- **Dedupe never folds across two people** — only within one subject.
- **A committee member with a coverage row but no claims is served, not an error.** Research
  finalization is authoritative; the store simply holds no rows for that person yet.
- **`evidence_for_ids` reads live claims only.** A DSAR tombstone is a supersession by a redaction
  row, so serving superseded evidence would re-surface erased personal text. A stale-served block
  whose citation was superseded shows no chip until regeneration — the safe direction.
- **A section whose reply was unusable twice is `failed`, never persisted.** Storing its empty draft
  would turn a transient provider failure into a permanently blank section; leaving it unwritten
  means the next `ensure_page` simply retries it as a missing section.
- **The floor is defence-in-depth.** `gather_section_inputs` already withholds unsafe rows from
  non-restricted sections, so the regenerate path cannot fire through `ensure_page` on real inputs;
  it is proven by a direct unit test over a hand-built unsafe input.
- **Page spend is summed from each runner's `caller.totals()`**, never from `draft.cost` — a
  retried or regenerated section made more than one call, and the money was spent either way.
- **Recipes seed through `RESEARCH_PACK_LOADERS`** (`arv2_wiring.py`), the same composition-root
  seam the field packs use: recipes are registry-like config data.

### Running it

```
uv run python scripts/generate_arv2_display.py \
    --database-url postgresql+asyncpg://clue:clue@localhost:55060/clue \
    --account zafran.io --page all                     # overview + insights

uv run python scripts/generate_arv2_display.py \
    --database-url ... --account zafran.io --contact "Nick Fisher"    # the contact page
```

`--database-url` is required so the command can never fall through to `CLUE_DATABASE_URL`. It
**spends money** — every section it decides is missing is one OpenRouter call — and writes nothing
when every section is already stored. `--force` rewrites a whole page, `--regenerate-stale`
rewrites only the sections a newer claim has moved underneath, `--dry-run` rolls the transaction
back (the calls still happen and are still paid for). Only JSON goes to stdout.

### What D3 wires

- `ensure_page(conn, …)` behind E2 (overview), E3 (insights) and E5 (contact profile).
- `evidence_for_ids(conn, workspace_id=…, claim_ids=…)` behind the shared `ResearchEvidence` read
  (source map §3.9) — the same rows the pages cite.
- `insight_summary(display_block, committee_size)` for the insights header's two-line count.
- **Regeneration runs in the background.** `ensure_page` is synchronous and a first open waits
  ~15 s; master plan §7's policy is to *serve the persisted block and regenerate the stale sections
  behind it*. `stale_sections` and the `regenerate_stale` flag are the seam; the background driver
  is D3's, not D2's.

### Posture caveats

- **Verification is off** in the shipped posture (`CLUE_VERIFICATION_ENABLED=false`), which is what
  the answer key was loaded and displayed under. With it on, two of the five Zafran
  `contact.role_on_committee` rows are unverified tier-4 synthesis and the committee reads three,
  not five — do not assume a five-member committee without checking the flag.
- **The display reads live claims, not the merge**, so a page can show two rows of the same field
  that the merge would have collapsed to one. That is deliberate (decision 1) and is the reason the
  source-map's older `current_values(...)` wording is superseded.
- **Safety is exactly as good as `outreach_safe`.** The floor and the gather filter both key on that
  column; a fact that is mis-flagged safe is displayed safely-by-contract and wrongly-in-fact. The
  fix for a wrong page is a better claim, never a better prompt.

## D3 — where the read surface lives

Master plan §6 and `docs/specs/ARV2-DATA-SOURCE-MAP.md` §1/§3. D3 is **not in this package** and
never will be: the five screens are HTTP read endpoints, so they live with the rest of the
workspace-scoped read surface under `platform/api/clue_api/frontend_read/`. This pointer exists so
a reader who arrives at the lane looking for "the ARV2 screens" is sent one directory over instead
of concluding they were never built.

The five endpoints (all under `/frontend/v1`, all workspace-scoped by `X-Workspace-Id`):

| | Route | Payload |
|---|---|---|
| E1 | `GET /accounts` | `AccountsResponseV1` — the accounts table |
| E2 | `GET /accounts/{id}` | `AccountDetailResponseV1` — the detail/preview, incl. `overviewDisplay` |
| E3 | `GET /accounts/{id}/workspace` | `AccountWorkspaceResponseV1` — `insightsDisplay`, `insightSummary`, `artifacts` |
| E4 | `GET /accounts/{id}/contacts` | `AccountContactsResponseV1` — the committee rows |
| E5 | `GET /accounts/{id}/contacts/{contactId}` | `AccountContactDetailResponseV1` — the contact page, incl. `contactDisplay` |

**One contract (D4-b, 2026-09-09).** `/frontend/v1` serves contract v1 and nothing else. The FI-2
readers, their wire models, their SQL and the modules that existed only for them are deleted; the
`?contract=` selector is gone and a request that still sends one is **ignored**, not 422'd. The v1
readers took the plain names (`list_accounts`, `read_account_detail`, `read_account_contacts`,
`read_contact_profile`). `frontend_read.app` no longer defines `ContractMode` / `contract_mode` /
`ContractDep`. *(Historical: D3 selected v1 per request with `?contract=v1`; without it E1/E2/E4/E5
served FI-2 payloads and `?contract=v2` was an enveloped 422. D4-b removed all of it.)*

The modules, under `frontend_read/`:

| Module | What it owns |
|---|---|
| `contract_v1.py` | The five pydantic payload models and their shared sub-types (`ResearchEvidence`, `ResearchDisplayBlock`, `BuyingCommitteeMember`, `AccountActivity`, …), plus `V1_PAYLOADS` — the mapping the parity suite iterates against the frontend's Zod in `apps/frontend/src/features/accounts/model/`. |
| `v1_shared.py` | Everything two or more endpoints compute: `arv2_display_allowed` (the D3 display predicate), the five label maps, the fit/band/label helpers, `email_facts`, tenure/education/LinkedIn/time labels, owners, custom fields, `last_modified_for`, `activity_for`, and `research_evidence_for`. |
| `display_pages.py` | The one seam onto D2. `DisplayPages.page(...)` composes a page from live blocks, degrades to an empty block rather than raising, and schedules stale-section regeneration in the background (never awaited by the request); `generate=False` is the authorisation-read mode the evidence routes use. It also owns `committee` / `buying_committee` / `rail_contacts` over one claims read. |
| `account_workspace.py` | E3, end to end. |
| `accounts_list.py` / `account_detail.py` / `contacts.py` | The E1 / E2 / E4+E5 readers — one contract, no branch. `accounts_list` also exports the public `read_spine_page` (the chat composer's mention catalog shares the one account scan). |
| `evidence_stream.py` | E7's artifact streaming — the three functions the deleted `evidence.py` still owed it. |
| `project_run_context.py` | `latest_project_run_context` only, for the agent turn wiring over the platform `project_run` table. (What was `committee.py` — its governed-committee reader resolved members through the old lane and returned nobody on ARV2 rows.) |

**The display module is consumed only through its published functions** — `ensure_page`,
`live_blocks`, `compose_display_block`, `stale_sections`, `insight_summary`, `evidence_for_ids`,
`committee_members` (with `resolve_subject`) and `read_recipes`, plus the pure `render_value_text`.
No endpoint reaches into `display_block` rows, prompts, the runner or the floor: if a screen needs
something the display module does not expose, the new function is D2's to add, not D3's to inline.

**D4 (2026-09-09) re-pointed the frontend at `?contract=v1` and changed nothing here.** The
`apps/frontend` accounts feature was re-lifted from the design build and its five repositories read
E1–E5 through the authenticated BFF — E1 walking `meta.nextCursor` at `limit=200` because the table
pages in the browser. No backend behaviour changed at D4.

**D4-b (2026-09-09) made every read ARV2-native and deleted the FI-2 surface.** Seven tasks on
`track-d4b`. What the read surface now does, and the constraints it puts on Track R:

1. **Research status** comes from `arv2_research_job` (`v1_shared.arv2_research_status_for`): the
   account's latest job by `(created_at, job_id)` within the workspace, `status` served verbatim
   (R2's `JobStatus` and the wire's `ResearchStatus` are the same five strings — a test pins the
   vocabularies equal), `refreshing` = a non-terminal job newer than a completed one, `not_started`
   when there is no job. It is **per account, not per project**.
2. **The committee** is `arv2/display/gather.committee_members`: the account's contacts with ≥1 live
   claim under the workspace scope, merged losers excluded, ordered `(persona_rank, name, id)`. No
   coverage row is consulted anywhere. **R3 constraint:** when the committee agent lands it replaces
   this rule *in this one function*, and it must write its own committee rows — it may not resurrect
   `entity_research_account_coverage`.
3. **Persona is display text on the wire** (`persona_display`), including in the `contactRefs[]` the
   display runner writes into `display_block.body_json`. `persona_label` / `persona_rank` /
   `PERSONA_TONES` still read the vocabulary value. **R3 constraint:** write the vocabulary value to
   the claim; the read surface does the labelling.
4. **`core.work_email` is an object** — `{address, status, checked_at?}`, `status` in
   `verified_smtp | catch_all_valid | invalid | unknown | unverified` (migration `7332ac974920`).
   `emailStatus` is `available` only for the first two verdicts; a bare string reads `lookup`.
   **R3 constraint:** the person mapper writes the object, never a bare address, and calls
   `answer_key.work_email_value(address, verification)` rather than re-deriving the grading.
5. **The loader writes ARV2 rows only.** `answer_key_loader` creates one `arv2_research_run` + one
   `arv2_research_job` through `account_research_store` (`create_run` → `create_job` → `begin_job` →
   `finish_job`); its four `entity_research_*` INSERTs are deleted. `--repair-research-rows` and
   `--repair-emails` bring an already-loaded database up to the same state, both idempotent.
6. **The guard.** `tests/api/test_frontend_read_arv2_only_guard.py` greps `clue_api/{arv2,frontend_read}`
   for `entity_research_`, `account_run`, `research_view`, `read_governed_committee`,
   `ContactEligibilityResolver` and bare `display_allowed`. Its **file allowlist is empty**. The one
   substring allowance is `entity_research_job_id`, a real ARV2 column on `provider_call_ledger`
   that holds an `arv2_research_job.job_id`.
7. Still owed, recorded so it is not rediscovered: `AccountContactDetailV1.linkedinUrl` should
   become nullable so the site-root fallback can go, and `POST /frontend/v1/accounts` does not exist
   (the frontend's create is a local non-optimistic draft).

## Notes recorded at R1 integration (2026-09-07)

- **The one native call.** `gemini_media_client.transcribe_long` is the only ARV2 call that bypasses
  OpenRouter (founder ruling): OpenRouter serves neither `gemini-3.5-transcribe` nor a file upload.
  It reads `Secrets.gemini_api_key`, sends it as `x-goog-api-key` (never `?key=`), and its cost is
  computed from `usageMetadata` with the proof-of-concept price sheet. Short items and embeddings go
  through OpenRouter like every other model call.
- **`ffmpeg` is a test-only dependency**: the Gemini live suite cuts a 180 s clip for the short path
  and skips when `ffmpeg` is absent. Production never cuts audio.
- **Two `AudioFile` types exist** — `media_feeds_client.AudioFile` (a downloaded enclosure: path,
  bytes, sha256, duration, content type, the last two optional) and `gemini_media_client.AudioFile`
  (a transcription input: path, duration, mime type, container format, all required). The
  conversion between them ships here as `gemini_media_client.transcription_input_from_enclosure`,
  which **raises** on an unknown duration or an unrecognised content type rather than defaulting:
  a `0`-second reservation would silently disarm the lane's one enforced money control, and an m4a
  labelled `mp3` is a wrong transcript.
- **The package `__init__` exports the value types as well as the client entry points** — R2 needs
  them to annotate anything, and a rule that forces submodule imports is a decorative boundary.
  The one exception is `AudioFile`: the two collide by name, so each is imported from its own
  module.
- **Every client keeps its own typed failures** (`BoardNotFound`, `UnsupportedMediaHost`,
  `MediaCeilingExceeded`, …) subclassing `Arv2Error`; consolidation into `errors.py` is deferred.
- **Halt rules are per provider, but one latch key has exactly one rule.** The wrapper latches on
  the `CallSpec.provider` string, so every spec that latches `openrouter` — the structuring call
  and the media client's short transcription, quote mining and embeddings — shares
  `openrouter.openrouter_halt_rule`. The native Gemini endpoints latch `gemini` and use
  `gemini_media_client.gemini_native_halt_rule`. Exa's ignores 2xx bodies (a successful dossier
  about a fintech names "credit" constantly); AI Ark's checks any 4xx/5xx body.
- **403 is a per-provider decision, not a lane-wide one.** OpenRouter's 403 is a *moderation
  verdict on the input*, so it does **not** halt: one flagged bundle would otherwise latch
  `openrouter` process-wide and take the whole run's model calls down. AI Ark's 403 (Cloudflare
  denial) and Exa's (auth) do halt, because for them it really is a refusal to serve.

## R2 composition constraints

R1 is entirely synchronous and single-threaded by design; these are the conditions R2 must compose
it under, not defects in it.

- **Every entry into this lane from the fleet's `async def handle` goes through
  `asyncio.to_thread`.** `ProviderCaller.call` blocks — on `Transport.send` (Exa deep reasoning
  gets 1200 s, long transcription 3000 s), on the AI Ark client's pacing sleep (up to 10.5 s per
  call), and on the retry backoff (up to 12+24+36 s). Calling it directly from an async handler
  repeats the recorded Stage-0 incident ("sync LLM/HTTP calls on the web process's event loop") at
  much larger magnitudes.
- **One `ProviderCaller` per worker task.** Its running totals (`_totals`) and its halt latch
  (`_halted`) are plain mutable attributes with no lock, so a caller shared across threads races on
  both the money trail and the latch. Sharing one is only safe if the sharing is serialised.
- **`reset_halt` is an operator action and needs a stated owner.** A latch survives for the process
  lifetime and there is no surface that clears it: whoever composes the lane decides who may call
  `reset_halt` (and on what evidence — credit topped up, key replaced), or the first refusal ends
  that provider for the process.
- **The `Transport` seam materialises whole bodies.** `send()` returns `HttpResponse.body: bytes`,
  so there is no streaming path: `download_enclosure` refuses an oversized enclosure by the feed's
  declared `length`, then by a `HEAD` `Content-Length`, then by the transferred size — but a host
  that lies about all three is still read into memory once. A streaming/size-capped transport
  (`send_to(request, sink, max_bytes)`) is R2 work.

## O4 — the synthesis turns (`clue_api/onboarding_synthesis_wiring.py`)

The step that turns the brand's onboarding research into audience documents. It is **not** in this
package: composing one governed deepagent turn means touching the agent/execution substrate, which
the lane may not import, so the module lives beside the other `clue_api` wiring roots as
`platform/api/clue_api/onboarding_synthesis_wiring.py`. The only piece that lives here is
`knowledge_frontmatter.py` — the inverse of `onboarding_documents.render_markdown`, which reads a
finished output's front matter and answers *what document is this*.

The shape is the account-research unit runner with the account scope swapped for the **brand**
scope. Each call — `launch_icps` for the ICP turn, `launch_persona` once per registered ICP —
materializes the brand's current servable knowledge documents read-only under
`inputs/brand/knowledge/`, runs one C5-governed turn inside the promoted
`onboarding-synthesis-unit@1` recipe under a per-brand system `project` row (born `archived` — a
scope anchor, never a motion a marketer opens), and registers each `outputs/` file whose front
matter identifies it as a versioned `brand_knowledge_document` (`icp-definition` → `proposed`,
`audience-persona` → `ready`). A re-synthesis at the same path writes the next version, names the
row it replaces in `supersedes_document_id`, and retires that row. Every failure is a step outcome
(`OnboardingSynthesisResult`), never a raise: the onboarding driver records outcomes.

`build_onboarding_synthesis_launcher(...)` is the production seam. `fleet_main` composes it behind
`CLUE_ONBOARDING_V2_ENABLED`; O3's `OnboardingRunWorkHandler` takes it as `synthesis=` at the merge.

Two things worth knowing before touching it:

- **The flat skill file is a duplicate on purpose.** `platform/agents/skills/audience-persona-v1/SKILL.md`
  exists only so the execution layer's flat skill discovery can resolve the `skill` pin the recipe
  requires — that pin is `audience-persona@v1` and stays there. **The catalog copy is
  authoritative**: it is the sha-pinned resource the profile carries and the agent actually reads,
  and since the synthesis split that is
  `platform/agents/catalog/skills/audience-persona/v2/SKILL.md` (`onboarding-synthesis@v2` pins the
  two `v2` skills; the `v1` profile is `retired`). Edit the catalog file the active profile pins;
  the flat one is a pin stub and says so in its own body — where it still names the `v1` catalog
  path, harmless but stale, left alone so the recipe's discovery digest is not disturbed.
- **`build_toolbelt(secrets=...)` is fail-closed.** The default `secrets=None` means *no
  credentials*, so `exa_search_evidence@1` registers but refuses `exa_not_configured` before any
  spend — deliberate, so no test toolbelt composes a live billable Exa client off a stray `.env`
  key. A production composition root must pass a real `Secrets` explicitly; `fleet_main` does.

## R2 — the account research agent

One `arv2_account_research` fleet task is **one account**: its own lease, its own job row, its own
failure. An account that goes wrong takes only itself down, and the rest of the run keeps moving.

### The module map (eleven modules)

| module | what it owns |
| --- | --- |
| `account_research_catalog.py` | the sha-pinned `arv2-account/v1` and `arv2-person/v1` catalogs (profile, prompt, three skills each), the resource bundle, and the system prompt built from it |
| `account_research_refusals.py` | the refusal codes and the envelope the model receives; each code's `reaction` sentence is the manual's row, word for word — `REFUSAL_CODES` for the account driver, `PERSON_REFUSAL_CODES` for the person driver |
| `account_research_store.py` | one function per run/job transition, plus the annotation writer and the readers the driver composes from |
| `provider_ledger.py` | the buffered raw/ledger sinks: `ProviderCaller` writes them from the worker thread, the async side drains raw bodies to artifacts and rows to `provider_call_ledger` right after the hop |
| `account_research_claims.py` | the deterministic claim mappers (provider record → typed draft) and the prose-claim carry-across |
| `account_research_tools.py` | the twelve governed tools and the `ToolRuntime` behind them (halt latch, provider semaphore, the drain, the lenient claim write) |
| `account_research_agent.py` | the `create_agent` loop and its cap-to-finalize middlewares |
| `account_research_driver.py` | the fleet handler: compose under the launch's pins, run the agent, settle the receipt — and, for an account job, fan its confirmed committee out |
| `committee_step.py` | R3: one account job's confirmed candidates become contact entities, their three committee claims and one person job each, inside the settling transaction |
| `account_research_launch.py` | **seam 1** — the account launch, the on-demand person launch, their typed refusals, the `Arv2LaunchService` seam, and the three toolbelt tools |
| `fleet_task.py` | the fleet identity of one research task (work id, dedup prefix, priority), shared by the enqueuer and the handler so neither has to import the other |

### The failure law

**A tool never raises into the graph, and `handle` contains every exception.** Every tool failure
comes back as the refusal envelope (it spends nothing, suspends nothing, ends nothing); every job
failure lands the job `needs_review` with a named `failure_code` a human can act on. The fleet
plane knows nothing about `arv2_research_job` rows, so an escaping exception would strand a job on
`in_progress` forever.

### One caller per invocation, and the buffered drain

`ProviderCaller` is synchronous and its totals/halt latch are unlocked mutable state, so **each
provider hop gets a fresh caller inside `asyncio.to_thread`** — never one shared across threads.
Its sinks only *buffer* (a Postgres write from that thread would need a loop hand-off inside a lock
the driver already holds); the async side drains them immediately after the hop, raw bodies to the
artifact store and ledger rows to `provider_call_ledger` stamped with the job id.

### The job states

`not_started → in_progress → completed | needs_review`, with `suspended` as a pause (a stopped or
lease-lost task parks there and is re-claimable). Runs share the same five words, and a run's
status is *derived* from its jobs in one statement rather than set by whoever finished one.

### Launching (seam 1)

```python
async def launch_arv2_account_research(
    conn, request: Arv2LaunchRequest, *, settings: Settings, storage: StorageBackend,
    profile_sha256: str, now: Callable[[], datetime] = _utcnow,
) -> Arv2LaunchReceipt

async def enqueue_launched_jobs(queue: WorkQueue, receipt: Arv2LaunchReceipt) -> int
```

**The rows land before the offer, and the launch itself queues nothing.** `DbTaskQueue.enqueue`
commits in its *own* transaction, so a task offered from inside the launch's transaction can reach
a worker before the run and job rows it names exist — and that worker's `begin_job` matches no row,
reads it as "a job somebody else finished", and marks the task done. The account would then never
be researched, silently and permanently (the dedup key is terminal, so no relaunch re-offers it).
So the receipt carries `to_enqueue` and the caller offers it after the commit:
`DbArv2LaunchService.launch` enqueues once the `conn_factory` block has exited, and the CLI
enqueues after `trans.commit()` and reports `"enqueued": n`. `to_enqueue` names **every** job of
the run, not only the newly inserted ones — the queue's dedup key makes re-offering a queued job a
no-op, which is what makes relaunching the repair for a run whose offer failed after the commit.
The driver has the matching defence: a task whose job row is not there returns
`job_row_not_visible` and requeues after 5 s (up to 12 attempts, then a loud `failed`), and only a
row that *exists* but is unclaimable is the idempotent `completed`.

It needs **only** account rows, an ICP artifact ref (key + sha256) and a product-selection version
— no `icp_spec`, no `account_research_directive`, no Stage-0 pin on the project run (standing rule
item 5). The ICP artifact ref is checked **against the project's ICP pin** (`project_icp_pin`,
founder rulings 2026-09-10) rather than trusted as the selector: a launch researches the one
confirmed document version a human pinned for this project, so a re-synthesis proposal or another
project's confirmation cannot repoint it. The run id is `uuid5` over the digest of the signed-off
request, so relaunching the same request returns the same run, writes no second job and buys no
second task. Every refusal is a typed `Arv2LaunchRefused` with a stable code: `lane_disabled`,
`account_not_found:<id>`, `account_not_in_workspace:<id>`, `project_icp_not_pinned`,
`icp_artifact_not_project_pin`, `icp_artifact_not_found`, `icp_artifact_not_confirmed`,
`icp_digest_mismatch`, `product_selection_version_unknown`, `project_not_found`.

Two toolbelt tools sit on it — `launch_arv2_account_research@1` (SPEND, refuses
`launch_action_ref_missing` without a captured user action) and
`read_arv2_account_research_run@1` (READ, the run row plus its job states). Both register on every
deployment and refuse `arv2_account_research_not_composed` where the lane is not composed. The CLI
for the answer-key runs is `scripts/launch_arv2_account_research.py`.

**The Head-of-ABM grant is deferred to O6** (ruling, 2026-09-08). Both tools are registered
UNGRANTED in `C6_AGENT_TOOL_AUTHORITY`, the way the ad-assets lane and the pre-P3.3 design writes
were: the platform's write surface stays complete and auditable, and the role decision lands with
the profile version that teaches the launch. Granting is not a dict edit —
`build_agent_profile_registry` refuses to compose when a role's authority and its profile's tool
list disagree, so the grant needs a new `head-of-abm` profile version carrying both pins *and* the
conversation surface's promoted-profile pin (`PROJECT_CONVERSATION_AGENT_PROFILE_ID`, checked at
`agent_turn_fleet_wiring.py:561`) moving with it. Until O6 mints that version, launching R2 is a
human act through the CLI or `launch_arv2_account_research` itself; seam 1 is unchanged either
way.

> **Resolved 2026-09-10 (O6, founder rulings 2 and 3).** `head-of-abm@v44` pins
> `launch_arv2_account_research@1`, `launch_arv2_person_research@1` and
> `read_arv2_account_research_run@1`, and all three are granted to `AgentRole.HEAD_OF_ABM`. See
> "The v44 tool surface" at the end of this file for what left the surface at the same time.

### Structuring takes sources, and the framing is never evidence (R2 close)

`structure_material` no longer takes one free `material` string. It takes **`sources[]`** (1–12),
each a `{url, kind, text, title}` block — `kind` is `page | posting | report | transcript |
provider` — plus one optional **`notes`** string. An old-shape call is refused
`invalid_arguments`; the argument model forbids extras.

- **Notes are never evidence.** The bundle renders every source as its own `=== SOURCE n (kind)
  <url> …` block and the notes as a single `=== CONTEXT — NOT EVIDENCE (do not quote)` block. A
  span that only appears in the notes comes back `NOT_FOUND` and is flagged `quoted_context` on the
  claim. Each block's own text has the fence vocabulary neutralised first, so a hostile page cannot
  close its block and re-open as a differently-attributed source.
- **The cited URL is corrected to the block the quote came from.** When a claim's span sits
  `EXACT` in a block that carries a URL, that URL wins over the one the model named (or supplied
  none) and the claim records `source_url_corrected`; the block's kind rides along as
  `source_kind_block` (which is what the audit later reads to say `second_hand_from_report`).
- **A model-produced batch writes one draft at a time.** `ToolRuntime.write_each` opens one
  transaction per draft, so one bad draft is a row in the result's
  `write_failures: [{field_key, error}]` rather than an exception that takes the batch down. Both
  model-produced batches use it — `structure_material`'s extraction and `write_claims`, which is
  the larger of the two (cap fifty). `negatives_written` counts what actually landed, and
  `dropped_rows` reports what a mode cap cut. The code-built batches (ATS board, provider record,
  finalization) still write as one transaction, because those drafts stand or fall together.
- **Proposed keys are normalised.** `normalise_proposed_key` folds spaces/dashes/slashes to `_`,
  drops anything outside `[a-z0-9_.]`, rewrites `core_x` → `core.x`, prefixes a namespace-less key
  with the subject, and — if the result still fails `is_valid_field_key` — falls back to
  `<subject>.proposed_<sha256[:8]>`. The raw spelling is kept as the marker `proposed_key_raw`.
  This is not cosmetic: the lenient gate calls `classify_field_key`, which **raises** on a
  malformed key, so one bad suggested key used to take the whole write down with it.
- **Scalar core fields are coerced.** For a field whose registry `type` is scalar,
  `coerce_scalar` unwraps a single-carrier object (`value/count/year/amount/n/total/text/name`) and
  turns a digit string into the number on an integer/number field. The original shape is kept as
  the marker `coerced_from`; an unregistered key, a list on a list field, and a two-carrier object
  are all left alone.
- A vacant committee seat is now valid with no `name` at all
  (`account.committee_candidate.required` is `["persona"]`).

### What the AI Ark mapper claims (R2 close)

`ai_ark_company_claims` now writes **every registered core/account field the record carries**, not
five. Each widened value is a tier-1 `ExtractionMethod.API` claim (`source_key="ai_ark:company"`,
`source_url=None`, markers `{json_path, provider_record: "ai_ark"}`), checked against the field's
registered `value_schema` and skipped — with `arv2.ai_ark_value_does_not_fit_its_field` — when it
does not fit or when the field is not registered in this deployment.

| record path | field |
| --- | --- |
| `summary.name` | `core.account_name` |
| `link.domain` | `core.primary_domain` |
| `summary.legal_name` | `core.legal_name` |
| `summary.description` | `core.company_about` |
| `summary.industry` | `core.industry` |
| `summary.founded_year` | `core.founded_year` |
| `summary.type` | `core.company_type` |
| `summary.staff.total` | `core.employee_count` |
| `summary.staff.range` | `core.employee_range` (`{label, min, max}`, the provider's own stated range) |
| `industries` (top level) | `core.industries_all` |
| `languages` (top level) | `core.company_languages` |
| `link.linkedin` / `link.crunchbase` / `link.twitter` | `core.company_linkedin_url` / `core.company_crunchbase_url` / `core.company_twitter_url` |
| `contact.email` | `core.company_email` |
| `technologies[].name` | `core.primary_tech_stack` |
| `technologies` | `core.tech_stack_categorised` (`[{name, category}, …]`) |
| `financial.revenue.annual` | `core.revenue_band` (bucket translation) |
| `location.headquarter` | `core.hq_location` — the **registered** shape `{raw: raw_address, city, region: state, country, country_code (only when the record carries one)}`, null keys dropped; a headquarter with no `raw_address` writes no claim at all |
| `financial.funding.total_amount` | `account.total_funding` — `{amount_usd, estimate_kind: "reported"}` |
| `financial.funding.rounds[newest]` | `account.recent_funding` — `{amount_usd, round}`, newest **by `announced_at`**, never by list position; no amount on the newest round means no claim |

**Funding amounts are read as USD** (founder ruling) and every such claim records
`markers.currency_assumed = "USD"`, so `markers->>'currency_assumed'` finds everything resting on
the assumption if a non-US record ever contradicts it. AI Ark states no currency of its own.
`core.annual_revenue` stays **unmapped**: the record answers a revenue *range* with no amount and
no currency, and `core.revenue_band` already carries the honest translation.

### The agent's model calls are ledger rows (R2 close)

Every model round of the loop lands one `provider_call_ledger` row — `provider="openrouter"`,
`operation="agent_completion"`, `phase="result"`, `label="round-<n>"`, with `extras` carrying the
served model, the prompt/completion/cached token counts and `cost_source`. Row ids are
`model:{job_id}:{attempt}:{round}`: the attempt is in the id, so a suspended job that is re-driven
does not collide its second attempt's early rounds with the first attempt's rows and lose them to
`ON CONFLICT DO NOTHING`. A round that raises records `outcome="transport_error"` with the
exception type as `error_code` and re-raises.

**The cost is OpenRouter's or it is nothing** (founder ruling — we ship no price table of our own):

1. `usage.cost` on the response (usage accounting is now asked for by default) → `cost_source =
   metered`;
2. else `GET {base}/generation?id=<generation id>` → `data.total_cost` → also **metered**. The
   lookup is bounded and can never fail the call it prices: ≤5 s timeout, one retry on 5xx, one
   retry after a 1 s pause on 404 (the meter lags the response), everything else swallowed to
   `None` with a `gateway.cost_lookup_failed` log naming the generation so a reconciliation pass
   can go back for it;
3. else the pre-existing per-model price table, *only* when a deployment happens to populate it →
   `estimate`, labelled so it can never be mistaken for a meter;
4. else `0` / `unpriced`, and the row books `cost_usd = NULL` rather than a zero nobody measured.

The rows drain **inside the settlement transaction, before `job_spend`**, so the job's `cost_usd`
already includes the model spend, and the receipt carries a `model_spend` block (calls, tokens,
cost, source). Streaming stays on the price sheet — `langchain_openai` drops OpenRouter's `cost`
on the streaming and Responses paths — but this lane does not stream.

### The link audit records why (R2 close)

`verify_links` now records a **reason** per claim alongside its verdict, in the annotation's
`detail_json` (`{reason, url, origin, structuring_mode}`):

| reason | verdict | when |
| --- | --- | --- |
| `on_page` | `EXACT` | the span is on the page |
| `partial_on_page` | `PARTIAL` | a near-miss span |
| `page_empty` | `fetch_failed` | the page loaded with no text |
| `page_unreachable` | `fetch_failed` | the fetch raised |
| `not_on_page` | `NOT_FOUND` | the page loaded and does not carry the span |
| `second_hand_from_report` | `NOT_FOUND` | same, but the claim's `source_kind_block` is `report` — the quote came through a report |
| `quoted_context` | `NOT_FOUND` | the span sat in the agent's own notes; recorded from the marker, **with no fetch at all** |

`job_link_audit` groups on `verdict` + reason and returns `"<verdict>/<reason>"` keys, which is
what the job receipt now tallies. Two behaviour notes: **every** audited claim gets an annotation
(a claim citing an already-failed URL used to be skipped silently — the URL is still fetched only
once, but each claim now gets its own `fetch_failed/page_unreachable` row), and an annotation
written before this change tallies as `<verdict>/unrecorded`, a label meaning "this row does not
say why", never a reason.

### Fit verdicts are keyed to the ICP's gates (R2 close)

`finalize_research`'s `fit_verdicts` are keyed to the pinned ICP's `hard_gates[].key`, read from
the ICP front matter at launch and carried on `JobScope.icp_gate_keys`:

- a label is matched case-folded and stripped of surrounding whitespace, and the accepted verdict
  is rewritten to the ICP's own spelling of the key, so `"Geography"` and `"stage "` are the gates
  the ICP named rather than new ones (folding a near-miss costs nothing; refusing it costs the run
  the only call that produces a finalized ending);
- a verdict naming a gate the ICP does not have *after* that folding is refused
  `invalid_arguments`, and the refusal names both the offending labels and the admitted keys —
  nothing is written and the job is not finalized, so a corrected retry is possible;
- an admitted gate the model did not assess is filled by the tool as
  `{verdict: "unclear", rationale: "not assessed"}`, and the claim carries the marker
  `filled_by_tool`;
- a **duplicate** verdict for the same gate is dropped rather than refused (first answer wins) and
  reported in `duplicate_gates`, so a repeated line never costs the finalization its summary, gaps
  and committee.

The same tuple is in the agent's context, so the list the model reads and the list the tool
enforces cannot diverge: `AccountContext.block()` renders `"icp_gate_keys": [...]` in the JSON head
and states that `finalize_research.fit_verdicts` carries exactly one verdict per key.

Three neighbouring corrections landed with it:

- **A transient `tool_error:` is not remembered.** It no longer goes through `remember_refusal`, so
  the identical retry is not foreclosed by `identical_call_repeated`. Typed refusals and
  `invalid_arguments` are still remembered.
- **A provider timeout inside the graph ends `model_error`, not `runtime_cap`.** The invoke is its
  own task; on `TimeoutError` the loop asks the task which it was — cancelled by the runtime cap
  (`runtime_cap`, in-flight hops still drained) or finished with its own exception (`model_error`,
  with `TimeoutError: …` in `error`).
- **Malformed ICP front matter is a typed launch refusal.** Unparseable front matter, a
  missing/blank `icp_key`, or a non-integer `version` each raise
  `Arv2LaunchRefused("icp_front_matter_invalid", …)` naming the document, and the CLI prints it as
  one `refused: …` line instead of a traceback. The launch pin and the bundle also now compute the
  profile digest through the same helper, so a CRLF catalog cannot pin one digest and verify
  another.

### Measuring recall against the answer keys (R2 close)

`platform/api/clue_api/arv2/answer_key_recall.py` grades a finished run's claims against the two
answer keys (Probook's file, Zafran's loaded rows), and
`scripts/arv2_answer_key_recall.py --run-id … --out …` writes `recall-probook.md`,
`recall-zafran.md` and `recall.json` from one read-only connection. It touches no provider and
spends nothing. Each key gets exactly one verdict — `exact > partial > field_only > missing` — and
recall counts `exact + partial`. Structured values are compared by their **leaf values**, never by
their object key names, so the two sides may shape `{"amount_usd": 40000000}` differently and still
agree; numbers match within 10 %.

The pre-close baseline is committed under `.context/arv2-r2-acceptance/recall-before/`:

```
probook recall 0.50 (exact 9 / partial 3 / field_only 9 / missing 3 of 24)
zafran  recall 0.45 (exact 16 / partial 14 / field_only 27 / missing 9 of 66)
```

By section — Probook `core` 5/13, `account` 7/9, `account.resonance` 0/2; Zafran `core` 16/29,
`account` 13/26, `account.resonance` 1/11. That is the number the post-close re-run is measured
against.

**R3 — the same measurement, per person.** `--people` also grades every person the answer key
covers who has claims in the graded runs: `people_keys` reads the loaded person-depth key back
grouped by contact (122 keys over ten people), each person is matched to their contact entity by
folded LinkedIn URL, and the run's claims on that contact are graded by exactly the account rules.
Each one writes `recall-<slug>.md` (`recall-nick-fisher.md`) and lands in `recall.json` under
`people`; the report carries `subject_kind: person` and `insight_found`, which is read off the
rows — any claim the job wrote carrying the `unique_insight` marker — never off what the agent
said it did. `--run-ids <a>,<b>` adds run ids to `--run-id` for every read, because a committee
person is researched inside their account's run while an on-demand person launch is its own run.

### Configuration

- `CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED` — the lane switch. Off: no fleet handler, no launch service,
  and the two tools refuse `arv2_account_research_not_composed`.
- `ARV2_ACCOUNT_AGENT_MODEL` / `ARV2_ACCOUNT_AGENT_MODEL_EFFORT` — the model this lane runs on, read
  directly by the driver (R2 composes its own loop, so there is no profile version to bump when the
  model changes). A worker with the flag on but no model id — or missing `CLUE_EXA_API_KEY`,
  `CLUE_OPENROUTER_API_KEY`, `CLUE_AI_ARK_API_KEY` or `CLUE_GEMINI_API_KEY` — logs
  `arv2.account_handler_not_composed` and composes **no handler**, so its jobs wait for a
  correctly-configured worker.
- The stop policy (founder, 2026-09-08): `CLUE_ARV2_ACCOUNT_MAX_MODEL_ROUNDS=100`,
  `CLUE_ARV2_ACCOUNT_MAX_TOOL_CALLS_PER_ROUND=50`, `CLUE_ARV2_ACCOUNT_MAX_RUNTIME_S=1800`, and no
  total-call or zero-yield cap.

### Known residual

**A lease lost mid-hop can lose that hop's ledger rows.** (The *job* is safe: the fleet cancels the
handler, and `handle` catches the `CancelledError` and parks the row `suspended` under an
`asyncio.shield` before re-raising, so the redelivery can claim it again.) The sinks buffer in the
worker thread and drain on the async side; if the lease is lost (or the task is cancelled) between the provider
answering and the drain, that hop's raw artifacts and `provider_call_ledger` rows are never
written, so money that was spent is missing from the money trail. The runtime cap already waits,
bounded, for in-flight hops; a lost lease does not get that courtesy, because the fleet cancels the
handler. Bounded by one hop per job.
## O5 — the Knowledge read surface

`clue_api/frontend_read/brand_knowledge.py` serves the onboarding documents to the brand-context
page: the servable tree, one document (verified artifact read → front matter + markdown + flattened
sources), and the onboarding status, on `/frontend/v1/brand-context/...`. Only `ready`/`proposed`/
`confirmed` versions are listed (no status chip — founder ruling 2026-09-08); the `design` folder
is the brand kit's. The store's `list_documents` stays status-blind for the page's own reasons; this
read filters.

## R3 — the committee step and the person agent

R2 researched an account and named its buying committee. R3 turns that finding into people the
platform can research, address and govern: a confirmed candidate becomes a contact entity with a
committee seat and a job of its own, and that job runs a second agent — the person agent — under
the same lane, the same fleet kind and the same failure law. Live acceptance is
`.context/arv2-r3-acceptance/acceptance.md`.

### A job row says what it researches

Migration `60e51eba0123` gives `arv2_research_job` three columns. `subject_type` is `account` (the
R2 job, and the value every existing row takes) or `person`; `subject_entity_id` is the contact a
person job researches and is `NULL` for an account job, held biconditional by the CHECK
`arv2_research_job_subject` so neither half can exist without the other; `profile_sha256` is the
agent profile *this job* was pinned to, because a person job is queued later than its run and may
run a different profile than the launch signed off on. The account a person job belongs to stays in
`account_entity_id`, so a person job is scoped, indexed and joined exactly like its siblings.
Uniqueness moved from the account to the subject: the expression index
`arv2_research_job_subject_once (run_id, subject_type, COALESCE(subject_entity_id,
account_entity_id))` still allows one account job per run and now also one job per person per run.
`downgrade()` refuses while any `person` row exists rather than dropping the column out from under
it.

There is **one fleet kind** for both subjects (`arv2_account_research`, work id = job id, dedup
prefix `arv2-account-research:`, priority −100, all three in `fleet_task.py`). The handler
dispatches on `job.subject_type`: `_compose` builds the account composition or `_compose_person`,
which pins the **job's** profile digest, loads the person catalog and the person tools, reads
`ARV2_PERSON_AGENT_MODEL` (falling back to the account model with a logged
`arv2.person_model_fallback` when the env line is unset), renders the account-then-person
already-established block, and settles a person-shaped receipt. That avoids a second fleet enum and
a second handler; the cost, recorded when it was ruled, is that person jobs compete for the same
per-kind worker slots as account jobs.

### The person catalog and its pin

`platform/agents/catalog/entity-research/arv2-person/v1/` holds five files — `profile.md`,
`prompt.md`, `dossier.md`, `audit.md`, `manual.md` — read through the same generic catalog root as
the account agent's. `profile.md` is the lane's **second pin**: `arv2_person_profile_sha256()` is
`4049f29f…` today, it is stamped on every person job at launch, and the driver refuses to compose
(`_ProfilePinMismatch`, "relaunch") when the catalog on disk no longer digests to the job's copy.
`manual.md` names every refusal code the person tools can emit, and `PERSON_REFUSAL_CODES` is
asserted against every person tool's refusals, so a tool can never hand this agent a reaction its
own manual does not carry.

### The person toolbelt (eleven tools)

`build_person_tools` binds eleven tools to one person job's runtime. Seven bodies are the account
job's, unchanged — `fetch_page`, `search_web`, `read_media_feeds`, `research_deep`,
`structure_material`, `write_claims`, `verify_links` — because they read the subject off the job's
scope rather than off the call, which is what lets one body serve both agents without a second copy
to drift. Four are this belt's own: `read_person_state` (the account reader plus the identity
lock), `lookup_person`, `unique_insight` and the person `finalize_research` (which writes openers
one claim per opener, hooks, `excluded_lookalike`, and `contact.reports_to` only when the agent
cites a posting or the person's own words).

`lookup_person` is the provider hop, and it holds three locks in order, none of them a scored
match. **(1) The argument against the job:** the URL the record is matched on must be the one the
committee step confirmed (`scope.person_linkedin_url`), not merely the one the model typed — the
check runs before the hop, so a mismatched call also costs nothing. A job carrying **no** confirmed
URL is refused `subject_lock_failed` right there, before the hop: the two provider-side locks do
not stand without an anchor (lock 2 would match whatever candidate carries the URL the model typed,
and lock 3 passes for every colleague at this account), so all three run only for URL-anchored
jobs. The person dossier's rung 2 already tells the agent to skip the call and say so in
`not_found` in that case. **(2) The LinkedIn URL:** the
name-scoped search returns up to three candidates and the one this job is about is the one whose
`linkedin_url` folds equal to that URL; no match is `subject_lock_failed`, and the refusal names
the companies the other candidates work for so they can be logged as lookalikes. **(3) The
employer, as corroboration only:** `AiArkClient._current_company_domain` resolves the record's
current employer by a ladder — fold-equal LinkedIn **company URLs** first, folded-name
**containment by whole word** second (`"cogent"` inside `"cogent security"` is the same employer
written short; `"box"` inside `"dropbox"` is not, and character containment would hand a mover the
old employer's domain and clear this very lock with it), otherwise unknown. A *different* resolvable company is `subject_lock_failed`
naming both domains; an employer the record simply cannot state lets the lookup **proceed**, with
every claim it writes carrying the marker `employer_unverified` and the result carrying
`employer_verified: false`. That third rung is the live L1 fix: the old code demanded the two
blocks spell the employer identically (`"Cogent"` vs `"Cogent Security"`), read the unstated domain
as a contradiction, and cost three confirmed members their whole lookup. Only past all three locks
is the email export bought, and the record's own claims are written **before** the export hop so a
transport failure there cannot lose the title, headline, location, badges and career history. An
export that finds nothing is a result (`email_export_empty`), never a refusal.

### `unique_insight`

The one-question pass — what a generic enrichment tool would never surface about this person — is a
**second reading of material this job already structured**, so it takes no sources of its own; with
nothing structured yet it refuses `invalid_arguments` naming the call to make instead. Its answer
may land only on a **fact** facet (`UNIQUE_INSIGHT_TARGET_KEYS`: `hobby`, `publications`,
`conference_talk`, `other_roles`, `voice_quote`, `recent_award`, `alma_mater`, `stated_interests`,
`self_summary`, `education_highschool`, `certifications`). A row on `contact.facet.hooks` or any
other outreach field is dropped, named in `dropped_off_target` and never written — the live L2
defect, where the insight landed on a derived outreach list. At most one row survives, the filter
runs before the cap (so an admissible second row is still the answer when the first was off
target), it is written at **priority 1**, and it carries the marker `unique_insight`. There is no
new field and no new column: "this job found an insight" is read off the marker on the row, never
off what the agent said it did.

### The media cap

`CLUE_ARV2_PERSON_MEDIA_MAX_ITEMS` (default 3) caps how many media items one person job may buy.
`read_media_feeds` counts the cap off the `contact.facet.public_appearances` claims **this job has
actually written**, not off a counter in memory, so a resumed job cannot re-buy what it already
has, and it checks before any source is chosen so a cap of zero costs nothing at all. Over the cap
is the refusal `media_cap_reached`, naming the count and the cap.

### The compliance pass

`person_compliance.apply_person_floor(drafts, *, purge_unevidenced)` is a **pure** function — drafts
in, surviving drafts and a log out, no settings, no database, no clock — wired at
`ToolRuntime.write`/`write_each` for person scopes only, so no person claim reaches the store
without passing it. The prompt tells the agent the floor; this module is the decision. Seven rules,
in order:

| # | rule | effect |
| --- | --- | --- |
| 1 | personal contact details — a phone, a private email or a home address, on any field but the professional `core.work_email` export | the draft is **dropped whole** |
| 2 | references to minors, even self-published | the matching **sentence is redacted**; a value that is wholly the match is dropped |
| 3 | the sensitivity floor (health, faith, politics, sexual orientation, trade-union, criminal) | same — redact the sentence, drop a wholly-matching value |
| 4 | origin, nationality, migration | recorded as biography: marker `origin_biography`, `outreach_safe=false` |
| 5 | a self-announced wedding or birth | marker `self_announced_milestone`, `outreach_safe=false` |
| 6 | no evidence span **or** no source URL | marker `unevidenced`; dropped only when the purge flag is on |
| 7 | an opener or a hook that itself meets the floor, or that rests on a sentence rule 4/5 made biography-only | the hook is **dropped** |

Redaction is by **sentence**, never by word: half a sentence with a hole in it is both unreadable
and still capable of implying what was removed. Nothing disappears silently — every drop, redaction
and marking is one row in the log (`action`, `field_key`, `reason`, `detail`), and the log rides
the person job's receipt as `compliance_log`, so a screen can say *something was removed and why*
without showing what it was; the per-call rows also come back on the `lookup_person`,
`unique_insight` and `structure_material` results as `compliance`. The pass never raises: a value
shape it cannot read is logged `unreadable_value` and passed through, because a compliance pass
that crashed the write path would cost a job every claim it had. Rule 6's purge is
`CLUE_UNEVIDENCED_ROW_PURGE_ENABLED` (default `false`) and **exempts two shapes**: a provider record
(`ExtractionMethod.API`) is evidenced by the record itself, which is not a page a human can open,
and `contact.facet.hooks` carries neither quote nor URL by design — without the exemption, turning
the purge on would delete the lane's whole deterministic spine.

The phone rule is narrower than "nine to fifteen digits": a match must carry a **phone signal** —
a leading `+`, a parenthesised area code, a dash/dot-separated tail, the UK 5+6 grouping, or one of
`tel`/`phone`/`mobile`/`cell`/`whatsapp`/`call me` in the sentence the candidate sits in. Live
(defect C1b) the looser scan merged whitespace-separated years and dates into long digit runs and
dropped four talk lists and a career history whole.

### The committee step

`committee_step.run_committee_step` runs inside the **settling transaction** of the account job
that made the finding. Each confirmed `account.committee_candidate` becomes a contact entity under
the account (reused when the LinkedIn URL already resolves to one), three claims keyed to that
contact — `contact.persona`, `contact.role_on_committee` (carrying the candidate's optional
`rationale` and `influence`) and `contact.current_title` — and one person job. Four rules shape it:
a **vacant seat is not a person** (no contact, no claims, no job — and neither is a named candidate
with no confirming URL); one member is **one savepoint**, so a member that cannot be written is a
recorded `CommitteeSkip` rather than an error that would cost the account job the `finish_job` row
it just wrote; the person job row is the member's **latch** (its id is derived from run + contact,
so a re-settled job writes nothing twice and still reports the member as work to offer); and the
step **queues nothing** — the driver offers the tasks once the settling transaction has committed,
rows first, offer second. Skip reasons are `vacant_seat`, `unconfirmed`, `committee_cap`,
`ambiguous_name` (two people of that name already under this account — refused, never guessed) and
`member_not_written`.

### The two launch paths

**Account fan-out** is the path above: `launch_arv2_account_research` starts an account job, and
its committee step queues one person job per confirmed member inside the same run. **On demand**,
`launch_arv2_person_research` researches contacts that already exist — a contact id or a LinkedIn
URL, mixed freely — and creates nobody: resolving a person is an identity act with its own
evidence, so a name the workspace does not hold is a typed refusal. It also **seats** each named
person: `seat_person_on_committee` writes `contact.persona` (from `--persona`, default `user`) and
`contact.role_on_committee` with the rationale "launched on demand by `<user>`", through the
committee step's own `committee_member_claims`, and never re-seats a contact who already holds a
live persona claim. Those two claims are written as `ExtractionMethod.HUMAN` — tier 1, no URL
required — because they are a human's own statement, not model synthesis; stamping them
`LLM_SYNTHESIS` would have tripped the writer's `source_missing` marker on a claim that is honestly
unevidenced-by-URL. `persona` is part of the run digest, so the same people at a different seat is
a different run rather than a silent replay. Its ICP comes from the **project's pin**, exactly like
the account launch's: an on-demand person launch has no approved artifact ref to be handed, and
before the pin existed it resolved "the brand's newest confirmed ICP" — an answer that moved the
moment onboarding re-synthesized or another project confirmed the same path. A project with no pin
refuses `project_icp_not_pinned` rather than researching against something nobody chose. This is the W2 walk fix: without a seat a person was
researched at full cost and then invisible on their own account's contact list. The tool
`launch_arv2_person_research@1` is registered UNGRANTED in `C6_AGENT_TOOL_AUTHORITY`, like its two
R2 neighbours.

### The repair script

`scripts/arv2_repair_person_lookups.py` re-runs the **deterministic** lookup for person jobs that
already finished — the repair for the people L1 cost. For each `--job-ids` it rebuilds the job's own
scope exactly as the driver does (the shared `person_scope_for`), calls the same two AI Ark
endpoints `lookup_person` calls, and writes the same claims under the same scope, through the same
lenient writer and the same compliance floor, with ledger rows stamped to the job that paid for
them; every claim carries `repaired: "lookup_person"`. **It never calls a model** — structurally:
the clients object it composes offers AI Ark and raises `NotImplementedError` from the rest. It is
**idempotent by default** (a contact already carrying the lookup's own non-repaired `ai_ark:person`
claims reports `skipped_already_looked_up`; `--force` overrides), `--persona` seats a finished
person who holds no seat, `--dry-run` reads and prints without a provider call or a write, and an
account job or a `not_started` job is refused on stderr with exit 2 before any spend.

### The committee the screens read

`contact_eligibility.Arv2CommitteeReferenceSource` is **first** in the default reference chain, and
its one applicability question is whether any live contact under this account holds a
`contact.persona` claim. When one does, this source is the authority for the account and hands the
resolver every live claim of every seated contact; when none does it returns `None`, which leaves
the legacy sources in charge of an account only the old lane ever researched. The coverage read was
removed from `display/gather.committee_members` (founder ruling 2026-09-09 — ARV2's own rows are
the only truth for the accounts screens), and six legacy expectations were retired with dated
reasons. `project_run_id` is deliberately unused: an ARV2 committee claim is a fact about a person
at an account, not a per-project-run artifact, so **every project targeting the account reads the
same seated people**.

**Two membership rules, on purpose (founder ruling 2026-09-10, after the rebase onto D4-b).** The
*pages* seat a contact on the D4-b rule — any contact under the account holding at least one live
claim (`display/gather.committee_members`, persona-ranked). The *governed chain* seats a contact on
R3's stricter rule — a live persona claim plus a role claim, because a governed member needs both
claim ids. They agree on live data: R3 creates contacts only through the committee step and the
on-demand launch, and both seat the person with those two claims before anything else is written.
Neither rule is to be bent toward the other. Everything below the source — product-exact filtering, the strong-binding
rule, the merge, the use-decision gate, the sort — is the shared governance, so an ARV2 answer is
governed exactly like a coverage-sourced one.

### The two migrations and the two shape changes

`60e51eba0123` is the job-subject migration above. `7c4f1a2b9d63` (its child) swaps one
**field-registry** row found wrong by the acceptance walk, exactly, in the `320e975d4c46` pattern:
`contact.facet.career_history` moves its flat `start`/`end` under the nested `date: {start, end}`
the read surface's `current_position_start` and the answer key both use — W3, which left every
mapped person's tenure empty. A row that is neither shape raises (naming the field) rather than
matching nothing in silence, and existing claims are not rewritten.

The walk's other shape finding, W1 — `core.work_email` written as a bare string while the contact
header's email chip reads `value["address"]` + `value["status"]` — is carried by **D4-b's**
migration `7332ac974920`, which landed first on the integration branch: `str`/`{"type":"string"}` →
`object`/`{address, status, checked_at?}` with the registry's closed vocabulary
`claimstore.packs.WORK_EMAIL_STATUSES` (`verified_smtp` | `catch_all_valid` | `invalid` |
`unknown` | `unverified`). R3's export mapper (`email_export_claim`) writes that shape; a found
export is always one of the two usable verdicts. The two flag-off old-lane writers of the field
(`frontend_read/contact_email_lookup.py`, `contact_channel_enrichment.py`) are D4-b's, and write
the verdict shape with `unverified`. The R3 and D4-b migration chains meet at the join
`57e06d696d49`, the single head.

### Configuration (R3's additions)

- `CLUE_ARV2_PERSON_MEDIA_MAX_ITEMS` (default `3`) — the per-person media item cap above.
- `ARV2_PERSON_AGENT_MODEL` (`x-ai/grok-4.6`) / `ARV2_PERSON_AGENT_MODEL_EFFORT` (empty) — the
  person lane's model, in the consolidated agent-model block. Unset is not a refusal: the driver
  falls back to the account model and logs `arv2.person_model_fallback` once at composition.
- `CLUE_UNEVIDENCED_ROW_PURGE_ENABLED` (default `false`) — compliance rule 6's purge.
- The lane switch and the stop policy are R2's, unchanged; person jobs read the same three
  `CLUE_ARV2_ACCOUNT_MAX_*` ceilings.

### Running it

```bash
set -a; source .env; set +a

# fan-out path: one account job whose committee queues its own person jobs
uv run python scripts/launch_arv2_account_research.py \
    --workspace ws_arv2_answer_key --project prj_arv2_answer_key \
    --accounts zafran.io --effort full --committee-cap 5

# on-demand path: contacts that already exist, seated as they are launched
uv run python scripts/launch_arv2_person_research.py \
    --workspace ws_arv2_answer_key --project prj_arv2_answer_key \
    --contacts https://www.linkedin.com/in/dana-reyes,<contact-uuid> \
    --persona champion --directive "open with the podcast"

# repair a finished person job's deterministic lookup (no model, idempotent)
uv run python scripts/arv2_repair_person_lookups.py --job-ids <job-uuid> --persona user --dry-run

# recall, per person as well as per account
uv run python scripts/arv2_answer_key_recall.py --people \
    --run-id <account-run> --run-ids <person-run>,<second-person-run> \
    --out .context/arv2-r3-acceptance/recall
```

`--people` grades every person the answer key covers who has claims in the graded runs:
`people_keys` reads the loaded person-depth key back grouped by contact (122 keys over ten people),
each person is matched to their contact entity by folded LinkedIn URL, and their claims are graded
by exactly the account rules. Each writes `recall-<slug>.md` and lands in `recall.json` under
`people`, carrying `subject_kind: person` and `insight_found` — read off the `unique_insight`
marker on the rows, never off what the agent said. `--run-ids` is additive to `--run-id` because a
committee person is researched inside their account's run while an on-demand launch is its own run.

### Known residual (R3)

The leaf-value recall grader understates a person run. Almost every missed key grades `field_only`
— the field is found but the free-text value does not leaf-match the answer key's phrasing — because
person facets are prose (a hobby, a quote, a talk) and exact leaf agreement is the wrong grader for
them. Field-found coverage was ≈ 0.9 on every person researched live. A semantic or containment
mode for facet text is the follow-up; until it exists, the R3 recall number is not the number the
master plan's exit gate means.

## O6 — the Head-of-ABM integration (what of it lives here, and what cannot)

Only one O6 module is inside the lane: **`icp_confirmation.py`**. It owns the ICP *knowledge
document* as the subject of a human gate — `current_icp_document` (the brand's current servable
`icp-definition` document for one key, read back through its verified bytes so its `product_ids`,
title and any existing confirmation are the document's own), `icp_gate_subject_ref` /
`icp_gate_snapshot` (what the gate names and shows), `confirm_icp_document` (the human's yes,
minted as a new `confirmed` version of the same path, stamped `confirmed_for_project_id`, with the
proposal retired) and the **project ICP pin** — `pin_project_icp` / `current_project_icp_pin` over
`project_icp_pin`, an append-only table whose greatest `pin_seq` is the project's current ICP. The
pin is written in the same transaction as the approval that minted the version, and it is what the
index card, the account launch and the person launch all resolve the project's ICP from;
`confirmed_for_project_id` in front matter survives as data about that document, never as the
selector. It imports only `clue_storage`, `clue_core`, SQLAlchemy and its `arv2` siblings, so the
import guard is satisfied.

The rest of O6 is composition, and composition may not live under `arv2/` — a module here imports
nothing outside the allowed prefixes (`tests/arv2/test_import_guard.py`), and these three need the
agent-turn, gate, toolbelt and chat machinery in `clue_api` proper:

| Module (outside `arv2/`) | What it owns | How it uses the lane |
|---|---|---|
| `clue_api/brand_knowledge_context.py` | The turn's knowledge pin (`agent_turn_knowledge_pin`) — which always contains the project's pinned ICP version, even when a newer one exists on its path — the pinned bodies, the read-only seed files under `inputs/brand/knowledge/`, and `BrandKnowledgeIndexCard@1`, whose `confirmed_icp` is the pinned document | Reads the same onboarding document rows this lane writes; parses their front matter with the lane's `knowledge_frontmatter`, and reads the lane's `current_project_icp_pin` |
| `clue_api/product_set_selection_gate_tools.py` | `open_product_set_selection_gate@1` — the set-valued product gate over the brand's catalog document | Presents the catalog contract §7.1 snapshot the lane's catalog synchronizer produced |
| `clue_api/icp_artifact_gate_tools.py` | `open_icp_confirmation_gate@2` — the gate over a knowledge-document artifact ref | Calls `arv2.icp_confirmation` for the subject, the snapshot and the confirmation write |

The direction of the dependency is the point: the composition modules import the lane, never the
other way round. Nothing on any of these paths reads a Client-KB version, a readiness decision or a
Stage-0 run pin (standing rule `_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`); an ICP
and a product catalog are files, and a file is pinned by ref and digest.

### The v44 tool surface — what the Head of ABM gained, and what left with it

Founder rulings 2 and 3 (2026-09-10) closed the grant this README deferred to O6, and they closed
it on **both** sides. `head-of-abm@v44` now pins fourteen tools, and the whole research surface of
the conversation is this lane's three:

- **granted (this lane)** — `launch_arv2_account_research@1`, `launch_arv2_person_research@1`
  (ruling 3: researching people a human named is the same act on the same lane as researching
  accounts they named) and `read_arv2_account_research_run@1`.
- **dropped (ruling 2)** — the five old-research-lane tools `launch_account_research@1`,
  `launch_selected_account_research@1`, `launch_contact_research@1`,
  `read_account_research_run@1` and `read_contact_research_run@1`, together with the skill that
  required all five, `account-deep-steering@v8`. They stay registered and invocable by whatever
  non-model surface still calls them, and `_RESERVED_REASON` records `superseded_by_onboarding_v2`
  against each so the capability map states WHY the model cannot reach them. A steering skill
  written against the ARV2 tools is a follow-up before O7 — dropping the old one is not a licence
  to re-grant its tools.

Mechanically: all three ARV2 tools declare `pin_requirements = ("project",)` — the execution row is
the trusted project coordinate (`Stage0StepPinProvider._execution_project_pin`), never a
model-authored body field, and the replay-safety audit refuses a standing recipe address that
declares no pin at all. All three are in `RECIPE_0_TOOL_ADDRESSES` and in `recipe0-stage0@22`'s
allowlist, slot requirements and node compatibility. The Stage-0 conversation *trial* withholds
both launches and both gates (a dev harness must not queue real jobs or address a real gate); the
run read stays installed there because it is read-only and addresses nobody.

## R4 — verified account discovery

R2 and R3 research accounts a human named. R4 is where the names come from: a cohort is
**discovered** from the project's pinned ICP, every candidate is **verified gate by gate** with a
quote and a source, and the human **approves** on the accounts table — after which the approved
accounts launch into the R2/R3 lane and display on the existing screens with nothing new to learn.
The plan of action is `docs/superpowers/plans/2026-09-10-arv2-r4-discovery-substance.md` (rev 5;
its §9 is the rulings ledger this section cites); live acceptance is owed under
`.context/arv2-r4-acceptance/`.

**The ICP document is the program.** Every confirmed ICP carries `hard_gates[] {key, rule, test}`
and `exclusions[]`, written in plain language and confirmed by a human. R4 encodes no gate in code:
the long list is built from the ICP's wording and the verifier asks each gate's own `rule` and
`test` as a question. A new ICP changes the questions and nothing else. Pattern code keeps one job —
reading structured provider payloads — and one regex ever touches ICP prose (the month count in a
gate's window).

Two providers, each doing the one thing the proofs of concept showed it does well
(`_memory/2026-09-10-arv2-r4-websets-experiment.md`): **Exa Websets** in company mode *finds*
companies (Exa `/search` on prose queries returns content *about* an ICP, not members of it), and
**Exa Answer** with a system prompt and an `outputSchema` *verifies* them (Websets' own criteria
verdicts were wrong six times in fifteen). The hand-written regex probe of rev 4 was dropped.

### The module map (nine modules)

| module | what it owns |
| --- | --- |
| `discovery_store.py` | the only module that speaks SQL to `arv2_discovery_run` / `arv2_discovery_candidate`: one function per run transition (`create_discovery_run`, `begin_discovery_run`, `record_webset`, `record_relaxed_search`, `request_relaxed`, `suspend_discovery_run`, `finish_discovery_run`), the candidate writers (`upsert_candidate`, `record_verdicts`, `mark_candidates_approved`) and the readers (`list_candidates`, `unapproved_domains`) |
| `exa_websets_client.py` | the thin Websets client — `create` / `get` / `items` / `add_search` through one private `_call` on the injected `ProviderCaller`, `is_all_green`, `newly_priced` (a webset row is billed once per run: `items(…, priced_item_ids=…)` returns every row and prices only the new ones), `websets_items_cost`, `websets_halt_rule` |
| `exa_client.py` (`answer`) | R4's addition to the R1 client: `answer_body`, `ExaCitation`, `ExaAnswerResult`, `ANSWER_ESTIMATE_USD`, and `ExaClient.answer` — one `/answer` hop inheriting the module's existing cost reader and halt rule |
| `discovery_brief.py` | the ICP document compiled into the brief one run executes — `Gate`, `DiscoveryBrief`, `compile_brief`, `buyer_sentence`, `parse_window_months`, and the typed `BriefError` |
| `discovery_verifier.py` | what we send and what we trust — `system_prompt(today)`, `gate_question`, `website_question`, `OUTPUT_SCHEMA` / `WEBSITE_SCHEMA`, `apply_guards` (the three guards), `fit_score`, `disposition`; pure, with no clock, no settings, no database and no provider |
| `discovery_launch.py` | **seam 1** for discovery — `read_pinned_icp` (the project's *current* pin, for the launch) and `read_icp_document` (a run's *own* pinned bytes, by key and sha, for the driver), `launch_arv2_discovery` (replay + lineage, rows only), `request_relaxed_pass`, `enqueue_discovery_run`, the `Arv2DiscoveryService` seam and the `launch_arv2_discovery@1` toolbelt tool |
| `discovery_driver.py` | the fleet handler: claim, compile, buy the long list, verify every candidate, land the run — plus `relaxed_criteria` and `revenue_band`, the two pure helpers its arithmetic lives in |
| `fleet_task.py` | R4's three names beside R2's — `ARV2_DISCOVERY_DEDUP_PREFIX = "arv2-discovery:"`, `ARV2_DISCOVERY_TASK_PRIORITY = -90`, `arv2_discovery_work_id(run_id)` (the run id **is** the work id) — so the enqueuer and the handler never import each other |
| `scripts/launch_arv2_discovery.py` | the operator CLI: launch, `--relaxed-pass <run>`, `--report <run>` |

`FleetTaskKind.ARV2_DISCOVERY` is its **own** fleet kind (unlike R3's people, which ride the account
kind) because a discovery run takes minutes, spends money and must survive a worker restart. Its
priority is −90: it outranks ordinary work and **yields to account research at −100**, because
research is work a human already approved on named accounts and discovery is looking for accounts
nobody has picked yet. Migration `2cd622be2da0` adds the enum label and the two tables; its
`downgrade()` refuses while any `arv2_discovery` task exists.

### The run, step by step

1. **Claim.** `begin_discovery_run` takes a `not_started` or `suspended` run. Nothing to claim is an
   idempotent `completed` and not a cent spent; a stop or a lost lease parks the run `suspended`; a
   task whose `work_id` disagrees with its `run_id` is refused before any spend.
2. **Compile.** The **launch** resolves the project's pinned ICP with `read_pinned_icp`
   (`project_icp_pin`; no pin is the refusal `project_icp_not_pinned`) and stamps its artifact key
   and sha on the run row. Every **attempt** then re-reads *that* document with `read_icp_document`
   — by the run's own key, refusing `icp_digest_mismatch` when the bytes have moved — rather than
   the project's current pin, so a human who confirms a new ICP version while a run is queued or
   suspended cannot silently change the gates half-way through it. `compile_brief` turns the
   document into the query sentence, the criteria and the gates. **Which gates become the webset
   criteria is the document's own decision**: the gates it marks `criterion: true`, in document
   order; when it marks none, its first three gates in document order. The launch records the
   resolved keys on the run row, so every attempt compiles the same criteria. A caller may force
   keys (the tool's request, the CLI's `--criteria-gates`, the operator env), and those are
   validated against the document. More than three, named or marked, is a refusal, never a silent
   truncation of a criterion the human configured.
3. **The long list.** One webset, `entity.type = company`, `count` = the strict ask,
   **at most three criteria** — each a hard gate a public page can answer, worded as the ICP means
   it. Hiring and intent are never webset criteria (3.7% and 2.7% success rates starved the search
   to one company); they are verified in step 4. `recall: true` records Exa's estimate of the pool
   size *before* the spend. The run polls to `idle` under a wall clock
   (`arv2_discovery_wall_s`, → `needs_review` with `webset_wall_exceeded`), and a run that already
   recorded a `webset_id` **reads it again instead of buying another**, whether the redelivery is a
   human's relaxed request or a plain resume after a restart. The webset's `strict_search_id` is
   recorded with it, so no later attempt has to guess which of a webset's searches is the strict one
   (array position is not a provider contract); a webset carrying two searches on a run that
   recorded no strict id refuses `webset_search_ambiguous` rather than guessing. Every read of the
   items page names the rows this run has already been charged for, so a resumed or widened run
   prices each row **once** — the receipt says so with `credits_priced_once`.
4. **Per candidate**, in this order, so nothing is verified twice or paid for needlessly:
   - **the website**, first: one Answer call for the company's own registrable domain, because
     Websets returned `probook.com` for `probook.ai`. The announcement's domain wins and the
     mismatch is recorded on the snapshot.
   - **the dedupes**, before any gate: a verified domain already an account in this workspace is
     `duplicate_of_existing`; one an earlier run of this project surfaced and the human did not
     approve is `not_chosen_before`. Both are recorded as candidate rows and cost exactly the one
     website answer. *Unapproved is not rejected* (ruling 1′): the row carries no "rejected" label
     anywhere, it simply is not surfaced again. Since ruling 8′ (2026-09-11) every verified
     candidate becomes a workspace account **and a member of the launching project** at once, so
     within one project a re-found company is always `duplicate_of_existing` first and
     `not_chosen_before` no longer arises; the mechanism stays for the cross-project case.
   - **one Answer per hard gate**, asking the gate's own `rule` and `test` verbatim under a system
     prompt that fixes today's date, ranks the company's own pages and dated news above profile
     pages, and says that no source found is `unclear`, never `fail`. Aggregator job sites count as
     hiring and intent evidence (ruling 5′).
   - **the three guards**, then **fit and disposition**, then the candidate account.
5. **The relaxed pass** — only when the strict pass came up short **and** the run allows it
   (automatically, or on a human's later request; both triggers are supported). It drops the
   criterion with the lowest success rate on the strict search (ties resolve to the last; an unrated
   criterion counts as lowest), adds a second search on the **same** webset excluding the strict
   results, asks for the shortfall, and then verifies every company it returns on **all** gates
   exactly like a strict one — so a partial match lands Medium or Low with an honest score rather
   than being hidden (ruling 4). The widening is bought **once per run**: its search id is recorded
   the moment `add_search` returns, and a run that already carries a `relaxed_search_id` polls and
   reads it instead of adding a second search (whose exclusion would name only the strict search,
   so Exa would re-find and re-charge for the first widening's results, once per retry).
6. **Land.** `finish_discovery_run` records a terminal status only (`completed` / `needs_review`)
   with `asked`, `found_strict`, `found_relaxed`, `analyzed`, the recall estimate and a receipt
   carrying the counters a human reads to decide whether the pool was exhausted or the ICP is too
   narrow: `shown`, `target_count`, `criteria`, `criteria_relaxed` (what *this attempt* sent, so
   null on an attempt that found the widening already bought), `relaxed_search_id` (which says a
   widening happened at all), `credits_priced_once`, the guard hit counts, `cost_usd`,
   `duplicates`, `not_chosen_before`, `unresolvable_domain` and `candidate_failures`. A short list is
   information, never padded.
7. **Containment, per candidate and per run.** `handle` never raises. One candidate that fails is
   logged, named in `candidate_failures` and left `pending` for the next attempt — its neighbours
   are still verified and the run lands `needs_review` keeping every counter. `ProviderHalted` and
   the wall clock end the *run* (the candidates already paid for are kept); a cancellation suspends
   under a shield. Every provider hop is one fresh caller inside `asyncio.to_thread` whose ledger and
   raw sinks are drained under the run's `LedgerStamp` in a `finally` — costs are always recorded and
   **never a gate** (ruling 3).

### The three guards

One guard per error kind the proof of concept actually produced, and nothing else. Each turns a
verdict the model got wrong into one a human can trust, and every overturn is recorded on the row
(`guard`, beside the model's own `model_verdict`):

| guard | what it catches |
| --- | --- |
| `quote_not_on_page` | `evidence_quote` must appear verbatim — NFKC-folded, typography and case normalised — in the text of a citation Exa actually returned; otherwise `unclear` |
| `wrong_company` | the citation carrying the quote must be on the company's verified domain, or name the company in its text on a word boundary (character containment would let a posting from same-name `infinIT` clear the guard for `INFI`); otherwise `unclear` |
| `outside_window` | when a gate names a window, the arithmetic is **code's**: `evidence_date` is checked against it (the model called a 2023 round "within 24 months"), and a pass outside the window becomes `fail` |

Plus two rules that are not guards: `no_source` (an empty quote or URL on a pass/fail is `unclear`),
and `malformed` (an answer that is not a mapping, or a verdict word the schema forbids, is `unclear`
with the model's word kept). Every one of them errs toward `unclear`, never toward a `fail` the
evidence does not support.

**Fit** is `(passes + ½ × unclears) / gates`, banded by the accounts list's own thresholds
(`CLUE_ARV2_FIT_HIGH_THRESHOLD` / `CLUE_ARV2_FIT_MEDIUM_THRESHOLD`) — a full match reads High 100,
three passes and one unclear High 88, half Medium 50, one of four Low 25. The Overall fit vocabulary
stays exactly High / Medium / Low; an unclear account is a Medium by score (ruling (a)), and every
discovered account is shown, Low fit included (ruling 5). `disposition` is `pass` / `partial` /
`unclear` — never `fail`, because a company we could not verify is not a company we disproved.

### What the human sees, and what approval is

Every verified candidate that is not a duplicate becomes an `account_entity` (`status = candidate`,
verified domain as the strong key, workspace-scoped) carrying one `account.scoring.fit` claim —
project-relative through the run's `run_lineage` row, kind `discovery` — plus the ordinary
`core.employee_count` / `core.revenue_band` claims from the Websets firmographics when they are
there. That is the table's **Overall fit** badge and **Fit score**; research status reads "Not
started". The per-gate verdicts, with their quotes and URLs, sit on the candidate row and are handed
to the researcher as "already established" at launch.

**Two founder rulings of 2026-09-11 changed what the table shows and what "approval" means.**
Ruling 7′: **a fit is global to the account** — the accounts list and the account detail show the
account's most recently scored fit whichever project scored it, membership or not
(`frontend_read.accounts_list.account_fit`; the FI-2 §7 primary-project rule is superseded on those
two surfaces, the detail's project sections keep the attribution). Before it, every freshly
discovered account showed an empty fit column, because it belonged to no project until approved.
Ruling 8′ (supersedes 6′): **a discovered account belongs to the launching project by default** —
the driver records the `project_account` membership (`added_via = 'discovered'`) in the same
transaction as the account row and its claims, for pass, partial and unclear alike; the human reads
the verdicts on the table and removes what they do not want. Adding the account to any *other*
project is the explicit human action below.

**Rulings 9′ and 10′ (2026-09-11): the mark, and the owner.** Every verified candidate's account
shows a **mark-type logo** — never a wordmark, never a banner — and the founder ruled Brandfetch's
**Logo API only** (the Brand API is overkill). Two sources, one rule each (`logo_resolution.py`):
Websets' `logoUrl` is **stored** as `core.logo_url` when it is LinkedIn's company mark (the PoC found
those correct in every inspected case and site-hosted images wrong about half the time — Open Graph
banners, team photos), and the platform's own route `/api/clue/frontend/v1/accounts/{id}/logo`
(`frontend_read/account_logo.py`) streams it under the workspace scope. A company with no stored
mark gets Brandfetch's Logo API URL for its domain at **display time**
(`cdn.brandfetch.io/domain/{domain}/w/128/h/128/fallback/lettermark/type/icon?c=<client id>`,
`CLUE_BRANDFETCH_CLIENT_ID`, public by design) — built by the reads, never fetched or stored:
the Logo API is embed-only and answers a script's fetch `302 x-bf-error: automated_traffic`
even with a valid client id, so the browser embeds it with its own `Referer`, and the frontend
renders both shapes with Next's optimizer off. No client id → the placeholder. And the human
who launched the discovery is each account's **creator and owner** (a fleet-driven launch
resolves the turn's human; `insert_account_entity(owner_user_id=…, created_by_user_id=…)`), until
an ownership mechanism exists. `scripts/backfill_discovery_run_logos_and_owners.py` applies both
to a run made before the rulings.

**The accounts table is the approval surface** (ruling 2), and the approval is the existing
"Add to project" bulk action — no new screen, no new button. Since ruling 8′ it means "add to
another project": for the launching project the membership already exists. `bulk_actions.add_accounts_to_project`
calls `mark_candidates_approved` on the **same transaction** as the membership insert, so a
membership and its approval land together or not at all; only the accounts that action actually
inserted are decided, and the store's `decision IS NULL` guard means a replay or an overlapping
second selection decides nobody twice. `decided_by_user_id` is `actor_user_id or requested_by` — the
same fallback the rest of the lane uses for the requesting human, so a local-auth approval records
the id that mode does carry rather than nobody. The approved cohort then launches through the
existing `launch_arv2_account_research`; there is no research button and no new research path.

### Configuration (R4's additions)

Eight keys, all in `.env.example` at parity:

- `CLUE_ARV2_DISCOVERY_ENABLED` (default `false`) — composes the handler and the launch service, and
  only when `CLUE_EXA_API_KEY` is configured too (otherwise the composition warns
  `arv2.discovery_handler_not_composed` and stays `None`). The tool registers on every deployment
  and refuses `arv2_discovery_not_composed` where the lane is off.
- `CLUE_ARV2_DISCOVERY_STRICT_COUNT` (default `35`) — the strict pass's ask for a target of 20,
  while precision is being measured (ruling 4).
- `CLUE_ARV2_DISCOVERY_RELAXED_AUTO` (default `true`) — run the relaxed pass automatically when the
  strict pass falls short.
- `CLUE_ARV2_DISCOVERY_CRITERIA_GATE_KEYS` (default **empty**) — operator override only. Empty means
  the pinned ICP decides its own webset criteria (below); a comma-separated list of that document's
  hard-gate keys forces those instead. At most three either way; a fourth is refused, not dropped.
  There is no deployment-wide default gate set (founder ruling 2026-09-11): the first Insight Health
  launch was refused `unknown_criteria_gate_key 'geography'` because the shipped default named the
  Clue ICP's keys and a synthesised ICP names its own.
- `CLUE_ARV2_DISCOVERY_ANSWER_MODEL` (default `exa`) — the Answer model the verifier asks.
- `CLUE_ARV2_DISCOVERY_POLL_INTERVAL_S` (default `15`) / `CLUE_ARV2_DISCOVERY_WALL_S` (default
  `1800`) — the webset poll cadence and the run's wall clock.
- `CLUE_ARV2_DISCOVERY_WEBSETS_USD_PER_CREDIT` (default `0.00449`) — Websets bill 10 credits per
  all-green result; this is the plan's dollar rate for the pre-spend estimate and the ledger.

### Starting one

```bash
set -a; source .env; set +a

# the operator path
uv run python scripts/launch_arv2_discovery.py \
    --workspace ws_arv2_answer_key --project prj_arv2_answer_key --target 20

# a relaxed pass on a run that already finished, and reading what a run found
uv run python scripts/launch_arv2_discovery.py --workspace ws_arv2_answer_key --relaxed-pass <run-id>
uv run python scripts/launch_arv2_discovery.py --workspace ws_arv2_answer_key --report <run-id>
```

`--report` deliberately does not require the lane flag: an operator must be able to read what a run
found on a deployment where discovery has since been switched off.

**From the project chat**, `head-of-abm@v45` grants `launch_arv2_discovery@1` — the profile bump
lands in R4, not at O7 (ruling 4′). v45 is v44 plus that one tool and the skill that teaches it
(`stage0-interview@v22`, whose new **§7b "Discover accounts for this project"** is the passage the
founder reviewed in chat), and `recipe0-stage0@23` carries the address in its allowlist, its slot
requirements and its node compatibility. The tool declares `pin_requirements = ("project",)`, so the
project coordinate is the execution row's, never a model-authored body field. The Stage-0
conversation *trial* withholds it beside the other two launches: a dev harness must not queue a real
discovery run against real providers.

### What R4 deliberately does not build

- **The Websets exclusion import.** Local dedupe by verified domain runs *always*; importing the
  workspace's existing account websites into the webset's own `exclude` waits until Exa confirms the
  per-plan cap on that list (ruling 1′). Nothing is lost meanwhile — the local dedupe catches the
  same companies, it just catches them after the long list rather than before it.
- **A per-run concurrency cap.** O6's per-process worker slots stand as they are; how workers are
  shared across job kinds — and whether the AI Ark spacing rule becomes a shared limiter — is a
  scheduling discussion of its own, taken up separately (ruling 3′). Inventing a cap here would
  pre-empt it.
- **Any frontend change.** Not a lifted screen, not a slot, not a marker: parity with the dummy
  frontend is the reference, and the accounts table already shows Overall fit, Fit score and research
  status. Suggestions live in `2026-09-10-arv2-frontend-polish-backlog.md`.
- **A chat approval gate.** While the accounts table is the approval surface, no gate tool is needed
  (ruling 2). ~~What the future in-project target-accounts tab reads is the founder's later
  decision (ruling 6′).~~ **Superseded 2026-09-11 by ruling 8′:** discovered accounts are members
  of the launching project from the moment they are verified, so the tab reads the project's
  members and nothing is pending.
- **The ICP's exclusion questions.** Spec §3 asks one `POST /answer` per hard gate *and per
  page-answerable exclusion*; R4 asks the gates only. `compile_brief` still compiles
  `DiscoveryBrief.exclusions` from the document, and nothing reads it. Two open questions make this
  a founder decision rather than an omission to fix quietly: how an exclusion scores, given that fit
  is `passes / gates` today and an exclusion is a disqualifier rather than a gate; and the cost —
  the confirmed Clue ICP states eight exclusions, so asking them is about eight more Answer calls,
  roughly **$0.04 per company**, on top of the four gate calls. Recorded as final-review finding I3;
  until it is decided, a company that clears every hard gate but sells to consumers can still land
  as a High-fit candidate for a human to read.

## ICP authoring and project-scoped documents (2026-09-12)

Before this, the only way a profile came into being was `synthesize_icps` during the brand's
onboarding walk: the walk wrote the brand's ICPs, a human confirmed one, and a project pinned it.
A marketer who read the proposals and said *"none of these is who we sell to"* had nowhere to go.
Now the Head of ABM can **write one down** in the conversation, and can ask for the **personas** of
a profile the human has confirmed. The documents an authoring turn produces can be **project-local**
— the same brand, a different project, a different profile — which is why the knowledge tables
grew a scope.

### The schema (migration `b953bf11e2a9`)

`brand_knowledge_document` gains:

- **`project_id text NULL`** — `NULL` is the brand's own knowledge; a value scopes the row to one
  project. The FK is composite (`(project_id, workspace_id) → project`), so a document cannot scope
  itself into another tenant's project.
- **`derived_from_document_id uuid NULL`** — the brand-level document this one was written from
  (self-FK). Lineage, not currency: it says what the author read, never what is served.
- The old `brand_knowledge_document_path_version` UNIQUE is replaced by the **scope-aware unique
  index** `brand_knowledge_document_scope_path_version (workspace_id, brand_id,
  COALESCE(project_id, ''), path, version)` — one path may exist once per scope per version, so a
  project's variant of `audience/icp.md` coexists with the brand's. The `''` sentinel is
  load-bearing; a real project id is never empty (the composite FK makes it unreachable).
- A partial index for the project reads, `'project'` admitted to the folder CHECK and
  `'project-plan'` to the kind CHECK.

`onboarding_run` gains **`kind text NOT NULL DEFAULT 'full'`** (`'full' | 'personas'`),
**`project_id`**, and **`persona_icp_document_id`**, welded by
`onboarding_run_persona_shape`: `(kind = 'personas') = (persona_icp_document_id IS NOT NULL)`. A
partial index enforces the one-open-personas-run-per-ICP-document read.

### The reader rule

One sentence decides every read: **a brand reader sees brand rows; a project reader sees both and
lets the project win.**

- **Brand readers filter `project_id IS NULL`.** `brand_knowledge_context.current_knowledge_documents`,
  the five onboarding-walk reads in `onboarding_store` (the walk writes the *brand's* knowledge and a
  project variant must not push its version chain along), and every `frontend_read/brand_knowledge`
  read including the PUT's `FOR UPDATE`/`MAX(version)` pair. That module's `IntegrityError` mapping
  now names `brand_knowledge_document_scope_path_version`.
- **Project readers union.** `current_project_knowledge_refs(conn, *, workspace_id, project_id)` is
  the mirror of the brand reader; `_current_input_documents` in `onboarding_synthesis_wiring` unions
  the ICP's project over the brand so a persona turn can read the very document it was asked about.
- **The ICP lookup orders project-local first.** `icp_confirmation.current_icp_document(...,
  project_id=)` selects `AND (project_id IS NULL OR project_id = :project_id)` and orders
  `path, (project_id IS NULL), version DESC` — a project-local row wins its path, and an unscoped
  read (`project_id=None`) sees brand rows only. `confirm_icp_document` mints the next version *in
  the subject's own scope* (`IS NOT DISTINCT FROM`) and carries `project_id` +
  `derived_from_document_id` forward; `ProjectIcpPin` carries the scope too.
  `account_research_store.read_persona_documents` is scoped the same way (a project's own persona
  beats the brand's), threaded from `run.project_id`.
- **Materialization.** `workspace_paths` groups by `(project_id, path)`; a project ref resolves
  through `project_workspace_path`, so it lands under `inputs/project/…` rather than
  `inputs/brand/knowledge/…`, and `knowledge_seed_files` **skips** it — plan 1's project-files pin
  owns everything under `inputs/project/`. `project_status.current_project_documents` compiles those
  rows onto the lease beside `status.md`/`decisions.md`, and `status.md` lists them under *Project
  documents* off the same read, so the card cannot name a file the turn does not seed.

### The two tools

**`author_icp_document@1`** (`clue_api/icp_authoring_tools.py` over
`arv2/icp_authoring.py`) — WRITE, `DOMAIN_IDEMPOTENT`, free. The model supplies `icp_key`, the whole
`document`, `scope` (`brand` | `project`) and an optional `derived_from_icp_key`; the project, brand,
human and turn come from the trusted `source_turn_ref` (pinned through
`_presenting_turn_project_pin`). The row is born **`proposed`** — authoring proposes, the human's
confirmation gate still decides. The document id is
`uuid5("arv2-icp-authoring:{turn}:{scope}:{key}")`, so a replay inside one turn returns the stored
row rather than re-rendering (the `authored_at` stamp is the one non-deterministic byte). Platform
front matter (`status`, `brand_id`, `project_id`, `derived_from`, the confirmation stamp,
`product_selection_version`, `user_edit`) is stripped from whatever the model typed and re-stamped
from the resolved rows. Supersede is scope-local and never retires a `confirmed` row.
Refusals: `icp_key_invalid`, `icp_front_matter_invalid` (kind / `icp_key` / non-empty `product_ids`
/ non-empty `hard_gates`, with the reason in the message), `icp_key_taken_by_brand`,
`icp_key_taken_by_project` (only a *servable* row owns a key — a superseded one's name is free
again), `derived_from_not_found`, `icp_document_version_race`; plus the turn-binding
`authoring_turn_ref_malformed` / `authoring_turn_not_found` / `authoring_addressee_missing` and
`icp_authoring_not_composed`.

**`request_persona_synthesis@1`** (`clue_api/persona_request_tools.py`) — SPEND,
`DOMAIN_IDEMPOTENT`, composed behind `onboarding_v2_enabled` (what it opens *is* an onboarding run;
with the lane off no worker would drive it and the row would hold that document's one open slot
forever). It takes the `icp_key`, checks it against the project's **pinned** ICP, and offers a
**personas-only onboarding run** through `DbOnboardingEnqueuer` — one place knows the task shape.
`persona_run_id = uuid5("arv2-persona-run:{ws}:{document_id}:{turn}")`.
Refusals: `persona_synthesis_not_composed`, `icp_not_pinned_for_project` (covers both "no pin" and
"not this key" — one fact from the agent's side), `persona_run_already_open`, `brand_not_onboarded`
(no completed `full` walk to copy the company domain from), `enqueue_failed` (which leaves the run
`failed`, so the document is free again), plus the turn-binding trio.

### The personas-only run

`onboarding_driver._run` branches to `_personas_only` before anything else: `mark_run_running` →
one `_persona_step` (the same step the full walk runs, unchanged) → `finish_run`. No client binding,
no recon, no catalog sync, no ICP turn — the brand was onboarded long ago. The `IcpRef` carries
`project_id`, so the persona is registered in the **ICP's own scope**, and `_register_documents`
takes its `project_id` from the ICP it was asked about.

Two filters keep the personas run out of the full walk's surfaces: `read_current_run` adds
`AND kind = 'full'` (the setting-up screen and `read_onboarding_status` render steps a personas run
does not have), and the `POST /onboarding` 409 `onboarding_in_progress` query does the same — a
personas run must not hold the workspace's one start slot.

### The grant (skill v23, profile v46, recipe v24)

`stage0-interview@v23` pins both tools and teaches them in prose: §1 names the `inputs/project/`
files, §3's outcomes, §5's *Revised* bullet, new **§5b "Author a profile"** (write the document,
choose `brand` vs `project` scope, name `derived_from_icp_key`, then open the confirmation gate —
authoring never confirms) and **§5c "Personas for a confirmed profile"**, and §10.
`head-of-abm@v46` pins skill v23 and the two tools; `recipe0-stage0-v24.json` admits both addresses
at all four sites; `CONVERSATION_RECIPE_VERSION = 24`;
`PROJECT_CONVERSATION_AGENT_PROFILE_ID = "head-of-abm@v46"`. Both tools are on
`STAGE0_CONVERSATION_TRIAL_SURFACE.withheld_tools` — this is a project-conversation capability.
v22 / v45 / `recipe0-stage0-v23.json` are byte-untouched.

### Standing-rule checklist (`_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`)

Run at this stage, all seven answered:

1. **Profile grants** — v46 pins no readiness / Stage-0 / Client-KB / Product-KB tool; the two
   added pins are the new-lane authoring pair. ✔
2. **Gate source** — untouched; neither new tool calls `compile_client_knowledge_card_v2`,
   `current_kb_version` or `load_pinned_client_knowledge` (grepped). ✔
3. **Scope pin content** — both tools resolve `_presenting_turn_project_pin` from the trusted
   `source_turn_ref`; no Client-KB pin, no new `AgentTurnScopePinConflict` path. ✔
4. **Context composition** — a project document is a read-only materialized `.md` on the lease plus
   an index row; no card compiler runs. ✔
5. **Launch path** — `launch_arv2_account_research` gained no precondition; the authoring pair is
   additive. ✔
6. **Static guard** — `tests/arv2/test_import_guard.py` green, `lint-imports` 26 kept / 0 broken. ✔
7. **`.env.example` posture** — unchanged; no new flag (`author_icp_document` needs none,
   `request_persona_synthesis` rides `onboarding_v2_enabled`). ✔
