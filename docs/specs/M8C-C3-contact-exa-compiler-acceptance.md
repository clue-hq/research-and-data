# M8C C3 — Contact-targeted Exa Deep compiler acceptance

- **Parent roadmap:** `M8C-contact-deep-research-and-selected-contact-enrichment-roadmap.md`
- **Depends on:** C0 selected-contact authority and C2 exact contact-subject durability
- **Branch:** `platform/c8-account-profiling-integration`
- **Recorded:** 2026-08-05
- **Status:** mechanically accepted; no credential lookup, provider request, operation reservation,
  claim write, channel reveal, or paid spend

C3 adds the exact-contact variant to the existing Exa Search Deep compiler. It freezes how an
already identity-resolved, explicitly selected contact becomes a bounded structured Search request
and how a returned citation is prevented from crossing the same-name/employer boundary. C4 owns
durable dispatch, immutable provider snapshots, settlement, snapshot-backed claim materialization,
and the separately authorized live canary.

## 1. Revalidated provider capability

The official Exa Search reference was revalidated on 2026-08-05. `POST /search` documents
`deep-reasoning`, one to ten `additionalQueries`, structured `outputSchema`, `systemPrompt`,
publication-date bounds, result URLs/text/highlights, field grounding, `requestId`, and
`costDollars`. The public endpoint currently documents a general maximum of 100 results; this
product retains the stricter accepted cap of 50. `costDollars` remains response evidence rather
than a preflight quote or final billing authority.

C3 does not use Search to discover a person. Sumble/identity admission must already have produced
the canonical contact and strong professional-profile key. Search is used only to research the
registered facets approved for that selected contact.

Official reference: <https://exa.ai/docs/reference/search>

## 2. Compiler contract

`clue_research.resolvers.exa.compile_exa_contact_deep_request` is the contact subject variant of
the existing account compiler. It reuses the same field aliases, closed nullable JSON schema,
property/depth budgets, content retrieval budgets, non-streaming response, schema validator, and
grounding parser. The contact variant additionally requires:

- `type="deep-reasoning"`, at most 50 results, and at most ten directional questions;
- one canonical contact id and one canonical employer account id;
- canonical full name and an approved strong professional-profile URL;
- canonical employer name and domain;
- available current title, function, and location as disambiguators;
- preferred primary-source and forbidden-source guidance;
- optional ordered publication-date bounds;
- explicit same-name, profile-mismatch, and employer-drift instructions;
- a source URL and inspectable evidence for every non-null value; and
- no email or phone output or inference.

Only `contact.facet.*` fields can enter the contact output schema. Questions affect query text only.
They cannot add a field, schema member, email, or phone.

## 3. Database-backed authority compiler

`clue_api.exa_contact_compiler.compile_registered_exa_contact_plan` resolves the selected-contact
intent against Postgres before producing any preflight. It fails closed unless all of the following
hold:

1. the selection embeds the independently resolved effective C0 policy;
2. the exact confirmed directive, project, project run, ICP, account, and contact agree;
3. the directive permits contact profiling and exact `exa_deep` use;
4. the canonical contact is unmerged, belongs to the exact account/workspace, and has full name plus
   an approved strong profile URL;
5. the canonical employer is unmerged and has a canonical domain;
6. each emitted field is active in the effective field registry and has an exact value schema;
7. the ICP/profile/manifest intersection compiles an effective field source plan authorizing exact
   `exa_deep`, and the run-specific plan selects it; and
8. every selected directional-question id resolves to the pinned confirmed directive.

The healthcare account-deep source override now includes a deliberate `CONTACT_FACET` slot whose
sole default is `exa_deep`. This closes the source-profile gap without changing the shared
healthcare pack or admitting Parallel Task.

## 4. Fingerprint and replay input

The compiler emits an `ExternalResearchAcquisitionRequest` with `subject_kind=contact` and the
exact account/contact tuple. Its semantic reuse fingerprint includes:

- directive pin, selection id/digest, and complete intent digest;
- canonical contact/employer target lock and disambiguators;
- ICP and exact effective field-source-plan digests;
- provider wire-request digest and compiler contract revision; and
- freshness policy.

The operation fingerprint additionally includes project run, observation window, contact, and
bundle ordinal. Changing the profile URL, employer name/domain, title, function, location,
directional questions, fields, source-plan revision, policy, or wire request changes the
fingerprint. C3 does not reserve or dispatch this request; C4 consumes the preflight.

## 5. Response and same-name defense

The existing schema/grounding parser runs first. Every non-null field must match its exact admitted
schema, have one grounding row, resolve every citation to a retained result, and have a direct
lexically supporting text/highlight span.

`normalize_exa_contact_deep_snapshot` then makes a separate target-binding decision per selected
citation:

- `exact`: the result binds the canonical person and canonical employer;
- `unresolved`: the exact person or employer cannot be proven, including a same-name result for
  another employer;
- `contradictory`: a professional-profile citation points to a different profile URL; or
- `not_evaluated`: the citation already failed field support/confidence or represented a null.

Only `exact` citations become provider-neutral candidates. Unresolved and contradictory citations
remain in the immutable attribution surface for review/audit and emit no candidate. An all-null
structured response is a valid paid hard miss. A malformed, differently shaped, ungrounded, or
uninspectable response fails closed.

The content-addressed fixture manifest is
`tests/fixtures/contact_research/c3_exa_contract_manifest.json`; it pins supported, empty,
malformed, contradictory-profile, and same-name/wrong-employer responses.

## 6. Exit-gate evidence

| C3 gate | Executable evidence |
|---|---|
| compiler cannot emit an unregistered field | real-Postgres test resolves the effective registry and rejects an unregistered `contact.facet.*` key before provider compilation |
| exact `exa_deep` authority for every emitted field | admitted-field/preflight validators require one matching content-addressed field source plan; database test proves the healthcare contact-facet plan |
| contact/employer disambiguators affect fingerprint | parameterized profile URL, employer name/domain, title, function, and location variants produce distinct semantic and operation fingerprints |
| structured, directional, bounded request | tests assert exact field aliases/schema, pinned directive question, `deep-reasoning`, 50/10 caps, date bounds, source guidance, target lock, and channel exclusion |
| malformed or ungrounded output fails closed | malformed fixture raises; unsupported/contradictory/same-name fixtures emit zero candidates while preserving disposition |
| supported and empty semantics | exact person+employer fixture emits one grounded candidate; all-null fixture emits none while retaining reported cost |
| no credential/provider call | the slice exposes no transport/coordinator call; all gates compile from values/Postgres and parse frozen artifacts only |

## 7. C4 handoff

C4 must persist the target lock beside the immutable request, dispatch the existing contact-subject
operation outside claim transactions, parse through the C3 contact entry point, settle native Exa
usage once, expose exact-contact ready snapshots, and materialize only `exact` candidates through
the existing contact field/verification path. It must not downgrade to the account normalizer or
reconstruct target identity from mutable state during replay.

## 8. Verification recorded

Recorded on 2026-08-05:

- 88 focused C0-C3/A0-A1/E0-E2 tests passed against the populated synthetic development
  database with no skips;
- the complete repository suite passed to 100% with exit code 0 against a newly created,
  base-to-head migrated disposable database;
- all changed Python files passed Ruff formatting and lint;
- mypy passed across all 526 source files;
- all 24 import-linter dependency contracts passed; and
- Alembic reported the single head `f9281fac77e1` before and after verification.

An attempted whole-repository run against the populated development database was rejected by the
C5.3 downgrade guard because that database correctly contains pre-materialized tool nodes; later
tests also encountered its intentionally seeded source manifests. The database remained at the
single head. The successful complete run therefore used the required isolated clean database,
which was deleted afterward. No credential was resolved and no Exa or Sumble request, provider
operation, or paid charge occurred in either run.
