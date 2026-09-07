# ARV2 D1 — the display substrate, the lenient claim writer, and the answer-key loader

Date: 2026-09-07. Branch `track-D`, worktree `managua`. Plan:
`docs/superpowers/plans/2026-09-07-arv2-d1-migration-and-answer-key-loader.md`. SDD ledger:
`.superpowers/sdd/2026-09-07-arv2-d1-migration-and-answer-key-loader/progress.md`.
Spec: `docs/specs/ARV2-MASTER-PLAN.md` v1.6 §4/§9 (Track D, D1) + `docs/specs/ARV2-DATA-SOURCE-MAP.md`
v1.1 §2.2. Operating rule: implementers were Opus subagents; every review was the controller's own,
first-hand (founder memory 2026-09-02).

After D1 the database can hold ARV2 research, the claim store has a write path that stores instead
of refusing, and the Zafran and ten-person answer keys are real rows in Postgres with entities,
lineage, committee coverage and media artifacts behind them.

## What landed, per task (commit shas)

Base for the plan: `2c9b17063`.

| Task | Commit | What |
|---|---|---|
| 1 | `284efdf77` | Alembic revision `65fb2128c904` — the whole D1 substrate in one reversible migration: `claim.signal_priority` / `.outreach_safe` / `.write_markers`, `account_entity.owner_user_id` / `.created_by_user_id`, `workspace_field_definition.presentation`, tables `display_block`, `display_section_recipe`, `provider_call_ledger`, `account_activity_event`, plus the persona-vocabulary data-fix (three `field_definition.value_schema` rows rewritten so a reloaded pack does not raise `FieldRedefinitionError`). Also the five leniency/check flags as `Settings` fields + `.env.example` lines. |
| 2 | `e600cd08c` | Frozen-`clue_core` contract delta: `Claim` gains `signal_priority`, `outreach_safe`, `write_markers`; the source-URL rule moves from construction to `can_be_promoted`; `Persona` gains `user`; `claimstore/claims.py` insert/select the three columns (34-column insert). |
| 3 | `d02cffd7a` | `platform/api/clue_api/arv2/catalog_seed.py` — `ARV2_PACK`, 38 field rows (35 answer-key keys + 3 keys the section recipes need), no overlap with the CORE / DEEP_PROFILING / COMMITTEE packs; `platform/api/clue_api/arv2_wiring.py` appends the loader to `clue_api.composition.RESEARCH_PACK_LOADERS` (wired at `fleet_main` + `projections_main`, unconditionally — packs load under either flag). |
| 4 | `85419c0ea` | `arv2/claim_writer.py` — `ClaimDraft`, `WriteReceipt`, `LenientClaimWriter`. Stamps tier from method (`TIER_FOR_METHOD`), tenant-private scope, facet governance defaults; marks `schema_valid=false`, `proposed_field`, `source_missing`, `identity_binding_defaulted`, `use_class_defaulted` instead of refusing. `lenient=False` restores the strict refusals. |
| 5 | `2b661f176` | `arv2/answer_key.py` — pure mapping, no DB: 169 Zafran drafts (5 skips) + 122 person-depth drafts, the persona map, bundle map, priority table, media wrap, pipe-joined-key split, and the deterministic run ids off `ANSWER_KEY_NAMESPACE`. |
| 2 fix | `b4ce86e2d` | Follow-on from the wider pass: `Persona.USER` gets its own `ANGLE_TEMPLATES` entry (daily-operator angle) in `narrative/prompts.py` and a `DEFAULT_FIELD_RELEVANCE` entry in `narrative/policy.py`. |
| 6 | `aab0c7445` | `arv2/answer_key_loader.py` + `scripts/load_arv2_answer_key.py` + `tests/arv2/test_answer_key_loader_db.py`. The real load: 294 claims, spine, entities, lineage ×2, three transcript artifacts, terminal research rows, six activity events. |
| 7 | `a25132d82` (fixes), see below (records) | Close-out: the deferred minors, this note, the README section, the two spec pointers. |

## Rulings taken during execution (verbatim from the SDD ledger, in order)

1. `| T5, T6 | unsafe-row assertions said 12 / 12+1 | DEFECT: zaf-132 is unsafe AND NOT FOUND → skipped. Ruling: corrected to 11 / 11+1 (plan amended, commit above) — cost if wrong: one test number |`
2. `Ruling (founder, 2026-09-07 evening): no wide/full API suite per task. Per-task = focused tests only. One wider run after Task 3 (migration half), one after Tasks 4–6 (loader half). Applies to Task 2 (message sent) and every later dispatch. Cost if wrong: a cross-task regression surfaces one checkpoint later, never unreviewed.`
3. `Task 2: FINDING (from wider pass, Important): tests/narrative/test_positioner.py::test_all_personas_have_distinct_angle_labels — Persona now has 5 members, ANGLE_TEMPLATES has 4, and angle_for(USER) falls back to the economic-buyer label. Ruling: add a real USER entry to narrative/prompts.py ANGLE_TEMPLATES (daily-operator angle) and to narrative/policy.py DEFAULT_FIELD_RELEVANCE, not relax the test — cost if wrong: one prompt template nobody composes in v1. Fix round queued after Task 5 (implementers stay sequential).`
4. `Ruling (Task 6 input): contact_eligibility.py:512 drops a member unless BOTH contact.persona and contact.role_on_committee resolve. Only Sanaz (zaf-165) and Tom (zaf-166) carry role rows. The loader writes a derived role claim for each committee member that has a persona but no role: value {"role": <persona>, "rationale": "<current title> — role derived from the committee persona recorded by the name-scoped AI Ark lookup", "plausible": true}, same provenance as the persona row (extraction api, source_key ai_ark, STRONG, professional-public, source_url None → source_missing), markers {"derived_role_from_persona": <persona source_row_id>}. Mechanical and marked, not invented. Cost if wrong: three annotated rows to supersede.`

## The twelve decisions the plan took (each is overturnable by the founder)

1. **Where the write markers live.** The master plan names the markers but gives them no column. They live in a new nullable `claim.write_markers jsonb`, written once at insert, mutable in place — write-time annotations, not provenance.
2. **A claim may exist without a source URL.** The rule moved from construction to promotion: `Claim` accepts a missing URL; `can_be_promoted` returns `False` when a URL-requiring method has no URL. Nothing verified today has no URL, so no existing row changed meaning.
3. **`Persona` gains `user` with no DDL**, because `persona` is not a Postgres enum — it is an `enum` list inside three registered value schemas. The migration rewrites those `field_definition.value_schema` rows so an already-migrated database does not raise `FieldRedefinitionError` when packs reload.
4. **Persona mapping for the Zafran committee.** `executive_sponsor` → `economic_buyer` (Sanaz Yashar, CEO); `adjacent_buyer` → `user` (Tom Anthony, SVP Global Sales). The malformed duplicate persona row `zaf-164` is skipped as a duplicate of `zaf-039`.
5. **Priority for the Zafran account run.** All 174 rows carry `priority: null`; the loader stamps priority from a field-key table, not from a model. The ten-person rows keep their own P1/P2/P3.
6. **`NOT FOUND` rows are not claims.** Four Zafran rows (`zaf-130`…`zaf-133`) carry the string `NOT FOUND…`. They are reported as `not_found` skips and never written — empty is the correct output.
7. **Deep-dossier sources have no URL.** `SOURCE A` is the Exa deep-reasoning dossier (no URL → `source_missing`); B is `https://www.zafran.io/`; C–F are the podcast, two videos and Nick's article. A multi-source label resolves to the first label that has a URL.
8. **Media rows carry their media fields inside `value_json`** — `{"text": …, "media_url": …, "media_timestamp": …}` — so the source map's `value_json.media_timestamp` read works. Where the registered schema is a plain string this sets `schema_valid=false`, which is the lenient contract.
9. **Every ARV2 claim is `tenant_private` with a workspace id.** Accounts are workspace-local (founder ruling 2026-07-22); a claim more private than its field is always allowed, so the writer never hits `ReuseScopeError`.
10. **Identity binding for the Zafran rows** (which carry none): `STRONG` when `source_kind` ∈ {`provider_database`, `transcript_self`, `company_primary`}, else `WEAK`. The ten-person rows keep their own `STRONG`.
11. **The three non-Zafran companies** (Cogent Security `cogent.com`, Harmonic Security `harmonic.security`, UPTIQ `uptiq.ai`) get account entities, project membership and contacts, but no research run, job or committee coverage — their status is honestly `not_started`.
12. **The loader is one-shot per database**, keyed on a deterministic run id; a second run refuses with `AlreadyLoaded` rather than duplicating rows.

## The real load

Database: the worktree's throwaway Postgres, `clue-pg-managua` container,
`postgresql+asyncpg://clue:clue@localhost:55060/clue`. Command:

```
uv run alembic upgrade head       # 65fb2128c904
uv run python scripts/load_arv2_answer_key.py \
    --database-url postgresql+asyncpg://clue:clue@localhost:55060/clue
```

(`--dry-run` first; the dry run and the real run reported identical bodies apart from the minted
entity ids.) Report of the committed run:

- `run_id` `6ac1cbd7-9137-5752-a1aa-45cb23b7af64`, `workspace_id` `ws_arv2_answer_key`,
  `project_id` `prj_arv2_answer_key`.
- **`claims_written` 294** = (174 − 5 Zafran) + 3 derived roles + (119 + 3 person-depth). Per run:
  Zafran 172, people 122.
- **Markers:** `answer_key` 294 · `source_row_id` 291 · `schema_valid` 129 · `source_missing` 129 ·
  `company_domain` 122 · `pipe_joined_key` 6 · `derived_role_from_persona` 3 ·
  `proposed_field_origin` 3. `proposed_field` is **0** and `registered_fields` is empty — the Task-3
  pack already registers every key both answer keys use.
- The two 129s are coincidence, not a bug: only 32 claims carry both markers. `source_missing`
  by method is api 98 / scrape 22 / llm_synthesis 9, which matches the source files exactly.
- **Skips (5):** `zaf-130`, `zaf-131`, `zaf-132`, `zaf-133` `not_found`; `zaf-164`
  `duplicate_persona`.
- **Accounts (4):** zafran.io, cogent.com, harmonic.security, uptiq.ai. **Contacts:** 12.
- **Artifacts (3):** the transcript blobs (44707 / 3224 / 5338 bytes) under
  `ws_arv2_answer_key/<sha256>`; 21 claims cite one via `artifact_key`.
- **Terminal research rows:** `entity_research_run` + `entity_research_job` (`terminal`,
  `completed`) + `entity_research_account_coverage` (5 members, `complete`, 42
  `completed_field_keys`, 172 claim refs) + the `entity_research_account_fleet` row the committee
  read resolves the run through.
- **Activity feed (6):** Zafran `created` / `updated` / `contacts`, plus `created` for the other
  three accounts.
- **Governed committee read against the committed database:** 5 members — Vari Kaur `champion`,
  Sanaz Yashar `economic_buyer`, Nick Fisher `economic_buyer`, Ben Seri `technical_evaluator`,
  Tom Anthony `user`. `outreach_safe = false` on 12 rows.

## Test-suite state (two wider passes, run outside this worktree)

**The suite is `.env`-file sensitive.** `pydantic-settings` reads the worktree `.env`, so the
posture in that file (verification off, `CLUE_SCRAPE_BACKEND=scrapling`, memory off, …) changes
test outcomes. **Run the suite from a checkout with no `.env`, or with the posture unset** —
otherwise 10 tests fail purely because of the ambient file and look like regressions.

Triage of wider pass #1 (HEAD `2b661f176` vs base `a778cf45e`, same 77 failing ids):

- **1 genuine D1 regression** — `tests/narrative/test_positioner.py::test_all_personas_have_distinct_angle_labels`, caused by `Persona.USER`. Fixed in `b4ce86e2d` (a real USER angle template, not a relaxed test).
- **37 fail identically at base in isolation** — reproducible pre-existing. This set includes the documented 11 known reds.
- **28 fail only in the full run** — ordering / dirty shared DB: source-manifest redefinition in the waterfall tests, "cannot downgrade M8D R2 while entity_research_job fleet tasks exist" in the three db_migrations tests, recipe0, etc. Not attributable to any change.
- **10 fail at head only because pydantic-settings reads the worktree `.env`** — all 10 pass from a clean head checkout with no `.env`.
- **1 live AI Ark credit test** (402 / missing key) — known.

**The known-red list is now 12, not 11:** add
`tests/claimstore/test_merge.py::test_empty_when_no_eligible_claim`, red under the R0 `.env`
posture (`CLUE_VERIFICATION_ENABLED=false` serves a lone tier-4 claim). Proven pre-existing.

Wider pass #2 (after Tasks 4–6) ran from a clean checkout `/tmp/d1-head` @ `aab0c7445` with no
`.env` against a fresh `clue_suite` database; it is the honest baseline for the next lane.

## Close-out gate (Task 7)

`ruff format --check` — the 10 documented pre-existing unformatted files, nothing new.
`ruff check . --statistics` — **9 findings, back at the documented baseline**: `.context` is now in
ruff's `extend-exclude` (the ~1,680 extra findings were all the merged proof-of-concept scripts
under `.context/`, which are evidence, not code). `mypy` — the one pre-existing
`subsystems/design/clue_design/ad_assets.py:149`. `lint-imports` — 26 contracts kept, 0 broken.
`alembic heads` — one head, `65fb2128c904`. Focused tests
(`tests/arv2 tests/db/test_arv2_d1_migration.py tests/claimstore/test_arv2_claim_columns.py
tests/narrative/test_positioner.py`) — 357 passed, 25 skipped, 1 failed, the failure being the known
live-provider aggregate `test_ai_ark_client_live.py::test_every_call_was_paced_and_ledgered_at_its_result_count_price`
(its six live calls skip for a missing key, then the aggregate asserts `0 == 6`).

**`make db-smoke` cannot run against a database that carries the answer key**, and this is a
data-state fact, not a D1 defect. The downgrade of the pre-existing revision `99923d6527c3` →
`a1c5b9842f0e` ("widen account coverage field axis to core fields") re-narrows the coverage field
axis, and the loaded `entity_research_account_coverage` row's `completed_field_keys` legitimately
contain 20 `core.*` keys, so the narrower CHECK cannot be re-added. Same class as the already
documented "cannot downgrade M8D R2 while entity_research_job fleet tasks exist". The whole
downgrade runs in one transaction, so the failure rolls back cleanly and the loaded data survives
untouched. **Run db-smoke on a clean throwaway database**, which is the repo convention anyway:

```
CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:55060/clue_d1_smoke make db-smoke
```

That is green (up → base → up).

`tests/arv2/test_answer_key_loader_db.py` **skips loudly** on a database that already carries the
key ("this test needs a database without it"). Expected; it was proved green on a clean database.

## Follow-ups for D2/D3

- **`render_value_text` reads `text` on media-wrapped values.** Decision 8 puts media rows'
  values inside `{"text": …, "media_url": …, "media_timestamp": …}`. Whatever renders a claim value
  for display must read `.text` on such a value rather than stringifying the object. D3.
- **`arv2_display_allowed`.** The display gate D3 owns (master plan ruling S10's read-time
  relaxation) is not built; today's reads use the older `display_allowed` posture.
- **`record` evidence is `extraction_method='api' AND source_url IS NULL`.** The source map's
  evidence rule now matches 98 real rows in the answer key (89 `ai_ark`, 6 `ashby_posting_api`,
  2 `gemini`, 1 `exa_contents`). The evidence hover must treat these as record-cited, not URL-cited — there is no URL and
  no snapshot behind them.
- **Dedupe of near-duplicate unsafe rows is not done.** The master plan's "one fact, one flag"
  dedupe is deliberately left to D2's recipe input filter; the control test's two duplicate cases
  stay in the data as the worked example.
- **`schema_valid=false` on 129 of 294 claims** is honest lenient-gate behaviour (free-text
  answer-key values against typed registered schemas), but it is a large fraction and the display
  layer will meet it.
- **With verification on, the Zafran committee reads three, not five.** Two of the five
  `contact.role_on_committee` rows are the run's own tier-4 synthesis and are unverified, so
  `active_merge_policy`'s `require_verified_tier4` gate hides them. The shipped posture is
  verification off (`.env.example`: `CLUE_VERIFICATION_ENABLED=false`), which is what the D1 test
  pins explicitly. D2/D3 must not assume a five-member committee without that posture.
