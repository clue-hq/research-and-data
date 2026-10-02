# Person research production port — 2026-09-24

- Founder explicitly authorized moving the side conversation's discovery-first trial into the
  actual platform person Deep Agent. No subagents, paid research launch, worker changes or push.
- Inspected current quality revision 10: person profile v9-person still uses shared prompt v6;
  Exa request still legacy; source navigation account-only. Durable brief, evidence, media,
  specialist, ledger and tracing infrastructure already present. Existing unrelated edits left alone.
- Implementing immutable quality revision 11/person profile v11-person. Account profile stays
  v10; claim/narrative stay v6. Historical resources/runs remain pinned. Legacy v1-v3 and runtime
  default selection unchanged. Port includes explicit charter, ordinary preliminary searches,
  adaptive follow-ups, full text/highlights/links, fresh-field views and actionable media candidates.
- Canonical source records and overviews use existing evidence grants, DB/object storage and
  erasure checks; no trial filesystem or benchmark inputs in production. Provider calls continue
  through ToolRuntime, operation journal, durable drain and shared observability.
- Isolated test database `clue_person_port_20260924` created on local Jerusalem Postgres for
  rollback-based integration checks; no application rows or shared database migrations intended.
- Completed the port and final review. New v4 launches pin recipe 11/person profile v11-person;
  the actual person Deep Agent receives both full skills and the existing durable brief. The
  default remains v2; no environment, worker, deployment or paid-research activation performed.
- Verification: 90 distinct tests passed across focused batches, including seven new request/
  integration cases; one S3 variant skipped because `CLUE_TEST_MINIO_ENDPOINT` is unset. Scoped
  Ruff and mypy passed; all 28 dependency contracts kept. Tests use scripted models/providers,
  so these results do not establish autonomous live research quality.
- Failures resolved during development: three typing issues, a too-literal new instruction-text
  assertion and an old evidence-count assertion. The latter now validates the new complete
  result by locator alongside the original report/text and stable replay, rather than array index.
- Existing unrelated working-tree edits remain untouched. Next acceptance is a fresh v4 person
  run against the retained independent comparison, including source reads and media follow-through.
- Implementation and exact resource pointers:
  `docs/superpowers/plans/2026-09-24-person-research-production-port.md`.
- Removed the task-created test database after verification; existing Postgres/worker processes
  were left running as found.
