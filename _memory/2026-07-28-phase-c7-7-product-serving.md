# C7.7 — product serving, tools, events, and compatibility

## Outcome

C7.7 is complete on `platform/c7-research-views`. The structured account/contact research view is
now exposed through exact governed tool contracts, the existing projections HTTP application, a
body-free status projection, and the durable run-event/SSE substrate. Retained dossier names are
thin deprecated aliases over the same handlers, receipts, hashes, authorization, replay result,
and source event.

## Implementation

- Central tool registration now includes `compose_dossier@1`, `get_research_view@1`, and
  `recheck_research_view@1`. Compose/re-check are operation-idempotent writes; get is effect-free.
  Outputs contain receipts/refs/hashes only. Exact workspace/project/run/product/subject
  preconditions fail closed, including when the serving collaborators are not configured.
- `research_view_api.py` owns account/contact live reads, saved receipt resolution, compose,
  re-check, evidence actions, and project status. Reads expose stable schema/hash headers,
  deterministic section paging, typed unavailable/redacted state, and cross-scope not-found
  semantics. Mutations require `Idempotency-Key` and call the same `ToolInvoker` path.
- `research_views.py` projects only latest snapshot/hash, stale-section count, coverage
  availability/count, and latest re-check state. It stores/serves no research body.
- Migration `677607ec1cd1` projects every inserted `research_view_event` into `run_event` in the
  same transaction with a database-owned scope/ref/reason payload. `dossier.updated` and
  `dossier.section.stale` are aliases with the same `source_event_id`; no caller-supplied body can
  enter SSE.
- Canonical and legacy `/dossier` routes share one function path. Legacy responses add
  deprecation/successor headers but preserve identical payloads, ETags, ids, authorization, and
  replay.
- New active C6 profile versions may use only `get_research_view@1`; all old profile versions and
  manifest hashes remain immutable for cold resume. Model authority remains absent for
  compose/re-check. The new read tool returns fetch refs and hashes, never values or evidence.
  New Head delegation grants/pins are consistent. The C6.4 historical regression helper is pinned
  to its internally consistent v1 profile family.

## Correctness coverage

- Account and contact canonical/legacy parity, contact-vs-account subject-shape isolation, foreign
  workspace hiding, product/run scope, exact idempotent compose/re-check replay, pagination/hash
  stability, saved receipt resolution, and body-free status.
- Typed evidence unavailability and no permanent/source URL path in snapshots, tool refs, status,
  or event payloads.
- Canonical and legacy event aliases have one source fact; SSE `Last-Event-ID` resumes after the
  supplied sequence and leaks no claim/evidence body.
- C6 receives only a research-view ref. The downstream nine-block fixture retains the same source
  hash and references without copied values/evidence.
- Tool counts, schema hashes, authority audit, active/delegated profile manifests, and the frozen
  C6.4 crash/delegation regression all pass.

## Legacy handoff disposition

The M12 `account_handoff.payload` remains the explicitly bounded legacy output contract documented
in C7.4. C7.7 neither reads nor writes it and introduces no second body store. Changing the M12
serve contract inside this HTTP/tool slice would be a breaking cross-milestone rewrite; C7.8 keeps
the serialized-payload/DSAR sentinel and owns the final closeout disposition. New C7 snapshots,
tools, projections, routes, and events are reference-only.

## Verification

- Focused C7.7/registry/authority integration matrix: 34 passed.
- Clean final full DB-enabled suite: 2,698 passed, 24 skipped (2,722 collected).
- Mypy: 434 source files, no issues.
- Import-linter: 24 contracts kept, 0 broken.
- Ruff format/check: 887 tracked/C7 Python files green; unrelated user-owned untracked
  `.claude/` and `.codex/` content excluded.
- Alembic: one head `677607ec1cd1`; clean isolated head → base → head passed; offline migration SQL
  generation passed.
- `git diff --check`: green.

## Failure notes

- The first clean full suite found the old C6.4 helper mixed Head v1 with newly active v2 child
  profiles. The helper now selects the complete v1 family; its durable delegation/crash behavior
  is unchanged and the exact regression passes.
- The final profile audit caught an initial in-place edit of active profile versions before
  commit. C7.7 now publishes additive v2/v3/v4 profiles and leaves every earlier version
  byte-identical, preserving cold-resume manifests.
- Re-running the entire DB suite on an already-used disposable database reproduced expected
  repository fixture collisions and downgrade guards. Recreating the isolated database produced
  the final clean pass. The database was also recreated before migration smoke.
- User-owned `.claude/`, `.codex/`, and
  `docs/architecture/clue-hq-research-model-surface.md` remain preserved and uncommitted.

## Next handoff

C7.8 runs the complete adversarial/eval/DSAR/serialized-payload/performance gate, reconciles the
remaining legacy compatibility interval, closes C7 documentation/status, and hands the verified
research-view surface to C8.
