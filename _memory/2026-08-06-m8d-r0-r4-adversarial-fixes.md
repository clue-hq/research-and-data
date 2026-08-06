# M8D R0-R4 adversarial remediation

## Scope closed

Closed every P1/P2 finding from the R0-R4 review without composing R5 behavior:

- R0 source authority is an exact field-to-source relation; manufactured strategies and
  field/source cross-products fail in core, API, and Postgres before dispatch.
- R1 public legacy DEEP construction/registration and old spend tools fail loudly; retained
  provider/durability/claim services remain directly testable and green.
- R2 stores immutable initial state, folds requests/observations/results into current state, rejects
  stale finalization, and makes finalization/job-event history append-only.
- R3 uses globally scoped content-addressed Postgres thread ids and enforces durable consecutive
  zero-yield limits across normal model/tool rounds and resume.
- R4 causation/result projection is provider-neutral, records caused/replay/joined observations,
  supports multi-contact committee results, and remeasures final indexed messages.
- Follow-ups persist the exact parent-result digest plus bounded attributable prior context,
  including discovered-contact identity/association/field context.
- Evidence paging is lossless UTF-8 and refuses a mid-code-point offset.
- Full contact erasure redacts journal payloads and deletes exact LangGraph checkpoint threads.
- Stale legacy tests now assert quarantine while separately exercising retained Exa/Sumble and
  identity-binding infrastructure.

## Persistence

Migration `5764311c620d` follows `f643425d0be4`. It adds field/source authority, prior context,
initial-state authority, provider-neutral operation lineage, result subject projection, immutable
history guards, and one-way journal redaction. Fresh-database base/down/up verification is clean and
there remains exactly one Alembic head.

## Verification

- Focused R0-R4 pure/Postgres/checkpointer matrix: green.
- Wider R1 production-composition suite: green after correcting stale legacy expectations.
- Retained Exa, Sumble, coverage, committee, contact, claim, and resolver matrix: green.
- Fresh isolated migration suite: 3 passed.
- Ruff and format: green on the remediation set.
- Mypy: 549 source files clean.
- Import-linter: 24 contracts kept.
- Repository-wide no-DB run reached 100%. Its model-facing-authority audit incorrectly included
  human-only backend steering operations; the audit now mirrors live composition by inspecting only
  addresses admitted to at least one agent role, while the exhaustive authority-inventory test
  continues to guard every registered address. One cross-subject DSAR test was also missing its
  standard `require_compliance_db` fixture; the gate is restored, so offline runs skip it and live
  database runs still execute the full assertion body.

## Environment note

Use a clean database for destructive migration smoke. The populated R0-R4 acceptance database
correctly refuses an R2 downgrade while durable `entity_research_job` fleet tasks exist.
