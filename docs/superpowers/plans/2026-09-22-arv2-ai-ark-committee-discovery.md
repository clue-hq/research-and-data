# ARV2 AI Ark committee discovery: implementation plan

**Status:** implemented locally, 2026-09-22. Steps 1–8 have implementation and offline
evidence; the pre-existing import/type-check failures are recorded in the
[acceptance report](2026-09-22-arv2-ai-ark-committee-acceptance.md). Step 9 is not initiated.
**Later founder ruling, 2026-09-22:** make v2 the default for future launches and build the
media-research improvement on that flow. Settings/example/local selectors now use v2;
historical jobs retain their pins. Live acceptance and deployment are still separate.
**Design:** [company-scoped committee discovery](../specs/archive/2026-09-22-arv2-ai-ark-committee-discovery-design.md).
**Base inspected:** `8df27dd25` on `origin/research-streaming`, pulled before planning.

## 1. Deliverable and boundaries

Give the existing account agent company-scoped SMART people search after account research,
with enough source context to choose a committee intelligently. Pass selected profiles into
the existing person jobs and enrich work emails and phones alongside person depth. Preserve
the claim/identity/storage/fleet seams and leave R4 company discovery unchanged.

The founder approved the flow, both enrichment channels, and continuation after exhausted
account Exa research failure. The founder's implementation request accepts the design's §10.3 engineering defaults.
It does not initiate live paid research or deployment.

Establish evidence and replay contracts before changing agent behavior. Each step must leave
current v1 behavior working. Do not begin by swapping prompt order while the tool still requires
known names. Steps below are sequential dependencies, with coherent local commits at green
checkpoints; nothing is pushed without explicit instruction.

## 2. Work sequence

### Step 1 — Review contracts and establish the baseline

**Inspect:** the master plan; ARV2 launch/store/driver/tools/committee modules; the shared
identity, compliance and storage seams. Review frontend contracts before any display change.

- [x] Refresh the branch against the then-current authorized upstream; preserve local user
  files. This planning session's pull does not guarantee upstream will stay unchanged.
- [x] Review design §10.3 as one contract package; record revisions without reopening the
  founder's already approved flow or channel/failure decisions.
- [x] Specify versioned operation, candidate-handle, selection-evidence, persona-pin, provider-
  binding and person-seed models, including ownership and lifecycle rules.
- [x] Settle multi-person-page erasure using existing storage mechanisms. Default to invalidating
  and purging the containing page if safe redaction is unsupported. An unresolved erasure path
  cannot accompany activation of a new persistent profile cache.
- [x] Inspect persona lineage metadata; where no exact ICP-version reference exists, implement
  lineage-unknown state rather than pretending there is a verified match.
- [x] Establish a focused offline baseline. Record pre-existing failures separately; no live
  client tests and no shared/lane database use.
- [x] Add the precise approved supersession to the master plan's AI Ark and R2/R3 descriptions.
  Preserve R4, media and general-purpose web-search decisions.

**Exit:** reviewed engineering contracts and known baseline.

### Step 2 — Extend the provider adapter without agent activation

**Modify:** `platform/api/clue_api/arv2/ai_ark_client.py`.
**Tests:** `tests/arv2/test_ai_ark_client.py`.

- [x] Expose company ID, person identity, source receipt and complete role-search paging metadata.
  Preserve current `people_by_name` callers and their named-lookup semantics.
- [x] Add `people_by_roles`: exact company ID or explicit domain fallback, SMART titles,
  optional validated seniority/functions, page and size. Construct provider JSON in code.
- [x] Extend email export with a person-ID input, preserving legacy LinkedIn input. Use the v1
  endpoint initially and normalize its documented no-email response.
- [x] Add typed phone lookup using LinkedIn or domain/name input; never person ID alone.
- [x] Preserve full scrubbed profiles and endpoint-specific empty/error semantics. Update
  no-email cost accounting, with provider-reported versus inferred charges distinguished.
- [x] Keep the shared caller, raw sink, ledger, scrubbing, pacing, halt rules and retries.
- [x] Test correct nested SMART shape, company locking, optional-filter omission, invalid inputs,
  page 0/page 1, no matches, response identity, phone arrays/duplicates, email verdicts, billing
  and removal of sensitive fields before raw persistence.

**Exit:** operations proven with offline fixtures; no agent uses the new path yet.
**Suggested checkpoint:** `feat(arv2): add company-scoped people and phone provider operations`.

### Step 3 — Add durable references, replay and context pins

**Modify:** ARV2 `account_research_store.py`, `account_research_launch.py`,
`account_research_driver.py`, `account_research_tools.py`; storage/ledger receipt seam as needed.
**Proposed new module:** `platform/api/clue_api/arv2/research_operations.py`.
**Migration:** generated random Alembic revision from the then-current head.

- [x] Implement design §6's operational record pointing to the existing ledger/artifact.
  Cover role search, email, phone and the account deep-attempt ordering receipt.
- [x] Add canonical fingerprints, ownership checks, leases and persisted result resolution.
  Successful, empty, failed and unknown are distinct; rationale text is not a billing key.
- [x] Commit reusable results before returning handles. Reconstruct from saved responses on
  replay; do not reissue an uncertain dispatched request or repurchase after a claim-write failure.
- [x] Add persona pins/missing states and reference-only job input/profile fields. Replay uses
  the original run pins; legacy rows retain explicit v1 interpretation.
- [x] Extend artifact-subject registration/erasure to all returned profiles, including unselected
  candidates. Every candidate/seed read checks scope, artifact integrity and erasure state.
- [x] Test rollback, leases, equivalent requests, crash boundaries, tampering, cross-workspace
  references, multi-person-page erasure and persona changes during a run.

**Tests:** extend `test_account_research_store_db.py`, `test_account_research_launch_db.py`,
`test_provider_ledger_db.py`; add operation replay tests; extend appropriate
`tests/compliance/test_dsar*.py` and storage artifact tests.

**Exit:** recoverable authorized references; no duplicate raw fact store. Up/down/up migration
smoke passes on an isolated disposable DB and Alembic reports exactly one head.

### Step 4 — Add role discovery and evidence-aware selection

**Modify:** ARV2 `account_research_tools.py`, `account_research_claims.py`.
**Tests:** `test_account_research_tools.py`, `test_account_research_claims.py`.

- [x] Add `discover_people` and `read_people_result` to the v2 account tools. Runtime owns
  company scope; agent chooses roles, titles, optional filters, pages and refinements.
- [x] Reuse the persisted company lookup; handle ambiguity and exact-domain fallback explicitly.
- [x] Permit discovery after either a successful account deep operation or an exhausted failure.
  An earlier call returns a recoverable ordering instruction; a display-stage label is insufficient.
- [x] Expose full profile material by reference and useful page metadata. Equivalent queries can
  support several role hypotheses without repeat spending.
- [x] Store concise role/search rationales as assessments with evidence references. Never demand
  hidden chain of thought or turn a hypothesis into a provider-certified fact.
- [x] Add provider/web/unfilled-role selection variants. Resolve provider facts server-side and
  keep profile provenance separate from the agent's committee-role rationale.
- [x] Distinguish not-found from evidenced vacancy; deduplicate people before applying committee
  cap; checkpoint the ordered selection claim references for settlement recovery.
- [x] Test unknown-name discovery, paging, refinement, forged handles, zero-result gaps,
  provider-only evidence selection and finalization after account Exa failure.

**Exit:** account tool flow discovers and selects people without pre-supplied names or a mandatory
web-confirmation URL. No mechanical confidence/coverage veto is introduced.

### Step 5 — Bind identities and persist the person handoff

**Modify:** ARV2 `committee_step.py`, store/driver settlement, identity seam and claim provenance.
**Tests:** `test_committee_step_db.py`, identity tests, `test_account_research_driver_db.py`.

- [x] Add workspace-scoped provider-subject binding with uniqueness and evidence through the
  shared identity package. Avoid parallel copies of resolution SQL in account/person tools.
- [x] Resolve provider ID and LinkedIn consistently. Support a selected person without LinkedIn;
  prevent ambiguous name matching from merging distinct provider identities.
- [x] Record provider/LinkedIn conflicts and existing-contact employment conflicts. Do not
  silently reparent a contact or substitute the account used by its person research job.
- [x] Atomically write contact, committee claims, ordered handoff state, person job and its
  reference-only seed. Retain deterministic job identity and post-commit queue behavior.
- [x] Resume settlement from live claim references after a crash. Reuse the existing deterministic
  profile mapper and one provenance adapter; no raw profile in finalization or queue JSON.
- [x] Test duplicate selection, cap ordering, same-name people, no LinkedIn, another employer,
  simultaneous selection, partial failure and repeated settlement/enqueue.

**Exit:** one local person job per selected distinct person, bound to correct source and account.

### Step 6 — Reuse the person seed and enrich both channels alongside depth

**Modify:** ARV2 `account_research_driver.py`, `account_research_tools.py`,
`account_research_claims.py`. **Tests:** person tool/driver paths, claims and compliance tests.

- [x] Compose the person from the source profile, selection rationale and pinned client/account
  context. Treat provider text as external data, not instructions; preserve subject locking.
- [x] Materialize available professional facts before channel requests can fail.
- [x] Begin independently keyed email/phone operations in the existing person job while its
  agent can continue Exa/web depth. Automatic startup and explicit agent requests use one
  operation owner, so concurrent calls cannot buy the same channel twice.
- [x] Email uses the selected provider ID. Phone initially uses selected-profile domain/name
  plus returned-identity checks; LinkedIn preference awaits the live contract canary.
- [x] Reuse `core.work_email` with its verdict/check time. Store the primary valid provider-
  ordered number in `core.direct_phone`; other numbers remain in governed source material.
  Do not invent validation, DNC or consent metadata, or promote a channel to an identity key.
- [x] Show independent channel states through person state/receipts. Join in-flight calls under
  existing shutdown limits; unfinished/unknown is not reported as not found.
- [x] Preserve unseeded on-demand lookup. After it obtains a bound profile, use the same mapper
  and channel service instead of a second enrichment implementation.
- [x] Prove seeded jobs buy no additional named search. Test channel independence, missing
  channels, mismatched phone identity, repeated tool calls, timeout, provider halt and erasure.

**Exit:** email/phone claims and person depth survive independent partial failures.

### Step 7 — Mint v2 resources and support pinned versions

**New:** five-file `platform/agents/catalog/entity-research/arv2-account/v2/` and
`arv2-person/v2/` bundles. **Modify:** catalog loader, launch/driver selectors and documentation.
**Tests:** `test_account_research_catalog.py`, driver/launch version cases.

- [x] Write consistent profile, prompt, dossier, audit and manual resources. Remove mandatory
  web-first/name-first committee instructions from every v2 resource.
- [x] Describe role planning, SMART semantics, company scope, refinement, profile reuse,
  independent channel outcomes, gaps and stopping. Preserve the person-depth charter.
- [x] Resolve resources and internal tool sets by each job's profile/version; preserve v1 bytes
  and interpret old rows explicitly as v1. Pin child authority at creation.
- [x] Record implemented status in the master plan and ARV2 README only when true. Preserve
  historical canary reports; corrections are dated additions.
- [x] Add settings only when needed and maintain example-file parity. No model changes or new
  Head-of-ABM `web_search@1` grants are required by this feature.

**Exit:** old and new jobs use their own resource/tool contracts; switching future-launch
selection does not break queued v1 jobs.

### Step 8 — Integrated offline and isolated-database acceptance

- [ ] Close every acceptance gate without exceptions. A01–A17 have local evidence; A18
  retains the pre-existing package-import guard failure, documented in the acceptance report.
  Complete design A01–A18 with actual evidence. Use scripted model turns and fixtures to
  test behavior, not tests that only search prompt strings.
- [x] Exercise account finalization → contacts → queued persons → seed reuse → both channels
  and depth → final receipts, including replay and partial failures.
- [x] Run relevant lint/type checks, focused regression suites, identity/erasure checks and
  disposable-DB migration smoke. Confirm one Alembic head and ARV2-only dependency/read guards.
- [x] Verify existing committee/email rendering and source authorization. Phone storage is not
  a shipped phone UI; any visible slot first needs the frontend contract review and its checks.
- [x] Verify env/example parity; record base failures and live tests still outstanding.
- [x] Commit coherent verified slices locally. Do not push, publish or deploy without instruction.

Focused existing offline suites, to supplement new operation/identity/privacy tests:

```sh
.venv/bin/python -m pytest -q \
  tests/arv2/test_ai_ark_client.py \
  tests/arv2/test_account_research_tools.py \
  tests/arv2/test_account_research_claims.py \
  tests/arv2/test_account_research_driver.py \
  tests/arv2/test_account_research_catalog.py \
  tests/arv2/test_provider_ledger.py \
  tests/arv2/test_person_compliance.py \
  tests/arv2/test_import_guard.py
```

Run DB tests separately against an explicitly provisioned disposable database; inspect the
actual connection configuration first. Live client tests are excluded from the command above.

**Exit:** reviewable release candidate with live acceptance explicitly outstanding.

### Step 9 — Live canary, review, activation and rollback

- [ ] When explicitly initiated, run Probook and Zafran with current ICP/persona context and
  actual company IDs. Do not seed discovery with historical committee names.
- [ ] Verify real SMART acceptance, paging, employer binding and semantic empty results.
- [ ] Probe the phone domain/name versus LinkedIn discrepancy in controlled calls, not as
  automatic repeated attempts across every contact.
- [ ] Measure role coverage, selection relevance, incorrect/stale identities, missed useful
  people, email/phone yield, latency and spend against a current human-reviewed reference set.
- [ ] Audit the provider ledger: no repeated named lookup for seeded people; account for all
  failed/empty attempts and distinguish estimates from settled spend.
- [ ] Review the evidence before production activation. Poor coverage is a reported result,
  not a reason to hardcode PoC names or fabricate a pass.
- [ ] Rollback changes future launches to v1 while retaining v2 readers/data. No automatic
  historical rerun or live DB downgrade.

**Exit:** live behavior demonstrated and release decision recorded. Offline green is insufficient.

## 3. Main risks and corresponding proof

| Risk | Required proof |
| --- | --- |
| SMART works in docs but fails live | Exact role-search request accepted and inspected in both canaries. |
| Matching title, irrelevant responsibility | Evidence-backed agent rationale and human-reviewed relevance comparison. |
| Role query becomes a company roster | Required role titles, runtime-owned employer scope and visible paging. |
| Duplicate charges during retries | One operation owner, crash/concurrency tests and live ledger audit. |
| Stale employment contaminates committee | Company/profile/contact binding checks and explicit conflict fixtures. |
| Candidate cache evades erasure | Multi-person-page and unselected-candidate erasure tests before activation. |
| Phone data suggests unsupported assurance | Preserve provider metadata; no invented validity/DNC/consent claims. |
| Version bump breaks queued jobs | Old-row v1/v2 replay tests and future-launch-only rollback. |
| Unrelated scope growth | R4, general web search, media, outreach and frontend redesign remain outside. |

## 4. Planning-session verification

This plan is grounded in source at `8df27dd25` and the provider documentation linked in the
design. The planning task changes documentation only. Runtime tests, migrations, paid provider
calls and live end-to-end acceptance are future work and are not claimed here.


## Authorized live follow-up — September 22

The founder requested the latest v3 flow (which includes this committee implementation) and a
comparison against the historical PoC, without a separate fresh v2 control. Real company-bound
SMART searches ran for both Probook and Zafran through the platform agents. Probook independently
selected all five historical members; Zafran selected three historical members plus a new
marketing-operations candidate. Two other historical Zafran subjects were researched separately.
Selected-profile reuse and both enrichment channels have live evidence; four Probook enrichment
cases were invalidated by a test-harness identity error; a separate on-demand recovery completed with emails and phones for all four. Original seeded-handoff outcomes remain qualified.

See the [live comparison and trace report](2026-09-22-arv3-live-poc-comparison.md) for measured
coverage, limits and receipts. The experiment uncovered and fixed a real shared-pacing deadlock
in `5c0b9b912`. Quality acceptance remains open; this does not close every Step 9 gate or change
production activation. The planning-session verification above remains historical.
