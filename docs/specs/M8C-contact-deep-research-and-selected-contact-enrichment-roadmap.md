# M8C — Contact-deep research and selected-contact enrichment roadmap
## Sumble professional graph + Exa Deep contact research + governed channel enrichment

> **Status:** implementation underway; C0 contract/field/policy freeze and C1 snapshot-backed
> professional materialization are mechanically accepted. C2 exact contact-subject durability is
> next. **Recorded:**
> 2026-08-05. **Parent capability:**
> [M8B account-deep provider integration](M8B-exa-sumble-account-deep-integration-roadmap.md).
> **Working branch at record time:** `platform/c8-account-profiling-integration`.
>
> M8C owns the contact-oriented work intentionally deferred by M8B: durable professional facts
> from the Sumble committee snapshot, contact-targeted Exa Deep research, selected-contact
> email/phone acquisition and independent validation, provider-neutral wait/resume composition,
> and the verified research handoff consumed by later content scaling. It does **not** create a
> second contact fleet, a Sumble-specific orchestrator, or a content-generation subsystem.

## 1. Authority and relationship to the existing system

This roadmap is a companion to M8B, not a rewrite of it. M8B remains the implementation and live
acceptance record for account profiling plus no-reveal Sumble committee discovery. M8C begins at
the boundary where M8B currently ends.

The authority order is:

1. [Architecture README](../architecture/README.md) resolves conflicts across the doc set.
2. [Harness architecture](../architecture/clue-hq-harness-architecture-and-requirements.md)
   governs the conversational, non-linear platform interaction.
3. [Platform agent runtime](../architecture/clue-hq-platform-agent-runtime.md) governs what an
   agent, worker, fleet, tool, and deepagent mean mechanically.
4. [Research architecture overview](../architecture/clue-hq-research-architecture-overview.md),
   [research layer](../architecture/clue-hq-research-layer-architecture.md), and
   [staged architecture](../architecture/clue-hq-discovery-and-research-staged-architecture.md)
   govern the claim substrate, research modes, identity, source waterfall, and output boundary.
5. [Compliance and personal data](../architecture/clue-hq-compliance-and-personal-data.md) and
   [signal execution and cost](../architecture/clue-hq-signal-execution-cost.md) govern personal
   data, use, bounded fan-out, and spend.
6. [M08 deep profiling](M08-deep-profiling.md) owns provider-neutral contact profiling and
   committee behavior; [M8A](M8A-project-run-deep-orchestration.md) owns the existing account-deep
   orchestration order; [M06A](M06A-exa-websets-sumble-discovery-integration.md) owns the Sumble S2
   release boundary; and M8B owns their Exa/Sumble account-deep composition.
7. [Doc S](../architecture/clue-hq-content-and-artifact-scaling.md) owns content and artifact
   scaling downstream of verified research. M8C defines only the research-side handoff into it.

Where a provider's current public documentation differs from M8B's captured and live-exercised wire
contract, the implementation must record that relationship and revalidate the exact endpoint,
entitlement, schema, charging event, and observed canary response before new paid behavior. Public
documentation does not silently invalidate an existing pinned contract, and an existing contract
does not authorize a new endpoint or product feature.

## 2. Outcome

Deliver one governed contact-research capability controlled by the platform deepagent and composed
inside the existing account-deep unit. For an explicitly selected subset of an identity-resolved
buying committee, it must:

1. preserve Sumble-returned professional and organization-map facts as typed, sourced claims;
2. run directional, person-targeted Exa Deep research only for admitted contact fields and gaps;
3. acquire email and/or phone only when the exact contact and exact channel reveal have been
   separately approved;
4. independently validate a channel before it is represented as verified identity or used for
   delivery;
5. resume after external waits without holding a claim transaction or duplicating spend;
6. verify identity binding, appropriateness, freshness, and evidence before promotion; and
7. expose a claim-referenced `account x contact` research view that later content scaling can
   consume without conducting research itself.

The intended composition is:

```text
platform deepagent conversation
    -> confirmed project research directive
    -> committee materialized for the account
    -> immutable selected-contact research receipt
         exact contact ids
         exact fields/questions
         exact reveal permissions by channel
         privacy + budget + source-policy refs
    -> existing detached account fleet
    -> existing AccountDeepOrchestrator
         account profiling                       [M8B: already present]
         Sumble committee acquisition/materialization [M8B: already present]
         selected-contact external preparation  [M8C: additive seam]
             Sumble snapshot professional facts
             contact-targeted Exa Deep operations
             optional email/phone operation + validation
         existing bounded profile_contact fan-out
         verification and handoff
    -> typed claims + provenance + coverage + receipts
    -> later content_run/content fleet consumes promoted claim refs
```

There is no automatic discovery-to-deep transition. There is also no independent "contact fleet"
in this design: the existing fleet schedules accounts, and each existing account orchestrator owns
its bounded contact fan-out.

## 3. Binding interaction and agency contract

### 3.1 Conversation remains non-linear

Account discovery produces context, not the next compulsory phase. After viewing discovered or
imported accounts, the user may ask the platform deepagent to:

- inspect, compare, filter, or explain accounts;
- change the ICP or discover more accounts;
- research one account or a selected subset;
- discover or refresh a buying committee;
- profile one or more already-known contacts;
- add, remove, or refine a research direction;
- allow professional research while disallowing contact reveals;
- approve email but not phone for named contacts; or
- do nothing and continue the conversation.

These are tool-capability choices made through the harness, not hardcoded platform phases. Each
tool still enforces its local database, policy, identity, and budget preconditions.

### 3.2 Research preview and durable direction

Before the first spend under a new contact-research direction, the deepagent must summarize:

- the accounts and contacts currently in scope;
- the buying-committee roles or selection rule;
- the professional fields and personal facets to research;
- the product/campaign hypotheses directing the search;
- the planned source waterfall;
- whether email and phone are excluded or separately requested;
- identity, jurisdiction, use, and evidence constraints;
- per-provider and per-channel limits; and
- expected cost units and any required approval.

The user may revise this conversationally. Durable state has two distinct forms:

1. advisory user preferences and recurring instructions enter scoped memory through its write
   seam; and
2. the exact executable plan is frozen as a confirmed, content-addressed research directive and
   pinned into the launched run.

Memory never becomes account truth. An agent draft never becomes executable merely because it was
suggested. Only a confirmed directive may authorize work.

### 3.3 Selection occurs after committee identity exists

A project directive can state a selection policy before the committee exists, for example:

```text
research up to two operations leaders and one executive sponsor;
allow professional-public facets;
do not reveal phone;
ask again before revealing email.
```

It cannot name canonical `contact_id` values that do not yet exist. After committee
materialization, the platform must resolve that policy to an immutable
`ContactResearchSelection` (name to be frozen in C0) containing at least:

- workspace, project, run, account, and directive pin/digest;
- selected canonical contact ids;
- committee/persona claim refs that explain each selection;
- admitted field keys and directional questions;
- per-contact Exa depth and limits;
- `email_reveal_allowed` and `phone_reveal_allowed` separately;
- validation requirements per channel;
- jurisdiction, use-class, source-profile, and policy revision refs;
- provider and channel budget reservations;
- human approval identity/time where required; and
- a stable content digest used in every downstream request fingerprint.

This receipt is an action-scoped authorization, not a new `CONTACT_RESEARCH` project phase. A later
selection creates a successor and affects future work only. Replay remains pinned to the original
receipt.

### 3.4 Independent invocation remains valid

The deepagent may invoke contact profiling independently of a full account-deep run when the local
preconditions already exist: canonical account, canonical contact, strong identity key, confirmed
directive, allowed field plan, jurisdiction/use policy, budget admission, and—only for a
reveal—the selected-contact authorization for that channel.

## 4. Current implementation that M8C must reuse

The codebase already has most of the provider-neutral contact research engine. M8C must extend and
compose it, not rebuild it.

### 4.1 Existing orchestration and bounded fan-out

- `platform/api/clue_api/deep/orchestrator.py` already runs account profiling, committee
  discovery, then a bounded `profile_contact` fan-out.
- `subsystems/research/clue_research/profiling/contact/worker.py` is the existing contact aspect
  worker.
- `subsystems/research/clue_research/profiling/contact/gaps.py` computes deep `contact.*` and
  `contact.facet.*` gaps from the field registry and current claims.
- `subsystems/research/clue_research/profiling/contact/fill.py` already uses the shared waterfall,
  pre-spend gate, born-correct identity binding/use classification, and same-name fail-closed
  behavior.
- Existing limits bound committee size, selected contacts, per-tier recursion, concurrent contacts,
  and spend reservations.

### 4.2 Existing registered personal-facet surface

`subsystems/research/clue_research/profiling/fields.py` currently registers deep contact facets for:

- nickname;
- stated interests;
- communication style;
- public appearances;
- publications;
- causes;
- alma mater; and
- career history.

Their current plan is Exa Deep-only. They are governed personal claims, not free-form dossier
fields. New facets remain open by field registration; M8C must not add a provider-specific branch
per facet.

### 4.3 Existing verification and handoff

The system already has:

- contact identity admission through strong identifiers;
- immutable born-correct identity-binding semantics for personal claims;
- jurisdiction/use classification and use decisions;
- evidence, source tier, verification status, freshness, and DSAR handling;
- committee role/persona claims and coverage;
- `platform/api/clue_api/contact_eligibility.py` for contact handoff and personalization
  eligibility; and
- a claim-referenced research view.

These remain authoritative. A provider response never bypasses them.

### 4.4 Existing durable external-research substrate

The generic external-research schema already models an account or contact subject and can persist
an immutable operation/snapshot. The current account-deep adapters primarily project account
subjects, so M8C must finish exact-contact projection and lookup rather than introduce a new
provider-operation table.

### 4.5 Existing directive boundary

The confirmed directive already carries `contact_profiling_allowed` and
`contact_reveals_allowed`. M8B deliberately rejects reveal-enabled launches because no selected-
contact reveal implementation exists yet. M8C replaces that coarse launch rejection with exact,
channel-specific authorization; it must not weaken the default.

## 5. Missing capability and required design deltas

### 5.1 Sumble professional facts are not first-class claims

The current Sumble committee candidate carries useful provider-returned data such as name, title,
function, level, team, location, profile URLs, and relationships. Committee materialization uses
the identity and role/persona behavior, but several professional facts remain trapped in the
candidate/snapshot rather than entering the claim store and handoff.

M8C must register and materialize a minimal professional-public set. C0 must decide the exact keys,
but the expected semantic surface is:

```text
contact.current_title
contact.job_function
contact.job_level
contact.team_membership
contact.current_location
contact.organization_relationship
```

The implementation must reuse an existing canonical field where one already represents the same
meaning. Provider-returned facts, provider-modeled relationships, and platform-inferred committee
roles must remain distinguishable in provenance and claim method.

### 5.2 Exa Deep is account-targeted in production composition

The M8B Exa path compiles and acquires account-targeted structured output. The contact fields may
name `exa_deep`, but production composition does not yet:

- compile an exact contact subject and employer binding into the request;
- produce contact-specific request fingerprints;
- acquire and persist a contact snapshot;
- look up a ready snapshot by exact contact; or
- materialize it through the existing contact resolver.

M8C must make account and contact two subject variants behind the same provider-neutral external
research seam. It must not fork the Exa provider package into a second implementation.

### 5.3 Contact-subject durability is only partially projected

The database schema accepts `subject_kind=contact` and `contact_id`, but runtime rows, ready-snapshot
references, reuse queries, materialization lookups, and indexes do not all expose or enforce the
same exact subject tuple.

The canonical operation identity must include:

```text
workspace_id
project_id
project_run_id where run-local policy requires it
subject_kind
account_id
contact_id when subject_kind=contact
provider/source_key
request_fingerprint
directive pin
contact-selection digest when applicable
```

An account snapshot must never satisfy a contact request. One contact's snapshot must never satisfy
another contact with the same name. Reuse must follow canonical merged identities deliberately,
not through loose name matching.

### 5.4 No provider-neutral contact preparation seam exists after committee

The current orchestrator prepares external committee work outside the claim transaction, then
materializes it, then directly calls contact profiling. Contact-targeted Exa and reveal/validation
may wait or paginate; they cannot execute inside the short claim transaction used to materialize
contact claims.

Add one provider-neutral preparation contract between committee materialization and contact
materialization. It receives contact research intents, returns ready/waiting/failed/budget-paused
outcomes, and knows nothing about committee inference or content. Provider-specific adapters
implement it by registration.

### 5.5 Contact reveal needs a narrower authorization model

`contact_reveals_allowed=true` is necessary but not sufficient. Reveals expose more personal data,
have separate charging events, and may be valid for one person or channel but not another.

The gate must prove all of the following before a reveal call:

1. the canonical contact belongs to the exact canonical account;
2. the contact was selected by an immutable selection receipt;
3. the requested channel is explicitly allowed;
4. personal-data, jurisdiction, lawful-basis/use, and retention policies pass;
5. the exact provider/source is admitted for the field;
6. pre-spend and the channel-specific budget reservation pass;
7. no fresh reusable validated result already exists; and
8. the stable request fingerprint has not already been submitted.

A non-selected contact or non-approved channel produces zero provider requests.

### 5.6 Channel representation and identity promotion are incomplete

The registry already contains `core.work_email`, while `ContactEntity.verified_email` is a strong
identity value. Those are not interchangeable states:

- a provider-returned email is an observed claim;
- a syntactically valid email is not necessarily reachable or independently corroborated;
- a validated, identity-bound email may become a verified identity key through a governed identity
  operation; and
- a phone number is a delivery/contact claim, not automatically an identity key.

C0 must freeze the canonical channel schema. Prefer reusing `core.work_email` if its entity scope,
pass, and governance can be corrected without changing its meaning. Add a canonical direct-phone
field only if none exists. Do not create `contact.email` and `core.work_email` duplicates.

Raw provider output must never write `ContactEntity.verified_email` directly. Promotion to the
identity entity occurs only after validation, strong binding, and conflict checks.

### 5.7 "Independent validation" needs an explicit contract

M8C must distinguish:

- **identity corroboration:** another source binds the same email/phone to the exact person and
  employer;
- **deliverability/reachability validation:** a validator assesses whether the channel is usable;
  and
- **appropriateness/use permission:** platform policy permits the intended outreach use.

These are separate decisions. The first does not prove the second; neither grants the third. C0
must specify the required combination for `observed`, `corroborated`, `validated`, and
`verified-identity` states.

### 5.8 Wake processing is provider-specific today

M8B has a Sumble committee wake worker. M8C introduces more external operations. The correct
direction is a provider-neutral external-research wake dispatcher that leases due operations and
routes by registered adapter. It must preserve provider rate limits and operation-specific
settlement, without creating a provider-specific project phase or a second research fleet.

### 5.9 The content scaling implementation is a separate boundary

The current repository has content-drafter agent resources and Doc S, but no complete production
`content_run`/`content_draft`/template-binding fleet that should be silently folded into this
milestone. M8C therefore provides a verified, claim-referenced contact research contract and one
consumer fixture. Building the full content fleet remains a separate content-plane milestone.

## 6. Provider responsibilities and wire-contract requirements

### 6.1 Waterfall by information class

| Information class | Preferred source/owner | Fallback or validation | Notes |
|---|---|---|---|
| Name and strong profile identity | Sumble People snapshot | official/professional profile | identity admission remains platform-owned |
| Current title, function, level, location | Sumble People | official employer/profile | typed professional-public claims |
| Team and organization relationship | Sumble organization/team/person graph | employer/careers primary source | label modeled versus explicit relations |
| Committee persona/role | platform committee worker | human review | never copied blindly from provider |
| Publications, appearances, career, public communication style | contact-targeted Exa Deep | primary source / reputable profile | exact-person and employer target lock |
| Email | selected-contact enrichment/reveal | independent corroboration/validator | separate channel budget and approval |
| Phone | selected-contact enrichment/reveal | independent corroboration/validator | never a default identity key |
| Contradiction or ambiguity | official employer page, professional profile, filing, or primary source | human review | empty/review is correct |

The effective source plan is versioned policy data. The table describes the intended default, not a
hardcoded provider chain.

### 6.2 Sumble

Sumble is the structured professional graph and organization-map source. The implementation should
maximize the already-acquired committee snapshot before spending again.

The current public Sumble documentation reviewed on 2026-08-05 describes a v3 API and a synchronous
`POST /v3/people/find` endpoint filtered by organization, job function, job level, country, and
other filter terms. Its documented response includes a provider person id and URL, LinkedIn URL,
name, job title, job function, job level, location/country, and start date; documented cost is one
credit per returned person. The public response shown does not document email or phone.

That differs from the repository's pinned and live-exercised M8B v9 contract. The public v3 page
does not invalidate the working v9 integration, and M8C must not rewrite M8B's history. C0 must
capture a dated public v3 fixture, retain the existing v9 fixture, and determine which entitled
contract applies to each new M8C operation. Any migration from v9 must be deliberate and separately
accepted. Until the relationship and any new capability are proven:

- do not assume Sumble returns contact channels;
- do not code a reveal against an undocumented endpoint;
- do not translate public web-application features into API guarantees;
- do preserve `credits_used`, request id, provider URLs, pagination/offset, and exact response;
- do cap people requests by selected roles/functions and exact account; and
- do reuse the M8B snapshot when it already contains the required professional facts.

Required frozen Sumble artifacts:

1. endpoint/version and entitlement;
2. request filters and maximum `limit`/offset behavior;
3. full success, empty, validation, auth, insufficient-credit, rate-limit, and server-error shapes;
4. exact charging event and returned credit counters;
5. retry and spend-unknown classification;
6. source/person/organization/team identifier stability;
7. field-level source URL semantics and freshness;
8. whether any channel reveal exists and how it is billed; and
9. immutable redacted canary fixture plus parser tests.

Official references to revalidate during C0:

- <https://docs.sumble.com/api>
- <https://docs.sumble.com/api/people>
- <https://docs.sumble.com/our-data/filter-reference>
- <https://docs.sumble.com/our-data>

### 6.3 Exa Search Deep/Deep-Reasoning

Exa Search is the open-web contact research source for admitted fields that need synthesized,
multi-source research. It is not the source of contact existence or committee membership.

The current Exa Search reference reviewed on 2026-08-05 documents `deep` and `deep-reasoning`
search types, a `people` category, `additionalQueries`, JSON `outputSchema`, returned result URLs,
`requestId`, and an endpoint-dependent `costDollars` object. M8C retains the M8B product decision
to use `type="deep-reasoning"` with a hard maximum of 50 results for this capability unless a later
accepted source-policy revision changes it.

The contact request compiler must include:

- canonical full name;
- canonical LinkedIn URL or approved strong profile key;
- canonical employer name and domain;
- known title/function/location as disambiguators;
- exact registered field keys and JSON schema;
- field-specific directional questions from the pinned directive;
- allowed/forbidden source guidance and date constraints;
- a demand for source URLs and evidence text per output field;
- an explicit same-name/person-target lock; and
- no email/phone field unless this operation is separately approved as channel enrichment.

Structured output is extraction convenience, not verification. Each value still needs an evidence
span, source URL, identity binding, use class, and promotion decision. An output that cannot be
resolved to a returned source remains unsupported.

Official references to revalidate during C0/C3:

- <https://exa.ai/docs/reference/search>
- <https://exa.ai/docs/websets/api-guide-for-coding-agents>
- <https://exa.ai/docs/websets/api-guide>

### 6.4 Exa Websets person import/enrichment

Exa Websets remains distinct from Exa Search. It may be used for a selected-contact channel
enrichment or independent corroboration if C0 freezes that contract and the effective plan selects
it.

The current Websets reference documents asynchronous lifecycle, person entities, imports of known
URLs, criteria, enrichments, polling/webhooks, external ids, and enrichment formats including
`email` and `phone`. This makes a bounded design plausible:

```text
known canonical LinkedIn/profile URL
    -> import into a run-scoped webset
    -> apply only approved email/phone enrichment
    -> wait durably
    -> persist item + enrichment results
    -> independently validate before identity promotion/use
```

It does not, by itself, prove deliverability or grant outreach permission. The exact entity import,
enrichment charging, result binding, empty semantics, and replay behavior must be canary-proven.
Discovery Websets must not be reused as the selected-contact enrichment container.

### 6.5 Official and professional primary sources

Official employer pages, leadership pages, biographies, filings, careers pages, and strongly bound
professional profiles are contradiction/fallback sources. They run through the same source-plan,
evidence, pre-spend, and identity rules. "Official" is a tier designation plus exact source key,
not permission to scrape any page or bypass terms/policy.

## 7. Target architecture and execution semantics

### 7.1 Account-deep stage composition

The existing public sequence remains `profile_account -> discover_committee -> bounded
profile_contact`. Internally, external preparation and short materialization steps become explicit:

```text
Stage 1       account profiling                        existing M8B
Stage 2A      Sumble committee external acquisition    existing M8B, outside claim tx
Stage 2B      committee identity/role materialization  existing M8B, short claim tx
Selection     resolve directive to selected contacts   new M8C receipt, no provider call
Stage 2C      Sumble professional fact materialization new M8C, snapshot-only, short tx
Stage 3A      contact external preparation             new M8C, outside claim tx
                Exa Deep contact research
                optional email/phone enrichment
                optional independent validation
Stage 3B      existing profile_contact materialization existing worker, short claim tx
Stage 4       verification, projections, handoff       existing system + additive fields
```

The stage labels are internal explanation only; they must not become a rigid user-visible workflow
or new project-run phases.

### 7.2 Provider-neutral preparation seam

C0 must freeze a protocol equivalent in responsibility to:

```python
class ContactResearchPreparation(Protocol):
    async def prepare(
        self,
        intent: ContactResearchIntent,
    ) -> ContactResearchPreparationOutcome: ...
```

The intent carries exact subject, directive, selection, fields, source plan, policy, and budget
refs. The outcome is one of:

- `READY`: all required immutable snapshots are available;
- `WAITING_EXTERNAL`: operation is submitted or still pending, with next wake information;
- `BUDGET_PAUSED`: no call occurred or further polling/materialization is safely paused;
- `NOT_ELIGIBLE`: no call occurred and governed reasons are recorded; or
- `FAILED`: terminal classified failure with spend settlement state.

The orchestrator does not branch on `provider == "exa"` or `provider == "sumble"`. It consumes
outcomes and returns the existing account-level wait/pause/failure semantics.

### 7.3 Transaction boundary

No network call, poll loop, provider backoff, or long model request may occur while a claim
transaction, exactly-once ledger claim, or account row lock is open.

```text
external side effect
    -> idempotent operation submit/poll outside claim transaction
    -> immutable raw snapshot + actual settlement
    -> READY reference
    -> short transaction reads snapshot and writes claims/refs
```

Materialization may be retried independently from acquisition. Provider cost settles once even if
claim materialization fails and is replayed.

### 7.4 Idempotency and replay

Every paid operation needs:

- stable content-addressed request fingerprint;
- uniqueness at the database boundary;
- one elected submitter under concurrency;
- immutable raw request/response/snapshot;
- provider request/operation identifiers;
- explicit spend state including spend-unknown;
- polling lease and retry classification;
- actual cost in the provider's native unit;
- conversion/estimate metadata kept separate from native units; and
- fresh-process replay that reads snapshots and performs zero provider traffic.

Changing an admitted field, selection, directive, provider contract revision, or reveal channel
changes the fingerprint. Retrying the same intent does not.

### 7.5 Identity and same-name defense

Contact Exa and channel enrichment require a strong pre-existing identity key—normally canonical
LinkedIn/profile URL. Name plus employer alone may support review but not automatic personal-claim
promotion.

Materialization must reject or route to review when:

- source content names a different employer or person;
- profile URLs conflict;
- the same name is unresolved across multiple people;
- the employment date/title contradicts the committee identity without corroboration; or
- the evidence does not bind the claimed fact to the exact contact.

Weak tier-4 personal claims remain excluded. Empty is correct.

### 7.6 Provider facts versus platform inference

At minimum, provenance must distinguish:

- `provider_returned`: literal structured provider value;
- `provider_modeled`: provider-derived relationship/category;
- `platform_inferred`: committee/persona or narrative inference from claims; and
- `human_asserted`: reviewed correction with audit provenance.

No provider job level automatically becomes an economic-buyer classification. No platform role
inference is presented as a provider-returned org-chart edge.

### 7.7 Coverage and partial completion

Contact research cannot prove it found every relevant person or every public facet. Outputs must
name:

- selected and skipped contacts;
- fields attempted, filled, empty, conflicted, or blocked;
- sources searched and unsearched;
- channels revealed, excluded, failed validation, or not requested;
- committee coverage estimate; and
- budget/policy stops.

Partial completion is a successful, truthful outcome when the accepted claims and coverage are
correct.

## 8. Research-to-content boundary

M8C stops at verified meaning. A later content fleet consumes the result; it does not become a
research resolver.

### 8.1 Contact research handoff contract

For each `account x contact x persona` selected for downstream work, the handoff must expose refs to:

- canonical account and contact identity;
- selected committee role/persona claims;
- professional facts such as title/function/team;
- promoted account pain, strategic, resonance, and value-narrative claims;
- promoted and use-cleared contact facets;
- use/appropriateness decisions and retention constraints;
- coverage and missing-data flags; and
- permitted delivery channels without placing raw channel values in general drafting context.

Every displayed or consumed assertion resolves to a claim/provenance ref. The handoff does not copy
an untraceable dossier blob.

### 8.2 Content consumption rules

- Deterministic template slots may use canonical identity and professional-public fields.
- Dynamic personalized copy may use only promoted, use-cleared contact facets and grounded value
  narrative claims.
- Missing personal evidence falls back to account-level or generic copy, or produces a review flag;
  it never invites invention.
- Email and phone route to delivery/export surfaces, not the drafting model context by default.
- A content agent cannot reveal a contact, call Exa/Sumble, or widen research scope implicitly.
- If content work identifies a research gap, the platform deepagent proposes a successor research
  directive and launches the research capability separately after any needed approval.

M8C acceptance includes a fixture proving this contract. Full content fleet scheduling, drafting,
template finalization, artifact derivation, and publishing are out of M8C scope.

## 9. Implementation slices

Every slice has a strict exit gate. Unit tests alone do not close a provider slice. No paid call
occurs without explicit live-call authorization and preflight evidence.

### C0 — Contract, field, and policy freeze

**Status:** complete. Binding acceptance record:
`M8C-C0-contact-research-contract-acceptance.md`.

**Owns**

- final contact research and selected-contact receipt schemas;
- professional and channel field keys/entity scopes;
- independent-validation state machine;
- current Sumble endpoint/version/entitlement and fixtures;
- Exa contact Deep and optional Websets enrichment wire contracts;
- native cost units, charge events, errors, rate limits, retry/spend-unknown rules;
- source-plan defaults and separate reveal budgets; and
- privacy, jurisdiction, retention, and approval policy refs.

**Exit gate**

1. No duplicate field meaning is introduced.
2. The existing v9 contract and current public/entitled contract relationship is resolved with
   dated fixtures, without silently migrating working M8B behavior.
3. "Validated" and "verified identity" have distinct, executable meanings.
4. Every request field maps to provider docs or a captured entitled canary.
5. Request fingerprints and reuse/freshness rules are specified.
6. Review signs off before migrations or live adapter work.

### C1 — Sumble snapshot-backed professional fact materialization

**Status:** complete. Binding acceptance record:
`M8C-C1-sumble-professional-materialization-acceptance.md`.

**Owns**

- registered professional-public fields;
- mapping existing Sumble committee snapshots to grounded contact claims;
- provider-returned versus modeled relationship provenance;
- strong contact/account association; and
- handoff inclusion for eligible professional facts.

**Does not own** a new Sumble request, reveal, committee classifier, or orchestrator.

**Exit gate**

1. Replaying an existing ready committee snapshot writes the same equivalent claims once.
2. No provider call or credit occurs.
3. Every value has field-level evidence/source metadata.
4. One candidate cannot write facts onto another same-name contact.
5. Provider facts and platform role inference remain visibly distinct.

### C2 — Exact contact-subject durability hardening

**Owns**

- runtime row/snapshot models exposing `subject_kind` and `contact_id`;
- exact contact-ready snapshot queries and constraints;
- required indexes and reversible migration, if schema changes are needed;
- merged-contact canonicalization behavior;
- contact-specific request fingerprint and replay tests; and
- provider-neutral wake-dispatch foundation.

**Exit gate**

1. Account and contact snapshots cannot cross-satisfy.
2. Contact A cannot reuse Contact B solely by name or employer.
3. concurrent submit elects one operation;
4. crash/restart performs no duplicate submit or charge;
5. replay from a fresh process performs zero HTTP; and
6. migration smoke has exactly one Alembic head on an isolated database.

### C3 — Contact-targeted Exa Deep contract and compiler

**Owns**

- account/contact subject variant in the existing Exa compiler;
- exact-person/employer target lock;
- registry-shaped JSON schema and directional questions;
- source/evidence requirements;
- bounded `deep-reasoning` request policy; and
- parser fixtures for supported, empty, malformed, contradictory, and same-name results.

**Exit gate**

1. Compiler cannot emit an unregistered field.
2. Effective source plan must admit exact `exa_deep` for every emitted field.
3. Contact identity and employer disambiguators affect the request fingerprint.
4. Malformed or ungrounded output fails closed.
5. No credential or provider call is needed for the slice gate.

### C4 — Durable Exa contact acquisition and snapshot-backed resolver

**Owns**

- submit/acquire through the generic external-research operation;
- immutable contact snapshots and actual Exa settlement;
- ready-snapshot lookup by exact contact;
- snapshot-backed provider-neutral contact resolver;
- materialization through the existing `fill_contact_field`; and
- live one-contact Exa canary after authorization.

**Exit gate**

1. Non-eligible/unselected contacts cause zero Exa calls.
2. One eligible contact intent creates one provider request.
3. External request completes outside the claim transaction.
4. Ready snapshot produces grounded, governed contact claims.
5. same-name/mismatched-employer evidence is dropped or reviewed;
6. actual dollars/usage settle once; and
7. fresh-process replay produces the same claims with zero provider traffic.

### C5 — Selected-contact channel enrichment and independent validation

**Owns**

- exact selected-contact/channel gate;
- email and phone as separate operations and budgets;
- chosen reveal/enrichment provider adapter(s);
- independent corroboration and/or deliverability adapters behind stable seams;
- observed-to-validated-to-identity-promotion transitions;
- channel freshness, objection, erasure, and retention handling; and
- live selected-contact canary after endpoint/entitlement and authorization are proven.

**Exit gate**

1. `contact_reveals_allowed=false` causes zero reveal traffic.
2. Email approval never authorizes phone, and vice versa.
3. Non-selected contacts cause zero reveal traffic.
4. Raw result never writes `verified_email` directly.
5. Failed, conflicting, or weak validation remains unusable and out of identity.
6. Native provider costs settle once per channel.
7. replay performs zero reveal/validation spend; and
8. DSAR/objection removes or suppresses all required channel uses.

### C6 — Provider-neutral preparation, wait/resume, and production composition

**Owns**

- contact preparation protocol/outcomes;
- selection materialization after committee identity;
- `WAITING_EXTERNAL` propagation and wake/resume;
- production adapter registration;
- detached-fleet and independent-contact tool composition;
- budget and cancellation propagation; and
- no-network-under-claim-transaction enforcement.

**Exit gate**

1. Existing `AccountDeepOrchestrator` stage semantics remain provider-neutral.
2. No new fleet, project phase, or provider branch is introduced.
3. Pending contact acquisition returns `WAITING_EXTERNAL` and resumes correctly.
4. Steering/cancellation is durable and does not duplicate spend.
5. Independent contact profiling works when local preconditions pass.
6. Existing account and committee paths regress green.

### C7 — Handoff and content-consumption bridge

**Owns**

- additive research-view/contact-eligibility projection for professional/channel fields;
- `account x contact x persona` claim-ref bundle;
- coverage and exclusion projection;
- safe separation of drafting context from delivery channels; and
- one content-contract consumer fixture.

**Exit gate**

1. Every projected fact resolves to an eligible claim/ref.
2. Personal facets require strong binding and an allowed use decision.
3. Disallowed or unvalidated channels are absent from delivery eligibility.
4. Raw email/phone is absent from generic drafting context.
5. Missing contact evidence produces an explicit fallback/coverage state.
6. No content generator calls a research provider.

### V0 — Offline and database acceptance

Run the combined regression matrix with fake transports only:

- directive and selection lifecycle;
- Sumble professional materialization;
- contact exactness, identity merge, and same-name negatives;
- Exa compiler/parser/materializer;
- reveal and validation state transitions;
- pre-spend/source-plan enforcement;
- crash, concurrency, waiting, resume, cancellation, and replay;
- verification/use/freshness/DSAR;
- handoff/content contract;
- migration smoke, enum parity, mypy, Ruff, and import-linter; and
- existing M8B account/committee regression suites.

V0 proves mechanics, not provider behavior.

### V1 — Bounded live acceptance

After explicit paid-call authorization, run one bounded account/contact canary against the
development database containing Stage 0, Client KB, confirmed ICP, and synthetic account-discovery
data.

V1 must prove:

1. exact database/workspace/project/ICP/discovery-batch preconditions;
2. user-confirmed directive and selected-contact receipt;
3. live Sumble professional snapshot semantics or a documented reuse of the already-live snapshot;
4. live contact-targeted Exa request and structured output;
5. live selected channel enrichment and independent validation if its contract is accepted;
6. immutable requests, responses, snapshots, evidence, and provider identifiers;
7. typed claims, identity binding, use decisions, and promoted research view;
8. native credits/dollars and monetary estimate/receipt reconciliation;
9. detached fleet waiting and resume;
10. content-contract consumption from claim refs; and
11. a fresh-process, zero-provider replay producing equivalent governed output.

Missing credential, catalog probe, mocked transport, exit code 0, or a completed phase with zero
provider traffic is not live acceptance.

## 10. Work sequencing and parallel ownership

```text
C0 contract freeze
    -> C1 Sumble professional materialization -----------+
    -> C2 contact durability -> C3 Exa compiler -> C4 ---+-> C6 composition -> C7 -> V0 -> V1
    -> C5 reveal/validation contract + adapter ----------+
```

- C1 may proceed after C0 because it reuses existing snapshots and should not touch acquisition.
- C2 may proceed in parallel with C1 once shared field/subject shapes are frozen.
- C3 follows C2's exact-contact operation contract; C4 follows C3.
- C5 may proceed separately only after C0 resolves provider/validation semantics.
- C6 is the serial integration point for the existing orchestrator and fleet.
- C7 can start its projection shape after C0/C1 but closes only after C5/C6 semantics are stable.
- V0 precedes all acceptance spend. V1 is a separate authorized live step.

Shared migration, exports, provider registry, and production composition changes should integrate
serially to avoid collision. Each parallel lane owns new isolated modules until its contract tests
pass.

## 11. Explicit non-goals

M8C does not include:

- a second contact fleet or contact-specific orchestrator;
- a Sumble-specific project phase or branches in `AccountDeepOrchestrator`;
- automatic discovery-to-account-deep or committee-to-reveal execution;
- whole-list Sumble people search;
- reveal of every committee candidate;
- sensitive/special-category personal research by default;
- ungoverned scraping or direct LinkedIn automation;
- Sumble Signals, Priority Signals, Intelligence Briefs, or trend-alert productionization;
- a general-purpose Exa Search tool for arbitrary agent browsing;
- global Parallel Task cleanup or replacement;
- frontend implementation;
- full content fleet/content schema/template/publishing implementation; or
- changing the immutable discovery seal or rerunning discovery to profile a known contact.

## 12. Combined release acceptance

M8C is complete only when all of the following are true:

1. Only final selected committee members receive contact operations.
2. A non-selected or ineligible contact causes zero Exa/reveal/validation traffic.
3. Email and phone are independently authorized and budgeted.
4. Sumble professional facts become typed, sourced, identity-bound claims without a new call when a
   fresh snapshot already exists.
5. Exa Deep requests are locked to the exact person and employer.
6. Same-name, wrong-employer, and conflicting-profile fixtures cannot promote personal claims.
7. Every personal claim carries the required identity binding, use class, evidence, freshness, and
   verification state.
8. Raw or failed-validation channel values never become verified identity or delivery-eligible.
9. No provider request or poll runs inside a claim materialization transaction.
10. Crash/restart/concurrent replay creates no duplicate request, charge, snapshot, or equivalent
    claim.
11. Fresh-process replay performs zero provider traffic and reproduces equivalent governed output.
12. Provider native cost units remain separate and settle exactly once.
13. The original account-discovery seal and M8B snapshots/claims remain unchanged.
14. Coverage reports partial, empty, conflicted, excluded, and unsearched states honestly.
15. Handoff exposes only promoted/use-allowed facts and resolves each fact to claim/provenance refs.
16. Content-facing `account x contact x persona` consumption works without invoking a research
    provider or exposing channels to generic drafting context.
17. The existing M8B account profiling, committee, waiting, steering, verification, and replay
    acceptance remains green.
18. A bounded live canary proves actual provider/model traffic, durable receipts, claims, spend,
    downstream output, and zero-spend replay.

## 13. Decisions that must be closed in C0

The following are deliberately not guessed in this roadmap:

1. Does the entitled M8B v9 contract remain the correct contract for each new M8C operation, how
   does it relate to the current public v3 API, and does either entitled surface expose a governed
   channel reveal?
2. Which canonical field represents work email, and what new field—if any—represents direct phone?
3. Which provider performs email/phone acquisition when Sumble does not expose it?
4. What exact combination of corroboration and deliverability is required before an email becomes
   a verified identity key?
5. Does phone ever participate in identity resolution, or remain delivery data only? The default
   recommendation is delivery data only.
6. Which professional profile URLs are approved as strong identity keys in each jurisdiction?
7. Which contact facets are in the first live release, and what per-tier contact/field limits apply?
8. What are the separate Sumble, Exa Search, Websets enrichment, email validation, and phone
   validation budget caps?
9. Does the first release support both email and phone, or email first with phone fail-closed?
10. What content-side consumer fixture is sufficient to close the handoff without implementing the
    later content fleet?

Until these decisions are frozen, the safe executable defaults are: professional contact profiling
may proceed for selected strongly identified contacts; contact reveal remains disabled; phone is
not an identity key; and no undocumented provider endpoint is called.
