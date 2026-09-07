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
the catalog sync, then the synthesis turn — through the `SynthesisLauncher` seam O4 fills — running
alongside the capped per-product background fan-out (`onboarding_max_parallel_runs`).

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

### The step graph

One `onboarding_run` task is one run, in this order:

```
  mark_run_running          overview ────────────────┐        synthesis ──────────────┐
  + bind the client  ─→     lineup ─→ catalog_sync ──┼─→                              ├─→ finish_run
                            reviews ─────────────────┘        product_research ×N ────┘
                                    (fast lane, concurrent)      (background, capped)
```

The fast lane runs its steps concurrently; the lineup's two passes are merged and handed straight
to `catalog_sync` inside the same step branch, which mints or reuses the product rows over the
artifact-keyed `onboarding_product_lineage`. The synthesis turn reads what the fast lane published
and does not wait for the per-product reports, so it runs *alongside* the background fan-out, which
is capped at `onboarding_max_parallel_runs`. `finish_run` settles the run `completed` or
`completed_with_gaps` from the steps' own statuses and sums their cost — a run with a failed or
empty step still finishes, it just says so.

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
- **`SynthesisLauncher`** — O4's `build_onboarding_synthesis_launcher`, supplied at the merge. The
  fleet composes `synthesis=None` until then, and the synthesis step settles `empty` with
  "synthesis agent not composed (O4)" rather than pretending it ran.

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
`LenientClaimWriter`, then the terminal research rows and the activity feed.
`scripts/load_arv2_answer_key.py` is the thin argparse wrapper:

```
uv run python scripts/load_arv2_answer_key.py \
    --database-url postgresql+asyncpg://clue:clue@localhost:55060/clue
```

(`--dry-run` runs the whole load in one transaction, prints the report and rolls back;
`--context-root` defaults to `.context`, `--storage-root` to `.artifacts/answer-key`.) **The load
is one-shot per database**: it is keyed on a deterministic run id, and a second run raises
`AlreadyLoaded` rather than duplicating rows. A database that already carries it must be reset, not
re-loaded.

**Two constraints this places on R2:**

- **R2's `write_claims` goes through `LenientClaimWriter`.** The structuring pass does not build
  `Claim` objects of its own and does not call `insert_claim` directly; the gate is the lane's only
  write path, so the stamping and the markers are uniform whatever produced the fact.
- **The loader's terminal rows are the shape R2's finalization must produce.** The
  `entity_research_run` / `entity_research_job` / `entity_research_account_coverage` triple (plus
  the `entity_research_account_fleet` row the committee read resolves the run through) is what the
  accounts screens read a finished account through. R2's real finalization writes the same rows
  with the same relationships; the loader is the worked example, not a special case.

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

## O4 — the synthesis turn (`clue_api/onboarding_synthesis_wiring.py`)

The step that turns the brand's onboarding research into audience documents. It is **not** in this
package: composing one governed deepagent turn means touching the agent/execution substrate, which
the lane may not import, so the module lives beside the other `clue_api` wiring roots as
`platform/api/clue_api/onboarding_synthesis_wiring.py`. The only piece that lives here is
`knowledge_frontmatter.py` — the inverse of `onboarding_documents.render_markdown`, which reads a
finished output's front matter and answers *what document is this*.

The shape is the account-research unit runner with the account scope swapped for the **brand**
scope. `OnboardingSynthesisLauncher.launch` materializes the brand's current servable knowledge
documents read-only under `inputs/brand/knowledge/`, runs one C5-governed turn inside the promoted
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
  requires. **The catalog copy — `platform/agents/catalog/skills/audience-persona/v1/SKILL.md` — is
  authoritative**: it is the sha-pinned resource the profile carries and the agent actually reads.
  Edit the catalog file; the flat one is a pin stub and says so in its own body.
- **`build_toolbelt(secrets=...)` is fail-closed.** The default `secrets=None` means *no
  credentials*, so `exa_search_evidence@1` registers but refuses `exa_not_configured` before any
  spend — deliberate, so no test toolbelt composes a live billable Exa client off a stray `.env`
  key. A production composition root must pass a real `Secrets` explicitly; `fleet_main` does.
