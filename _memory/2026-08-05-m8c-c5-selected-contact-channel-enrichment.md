# M8C C5 selected-contact channel enrichment

## Final state

C5 is mechanically complete on `platform/c8-account-profiling-integration`. It adds a governed,
exact-contact and exact-channel enrichment operation using Exa Websets acquisition behind a
provider-neutral validator seam. It does not auto-reveal committee contacts, create another fleet,
or place provider behavior inside the account orchestrator.

## Decisions and invariants

- The confirmed research directive authorizes contact reveals in general. The immutable
  selected-contact receipt is the narrower authority for the exact contact, channel, acquisition
  source, independent validator, contract pins, and separate budgets.
- Email and phone are separate operations. Email approval cannot authorize phone, and a selected
  contact cannot authorize another contact.
- Raw provider output becomes a tenant-private, weak-bound observed claim. It can never directly
  write `contact_entity.verified_email`.
- Promotion requires the use gate plus independently sourced, reachable, strong, exact-person and
  exact-employer validation. Only email may become an identity key; phone remains delivery data.
- Acquisition settlement and validation settlement are each atomic with their claims, artifacts,
  lawful-basis linkage, provider units/cost, and project-run debit.
- A validator crash after dispatch is spend-unknown and quarantined rather than retried as if free.
- Reuse is content-addressed, exact-subject, freshness- and retention-bounded, and writes a receipt
  with zero provider traffic and zero spend.
- Objection, erasure, and retention suppress use, tombstone channel claims, clear promoted email
  where required, and make every subject-bound request/CSV/provider/validation/receipt artifact
  physically purgeable.
- Declared-private field scope is now threaded through the waterfall reuse classifier. This closes
  the prior risk that `core.work_email` or `core.direct_phone` could be restamped public from a
  source default.

## Main implementation

- `libs/clue-core/clue_core/contact_channel.py` freezes request, state, spend, validator, and result
  contracts; `contact_research.py` carries the exact source plan and separate caps.
- `fd8d61eb482f_m8c_c5_contact_channel_enrichment.py` adds the operation, artifact, reuse, and
  suppression ledgers plus database checks/triggers for exact subject and observed-claim lineage.
- `durable/contact_channel.py` owns reservation, leases, settlement, reuse, and usability.
- `platform/api/clue_api/contact_channel_enrichment.py` composes preflight, Exa person import and
  one-channel enrichment, durable polling, use gating, independent validation, and identity
  promotion without holding a database transaction across network traffic.
- `compliance/dsar.py` and identity helpers implement channel-specific suppression, erasure,
  retention, artifact purge, and locked idempotent verified-email promotion.
- `M8C-C5-selected-contact-channel-enrichment-acceptance.md` is the binding C5 acceptance record.

## Verification

- Clean PostgreSQL affected suite: 174 passed.
- C5 acceptance module: 7 passed.
- Migration smoke on a separate clean database: head -> base -> head passed; single head
  `fd8d61eb482f`.
- Production-path mypy passed.
- Scoped Ruff passed; the only repository-wide formatting findings were two unrelated pre-existing
  files, and repository-wide Ruff also traversed unrelated untracked local skill directories.
- All 24 import-boundary contracts passed.
- A broader non-destructive repository run retained 24 pre-existing order/isolation failures caused
  by suites sharing committed global seed rows. The clean affected suite passed after these C5
  changes.

No paid Exa or validator call was made. Per the roadmap, the live one-contact canary requires
separate spend authorization plus C6 production validator registration and wait/resume
composition. Public documentation and deterministic provider doubles prove the wire/mechanical
contract, not entitlement, billing, or live endpoint acceptance.

## Next handoff

C6 owns the provider-neutral preparation outcome, `WAITING_EXTERNAL` propagation, wake/resume,
production adapter registration, detached-fleet and independent-contact tool composition, and the
separately authorized live canary.
