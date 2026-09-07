# ARV2 D2 — the display module (claims → the three pages a marketer reads)

Date: 2026-09-07 → 2026-09-08. Branch `track-d2`, worktree `managua`, base `602a2dac5` (the D1 +
O1 join `3742d1281a10` merged). Plan:
`docs/superpowers/plans/2026-09-07-arv2-d2-display-module.md`. SDD ledger:
`.superpowers/sdd/2026-09-07-arv2-d2-display-module/progress.md`.
Spec: `docs/specs/ARV2-MASTER-PLAN.md` §7 + `docs/specs/ARV2-DATA-SOURCE-MAP.md` §4, work-split
A4 (machinery) / S4 (recipes + prompts, Shashank's content). Operating rule: implementers were
Opus subagents; every review was the controller's own, first-hand (founder memory 2026-09-02).

After D2 the lane can turn stored claims into the three pages — account **overview**, **insights**,
and a **contact page** — one Luna call per section, all sections of a page in parallel, every
sentence carrying the claim ids it used, and a `display_block` row per section so a second visit
costs nothing. **No migration:** `display_block` and `display_section_recipe` are D1 tables.

## What landed, per task (commit shas)

Base for the plan: `f6143910d`.

| Task | Commit | What |
|---|---|---|
| 1 | `401add8a1` | The four `Settings` fields + `.env.example` lines (`CLUE_ARV2_DISPLAY_MODEL` / `_TIMEOUT_S` / `_MAX_PARALLEL` / `_CLIENT_PITCH`); `display/recipes.py` — `SectionRecipe`, the 17 `SYSTEM_RECIPES` (3 restricted, bare h1s), `RECIPE_VERSION`, `recipes_for`, the upsert seeder `load_display_recipes` and the workspace-override reader `read_recipes`; wiring through `arv2_wiring.RESEARCH_PACK_LOADERS`. |
| 2 | `9c4a0da3d` | `display/prompts.py` — `SYSTEM_PROMPT` (stable prefix, the three fixed lines, the output shape), the 17 `SECTION_INSTRUCTIONS`, `build_messages`, `RESPONSE_FORMAT`, the regenerate line; `display/render.py` — `render_value_text`, `DisplayClaim`, `alias_table` (`c1…cN`), `dedupe_near_duplicates`. |
| 3 | `efa08b27f` | `display/gather.py` — `resolve_subject`, `client_context`, `committee_members`, `gather_section_inputs`: one read of the subject's **live** claims, three counted exclusions (sensitive never, unsafe outside restricted, unverified tier-4 under a verifying posture), per-subject dedupe. |
| 4 | `f346b2b81` | `display/runner.py` — `LunaSectionRunner` (one call per section, retried once on an unusable reply), the tolerant reply models, the pure `materialise`; `display/floor.py` — `check_floor` / `forbidden_aliases_for` / `apply_floor` and the flag-gated `verbatim_annotations`. |
| 5 | `71e326f9e` | `display/blocks.py` — `block_body`, `live_blocks`, `insert_block`, `supersede_blocks`, the recipe-scoped `stale_sections` (5 reasons), `compose_display_block`, `insight_summary`; `display/evidence.py` — `EvidenceRef`, `resolve_evidence`, `evidence_for_ids`, `source_domain`, `favicon_url`. |
| 6 | `63ce6041c` + fix `c51de3e59` | `display/page.py` — `ensure_page` (decide → write concurrently under a semaphore → persist sequentially on the one connection), `default_runner_factory`, `record_page_written`, `PageResult`; `scripts/generate_arv2_display.py`. The fix adds `PageResult.failed`: a section whose reply was unusable twice is reported, **not** persisted. |
| 7 | `edc10997a` (live test), this note's commit (records) | `tests/arv2/display/test_display_live.py`, the real generation of the three Zafran pages, the README section, the two spec notes, this note. |

## Rulings taken during execution (from the SDD ledger, in order)

1. **Pre-flight defect (minor):** `floor.forbidden_aliases_for` needs the alias map the draft was
   written under, and `SectionDraft` had no field for it. Ruling: add
   `SectionDraft.aliases: Mapping[str, str]` to the T4 interface. Cost if wrong: one field.
2. **Pre-flight:** seeding recipes through `RESEARCH_PACK_LOADERS` is a pragmatic reuse of the
   composition-root seam — recipes are registry-like config data. Cost if wrong: a rename.
3. **Recipe content (S4) and the prompts are Shashank-owned content.** Surface both verbatim to the
   founder at close-out; controller approval is not content sign-off.
4. **(T2) Near-duplicate containment is TOKEN-SET containment (`left <= right`), not substring.**
   The brief's prose and its own test disagreed and the test is the binding one: a terse same-field
   claim whose every token appears in a fuller same-field claim folds into the fuller one, so no
   fact is lost from display. The dropped→kept map is recorded in `checks`.
5. **(T2 note carried to T4/T6)** the regenerate call must reuse the SAME `SectionInput`, so the
   alias table is byte-identical and the forbidden aliases still name the claims the first draft
   cited.
6. **(T3) Dedupe folds WITHIN one subject** (person or account), never across two people — two
   committee members sharing a certification must both keep their row. Strictly safer.
7. **(T3) With a coverage row, committee members are served even when the store holds no claims for
   them** — research finalization is authoritative; the writer simply has no rows yet. Not an error.
8. **(T4 carried to T6, two items):** (a) `SectionDraft.cost` is the LAST attempt's `CallCost`, so
   page spend is taken from each runner's `caller.totals()`, never by summing `draft.cost`; (b) the
   `floor.verbatim_annotations` docstring named the wrong flag (`arv2_display_verbatim_check`); the
   real one is `settings.evidence_verbatim_check`.
9. **(T5) `evidence_for_ids` stays on LIVE claims** (`include_superseded=False`). A DSAR tombstone
   is a supersession by a redaction row, so returning superseded evidence would re-surface erased
   personal text. A stale-served block whose citation was superseded shows no chip until
   regeneration — the safe direction.
10. **(T6, from a controller finding) a `reply_invalid` draft is NOT persisted.** Storing its empty
    body would turn a transient provider failure into a section that reads blank on every later
    visit until something made it stale. It is reported in the new `PageResult.failed` (and in the
    CLI report), excluded from `generated`, and retried naturally as a missing section next time.
11. **(T6) The floor is defence-in-depth.** `gather_section_inputs` already withholds unsafe rows
    from non-restricted sections, so `floor_regenerated` cannot be True through `ensure_page` on
    real inputs; the regenerate path is proven by a direct unit test over a hand-built unsafe
    `SectionInput`. The plan's `is True` assertion was a plan defect.
12. **(T6, recorded not changed)** `force=True` retires blocks *before* the calls, so a section that
    then fails twice has no live block until the next call. Acceptable — `force` is an operator
    action.

The plan's own twelve decisions are reproduced (condensed) in
`platform/api/clue_api/arv2/README.md` § "D2 — the display module".

## The live exit gate

`tests/arv2/display/test_display_live.py` — one test, one page (Nick Fisher's contact page, five
sections), real gateway, real D1 answer key, inside `rollback_conn(seed_pack=False)` so nothing
persists. It skips (never fails) when `CLUE_OPENROUTER_API_KEY` is blank/unset or when the answer
key is not in the database (the inverse of `test_answer_key_loader_db._skip_if_already_loaded`).
It asserts: `failed == ()`; every section generated or honestly empty and every generated section
non-empty; every `claimIds` entry a uuid with an evidence card behind it; `cited_flags` all true in
every non-restricted block **and** no unsafe-evidence id cited outside the restricted section;
every `openers` item carrying a `sendLine`; no `http` and no `c<N>` alias in any `h2`/sentence;
`cost_usd > 0`; and `result`-phase ledger rows with `cost_source == "metered"`.

Ran once, green. Five metered OpenRouter calls, **$0.01339** total (13.3–20.6 s each, all HTTP 200).

## The real generation (persisted, worktree DB `postgresql+asyncpg://clue:clue@localhost:55060/clue`)

```
uv run python scripts/generate_arv2_display.py --database-url ... --account zafran.io --page all
uv run python scripts/generate_arv2_display.py --database-url ... --account zafran.io --contact "Nick Fisher"
```

| Page | cost_usd | generated | skipped_empty | failed | stale_served | evidence |
|---|---|---|---|---|---|---|
| overview | 0.01503660 | all 6 | — | — | — | 40 |
| insights | 0.01698680 | all 6 | — | — | — | 36 |
| contact | 0.00614466 | all 5 | — | — | — | 21 |

`total_cost_usd` 0.03202340 (account command) + 0.00614466 (contact command) = **$0.0382** for 17
sections. The contact page cost less than half the live test's identical five sections — the stable
prompt prefix is being cached provider-side, which is exactly what it was shaped for.

Section × cited claims × items (`display_block`, `superseded_at IS NULL`; every
`floor_dropped_items` is absent, i.e. the floor never fired):

| page | section | cited | items |
|---|---|---|---|
| contact | why-this-person / problem-right-now / openers / angles / do-not-mention | 5 / 4 / 3 / 3 / 10 | 3 / 4 / 3 / 3 / 10 |
| insights | buying-signals / money-and-momentum / tools-they-already-use / how-they-sell / contact-insights / context-only | 4 / 6 / 3 / 4 / 11 / 8 | 4 / 3 / 3 / 2 / 5 / 8 |
| overview | what-they-do / why-they-fit / why-now / buying-committee / how-to-approach / watch-outs | 11 / 8 / 3 / 15 / 9 / 8 | 0 / 6 / 3 / 5 / 5 / 8 |

(`what-they-do` is a narrative section: 0 items, 2 `intro` sentences over 11 claims. `why-they-fit`
is narrative too and produced 1 intro sentence + 6 items with `fitDisposition` set.)

**The A4 exit gate.** The SQL that counts unsafe claims cited outside a restricted section printed
**`0`**:

```sql
select count(*) from display_block b
  join lateral unnest(b.cited_claim_ids) c(id) on true
  join claim on claim.id = c.id
 where b.superseded_at is null and claim.outreach_safe = false
   and b.section_key not in ('context-only','watch-outs','do-not-mention');
```

**Checks worth recording.** Across all 17 sections: `unknown_aliases` **0**, `off_recipe` **0**,
`uncited_sentences` **0**, `segments_dropped` **0**, `reply_retried` **false** everywhere,
`reply_invalid` **false** everywhere, `floor_regenerated` **false** everywhere, `model_said_empty`
**false** everywhere. The only non-zero counter is `unresolved_refs`: `insights/context-only` **3**
and `insights/how-they-sell` **4** — the model put names in `contactRefs` that resolve to no
committee member; they are dropped and counted, exactly as designed.

Three `account_activity_event` `summary` rows were written (`Overview written` / `Insights written`
/ `Contact page written`), the contact one carrying `ref_json = {"contact_id": …}`.

## The copy, read once (honest notes — nothing was tuned)

The copy is good: every date is in words ("2 December 2025", "17 June 2026"), no url and no alias
appears anywhere, every contact-page item carries a paste-ready `sendLine`, the restricted sections
say what must not be used and why, and the insights sections close with "What it means for us: ".
Four things worth carrying forward, none of them an exit-gate defect:

1. **The same personal hook is reused across two sections of the contact page.** `openers` and
   `angles` both build on Nick's 96%-of-vulnerabilities post and on the Black Hat comic-store post.
   `FIXED_LINES[2]` ("use the personal-hobby hook at most once per page") is unenforceable per call
   because the sections run in parallel — this is the already-recorded D3/D4 follow-up, now observed
   live. Strictly the rule was not violated (neither claim is `contact.facet.hobby`), but the effect
   the rule exists to prevent is visible.
2. **An outreach-safe claim can be about the same subject an unsafe claim forbids.** `angles` built
   a direct-mail item from `contact.facet.publications` (`outreach_safe = true`) whose evidence span
   is Nick's post about publishing his *Cocktail Chemistry* book — while `do-not-mention` correctly
   says not to use the Cocktail Chemistry hobby as a hook. The model did not name the book, so
   nothing leaked; the observation is that display safety is exactly as good as `outreach_safe`, and
   the answer key holds a safe/unsafe pair about one subject. R-side data question, not a D2 defect.
3. **The model sometimes quotes our own rendered value as if it were a source quote** — e.g.
   `"open_reqs_total: 27; published_last_30_days: 9; published_last_7_days: 4"` in
   `insights/buying-signals`. It is accurate and cited; it just reads like machinery. A prompt nit
   for the S4 content owner.
4. **The restricted sections contain near-duplicate items** (the Snir Havdala departure and the
   ARR/cash-burn report each appear twice in `watch-outs` / `do-not-mention` / `context-only`),
   because the answer key holds two claims about each. The D1 note already records that
   near-duplicate unsafe rows were deliberately left in the data; the dedupe folds *within* a field
   key, and these are two different field keys.

## Test-suite state

- **Wider offline pass #1** (ledger, after T5/T6, non-display suites, provider keys unset,
  `--ignore-glob='*_live.py'`, log `.artifacts/d2-wider-pass-1.log`): 507 passed, 2 failures, both
  attributed and neither D2 —
  `tests/claimstore/test_merge.py::test_empty_when_no_eligible_claim` (the documented 12th known red
  under the R0 `.env` posture) and `test_batch_scales_to_1k_entities` (it counts **all** claims on
  `account.recent_funding` with no workspace filter; this worktree DB carries the committed answer
  key's 5 such rows → 1005 ≠ 1000; a data-state artefact of the loaded DB, green on a clean one).
- **Close-out pass** (Task 7, same command, log `.artifacts/d2-closeout-pass.log`): **600 tests —
  596 passed, 2 skipped, 2 failed**, the two failures being exactly the two above and nothing else.
  The 93-test display suite is the difference from pass #1 and is entirely green.

## Close-out gate

| Gate | Result |
|---|---|
| `pytest tests/arv2 tests/claimstore tests/db/test_arv2_d1_migration.py tests/narrative/test_positioner.py -q --ignore-glob='*_live.py'` | 596 passed / 2 skipped / 2 failed — both pre-attributed, nothing new |
| `ruff check . --statistics` | **9** findings (4 F401, 2 I001, 2 SIM300, 1 E501) — the documented baseline, none in D2 files |
| `ruff format --check .` | the 10 documented pre-existing unformatted files, none in D2 files |
| `mypy` | the one pre-existing `subsystems/design/clue_design/ad_assets.py:149`, 769 files checked |
| `lint-imports` | 26 contracts kept, 0 broken |
| `alembic heads` | one head, `3742d1281a10` — D2 adds no migration |

## Standing-rule checklist (`_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`, items 1–7)

D2 is a read-and-render module with no agent, no turn and no gate, so the relevant facts are
negative ones — and they were checked, not assumed. `grep -rn` over
`platform/api/clue_api/arv2/display/` returns **zero** hits for `client_knowledge`, `readiness`,
`stage0`, `display_allowed`, `product_id`, `ClientKnowledgeCard` and `current_kb_version`.

1. **Profile grants** — n/a: D2 grants no tool and touches no profile.
2. **Gate source** — n/a: D2 opens no gate. The only human-authority coupling is that a page is
   written on request, never ahead of it.
3. **Scope pin content** — n/a: D2 writes no scope pin and reads none. It never reads
   `project_run`, so a Stage-0 pin cannot refuse a page.
4. **Context composition** — n/a: no Client-KB card compiler is reachable from the module (zero
   `client_knowledge` hits). `client_context` reads the workspace's brand name and one setting.
5. **Launch path** — untouched: `launch_account_research` gained no precondition.
6. **Static guard** — green: `tests/arv2/test_import_guard.py` walks the whole `clue_api/arv2`
   tree, `display/` included, and it passes in the close-out run.
7. **`.env.example` posture unchanged** — `CLUE_SELF_SERVE_PROVISIONING_ENABLED=false` (line 121),
   `CLUE_STAGE0_OFFICIAL_SITE_CRAWL_MODE=off` (line 91),
   `CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED=false` (line 345). D2 added only the four
   `CLUE_ARV2_DISPLAY_*` lines.

No item fails.

## Follow-ups for D3/D4

- **D3 wires the module.** `ensure_page` behind E2 (overview), E3 (insights) and E5 (contact
  profile); `evidence_for_ids` behind the shared `ResearchEvidence` read (source map §3.9);
  `insight_summary` for the insights header count. **Regeneration must run in the background** —
  master plan §7's policy is to serve the persisted block and regenerate the stale sections behind
  it; `stale_sections` + the `regenerate_stale` flag are the seam, the driver is D3's.
- **`arv2_display_allowed` is still unbuilt** (carried from D1). The display gate ruling S10's
  read-time relaxation has no implementation; today's reads use the older `display_allowed` posture.
  D3 owns it.
- **The page-level hobby/personal-hook annotation.** `FIXED_LINES[2]` cannot be enforced per call
  (sections run in parallel). A page-level check counting hobby/personal-facet claim citations
  across a page's sections — an annotation, not a blocker — is the fix; observed live (copy note 1).
- **`record`-kind evidence has no URL to open.** Of the **61** distinct claims cited across the
  three generated pages, **37** have no `source_url` (27 of those are `record` kind:
  `extraction_method = api AND source_url IS NULL`) and **25** have no `evidence_span`, so their
  card falls back to `researchExcerpt`. The frontend's "Sources" panel and the inline chip must both
  render a record honestly (lock + "Record", no link) rather than assuming a domain exists.
- **`unresolved_refs` needs a home in the UI or the prompt.** Two insights sections named people the
  committee does not contain; the refs are dropped silently from the payload. Either the section
  instruction should say "name only the people listed", or the annotation should surface to an
  operator.
- **The two S4 content files still need the founder's content sign-off** —
  `display/recipes.py` (the 17 recipes) and `display/prompts.py` (the system prompt and the 17
  section instructions). Controller review covered mechanics only (ledger ruling 3).
- **`prompts.py` nits from the live copy** — discourage quoting a rendered field payload as if it
  were a source quote (copy note 3).
- **Verification posture.** Everything above was generated with `CLUE_VERIFICATION_ENABLED=false`.
  With it on, two of the five Zafran `contact.role_on_committee` rows are unverified tier-4
  synthesis and the committee reads three, not five (D1 note). D3 must not assume five.

## Controller close-out attestation (2026-09-08)

The Task-7 Opus implementer was cut off by the Opus session rate limit immediately after writing its
report; every deliverable (live test, the three persisted pages, the records) had already landed.
The controller (Fable) then re-ran the whole close-out gate first-hand and got the same numbers:
596 passed / 2 skipped / 2 failed (the two pre-attributed non-D2 reds), ruff 9 findings (baseline),
10 pre-existing unformatted files, mypy's one pre-existing `ad_assets.py:149`, lint-imports 26/0,
one Alembic head `3742d1281a10`. Whole-branch checks: 10 commits `f6143910d..6a682d596`, 32 files,
+7754/−2; nothing under `.artifacts/` tracked; no key material in the branch diff. Independent copy
scan of the persisted pages (231 sentences): 0 aliases, 0 URLs/domains, 0 numeric dates in prose;
SQL leak check 0.

Founder items to review (content, not code): `display/recipes.py` (the 17 recipes) and
`display/prompts.py` (system prompt + 17 instructions) are Shashank's S4 content and were written by
the agent under the plan; the four copy-quality notes above are theirs to act on.
