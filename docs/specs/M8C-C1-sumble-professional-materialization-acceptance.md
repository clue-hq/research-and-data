# M8C C1 — Sumble snapshot-backed professional materialization acceptance

- **Parent roadmap:** `M8C-contact-deep-research-and-selected-contact-enrichment-roadmap.md`
- **Depends on:** accepted M8C C0 contracts and an existing ready M8B Sumble committee snapshot
- **Branch:** `platform/c8-account-profiling-integration`
- **Accepted:** 2026-08-05
- **Status:** mechanically accepted; no new provider request, credit, reveal, migration, fleet, or
  orchestrator

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
`professional_public`, strongly identity-bound, zero incremental cost, and linked to their exact
workspace-scoped response artifact, operation, snapshot, request fingerprint, source URL/span,
provider product, observation time, and confidence.

## 2. Identity, replay, and transaction behavior

`SumbleCommitteeSource` reads only exact-account ready snapshots and carries field-specific
`CandidateProfessionalFact` records with each candidate. The existing committee worker first
identity-admits the candidate under the known account, then writes professional facts onto the
resulting canonical contact inside the existing short claim transaction. No external request or
poll occurs in that transaction.

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
   traffic on replay; and
9. the complete repository test suite passes against an isolated Postgres database migrated to
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

## 4. Boundary retained

C1 makes no Sumble or Exa provider request, spends no credits, reveals no email or phone, mutates no
identity strong key, and adds no schema migration. Exact contact-subject acquisition durability is
C2; contact-targeted Exa compilation and acquisition are C3/C4; governed channel reveal and
validation remain C5.
