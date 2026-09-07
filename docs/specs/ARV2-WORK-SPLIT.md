# ARV2 work split — exactly what Shashank owns, exactly what Aryan owns, and how work moves between them

**Companion to `ARV2-MASTER-PLAN.md` (v1.2). Version 1.0, 2026-09-04.** This document exists so that
Shashank can start and keep working without asking Aryan what to do next, and so that Aryan's time
goes only where it must. Read §1 (the line), §2 (the starter kit), then your own section (§3 or §4).
§5 is the timeline of who waits on whom; §6 holds the first charters, ready to paste to an agent.

---

## 1. The line — one rule, then the map

**The rule: Shashank produces content, specs, screens, leaf code via agents, and acceptance
evidence; Aryan produces the four integration points, reviews every branch, and merges.** "Leaf
code" means a module with no wiring into the platform: it can be built, tested against recorded
fixtures, and reviewed in isolation. "Integration point" means anything that changes what the
running system does: a database migration, a writer into the claim store, a read endpoint, or
wiring into the fleet/composition roots.

### 1.1 What Shashank touches (and his agents may edit)
| Area | Path | Notes |
|---|---|---|
| The dummy frontend | `clue-frontend` repo, branch `integration/live-backend-v1` (truth commit `84f8ee7`, 5 Sep), all of it | Presentation truth. He is the only owner. |
| Contract documents | `apps/frontend/docs/api-contracts/*.md` | He writes; Aryan signs. |
| Plans, specs, charters | `docs/specs/ARV2-*.md`, `.context/**` | Evidence and answer keys live in `.context/<run>/`. |
| The accounts feature re-lift | `apps/frontend/src/features/accounts/**` (D4 only) | Agent-executed from a charter; Aryan merges. |
| Research-agent content | `platform/agents/catalog/entity-research/arv2-account/v1/**`, `.../arv2-contact/v1/**` (profile, prompt, skills, manual) | Content, sha-pinned by Aryan at composition time. |
| Display content | the section-recipe seed file and the Luna section prompts (module created by Aryan in D2; content files his) | Recipes = which field keys feed which section; prompts = the section instructions. |
| Provider clients (leaf code) | `platform/api/clue_api/arv2/{ai_ark,exa,ats,rss,gemini,structuring}_client.py` + their fixture tests | Built by agents from his charters; recorded fixtures; Aryan reviews before merge. |
| The compliance pass (leaf code) | `platform/api/clue_api/arv2/compliance.py` + tests | Same. |
| Structuring prompts + the field catalog seed rows | `platform/api/clue_api/arv2/catalog_seed.py` (data only) | Same. |

### 1.2 What Shashank never touches (Aryan only)
`alembic/**` · `libs/**` (config, core, gateway, db, storage) · `platform/api/clue_api/*_wiring.py`,
`fleet_main.py`, `composition.py`, `run_composition.py`, `toolbelt_wiring.py`,
`agent_registry_wiring.py` · `platform/api/clue_api/frontend_read/**` · `subsystems/research/**`
(the claim store package) · anything under auth, tenancy, or storage · `.env.example` values for
flags he did not introduce (his charters may *add* a flag line for a flag their code introduces —
never change an existing one) · the shared base branch itself (he never merges or pushes to it).

### 1.3 How a piece of work moves
1. Shashank writes a charter (template in §6.0) and runs it with an agent on a **task branch** named
   `task/<step>-<slug>` cut from the shared base.
2. The agent commits on the task branch and reports; Shashank checks the report against the exit
   gate first-hand (opens the screen, runs the command, reads the diff summary). If it fails, he
   re-charters; he does not "fix it a bit" by hand.
3. He hands Aryan the branch name + the report + the exit-gate evidence (one message).
4. Aryan reviews (integration points get a code read; leaf code gets a fixture-test run + a skim),
   merges to the shared base, and replies "merged" or "changes: …".
5. Both pull the shared base before starting anything new. Daily.

---

## 2. The starter kit — what Aryan hands Shashank before he begins (all of it, once)

1. **The shared base, `origin/integration/design-improvement`** — the current platform line
   (it absorbed the old `install-agent-browser-global` line on 2026-09-07), with R0 and every plan document on it (`ARV2-MASTER-PLAN.md`,
   `ARV2-WORK-SPLIT.md`, `ARV2-AGENT-BRIEFING.md`, `ARV2-GETTING-STARTED-SHASHANK.md`,
   `ARV2-ROADMAP.md`). Aryan keeps it in sync with the platform line. Until this is pushed, nothing
   else can start.
2. **Keys and access:** the Apollo and AI Ark keys rotated; the AI Ark paid tier bought;
   `CLUE_GEMINI_API_KEY`, `CLUE_EXA_API_KEY`, `CLUE_AI_ARK_API_KEY`, `CLUE_OPENROUTER_API_KEY` in his
   local `.env` (never in any artifact); the local Postgres for db-gated tests documented in
   `DEV_STACK.md`.
3. **The empty homes for his leaf code:** the package `platform/api/clue_api/arv2/` with an
   `__init__.py`, a `README.md` naming each expected module, the fixture-test layout
   (`tests/arv2/fixtures/<provider>/*.json`), and the `CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED=false`
   flag already in `.env.example` — so his charters have exact paths to name.
4. **The answer keys, listed by path:** Probook (`chicago/.context/arv2-clue-sample-v3/`), Zafran
   (`chicago/.context/arv2-one-account-aiark/`), the ten people (`chicago/.context/arv2-person-depth/`),
   the three Zafran spec pages (`chicago/.context/frontend-page-content/`), the display control test
   (`chicago/.context/display-layer-control-test/`).
5. **The four flags his code may read** (already in `.env.example` after D1): `CLUE_CLAIM_WRITE_LENIENT`,
   `CLUE_EVIDENCE_VERBATIM_CHECK`, `CLUE_UNEVIDENCED_ROW_PURGE_ENABLED`, `CLUE_SENSITIVITY_FLOOR_ENABLED`.
6. **The charter template** (§6.0) and the standing rules (master plan §2 items 7–10).

---

## 3. Shashank's steps — in order, each with inputs, exit gate, and what he hands back

| # | Step | Inputs he needs | Exit gate (he checks it himself) | Hand-back to Aryan |
|---|---|---|---|---|
| S1 | **D0-a — apply the remaining rulings to the dummy frontend** (master plan §8: R1 no dates on chips or in hover cards, R4 full quote, R5 email via `emailClaimId`, R6 "Unassigned" owner, R7 null score on create, R8 contact date + served tenure, R9 remove the h1/overall-fit parsers, delete the dead digest) | `live-backend-v1` @ `84f8ee7`, the rulings list | `npm run design-system:build && npm run lint && npm run build && npm test` green (≥118 tests, fidelity tests untouched); Zafran pages render per the 5 Sep presentation | The dummy commit sha + screenshots of the three Zafran pages |
| S2 | **D0-b — write contract v1** into `apps/frontend/docs/api-contracts/accounts.md` (master plan §6, every field, every backend-owned semantic, the "no field_key on the wire" ruling) | master plan §6, the dummy's `model/*.ts` | The doc lists all five payloads field-for-field and matches the Zod models exactly (an agent diff) | Task branch for Aryan to sign; this is the frozen wire contract |
| S3 | **Catalog seed rows** — the new registered fields (master plan §4) as data with a one-sentence researcher-facing description each, every sub-field optional | master plan §4; the PoC field lists | A test loads the rows into a throwaway registry and validates every value schema | Task branch (leaf) |
| S4 | **Section recipes + Luna section prompts** — the recipe seed (page → section → allowed field keys, h1, order, restricted, default_open) and one instruction file per section, with the three fixed prompt lines | `frontend-page-content/README.md` §2–3, the control-test decisions | A test asserts every field key in every recipe is a registered key; prompts contain the three lines | Task branch; content files inside the module Aryan created in D2 |
| S5 | **R1 charters and runs — the provider clients** (one charter per client: AI Ark, Exa, ATS, RSS/YouTube probe, Gemini media, OpenRouter structuring), each with save-raw-before-parse, ledger, pre-spend estimate, retries, and the client-specific laws (master plan §3 + Appendix A) | master plan §3; the PoC scripts as reference; live keys | Recorded live fixtures under `tests/arv2/fixtures/<provider>/` for Zafran + Probook; fixture tests green; **no claim writes**; every flag the client introduces added to `.env.example` | One task branch per client |
| S6 | **The compliance pass module** (leaf) — sensitivity floor (redact minors references; mark origin/faith/health `outreach_safe=false`), unevidenced marking, all flag-driven, never dropping a claim | master plan §2 items 2 and 6; the PoC `p5b_redact.py` as reference | Tests: the Sanaz children case is redacted, the origin line is marked, nothing is dropped, flags off ⇒ no-op | Task branch |
| S7 | **Research-agent content** — `arv2-account/v1` and `arv2-contact/v1` catalog folders: profile, prompt, the dossier skill (the ten-section charter), the contact-depth skill (the personal charter), the audit skill, the manual (refusal → reaction table) | the PoC charters (`z5_exa_deep.py`, `p3_deep.py`), master plan §9 R2/R3 | An agent dry-runs each prompt against the Zafran/Probook fixtures and the output matches the answer-key sections | Task branch; Aryan sha-pins at composition |
| S8 | **D4 — the accounts re-lift** into `apps/frontend` (the dummy's accounts feature folder, the accounts layout shell, the `/api/source-favicon` route, and the design-system token changes; adapters re-pointed at `/frontend/v1`; no new components) | the dummy at its D0 commit; Aryan's D3 endpoints live | `apps/frontend` gates green; with `CLUE_API_BASE_URL` set the three Zafran pages render from the real backend; fixtures still demo offline | Task branch; Aryan merges |
| S9 | **D5 — acceptance walk-through** — the three Zafran spec pages vs the live pages, section by section; drift list | D2–D4 merged | A signed checklist in `.context/d5-acceptance/` with screenshots; drift list empty or ruled | The checklist |
| S10 | **R2/R3 acceptance** — when Aryan has composed the lane: run Probook, Zafran, the ten people; compare to the answer keys; cost ledgers reviewed | the composed lane | The exit gates in master plan §9 met, evidence in `.context/` | The evidence folders |

Ongoing, his: the weekly open-decision list for the ruling session; every cost ledger reviewed; the
dummy kept as the design truth (any screen change lands there first, then is re-lifted).

---

## 4. Aryan's steps — the integration points and the merges

| # | Step | What exactly | Exit gate | Unblocks |
|---|---|---|---|---|
| A1 | **Push the base; keys; the starter kit** (§2) | push R0 + plans; rotate keys; buy AI Ark tier; create `platform/api/clue_api/arv2/` skeleton + fixture layout + the lane flag in `.env.example` | Shashank can pull and see everything | S1–S7 |
| A2 | **D1 — the migration** (master plan §4): `signal_priority`, `outreach_safe`, `display_block`, the recipe config table; register the S3 seed rows; the five leniency/check flags in `Settings` + `.env.example` | single alembic head; `make db-smoke` green; parity test green | S4, A3 |
| A3 | **D1 — the claim loader**: a governed writer that turns `claims_zafran.json` + `claims_people.json` into real claims through `insert_claim` in lenient mode (stamp priority/outreach_safe, unify `use_class`, write run lineage, snapshot media transcripts, one-fact-one-flag dedupe) | 174 + 119 rows in the store, catalog-valid, lineage-pinned | D2, D3 |
| A4 | **D2 — the display module**: the Luna section runner (stable prefix, parallel sections, default effort), the evidence resolver (domain + favicon + title, cached), `display_block` persistence with the generate-once / recipe-scoped-invalidation policy, the floor check; the module exposes the recipe + prompt files Shashank owns (S4) | Zafran overview, insights, Nick Fisher pages generated from the store; 0 unsafe leaks | S8 (with A5) |
| A5 | **D3 — the read surface**: the five contract-v1 payloads on `/frontend/v1` | payloads validate against the dummy's Zod models byte-for-byte (a test that imports the schemas) | S8 |
| A6 | **Merge S1–S8 branches** as they arrive; sha-pin S7 content into the profiles | each merge: gates green on the base | continuous |
| A7 | **R2 composition**: the `Arv2JobDriver`, `write_claims` (lenient), the `finalize` tool, the fleet handler behind `CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED`, the launcher; import-guard test (nothing in `arv2/` imports a quarantined module); toolbelt authority dict updated | one real account job runs end-to-end on the fleet; old lane still inert | S10 |
| A8 | **R3 composition**: the contact definition, committee protocol tools, the compliance pass wired after structuring | the ten-person run reproduces on the fleet | S10 |
| A9 | **R4 composition**: discovery tools, cohort approval gate, fleet fan-out with a concurrency cap | a 20-account cohort end-to-end | — |
| A10 | **Track O** — his own lane (onboarding as research pipeline, ICP artifacts, project context, Exa MCP, brand context, the output-pane handoff), scheduled around A1–A9 | per Track O | — |

Aryan's time budget is the constraint: A2–A5 are each a bounded day or less if the S-side inputs
arrive first; A7–A9 are the larger builds. Nothing in the S list needs him except reviews.

---

## 5. Who waits on whom (the timeline)

```
A1 push + kit ─────────────► S1 D0-a  S2 D0-b  S3 seed rows  S5 R1 clients  S6 compliance  S7 content
                                │        │          │             │             │             │
A2 migration ◄───────────── (S3 rows) ◄──┘          │             │             │             │
A3 loader ──────────────────────────────────────────┘             │             │             │
A4 display module ──── needs S4 recipes/prompts ◄─────────────────┼─────────────┼─────────────┤
A5 read surface ──── needs S2 contract v1 signed                  │             │             │
S8 re-lift ──── needs A4 + A5 merged                              │             │             │
S9 D5 acceptance ── needs S8                                      │             │             │
A7 R2 composition ── needs S5 clients + S7 content + A2 ◄─────────┘─────────────┘─────────────┘
S10 R2/R3 acceptance ── needs A7/A8
```
Parallel by design: S1/S2/S3/S5/S6/S7 all start the day A1 lands and need nothing from Aryan but
reviews. A2–A5 are Aryan's next week. S8/S9 follow A4/A5. A7 follows S5/S7.

---

## 6. The first charters (ready to paste)

### 6.0 The charter template (every task uses it)
```
CHARTER: <step id> — <one-line goal>
Base: shared base at <sha>. Branch: task/<step>-<slug>.
Inputs (read these first, exact paths): …
Files you MAY create/edit: … (nothing else; if you believe another file must change, STOP and say so)
Standing rules: no invented UI components; every new flag in .env.example in the same commit;
  save raw before parse; no keys in any file; no push; commit on the task branch only;
  no Co-Authored-By / AI attribution in commit messages.
Exit gate (must be true before you report): …
If you must decide anything not written here: STOP, write "QUESTION", end your run.
Report: what changed (file:line), the exit-gate evidence (command output / screenshot path),
  the commit sha, any QUESTION.
```

### 6.1 S1 — D0-a: apply the remaining rulings to the dummy frontend
Goal: make `clue-frontend` (`integration/live-backend-v1`) match master plan §8's remaining rulings
without changing the 5 Sep presentation decisions. Inputs: `docs/specs/ARV2-MASTER-PLAN.md` §6–§8;
`src/features/accounts/**`; `docs/zafran-content-implementation.md` (the presentation decisions —
do not undo them). Files: `src/features/accounts/**` and `src/app/accounts/**` only. Work, in
order: (R1) no dates on chips or in the hover card — remove any date rendering; `verifiedAt` and `publishedAt` stay on the wire untouched; (R4) remove the 4-line clamp on the hover-card quote; (R5) resolve the contact
email chip via `emailClaimId`, delete the substring match; (R6) `resolveAccountOwner` returns
"Unassigned" when `owner` and `createdBy` are both null — never the current viewer; (R7)
`createLocalAccount` sets `fitScore: null` and `overallFit: null`, making `overallFit` nullable in
`model/account.ts` and `model/account-detail.ts` (render "—"; a contract-v1 change to record in S2); (R8) the contact page
"Updated" shows the contact's latest `verifiedAt`, and tenure prefers the served `tenureLabel`;
(R9) delete the client-side h1 count stripping and the "Overall fit" regex — read `overallFit`
and `items.length`; delete the dead `ResearchDigest`. Exit gate: the frontend gate green with the
fidelity tests unchanged; screenshots of the three Zafran pages showing R1, R4, R6.
### 6.2 S2 — D0-b: contract v1 into `accounts.md`
Goal: `apps/frontend/docs/api-contracts/accounts.md` states the five payloads and the shared types
field-for-field as the dummy's `model/*.ts` define them at `live-backend-v1` @ `84f8ee7` (incl.
`segments`, `researchExcerpt`, `verificationKind`, `fitDisposition`, `intro`, actor-based
activity, account artifacts, `owner`/`createdBy`, nullable `fitScore`), plus master plan §6's
backend-owned semantics and the rulings that `field_key`/`use_class`/`source_type` are not on the
wire and that `h1` is served bare. Files:
that one file. Exit gate: an agent-produced diff between the doc's field lists and the Zod schemas is
empty; the doc has a "Backend-owned semantics" section and a "Not on the wire" section.

### 6.3 S5 (one of six) — the AI Ark client
Goal: `platform/api/clue_api/arv2/ai_ark_client.py` with `company_by_domain(domain)`,
`people_by_name(name_variants, domain)`, `export_email(linkedin_url)`; each call saves the raw
response, annotates status/latency/request, writes a ledger row, raises a pre-spend estimate first,
retries per Appendix A, paces ≥10.5 s, halts on 402/403/"credit", drops `birth_date` **before**
persistence, parses the email block at `email.output[0]` into `verified_smtp | catch_all_valid |
not_found`. Inputs: master plan §3 row "AI Ark"; `chicago/.context/arv2-one-account-aiark/z_lib.py`,
`z1a`–`z1d` as reference; the key from `.env`. Files: the client module, `tests/arv2/test_ai_ark_client.py`,
`tests/arv2/fixtures/ai_ark/*.json`, one new line in `.env.example` if a client-specific knob is
introduced. Exit gate: recorded fixtures for Zafran (company, 3 name-scoped people, 2 emails) and
Probook; tests green offline against the fixtures; no claim writes; the ledger shows credits by
result-count arithmetic. (Repeat this pattern for Exa, ATS, RSS/YouTube probe, Gemini, structuring.)

### 6.4 S6 — the compliance pass
Goal: `platform/api/clue_api/arv2/compliance.py`: `apply(claims, flags)` → claims with redactions
and markers. Rules: minors references removed from the value (even if self-published); origin /
nationality / faith / health / politics / sexuality / family-tragedy facts marked
`outreach_safe=false` and barred from `hooks`/`openers`; rows with no quote and no URL marked
`unevidenced` (purged only if `CLUE_UNEVIDENCED_ROW_PURGE_ENABLED=true`); never drop a claim whole;
log every action. Inputs: master plan §2 items 2 and 6; `chicago/.context/arv2-person-depth/p5b_redact.py`
and `p5_tables.py` (the regex sets) as reference. Exit gate: tests for the Sanaz cases and a
flags-off no-op.

### 6.5 S4 — recipes and section prompts
Goal: the recipe seed (page/section/order/h1/allowed_field_keys/restricted/default_open) for the
three pages from `frontend-page-content/README.md` §2, and one instruction file per section with the
three fixed lines (never type claim ids into prose; dates as "17 June 2026"; the hobby hook at most
once per page), the `sendLine` as a separate field, and the empty-recipe rule. Files: the content
files under the module Aryan created in A4. Exit gate: a test asserts every recipe key is a
registered field; a dry run against the Zafran claims fixture produces all sections with 0 unsafe
citations outside restricted sections.

---

## 7. The two rules that keep this split honest
1. If Shashank finds himself editing something in §1.2, the task was scoped wrong — stop and hand it
   to Aryan as a one-line ask.
2. If Aryan finds himself writing content, specs, prompts, or fixtures, the task belongs in §3 —
   hand it back as a charter for Shashank.
