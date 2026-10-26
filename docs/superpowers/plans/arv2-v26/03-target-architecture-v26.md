# ARV2 v26 — 03. Target architecture (deterministic design)

**Status:** design, Lane L5 of the v26 program, 2026-10-07; **reconciled 2026-10-07** against
`RECONCILIATION-RULINGS.md` (R2, R9–R16, R19 applied; R3/R5/R6/R7/R12 are this document's own
positions and stand) using review A (C1–C40, §2, §5) and review B (edits 1–10, Appendix A) as the
change list. Replaces §2 of `docs/superpowers/plans/2026-10-06-account-research-v26-cost-and-speed-plan.md`
(the plan's §1 brief, §3 numbers and §7 decisions remain the founder-reviewed intent this document
implements). Built on the evidence records of this folder — `01-evidence-all-production-runs.md`
(01), `01b-follow-up-chains-and-nothing-lost.md` (01b), `02-codebase-map-research-lane.md` (02) and
`03a-runtime-and-toolbelt-mechanics.md` (03a). 03a §8 chose the runtime mechanisms; this document
builds on them and diverges in two places, each with its reason: §5.3 (the tool-result clearing
exclusion list — arithmetic) and §3.8 (the deferred contact page is a research-kind continuation, not
a display task — 04 §0.5's verified reason, adopted by R11). 04 follows this document line by line
and 05 follows both (R1); the parameter sheet in §10 is the single sheet both are regenerated from
(R7).

**Recipe integers (R2).** Two mints, one program: **r26** is the week-1 mint (tool-shape and prompt
changes force it — 04 §0.2) and **r27** is the pipeline this document designs. "v26" stays the
program's name and the settings prefix (`CLUE_ARV2_V26_*`); every pipeline gate in code reads
`quality_recipe_version >= 27`, and this document says *r27* where the pipeline is meant and *r26*
where the week-1 mint is.

**Conventions.** `02 §x (path:line)` and `03a §x (path:line)` cite the two maps, which carry the
line numbers into main `fa4bed77b`; a bare `path:line` marked *(verified 2026-10-07)* is a fact
read directly from the checkout because neither map covers it. "Setting" means a `Settings` field
in `libs/clue-config/clue_config/settings.py` **and** a line in `.env.example` with the same
default (the parity rule in `CLAUDE.md`); every v26 setting is listed once, in §10, and is named
`CLUE_ARV2_V26_*` unless it extends an existing name. "Account judge" and "contact judge" are the
two governed Deep Agent turns of r27; "pre-step" is the code that runs before each turn.
Prices are the plan's §3 sheet (Grok 4.6 $2.00 / $0.50 cached / $6.00 per M; Gemini 3.8 Flash
$0.75 / $0.075 / $3.75; GPT-5.6 Luna $0.20 / $0.02 / $1.20; Exa search $0.009, contents $0.004,
deep ≈ $0 at the pinned surface; AI Ark ≈ $0.01 per credit).

**Binding rulings this design obeys (founder, 2026-10-07 unless dated).** Every buying-committee
contact (top 4–5) gets full-depth research — no light/deep tiers. The account and all its contacts
start together the moment the account is approved. The agent keeps its investigative follow-ups:
the rule table is a floor, not a ceiling, and follow-ups are cheap because tools return extracted
candidates, never raw pages. Every provider call is concrete. v26 is a new recipe/profile on the
governed runtime — toolbelt, journal, replay, DSAR and the claims import stay. No code counts
words, lines or items in agent prose (2026-10-04). The Miscellaneous dump (D3) and the model
choices (D4) are the founder's; both outcomes are designed for where that is cheap. Media stays off
(D1, §7). The committee is automatic (D10).

---

## §1 Scope and non-goals

### 1.1 In scope

1. **Recipe 27**: profiles `quality-account-research@v27` and `quality-person-research@v27-person`
   (the latter with its own `AgentRole` `person_research`, R4), prompts, skills, `recipe-v27.json`,
   `launch-v4-r27.json`, the ladder branch, minted exactly as 02 §5.6 requires
   (`quality_research_wiring.py:312-346`; `quality_catalog.py:14`). Recipe 26 is the week-1 mint
   (04 §0.2: W1-2/3/5/9/12/13/14); this document designs r27 and names r26 only where r27 builds on
   something r26 minted.
2. **The pre-step** (03a §8a): A0 committee, A0.0 context compile, A1/A2 acquisition plans, A3
   table-driven follow-ups, the mechanical gap round, and B extraction — code in
   `arv2/acquisition_plan.py`, `arv2/followups.py`, `arv2/quality_extract.py`, `arv2/committee_rank.py`,
   executed from `ResearchUnitRuntime.run` between `bindings` and the task artifact
   (03a §8a: `quality_research_wiring.py:901`, `:867-879`).
3. **Two tools**: `acquire_research_evidence@2` (03a §8b — the judge's investigative surface,
   returning candidates; **minted once in r26 with the r27 shape already present** — `candidates`
   empty until the extractor lands, plus `ledger` — R13 / 04 §0.4) and `submit_brief@1` (new, §3.7
   — one call that validates, persists and imports the brief through the unchanged `finish_dossier`
   import path; R3).
4. **Pages**: the per-section parallel writer (03a §8g) on the page-writer runtime, contact pages
   deferred to the account import as a research-kind continuation (04 §0.5/P1, adopted by R11),
   account pages written once plus one conditional refresh.
5. **State**: contacts released at nomination, the `pending_continuations` predicate for r27,
   stage markers, lease/takeover behaviour per stage (§6).
6. **Settings, flags, rollout, observability** (§8–§10). **One migration from this design** (W2's
   two — W2-17's indexes and W2-19's lazy bytes — are W2's own, 04 §10): the `person_research`
   role widens the **five** role constraints (**six** predicates) the corrected 02 §3.8 enumerates
   (`agent_turn_role`, `agent_plan_role`, `agent_delegation_roles`, `agent_model_call_role`,
   `quality_execution_role`'s value set and its root predicate `parent_execution_id IS NULL AND
   role='account_research'` — 04 W3-26, reversible, hash-id per the `CLAUDE.md` conventions) and
   lifts the hard-coded `role != "account_research"` refusals a contact judge would hit
   (Appendix B). Every other durable addition is a content-addressed artifact, an
   `artifact_reference` kind (a code-only vocabulary, 02 §3.7), an `input_refs` key (02 §3.2) or an
   `arv2_research_operation` kind (02 §3.3) — so rollback is configuration (§9.4) and the
   migration stays.

### 1.2 Non-goals

- **v25 and r26 behaviour.** Nothing here changes a v25 or an r26 run: every pipeline behaviour is
  behind `quality_recipe_version >= 27` (one predicate `uses_v26_pipeline(scope)` in
  `quality_policy.py`, the pattern of `:14-22`, 02 §9.1); the v25/r26 profiles, tools
  (`acquire_research_evidence@1` stays registered and default, 03a §2.1) and settings keep their
  values. W1 (plan §4) ships as r26 and flags separately (04 §3); r27 builds on the r26 mints it
  names (§1.1 items 1 and 3) and on nothing else in W1.
- **W2 platform throughput** (plan §4 W2). v26 is *correct* without W2 and *fast* only with it:
  the stage timings in §5.5 assume W2-20/16/17/15 landed; without them every provider operation
  pays the ~45 s indexing tail 01 §1.3 measured and the time triples while cost barely moves
  (plan §3). W2 is tracked there, not here.
- **The account-level operation pool** (plan W2-18): `arv2_research_operation` stays job-keyed
  (02 §3.3, `UNIQUE(ws, job_id, kind, request_sha256)`); cross-job reuse is by plan and by the
  request-sha sibling rule (§3.3.4), never by sharing operation rows.
- **Media on** (W4, D1) — §7 states the exact switch-on conditions and nothing else.
- **Launch latency** (W1-11 / D7): the Head-of-ABM turn is out of scope; §3.1 states only what v26
  requires of the launch (nothing new on the wire).
- The frontend, the quarantined M8D lane, the claim store, the field registry, the DSAR machinery
  and the fleet queue are consumed as they are (02 §10 items 1, 5, 15, 17).

---

## §2 The research contract (campaign brief)

### 2.1 Classes, caps, minimums, where each class is served

Caps and minimums are **settings** (§10, group C2); the defaults are **01b §6's recommended
values** (R10): the evidence record showed the plan's §1 caps cutting A-class items on three accounts
(Stack, Committee, Watch-outs — 01b T8) and on the richest contacts (own-words, problem-now,
proud-of, hooks — 01b T9), and 01b's values cut none. A cap bounds what the page writer
sees per class; items the judge ranks past the cap still import (retained for audit, 02 §10 item 4)
with `write_markers.over_cap=true` and are never served (§3.7.4). A minimum is the count that, when
unmet after A3, fires the mechanical gap round (§3.5). "Interp." = the one-line
`agent_interpretation` is **required** on the item (presence check, §3.7.3 — not a word count).

**Account brief (cap total ≈ 50):**

| Class id | What | Cap setting (default) | Min setting (default) | Interp. | Display sections it feeds (`page_writer.py:41-66` keys, *verified*) | Content-plane slot kind (Doc S §4 table, `clue-hq-content-and-artifact-scaling.md:76-78`) |
|---|---|---|---|---|---|---|
| `trigger` | one item per dated event: leadership change (+ successor or vacancy), funding, launch, expansion, hiring surge, award, layoff; a *sequence* item cites ≥ 2 candidates | `CLUE_ARV2_V26_CAP_TRIGGER` (10) | `CLUE_ARV2_V26_MIN_TRIGGER` (3) | yes | overview/`why-now`; insights/`buying-signals`, `money-and-momentum` | repeater (why-now items), dynamic (email hook, ad timing) |
| `initiative` | what they are publicly trying to do this year, in their words | `…_CAP_INITIATIVE` (5) | `…_MIN_INITIATIVE` (1) | yes | overview/`why-they-fit`, `how-to-approach` | dynamic (landing-page headline) |
| `pain` | problems they, their customers or employees name | `…_CAP_PAIN` (5) | — (0) | yes | overview/`how-to-approach`; insights/`how-they-sell` | dynamic (problem framing, ad copy) |
| `motion_proof` | how they sell/market; named customers; claimed outcomes | `…_CAP_MOTION_PROOF` (5) | — | no | insights/`how-they-sell`; overview/`what-they-do` | programmatic (logos), dynamic (credibility lines) |
| `stack` | tools they use that matter to the seller's product — for the benefits and fleet sellers the incumbent-vendor list *is* the fit assessment and each item is also a do-not-say (01b §6) | `…_CAP_STACK` (8) | — | no | insights/`tools-they-already-use`; overview/`why-they-fit` | programmatic (fit), dynamic (technical angle) |
| `committee` | who decides/champions/evaluates/blocks, with role evidence; the nominated 4–5 **plus alternates and blockers** | `…_CAP_COMMITTEE` (10) | `…_MIN_COMMITTEE` (4) | yes | overview/`buying-committee`, `how-to-approach` | programmatic (contact selection, routing) |
| `watch_out` | disqualifiers, sensitivities, competitors in place | `…_CAP_WATCH_OUT` (4) | — | no | overview/`watch-outs` (restricted) → shared into insights/`context-only` (02 §3.12, `recipes.py:116`) | dynamic (do-not-say), routing |
| `not_found` | what was searched for and not found, each citing ≥ 1 acquisition-ledger operation id | `…_CAP_NOT_FOUND` (3) | — | no | the `gaps[]` array of the section its `about_class` names (`page_writer.py` `OUTPUT_SHAPE`, *verified*: sections carry `gaps`) | honest gaps; a vacant seat is a why-now |
| `firmographic` | HQ, headcount, industry, founded, funding totals | fixed — **not extracted**; the deterministic provider claims (`lookup_company` AI Ark company claims, `read_ats_board` postings — 02 §2.3) | — | no | overview/`what-they-do` via the registered `core.*`/`account.*` fields (`display/recipes.py:127-146`, *verified*) | programmatic (mail address block, stats) |

**Contact brief (cap total ≈ 24; every contact):**

| Class id | What | Cap (default) | Min (default) | Interp. | Display sections (`page_writer.py:58-66`) | Slot kind |
|---|---|---|---|---|---|---|
| `remit` | current remit and what they own (the judge **merges** corroborating records — profile, enrichment, org chart, bio — into one item; 01b §6: merged, no contact exceeds 2) | `…_CAP_REMIT` (2) | `…_MIN_REMIT` (1) | no | contact/`why-this-person` | programmatic/dynamic |
| `problem_now` | the problem they are working on right now — their posts, their team's job postings, their initiatives | `…_CAP_PROBLEM_NOW` (5) | `…_MIN_PROBLEM_NOW` (1) | yes | contact/`problem-right-now` | dynamic |
| `own_words` | verbatim quotes with URL and date | `…_CAP_OWN_WORDS` (8) | `…_MIN_OWN_WORDS` (2) | no | contact/`openers`, `angles` | repeater (each artifact picks a different one) |
| `proud_of` | what they are proud of / recognised for, from their own or their employer's posts | `…_CAP_PROUD_OF` (3) | — | no | contact/`angles`, `why-this-person` | dynamic |
| `hook` | personal opener, **self-disclosed only**, use-class gated (§2.5) | `…_CAP_HOOK` (4) | — | no | contact/`openers` | dynamic (opener) |
| `career_arc` | one line | `…_CAP_CAREER_ARC` (1) | — | no | contact/`why-this-person` | dynamic |
| `do_not_mention` | one line | `…_CAP_DO_NOT_MENTION` (1) | — | no | contact/`do-not-mention` (restricted) | routing |
| `not_found` | as for the account | `…_CAP_NOT_FOUND` (3, shared setting) | — | no | `gaps[]` | — |
| `identifier` | title, office location, work email | fixed — the AI Ark record kept from A0 and the `core.work_email` claim `enrich_contact` writes (02 §2.3) | — | no | programmatic | programmatic (mail) |

**Dropped by construction** (plan §1): education entries, early-career roles, namesake
inventories, hometown/pets/milestone sweeps, process narration, recording listings. They are not
classes, so the extractor has no class to put them in (§3.5.2) and the judge has no section to
rank them into; a namesake *is* recorded — as a `subject_anchor.matched=false` candidate that can
only become an `unbound` hook (§2.5).

### 2.2 Field mapping — claim store, display, content plane

- **Claim field keys.** Every brief item imports through the unchanged
  `finish_dossier` → `import_research_dossier` path as an `account.research_finding` /
  `contact.research_finding` claim (02 §2.2: `dossier_import.py:69`), one claim per item, with the
  item's `value_json` carrying the v26 extras the master plan already allows as sub-fields
  (`docs/specs/ARV2-MASTER-PLAN.md:174-176`, *verified*): `class`, `rank`, `statement`, `quote` |
  `typed_value`, `interpretation`, `personas[]`, `candidate_ids[]`, `not_found`; `claim_type`
  is widened to `observation | reported_statement | synthesis | not_found` on the lenient
  `FindingV2`/`EntryV2` models of 04 W1-2 (R3; review A Q20) — **`Finding` itself is not widened**:
  `Entry(Finding)` puts the literal in `save_dossier_section@1`'s input schema, so a wider base
  literal would move the `@1` sha and every v16–v25 pin; the importer takes `entry_model=` and
  04 W1-2 defines the claim kind each value imports as.
  Firmographics and identifiers are **not** research findings: they are the registered fields the
  deterministic provider writers already stamp (`QualityProviderWriter`, 02 §2.3 `lookup_company`,
  `read_ats_board` → `account.open_requisitions`, `enrich_contact` → `core.work_email`), and the
  content plane's programmatic slots bind to those registry keys (Doc S §4: `BindingHint.source_path`
  = registry field key, *verified* `clue-hq-content-and-artifact-scaling.md:76`).
- **Display sections.** The v26 page writer slices the brief **by class** (table above), not by the
  recipes' `allowed_field_keys` — those lists (`display/recipes.py:50-310`, *verified*) govern the
  legacy claim-driven display path and the Miscellaneous/uncovered logic (02 §3.12, §10 item 13),
  which v26 does not use for its sections. The section keys themselves are unchanged
  (`page_writer.py:41-66`), so `display_block` rows, `arv2_research_page_current` and the frontend
  read (02 §1.7, §3.12) need nothing new.
- **Content plane.** Programmatic ← registered fields; dynamic ← `*.research_finding` claims
  selected by `value_json.class`; repeater ← the class's items ordered by `value_json.rank`
  (the judge's order) × persona relevance from `value_json.personas[]` — Doc S §6.3's working
  default (*verified* `clue-hq-content-and-artifact-scaling.md:132-137`), unchanged.
- **Interpretation.** `agent_interpretation` is already a `Finding` field (02 §2.2 `Entry` model;
  `dossier_findings.py:38-48`, *verified*) and is already imported; v26 makes it required on the
  classes marked above and passes it to the writer (plan W1-13).

### 2.3 The finding record (what the judge emits per item)

One JSON object per item; the server fills every default (§3.7.3) so a judge omission never costs a
round. Field names reuse the `Entry`/`Finding` contract (02 §2.2) wherever one exists.

```json
{
  "id": "F012",
  "class": "trigger",
  "topic": "CMO departure, September 2025",
  "claim_type": "synthesis",
  "finding": "The CMO left in September 2025 and no successor has been named as of May 2026.",
  "candidate_ids": ["c_8a1f0c2d9e77", "c_3b44a0d1c2f9"],
  "quote": null,
  "typed_value": null,
  "source_paths": [],
  "attribution": null,
  "time_context": "2025-09 → 2026-05",
  "confidence": 0.8,
  "use_class": null,
  "personas": ["economic_buyer", "champion"],
  "agent_interpretation": "Vacant economic-buyer seat; the SVP Marketing hired in Feb 2026 is the likely budget owner.",
  "rank": 1,
  "conflicts_with": [],
  "wrong_entity": false,
  "not_found": null
}
```

Rules, each enforced by `submit_brief@1` as a *shape* check (never a content judgement):

- `candidate_ids` cite candidates from the subject's pool or from the judge's own follow-up
  receipts (§4.1); `claim_type="synthesis"` requires ≥ 2 ids whose `source.url` differ (plan AT-4);
  `observation`/`reported_statement` require exactly 1 id, and the item's `quote` | `typed_value`, `source_paths`,
  `attribution`, `time_context` are **copied from that candidate** by the server when omitted —
  and *restored* from it when the judge's copy fails the quote rule (§3.7.3): the candidate is
  authoritative for evidence, the judge for selection, ranking and interpretation.
- `not_found` is `{operation_ids: [uuid…], searched_for: str, about_class: str}`, implies
  `claim_type="not_found"` and requires `candidate_ids = []`; every `operation_id` must be in the
  job's ledger (§4.2) or the judge's own receipts (plan AT-4's ledger-cited gap).
- `conflicts_with` holds item ids (`F…`) of the same brief, mapped to claim ids at import exactly
  as `EntryReview.conflicts_with` is today (02 §2.2: `dossier_json.py:17-45`, *verified* — string
  ids resolved by the importer).
- `wrong_entity=true` keeps the item for audit and never serves it (02 §10 item 4).
- `use_class` on contact items is the extractor's classification (§2.5) and may only be
  **tightened** by the judge (`professional-public` → `personal-public-non-sensitive` →
  `sensitive`), never loosened.
- `rank` is the judge's order within the class; missing ranks are assigned by emission order.

### 2.4 The candidate record (what extraction produces)

See §4.1 for the schema; the relation is: a finding *cites* candidates, a candidate *cites* one
stored evidence source (`arv2_evidence_source`, 02 §3.5) by `source_id` and readable path, and
the provenance chain claim → finding → candidate → source → `provider_call_ledger` row is what the
import's `source_paths` and the `artifact_derivation` rows (§3.5.6) make durable.

### 2.5 Use-class, subject anchor, identity binding

- Contact candidates carry `use_class ∈ {professional-public, personal-public-non-sensitive,
  sensitive}` (`libs/clue-core/clue_core/enums.py:90-96`, *verified*) assigned by the extractor
  against the person-floor keyword lists (`arv2/person_compliance.py` `KEYWORDS`, *verified*), with
  `sensitive` for any floor hit; a `hook` must be `self-disclosed` (`attribution.kind="self"`) and
  `use_class ≠ sensitive` or it is imported `outreach_safe=false` and never served.
- Every contact candidate carries a `subject_anchor` (§4.1): the extractor must find, in the
  *same source*, the LinkedIn slug/URL from the AI Ark record **or** the employer name together
  with a title token of the record's title; otherwise `matched=false`. Unmatched candidates import
  with `identity_binding=weak` (`enums.py:99-104`), which never promotes and never drives outreach
  (02 §10 item 2; master plan line 184) — the `unbound` hook of plan AT-5.
- The person floor (`apply_person_floor`) runs on **every contact claim at import for r27**
  regardless of the advisory policy — **provisional ruling R15, flagged as founder decision D11**
  (the floor is gated off for every recipe ≥ 6 today; 02 §10 item 21 parks *stopping collection*,
  not the floor, and the master-plan law is that the floor "runs by default and redacts/marks,
  never drops", 02 §10 item 3). Today it runs only when `not advisory`
  (`quality_claims.py:587-590`, *verified*), and every recipe ≥ 6 is advisory
  (`quality_policy.py:10-11`, *verified*) — so on v25 no person claim passes the floor (plan §0
  item 26 is correct; 02 §9.2's "live-on-v25" means reachable, not exercised). r27 changes the
  predicate to `(not advisory) or recipe >= 27`; the floor redacts by sentence and logs
  (`person_compliance.py:1-20`, *verified*), it never raises. If D11 is ruled the other way, the
  predicate stays as today and the extractor's use-class marking (§3.5.3 step 3) is the only floor.

---

## §3 Stage specifications

Common to every stage: it runs inside the job's fleet task, after `begin_job` and under the work
lease (03a §5.4 item 4: `account_research_driver.py:1161`, `:1183`), on the claiming attempt;
every paid call goes through `ToolRuntime.operate` (03a §5.4 item 1: `account_research_tools.py:698-728`,
*verified* — `operations.begin` → `call_provider` → `recover_acquisitions` → `operations.body`),
so the pair `(job, kind, request)` is single-purchase and a re-drive reads the stored body
(02 §3.3); every derived output is persisted with `ResearchArtifacts.persist_body` + subject
bindings + `artifact_derivation` rows (03a §5.4 item 2); every stage ends by writing its completion
marker (03a §5.4 item 3) and its progress stamp `input_refs.v26_stage` (§6.1). A stage is
re-entrant: on entry it reads its marker and skips when present. Stage wall-clocks are settings;
a stage that times out proceeds with what landed and records `timed_out` in the ledger — except the
judge (C), which has no wall clock (founder ruling 2026-09-27, 02 §6 `CLUE_ARV2_ACCOUNT_MAX_RUNTIME_S=0`)
and is bounded by rounds and operations instead.

Stage order per job and the markers (`artifact_reference.reference_kind` : `reference_id`):

| Job | Stages in order | Marker written at the end of each |
|---|---|---|
| account | launch → A0.0 compile → A0 committee → A1 acquire → B → A3 (≤ 2 rounds, each + B) → gap round (≤ 1, + B) → wait for people pools → C-account → E-account → settle | `research_compile:<context_id>` · `research_committee:<job>:<plan_sha>` · `research_candidates_first:<job>:<plan_sha>` (after A1 + B) · `research_candidates:<job>:<plan_sha>` (the final pool, after the gap round — 03a §5.4 item 3's name) · `research_json_dossier` + `research_account_import_ready` (existing, 02 §3.11) · `research_page` per section (existing) |
| contact | claim → A2 acquire → B → A3 → gap round → wait for the account's first pool → C-contact → settle → (page by the `contact_page` continuation, §3.8) | `research_candidates_first` · `research_candidates` · dossier/import-ready · `research_page` |

`plan_sha` = sha256 of the canonical JSON of the subject's acquisition plan (§3.3.1), so a changed
plan (a new rules file, a changed setting) is a new marker and a re-drive re-runs the stage — while
the operations themselves still replay from `arv2_research_operation` when their requests are
byte-identical.

### 3.1 Launch (unchanged on the wire; recipe selection changes)

- **Trigger/inputs/outputs:** exactly 02 §1.1 — `launch_arv2_account_research@1`, one
  `arv2_research_run`, one account `arv2_research_job`, rows first, offer second
  (`account_research_launch.py:247-413`, `:469-509`).
- **What changes:** the recipe version a launch pins. `arv2_account_profile_sha256` /
  `arv2_person_profile_sha256` read `CURRENT_RECIPE_VERSION` today (02 §5.6:
  `account_research_launch.py:1177-1200`); P5 (04 §2.5, adopted by R2) routes them through
  `recipe_version_for(settings, workspace_id)` (§9.1) — the pilot version for a listed workspace,
  else `CLUE_ARV2_RECIPE_VERSION or CURRENT_RECIPE_VERSION` — so one workspace can launch at 27
  while the default stays 26; an unminted or out-of-range version is the typed refusal
  `recipe_version_unavailable` (added to the set at `:190-206`). The run row stores nothing new;
  the job's `input_refs.quality_recipe_version` is stamped at compose as today
  (`account_research_driver.py:1333-1344`).
- **`committee_cap`** (launch input 1–12, default 5; 02 §1.1) is the number A0 nominates.
- **Replay:** unchanged (run id = request digest; relaunch is a no-op, 02 §3.1). Note for rollback
  (§9.4): because the request digest includes the profile sha, a relaunch after a recipe-version
  change is a **new** run, not a no-op.
- **Failure modes:** the launch's typed refusals (02 §1.1 `:190-206`) gain `recipe_version_unavailable`;
  a `launch-v4-r27.json` that fails its hash check refuses at boot (`load_quality_resources`,
  02 §5.6), never at launch.

### 3.2 A0.0 Context compile and A0 Committee (account job; first code step)

**Trigger.** The account job is claimed (`begin_job`), composed and fenced; the `ToolRuntime`
exists (03a §5.4). Runs before any Exa call because every Exa template needs its variables and A0
needs titles.

**A0.0 — context compile (one leaf call per pinned context, cached).**
*Inputs:* the pinned context documents (ICP with `persona_map`, the `audience-persona` documents,
product-catalog/company-overview seller documents — 02 §3.4; `quality_context.py:316,355-360`,
*verified*: personas are prose documents, there is no structured title list anywhere, which is
why this step exists). *Call:* one `openrouter` `chat/completions` through `ProviderCaller` with
the `structure_material` precedent (03a §2.3), model `RESEARCH_EXTRACT_AGENT_MODEL`, label
`v26-compile`, strict JSON output:

```json
{"roles": [{"persona": "economic_buyer", "titles": ["CMO", "Chief Marketing Officer", "SVP Marketing"],
            "seniority": ["c_suite", "vp"], "functions": ["marketing"]}],
 "search_terms": {"category_tools": ["…"], "problem_terms": ["…"], "icp_terms": ["…"], "seats": ["CMO", "VP Marketing"]}}
```

validated against the AI Ark vocabularies (`SENIORITY_VALUES`, `function_values()` —
`ai_ark_client.py:76-82`, *verified*; `role_search_body` refuses unknown values, `:259-311`),
titles ≤ `CLUE_ARV2_V26_ROLE_TITLES_MAX` (12) per persona, every persona of `persona_map` present.
*ICP-authored vocabulary wins (review B §3 row 13):* when the pinned ICP document's front matter
carries a `search_terms:` block (`category_tools`, `problem_terms`, `icp_terms`, `seats`) or a
persona document carries `titles:`, the compile copies those values **verbatim** and the model
fills only the keys that are absent — vocabulary is ICP data first, model output second, and the
compile artifact records per key which it was (`source: icp|model|default`). *Oracle:* the compile
artifact of every pilot context is frozen as a fixture (`tests/arv2/v26/fixtures/compile_<context_id>.json`)
and read once by the founder (≈ 50 terms); a changed compile is a changed `plan_sha` for every
account of that context (already true). *Output/storage:* artifact
`application/vnd.clue.research-compile+json`, bound to the project (`project_bindings`), retained
as `research_compile:<context_id>`; the job's
`input_refs.v26_compile_sha` records which compile it used. *Idempotency:* keyed on `context_id`
(the pinned context, 02 §3.4) — one call per context per deployment, replayed by every account and
re-drive that shares the pin. *Failure:* invalid JSON → one retry with the repair instruction; a
second failure or a persona with zero valid titles → that persona uses `DEFAULT_ROLE_TITLES`
(a code constant per `Persona` value, `enums.py:358-367`, *verified*) and the ledger records
`role_titles_source=default` for it; the stage never fails the job. *Cost:* ≈ 6k tokens in / 0.5k
out ≈ $0.007 (Flash), one ledger row `provider='openrouter'`, Langfuse generation under span
`arv2.v26.compile`.

**A0 — committee.**
*Provider calls, in this order, all `ai_ark`, all through `operate` and therefore the global
advisory lock + `CLUE_ARV2_AI_ARK_MIN_GAP_S` (10.5 s) pacing (02 §2.3 "AI Ark pacing";
`account_research_tools.py:466-492`):*

| # | Operation kind (`arv2_research_operation.kind`) | Call | Args | Credits |
|---|---|---|---|---|
| 1 | `company_lock` (existing) | `company_by_domain(scope.account_domain)` (02 §2.3 `lookup_company`) | the account domain | 0.1 per company returned (`ai_ark_client.py:70`) |
| 2–6 | `people_roles` (existing) | `people_by_roles(titles, company_id=lock.company_id or domain=…, seniority, functions, page=0, size=CLUE_ARV2_V26_ROLE_SEARCH_SIZE)` (`role_search_body`, `ai_ark_client.py:259-311`, *verified*: SMART title match, exact employer scope) | per persona of `persona_map` in the order `economic_buyer, champion, technical_evaluator, blocker, user` with that persona's compiled titles/seniority/functions | 0.5 per record returned (`:71`) → ≤ 2.5 per role at size 5 |

The `discover_people` precondition "an attempted `account_deep` first" (02 §2.3:
`committee_discovery.py:244-253`) is **not** applied on the v26 pre-step path (the founder ruled
the title search needs no account picture); the pre-step calls the `people_roles` body directly,
not the `discover_people` wrapper. The 10.5 s gap makes the six calls a **63 s floor**; nothing
else in A0 waits.

*Ranking (pure function `committee_rank.py`, unit-tested):* for each record `r` returned for
persona `p`: `role_fit = 1.0` if every token of some compiled title of `p` appears in `r.title`
(case-folded), else `0.5` (SMART returned it); `seniority = {c_suite: 1.0, owner/founder/partner: 0.9,
vp: 0.8, head: 0.7, director: 0.6, manager: 0.4, senior: 0.3, other: 0.1}[r.seniority]`;
`footprint = 1.0` if `r.linkedin_url` else `0`. `score = 3·role_fit + 2·seniority + footprint`;
ties by AI Ark result order. *Selection:* take the best record per persona in the order above
(skipping a `provider_subject_id` already taken), then fill to `committee_cap` by global score;
records ranked 2nd–`CLUE_ARV2_V26_COMMITTEE_ALTERNATES_PER_ROLE` (3) per persona become
**committee-class candidates** (`candidate.kind="committee_alternate"`, no job) in the account
pool. A persona with zero records yields a ledger entry the judge can cite as `not_found`.

*Nomination (code, service authority):* for each selected record, the `NominateCommitteeTool`
body as a plain function (03a §8a: `quality_committee_tool.py:158-222`, *verified* `:150-230` —
`submit_proposal` of the `account.committee_selection` claim at the exact AI Ark row,
`link_selection_claim`, `save_person_brief`, `create_job(subject_type="person", input_refs={parent_job_id,
candidate_ref, discovered_via="ai_ark_role_search", persona, …})`, `register_child`), with the
mechanical brief `"<persona> candidate: <title> at <account>; research per the v26 contact contract"`
(the brief is instructions, not evidence — `person_research_brief.py:1`, *verified*). Each
contact's nomination is **its own transaction** (the body's `FOR NO KEY UPDATE` on the parent row
must not be held across A0's paced calls — review A Q61). The person jobs are born `not_started`
and are **offered by the sweep, not by the pre-step** (review A K2/C38): the pre-step runs inside
`ResearchUnitRuntime` (03a §8a), which is composed without a queue (`fleet_main.py:790-792`); the
queue is the driver's (`account_research_driver.py:2490`) and the release path is the sweep's
(`sweep_quality` → `ready_person_jobs` → `enqueue_launched_jobs`, `account_research_driver.py:951-975`,
corrected 03a §5.4). The r26 `ready_person_jobs` TRUE branch
(W1-8; `quality_person_release.py:89-92`, *verified*) makes every sweep (`CLUE_ARV2_QUALITY_RECONCILE_INTERVAL_S`
= 10 s, 02 §1.6) and the parent's own settle select them, and `enqueue_launched_jobs` offers them
with the launch's work id/dedup key (02 §1.1 `:469-509`; rows first, offer second) — so a contact
starts ≤ 10 s after its row exists. Person job id = `quality_person_job_id(run, account,
contact)` (`account_research_launch.py:150-151`, *verified*), so a re-drive nominates onto the same
rows (`create_job … ON CONFLICT DO NOTHING`, 02 §3.2).

*Outputs/storage:* the five AI Ark pages as operation results + evidence `provider_record` rows
(existing `index_acquisition`); the committee-class candidates (§4.1) in the account pool; the
person job rows (the fleet tasks follow from the sweep); marker `research_committee:<job>:<plan_sha>`.

*Idempotency/replay:* the six operations replay from `arv2_research_operation` (same request →
same id); nomination is idempotent per contact (job id, selection claim key `nominate:<op>`,
02 §2.2); the marker is read first and the whole stage skipped when present. A takeover between
nomination and the marker re-runs the stage: every write is `ON CONFLICT DO NOTHING` or
content-addressed, so the second pass is a no-op that then writes the marker.

*Failure modes and reactions:*

| Failure | Reaction (deterministic) |
|---|---|
| AI Ark 429/5xx | `ProviderCaller` retries ≤ 4 with `12·(n+1)` s / `Retry-After` (02 §2.3 Retries); then the operation is `failed` with `http_status`; the stage continues with the other roles |
| AI Ark credit halt (`CREDIT_HALT_REASON`) | latched for the job (02 §2.3); the remaining role searches are refused `provider_halted` pre-dispatch (`operate`, *verified* `:709-717`); A0 ends with what it has |
| `company_lock` finds 0 or > 1 companies | role searches use `domain=` scope instead of `company_id` (`role_search_body` accepts either, *verified*) |
| < `CLUE_ARV2_V26_MIN_COMMITTEE` (4) records across all roles | the committee **gap round** (§3.5.7) runs after B: one web search per missing seat; results with a LinkedIn URL are nominated through the `NominateBriefedWebCommitteeTool` body (`discovered_via="web_gap"`, 02 §2.2) up to `committee_cap`; the person job for such a contact uses `lookup_person(linkedin_url)` (`person_named`, 02 §2.3) in A2 instead of a kept AI Ark record |
| 0 records everywhere and the web gap finds none | the account proceeds alone; the brief's committee class is `not_found` items citing the six operation ids; no person jobs (zero yield is an honest terminal outcome, 02 §10 item 7) |
| `DBAPIError` inside `_drain` (01 §3.8 saw 2 on the 12-job batch) | the hop holds the raw response; `_drain` is retried once after 2 s (`CLUE_ARV2_V26_DRAIN_RETRIES=1`); a second failure marks the operation `failed/drain_failed` and the response is **not** repurchased (the row stays single-purchase; a re-drive sees `failed` and re-issues only because the request is byte-identical and the state is not `succeeded` — the existing `won=False` path, 02 §3.3) |
| lease lost mid-stage | the fleet cancels the work (02 §7.3); `call_provider` is shielded so an in-flight hop completes and drains (02 §2.3 "Calls are shielded"); the takeover re-enters the stage and replays |

*Budgets:* 6 AI Ark calls (fixed); wall `CLUE_ARV2_V26_ACQUIRE_WALL_S` (300 s) shared with A1.
*Cost accounting:* 6 ledger rows `provider='ai_ark'` stamped with the account job
(`LedgerStamp`, 03a §2.3); Langfuse span `arv2.v26.committee` with attributes
`roles_searched, records, nominated, alternates, wait_ms_total` (the advisory-lock wait is
already logged, 02 §8.5 item 1).
*DSAR:* unchanged from today's nomination — the selection claim cites the AI Ark row; provider
subjects are registered (`provider_identity`, 02 §3.15); a later erasure of the contact
privacy-erases the provider page and nulls `linkedin_url` (`provider.py:247-303`).

**P6 — required fix (A-owned; blocking before any r27 pilot; R14):** `stop_contact_jobs` and the
claim writer's privacy block filter `profile_ref IN ('agent-profile:arv2-person:v2', '…:v3')` while
every quality person job carries `…:v4` (02 §3.15 "Observation", `research_operations.py:292-293`,
`claim_writer.py:142-146`). A v4 — and therefore an r26/r27 — contact's privacy-stop never sets
`input_refs.privacy_stopped` on its job today. P6 widens both filters to the prefix `profile_ref
LIKE 'agent-profile:arv2-person:v%'` (04 P6 — the ref is catalog-versioned, not recipe-versioned)
with a DB test (`tests/arv2/test_privacy_stop_v4_db.py`) that a v4 person job's privacy-stop sets
the flag and the claim writer refuses; §3.9 depends on it; 05 §6 gates on it.

### 3.3 A1 / A2 Acquisition (code, one parallel batch per subject)

#### 3.3.1 The plan

`acquisition_plan.py::plan(subject, context_compile, settings) -> AcquisitionPlan` is a pure
function returning an ordered list of `PlannedOperation{template_id, kind, provider, request,
depends_on}`; `plan_sha = sha256(canonical_json(plan))`. Template variables come only from the
subject row (name, domain; for a contact the kept AI Ark record: full name, title, employer,
linkedin_url, department) and the A0.0 compile (`persona_titles`, `seats`, `category_tools`,
`problem_terms`, `icp_terms`); the date variable `since` = `today − CLUE_ARV2_V26_RECENCY_DAYS`
(270 — the nine-month window the account skill already uses, 02 §5.3) **rounded to the first of the
month** so that re-drives within a month produce byte-identical requests (and therefore replay).

#### 3.3.2 A1 — account batch (≤ 25 provider calls)

All Exa requests are `POST /search` bodies built by `search_body` (`exa_client.py:408-450`,
*verified*: `query, type, numResults, contents.text.maxCharacters`, plus `includeDomains`,
`startPublishedDate`, `contents.highlights`, `contents.extras` only when given). Account search
parameters: `type="auto"`, `numResults=CLUE_ARV2_V26_ACCOUNT_SEARCH_NUM_RESULTS` (8),
`contents.text.maxCharacters=CLUE_ARV2_V26_ACCOUNT_SEARCH_TEXT_MAX_CHARS` (1500),
`contents.highlights={"numSentences": 3, "highlightsPerUrl": 2, "query": <template highlight>}`.
`{name}` is the account's display name in quotes; `{domain}` its domain.

| # | Template id | Kind | Query template | Dated (`startPublishedDate=since`) | Highlight query |
|---|---|---|---|---|---|
| 1 | `T_leadership` | `search_web` | `"{name}" (appointed OR joins OR named OR promoted OR departs OR leaves OR steps down) ({seats OR-joined})` | yes | `{name} leadership change` |
| 2 | `T_hiring` | `search_web` | `"{name}" (hiring OR "job opening" OR careers) (marketing OR "account-based" OR "demand generation" OR "field marketing")` | yes | `{name} hiring marketing` |
| 3 | `T_stack` | `search_web` | `"{name}" (uses OR "powered by" OR integrates OR "built on") ({category_tools OR-joined})` | no | `{name} tools` |
| 4 | `T_news_funding` | `search_web` | `"{name}" (raises OR funding OR acquires OR acquired OR launches OR expands OR layoffs OR award)` | yes | `{name} news` |
| 5 | `T_abm_programme` | `search_web` | `"{name}" ("account-based" OR ABM OR "field marketing" OR "demand generation") (program OR strategy OR campaign OR playbook)` | no | `{name} marketing program` |
| 6 | `T_customers_proof` | `search_web` | `"{name}" ("case study" OR customer OR "chose {name}" OR "selected {name}" OR results)` | no | `{name} customer results` |
| 7 | `T_pain` | `search_web` | `"{name}" (frustrated OR frustrating OR challenge OR struggling OR "pain point" OR complaint OR review) (marketing OR sales OR {problem_terms OR-joined})` | yes | `{name} frustration challenge` |
| 8 | `T_succession` | `search_web` | `"{name}" ("former {seat}" OR "new {seat}" OR "interim {seat}" OR "{seat} vacancy") for the top-3 compiled seats, OR-joined | yes | `{name} successor` |
| 9 | `T_ats` | `read_ats_board` | `{company_url: "https://{domain}"}` (02 §2.3: slug read from pages, never guessed) | — | — |
| 10 | `T_account_deep` | `research_deep` | the v26 account charter (`provider-requests/account-deep/v2/exa-system.md` + the compact, evidence-first report instruction of plan W1-14), `additional_queries` = templates 1, 4, 7 rendered, `num_results=CLUE_ARV2_V26_ACCOUNT_DEEP_NUM_RESULTS` (40), contents as today (`highlights: true, extras.links: 1`, **no text** — 02 §2.3 "Exa deep-reasoning request"), surface pinned by `CLUE_ARV2_V26_DEEP_SURFACE=search-deep-reasoning` (D8: `/search type=deep-reasoning`, never `/agent/runs`) | — | — |
| 11 | `T_cited_pages` | `fetch_page` × ≤ `CLUE_ARV2_V26_ACCOUNT_CITED_FETCH_MAX` (10) | the first N distinct URLs cited in the deep report body, in citation order, `max_chars=CLUE_ARV2_V26_FETCH_MAX_CHARS` (8000), **after the sibling rule** (§3.3.4) | — | — |
| 12 | `T_homepage` (R10) | `fetch_page` | `https://{domain}`, `max_chars` 8000 — 01b T7: 38 possible A-class findings across 5 accounts came from the homepage | — | — |
| 13 | `T_site_pages` (R10) | `fetch_page` × ≤ `CLUE_ARV2_V26_ACCOUNT_SITE_PAGES_MAX` (4) | the subject-site pages the homepage links to, matched in this order on the link path: `/careers`, `/news\|/blog\|/press`, `/about\|/team`, `/benefits`; one fetch per match, a 404 tolerated (`empty`) — 01b T7/§3: 44 possible / 16 strict A across four accounts that the deep-cited pages did not reach | — | — |

`depends_on`: 11 depends on 10; 13 depends on 12; `company_lock` (A0 #1) precedes nothing here.
Issue order: 1–10 and 12 in one `asyncio.gather` bounded by the per-provider semaphores (`exa` =
`CLUE_ARV2_ACCOUNT_PROVIDER_CONCURRENCY` 4, `ats` 4; 02 §2.3), then 11 and 13.

#### 3.3.3 A2 — contact batch (≤ 19 provider calls, all five contacts at once)

Variables: `{full_name}` (quoted), `{employer}` (the account name), `{title}`, `{domain}`,
`{linkedin_url}`, `{department}` (the AI Ark record's function or the title's function word).
Search parameters: `type="auto"`, `numResults=CLUE_ARV2_V26_PERSON_SEARCH_NUM_RESULTS` (8),
`contents.text.maxCharacters=CLUE_ARV2_V26_PERSON_SEARCH_TEXT_MAX_CHARS` (1500),
`contents.highlights={"numSentences": 3, "highlightsPerUrl": 2, "query": "{full_name}"}`.

| # | Template id | Kind | Query / args | Domains / dates |
|---|---|---|---|---|
| 1 | `P_linkedin_posts` | `search_web` | `"{full_name}" {employer}` | `includeDomains=["linkedin.com"]` |
| 2 | `P_talks` | `search_web` | `"{full_name}" ({employer} OR "{title}") (podcast OR webinar OR interview OR keynote OR panel OR fireside)` | — |
| 3 | `P_bylines` | `search_web` | `"{full_name}" (author OR byline OR "written by" OR blog OR column)` | `excludeDomains=["linkedin.com"]` |
| 4 | `P_employer_mentions` | `search_web` | `"{full_name}"` | `includeDomains=["{domain}"]` |
| 5 | `P_team_postings` | `search_web` | `"{employer}" ({department} OR "{title}") (hiring OR "job opening" OR "we're hiring")` | dated `since` |
| 6 | `P_news` | `search_web` | `"{full_name}" {employer}` | `excludeDomains=["linkedin.com"]`, dated `since` |
| 7 | `P_person_deep` | `research_deep` | the v26 person charter (`provider-requests/person-deep/v2/exa-system.md`: remit, current problem, own words, proud-of, hooks — the plan's §1 contact classes; no biography sweep), `num_results=CLUE_ARV2_V26_PERSON_DEEP_NUM_RESULTS` (**12**, D9), `contents.text.maxCharacters=CLUE_ARV2_V26_PERSON_DEEP_TEXT_MAX_CHARS` (**4000**, D9), `contents.highlights={"query": "{full_name}", "maxCharacters": CLUE_ARV2_V26_PERSON_DEEP_HIGHLIGHT_MAX_CHARS (1000)}`, `extras={"links": 3}` (no `imageLinks`); `same_name_exclusions` from the compile's namesake note when present | — |
| 8 | `P_cited_pages` | `fetch_page` × ≤ `CLUE_ARV2_V26_PERSON_CITED_FETCH_MAX` (6) | distinct URLs cited in the deep report, citation order, `max_chars` 8000, after the sibling rule | — |
| 9 | `P_enrich` | `enrich_contact` | `{channels: ["email"]}` → AI Ark `/v1/people/export/single` on the kept record id (02 §2.3; `ai_ark_client.py:926-947`, *verified*) — identifiers only, no profile re-lookup, **no phone** | AI Ark pacing lock |
| 10 | `P_profile` (R10) | `fetch_page` | `{linkedin_url}` from the kept record, `max_chars` 8000 — 01b T7: 25 possible A across 5 accounts; the profile fetch behind a name lead alone carried 14 strict A | — |
| 11 | `P_post_pages` (R10) | `fetch_page` × ≤ `CLUE_ARV2_V26_PERSON_POST_PAGES_MAX` (4) | the first N `linkedin.com/posts/` URLs returned by template 1, result order, `max_chars` 8000 — 01b T7: the per-post fetch is what yields the verbatim own-words (38 possible A in four accounts) | — |

`depends_on`: 8 on 7; 11 on 1. Issue order: 1–7, 9 and 10 in one `gather`; 8 and 11 after their
dependency. For a **web-gap**
contact (§3.2) template 9 is preceded by `lookup_person(linkedin_url)` (`person_named`, size 3,
strict — 02 §2.3) and the first strict match becomes the kept record; no match → the contact is
researched from the web only and `identifier` items are `not_found`.

The `research_deep` request config files are **versioned data** (`provider-requests/*/v2/`) pinned
in `launch-v4-r27.json`; `numResults` and `type` in those files are not read (02 §2.3) — the
numbers above are the tool arguments, set from the settings. **D9 is a single bounded comparison,
not a loop** (review B §3 row 3): the pool freeze captures both request shapes (production
20 × 10k and r27 12 × 4k) in one sitting, AT-1 runs on both, and the smallest cap that holds ≥ 0.95
is pinned — once. **D8** is already pinned by the code (`type="deep-reasoning"` is hard-coded,
`exa_client.py:523`, 02 §2.3); `CLUE_ARV2_V26_DEEP_SURFACE` makes that pin an explicit, refusing
setting (the `agent-runs` surface is refused until priced); the *price* of the pinned surface is a
fit (≈ $0 over 12 runs), not a sheet entry, so §5.5 carries +$3.00 as a line until D6 prices it.

#### 3.3.4 The sibling rule (no re-purchase within an account)

Before any planned or judge-issued operation is dispatched, the runtime looks for a **sibling**:
an `arv2_research_operation` row of the same `(workspace_id, run_id, account_id, kind,
request_sha256)` that already `succeeded` on another job of the account (04 W3-22's
`SiblingDedup.find_sibling`, adopted by review A C10 — the acceptance metric "zero repurchased
`(kind, request_sha256)`" is request-sha based, and `max_chars` is 8000 in both lanes so a URL
fetch has an identical request sha). Account-level kinds only (`account_search`, `account_page`,
`account_deep`, `quality_tool:search_web`, `quality_tool:fetch_page`); person lookups are never
pooled (plan W2-18). A hit serves the sibling's stored body **and its stored `candidates` block**
to the requesting job with no provider call and **no re-extraction** (review B §1.2 row 8), and
writes a free local operation `pool_read` (kind `v26_pool_read`, request `{sibling_operation_id}`)
so the ledger shows it and replay is exact; the sibling's candidates are re-keyed to the reading
subject only for `subject`-agnostic classes (account classes), never silently re-anchored to a
contact. A person subject may read account-level sources by design
(`quality_evidence.py:423-426,499-502`, 02 §3.5). Cross-job duplicates that escape the rule (a URL
variant, a differently rendered query) are accepted and **measured** (`arv2.v26.duplicate_fetch`
counter, §8).
#### 3.3.5 Outputs and storage (both batches)

Per operation: the `arv2_research_operation` row (state `succeeded|empty|failed|unknown`), the
ledger estimate + result rows, the raw response artifact, and the evidence sources
(`index_acquisition` → `arv2_evidence_source` rows `provider_record` / `web_snapshot` /
`research_report`, readable at `/evidence/NNNN-slug.json` — 02 §2.3, §3.5). v26 adds nothing to
these tables. The batch's **acquisition ledger** (§4.2) is derived from the rows, not stored
separately, and is embedded in the pool artifact (§3.5.5).

#### 3.3.6 Idempotency and replay

Operation identity is `uuid5("arv2-operation:v1:<ws>:<job>:<kind>:<sha(request)>")`
(`research_operations.py:55-66`, *verified*) — the plan renders byte-stable requests
(§3.3.1), so a re-drive re-issues the same requests and reads the stored bodies
(`won=False` → `operations.body`, *verified* `:698-728`). A `running` row whose 2-hour lease
expired becomes `unknown/dispatch_outcome_unknown` (02 §3.3) and is never repurchased by the
pre-step: it is a ledger entry the judge may cite. The batch is complete when every planned
operation is in a terminal state or the wall-clock expired; the marker `research_candidates_first`
is written only after B (§3.5) over the whole batch.

#### 3.3.7 Failure modes and reactions

| Failure | Reaction |
|---|---|
| Exa 429/5xx | retries as 02 §2.3 (4 attempts, backoff); then `failed` + `http_status`; the plan continues |
| Exa deep thin response | the existing one retry (`is_thin_deep_response`, 02 §2.3); an account deep still thin → `RefusalError("deep_thin_response")` → state `empty`; a person deep empty → `gaps:["deep_report_empty_review_returned_sources"]` (02 §2.3) — both are ledger entries, the batch continues |
| Empty results | state `empty`, `result_count=0`; feeds `not_found` |
| ATS board not found | `read_ats_board` returns no postings (02 §2.3); ledger `empty` |
| AI Ark `subject_lock_failed` on `enrich_contact` (01 §3.8: 4 on the 12-job batch) | retried once after `CLUE_ARV2_V26_SUBJECT_LOCK_RETRY_S` (15 s); then `failed/subject_lock_failed`; the email is absent, the contact proceeds |
| `DBAPIError` in `_drain` | as §3.2 (one drain retry, then `failed/drain_failed`, no repurchase) |
| every operation of the batch failed (no `succeeded`, no `empty`) | stage `failed_provider`; the job lands `needs_review/acquisition_failed` via `_contain` (02 §1.2) — a re-drive replays what succeeded and re-issues the failed requests |
| the batch produced only `empty` operations | **not** a failure: the subject proceeds to B (nothing to extract), A3 (nothing to follow), the gap round (fires for every class with a minimum) and the judge, which investigates within budget and emits `not_found` items; honest empty pages follow |
| wall-clock `CLUE_ARV2_V26_ACQUIRE_WALL_S` (300 s) | operations still in flight are left to complete under the shield; the stage proceeds with the landed ones and records `timed_out` |
| lease lost | as §3.2 |

#### 3.3.8 Budgets, cost accounting, DSAR

Budgets are the fixed counts above (account: 8 searches + 1 ATS + 1 deep + ≤ 10 cited fetches + 1
homepage + ≤ 4 site pages = ≤ 25 Exa/ATS calls; contact: 6 searches + 1 deep + ≤ 6 cited fetches +
1 profile + ≤ 4 post pages + 1 export = ≤ 19) and the wall-clock; the four R10 templates add
≈ $0.12 per account + 5 at the fetch price. Cost: every call is a ledger row
with the job stamp; the job meter sums them (02 §3.6, §8.2). Langfuse: span `arv2.v26.acquire`
per batch with `ops_issued, ops_succeeded, ops_empty, ops_failed, provider_ms_sum, drain_ms_sum,
pool_reads` and the provider spans beneath it. DSAR: sources are job-keyed and subject-bound as
today (02 §3.5); a contact's privacy-stop makes `job_available` false and the stage checks it
before every operation (`operate` → `job_available`, 02 §2.3), so a stopped contact's batch ends at
the next operation boundary with `privacy_stopped` in the ledger.

### 3.4 A3 Guaranteed follow-ups (code, table-driven — the floor)

**Trigger.** After B has run over the subject's batch (§3.5) and produced the first pool; runs
≤ `CLUE_ARV2_V26_FOLLOWUP_ROUNDS_MAX` (2) rounds, each round followed by B over its results.

**The rule table** is **data, not code** — `platform/agents/catalog/research-quality/followups/v1/rules.json`,
pinned by sha in `launch-v4-r27.json` like every other resource (02 §5.6), so a changed table is a
new resource version and a different `plan_sha`. Its rows are **01b's recommended floor, verbatim**
(R9: the eleven pairs of 01b §3 "Recommended floor", delivered as
`.artifacts/arv2-research-runs-20261007/fixtures/rule_table.json`, 01b §8), converted into the shape
below by W0 (04 §1); this section fixes the shape, the trigger grammar and the executor. Each rule:

```json
{"rule_id": "person_named_in_result", "subject": ["account", "contact"],
 "trigger": {"kind": "entity", "entity_kind": "person", "classes": ["trigger", "committee", "remit", "problem_now", "own_words"]},
 "operations": [
   {"kind": "search_web", "query": "\"{entity.text}\" \"{name}\"", "dated": false, "num_results": 8},
   {"kind": "fetch_page", "url": "{result.linkedin_url}", "when": "a result URL is a linkedin.com/in/ profile", "round": 2}
 ],
 "max_per_trigger": 1, "max_per_round": 4, "dedupe": "{entity.text}"}
```

(`max_per_round` is **per rule**; the cut across all rules in a round is
`CLUE_ARV2_V26_FOLLOWUP_OPS_PER_ROUND_ACCOUNT` / `…_PERSON` = 11 / 8, §10 C5.)

**Trigger kinds** (closed set, validated at resource load; review B §2.2 item 1 is why `entity`
exists):

| `trigger.kind` | Fires on | Variables it defines |
|---|---|---|
| `entity` (R9) | a candidate of one of `classes` whose extractor-emitted `entities[]` (§4.1) contains an entity of `entity_kind ∈ person \| org \| vendor \| programme \| event \| url \| phrase \| prior_employer \| subject_site_page \| title` | `{entity.text}`, `{entity.kind}`, `{candidate.source.url}`, `{candidate.source.host}`, `{candidate.quote}`, `{candidate.typed_value}`, `{candidate.finding}` |
| `class_terms` | a candidate of `class` whose `finding` contains any of `any_of` (case-folded token match on extractor output, never on prose the agent wrote) | the candidate-field variables above |
| `attribute` | a candidate whose `source.kind`, `attribution.kind` or `evidence.value_kind` equals `value` | the candidate-field variables above |
| `ledger` | a ledger entry of `template` in `state ∈ empty \| failed` — a lead that *failed* (ATS empty ⇒ a jobs-site search) | `{template}` |
| `result` (round 2 only) | a result URL of a round-1 follow-up matching `when` (host or path pattern) | `{result.url}`, `{result.linkedin_url}` |

Subject and compile variables (`{name}`, `{domain}`, `{full_name}`, `{employer}`, `{title}`,
`{seats}`, `{category_tools}`, …, §3.3.1) are available in every template. Operation kinds allowed:
`search_web`, `fetch_page`, `read_ats_board`; `discover_people` (account only); `lookup_person`
(contact only, a URL lead — a seeded job refuses a name search, `committee_discovery.py:697-710`,
review A Q3 — so a **person-name** lead on a contact job issues `search_web` and, in round 2, the
profile `fetch_page`); `read_media` only when §7's gate is on.

**The eleven floor rows** (01b §3, in order of strict yield; each must *fire* on a synthetic
candidate in `tests/arv2/v26/test_followups.py` — plan AT-3(c) is "fires", not "exists"):

| # | 01b trigger | Rule (trigger kind → operations) |
|---|---|---|
| 1 | a person named in any result | `entity:person` → `search_web "{entity.text}" "{name}"`; round 2: `fetch_page {result.linkedin_url}` when a profile URL is returned (01b: the profile fetch alone 14/20 strict A) |
| 2 | a vendor named in a result | `entity:vendor` → `search_web "{entity.text}" "{name}" (customer OR "case study" OR partner)`; round 2: `fetch_page {result.url}` when the host is the vendor's |
| 3 | an exact phrase worth its own search (a title, programme or award name, a product line) | `entity:phrase` → `search_web "{entity.text}" "{name}"` |
| 4 | a URL in a result that is not the homepage/board/profile | `entity:url` → `fetch_page {entity.text}` (press item, article, aggregator, filing) |
| 5 | a page on the subject's own site surfaced by a result | `entity:subject_site_page` → `fetch_page {entity.text}` (careers, benefits, news/blog, team) |
| 6 | a talk, podcast, webinar or event named with the subject | `entity:event` → `search_web "{entity.text}" "{full_name \| name}"`; `read_media` only under §7 |
| 7 | a prior employer, board or association named on the profile (contact) | `entity:prior_employer` → `search_web "{full_name}" "{entity.text}"` (hooks, do-not-mention) |
| 8 | education / prior-employer disambiguation for a common name (contact) | `entity:prior_employer` with `attribute:subject_anchor.matched=false` → `search_web "{full_name}" "{entity.text}" {employer}` — the namesake guard (its yield is C-class exclusions, 01b) |
| 9 | a departure in a result | `class_terms trigger any_of[departs, departure, left, steps down, former, stepped down]` → `search_web "{name}" ("new {seat}" OR "interim {seat}" OR "appointed {seat}" OR "{seat} successor")`, dated — plan-mandated (the Dialpad "no named successor" item) |
| 10 | a marketing/function job listing in a result | `entity:url` on class `trigger\|problem_now` whose host is a jobs site **or** `attribute:source.kind=ats_posting` → `fetch_page {entity.text}` (the full posting) — plan-mandated |
| 11 | a committee candidate (alternate) | `attribute:candidate.kind=committee_alternate` → `fetch_page {candidate.linkedin_url}` and `search_web "{candidate.name}" {employer}` on `includeDomains=[linkedin.com]` — plan-mandated; covered by #1 and the own-post template for nominated contacts |

Pairs 01b found in one account only (initiative/programme name, partner/channel, press-release
URL, location) are **not** rows: they are the judge's discretion, which it keeps (§3.6.2).

**Executor** — `followups.plan_followups(pool, ledger, rules, round) -> list[PlannedOperation]`,
a pure function (plan AT-3's unit test): evaluate every rule against every candidate/ledger entry
of this subject, dedupe by the rule's `dedupe` key across *both* rounds and against every request
already in the ledger (the sibling rule, §3.3.4), order by `(rule position, candidate rank)`,
cut at `CLUE_ARV2_V26_FOLLOWUP_OPS_PER_ROUND_ACCOUNT` (**11**) / `…_PERSON` (**8**) — 01b T1's
per-run maxima (21 account / 14 contact follow-ups over ≤ 2 rounds) + 1, applied now rather than
after RC-2 (review B §1.2 row 10); `max_per_round` applies per rule. Round 2 sees round 1's
candidates (a chain: departure → successor search → "no successor" candidate → nothing further;
vendor → vendor search → customer page) — the depth-2 mechanism 01b T4 shows carries 8 A-class
findings.

**Outputs** are ordinary operations (§3.3.5) with `kind = "v26_followup:<rule_id>"` so the ledger
names the rule, plus — in the ledger entry — **`follows`** = `{operation_id: <the operation whose
result carried the trigger>, candidate_id: <the triggering candidate> | null, rule_id}` (R9: the
operation id of the trigger is mandatory for every A3 operation; it is what plan AT-9's chain-recall
test joins on). **Replay:** the same pool produces the same plan; the operations replay.
**Failures:** per operation as §3.3.7; a rule whose template cannot render (missing variable) is
skipped and logged `followup_rule_unrenderable` — never a job failure. **Budget:** ≤ 2 × 11 = 22
account / ≤ 2 × 8 = 16 contact operations. **Cost/telemetry:** span `arv2.v26.followups` per round
with `rules_fired{rule_id}`, `ops`, `deduped`.
### 3.5 B Extraction (cheap model, throw-away context, subject anchor) and the gap round

#### 3.5.1 Trigger and inputs

Runs over every evidence source the subject's operations produced (A1/A2, each A3 round, the gap
round) that has text — `web_snapshot` bodies, `research_report` bodies, deep-call per-result
`text`/`highlights` (`exa_source_texts`, `quality_acquisition.py:268-281`, *verified*), search
result texts/highlights, ATS posting descriptions — and **not** over `provider_record` rows whose
prose is dropped by policy (AI Ark `enrichment_only`, 02 §2.3). The deep call's per-result texts
are extracted when `CLUE_ARV2_V26_EXTRACT_DEEP_RESULT_TEXT=true` (default: at the D9 pin of
12 × 4k chars they are ≈ 12k tokens per contact ≈ $0.009 on Flash, and they carry the own-words
spans plan AT-1 measures recall against). The same function serves the judge's follow-ups inside
`acquire_research_evidence@2` (03a §8b), so there is one extractor.

#### 3.5.2 The call

Model `RESEARCH_EXTRACT_AGENT_MODEL` / `_EFFORT` (R12: a leaf call, no `AgentRole`; default
**`google/gemini-3.8-flash`** — D4's recommended pick, review A C18 / review B §3 row 1; a D4 ruling
for Luna is an env change. The Luna comparison is run **once** at the pool freeze: AT-1 on both
models over the same pools, ≈ $0.2; Luna is adopted iff its recall ≥ Flash − 0.01 on every pool),
through `ProviderCaller` on the thread pool with the `structure_material` precedent
(03a §2.3; `runtime.call_provider("extract", hop)` with the `extract` semaphore key, 03a §8b).
Batching: sources ≤ `CLUE_ARV2_V26_EXTRACT_CHUNK_CHARS` (20,000) are packed
`CLUE_ARV2_V26_EXTRACT_BATCH_SOURCES` (4) per call up to `CLUE_ARV2_V26_EXTRACT_BATCH_MAX_CHARS`
(24,000); a larger source is chunked at 20,000 chars with `CLUE_ARV2_V26_EXTRACT_CHUNK_OVERLAP_CHARS`
(500) overlap, one call per chunk (a 56k-char deep report = 3 calls). The instruction block
(≈ 2k tokens: the class table of §2.1 for the subject kind, the quote rule, the anchor rule, the
use-class rule, the output schema, **no seller context** — the extractor classifies, it does not
judge fit) is byte-identical across calls so the provider's prefix cache serves it (03a §4.4).
Request: `openrouter_chat_request` with `temperature=0`, `max_tokens=CLUE_ARV2_V26_EXTRACT_MAX_OUTPUT_TOKENS`
(**2000**, R16(c) — a structural per-call output bound; a batch whose output would exceed it is
**split in half and re-run**, §3.5.4, so the bound never costs candidates), JSON mode; the subject
block names the subject (account name/domain; contact name, title, employer, LinkedIn slug) so the
anchor check has its targets. Concurrency: `CLUE_ARV2_V26_EXTRACT_CONCURRENCY_PER_JOB` (6) and a
handler-wide `CLUE_ARV2_V26_EXTRACT_CONCURRENCY_PER_PROCESS` (16) semaphore (so six jobs on one
worker cannot open 36 OpenRouter streams). Wall-clock `CLUE_ARV2_V26_EXTRACT_WALL_S` (180 s) per
stage. **Call count** per subject ≤ `CLUE_ARV2_V26_EXTRACT_MAX_CALLS_ACCOUNT` (120) /
`…_PERSON` (60) — 2× the expected 60 / 30 (review B §1.3's "cheap move", added so the extraction
line of the structural ceiling is a pure function of settings); past it a source is marked
`extract_skipped/budget` and the judge's ledger says so.

Output per call: `{"candidates": [Candidate…], "rejected": [{"finding": "...", "reason": "no_quote"}]}`
in the §4.1 schema minus the server-stamped fields — every candidate carrying its **`entities[]`**
(R9: `{kind, text}` for every person, org, vendor, programme, event, URL, phrase, prior employer,
subject-site page or title the candidate's source names, so every floor row of §3.4 has something
to fire on). **No cap on candidates** (plan AT-1).

#### 3.5.3 The mechanical checks (code, after every call)

1. **Quote rule (plan AT-7 as 01b §5 refines it — R8), mechanical, two branches.** For
   `evidence.kind="quote"`: split on at most one marked elision `[…]`; each span must have
   ≥ `CLUE_ARV2_V26_QUOTE_ELISION_MIN_WORDS` (8) words when an elision is present; accept iff
   `quote_verdict(span, source_text) == "EXACT"` for every span, where `quote_verdict` is
   **`substring_verdict` extended** (`arv2/text.py:44-67`, *verified*: NFKC, straight quotes,
   collapsed whitespace, case-fold, non-alphanumerics blanked) by 01b §5's three additions applied
   to both sides before the existing normaliser: literal escape sequences (`\n`, `\t`, `\r`) folded
   to whitespace, every dash variant folded to `-`, boundary punctuation stripped; and by one rule
   the existing normaliser already enforces because it keeps digits — digits and dates inside a span
   must match exactly (a restated year or contract length is `NOT_FOUND`, the one legitimately
   meaning-changing kind 01b found). `source_text` is the stored body of the cited source (never
   the extractor's input copy). `PARTIAL` is a rejection (`quote_partial`), as is a quote longer than
   `CLUE_ARV2_V26_QUOTE_MAX_CHARS` (600; a field bound, not a prose count). The regression is 01b's
   `fixtures/quote_fidelity.json` (488 judged spans; 55/89 verbatim on fetched pages): AT-7's
   ≥ 41/43 target on the Dialpad spans plus 01b's eight boundary-punctuation and four digit/date
   cases as named fixtures. For
   `evidence.kind="typed"` (`value_kind ∈ number|date|money|title|location`): the slice
   `source_text[source_offset : source_offset + len(raw)]` must normalise to `raw`, and `value`
   must parse from `raw` by kind (digits after separator stripping; ISO date from a parsed date;
   `normalize_for_match` equality for title/location). Rejected candidates are kept in the
   operation's result under `rejected[]` with the reason — audit, never shown to the judge.
2. **Subject anchor** (contact only): `matched=true` iff the cited source body contains the
   LinkedIn slug/URL, or the employer name and ≥ 1 title token (case-folded, `normalize_for_match`).
3. **Use-class** (contact only): the extractor's class is overridden to `sensitive` when any
   person-floor keyword category matches the candidate's `finding` or quote (the
   `person_compliance.KEYWORDS` lists, *verified*), recorded in `verdict.floor[]`.
4. **Class validity**: a candidate whose `class` is not in the subject's class set is dropped
   (`class_invalid`) — this is how the dropped categories of §2.1 stay out.
5. **Date**: `date` must be ISO `YYYY-MM-DD` or `YYYY-MM`; `date_basis ∈ published|stated_in_text|none`;
   an unparseable date becomes `null/none`.

Every drop is counted per source and reason; nothing raises (a raise inside the acquire tool is a
failed node that blocks finalization, 03a §5.5).

#### 3.5.4 Failure modes

| Failure | Reaction |
|---|---|
| truncated output (`finish_reason=length`) | **deterministic halving**, never a retry of the same request: a batch is split into two batches (a single chunk into two half-chunks with the overlap) and both re-run; a chunk already at `CLUE_ARV2_V26_EXTRACT_MIN_CHUNK_CHARS` (2,000) that still truncates is marked `extract_failed/length` (review B edit 9 — the 6k-output cliff is gone) |
| invalid JSON (not truncation) | one retry (`CLUE_ARV2_V26_EXTRACT_RETRIES=1`) with the repair instruction appended; then the source/chunk is marked `extract_failed` in the ledger, zero candidates, the stage continues; counted (plan AT-1 reads it) |
| OpenRouter 429/5xx | `ProviderCaller` retries (02 §2.3); then `extract_failed/http` for that call |
| model refuses / empty output | `extract_failed/empty`; continue |
| wall-clock | the sources still unextracted are **re-run once** after the wall with the per-process semaphore halved (a 429 storm is the usual cause); any still unextracted → the subject lands `needs_review/extract_incomplete` — **loud, never a silently thinner pool** (review B §3 row 16); a re-drive extracts only what is missing |
| call budget `CLUE_ARV2_V26_EXTRACT_MAX_CALLS_*` reached | the remaining sources are marked `extract_skipped/budget`; the judge's ledger lists them and it may request any of them through `fetch_page` (served from the stored body, §3.3.4, which **does** spend one extraction call of the judge's own budget) |
| `DBAPIError` persisting the pool | one retry; then `needs_review/pool_persist_failed` (the operations and raw candidates are in the operation results already, so a re-drive re-persists without re-extracting) |

#### 3.5.5 Outputs, storage, idempotency

Candidates are stored **inside each operation's result value** (`value["candidates"]`,
`value["rejected"]`, `value["extraction"]={model, prompt_version, calls, chars_in, tokens}`),
so the `won=False` replay path serves them unchanged (03a §8b) and a re-drive extracts only
operations whose result has no `extraction` block (per-operation idempotency). After A1/A2 + B,
after each A3 round + B, and after the gap round + B, the subject's **pool artifact**
`application/vnd.clue.research-candidates+json` = `{subject, plan_sha, candidates[], ledger[],
stats}` is persisted content-addressed with `subject_bindings=((subject_id,"research"),)`,
`project_bindings`, and `artifact_derivation` rows from **every source artifact** to the pool
artifact (03a §5.4 item 2, §7.3), then retained as `research_candidates_first:<job>:<plan_sha>`
(the first pool, after A1/A2 + B) and `research_candidates:<job>:<plan_sha>` (the final pool, after
the gap round — 03a §5.4 item 3's marker; review A C9/C11: two markers because the contact judge
waits on the first and the account judge on the final). The final pool is the only thing C reads
(§4). `scripts/` get `arv2_v26_freeze_pool.py` to dump a job's
final pool + sources for the replay gate (plan §6).

#### 3.5.6 Cost accounting and DSAR

Ledger rows `provider='openrouter'`, `label='extract-<operation_id>[-<chunk>]'`, job-stamped,
`cost_usd` from `openrouter_cost_reader` (03a §2.3) — the meter counts them; Langfuse generations
under span `arv2.v26.extract` (`sources, calls, chars_in, candidates, rejected{reason}, floor_hits`).
DSAR: the pool artifact is bound to the subject and derived from every source, so a contact's
erasure cascades to it through `artifact_erase_derivatives` (02 §3.7) and a privacy-erased
source's candidates are unreadable with it. **The extractor's own envelope needs an explicit
binding** (review A K3, corrected here): a `ProviderCaller` call writes its request — the source
text, i.e. the contact's quoted words — inside the ledger's response envelope artifact
(`ledger.py:258-266`, corrected 03a §7.3), and because the extraction hop runs through
`call_provider` with **no** `arv2_research_operation`, nothing binds that artifact to the subject
(today `_drain` binds nothing; `index_acquisition` skips `openrouter` rows, `quality_acquisition.py:53`).
So after every extraction call **`_drain`** (`account_research_tools.py:596-688`; 04 W3-23) — the
one site both callers (the pre-step for A1/A2/A3/gap, `acquire@2` for a judge follow-up) pass
through, for calls labelled `extract-*` — records `agent_artifact_subject(subject)` on the call's
`response_artifact_key` (`ledger.py:258-266` is where the key is known) and one
`artifact_derivation` row from each source artifact of the batch to it, in the same transaction
that stores the operation's `candidates` block — the erasure trigger
then cascades to the envelope exactly as it does to the pool. Without
this the envelope is residue of the `[M10.5×M9.3]` class (`CLAUDE.md`); with it, no v26 artifact
holding personal text is unbound.

#### 3.5.7 The mechanical gap round (plan AT-2)

After the last A3 round + B, count the subject's **accepted** candidates per class (quote-verified
and, for contacts, `matched=true`). For every class whose count is below its `…_MIN_*` setting,
issue that class's `gap_templates` from `rules.json` (≤ `CLUE_ARV2_V26_GAP_OPS_PER_CLASS` (2) per
class; one round, `CLUE_ARV2_V26_GAP_ROUNDS_MAX=1`), then B. The committee gap additionally
nominates (§3.2). Gap operations are `kind="v26_gap:<class>"`. The judge is told, in its ledger,
which minimums were unmet before and after the gap round; a minimum still unmet is the judge's to
investigate (it has the budget) and, failing that, to record as `not_found`. The gap round is
**pre-judge only** — the pool must be final before the turn is assembled (03a §5.4 item 5).

### 3.6 C Judge + investigate (the governed turns)

Both judges are one governed Deep Agent turn each on the runtime 03a §1 describes; nothing in the
graph, the middleware order, checkpointing, `finalize_turn` or `recover()` changes. What is new is
the profile (role, prompt, tools, pins), the opening context (§4.3), the tool-result clearing
(§5.3) and the per-role budgets (§5.4). The account judge waits for its contacts' pools; the
contact judge takes the account's **first** pool (§3.6.4).

#### 3.6.1 Profiles

| | `quality-account-research/v27` | `quality-person-research/v27-person` |
|---|---|---|
| `role` | `account_research` | **`person_research`** (R4; new `AgentRole` member; 03a §2.2 — resolved by `quality_profiles` for person scopes at the ladder; its `PERSON_RESEARCH_AGENT_MODEL`/`_EFFORT` lines in the model block; the driver's `ARV2_PERSON_AGENT_MODEL` override stays; the six role CHECKs widened by the W3-26 migration, §1.1; user-facing text says "contact") |
| prompt | `prompts/quality-account-research/v27/SYSTEM.md` — **self-contained**: the contract (§2.1 classes, caps as text, minimums), the judge's job (select, merge, rank, interpret, investigate), the tool semantics (candidates not pages; `follows`; the ledger), the brief format, the finish sequence. ≈ 5k tokens. The judge needs no skill read to work. | `prompts/quality-person-research/v27-person/SYSTEM.md`, ≈ 4.5k tokens, same shape for the contact contract |
| skills pinned (mounted read-only for on-demand `read_file`; the resource map lists them) | `campaign-brief-account/v1` (the §2 contract and record, long form), `governed-evidence/v5` (trust rules) — no `person-research-briefing` (A0 nominates in code with §3.2's template brief; 04 W3-24) | `campaign-brief-contact/v1`, `governed-evidence/v5` |
| tools pinned | `acquire_research_evidence@2`, `search_evidence@3` (W1-3's non-raising version), `submit_brief@1` (+ `finalize_turn`) | `acquire_research_evidence@2`, `search_evidence@3`, `submit_brief@1` |
| acquire operations allowed (the `ACQUISITIONS` filter, 02 §2.3) | `search_web, fetch_page, read_ats_board, lookup_company, discover_people, read_people_result` — **no** `research_deep` (pre-step only; deliberate, review A §3), **no** media (§7) | `search_web, fetch_page, lookup_person, enrich_contact` — no `research_deep`, no media |
| `model.model_id` / `max_output_tokens` / `temperature` | `x-ai/grok-4.6` (overridden by `ARV2_ACCOUNT_AGENT_MODEL`, 02 §5.1) / **16384** (as v25; C36) / 0.0 | `x-ai/grok-4.6` (`ARV2_PERSON_AGENT_MODEL`) / **12288** / 0.0 |
| workspace | as v25 (`readable .deepagent inputs context work outputs research evidence reads`, writable `work outputs`) — but with **raw views off** (R16(a), `CLUE_ARV2_V26_JUDGE_RAW_READS=false`): for an r27 judge `ResearchViewMount` serves `/research/context.json`, `/research/claims/*`, `/evidence/index.json`, the dossier views, the materialised `inputs/candidates-*.json` and **`/research/operations/<id>/candidates.json`** — a new view (04 W1-4) that renders the operation's `candidates` block + ledger entry as whole JSON (never the raw result); `/research/operations/<id>/0.json`, `/<N>.json` and every `/evidence/*` body are refused with a receipt-shaped payload (`{refused: "raw_reads_off", use: "search_evidence or the candidates file"}`) — a `ReadResult(error=…)`, not a raise. `search_evidence@3` (bounded matches with context) is the only way to look inside a page | same |
| delegation / `max_plan_nodes` | none / 64 | same |
| nominate tools | **none** (A0 nominates; alternates are brief items; D10) | — |

The dossier tools (`save_dossier_section@1/@2`, `update_dossier_findings@1/@2`, `validate_dossier@1`,
`finish_dossier@1`, `begin/discard_dossier_revision@1`) stay registered (replay of v25/r26 jobs) but
are **not pinned** by the r27 profiles — the judge emits the brief in one `submit_brief@1` call
(R3; 04 W3-24 adopts it and drops the save/validate/finish sequence for r27). `recipe-v27.json`
allowlists exactly the pinned tools plus `finish_dossier@1` (which `submit_brief` calls internally,
§3.7). The judge does **not** write `/outputs/research.json` itself: the completion guard builds it
from storage (`quality_research_wiring.py:1013-1062`, 02 §1.3; review A Q66).

#### 3.6.2 The loop

Round 1: the model receives the system prompt + the L7 task message (the pool, the ledger, the
persona/ICP block — §4.3) and, by `tool_choice="required"` (03a §1.1), issues tool calls: any
mix of `acquire_research_evidence@2` follow-ups (each returns ≤ `CLUE_ARV2_V26_RECEIPT_CANDIDATES_MAX`
(20) candidates inline within the 10 KiB receipt bound, the full list at
`/research/operations/<id>/candidates.json` — the r27 view, §3.6.1; the receipt's `candidates_path`
names it), `search_evidence@3`, `read_file` on that path or on `inputs/candidates-*.json` (rare, discouraged by
the prompt), or `submit_brief@1` when satisfied. The prompt tells it: investigate every lead it judges worth a
hop — a follow-up costs one operation of the budget and a few hundred tokens, nothing else; cite
candidates by id; a `not_found` needs an operation id; a synthesis needs two sources; one
interpretation line on the classes that require it. Expected rounds: account 7, contact 5
(plan §3); hard caps `CLUE_ARV2_V26_ACCOUNT_MAX_MODEL_ROUNDS` (20) / `…_PERSON_…` (12), enforced by
`TurnBudgetMiddleware` (finalize-only from `max−2`, warnings for 3 rounds before — 03a §1.1), and
operation caps `CLUE_ARV2_V26_ACCOUNT_MAX_OPERATIONS` (30) / `…_PERSON_…` (15), enforced inside
`acquire@2` as a non-spending refusal value `operation_budget_exhausted` (03a §8e). The last two
rounds of every successful turn are `submit_brief` then `finalize_turn` (alone in its batch,
02 §2.4).

#### 3.6.3 `acquire_research_evidence@2` (the judge's investigative surface; minted once in r26)

`@2` is **minted once, in r26 (W1-5), with the r27 shape already present** (R13 / 04 §0.4): on r26
it returns content-bearing receipts with `candidates = ()` and `ledger`; on r27 the extractor fills
`candidates`. No `@3` — which means the **`Candidate` model (§4.1, including `entities[]`, the
nested `CandidateSource`/`CandidateEvidence`/`CandidateAnchor`/`Entity` models and the
`subject_anchor`/`use_class`/`verdict` fields) and the `LedgerEntry` model (§4.2, including
`follows`) are FINAL at the r26 mint**: the output sha the r26 profiles pin is computed over them,
so any field added later is a new version and a re-mint. The r27 extractor and executor only
populate what r26 declared. Input: `AcquireResearchInput2 = {operation, arguments, purpose?: str ≤ 200,
follows?: str}` — `purpose` and `follows` (a candidate id or an operation id — the lead) ride the
ledger entry (review A C6: 03 wins; without `follows` AT-9 cannot be computed on judge follow-ups).
Body: every step of `@1` (02 §1.4, `quality_provider_tools.py:124-215`), with the sibling rule
(§3.3.4) before dispatch, the operation-budget count before `operations.begin` (03a §8e; predicate
`kind LIKE 'quality_tool:%' AND state <> 'failed'` — an argument refusal creates a `failed` row and
must not spend the budget, review A C27), and B (§3.5) after `tool.ainvoke` and before the result
artifact (03a §8b; a sibling hit serves the sibling's stored candidates and runs no extraction).
Output `AcquireResearchReceipt2` (nested `ToolOutput` models declared — `ReceiptItem`,
`Candidate`, `ReceiptOutcome`, `LedgerEntry`; `class` via alias with `populate_by_name`, review A
Q29/Q30):

```
operation_id · status ∈ completed | refused | unavailable | tool_error | outcome_unknown (C7: the
  plan's W1-5 literal — a failed media read is `unavailable`, an exception `tool_error`, never
  `completed`) · result_path · error_code · reason (≤ 300 chars of the body's detail/gaps) · recovery
  · replayed · outcome {provider, kind, result_count, http_status} · items[≤ 20] {title, url, kind,
  published, snippet ≤ 600, path} (r26's content-bearing half) · candidates[≤ 20] (§4.1 records) ·
  candidates_total · ledger (the §4.2 entry: op, kind, template|rule_id, state, result_count,
  http_status, candidates, rejected, follows, pool_read, provider_ms)
```

Items and candidates are truncated so the serialised receipt stays ≤ 10 KiB, under the 12 KiB
spill line (03a §1.3; 04 W1-5); the full candidate list is at `/research/operations/<id>/candidates.json`
(the r27 view, §3.6.1; the receipt's `candidates_path` names it). Replay: `DOMAIN_IDEMPOTENT`,
`operation_id_required`, the stored result (candidates included) is served on `won=False` and by
the journal (03a §5.2). Refusal values (returned, never raised — 03a §8e):
`operation_unavailable_for_subject`, `invalid_acquisition_arguments`, `operation_budget_exhausted`,
`provider_halted:<p>`, `privacy_stopped`. Registration: `@2` beside `@1` in `quality_tools`, both
instances built from the same `acquisition_runtime` and both given the `QualityProviderWriter`
replacement (`quality_research_wiring.py:522-532`, `:740`; review A Q31).
#### 3.6.4 What each judge waits for (deterministic, recorded)

- **Account judge** waits until every registered child has `research_candidates` (its final pool) **or** is
  terminal (`needs_review`/failed) **or** `CLUE_ARV2_V26_PEOPLE_POOL_WAIT_S` (240 s, polled every
  5 s) has elapsed since the account's own final pool; the L7 then embeds exactly the pools
  present and the ledger names the contacts whose pool was absent — so the turn's context is a
  recorded fact (its sha in the context receipt, 03a §3.4) and replay re-reads the same L7.
- **Contact judge** waits for the account's `research_candidates_first` (the first pool, A1 + B,
  which lands ≈ 1.5 min before any contact's final pool) up to `CLUE_ARV2_V26_ACCOUNT_POOL_WAIT_S`
  (120 s); then proceeds with the class-filtered slice present (possibly empty, recorded).

#### 3.6.5 Failure modes

| Failure | Reaction |
|---|---|
| model 429/5xx/stall | **no fallback model** (R16(b): `CLUE_ARV2_V26_FALLBACK_MODELS=` empty — the research roles' model is built without the global `CLUE_AGENT_FALLBACK_MODELS` chain, so a primary failure can never silently reprice the run at a model the price sheet does not carry); the gateway's own retries and first-token timeout apply (`max_retries` 2, `CLUE_AGENT_FIRST_TOKEN_TIMEOUT_S`); when they are exhausted the turn is **suspended** (`suspend_job`, attempt-fenced, requeued with `available_at = now + CLUE_ARV2_V26_MODEL_RETRY_DELAY_S` (60 s)) and resumes from its checkpoint on the next claim, ≤ `CLUE_ARV2_V26_MODEL_RETRY_SUSPENDS` (3) times per turn (counted on `input_refs.v26_model_suspends`); the next failure lands **`needs_review/model_unavailable`** — the only way that code is reached, and never a priced call on another model; a failed call still counts one round |
| tool refusal values | read by the model; no repair round is charged for a refusal *value* (only raised `GovernedToolFailure`s are budgeted, 03a §1.3) |
| `submit_brief` returns `{accepted: false, errors[]}` | the model fixes the listed fields and resubmits, ≤ `CLUE_ARV2_V26_BRIEF_RESUBMITS` (2); a third failure → the model is told to `finalize_turn(status="blocked")` and the job lands `needs_review/brief_invalid` with the last document retained |
| plain-text stop | the one finalize-only recovery call (03a §1.1) |
| round cap reached without a brief | `TurnBudgetMiddleware` forces `finalize_turn`; the completion guard finds no dossier → `needs_review/quality_unit_incomplete` (02 §3.2 failure codes); the pool and ledger survive for a re-drive, which starts a fresh turn on the same pool |
| operation cap reached | further `acquire` calls return `operation_budget_exhausted`; the judge must submit with what it has |
| context: clearing then compaction (§5.3) | automatic; no failure |
| lease lost mid-turn | the fleet cancels; the checkpoint holds the last superstep (03a §5.1); the takeover's `_run_turn` resumes from `current.values` with `state=None` (03a §5.1); a batch that died mid-way is patched by `PatchToolCallsMiddleware` (03a §1.1) |
| contact privacy-stopped while the account judge runs | `before_work` on the **contact** job refuses (02 §1.3); the account judge is unaffected mid-turn; at `submit_brief` the server drops items whose candidates belong to a stopped contact's pool (their artifacts are privacy-erased) with per-item `error="source_erased"`, never refusing the brief (§3.7) |

Budgets, cost and DSAR for C are §5 (context and cost), §3.7 (import) and §3.9 (DSAR).

### 3.7 `submit_brief@1` — validate, persist, import (one call)

**Input:** `{"sections": [{"section": "<class id>", "findings": [FindingRecord…]}], "coverage_note": str?}`
— the §2.3 records grouped by class (one section per class; the dossier document is the same
`{"sections":[{"section","findings":[…]}]}` shape `save_dossier_section` builds today, 02 §5.3
claim-ready skill, so `finish_dossier`'s importer reads it unchanged).

**Server defaults and derivations (in order, all shape-level):**
1. Ids: missing `id`s are assigned `F001…` in order; duplicates refused in `errors[]`.
2. Evidence: for a single-candidate item, copy `quote|typed_value`, `source_paths`, `attribution`,
   `time_context`, `confidence` from the cited candidate when absent; **re-verify** the judge's
   `quote` against the stored source (§3.5.3 rule) and, on any mismatch, replace it with the
   candidate's verified quote and mark `quote_restored`. For a `synthesis` item, `source_paths` =
   the union of the cited candidates' paths.
3. `claim_type`: `synthesis` when ≥ 2 candidate ids; `not_found` when `not_found` is set;
   otherwise `reported_statement` when the cited candidate's `attribution.kind ∈ {self, third_party,
   provider_synthesis}`, else `observation` (the widened literal, R3; 04 W1-2 maps each to its claim
   kind at import).
4. **`review` is derived, never asked for**: `conflicts_with ≠ []` → `{status: potential_conflict,
   reason: "judge-marked", conflicts_with}`; `wrong_entity=true` → `{status: wrong_entity, reason:
   "judge-marked", expected_entity: {subject}}`; otherwise `{status: supported, reason:
   "judge-selected; review defaulted", …}` with `write_markers.review_defaulted=true`. **Never**
   `insufficient_context` (its import conclusion is `unresolved`, which the page query drops —
   plan W1-2) and never `duplicate` (the judge merges duplicates into one item with several
   candidate ids). The `Review` validator's linkage rules (`dossier_findings.py:16-34`, *verified*)
   are satisfied by construction.
5. `value_json` extras (§2.2) stamped from the record; `rank` by emission order when absent;
   `personas` default = every persona of `persona_map`.
6. **Caps** (§2.1): within each class, items ranked past the cap are marked
   `write_markers.over_cap=true` (imported, not served); nothing is refused for being over cap.
7. **Interpretation presence** on the classes marked in §2.1: a missing/blank
   `agent_interpretation` → `errors[] += {id, field: "agent_interpretation", code: "required"}`.
8. `not_found` operation ids must exist in the job's ledger or receipts; `synthesis` needs ≥ 2
   distinct source URLs (plan AT-4); candidate ids must resolve — each failure is an `errors[]` row.
9. Contact items: `use_class` may only tighten (§2.3); unmatched-anchor candidates may only
   appear under `hook` and import `identity_binding=weak, outreach_safe=false`.

**If `errors[]` is non-empty:** return `{accepted: false, errors[], corrected_fields[]}` — a
completed operation with a value, not a raise (03a §8e) — and persist nothing. **Else:** persist the
document + snapshot exactly as `_persist` does (`research_json_dossier_document`,
`research_json_dossier` at `{job}:{version:010d}`, 02 §2.2), then run the `finish_dossier` body
unchanged: freeze, `import_id = uuid5("research-json-dossier:<job>:<sha>")`,
`import_research_dossier` → `submit_proposal` → claims; receipt on the snapshot;
`mark_account_import_ready` (02 §1.4, §3.11). The person floor runs at import for r27 (§2.5,
D11). Return `{accepted: true, path, version, claim_ids[], import: {stored, errors, reused},
over_cap: n, restored_quotes: n}`.

**Idempotency:** `DOMAIN_IDEMPOTENT`; the document sha keys the import (02 §2.2 `finish_dossier`),
so a replayed `submit_brief` with the same document returns the same import with
`entries[].replayed=true`; a different document after a committed import is a revision
(`import_revision`, 02 §2.2) — allowed once (`CLUE_ARV2_V26_BRIEF_RESUBMITS` covers only rejected
submissions; an accepted brief is final for the turn).
**Failure:** an import exception (DB) is the one case that raises — it is a real failure the
harness must see (`operation_failed`, budgeted), and `finalize_turn` will refuse until `retry_of`
replays it (03a §5.5), which the idempotent import makes safe.
**Cost:** one tool round (≈ $0.03–0.09 at the judge's context); `arv2.dossier.import` span as today.

### 3.8 E Pages (per section, parallel, written once; deferred for contacts)

**Trigger.** Account: inside the account job right after C-account's turn commits (the import-ready
row exists). Contact: the **`contact_page` continuation of the research kind** (04 §0.5 / P1,
adopted by R11; the one divergence from 03a §8f, whose display-kind task would write Luna blocks
the frontend never serves for a quality subject — `frontend_read/display_pages.py:346-375`,
02 §1.7 — and whose handler is not composed with the page writer, `account_research_driver.py:2478-2480`):
a `fleet_task` of kind `arv2_account_research`, `work_id = job_id`, `dedup_key =
"arv2:contact-page:<job>:<ready_version>"`, priority −80, `reopen_terminal=True`, payload
`{continuation: "contact_page", job_id, run_id, workspace_id, parent_job_id, ready_version}`,
where `ready_version` is the parent's newest `arv2_research_import_ready.dossier_version` read
inside the enqueuing transaction. Enqueued (rows first, offer second) by **(a)** the contact's
`_settle_quality` when the parent's import-ready row exists at settle, else by **(b)** the 10 s
sweep's `contact_pages_due` selection (a `completed` r27 child whose parent has `READY_KIND` and
which has no live contextual `display_block` for `(contact, subject, 'contact')`) — which also
covers every contact that finished before its account, within ≈ 10 s of the account's
`finish_dossier`. The handler's `_contact_page_continuation` runs `write_job_pages` under `_jobs`
(it is a research slot for ≈ 1–2 min); a payload whose parent is not ready returns
`failed/parent_not_ready, requeue=False` and the sweep re-offers when it is; an already-current page
(`page_inputs().sha256` equals the live block's manifest) returns `completed/already_current`
without a model call.

**Attempt ceiling (R16(d)).** Each continuation attempt increments `input_refs.v26_page_attempts`
on the contact job (a jsonb key, no CHECK); `contact_pages_due` excludes jobs at
`CLUE_ARV2_V26_PAGE_MAX_ATTEMPTS` (2), after which the job stays `needs_review/page_section_failed`
and only `manual_refresh` re-offers. Without this the sweep's `reopen_terminal` re-offer is an
unbounded loop (review B §1.2 row 19). The account's in-job write is bounded by the same count.

**Inputs per section** (a "section packet", ≈ 7k tokens account / 9k contact): the seller brief
(cached artifact `research_seller_brief`, 02 §1.5), the subject identity, the section guide
(`account-pages`/`contact-page` v2 — per-section text, neutral examples per 02 §10 item 12), the
section's class slice from the brief (§2.1 mapping; full records: statement, quote, URL, date,
interpretation, rank), the committee roster for `buying-committee`/`how-to-approach`, and — for
contact sections — the account's trigger/initiative/pain items (≤ `CLUE_ARV2_V26_PAGE_ACCOUNT_CONTEXT_ITEMS`
(10)) so the contact page can tie the person to the account story. No Miscellaneous section is
written when `CLUE_ARV2_V26_MISC_SECTION=off` (D3 "yes"); with `on`, the dump is kept but filtered
to claims that are `outreach_safe` **and** `use_class=professional-public` (closing the plan's §0
item 26 leak path either way). Insights' `context-only` keeps its 2026-09-29 placement (review A
C29: a ruling stands until the founder changes it).

**Calls:** one `write_checked` per section (03a §8g: `page_writer.py:200-237`), model
`RESEARCH_NARRATIVE_AGENT_MODEL` / `_EFFORT` (D4 small model; exists, 02 §6), through the
`ProviderCaller` `ModelCall` (02 §1.5), gathered under `asyncio.Semaphore(settings.arv2_display_max_parallel)`
(30, existing) — account 11 sections (6 overview + 5 insights, minus `miscellaneous` → 10 when D3
is off), contact 6 (→ 5). Per-section timeout `CLUE_ARV2_V26_PAGE_SECTION_TIMEOUT_S` (120 s), one
repair (`CLUE_ARV2_V26_PAGE_SECTION_REPAIRS=1`, the existing rule), checks correctness-only
(refs resolve, quotes appear in cited findings, private matters absent, `send_line` only in
openers — 02 §1.5; no word counts, 02 §10 item 11). Output: the existing section JSON
(`OUTPUT_SHAPE`, *verified*). Publish: the page's sections are published **in one transaction**
(`publish_page(... sections=(…))` once per page) so a reader never sees a partial page
(review B §4.1's ambiguity, resolved); the per-section `expected_dependency_sha256` from
`page_inputs` (03a §8g; 02 §1.5) still skips a section whose input sha equals the live block's
(plan W1-10). The first write's writer artifact stores every section's input sha
(`section_inputs`) so the refresh can compare (review A Q68).

**Conditional account refresh (D5):** when the account's generation reconciles after the **last**
child is terminal (§6.3), recompute every account section's packet with the children's briefs
folded in and rewrite **every section whose slice sha changed** (review A C31: 04's superset — the
same cost as 03's two named sections when nothing else changed, and correct when it did); a page
whose `page_inputs().sha256` is unchanged is skipped whole (W1-10). Nothing is rewritten, ever,
without `manual_refresh`.

**Failures:** a section whose repair fails → the page is **not** published (one transaction), the
job lands `needs_review/page_section_failed:<key>`, and the next attempt (≤ the ceiling above)
re-runs only the failed section (the others' drafts are kept in the writer artifact). A writer
exception → `needs_review/page_writer_failed` as today (02 §1.5). Timeout → the same path.
**Replay:** the page publish is idempotent on `(subject, page, dependency sha)` (02 §3.10 page
pointer upsert); a takeover re-runs only sections without a kept draft.
**Cost/telemetry:** one ledger row per section (`label='page-writer-v26-<page>-<section>'`), one
Langfuse generation each under span `arv2.v26.pages` with `sections, repaired, skipped_unchanged,
duration_ms{section}, attempt` — the per-section timing 02 §8.5 item 6 records as absent. The
contact page's spend is job-stamped on the ledger; `arv2_research_job.cost_usd` was written at
`finish_job` — `add_job_spend` (§3.9) adds it so the job row stays the money truth.
**DSAR:** pages are bound via `agent_artifact_subject` to every subject they describe
(02 §3.15), unchanged; the continuation binds the contact.
### 3.9 Settle, and DSAR / erasure behaviour across the stages

**Settle (`_settle_quality`, 02 §1.5), v26 branch:** account — after E: `finish_job` (attempt-fenced;
counters from `quality_meter.usage`, which now also sums the extractor's and compile's
`openrouter` ledger rows because they carry the job stamp), `signal(initial_settled)`,
activity row (the contacts that finished first get their page through the sweep's
`contact_pages_due` within ≈ 10 s, §3.8 b). `ready_person_jobs` stays in the settle (it is what
offers the children, §3.2). Contact — after C: `finish_job`, `record_child_result`, enqueue its own
`contact_page` continuation when the parent is import-ready (§3.8 a), **no inline page write**
(`_write_pages` returns the result untouched for an r27 contact — `defers_contact_page(scope)`,
04 P1). The job row's `cost_usd` now includes everything the job bought
(compile, acquisition, extraction, judge, pages); the refresh's spend bills the account job id on
the ledger (02 §8.5 item 9) and v26 adds a second `finish_job`-free counter update
(`add_job_spend`, fenced on `status='completed'`) so the row stays the money truth.

**DSAR / erasure, by object:**

| Object | Binding / derivation | On contact erasure or privacy-stop |
|---|---|---|
| AI Ark records, provider pages | `provider_identity`, `provider_artifact_subject` (02 §3.15) | existing: page privacy-erased, `linkedin_url` nulled |
| evidence sources (`arv2_evidence_source`) | job-keyed, subject in `_subject` (02 §3.5) | existing: readers filter erased/expired; `stop_contact_jobs` erases operation artifacts (02 §3.15) — **with the v4 filter fix of §3.2** |
| pool artifacts (`research-candidates`) | `subject_bindings=(contact,)`, derivation from every source | erased by the derivation trigger when any source is erased; privacy-stop → `erase_subject` reaches it through `agent_artifact_subject` |
| the extractor's call envelopes (request = the quoted source text; `ledger.py:258-266`) | `agent_artifact_subject` + derivation from each source of the batch, recorded after every call by the pre-step or by `acquire@2` (§3.5.6; review A K3) | erased with the sources; privacy-stop reaches them through the subject binding |
| the account's L7 task artifact and the account turn's `agent-model-input` artifacts (they embed the people slice) | the research `AgentTurnRequest` for an account job lists **every committee contact** among its subjects, so the turn's artifacts (`:772-779`, 03a §5.4 item 2) and the model-input artifacts (`agent_runtime_wiring.py:163-196`, 03a §7.1 — written with the turn's subject bindings) are bound to each contact (A-owned change) | erased with the contact; the account turn can then **not** be replayed (the context materializer's sha verification fails, 03a §5.1) — correct: late responses stay unreadable (02 §10 item 17) |
| claims imported from the brief | `source_paths` → evidence; `artifact_derivation` candidates → dossier | existing: `eligible_sql` excludes claims whose support is erased (02 §3.9); `submit_brief` refuses to write an item whose candidate artifact is already erased (per-item `source_erased`) |
| pages | `agent_artifact_subject` per described subject (02 §3.15) | existing tombstone + erase; the sweep never re-offers a page for a privacy-stopped contact (`contact_pages_due` carries the same guards as `ready_person_jobs`: generation not `suspended|privacy_stopped`, `input_refs.privacy_stopped <> 'true'` on child and parent — `quality_person_release.py:85-87`, *verified*) |
| ledger rows | job-stamped, no personal text beyond the request envelope (the raw artifact) | the raw artifact is erased with the operation; the row survives as audit (02 §3.6) |

Privacy-stop of a contact mid-pipeline: `job_available` turns false (`input_refs.privacy_stopped`,
02 §3.15 readers) → the pre-step stops at the next operation (§3.3.8), the judge's `before_work`
refuses (02 §1.3), the generation's child is terminal `failed/privacy_stopped`, the account judge's
`submit_brief` drops the items citing it (§3.6.5), and no page task is offered. Nothing is
re-purchased after a stop (the operations are single-purchase and the job is unavailable).

---

## §4 The candidate pool and the judge's view

### 4.1 Candidate schema (JSON, one object per candidate)

```json
{
  "id": "c_8a1f0c2d9e77",
  "subject": {"kind": "contact", "entity_id": "2f4c…"},
  "class": "own_words",
  "finding": "Says the hardest part of field marketing this year is proving pipeline influence.",
  "evidence": {"kind": "quote", "quote": "the hardest part of field marketing this year is proving pipeline influence […] we rebuilt our attribution twice", "elided": true},
  "source": {"source_id": "9d1e…", "path": "/evidence/0042-linkedin-post.json", "url": "https://www.linkedin.com/posts/…", "title": "…", "kind": "web_snapshot", "operation_id": "b7c0…", "template_id": "P_linkedin_posts"},
  "attribution": {"kind": "self", "speaker": "Emily Wall"},
  "date": "2026-05-12", "date_basis": "published",
  "confidence": 0.9,
  "use_class": "professional-public",
  "subject_anchor": {"kind": "linkedin_slug", "value": "emily-wall-abm", "matched": true},
  "entities": [{"kind": "programme", "text": "field marketing"}, {"kind": "vendor", "text": "6sense"}, {"kind": "url", "text": "https://…/attribution-rebuild"}],
  "extractor": {"model": "<RESEARCH_EXTRACT_AGENT_MODEL>", "prompt_version": "extract-v1", "call_id": "<ledger call id>"},
  "verdict": {"quote": "EXACT", "floor": []}
}
```

- `id` = `"c_" + sha256(class ‖ url ‖ normalize_for_match(quote | raw))[:12]` — content-addressed
  (04 W1-5's `(class, quote or typed_value, url)` address), so a re-extraction of the same source
  yields the same ids, the same quote from the same page found by two operations is one candidate,
  and the judge's citations survive a replay.
- This record, with `entities[]`, is the `Candidate(ToolOutput)` of `arv2/candidates.py` that
  `acquire_research_evidence@2` carries from the **r26 mint** onward (§3.6.3; R13): declared whole
  in W1-5, empty on r26, populated on r27 — never widened afterwards without a re-mint.
- `entities[]` (R9) — `{kind ∈ person | org | vendor | programme | event | url | phrase |
  prior_employer | subject_site_page | title, text}` for everything the candidate's source names
  that a follow-up could chase; the §3.4 `entity` trigger kind fires on them. Extractor output,
  mechanical to check (`text` must occur in the source body under `normalize_for_match`; an
  entity that does not is dropped, `entity_unverified`).
- `evidence` is the quote branch above or `{"kind": "typed", "value_kind": "date", "value":
  "2025-09", "source_offset": 1832, "raw": "September 2025"}`.
- `attribution.kind ∈ self | employer | first_party | third_party | provider_synthesis` (the deep
  report's own sentences are `provider_synthesis` and may only back a `synthesis` item together
  with a non-synthesis candidate — the existing `research_report` kind, 02 §3.5).
- Account candidates omit `use_class` and `subject_anchor` (`null`); `committee` candidates from
  A0 carry `source.kind="provider_record"` and `attribution.kind="provider_synthesis"` with the
  AI Ark row as the source.
- `verdict.quote ∈ EXACT` only (rejected candidates are not in the pool); `verdict.floor[]` lists
  the floor categories that fired.

### 4.2 The acquisition ledger (what the judge sees, per subject)

One JSON array, one entry per operation the pre-step issued for the subject, in issue order, ≈ 35–50
entries ≈ 1.5–2k tokens:

```json
{"op": "b7c0…", "kind": "search_web", "template": "T_leadership", "query": "\"Dialpad\" (appointed OR …)",
 "state": "succeeded", "result_count": 8, "http_status": 200, "candidates": 11, "rejected": 2,
 "follows": null, "pool_read": false, "provider_ms": 2500}
{"op": "c91a…", "kind": "v26_followup:departure_successor", "template": null, "query": "\"Dialpad\" (\"new CMO\" OR …)",
 "state": "empty", "result_count": 0, "http_status": 200, "candidates": 0, "rejected": 0,
 "follows": {"operation_id": "b7c0…", "candidate_id": "c_8a1f0c2d9e77", "rule_id": "departure_successor"},
 "pool_read": false, "provider_ms": 2300}
```

plus a trailer `{"minimums": {"trigger": {"required": 3, "before_gap": 2, "after_gap": 4}, …},
"budget": {"operations_max": 30, "operations_used": 0, "extract_calls_max": 120, "extract_calls_used": 58},
"skipped": {"extract_skipped/budget": 0, "extract_skipped/timeout": 0}, "absent_pools": ["<contact id>"]}`
(the account) or `{"account_pool": "first|final|absent"}` (a contact). `follows` is the AT-9 join
(R9): `operation_id` is mandatory on every A3 operation, optional on a judge follow-up. `kind` values the judge may
cite in `not_found`: every operation id in this array or in its own receipts. Derived from
`arv2_research_operation` + ledger rows at pool-persist time (§3.5.5); the same bytes are in the
pool artifact.

### 4.3 How candidates reach the judge (03a §8c: the task message + `inputs/` file)

The L7 `agent-turn-input` artifact (`quality_research_wiring.py:867-879`, 03a §8c) carries, in
this order: (1) the objective and the completion contract (as today); (2) a **context block**
≈ 3k tokens: the ICP's `persona_map`, hard gates and exclusions (from the pinned ICP document's
front matter, master plan §5.2), the seller's product summary (the first 1,500 chars of the
`product-catalog` document) and, for a contact, its persona + the A0 record (title, employer,
LinkedIn URL); (3) the **pool**: for the account judge, all account candidates (expected 12–20k
tokens) **plus the people slice** — the top `CLUE_ARV2_V26_PEOPLE_SLICE_PER_CONTACT` (20)
candidates of each contact's final pool by `(class ∈ remit, problem_now, own_words, proud_of)`,
then confidence (≈ 1.6k tokens per contact, plan AT-8); for a contact judge, its own candidates
(6–12k) **plus the account slice** — the account's first pool filtered to `class ∈ trigger,
initiative, pain, stack`, top `CLUE_ARV2_V26_ACCOUNT_SLICE_MAX` (60) by confidence (≈ 6k); (4) the
ledger (§4.2). The pool rides the task artifact's objective as a **fenced text block** (`---
candidates ---` … `--- ledger ---`), not as a nested JSON value, so the L7 human message is not
JSON-inside-JSON (review A Q64 — the very thing W1-4 removes from the views). The same bytes are
materialised read-only as `inputs/candidates-<kind>.json` (`kind ∈ account | contact`; 03a §8c's
path) through a `ContextCandidate(materialized_path=…)` emitted by the research assembler's L5
layer source (`_Contexts.assemble`, `quality_research_wiring.py:353-388`; 03a §8c) so
`grep`/`read_file` work without a second copy, verified by sha on resume. The pool is sent **once per generation inside
the cached prefix** (03a §8c), never cleared, never re-read. Hard bound: if the assembled L7
exceeds `CLUE_ARV2_V26_L7_MAX_TOKENS_ACCOUNT` (40,000) / `…_PERSON` (32,000) (by `len(bytes)/4`), the
pool is trimmed **per class by rank** (lowest-confidence first, never below each class's minimum)
until it fits, and the ledger trailer records `trimmed: {class: n}` — the judge can still reach
every trimmed candidate at `inputs/candidates-<kind>.json`.

### 4.4 What the account judge gets from contacts and vice versa

- Account ← contacts: the people slice (§4.3) and, in the ledger trailer, each contact's
  `minimums` after its gap round. This is what lets the account judge emit the org-sequence
  finding (plan AT-8) and rank committee items with role evidence from the person research.
- Contact ← account: the class-filtered first pool (§4.3) — the account's **story** (triggers,
  initiatives, pains, stack) so the contact is judged against it without waiting for the account
  judge. The contact judge never sees other contacts' candidates.
- Neither judge sees the other's **brief** (the briefs are written in parallel); the page writer
  joins them (§3.8 packets).

### 4.5 The per-class minimums and the gap round

Defined in §2.1 and executed in §3.5.7; the judge sees the before/after counts in its ledger
trailer. The judge has no mechanical minimum of its own: an unmet minimum after the gap round is a
lead it is prompted to chase and, failing that, a `not_found` item — the honest empty state of
plan §1.

### 4.6 The output schema and how the import consumes it unchanged

The judge emits §2.3 records grouped by class through `submit_brief@1` (§3.7). After the server
defaults, each record is a valid `EntryV2` (`id`, `topic`, `claim_type` — the literal widened to
`observation | reported_statement | synthesis | not_found` on `FindingV2`/`EntryV2`, never on
`Finding` itself (04 W1-2's `@1`-sha reason, §2.2), R3 / review A Q20 —
`finding`, `source_paths`, `attribution`, `time_context`, `qualifications=[]`, `review{…}`,
`agent_interpretation`; 02 §2.2) with the v26 extras in the `finding` value's companion
`value_json` — the importer
(`import_research_dossier`, 02 §1.4) reads the document, writes `*.research_finding` claims
(`dossier_import.py:69`), persists the receipt on the snapshot and marks the import ready, exactly
as for a v25 dossier. The `review` derivation (§3.7 step 4) guarantees that **no defaulted v26
item imports `unresolved`**: an item the judge did not mark is `supported` and imports
`supported`; a judge-marked `potential_conflict` imports exactly as the importer maps it today
(the five semantic axes, 02 §3.9 — the correct, visible-as-uncertainty outcome of 02 §10 item 4);
`wrong_entity` imports `invalid`, retained for audit. A page query therefore never drops an item
the judge selected without marking.

---

## §5 Context economics by construction

### 5.1 Opening context per role (tokens; bytes ÷ 4)

| Block | Account judge | Contact judge | Sent | Cleared? |
|---|---|---|---|---|
| system prompt (r27 `SYSTEM.md`) + generated resource map (03a §4.3) | 5,000 + 1,000 | 4,500 + 1,000 | every call, cached prefix | never |
| **the duplicated L1 copy** (03a §4.3: the same prompt again as the first conversation message) | +6,000 today; **0** once W1-6 lands (A-owned; v26 does not depend on it — it is a cost line, not a correctness line) | +5,500 / 0 | every call | never |
| L7 task: objective + contract | 800 | 600 | once, cached prefix | never |
| L7 context block (ICP/persona/product) | 3,000 | 3,000 | once | never |
| L7 pool: own candidates | 16,000 expected (12–25k) | 9,000 (6–12k) | once | never |
| L7 pool: the other side's slice | people slice 5 × 1,600 = 8,000 | account slice 6,000 | once | never |
| L7 ledger | 2,000 | 1,500 | once | never |
| **Opening total (W1-6 landed)** | **≈ 35,800** (max ≈ 48k at the L7 bound) | **≈ 25,600** (max ≈ 34k) | | |

What is **never re-sent** as new input: everything above after the first call (prefix cache,
03a §4.4); skills (not read); evidence pages (not read — candidates replace them); the deep report
(extracted in B, never in context); provider results (receipts carry candidates, ≤ 12 KiB).

### 5.2 Per-round growth

Each round adds the model's output (median 274 tokens on today's runs, 01 §2.4 T2.5 mean 702 —
r27 prompts ask for terse reasoning; budget **400**) and its tool results: an `acquire@2` receipt
≤ 10 KiB ≈ **2,500** tokens (20 candidates × ~110 tokens + items + ledger entry), a
`search_evidence@3` result ≤ 1k, a `read_file` of the candidates rendering of an operation ≤ the
operation's candidates (≤ 3k in practice) — with raw views off (§3.6.1) there is no 80k-char read
left to clear. Budget **+3,400 per investigative round** (kept as the conservative bound),
+400 for a reasoning-only round. The brief emission round is output-heavy: account ≈ 9–11k tokens
(50 items × ~200), contact ≈ 4–6k (24 items), capped by the profile's `max_output_tokens`
(16,384 / 12,288).

### 5.3 Tool-result clearing and the per-role window (the one divergence from 03a §8d)

`ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=T_role, keep=CLUE_ARV2_V26_CLEAR_KEEP_RESULTS
(4), clear_tool_inputs=False, exclude_tools=("submit_brief", "finalize_turn"), placeholder="[cleared —
candidates remain citable by id; full list at /research/operations/<op>/candidates.json]")])` in
the research bindings tuple (03a §8d: `quality_research_wiring.py:743-751`), `T_role =
CLUE_ARV2_V26_ACCOUNT_CLEAR_TRIGGER_TOKENS` (45,000) / `…_PERSON_…` (42,000). **Divergence:** 03a
§8d excludes `acquire_research_evidence` from clearing so candidate receipts stay in view. With the
pool in the L7 prefix that exclusion breaks the cap arithmetic: 20 investigative rounds × 3,000
tokens of receipts = 60k tokens that can never leave, on top of a 36k opening — the 60k cap is
exceeded by round 9. So v26 clears `acquire@2` receipts too; a cleared receipt loses nothing the
judge needs, because (a) its candidates are cited **by id** and `submit_brief` resolves ids from
the stored operation results, not from the context, and (b) the whole list is one `read_file`
away at the view path named in the placeholder. The per-role **context cap** is applied where
compaction is sized (03a §8d): the window handed to `CompactionSettings` is
`min(model window, CLUE_ARV2_V26_ACCOUNT_CONTEXT_CAP_TOKENS (60,000) | …_PERSON_… (56,000))`, so
compaction triggers at 54k / 50.4k and keeps 6k / 5.6k — a backstop that, with clearing on, will
in practice not fire on reported usage (03a §4.2); the settings comment says so. Clearing edits
the request only (03a §4.2): checkpoints keep the originals, replay re-clears identically, and
`ToolRepairRoundsMiddleware` still reads the original `ToolMessage`s.

**Steady state after the trigger:** context ≈ opening + 4 kept receipts (12k) + AI turns (≤ 20 ×
400 = 8k) ≈ 36k + 20k = **56k worst case** for the account — under the 60k cap, so compaction
never has to fire in a maximal run (with `keep=6` the same sum is 62k, which is why the keep is
4). The expected 7-round account run crosses the 45k trigger at round 4 (36k + 3 × 3.4k = 46.2k);
from round 5 the oldest receipt beyond the last four is cleared each round (one ≈ 10k re-bill,
≈ $0.02), and the live context stays ≈ 47–48k. Contact: 25.6k + 5 × 3.4k = 42.6k at round 5, the
42k trigger fires at the last round at most.

### 5.4 Per-role budgets (settings) and what enforces each

| Budget | Account | Contact | Enforced by |
|---|---|---|---|
| model rounds | `CLUE_ARV2_V26_ACCOUNT_MAX_MODEL_ROUNDS` 20 | `…_PERSON_…` 12 | `Allowance.model_calls` + `TurnBudgetMiddleware` built from subject-kind settings at `quality_research_wiring.py:1233-1238` (03a §8e) |
| provider operations (judge follow-ups) | `CLUE_ARV2_V26_ACCOUNT_MAX_OPERATIONS` 30 | `…_PERSON_…` 15 | `acquire@2` counts `kind LIKE 'quality_tool:%' AND state <> 'failed'` rows for the job in the `operations.begin` transaction (03a §8e; `research_operations.py:260-270`; review A C27) |
| extraction calls the judge's follow-ups may spend | the subject's `CLUE_ARV2_V26_EXTRACT_MAX_CALLS_ACCOUNT` 120 (shared with the pre-step) | `…_PERSON` 60 | `quality_extract` call counter per job (§3.5.2) |
| context | cap 60,000; clear at 45,000; keep 4 | cap 56,000; clear at 42,000; keep 4 | §5.3 |
| raw reads | off (`CLUE_ARV2_V26_JUDGE_RAW_READS=false`) | off | `ResearchViewMount` r27 rendering (§3.6.1; R16(a)) |
| model fallback | none (`CLUE_ARV2_V26_FALLBACK_MODELS=`) | none | the research model is built without the global chain (§3.6.5; R16(b)) |
| output per call | 16,384 (profile) | 12,288 (profile) | the profile pin (02 §5.1 `max_output_tokens`) |
| tool calls per round | `CLUE_ARV2_ACCOUNT_MAX_TOOL_CALLS_PER_ROUND` 50 (existing; irrelevant in practice) | same | existing allowance |
| wall-clock | none (founder ruling 2026-09-27) | none | — |
| repair rounds / finalize repairs | 10 / 2 (existing, 03a §6) | same | existing middleware |

### 5.5 Expected and maximum tokens per round, and the cost ceiling per subject

Let `O` = opening tokens, `g` = growth per investigative round (3,400), `R` = rounds, `B` =
brief output tokens, `p_n, p_c, p_o` = new-input, cached-input, output prices per token.
Rounds 2..R re-send the prefix as cached input; each round's new input is the previous round's
growth; the first call past the clearing trigger is one full miss of the cleared prefix
(03a §4.4), bounded by `T_role`.

```
cost(role) = p_n · [O + (R−1)·g + miss]  +  p_c · Σ_{r=2..R} C_r  +  p_o · [(R−1)·400 + B]
C_r (live context at round r) = min(O + (r−1)·g, cap)       miss = T_role if R·g + O > T_role else 0
```

**Account judge (Grok 4.6; O = 35,800; g = 3,400; cap 60k; T = 45k):**

| | R | new input | cached input | output | **$** |
|---|---|---|---|---|---|
| expected | 7 | 35.8k + 6×3.4k = 56.2k → $0.112 | Σ(35.8k + (r−1)·3.4k, r=2..7) = 6×35.8k + 3.4k×21 = 286.2k → $0.143 | 6×400 + 9k = 11.4k → $0.068 | **$0.32** |
| maximum (modeled) | 20 | 35.8k + 19×3.4k + 45k miss = 145.4k → $0.291 | 19 rounds × ≤ 60k = ≤ 1,140k → $0.570 | 19×400 + 16.4k = 24k → $0.144 | **$1.00** |

**Contact judge (O = 25,600; cap 56k; T = 42k):** expected R = 5: new 25.6k + 4×3.4k = 39.2k →
$0.078; cached Σ = 4×25.6k + 3.4k×10 = 136.4k → $0.068; output 4×400 + 5k = 6.6k → $0.040 →
**$0.19**; maximum R = 12: new 25.6k + 11×3.4k + 42k = 105k → $0.21; cached 11 × ≤ 56k = 616k →
$0.31; output 11×400 + 12k = 16.4k → $0.098 → **$0.62**. Five contacts: **$0.93 expected, $3.10
maximum**. The `miss = T_role` term is an upper bound: with the pool in the prefix the earliest
cleared message sits at ≈ O, so the real re-bill is the suffix after it (≈ 10–20k tokens, 03a §4.4),
not the whole trigger.

**Extraction (B), per account + 5 contacts, Flash / Luna:** account input ≈ 316k chars
(plan §3) ≈ 79k tokens new + 60 calls × 2k cached instructions; output ≈ 173 candidates × 110 =
19k → Flash $0.059 + $0.009 + $0.071 = **$0.14** (Luna $0.016 + $0.002 + $0.023 = **$0.04**).
Contact at the D9 pin: report 55k + 12 × 4k texts + 6 searches × 8 × 1.5k + 6 fetches × 8k ≈
223k chars ≈ 56k tokens; output ≈ 120 × 110 = 13k → Flash $0.042 + $0.006 + $0.049 = **$0.10**
(Luna **$0.03**) × 5 = **$0.50** (Luna $0.15). Maximum (every A3/gap/judge follow-up extracted,
≈ 1.6× the chars): **$1.0** Flash / $0.3 Luna.

**Pages (E), D3 off:** account 10 sections × (7k in + 1.5k out) + refresh 2 sections → Flash
12 × ($0.00525 + $0.0056) = **$0.13**; contacts 5 × 5 × (9k + 1.5k) → 25 × ($0.00675 + $0.0056)
= **$0.31** (Luna $0.04 + $0.09). Ceiling = every section repaired once = 2× expected (Flash
$0.88, Luna $0.26). Compile: $0.007 once per context.

**Providers:** expected 55 searches × $0.009 + 49 fetches × $0.004 + 6 deep × $0 = **$0.69**
(the four R10 templates add 9 fetches ≈ $0.04, inside the rounding of the verified total below);
AI Ark 1 company (0.1) + 5 roles × 5 × 0.5 (12.5) + 5 exports × 1.0 (5.0) = 17.6 credits ≈
**$0.18**. Maximum: account 23 (A1) + 22 (A3 at 2 × 11) + 6 (gap: 3 classes with minimums × 2) +
30 (judge) = 81; contact 17 (A2) + 16 (A3 at 2 × 8) + 6 (gap) + 15 (judge) = 54 × 5 = 270;
**351** operations at the search price → **$3.16**; AI Ark + 5 web-gap `lookup_person` ≈ 25
credits → $0.25. **D8 is a line, not a footnote** (review B §1.2 row 15): the pinned surface's
price is a fit (≈ $0 over 12 runs), so until D6's read-only ledger prices it the ceiling carries
**+$3.00** (6 reports at $0.50; +$6.00 with every thin-response retry).

**Totals per account + 5 contacts.** The launch turn (today $0.28–0.78, 01 T1.5) is **excluded**
from the gated total: it is the Head-of-ABM's and no v26 setting bounds it (W1-11 / D7); plan §3
added $0.30 for it.

| | Flash extractor + Flash pages | Luna / Luna |
|---|---|---|
| expected (review B verified to the cent; stands per R16) | 0.32 + 0.93 + 0.14 + 0.50 + 0.44 + 0.84 + 0.01 = **$3.18** (+ $0.30 launch = the plan's **$3.48**) | 0.32 + 0.93 + 0.04 + 0.15 + 0.13 + 0.84 + 0.01 = **$2.42** (+ launch = **$2.72**) |
| expected at realistic investigation (review B §1.1: 12 account / 8 contact rounds, the corpus's 58 % follow-up share) | judges $0.54 + 5 × $0.30 = $2.04 → **≈ $4.0** (+ launch ≈ $4.3) | **≈ $3.2** |
| **modeled ceiling** (every cap hit, D8/D9 pinned) — the number the gate enforces (05 §4.2, ×1.10) | 1.00 + 3.10 + 1.0 + 0.88 + 3.41 + 0.01 = **$9.4** | 1.00 + 3.10 + 0.3 + 0.26 + 3.41 + 0.01 = **$8.1** |
| modeled ceiling if D8 is not ≈ $0 | + $3.00 (+ $6.00 with retries) | + $3.00 |

The modeled ceiling is a **ceiling**: it needs every judge to run every round and every operation,
every follow-up to extract at the maximum, every section to be repaired and every clearing miss to
land at its bound — none of which the expected path does. It is higher than the plan's §3 "max
after pinning ≈ $5–6" because that model did not charge the gap rounds, the judge's full operation
budget, the clearing re-bill or page repairs; the expected case agrees with the plan within $0.6.
Today's measured cost has no ceiling (01 §2.2: 350-round allowance).

**The structural ceiling — what the settings alone guarantee (R16).** The modeled ceiling assumes
the judge emits ≈ 400 tokens on a non-brief round and the prefix cache serves every call; the
settings cannot promise either. With review B's four uncapped paths closed — (a) raw reads off, so
no tool result exceeds a 10 KiB receipt (`CLUE_ARV2_V26_JUDGE_RAW_READS=false`); (b) no fallback
model, so no call is priced off the sheet (`CLUE_ARV2_V26_FALLBACK_MODELS=`); (c) extraction output
≤ 2,000 tokens per call with halving (`CLUE_ARV2_V26_EXTRACT_MAX_OUTPUT_TOKENS`) and ≤ 120 / 60
calls per subject (`CLUE_ARV2_V26_EXTRACT_MAX_CALLS_*`); (d) ≤ 2 page attempts
(`CLUE_ARV2_V26_PAGE_MAX_ATTEMPTS`) — every term below is `count setting × size setting × sheet
price`, with no assumption about model behaviour:

```
judge(role)      = rounds × [ cap·p_c  +  (4 receipts·2.5k + max_out)·p_n  +  max_out·p_o ]     (cache-friendly: new input per call ≤ one round's growth)
judge_nocache    = rounds × [ cap·p_n  +  max_out·p_o ]                                           (every call a full miss)
extraction       = calls_max × [ 6k·p_n(extractor) + 2k·p_c + 2k·p_o ]                           (24k-char batch, 2k instructions cached, 2k out)
pages            = sections × attempts × (1 + repairs) × [ packet·p_n + 1.5k·p_o ]
providers        = (A1 + A3 + gap + judge ops) × search price  +  AI Ark credits  (+ D8 line)
```

| Component (Flash extractor and pages, Grok judges) | Modeled ceiling | Structural, cache-friendly | Structural, every call a miss |
|---|---|---|---|
| Account judge (20 × [60k·$0.5 + 26.4k·$2 + 16.4k·$6] / M) | $1.00 | **$3.62** | 20 × [60k·$2 + 16.4k·$6] / M = **$4.37** |
| Five contact judges (12 × [56k·$0.5 + 22.3k·$2 + 12.3k·$6] / M each) | $3.10 | **$8.76** | 12 × [56k·$2 + 12.3k·$6] / M × 5 = **$11.2** |
| Extraction (120 + 5 × 60 = 420 calls × [6k·$0.75 + 2k·$0.075 + 2k·$3.75] / M) | $1.0 | **$5.10** | $5.10 |
| Pages (12 account + 25 contact sections × 2 attempts × 2 calls) | $0.88 | **$1.76** | $1.76 |
| Providers (351 ops + 25 credits; D8 at the fitted ≈ $0) | $3.41 | **$3.41** (+ $3.00–6.00 D8) | $3.41 |
| Compile | $0.01 | $0.01 | $0.01 |
| **Total** | **$9.4** | **≈ $22.7** | **≈ $25.8** |

(Luna extractor and pages: structural ≈ $17.9 / $21.0.) **$9.4 is the modeled ceiling the gate
enforces; the settings alone bound the run at ≈ $23; the three terms that separate them are output
tokens per round, resubmits and cache misses, each measured by Q2** (review B §1.3, written here
as asked). Nothing in the structural column is reachable without the judge emitting its maximum
output on every round or every call missing the cache; what matters for the founder's
"deterministic" ask is that both columns are finite and are functions of §10 alone — today's run
has no bound of either kind. Lowering the judges' `max_output_tokens` is not available (the brief
needs 9–15k); the one further lever would be a per-round output cap for non-brief rounds, which
the profile pin cannot express.

### 5.6 Time (critical path, W2 landed; seconds)

launch 45 → A0.0 compile 6 (cached after the first account) → A0 63 (6 AI Ark calls at 10.5 s)
‖ A1 Exa 60 (deep 53) → B account 20 → A3 round 30 → B 10 → gap 0–30 → **account pool final ≈ t+200**;
contacts: created t+63, offered by the next sweep ≤ t+73 → A2 61 (deep 53; the exports queue behind
the AI Ark lock, ≤ 10 × 10.5 = 105 s for the fifth) → B 20 → A3 25 → B 8 → **contact pool final
≈ t+200..240** → account judge
starts ≈ t+230 (after the people pools) → C-account 160 (7 rounds × ~12 s + the 9k-token brief at
~88 tok/s ≈ 100 s) → E account 51 → **account pages ≈ t+440 ≈ 7.3 min**; contact judges start
≈ t+240 → C-contact 110 → settle → the `contact_page` continuation claimed within the poll interval
→ E contact 40 → **contact pages ≈ t+400**. Two accounts launched together: the AI Ark lock serialises 22 calls
(231 s) and the second account's committee lands at ≈ t+126; everything else is parallel; final
pages ≈ 8.5 min. Three accounts: ≈ 9.5 min, bounded by the AI Ark gap, which is the one serial
resource (`CLUE_ARV2_AI_ARK_MIN_GAP_S`, paid tier unverified — 02 §6).

---

## §6 Orchestration and state

### 6.1 Job, generation and child state (what changes for r27)

- **Job rows** (`arv2_research_job`, 02 §3.2): no column changes. Progress rides
  `input_refs.v26_stage ∈ {compiling, committee, acquiring, extracting, following_up, gap, waiting_pools,
  judging, writing, settled}` written under the job row lock by a small `set_job_input_ref`
  (jsonb merge, no CHECK), because the `stage` CHECK vocabulary (`deep_research|synthesis|
  committee|member_research`, 02 §1.2) would need a migration to widen and the progress card can
  read `input_refs` (02 §1.7 reads milestone fractions; v26 maps `v26_stage` onto them:
  compiling/committee 0.1, acquiring 0.25, extracting 0.35, following_up/gap 0.45, waiting_pools
  0.5, judging 0.6, writing 0.85, settled 1.0). The `stage` column keeps `deep_research`
  (stamped at claim today, `account_research_driver.py:1177`).
- **Contacts released at nomination** (plan W1-8, an r26 gate; 03a §8f): A0 creates the person
  jobs; the **sweep offers them** (§3.2; review A K2 — the pre-step has no queue;
  `account_research_driver.py:951-975`). `ready_person_jobs`
  gains a `recipe >= 26 → TRUE` branch in its `CASE` (`quality_person_release.py:89-92`, *verified*
  — the branch replaces the `artifact_reference` EXISTS for r26+ rows) so every sweep
  (`sweep_quality` → `ready_person_jobs`, 02 §1.6) and the parent's settle offer a child that is not
  yet claimed, with the same work id/dedup key as the launch (02 §1.1). The r26 person prompt and
  the driver's `person_task_instruction(account_dossier_available=…)` stop telling a contact that
  its parent dossier is readable (review A Q9/Q37 — 04 owns the edit; recorded here as the design
  requirement: a contact released before the import reads no parent dossier, it reads the account's
  first pool, §4.3).
- **Deferred contact page** (P1; 04 §0.5, R11): `_write_pages` returns the unit result untouched for
  an r27 contact (`defers_contact_page(scope)`); the page is the `contact_page` continuation of
  §3.8, with its attempt ceiling. `read_parent_dossier`'s raise (02 §1.6,
  `page_writer_runtime.py:405-416`) is reached only from the continuation, which checks readiness
  first.
- **Generation** (`arv2_account_research_generation`, 02 §3.10): unchanged tables and signals.
  `record_child_result` per terminal child as today; `pending_continuations` (02 §1.6,
  `quality_generation.py:390-436`) gains the r27 predicate **"no registered child without
  `terminal_status`"** — the import-ready exception that lets a continuation run per person import
  (the measured ~3 rewrites) is removed for r27 rows, so exactly **one** continuation is offered
  per account, after the last child, and its body is the conditional refresh (§3.8) instead of
  `_rewrite_account`'s full rewrite (02 §1.6 `:849-905`). **Terminal predicate for a stopped child**
  (review A Q35): a child whose job is `needs_review` with `failure_code = privacy_stopped`, or
  whose `input_refs.privacy_stopped = 'true'`, counts as terminal — `terminal_status` is set to
  `failed` for it by `record_child_result` (the `arv2_generation_child` CHECK admits `failed`,
  02 §3.10) even though `failed` is not a job status (02 §3.2).
- **Account pages once + conditional refresh**: §3.8. The refresh runs under the continuation
  lease (`continuation_work_id`, 02 §3.10) with `only_if_work_idle=True` (02 §1.6), publishes
  per section and settles the revision in one transaction as `rewrite_account_pages` does today
  (`page_writer_runtime.py:712-721`); a refresh that changes nothing settles the revision
  `reconciled` without a model call.

### 6.2 Fleet slot usage and the per-process caps

- **6 jobs per account from t ≈ 73 s**: the account job (claimed at launch) plus 5 person jobs
  created at the end of A0 and offered by the next sweep (≤ 10 s later). Each holds a research slot (`_jobs`, 02 §1.2) for its whole
  life — pre-step, judge and (account only) pages included (03a §5.4 item 4). Fleet-wide:
  3 batch processes × `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS` (4) = 12 (02 §7.1); two accounts fill
  it, a third account's children queue at priority −100 FIFO (`enqueue_seq`, 02 §7.3) and are
  claimed as slots free (≈ 7 min later). The person tasks are claimed in `enqueue_seq` order
  across processes (`max_in_flight` reserved before the claim, 02 §7.3), so no slot is held by an
  unstartable job (the 2026-10-03 defect stays closed).
- **Per-process caps the design introduces**: `CLUE_ARV2_V26_EXTRACT_CONCURRENCY_PER_PROCESS` (16,
  a handler-wide semaphore beside `_jobs`), `…_PER_JOB` (6). Existing: provider concurrency per
  job per provider (`exa` 4, `ats` 4, `ai_ark` 1; 02 §2.3), `_jobs` (4), the thread pool (128),
  the DB pool (5 + 10; P3 sizes it before W2-15). With W2-15 (the `_db_lock` removed) the judge
  loops are I/O-bound and `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS` can be raised to **6** per
  process (one full account per process, 18 fleet-wide) — a setting change recorded in §10, taken
  only after W2-20's wait metric reads ~0.
- **AI Ark pacing across 6 jobs**: one global advisory lock per API token + 10.5 s gap (02 §2.3).
  v26 issues per account 1 + 5 (A0) + 5 (exports) = 11 calls; the pre-step issues A0's six
  back-to-back from the account job so the committee lands at ≈ 63 s, and the five exports queue
  behind each other (first-come on the try-lock, `account_research_tools.py:468-492`) off the
  critical path except for the last contact (§5.6). `lookup_person` for a web-gap contact adds one
  paced call each. No per-provider budget is needed beyond the fixed plan; the halt rule latches
  as today.

### 6.3 Lease / takeover behaviour per stage, and what a crashed stage replays to

Leases are 30 s, renewed every 10 s, stale after 60 s; takeover is fenced by `begin_job`'s
`attempt` (03a §5.3). Non-status writes of a superseded zombie are not fenced (03a §5.3) — the
table says why that is safe per stage.

| Stage | Takeover resumes at | What replays, how | Zombie-write exposure |
|---|---|---|---|
| A0.0 compile | marker `research_compile:<context>` present → skip | one artifact keyed on the context; a second compile for the same context is a byte-identical artifact (content-addressed) → `retain_artifact` no-op | none (idempotent) |
| A0 committee | marker present → skip; else re-run | the 6 operations replay (`won=False` → stored body); nominations are `ON CONFLICT DO NOTHING` on job id / selection key; the sweep's offers dedup on `(kind, work_id, dedup_key)` (02 §3.14) | a zombie nominating the same contact lands on the same rows — no-op |
| A1 / A2 | marker `research_candidates_first` absent → re-run the plan | every operation replays; only operations not `succeeded` are re-issued (byte-identical requests); the pool is re-persisted (same sha if nothing changed) | duplicate ledger rows cannot occur (deterministic ledger ids, 02 §3.6); a zombie's late `_drain` finishes the same operation row under `owner_token` fencing (02 §3.3) |
| B | per-operation `extraction` block absent → re-extract that operation only | the candidates live in the operation result; ids are content-addressed | a zombie re-extracting writes the same candidates (same ids) |
| A3 / gap | the pool's `ledger[]` shows which rules fired; the planner is pure → the same plan; operations replay | as A1 | as A1 |
| waiting for pools | re-evaluated from markers | — | — |
| C (judge) | the checkpoint (`thread_id = execution_id`, 03a §5.1); `_run_turn` resumes with `state=None`; a committed outcome short-circuits (`load_committed_outcome`) | tool calls replay through the journal (`COMPLETED` → stored result) and the A9 key; `submit_brief` replays on the document sha | the one real exposure: two drivers on one checkpoint thread inside the ≤ 60 s staleness window (03a §5.3's documented residual; v26 adds nothing to it) |
| E (account, in-job) | unpublished sections only (dependency sha) | per-section `publish_page` idempotent | a zombie publishing an identical section is refused by `expected_dependency_sha256` (02 §1.5) or lands the same block |
| settle | `finish_job` fenced on `attempt` + `in_progress` → the zombie gets `_JobSuperseded` | — | none |
| E (contact, `contact_page` continuation) | the continuation task's own lease; dedup `arv2:contact-page:<job>:<ready_version>`; attempts counted on the job row | idempotent publish; `already_current` short-circuit | none |

A crash **inside the pre-step** (before `AgentTurnRequest` exists) leaves an `execution` row with
no `agent_turn` (review B §4.1): that is recoverable by construction — the next attempt re-enters
at the first missing marker and the turn is created only once the pool is final — and
`load_committed_outcome` (03a §5.1) finds nothing to short-circuit, which is correct. A stage that
crashes with an exception (not a lease loss) goes through `_contain` →
`needs_review/<failure_code>` (02 §1.2) with the codes named in each stage's table; a re-drive
(`not_started|suspended` are claimable, 02 §1.2 `begin_job`) resumes at the first missing marker.
`needs_review` is **not** claimable (a finished row is a redelivery, 02 §1.2 `_not_claimable`), so
operators re-drive by `suspend` → re-offer as today; v26 adds no new recovery surface.

---

## §7 Media: off in v26.0, gated — and the exact conditions to switch it on

**State in v26.0:** `discover_media`, `read_media`, `search_transcripts`, `open_transcript` are
removed from the judges' allowed operation set (§3.6.1) and from every pre-step plan, by the
`ACQUISITIONS` filter in `build_*_tools` gated on `quality_recipe_version >= 26 and not
settings.arv2_media_enabled` (02 §2.3: `quality_provider_tools.py:45-59`,
`account_research_catalog.py:56-57`; the setting is 04 W1-12's `CLUE_ARV2_MEDIA_ENABLED`, review A
C32 — it gates r26 and r27 alike) — a gate, not an allowlist entry, because media reaches the
model only as operations of `acquire_research_evidence` (02 §2.1). The r26/r27 prompts carry no
media instruction. Evidence for "off": 42 runs, 26 `discover_media` + 21 `read_media` attempts, **0
transcripts**, 8 `FileNotFoundError: ffprobe`, 11 `unavailable` with the resolver gap codes, and
every candidate `candidate_not_yet_attempted` (01 §3.4 T3.5); the backend image installs no
ffmpeg (02 §7.2) and the Deepgram key is absent from the deploy templates (02 §6 "Media").

**Switch-on (`CLUE_ARV2_MEDIA_ENABLED=true`) is refused by the worker at composition unless
all four hold — conditions 1 and 2 as a boot check in W4 (review A C32), 3 and 4 as code facts —
each logged `arv2.v26.media_gate`:**

1. `ffprobe` and `ffmpeg` resolve on the worker image (`shutil.which`), i.e.
   `docker/backend/Dockerfile` installs them (02 §7.2 lists the apt set that lacks them).
2. `CLUE_DEEPGRAM_API_KEY` is set (02 §6: optional today, `driver:2468`), and one
   `provider_call_ledger` row with `provider LIKE 'deepgram%'` and `outcome='ok'` exists for the
   deployment (a one-time smoke transcription recorded by the operator — 01 §7 item 7 expects
   zero such rows today).
3. Podcast-platform → RSS/audio resolution exists for the hosts 01 §3.4 names
   (`arv2/media_resolution.py` supports YouTube, direct audio/video and RSS only, 02 §2.3).
4. The receipt carries the real outcome: `acquire@2` already returns `status=refused` with
   `error_code` for a failed read (§3.6.3), so the `completed`-for-failed receipt of 01 §3.4 cannot
   recur on v26.

When on: media becomes part of **A2** for every contact — `discover_media` with `query="{full_name}"
{employer} (podcast OR webinar OR talk)` → candidates whose title or description names the
contact (the resolver's identity rule: metadata never establishes voice, 02 §10 item 9) →
≤ `CLUE_ARV2_PERSON_MEDIA_MAX_ITEMS` (3, existing) `read_media` operations → the transcript is a
`transcript` evidence source and B extracts `own_words` candidates from it under the same quote
rule (§3.5.3) against the transcript text; `media_seconds` ride the existing per-job ceiling
(`CLUE_ARV2_MEDIA_SECONDS_CEILING`, 02 §6). No account-side media in v26.x (the one account
podcast found in production featured the *former* CMO, plan §0 item 12).

---

## §8 Observability

### 8.1 Spans and attributes (OTel → Langfuse through the existing filter, 02 §8.1)

All under the job's `fleet.task` root trace (one trace per job since PR #90, 02 §8.1), named
`arv2.v26.<stage>`, each with `job_id, run_id, workspace_id, account_id, subject_kind,
recipe_version=27, plan_sha, attempt`:

| Span | Attributes |
|---|---|
| `arv2.v26.compile` | `context_id, cached, personas, titles_total, source{model,default}` |
| `arv2.v26.committee` | `roles_searched, records, nominated, alternates, web_gap_nominated, ai_ark_wait_ms_total` |
| `arv2.v26.acquire` (per batch/round: `phase ∈ A1|A2|A3-1|A3-2|gap`) | `ops_planned, ops_issued, ops_replayed, ops_succeeded, ops_empty, ops_failed, ops_unknown, pool_reads, duplicate_fetches, provider_ms_sum, drain_ms_sum, wall_ms, timed_out` |
| `arv2.v26.extract` (per stage) and one generation per call | `sources, chunks, calls, chars_in, tokens_in, tokens_cached, tokens_out, candidates, rejected{quote_partial,quote_not_found,quote_too_long,class_invalid,typed_mismatch}, floor_hits, anchored, unanchored, retries, failed` |
| `arv2.v26.followups` (per round) | `rules_fired{rule_id}, ops, deduped, unrenderable` |
| `arv2.v26.gap` | `classes_below_min{class}, ops, after{class}` |
| `arv2.v26.wait_pools` | `children, present, absent, waited_ms` |
| the judge turn (existing `account-research.turn` / new `person-research.turn`, from the role — 02 §8.1's `role.replace('_','-') + ".turn"`) | trace tags gain `v26`, `account:<domain>`, `job:<id>` and metadata `job_id` (02 §8.1 records both absent on v4) |
| `arv2.v26.pages` and one generation per section | `page, sections, written, repaired, skipped_unchanged, failed, duration_ms{section}` |
| `arv2.v26.refresh` | `sections_checked, sections_changed, written` |
| `arv2.v26.settle` | `cost_usd, credits, rounds_used, rounds_max, operations_used, operations_max, context_peak_tokens` |

The `db.critical_section` seam (02 §8.3) gains **one** new site — the `_db_lock` **wait** at
`_connection()` (`critical_section("arv2.db_lock.wait")` around the `async with self._db_lock`
alone, W2-20): the number 02 §8.5 item 1 says nobody measures.

**Trace size (review A M9, the plan's "unaddressed" 100 MB ceiling).** A job's trace is bounded by
construction on r27: every string the SDK exports is 8,000-char-masked (02 §8.1), the pre-step's
≈ 100 provider spans therefore cost ≤ 8 KB each (≈ 1 MB), each judge generation records its input
at ≤ the context cap (60k tokens ≈ 240 KB) × ≤ 20 rounds ≈ 5 MB, and extraction generations are
≤ 24k-char inputs × ≤ 120 calls ≈ 3 MB — ≈ 10 MB per account job at the structural maximum,
against 03a §3.4's ≈ 100 MB for a 60-call v25 run at 200k context. `arv2.v26.settle` adds
`trace_bytes_estimate` (the sum of the exported string lengths the handler counted) so the RC gate
can assert `max trace bytes per job < 50 MB` (05 owns the line).

### 8.2 Metrics (OTel, `libs/clue-obs/clue_obs/otel/metrics.py` gains an `arv2.v26.*` set; the
v4 harness has none today, 02 §8.4)

`arv2.v26.db_lock_wait_ms` (histogram) · `arv2.v26.stage_duration_ms{stage}` (histogram) ·
`arv2.v26.candidates{subject_kind,class,source_kind}` (counter) ·
`arv2.v26.quote_rejections{reason}` (counter) · `arv2.v26.followup_ops{rule_id}` (counter) ·
`arv2.v26.gap_rounds{class}` (counter) · `arv2.v26.budget_use_ratio{kind=rounds|operations|context,
subject_kind}` (histogram, at settle) · `arv2.v26.ai_ark_wait_ms` (histogram) ·
`arv2.v26.duplicate_fetch` (counter) · `arv2.v26.pool_read` (counter) ·
`arv2.v26.brief_resubmits` (counter) · `arv2.v26.over_cap_items{class}` (counter) ·
`arv2.v26.cost_usd{stage}` (counter, from the ledger at settle). Gated by
`CLUE_ARV2_V26_METRICS_ENABLED` (true).

### 8.3 Release tag on traces

`CLUE_RELEASE` (exists, blank — `.env.example:317`, 02 §8.1 "never set") is **set by
`deploy/vm/deploy.sh`** from the git sha it already puts into the image tag (02 §8.1), so Langfuse's
`release=` carries it and every v26 span adds `clue.release`. The job row keeps no version column;
the pair `(profile_sha256, clue.release)` on the trace is the version record.

### 8.4 Dashboards for the replay gate (plan §6)

Four Langfuse/SQL views, each filterable by `run_id` and `recipe_version`:

1. **Cost and time per account** — `cost_usd{stage}` summed over the account job and its children
   (ledger `phase='result'` + `agent_model_call` by `arv2_quality_execution`, 02 §8.2) and
   `launch → last publish_page` wall time; targets from plan §3.
2. **Recall** — AT-1 candidate recall and AT-9 follow-up chain recall, computed by the replay
   script over the frozen pools (`scripts/arv2_v26_replay_gate.py`, which reads `follows` from the
   ledger entries and the 01b chain lists) and emitted as the gauge `arv2.v26.replay_recall{test}`.
3. **Zero-lists** — counts that must be 0: `brief_resubmits` ending in `needs_review/brief_invalid`,
   refused finishes, refused listings (`ls`/`glob`/`grep` errors), media operations, operations
   with `won=False` outside a re-drive (repurchase), `duplicate_fetch`, wrong-employer committee
   items (`wrong_entity` on class `committee`).
4. **Budget use** — the `budget_use_ratio` distributions per role; a run touching 1.0 on rounds or
   operations is the "depth starved" signal plan §8 names (raise the budget before anything else).

---

## §9 Flags and rollout

### 9.1 Recipe selection (R2, P5 — 04 §2.5 adopted)

- Two recipe integers, one program: **r26** = the week-1 mint (`CURRENT_RECIPE_VERSION` becomes
  26 on day 4 of week 1, 04 §7.5), **r27** = this pipeline (`CURRENT_RECIPE_VERSION` becomes 27 at
  the W3 mint). `quality_catalog.py:14`'s constant is the newest version the code knows and the
  upper bound; `launch-v4-r26.json` and `launch-v4-r27.json` are hashed at boot like r25
  (02 §5.6).
- **The P5 selector** (three settings, 04 §2.5; §10 C1): `CLUE_ARV2_RECIPE_VERSION` (blank = the
  code's `CURRENT_RECIPE_VERSION`) is the recipe new launches pin by default;
  `CLUE_ARV2_RECIPE_PILOT_VERSION` + `CLUE_ARV2_RECIPE_PILOT_WORKSPACES` (comma list) make the
  listed workspaces launch at the pilot version instead. `recipe_version_for(settings, workspace_id)`
  in `arv2/quality_catalog.py` returns the pilot version for a listed workspace, else
  `arv2_recipe_version or CURRENT_RECIPE_VERSION`, and refuses any value outside
  `range(2, CURRENT_RECIPE_VERSION + 1)` as the typed launch refusal `recipe_version_unavailable`
  (§3.1). Read by the launch's profile-sha derivation and nowhere else; the job's
  `input_refs.quality_recipe_version` is stamped from the run's pinned bundle at compose (02 §1.2)
  exactly as today, so every later behaviour gate reads the job, never the env.
- **Ladder branches** (`quality_research_wiring.py:312-346`): `version >= 27 → v27 / v27-person`;
  `version == 26 → v26 / v26-person` (the r26 mint); `25` unchanged.
- **Code gates**: `quality_recipe_version >= 26` for the r26 items (W1-2/3/5/8/9/12/13/14 — 04 §3);
  `>= 27` through one predicate `uses_v26_pipeline(scope)` in `quality_policy.py` for everything
  this document designs: the pre-step, the extractor filling `acquire@2`'s `candidates`,
  `submit_brief`, the per-role allowances, clearing values and caps, raw reads off, no fallback
  chain, the person floor at import (D11), the `pending_continuations` predicate, and the page
  writer's brief mode. The `contact_page` continuation (P1) and `CLUE_ARV2_MEDIA_ENABLED` are r26
  gates this pipeline inherits.

### 9.2 Rollout, in order (review A Q16: stated once, here and in 04 P5 identically)

1. Week 1: the r26 mint lands; `CURRENT_RECIPE_VERSION = 26`; the three P5 lines blank. RC-1 runs on
   r26 (it is what makes W1's gains and its replay measurable — R2).
2. The r27 mint lands with the W3-26 migration applied (`alembic upgrade head` before the workers
   boot); `CURRENT_RECIPE_VERSION = 27`.
3. **Pilot:** `CLUE_ARV2_RECIPE_VERSION=26` (the default for every workspace) +
   `CLUE_ARV2_RECIPE_PILOT_VERSION=27` + `CLUE_ARV2_RECIPE_PILOT_WORKSPACES=<one workspace>`; set
   the r27-only lines (`RESEARCH_EXTRACT_AGENT_MODEL` at D4's pick, `PERSON_RESEARCH_AGENT_MODEL`,
   `RESEARCH_NARRATIVE_AGENT_MODEL`, `CLUE_RELEASE` via deploy.sh); D8/D9 defaults are already
   pinned in §10. P6 (§3.2) is a go/no-go line before this step (05 §6).
4. The replay gate (plan §6; 05) passes **twice** on Dialpad + Loopio.
5. **Cutover:** blank `CLUE_ARV2_RECIPE_VERSION` (→ 27) and the two pilot lines. r26 jobs in
   flight finish on their pin; the r25/r26 profiles, tools and ladder entries stay forever (catalog
   immutability, 03a §2.1).

### 9.3 v25 and r26 untouched — the proof obligations

`tests/arv2/test_quality_json_dossier.py` keeps asserting the v25 shape for `version=25`, the r26
shape for 26, and gains the r27 constants; `tests/arv2/test_quality_owned_narrative.py` and the DB
tests that assert `input_refs["quality_recipe_version"] == CURRENT_RECIPE_VERSION` (02 §5.6 item 7)
are re-pointed at `recipe_version_for(settings, ws)`; `tests/arv2/test_settings.py` proves the three
P5 fields parse (blank, int, list) and `tests/arv2/test_account_research_launch_db.py` proves a
pilot workspace pins the pilot bundle, a non-pilot one the default, and an unminted pilot version is
refused `recipe_version_unavailable` (04 P5's tests); the replay of a stored v25 job
(`test_quality_driver_db.py`) must produce byte-identical receipts after the change (the regression
that proves "untouched").

### 9.4 Rollback path

- **During the pilot (step 3):** remove the workspace from `CLUE_ARV2_RECIPE_PILOT_WORKSPACES` →
  its next launch pins 26. In-flight r27 jobs keep running on their pin (they are self-contained:
  markers, pool artifacts, `acquire@2`, `submit_brief`, the continuation all key on the job); an r27
  job that must be abandoned is `suspend`ed and left (a re-drive would resume r27 — correct, the pin
  is the contract).
- **After cutover (step 5):** set `CLUE_ARV2_RECIPE_VERSION=26`. Same semantics.
- **The design's one migration stays** (W3-26's five role constraints / six predicates, §1.1;
  W2-17 and W2-19 are W2's own, 04 §10): rollback is configuration, not a
  downgrade — the widened CHECKs are inert for v25/r26 rows, and the downgrade refuses while any
  `person_research` row exists (so it is never run against a pilot's rows). The new
  `artifact_reference` kinds and `input_refs` keys are inert for v25/r26 readers.
- A relaunch of the same request after a rollback is a **new run** (the profile sha is in the
  request digest, §3.1), so a rolled-back account can be re-researched on r26 without a manual
  row deletion.

---

## §10 Deterministic parameter sheet (the single sheet — R7; 04 §9 and 05 are regenerated from it)

Every setting the design introduces or changes. "Where read" names the code site the setting is
consumed at (new modules per §1.1; existing sites by their 02/03a citation). The `.env.example`
line is the exact text to add in the ARV2 block (02 §6; after `.env.example:217`), or the model
block (`.env.example:366-444`) for `*_AGENT_MODEL*`. Defaults marked **D4** / **D8** / **D9** /
**D11** are founder decisions; the design ships the recommended value and a ruling replaces it as
an env change (02 §10 item 20). Every v26 setting is a `Settings` field named `arv2_v26_<lower>`
unless it extends an existing name; a name appears here **once** and nowhere else in a different
spelling.

**C0 — recipe-26 and W2 switches (every recipe; owned by 04 W1/W2/P3, listed here so the sheet is one)**

| Setting | Default | Unit | Where read | `.env.example` line |
|---|---|---|---|---|
| `CLUE_ARV2_ACCOUNT_CLEAR_TRIGGER_TOKENS` / `CLUE_ARV2_PERSON_CLEAR_TRIGGER_TOKENS` | 100000 / 100000 | tokens | `ClearToolUsesEdit(trigger=)` on recipe < 27 (04 W1-1) | `CLUE_ARV2_ACCOUNT_CLEAR_TRIGGER_TOKENS=100000`, `CLUE_ARV2_PERSON_CLEAR_TRIGGER_TOKENS=100000` |
| `CLUE_ARV2_CLEAR_KEEP_RESULTS` | 6 | tool results | `ClearToolUsesEdit(keep=)` on recipe < 27 (04 W1-1) | `CLUE_ARV2_CLEAR_KEEP_RESULTS=6` |
| `CLUE_ARV2_ACCOUNT_CONTEXT_WINDOW_TOKENS` / `CLUE_ARV2_PERSON_CONTEXT_WINDOW_TOKENS` | 200000 / 200000 | tokens | the `CompactionSettings` window on recipe < 27 (04 W1-1) | `…=200000`, `…=200000` |
| `CLUE_ARV2_VIEW_FORMAT` / `CLUE_ARV2_VIEW_MAX_CHARS` | `text` / 80000 | Literal[`text`,`json`] / chars | the plain-text views (04 W1-4) | `CLUE_ARV2_VIEW_FORMAT=text`, `CLUE_ARV2_VIEW_MAX_CHARS=80000` |
| `CLUE_AGENT_L1_AS_MESSAGE` | false | bool | the duplicate L1 prompt (04 W1-6) | `CLUE_AGENT_L1_AS_MESSAGE=false` |
| `CLUE_ARV2_DRAIN_OUTSIDE_SLOT` | true | bool | slot release before `_drain` (04 W1-7) | `CLUE_ARV2_DRAIN_OUTSIDE_SLOT=true` |
| `CLUE_ARV2_PAGE_GUIDE_VERSION` | `v2` | guide set | `page_writer_models(settings, …)` (04 W1-13) | `CLUE_ARV2_PAGE_GUIDE_VERSION=v2` |
| `CLUE_ARV2_RECOVER_ON_SUCCESS` | false | bool | `recover_acquisitions` on the success path (04 W2-17) | `CLUE_ARV2_RECOVER_ON_SUCCESS=false` |
| `CLUE_ARV2_JOB_MAX_DB_CONNECTIONS` | 3 (0 = the worker-wide lock; the kill switch) | connections per job | the research tool transactions (04 W2-15) | `CLUE_ARV2_JOB_MAX_DB_CONNECTIONS=3` |
| `CLUE_ARV2_INDEX_LAZY` | true | bool | Exa result-text indexing (04 W2-19, after RC-2) | `CLUE_ARV2_INDEX_LAZY=true` |
| `CLUE_DB_POOL_SIZE` / `CLUE_DB_MAX_OVERFLOW` (existing) | sized by 04 P3 | connections | the engine pool | comment updated by P3 |
| `CLUE_ARV2_PAGES_PER_SECTION` | true | bool | the per-section page writer (§3.8; 04 W3-25) | `CLUE_ARV2_PAGES_PER_SECTION=true` |

**C1 — recipe selection and rollout (P5, 04 §2.5 adopted)**

| Setting | Default | Unit | Where read | `.env.example` line |
|---|---|---|---|---|
| `CLUE_ARV2_RECIPE_VERSION` | (blank = `CURRENT_RECIPE_VERSION`) | recipe int in `range(2, CURRENT + 1)` | `recipe_version_for` (launch, §9.1) | `CLUE_ARV2_RECIPE_VERSION=` |
| `CLUE_ARV2_RECIPE_PILOT_VERSION` | (blank) | recipe int | `recipe_version_for` | `CLUE_ARV2_RECIPE_PILOT_VERSION=` |
| `CLUE_ARV2_RECIPE_PILOT_WORKSPACES` | (blank) | csv workspace ids (`NoDecode` + validator, as `agent_model_context_windows`) | `recipe_version_for` | `CLUE_ARV2_RECIPE_PILOT_WORKSPACES=` |
| `CLUE_ARV2_MEDIA_ENABLED` (every recipe, so no `V26` infix — 04 §0.8, W1-12) | false | bool | `build_*_tools` media gate (§7) + the W4 boot gate | `CLUE_ARV2_MEDIA_ENABLED=false` |
| `CLUE_ARV2_V26_METRICS_ENABLED` | true | bool | `clue_obs` metrics (§8.2) | `CLUE_ARV2_V26_METRICS_ENABLED=true` |
| `CLUE_RELEASE` (existing, blank) | set by `deploy/vm/deploy.sh` to the git sha | string | Langfuse `release=` (02 §8.1) | unchanged line; deploy sets it |

**C2 — the contract: caps and minimums (§2.1; values = 01b §6, R10)**

| Setting | Default | Where read | `.env.example` line |
|---|---|---|---|
| `CLUE_ARV2_V26_CAP_TRIGGER` / `_INITIATIVE` / `_PAIN` / `_MOTION_PROOF` / `_STACK` / `_COMMITTEE` / `_WATCH_OUT` / `_NOT_FOUND` | 10 / 5 / 5 / 5 / **8** / **10** / **4** / 3 | `submit_brief@1` (over-cap marking), the page packets | `CLUE_ARV2_V26_CAP_TRIGGER=10` … one line each |
| `CLUE_ARV2_V26_CAP_REMIT` / `_PROBLEM_NOW` / `_OWN_WORDS` / `_PROUD_OF` / `_HOOK` / `_CAREER_ARC` / `_DO_NOT_MENTION` | 2 / **5** / **8** / **3** / **4** / 1 / 1 | same | one line each |
| `CLUE_ARV2_V26_MIN_TRIGGER` / `_COMMITTEE` / `_INITIATIVE` / `_OWN_WORDS` / `_PROBLEM_NOW` / `_REMIT` | 3 / 4 / 1 / 2 / 1 / 1 | the gap round (§3.5.7); the ledger trailer | one line each |

**C3 — compile and committee (§3.2)**

| Setting | Default | Unit | Where read | `.env.example` line |
|---|---|---|---|---|
| `CLUE_ARV2_V26_ROLE_TITLES_MAX` | 12 | titles per persona | A0.0 validator | `CLUE_ARV2_V26_ROLE_TITLES_MAX=12` |
| `CLUE_ARV2_V26_ROLE_SEARCH_SIZE` | 5 | AI Ark `size` | A0 `people_by_roles` | `CLUE_ARV2_V26_ROLE_SEARCH_SIZE=5` |
| `CLUE_ARV2_V26_COMMITTEE_ALTERNATES_PER_ROLE` | 3 | records → committee-class candidates | `committee_rank` | `CLUE_ARV2_V26_COMMITTEE_ALTERNATES_PER_ROLE=3` |
| `committee_cap` (launch input; run row) | 5 | contacts nominated | existing (02 §1.1) | — |
| `CLUE_ARV2_AI_ARK_MIN_GAP_S` (existing) | 10.5 | s | existing pacing (02 §2.3) | unchanged |

**C4 — acquisition (§3.3)**

| Setting | Default | Unit | Where read | `.env.example` line |
|---|---|---|---|---|
| `CLUE_ARV2_V26_ACCOUNT_SEARCH_NUM_RESULTS` | 8 | Exa `numResults` | `acquisition_plan` (A1 searches, A3, gap) | `CLUE_ARV2_V26_ACCOUNT_SEARCH_NUM_RESULTS=8` |
| `CLUE_ARV2_V26_ACCOUNT_SEARCH_TEXT_MAX_CHARS` | 1500 | chars per result | `search_body(text_max_chars=)` | `CLUE_ARV2_V26_ACCOUNT_SEARCH_TEXT_MAX_CHARS=1500` |
| `CLUE_ARV2_V26_ACCOUNT_DEEP_NUM_RESULTS` | 40 | Exa `numResults` | A1 `research_deep` args | `CLUE_ARV2_V26_ACCOUNT_DEEP_NUM_RESULTS=40` |
| `CLUE_ARV2_V26_ACCOUNT_CITED_FETCH_MAX` | 10 | URLs | A1 `T_cited_pages` | `CLUE_ARV2_V26_ACCOUNT_CITED_FETCH_MAX=10` |
| `CLUE_ARV2_V26_ACCOUNT_SITE_PAGES_MAX` (R10) | 4 | URLs | A1 `T_site_pages` | `CLUE_ARV2_V26_ACCOUNT_SITE_PAGES_MAX=4` |
| `CLUE_ARV2_V26_PERSON_SEARCH_NUM_RESULTS` | 8 | Exa `numResults` | A2 searches | `CLUE_ARV2_V26_PERSON_SEARCH_NUM_RESULTS=8` |
| `CLUE_ARV2_V26_PERSON_SEARCH_TEXT_MAX_CHARS` | 1500 | chars | A2 searches | `CLUE_ARV2_V26_PERSON_SEARCH_TEXT_MAX_CHARS=1500` |
| `CLUE_ARV2_V26_PERSON_DEEP_NUM_RESULTS` | **12** (D9) | Exa `numResults` | A2 `research_deep` | `CLUE_ARV2_V26_PERSON_DEEP_NUM_RESULTS=12` |
| `CLUE_ARV2_V26_PERSON_DEEP_TEXT_MAX_CHARS` | **4000** (D9) | chars per result | A2 `research_deep` `contents.text.maxCharacters` | `CLUE_ARV2_V26_PERSON_DEEP_TEXT_MAX_CHARS=4000` |
| `CLUE_ARV2_V26_PERSON_DEEP_HIGHLIGHT_MAX_CHARS` | 1000 | chars | A2 `contents.highlights.maxCharacters` | `CLUE_ARV2_V26_PERSON_DEEP_HIGHLIGHT_MAX_CHARS=1000` |
| `CLUE_ARV2_V26_PERSON_CITED_FETCH_MAX` | 6 | URLs | A2 `P_cited_pages` | `CLUE_ARV2_V26_PERSON_CITED_FETCH_MAX=6` |
| `CLUE_ARV2_V26_PERSON_POST_PAGES_MAX` (R10) | 4 | URLs | A2 `P_post_pages` | `CLUE_ARV2_V26_PERSON_POST_PAGES_MAX=4` |
| `CLUE_ARV2_V26_FETCH_MAX_CHARS` | 8000 | chars | every `fetch_page` (`max_chars`) | `CLUE_ARV2_V26_FETCH_MAX_CHARS=8000` |
| `CLUE_ARV2_V26_RECENCY_DAYS` | 270 | days, rounded to month start | dated templates' `startPublishedDate` | `CLUE_ARV2_V26_RECENCY_DAYS=270` |
| `CLUE_ARV2_V26_DEEP_SURFACE` | `search-deep-reasoning` (**D8**; already what `exa_client.py:523` hard-codes) | Literal[`search-deep-reasoning`] (`agent-runs` refused until priced) | `research_deep` dispatch | `CLUE_ARV2_V26_DEEP_SURFACE=search-deep-reasoning` |
| `CLUE_ARV2_V26_EXTRACT_DEEP_RESULT_TEXT` | true (D9 second half) | bool | B source selection | `CLUE_ARV2_V26_EXTRACT_DEEP_RESULT_TEXT=true` |
| `CLUE_ARV2_V26_ACQUIRE_WALL_S` | 300 | s per batch | A0/A1/A2/A3/gap | `CLUE_ARV2_V26_ACQUIRE_WALL_S=300` |
| `CLUE_ARV2_V26_SUBJECT_LOCK_RETRY_S` | 15 | s | `enrich_contact`/`lookup_person` retry | `CLUE_ARV2_V26_SUBJECT_LOCK_RETRY_S=15` |
| `CLUE_ARV2_V26_DRAIN_RETRIES` | 1 | count | `_drain` DBAPIError retry | `CLUE_ARV2_V26_DRAIN_RETRIES=1` |
| `CLUE_ARV2_V26_ACQUISITION_PLAN_ENABLED` | true | bool | the pre-step's acquisition plan (A1/A2/A3/gap + B; 04 W3-22 — `false` is W3-22's rollback) | `CLUE_ARV2_V26_ACQUISITION_PLAN_ENABLED=true` |
| `CLUE_ARV2_V26_AS_OF_DATE` | (blank = today) | ISO date | `acquisition_plan.plan`'s `since` only (§3.3.1) — pins dated templates so a replay across a month boundary is byte-identical (05 §2.1 `--as-of`) | `CLUE_ARV2_V26_AS_OF_DATE=` |
| `CLUE_ARV2_ACCOUNT_PROVIDER_CONCURRENCY` (existing) | 4 | per job per provider | unchanged | unchanged |

**C5 — follow-ups and the gap round (§3.4, §3.5.7; aligned to 01b, R9/R10)**

| Setting | Default | Unit | Where read | `.env.example` line |
|---|---|---|---|---|
| `CLUE_ARV2_V26_FOLLOWUP_ROUNDS_MAX` | 2 | rounds | `followups` executor | `CLUE_ARV2_V26_FOLLOWUP_ROUNDS_MAX=2` |
| `CLUE_ARV2_V26_FOLLOWUP_OPS_PER_ROUND_ACCOUNT` | **11** (01b T1 maxima + 1) | ops | executor | `CLUE_ARV2_V26_FOLLOWUP_OPS_PER_ROUND_ACCOUNT=11` |
| `CLUE_ARV2_V26_FOLLOWUP_OPS_PER_ROUND_PERSON` | **8** | ops | executor | `CLUE_ARV2_V26_FOLLOWUP_OPS_PER_ROUND_PERSON=8` |
| `CLUE_ARV2_V26_GAP_ROUNDS_MAX` | 1 | rounds | gap round | `CLUE_ARV2_V26_GAP_ROUNDS_MAX=1` |
| `CLUE_ARV2_V26_GAP_OPS_PER_CLASS` | 2 | ops | gap round | `CLUE_ARV2_V26_GAP_OPS_PER_CLASS=2` |
| rules file | `followups/v1/rules.json` (resource, sha-pinned; rows = 01b's eleven floor pairs) | — | `launch-v4-r27.json` | — (not env) |

**C6 — extraction (§3.5; R12, R16(c))**

| Setting | Default | Unit | Where read | `.env.example` line |
|---|---|---|---|---|
| `RESEARCH_EXTRACT_AGENT_MODEL` | `google/gemini-3.8-flash` (**D4**; a leaf call, no role — R12) | OpenRouter id | `quality_extract` + A0.0 compile (03a §8b precedent `page_writer_runtime.py:98-106`) | `RESEARCH_EXTRACT_AGENT_MODEL=google/gemini-3.8-flash` in the model block |
| `RESEARCH_EXTRACT_AGENT_MODEL_EFFORT` | `low` | effort | same | `RESEARCH_EXTRACT_AGENT_MODEL_EFFORT=low` |
| `CLUE_AGENT_MODEL_CONTEXT_WINDOWS` (existing) | + `google/gemini-3.8-flash=<window>` | registry | the guard test (03a §2.2) | entry appended |
| `CLUE_ARV2_V26_EXTRACT_BATCH_SOURCES` | 4 | sources per call | batcher | `CLUE_ARV2_V26_EXTRACT_BATCH_SOURCES=4` |
| `CLUE_ARV2_V26_EXTRACT_BATCH_MAX_CHARS` | 24000 | chars per call | batcher | `CLUE_ARV2_V26_EXTRACT_BATCH_MAX_CHARS=24000` |
| `CLUE_ARV2_V26_EXTRACT_CHUNK_CHARS` | 20000 | chars | chunker | `CLUE_ARV2_V26_EXTRACT_CHUNK_CHARS=20000` |
| `CLUE_ARV2_V26_EXTRACT_CHUNK_OVERLAP_CHARS` | 500 | chars | chunker | `CLUE_ARV2_V26_EXTRACT_CHUNK_OVERLAP_CHARS=500` |
| `CLUE_ARV2_V26_EXTRACT_MIN_CHUNK_CHARS` | 2000 | chars (the halving floor) | §3.5.4 | `CLUE_ARV2_V26_EXTRACT_MIN_CHUNK_CHARS=2000` |
| `CLUE_ARV2_V26_EXTRACT_MAX_OUTPUT_TOKENS` | **2000** (R16(c)) | tokens per call | request `max_tokens` | `CLUE_ARV2_V26_EXTRACT_MAX_OUTPUT_TOKENS=2000` |
| `CLUE_ARV2_V26_EXTRACT_MAX_CALLS_ACCOUNT` / `…_PERSON` | **120 / 60** (2× expected; makes the extraction ceiling structural) | calls per subject | `quality_extract` counter | `CLUE_ARV2_V26_EXTRACT_MAX_CALLS_ACCOUNT=120`, `CLUE_ARV2_V26_EXTRACT_MAX_CALLS_PERSON=60` |
| `CLUE_ARV2_V26_EXTRACT_RETRIES` | 1 | count | JSON repair retry (not truncation) | `CLUE_ARV2_V26_EXTRACT_RETRIES=1` |
| `CLUE_ARV2_V26_EXTRACT_CONCURRENCY_PER_JOB` | 6 | calls | `_semaphore("extract")` | `CLUE_ARV2_V26_EXTRACT_CONCURRENCY_PER_JOB=6` |
| `CLUE_ARV2_V26_EXTRACT_CONCURRENCY_PER_PROCESS` | 16 | calls | handler-wide semaphore | `CLUE_ARV2_V26_EXTRACT_CONCURRENCY_PER_PROCESS=16` |
| `CLUE_ARV2_V26_EXTRACT_WALL_S` | 180 | s per stage (one halved re-run after it) | B | `CLUE_ARV2_V26_EXTRACT_WALL_S=180` |
| `CLUE_ARV2_V26_QUOTE_ELISION_MIN_WORDS` | 8 | words per span (field bound) | quote rule | `CLUE_ARV2_V26_QUOTE_ELISION_MIN_WORDS=8` |
| `CLUE_ARV2_V26_QUOTE_MAX_CHARS` | 600 | chars (field bound) | quote rule | `CLUE_ARV2_V26_QUOTE_MAX_CHARS=600` |

**C7 — the judges (§3.6, §5; R6, R16(a)(b))**

| Setting | Default | Unit | Where read | `.env.example` line |
|---|---|---|---|---|
| `CLUE_ARV2_V26_ACCOUNT_MAX_MODEL_ROUNDS` / `…_PERSON_…` | 20 / 12 | rounds | `Allowance` + `TurnBudgetMiddleware` by subject kind (`quality_research_wiring.py:1233-1238`) | `CLUE_ARV2_V26_ACCOUNT_MAX_MODEL_ROUNDS=20`, `CLUE_ARV2_V26_PERSON_MAX_MODEL_ROUNDS=12` |
| `CLUE_ARV2_V26_ACCOUNT_MAX_OPERATIONS` / `…_PERSON_…` | 30 / 15 | provider ops (`state <> 'failed'`) | `acquire@2` budget count | `…=30`, `…=15` |
| `CLUE_ARV2_V26_ACCOUNT_CONTEXT_CAP_TOKENS` / `…_PERSON_…` | 60000 / 56000 | tokens | `compaction_for` wrapper (03a §8d) | `…=60000`, `…=56000` |
| `CLUE_ARV2_V26_ACCOUNT_CLEAR_TRIGGER_TOKENS` / `…_PERSON_…` | 45000 / 42000 | tokens | `ClearToolUsesEdit(trigger=)` | `…=45000`, `…=42000` |
| `CLUE_ARV2_V26_CLEAR_KEEP_RESULTS` | 4 | tool results | `ClearToolUsesEdit(keep=)` | `CLUE_ARV2_V26_CLEAR_KEEP_RESULTS=4` |
| `CLUE_ARV2_V26_JUDGE_RAW_READS` (R16(a)) | false | bool | `ResearchViewMount` r27 rendering (§3.6.1) | `CLUE_ARV2_V26_JUDGE_RAW_READS=false` |
| `CLUE_ARV2_V26_FALLBACK_MODELS` (R16(b)) | (blank = no fallback) | csv model ids | the chain is `GatewayConfig.fallback_models` (`libs/clue-config/clue_config/gateway.py:100, 182, 191`), read by `GovernedAgentChatModel` (`agent_model.py:1047`) through the one provider `build_agent_model_provider(config)` builds (`agent_model_wiring.py:13`); `AgentModelProvider.build(...)` (`clue_agents/ports.py:200-208`) gains a `fallback_models` override (A, 04 W3-24 item 7) that `quality_research_wiring.py:785-794` passes for `account_research` / `person_research` from this value — replacing `CLUE_AGENT_FALLBACK_MODELS` for them | `CLUE_ARV2_V26_FALLBACK_MODELS=` |
| `CLUE_ARV2_V26_MODEL_RETRY_DELAY_S` | 60 | s (`available_at` on suspend) | §3.6.5 | `CLUE_ARV2_V26_MODEL_RETRY_DELAY_S=60` |
| `CLUE_ARV2_V26_MODEL_RETRY_SUSPENDS` | 3 | suspends per turn before `needs_review/model_unavailable` | §3.6.5 (`input_refs.v26_model_suspends`) | `CLUE_ARV2_V26_MODEL_RETRY_SUSPENDS=3` |
| `CLUE_ARV2_V26_BRIEF_RESUBMITS` | 2 | rejected submissions | `submit_brief@1` | `CLUE_ARV2_V26_BRIEF_RESUBMITS=2` |
| `CLUE_ARV2_V26_RECEIPT_CANDIDATES_MAX` | 20 | candidates inline (≤ 10 KiB receipt) | `acquire@2` receipt | `CLUE_ARV2_V26_RECEIPT_CANDIDATES_MAX=20` |
| `CLUE_ARV2_V26_PEOPLE_SLICE_PER_CONTACT` | 20 | candidates | account L7 assembly | `CLUE_ARV2_V26_PEOPLE_SLICE_PER_CONTACT=20` |
| `CLUE_ARV2_V26_ACCOUNT_SLICE_MAX` | 60 | candidates | contact L7 assembly | `CLUE_ARV2_V26_ACCOUNT_SLICE_MAX=60` |
| `CLUE_ARV2_V26_L7_MAX_TOKENS_ACCOUNT` / `…_PERSON` | 40000 / 32000 | tokens (bytes ÷ 4) | L7 trim | `…=40000`, `…=32000` |
| `CLUE_ARV2_V26_PEOPLE_POOL_WAIT_S` | 240 | s | account judge wait (§3.6.4) | `CLUE_ARV2_V26_PEOPLE_POOL_WAIT_S=240` |
| `CLUE_ARV2_V26_ACCOUNT_POOL_WAIT_S` | 120 | s | contact judge wait | `CLUE_ARV2_V26_ACCOUNT_POOL_WAIT_S=120` |
| `ARV2_ACCOUNT_AGENT_MODEL` (existing) | `x-ai/grok-4.6` | id | driver override (02 §5.1) | unchanged |
| `ARV2_PERSON_AGENT_MODEL` (existing) | `x-ai/grok-4.6` | id | driver override | unchanged |
| `ARV2_PERSON_AGENT_MODEL_EFFORT` (existing) | unchanged | effort | driver override | value unchanged; its `.env.example` comment corrected (04 W3-26) |
| `PERSON_RESEARCH_AGENT_MODEL` / `_EFFORT` (R4) | `x-ai/grok-4.6` / `medium` | id / effort | the new role's registry + gateway effort (03a §2.2) | two lines in the model block beside `ACCOUNT_RESEARCH_AGENT_MODEL` |
| `ACCOUNT_RESEARCH_AGENT_MODEL_EFFORT` (existing) | `medium` | effort | gateway (02 §5.1) | unchanged |
| profile `max_output_tokens` | 16384 / 12288 | tokens | profile pin (not env; C36) | — |
| `CLUE_ARV2_ACCOUNT_MAX_RUNTIME_S` (existing) | 0 | s | unchanged — no wall clock on C | unchanged |

**C8 — pages (§3.8; R11, R16(d), C31)**

| Setting | Default | Unit | Where read | `.env.example` line |
|---|---|---|---|---|
| `RESEARCH_NARRATIVE_AGENT_MODEL` / `_EFFORT` (existing) | **D4** small model (`google/gemini-3.8-flash` recommended; Grok only if the founder's two readings fail on prose while depth passes — review B §3 row 2) / `medium` | id | page writer (02 §1.5) | value change only |
| `CLUE_ARV2_DISPLAY_MAX_PARALLEL` (existing) | 30 | sections in flight | the per-section gather (03a §8g) | unchanged |
| `CLUE_ARV2_V26_PAGE_SECTION_TIMEOUT_S` | 120 | s per section | `write_checked` | `CLUE_ARV2_V26_PAGE_SECTION_TIMEOUT_S=120` |
| `CLUE_ARV2_V26_PAGE_SECTION_REPAIRS` | 1 | repairs | `write_checked` | `CLUE_ARV2_V26_PAGE_SECTION_REPAIRS=1` |
| `CLUE_ARV2_V26_PAGE_MAX_ATTEMPTS` (R16(d)) | 2 | continuation/in-job attempts per page | `contact_pages_due` + the in-job write (§3.8) | `CLUE_ARV2_V26_PAGE_MAX_ATTEMPTS=2` |
| `CLUE_ARV2_V26_PAGE_ACCOUNT_CONTEXT_ITEMS` | 10 | items | contact packets | `CLUE_ARV2_V26_PAGE_ACCOUNT_CONTEXT_ITEMS=10` |
| `CLUE_ARV2_V26_MISC_SECTION` | `off` (**D3** yes; `on` = filtered dump) | Literal | page packets + `quality_pages` dump | `CLUE_ARV2_V26_MISC_SECTION=off` |
| `CLUE_ARV2_V26_PAGE_WALL_S` | 300 | s per page set | E | `CLUE_ARV2_V26_PAGE_WALL_S=300` |
| `CLUE_ARV2_PAGE_WRITER_TIMEOUT_S` (existing) | 900 | s | v25/r26 path only | unchanged |

**C9 — orchestration (§6)**

| Setting | Default | Unit | Where read | `.env.example` line |
|---|---|---|---|---|
| `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS` (existing) | 4 → **6 after W2-15** (post-W2-20 measurement) | jobs per process | `_jobs` (02 §1.2) | value change, with the comment updated |
| `CLUE_ARV2_QUALITY_RECONCILE_INTERVAL_S` (existing) | 10 | s | the sweep (offers contacts and contact pages) | unchanged |
| `CLUE_FLEET_*` (existing) | unchanged | | | unchanged |

Settings the design deliberately does **not** add: a per-provider spend cap (money caps only
record, 02 §10 item 3 — the fixed plan is the cap); a judge wall-clock (ruling 2026-09-27); any
count of words in prose (ruling 2026-10-04); a committee approval gate (D10); a separate
`CLUE_ARV2_V26_ACCOUNT_REFRESH_SECTIONS` list (the refresh rewrites every section whose slice sha
changed, C31).

---

## Appendix A — decisions this design made that the plan left open (as reconciled)

1. **Role titles are compiled, not assumed** (§3.2 A0.0): the pinned personas are prose
   documents with no title list, so one cheap, context-keyed, cached leaf call compiles
   `persona → titles/seniority/functions` and the Exa template vocabulary — **ICP front-matter
   `search_terms:`/`titles:` win verbatim when present**, the compile is frozen as a fixture per
   pilot context, and a code-constant fallback covers a persona with no titles.
2. **`submit_brief@1` replaces the save/validate/finish sequence** (§3.7; R3): one tool call that
   validates by shape, derives `review` (never `insufficient_context`), derives the widened
   `claim_type`, restores evidence from candidates, marks over-cap items instead of refusing, and
   runs the unchanged `finish_dossier` import. The end of every turn is two rounds, not eleven.
3. **Acquire receipts are cleared like any tool result** (§5.3; R6): the one divergence from
   03a §8d, forced by the 60k cap arithmetic (keep 4); safe because citations are content-addressed
   candidate ids resolved server-side, and the full list stays one read away.
4. **Deterministic waits, recorded** (§3.6.4; R5): the account judge waits bounded time for its
   contacts' final pools (`research_candidates`) and the contact judge for the account's first
   pool (`research_candidates_first`); the L7 records exactly what was present.
5. **The sibling rule** (§3.3.4; C10): cross-job de-duplication by `(ws, run, account, kind,
   request_sha256)` over `arv2_research_operation`, serving the sibling's stored candidates with no
   re-extraction — no operation-pool schema change.
6. **The contact page is a research-kind `contact_page` continuation** (§3.8; R11, 04 §0.5) with
   an attempt ceiling, not a display-kind task — the second divergence from 03a §8.
7. **Deep-report result texts are extracted** at the D9 pin (≈ $0.01 per contact; they carry the
   own-words spans AT-1 measures); D9 itself is one bounded offline comparison at the freeze.
8. **The person floor runs at import for r27** (§2.5) — provisional ruling R15, founder decision
   D11; the other outcome is one predicate line.
9. **One migration from this design, not none** (§1.1, §9.4; W2's two are W2's own, 04 §10): the
   `person_research` role widens five role constraints (six predicates); every
   other durable addition is an artifact, a reference kind or an `input_refs` key, and rollback is
   configuration.
10. **The web-gap committee fill** (§3.2): when AI Ark yields fewer than four records, the gap
    round's web search nominates LinkedIn-bearing candidates up to the cap through the existing
    web-nomination body, so "every contact gets full research" holds on thin AI Ark coverage.
11. **The `entity` trigger kind** (§3.4; R9): the extractor emits `entities[]` per candidate and
    rules may chase a person, vendor, phrase, URL, subject-site page, event or prior employer named
    inside a candidate — the grammar that makes all eleven of 01b's floor pairs fire, with
    `follows` on every A3 operation so AT-9 is computable.
12. **Two ceilings** (§5.5; R16): the modeled $9.4 the gate enforces and the structural ≈ $23 the
    settings alone guarantee, with raw reads off, no fallback chain, extraction output and call
    caps, and a page attempt ceiling closing review B's uncapped paths.
13. **`@2` is minted once** (§3.6.3; R13): in r26, with `candidates` and `ledger` already in the
    shape, so the r27 extractor changes no tool shape.

## Appendix B — A-owned prerequisites this design depends on (from 02/03a and the reviews)

- **P1** deferred contact page (04 §2.1) — designed in §3.8/§6.1 as the research-kind continuation;
  (A) wires `_contact_page_continuation`, `contact_pages_due`, the settle enqueue and the attempt
  ceiling.
- **P2** re-mint — §3.6.1 and 02 §5.6's procedure for r26 and r27, including the five hard-coded
  tests 04 §8.3 names.
- **P3** pool/pgbouncer sizing before W2-15 — §6.2.
- **P5** recipe selection — §9.1, 04 §2.5.
- **P6 (R14; blocking before any r27 pilot):** the `profile_ref` v4 filter fix in
  `stop_contact_jobs` and `claim_writer` (§3.2), with the DB test that a v4 person job's
  privacy-stop sets `input_refs.privacy_stopped` and the claim writer refuses; 05 §6 makes it a
  go/no-go line.
- **The `person_research` role, in full (corrected 02 §3.8 and 03a §2.2):** the W3-26 migration
  widens **five** DB constraints (**six** predicates) — `agent_turn_role` and `agent_plan_role` (`6628a407e993:59-62`,
  re-installed by the `_roles` loop at `f4b30cb3d088:23-26`), `agent_delegation_roles`
  (`f4b30cb3d088:27-30`), `agent_model_call_role` (`65880921cd52:20-25`, re-installed by
  `c237eb027732:29-41`), and `quality_execution_role`'s value set **and** its root predicate
  `parent_execution_id IS NULL AND role='account_research'` (`f4b30cb3d088:70-72`) — without the
  last two the lane fails at its first model-call record and its first plan; **and** the code
  gates that refuse any role but `account_research`, which must admit `person_research`:
  `quality_provider_tools.py:142` (otherwise "specialists request acquisition through their
  parent" on the first evidence call), `quality_json_dossier.py:198`, `quality_views.py:210,215,308`
  (operations, capabilities and context views) and `quality_tools.py:89`
  (`quality_committee_tool.py:88` stays account-only; `quality_dossier.py:168` and
  `quality_owned_narrative.py:174,225` guard pre-25 surfaces a r27 judge does not use); plus the
  `AgentRole` member, `quality_profiles` resolving it for person scopes at the ladder (`:785`),
  `bind_execution(role=…)` (`:707`), the constitution (`:888`), the dossier-middleware check
  (`:729`), and its model-block lines with a context-window entry (03a §2.2).
- The research `AgentTurnRequest` subject list for account jobs (every committee contact) so the
  turn's artifacts and the model-input artifacts carry contact bindings — §3.9; and the extractor
  envelope binding after every call — §3.5.6.
- `claim_type` widened to four values on `FindingV2`/`EntryV2` — never on `Finding` (the `@1`
  sha) — and the claim kinds each imports as (04 W1-2; review A Q20/Q23) — §2.2, §3.7.
- The r26 person prompt and `person_task_instruction` no longer naming the parent dossier for a
  contact released before the import (review A Q9/Q37) — §6.1.
- W1-6 (the duplicated L1 prompt) — a cost line in §5.1, not a dependency.

## Appendix C — 01b alignment (applied in this round; R9/R10)

01b landed between this document's first and reconciled versions. Applied here: (1) the rule table's
rows are 01b §3's eleven floor pairs, each expressed in §3.4's grammar with the `entity` trigger
kind where the pair is a lead found inside a candidate; the committed `followups/v1/rules.json` is
derived from 01b's `fixtures/rule_table.json` by W0; (2) the per-round follow-up caps are 01b T1's
per-run maxima + 1 (11 account / 8 contact); (3) the class caps are 01b §6's values (§2.1, §10 C2);
(4) the quote rule is 01b §5's (§3.5.3) and `fixtures/quote_fidelity.json` is its regression;
(5) 01b's `fixtures/nothing_lost/<account>.json` are the AT-6 fixtures and `fixtures/chains/<account>.json`
the AT-9 oracle, joined on the ledger's `follows` (01b's `nyc.gov` nothing-lost fixture is absent
on disk — review A K4 — and is 01b's to add); (6) if a later 01b revision needs an operation kind
§3.4 does not allow, that kind is added to the executor's closed set here, with its budget, before
the rules file is pinned.
