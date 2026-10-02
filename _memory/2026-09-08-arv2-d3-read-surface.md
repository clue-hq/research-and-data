# ARV2 D3 — the read surface (claims + display blocks → the five accounts-screen payloads)

Date: 2026-09-08. Branch `track-d3`, worktree `managua`, base `16e79c279` (fast-forwarded to
`origin/integration/design-improvement` @ `33ab4fed1` — D2 merged via PR #47, O3/O4 merged). Plan:
`docs/superpowers/plans/2026-09-08-arv2-d3-read-surface.md`. SDD ledger:
`.superpowers/sdd/2026-09-08-arv2-d3-read-surface/progress.md`. Spec: `ARV2-MASTER-PLAN.md`
§6/§7/§8, `ARV2-DATA-SOURCE-MAP.md` §1/§3/§4/§5, work-split A5/§6.2. Operating rule: implementers
were Opus subagents; every review was the controller's own, first-hand (founder memory 2026-09-02).

After D3 the five accounts screens have a backend. D1 gave the lane claims, D2 turned them into
pages; D3 serves both — plus the rail facts, the committee, the evidence drawer and the activity
feed — as five contract-v1 payloads on the existing `/frontend/v1` router. **No migration.**

## The governing ruling (read this first)

**Contract v1 is selected per request with `?contract=v1`.** Without the parameter, E1/E2/E4/E5
serve their FI-2 bodies byte-for-byte; `apps/frontend`, its adapters/models, and the FI-2 route
tests are **untouched by D3**. E3 (`/accounts/{id}/workspace`) is a new route with no FI-2 shape
beside it and serves v1 in both modes. `?contract=v2` (any unrecognised value) is an enveloped 422
everywhere. D4 re-points the adapters to `?contract=v1` and then deletes the FI-2 branches and the
parameter together.

Why: the plan's original shape reshaped the payloads in place, which meant renaming
`researchStatus[]` → `projectResearchStatus` and `projects[]` → `projectMemberships` across 33
usages in 7 frontend files and putting two shapes in every row for one intermediate step. **There
are therefore no FI-2 renames in D3** — those names did not change anywhere, and no `apps/frontend`
file was edited for them. Cost if the ruling was wrong: one query parameter to remove at D4.

## What landed, per task (commit shas)

| Task | Commit | What |
|---|---|---|
| 1 | `213d285fb` | `frontend_read/contract_v1.py` — the five strict pydantic payload models + shared sub-types, `V1_PAYLOADS`; the vendored Zod under `tests/api/contract_v1/zod/` with the ruled D0-a amendments, `validate.ts` (two modes), `zod-fields.json`, `oracle.py`; the contract-v1 section of `apps/frontend/docs/api-contracts/accounts.md` (S2). |
| 2 | `50c6d7bb8` | `frontend_read/v1_shared.py` — `arv2_display_allowed` (ruling S10), the five label maps, fit/bands/labels, `email_facts`, tenure/education/LinkedIn/time labels, `owners_for`, `custom_fields_for`, `last_modified_for` (one CTE), `activity_for`, `research_evidence_for`; three `Settings` fields + `.env.example` lines. |
| — | `5b74a6eb7` | The plan amendment recording the `?contract=v1` ruling above. |
| 3 | `838992cb8` | `app.py::contract_mode` / `ContractDep`; `accounts_list.list_accounts_v1` beside the untouched FI-2 reader (shared `_read_spine_page` / `_next_cursor`), the v1 research-jobs statement with the refresh flag, primary-project fit, bands and labels. |
| 4 | `e9f9794c1` + `2cf9546d2` | `frontend_read/display_pages.py` — `DisplayPages` (never raises at construction), `page()` = `ensure_page(regenerate_stale=False)` inside a degrading try, composed from live rows in both paths, stale → background task keyed per page with dedupe on its own connection, never awaited; `committee` / `buying_committee` / `rail_contacts` over one claims read; `iso_utc` on activity; `secrets` threaded through `app.py` / `projections_app.py`. |
| 5 | `d6010fddf` + fix `675f9f7b1` | E2 `read_account_detail_v1` beside the FI-2 reader (byte-identical FI-2 body): rail, `overviewDisplay`, `buyingCommittee`, `researchEvidence` = page ∪ email claim ids, activity. The fix makes the E7 evidence route authorise with `DisplayPages.page(generate=False)`. |
| 6 | `93f50b1cd` | `frontend_read/account_workspace.py` — E3 end to end: `insightsDisplay`, `insightSummary`, evidence over the page's citations, activity, `insights` / `artifacts` = `[]`. |
| 7 | `cebee647c` | E4/E5 in `contacts.py`: rows = the coverage committee via `committee()`, the rail facts, `contactDisplay`, reports via `reports_to`, evidence = page ∪ email ∪ location; the contact evidence route authorises with `generate=False`. |
| 8 | `82d0f8ebd` (walk) + `1f6ac892d` (the controller's shape fix, see the second finding) + this note's commit (records) | `tests/api/test_frontend_read_v1_live_zafran_db.py` — the Zafran walk; the README/spec/memory records. |

## Rulings taken during execution (from the SDD ledger, in order)

1. **(pre-flight, T1↔T3/T5/T6/T7)** T1's aliases are canonical: the route models import the shared
   sub-types (`ResearchEvidence`, `AccountActivity`, `AccountOwner`, …) from `contract_v1` rather
   than redefining them.
2. **(pre-flight, T1↔T4)** T1 applies the `BuyingCommitteeMember.linkedinUrl: HttpUrl | null`
   amendment **up front** (marked `// D3 ruling` in the vendored Zod) so the oracle is stable from
   T1 onward; T4 does not touch the Zod.
3. **(T1) Where the plan's prose and the Zod disagree, the Zod is the contract.**
   `AccountDetailV1` is **not** a superset of `AccountV1` (no `researchIsRefreshing`, `revenueBand`,
   `employeeBand`, `locationCount`, `primaryProjectId`, `projects` on the detail), and
   `fitCriteria` / `contacts` / `insights` / `activity` (E2) and `insights` / `artifacts` /
   `activity` (E3) are **required** arrays — an empty list is the honest answer, an absent key is
   not.
4. **(T1) E4 keeps `meta.total` on the envelope** (source map §1); the dummy's non-strict Zod
   ignores it.
5. **(T2) `custom_fields_for` mirrors `list_effective_fields`** — the retirement join *and* the
   dynamic-Client-KB-erasure `NOT EXISTS`. The erasure check is DSAR posture, not a readiness gate,
   so the standing rule is not violated; recorded because the table name is Client-KB-adjacent.
   Cost if wrong: a workspace under erasure shows no custom fields (the safe direction).
6. **(controller, before T3) the `?contract=v1` ruling** — see "The governing ruling" above. Global
   Constraint 11's retire-list is void.
7. **(T3) `iso_utc` (UTC, trailing `Z`) is THE v1 datetime form** — Zod 4's `datetime()` rejects
   `+00:00`. Any earlier v1 serialisation with `.isoformat()` (T2's `activity_for.occurred_at`) was
   switched to it in T4.
8. **(T3, accepted deviation) `employee_band` / `location_label` read the registry objects' own
   `label` / `raw` keys** rather than rendering whole objects — E2 must reuse them, and rendering
   the object puts `"city: Tel Aviv; country: Israel; raw: …"` on a table cell.
9. **(T4, accepted) a degraded read still schedules the background repair** (fails fast, logged).
10. **(T5, controller finding — Important) the evidence route must not spend.** E7's new fallback
    called `display.page(...)`, which can **generate** inside an evidence `GET` wherever a runner
    exists. Ruling: `DisplayPages.page(..., generate=False)` for authorisation reads — no
    `ensure_page`, no regeneration scheduling. Fixed in `675f9f7b1`.
11. **(T5, accepted deviations)** `project_names` is not read (no v1 detail field consumes it); the
    fixture uses D2's contacts-with-claims committee fallback; `_app` pins
    `arv2_display_generate_on_read=False` so route suites can never spend.
12. **(T6, cosmetic follow-up)** `_account_404` is imported from `contacts.py`; promote it to a
    shared home at D4 cleanup.
13. **(T7) E5 addressability** — a contact is served when it is **under this account** *and* has
    ≥1 live claim **or** a stored display section, not only when it sits on the committee.
    Generation is attempted only when claims exist. The FI-2 test
    `a_contact_on_no_committee_of_this_account_is_a_404` was updated to seed a *claimless* contact
    explicitly (still a 404) with a sibling positive test.
14. **(T7, accepted) a contact with no safe LinkedIn URL is served the site root**
    `https://www.linkedin.com/` with `linkedinLabel: "LinkedIn"` — the dummy declares the field a
    required `HttpUrl`, and a site root is never a guessed profile. Making it nullable (as
    `BuyingCommitteeMember.linkedinUrl` now is) is a D4 follow-up.
15. **(T4 process note)** never use `git stash` on this stack — a temporary WIP commit or a second
    worktree instead.

## The Zafran walk (Task 8) — the numbers

`tests/api/test_frontend_read_v1_live_zafran_db.py`, run against the worktree DB
(`clue-pg-managua` 55060, head `9f81e5692fea`) with `frontend_read_enabled=True` and
`arv2_display_generate_on_read=False` — a **projection over stored blocks**, no model call, inside
the usual rolled-back transaction. It **skips** (never fails) when the answer key or Zafran's live
overview block is absent. Payload dumps: `.artifacts/d3-zafran/*.json` (git-ignored;
`CLUE_D3_DUMP=0` turns the dump off).

- **E1** — 4 accounts in `ws_arv2_answer_key`. Zafran `researchStatus "completed"` /
  `"Researched"`, `websiteUrl "https://zafran.io"`, `employeeBand "51-200"`, `revenueBand
  "10m_50m"`, `locationsLabel "New York, New York, United States, North America"`,
  `locationCount 1`, `researchIsRefreshing false`. Cogent / Harmonic / UPTIQ `not_started`,
  bands `"Unknown"`. `fitScore` and `overallFit` **null on every row** (no `account.scoring.fit`
  claim exists anywhere in the answer key). `meta {total: 4, nextCursor: null}`.
- **E2** — `overviewDisplay` 6 sections in recipe order (`what-they-do`, `why-they-fit`, `why-now`,
  `buying-committee`, `how-to-approach`, `watch-outs`) with item counts `0/6/3/5/5/8`;
  `what-they-do` is a 2-sentence **intro** with no items, `why-they-fit` carries an intro too;
  `watch-outs` is the one `restricted` section. **44** `researchEvidence` rows covering all **40**
  claim ids cited in the block plus the 4 non-null `emailClaimId`s. `buyingCommittee` 5 members
  (Nick Fisher / Sanaz Yashar `economic_buyer`, Vari Kaur `champion`, Ben Seri
  `technical_evaluator`, Tom Anthony `user`), all with a `linkedinUrl`. **6** activity rows, every
  `actor.type == "clue"`. `headcountLabel "167 (51-200)"`, `locationsLabel` as above,
  `foundedLabel "2022"`. Providers on the evidence rows: AI Ark, Ashby, Exa, Gemini transcript,
  `exa_deep_reasoning`, `structuring_pass`; 32 of 44 rows have no `sourceUrl` (private records).
- **E3** — `insightsDisplay` 6 sections in recipe order with item counts `4/3/3/2/5/8`;
  `context-only` is the one `restricted` section. `insightSummary == ["17 insights", "5 people"]`
  — 17 = 4+3+3+2+5, i.e. the **non-restricted** items only (the 8 `context-only` watch-outs are
  not counted); 5 = the committee. **36** evidence rows covering all 36 cited ids. `artifacts` and
  `insights` both `[]`. 6 activity rows.
- **E4** — 5 rows, `meta.total 5`, ordered by persona rank: Nick Fisher and Sanaz Yashar
  (`economic_buyer`, tone `olive`, influence `High`), Vari Kaur (`champion`, `orange`, `High`),
  Ben Seri (`technical_evaluator`, `blue`, `Medium`), Tom Anthony (`user`, `cyan`, `Medium`). All
  `profileAction "page"`, `socials ["linkedin"]`.
- **E5 (Nick Fisher)** — `contactDisplay` 5 sections in recipe order (`why-this-person`,
  `problem-right-now`, `openers`, `angles`, `do-not-mention`) with item counts `3/4/3/3/10`;
  `do-not-mention` is `restricted`. Every `openers` item carries a `sendLine` with text.
  `tenureLabel "2 years 5 months"`, `employmentStartedAt "2024-04-01"`,
  `linkedinLabel "nicholastfisher"`, `locationLabel "New York, New York, United States, North
  America"`, `recentSignalsLabel "29 signals"`, `emailClaimId` set,
  `lastModifiedAt 2026-09-07T16:27:16.915936Z` (the contact's own stamp, ruling R8). **23**
  evidence rows covering the page's 21 cited ids plus the email and location claims.
  `overviewParagraphs` / `evidence` / `reports` all `[]`.
- **Both contracts** — the same five requests **without** `?contract=v1` still serve the FI-2
  shapes (E1 row has `scores`, E2 has `neutralFacts`, E4 row has `roleOnCommittee`, E5 has
  `professionalFacts`), and E3 returns byte-identical v1 with or without the parameter.
- **Validation** — every payload validated twice: the `contract_v1` pydantic model **and** the
  frontend's vendored Zod through `tests/api/contract_v1/oracle.py::zod_validate` (Node present;
  the oracle did not skip).

### The walk's second finding — three rail facts read the registry sketch, not the provider's record

The first walk served Nick's `educationLabel: null`, `linkedinFollowers: null`, `linkedinCreator:
null` although the answer key holds all three. The store carries AI Ark's **own** shapes:
`contact.facet.alma_mater` is a list (strings like `"MBA at Columbia Business School (2011 -
2013)"`, or objects keyed `school`/`degree`), `contact.network_statistics` nests
`network.followers_count`, and `contact.member_badges` is one flag per badge (`{"creator": true,
…}`). The three readers accepted only the registry sketches (`{institution, degree}`,
`{followers}`, a list of badge names). **Fixed at close-out by the controller** (Opus was
rate-limited; the change is three shape branches plus tests, commit named below): each reader now
accepts both the sketch and the provider record. After the fix the walk serves
`educationLabel "MBA at Columbia Business School (2011 - 2013)"`, `linkedinFollowers 6808`,
`linkedinCreator true`. The same class of gap remains open for `revenueLabel`/`fundingLabel`
(follow-up 5) — those are objects rendered whole, not nulls.

### The walk's one finding — `emailStatus` is `"lookup"` for everyone

Decision 13 (source map §3.5/§3.6) reads the email chip off a `core.work_email` claim whose
`value_json` is the provider's `{address, status}` pair — the shape `AiArkEmailExport` insists on
("an address flattened away from its status/domainType pair is a claim nobody can grade").
**No writer produces that shape.** D1's answer-key loader stores the bare address string
(`"nick@zafran.io"`, `verification_status = unverified`), FI-2's own email-lookup writer stores
`_normalize_email(email)` — also a bare string — and `core.work_email` is registered
`value_type = str`. So `v1_shared.email_facts` returns `lookup` for every real contact, E4 serves
no `emailLabel`, and `buyingCommittee[].email` is `null` while `emailClaimId` is set (which is why
the walk still proves the evidence join).

This is the **fail-closed** direction — the screen offers a lookup rather than presenting an
ungraded address as verified — so the reader was left exactly as specified rather than taught to
accept a bare string. Flipping it is a product ruling about showing unverified addresses; the real
fix is a writer that keeps the provider verdict. Pinned by the walk with the reasoning in-line, and
recorded in source map §3.5.

## The standing-rule checklist (2026-09-07 "no old-lane gate may block new-lane")

- `grep -rn "client_knowledge\|readiness\|stage0\|current_kb_version\|ClientKnowledgeCard"` over
  `frontend_read/{contract_v1,v1_shared,display_pages,account_workspace}.py` → **zero hits**. No
  ARV2 read consults Client-KB readiness, a Stage-0 gate or a KB version.
- `grep -n "display_allowed" frontend_read/*.py` → the C7 predicate appears **only on FI-2 paths**
  (`committee.py`, `contacts.py`'s FI-2 readers, `contact_email_lookup.py`, and `prose.py` where it
  is an injected callable). Every v1 path uses `arv2_display_allowed` (ruling S10), which does not
  consult `identity_binding`.

## Close-out gate (run alone, 2026-09-08)

| Gate | Result |
|---|---|
| `pytest tests/api tests/arv2 tests/claimstore` (keys unset, `--ignore-glob='*_live.py'`) | **deferred — hung twice at ~50% of `tests/api` (an artifact poller), stopped after 100 min; see the attribution note below** |
| `ruff check . --statistics` | **9** findings — the baseline (4 F401, 2 I001, 2 SIM300, 1 E501); none in a D3 file |
| `ruff format --check .` | **10** pre-existing unformatted files; none D3 |
| `mypy` | **1** error — the pre-existing `subsystems/design/clue_design/ad_assets.py:149` (781 files checked) |
| `lint-imports` | **26 kept / 0 broken** |
| `alembic heads` | one head `9f81e5692fea` — D3 adds no migration |
| `apps/frontend` | **not changed by D3.** `git diff --stat 16e79c279..HEAD -- apps/frontend` = `docs/api-contracts/accounts.md` only (+313 lines, the T1 contract-v1 section). No build was run because no buildable file moved. |

### Failure attribution

**Deferred (founder stopped it, 2026-09-08).** The wide pass (`tests/api tests/arv2
tests/claimstore`, keys unset) never completed: twice it stalled at roughly the halfway mark of
`tests/api` — Postgres showed the run re-issuing one `SELECT … FROM artifact WHERE storage_key = $1`
without pause, i.e. a test polling for an artifact that never appears when the provider keys are
unset — and the repo has no `pytest-timeout` to cut it off. It was killed after 100 minutes on the
founder's instruction. **What was verified instead, per task and first-hand:** every D3 route
suite (`test_frontend_read_{accounts_list,account_detail,account_workspace,contacts,app,
display_pages_db,v1_shared,v1_live_zafran_db}.py`, `tests/api/contract_v1`, `tests/arv2/test_settings.py`)
green after every task; the FI-2 route suites untouched and green; ruff/format/mypy/lint-imports
clean on every task's diff; one Alembic head. Pre-existing reds seen by the implementers and
attributed (not D3): `tests/arv2/test_onboarding_settings.py` (`.env.example` ships
`CLUE_ONBOARDING_V2_ENABLED=true` vs the code default `False`), `tests/api/test_projections_app.py`
(local `.env` `CLUE_CHAT_REASONING_TRACE_MODE=raw`), `tests/api/test_frontend_bulk_actions.py` ×3,
and four modules that raise at import when `CLUE_EXA_API_KEY` is unset. **Owed:** one wide pass
run per directory with `uv run --with pytest-timeout pytest … --timeout=120` streaming to a log,
which will name the poller as a timeout instead of hanging.

## Follow-ups for D4

1. **Re-point the `apps/frontend` adapters to `?contract=v1`**, then **delete the FI-2 branches and
   the `contract` parameter together** (`accounts_list.list_accounts`, `account_detail`'s FI-2
   reader + `AccountDetail`/`neutralFacts`/`projectSections`, `contacts.read_account_contacts` /
   `read_contact_profile`, `app.contract_mode` / `ContractDep`) and the FI-2 route tests with them.
2. **Lift the vendored Zod** (`tests/api/contract_v1/zod/`, the D0-a amendments marked
   `// D3 ruling`) back into `apps/frontend` — that copy is what the re-lift consumes.
3. **`_account_404` needs a shared home** — it lives in `contacts.py` and is imported by
   `account_workspace.py`.
4. **`AccountContactDetailV1.linkedinUrl` should be nullable**, like
   `BuyingCommitteeMember.linkedinUrl` now is, so the site-root fallback can go away.
5. **`revenueLabel` / `fundingLabel` must read the registry objects' keys** the way `employeeBand`
   and `locationsLabel` already do. The walk serves
   `"amount_max: 25000000; amount_min: 10000000; as_of: 2026-08-22; currency: USD; estimate_kind:
   provider_estimate"` on the rail today.
6. **The `"—"` title placeholder is E2's committee card only.** E4 serves `title: null` (ruling
   S7); the re-lift must render the dash client-side there, not expect it on the wire.
7. **`core.work_email` has no gradeable writer** (the finding above) — the email chip cannot say
   "available" until one exists, or until the reader is ruled to accept a bare address.
