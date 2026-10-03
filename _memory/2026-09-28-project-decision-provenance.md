# Project decision provenance repair — 2026-09-28

- Previous goal turn was progress: tracing found source/style, stale preference,
  and qualification failures. Continued with the existing context projection
  repair. User's no-new-generation restriction remains in force.
- read_statements now carries captured-input kind/actor/time/source reference,
  recording actor, and recorded entity alongside existing statement lineage.
  The recording agent is not the source author; preserve both fields separately.
- load_project_decisions/render_decisions_markdown preserve those fields plus
  statement/input IDs, route reference, and correction lineage. Missing metadata
  stays null. Quotes still use the canonical span/hash verifier and DSAR exclusion.
- Project-library digest includes a renderer format version, so new turns refresh
  old materializations; historical per-turn pins retain exact original bytes.
  No schema migration, provider/model change, or frontend contract change.
- RED: three actual DB regressions failed for lost source IDs, lost target/correction
  references, and stale renderer cache identity. GREEN: four selected DB tests;
  eleven pure rendering tests. Broader DB run: 56 passed, one failed in product
  confirmation (Project.updated_at missing). Reproduced that exact failure with
  the three changed production modules loaded from committed baseline sources.
- Initial isolated baseline test stopped at missing workspace table because its
  standalone fixture probes but does not migrate. Runner corrected to migrate
  its disposable DB explicitly; rerun reached the same baseline updated_at error.
- Scoped Ruff and mypy (three source files, silent imported modules) pass; all
  28 import contracts pass; whitespace pass. Root make check first hit sandboxed
  uv cache access; using a temporary cache/no sync reached the existing unrelated
  formatting failure in untracked test_seller_context_db.py. Left it untouched.
- All DBs were unique disposable local databases, removed after tests. Initial
  pytest temp cleanup warned about old read-only garbage; later tests used fresh
  explicit basetemp paths. No live data mutated, no service restart, no paid model
  call, no generation or page edit, no push. Unrelated working-tree edits preserved.
- Remaining: this exposes source/scope for correct reasoning and correction by ID;
  it does not itself fix absent live feedback, enforce delegated attribution,
  normalize typography or qualify the page. Continue canonical correction/handoff,
  typography-role reuse, and acceptance checks against the retained failed case.
  Goal stays active and incomplete. Full evidence and boundary recorded in the
  2026-09-28 native regression audit under subsystems/clue-design/docs/.
