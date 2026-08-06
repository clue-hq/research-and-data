# M8C C1 — Sumble snapshot-backed professional materialization acceptance

- **Parent roadmap:** `M8C-contact-deep-research-and-selected-contact-enrichment-roadmap.md`
- **Depends on:** accepted M8C C0 contracts and an existing ready M8B Sumble committee snapshot
- **Branch:** `platform/c8-account-profiling-integration`
- **Accepted:** 2026-08-05
- **Status:** mechanically accepted after adversarial candidate-selection and lineage remediation;
  no new provider request, credit, reveal, fleet, or orchestrator

C1 turns the already-acquired Sumble People and Teams organization graph into typed professional
claims on the exact identity-admitted committee contact. It remains a snapshot-materialization
slice: Sumble acquisition stays owned by M8B S2, and contact-targeted acquisition starts in later
M8C slices.

## 1. Materialized field contract

C1 registers and writes the six professional-public fields frozen by C0:

| Field | Snapshot basis | Provenance classification |
|---|---|---|
| `contact.current_title` | Sumble People current position | provider returned |
| `contact.job_function` | Sumble People function | provider returned |
| `contact.job_level` | Sumble People seniority/level | provider returned |
| `contact.current_location` | Sumble People location | provider returned |
| `contact.organization_relationship` | exact current Sumble employer id/name/start | provider returned with explicit basis |
| `contact.team_membership` | Sumble Teams membership | provider modeled, never presented as a platform inference or provider-observed fact |

All six fields are contact-scoped, deep-pass, committee-gated, tenant-private, 30-day-freshness
fields with no waterfall tier plan. Materialized claims are API-extracted, tier 1,
`professional-public`, strongly identity-bound, zero incremental cost, and linked to their exact
workspace-scoped response artifact, operation, snapshot, request fingerprint, source URL/span,
provider product, observation time, and confidence. `claim.provenance_kind` is the typed durable
classification: literal attributes are `provider_returned`, team membership is
`provider_modeled`, and committee role/persona judgments are `platform_inferred`. Evidence prose
and `value_json` are no longer the only place this distinction survives.

## 2. Identity, replay, and transaction behavior

`SumbleCommitteeSource` reads only exact-account ready snapshots and carries field-specific
`CandidateProfessionalFact` records with each candidate. The existing committee worker first
identity-admits the candidate under the known account, then writes professional facts onto the
resulting canonical contact inside the existing short claim transaction. No external request or
poll occurs in that transaction.

The combined source no longer concatenates People before Teams and truncates. Candidates returned
by both snapshots are selected first because they have the richest evidence; remaining capacity
alternates Teams-only and People-only identities, beginning with Teams, while retaining provider
order within each class. Thus a full People result page cannot erase every paid Teams-only
organization-map candidate. The exact directive/worker cap still bounds the union.

Migration `26eaa6262063` makes lineage substrate authority. A Sumble professional claim is rejected
unless PostgreSQL can join its exact references to a ready committee operation, succeeded matching
source snapshot, response artifact, project run, workspace, operation account, and admitted contact
under that account. It also enforces tier-1 API extraction, committee mode, strong binding,
professional-public use, tenant-private scope, zero incremental materialization cost, and the
field-appropriate typed provenance. Missing, fabricated, cross-account, cross-contact, or mutated
lineage is unrepresentable even if an application caller bypasses the committee worker.

Replay identity includes canonical contact, field, run, source, and provider product. An equivalent
ready-snapshot replay returns the existing immutable claim reference. If the same replay identity
would change the value or immutable provenance, materialization raises
`ProfessionalFactReplayConflict`; it does not silently overwrite or duplicate the fact. Two people
with the same name but different strong LinkedIn identities resolve to different contacts and
cannot share professional claims.

Committee result references now include the professional claim ids. The existing governed and
legacy-compatible handoff readers admit those eligible professional field keys; no parallel
handoff request or copied dossier is introduced. Sumble professional facts and the platform's
LLM-derived committee role/persona claims retain different extraction methods and source
provenance.

## 3. Exit-gate evidence

The C1 tests prove:

1. an existing ready People/Teams snapshot produces all six grounded professional facts;
2. replay returns the same claim references and performs no additional transport call;
3. field-level artifact, operation, snapshot, request, source, product, and evidence metadata are
   retained;
4. same-name contacts with different strong identities remain isolated;
5. provider-returned, provider-modeled, and platform-inferred facts are visibly distinct;
6. an immutable replay mismatch fails closed;
7. professional claim references appear through the existing committee result and handoff paths;
8. the V0 fresh-process replay expects the six added claims and still performs zero provider
   traffic on replay;
9. a full People page plus a disjoint Teams-only person retains organization-map representation
   inside the same bounded cap;
10. fabricated, missing, semantically mismatched, cross-account/contact, and mutated lineage fails
    at the database boundary; and
11. the complete repository test suite passes against an isolated Postgres database migrated to
    Alembic head.

Verification recorded on 2026-08-05:

- 26 C1-focused database tests passed;
- 82 broader committee, orchestrator, and handoff database tests passed;
- the disposable fresh-process V0 acceptance test passed;
- Ruff passed on the changed C1 Python files;
- mypy passed across `libs`, `subsystems`, and `platform` (525 source files);
- all 24 import-linter contracts passed; and
- the complete live-DB pytest suite reached 100% with exit code 0 after the disposable database was
  migrated to head.

The first monolithic attempt intentionally started with an empty database and exposed an unrelated
DSAR test that opens tables without requesting its migration fixture. The accepted run used the
repository's required live-DB precondition—fresh database followed by `alembic upgrade head`—and
the DSAR test and complete suite passed. No production behavior was changed for that setup issue.

The adversarial-remediation closeout used two additional C1-owned databases so committed registry
seeds from an earlier run could not contaminate the result. Seventeen focused claim/source/
materialization tests and the fresh-process V0 replay passed. The complete 3,398-case repository
collection reached 100% with exit code 0 against a freshly migrated database, with only the
repository's expected skips. A separate empty database passed the full Alembic
head→base→head smoke; `26eaa6262063` remained the sole head. Mypy passed all 525 source files,
all 24 import contracts remained intact, and Ruff format/lint passed on every changed C1 Python
file.

## 4. Boundary retained

C1 makes no Sumble or Exa provider request, spends no credits, reveals no email or phone, and
mutates no identity strong key. Its one additive reversible migration is limited to typed claim
provenance and exact Sumble professional-lineage enforcement. Exact contact-subject acquisition
durability is C2; contact-targeted Exa compilation and acquisition are C3/C4; governed channel
reveal and validation remain C5.
