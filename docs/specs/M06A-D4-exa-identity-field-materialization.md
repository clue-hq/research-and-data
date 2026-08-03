# M06A D4 — Exa identity admission and discovery-field materialization

**Status:** implemented acceptance contract

**Parent:** `M06A-exa-websets-sumble-discovery-integration.md`, Slice D4

**Boundary:** D4 consumes only D3-terminal, immutable Exa item snapshots. It performs no Exa
network calls, creates no new paid operation, and does not seal a batch or advance the project to
scoring. D5 owns the seal and project-phase barrier.

## 1. Outcome

D4 turns every durable Exa company item into one of four explicit identity outcomes:

- `admitted`: the item resolves to a canonical workspace-local account;
- `merged`: an actual losing account identity was collapsed into a survivor;
- `review_required`: M2 created an identity-review task and D4 retains that task reference;
- `excluded`: the item cannot honestly become an account, with a durable reason.

Only an admitted or merged item may produce account claims. A new claim is keyed to the current
survivor, carries its immutable item artifact, and remains append-only. If that account later
merges, the claim remains on its original identity row and is read through M2's canonical-member
view; D4 never rewrites claim ownership. Every required discovery
field then receives either a resolved winning claim or an honest non-value state. D4 may reach
`seal_pending` only after every item has a terminal admission and all admitted accounts have D4
field decisions; review and retry states leave the batch blocked in field materialization.

## 2. Inputs and preconditions

For one `(workspace_id, batch_id)`:

1. the batch and immutable plan exist in the same workspace;
2. the batch is in `identity_resolution`, `field_materialization`, or replayable `seal_pending`;
3. every planned operation is D3 seal-terminal;
4. every successful Exa operation has exhausted item pagination and final reconciliation;
5. every consumed item has a content-addressed raw artifact; and
6. the operation is a company search-only Webset already reconciled by D3.

A failed precondition writes no partial D4 state. The materialization transaction locks the batch,
so two workers cannot race to insert equivalent claims.

## 3. Seams and ownership

### 3.1 Provider adapter

`clue_research.adapters.exa_websets` owns a pure normalizer from the typed, already-validated
`ExaWebsetItem` plus its terminal enrichment definitions to a D4 company observation. It:

- requires a company item;
- derives the registrable-domain identity hint from `properties.url`;
- preserves every criterion evaluation and its `yes | no | unclear` state;
- maps each enrichment result through the definition's `metadata.clueFieldKey`;
- retains reasoning and references;
- emits explicit missing observations for terminal `result=null`;
- projects the approved built-ins only; and
- excludes `foundedYear` and `webTraffic` by construction.

The adapter does not import identity, claim-store, durable-repository, or API-root code.

### 3.2 Snapshot-backed discovery channel

The adapter exposes the normalized item's grounded `CandidateRecord`. Its record handle is the Exa
item id and its source URL is the company URL. This satisfies the existing `DiscoveryChannel`
grounding contract without submitting another query. The API root supplies only the already-loaded
snapshot set; the channel does not perform provider I/O.

### 3.3 API composition root

`clue_api.exa_websets_materialization` composes, but does not duplicate:

- D1 repositories and artifact-subject binding;
- the D4 Exa normalizer/channel;
- M2 `admit`, `resolve`, `disposition`, `surviving_id`, and merge history;
- the claim-store field registry, append-only insert, and deterministic merge view; and
- the versioned D0 discovery-envelope policy.

No research subsystem imports another subsystem. Cross-component orchestration remains at the API
root.

## 4. Identity and evidence rules

1. Name and registrable domain are identity hints before field claims exist.
2. A company item without a non-empty name or resolvable domain is excluded; D4 never creates a
   name-only or domain-only fiction to satisfy completeness.
3. M2 is the only component allowed to mint or merge an `account_entity`.
4. Mid-band ambiguity records `review_required` plus the exact `identity_review_task.id`; it cannot
   seal until a human admits or excludes it.
5. A replay reads the durable M2 review decision. An open task remains blocked; `create_new_entity`
   or `merge_into` continues with the recorded survivor; a dismissed or explicitly rejected
   observation becomes an honest exclusion. The terminal candidate link retains the same review
   task id, and its composite foreign key prevents cross-workspace lineage. D4 never guesses the
   human outcome.
6. Claims are attached only after `surviving_id` is known. A later merge redirects the candidate
   link to the current survivor while preserving the originally admitted account id and claim ids.
7. Two items with the same domain map to one survivor while retaining separate source-item and
   artifact references. A `merged` link is used only when a real losing entity exists; repeated
   observations that resolve directly to the same survivor remain `admitted`.
8. The discovery-provenance claim is item-idempotent when an artifact key is supplied. Criterion
   evaluations, reasoning, references, Exa item id, and Webset/search lineage remain in its
   structured discovery metadata.

## 5. Field mapping policy

All value claims use `source_key=exa_websets`, `extraction_method=api`, the D3 raw item artifact,
the strongest relevant reference URL, zero claim-level cost (the operation receipt owns paid
spend), and `research_mode=account_discovery`.

| Exa observation | Canonical field | Value rule |
|---|---|---|
| company name | `core.account_name` | non-empty string |
| company URL | `core.primary_domain` | registrable domain only |
| industry | `core.industry` | non-empty string |
| employees | `core.employee_count` | non-negative integer |
| headquarters/location | `core.hq_location` | normalized object with required `raw` |
| about | `core.company_about` | non-empty string |
| `financials.revenueAnnual` | `core.annual_revenue` | provider estimate, USD mapping policy, item update date |
| `financials.fundingTotal` | `account.total_funding` | provider-estimated USD amount |
| latest funding round | `account.recent_funding` | amount when present plus optional round |
| mapped LinkedIn enrichment | `core.company_linkedin_url` | one absolute LinkedIn company URL |
| mapped revenue-number enrichment | `core.annual_revenue` | USD provider estimate, item update date |
| mapped revenue-band enrichment | `core.revenue_band` | closed vocabulary only |
| mapped company email | `core.company_email` | one syntactically valid public company email |
| mapped company phone | `core.company_phone` | one syntactically valid public company phone |

The raw provider snapshot keeps every additive field. `foundedYear` and `webTraffic` are never
projected into claims. Null built-ins do not create claims. A terminal null enrichment creates a
missing attempt with its reasoning/reference lineage, not a null-valued claim.

Live contract note: company email and phone are requested/stored in the enrichment definition as
`text`, while terminal item results specialize their formats to `email` and `phone`. D4 permits
exactly those two logical-field specializations; every other result format must equal its terminal
definition format.

Built-in financial values are explicitly stamped `provider_estimate`; they are not represented as
audited or company-reported truth. A future provider-contract revision must replace the versioned
USD mapping if Exa documents different currency semantics.

## 6. Criterion evidence

Criterion evaluations do not become independent account facts. They are structured discovery
evidence on the item-specific discovery-provenance claim:

```text
criterion, satisfied(yes|no|unclear), reasoning, references[]
```

D4 never rewrites `no` or `unclear` to `yes`, and it does not exclude a D3-reconciled search item
solely because of that status. Conflicting or uncertain criteria remain visible to scoring/review.

## 7. Field-resolution algorithm

For each admitted survivor and every D0 envelope field:

1. collect D4 claims from every source item mapped to that survivor;
2. apply the field's ordered canonical attempts;
3. read the merge-resolved claim-store result across the survivor and all transitive losing
   identities for each attempt;
4. write `resolved` with all contributing claim ids and the winning claim when one exists and is
   not conflicting;
5. write `conflict` with every disagreeing claim when authoritative observations conflict;
6. write `confirmed_missing` when a requested terminal enrichment returned `null`, or when the
   terminal company item explicitly contains a nullable/absent built-in property that D4 attempted;
7. write `failed_terminal` when a required attempt was never planned or provider evidence cannot
   be safely canonicalized; this deliberately blocks D5 until a human accepts missing or excludes
   the account; and
8. write `account_excluded` only after an explicit account exclusion.

Hard identity name/domain must resolve and may never use a missing disposition. `identity.account_name`
uses the canonical account plus its `core.account_name` evidence claim; `identity.primary_domain`
uses the canonical account plus `core.primary_domain`.

## 8. Replay and atomicity

- Equivalent claim identity is `(canonical identity family, field_key, source_key, artifact_key,
  value_json)`. A later identity merge therefore reuses a claim written on the losing member.
- A replay reuses the existing claim id; it never inserts an equivalent second claim.
- Discovery-provenance identity additionally includes the item artifact when supplied, so multiple
  Exa items for one survivor retain separate admission evidence.
- Candidate links and field resolutions use their existing immutable replay contracts.
- When an already-materialized account later merges, D4 writes survivor-keyed field resolutions
  that reference the original append-only claims. Historical loser-keyed resolutions remain as
  lineage; D1 validates their claim membership through the same transitive identity family.
- Artifact-subject links use the existing unique upsert.
- The whole D4 batch runs in one transaction under a batch row lock. A failure rolls back account
  admission, claims, links, resolutions, normalization flags, and state changes together.
- An explicit later observation window carries new artifact keys and therefore creates new
  append-only observations rather than being hidden by the replay cache.

## 9. State transitions

```text
identity_resolution -> field_materialization -> seal_pending
```

`review_required`, `failed_retryable`, a missing hard identity, or an unprocessed item stops before
`seal_pending`. D4 never writes `sealed`. D5 independently re-evaluates all fourteen SQL conditions
inside the seal transaction.

## 10. Acceptance matrix

| Case | Required proof |
|---|---|
| real D2 two-row Webset | two canonical accounts, normalized items, item-specific discovery evidence, approved base claims, item artifacts bound to survivors, and field-resolution rows |
| real enriched item | mapped LinkedIn/email/phone claims and terminal missing revenue with references/reasoning retained |
| exact replay, fresh service process | zero Exa calls, zero new accounts, zero new equivalent claims, stable claim ids/resolutions/artifact bindings |
| same-domain adversarial items | one survivor, two candidate/source-item lineages, both artifacts reachable, no evidence loss |
| conflicting authoritative observations | both claims retained, resolution `conflict`, no silent overwrite |
| ambiguous identity | M2 review task id persisted, no claims written, batch blocked |
| reviewed identity | open-task replay creates no duplicate task; a durable create/merge decision resumes D4 and an explicit rejection excludes |
| survivor redirect after materialization | candidate link follows the transitive survivor, original claim ids are reused, no claim is rewritten or duplicated, and seal-readiness remains true |
| invalid/missing identity | explicit exclusion, no account or claims |
| field policy | about and approved financial/funding fields survive; founded year and web traffic never become claims |
| database | one Alembic head; clean upgrade/downgrade/upgrade succeeds |
| static/regression | D0–D4 targeted suite, mypy/import contracts, changed-file lint/format pass |

Live D4 acceptance reuses the already-paid D2/D3 artifacts and must make no provider request.

## 11. Explicitly out of scope

- D5 seal/manifests/project advancement;
- Sumble waterfall calls;
- contact/person discovery or contact enrichment;
- atomic intent-signal implementation;
- Exa Search API integration;
- verification/corroboration promotion; and
- changing provider billing already settled by D3.
