# Executor permanent-block resume guard

- Native recipe closure could spin after a permanent tool precondition refusal: `node.blocked`
  initially parks at `awaiting_input`, but a later gate decision resumes the execution. The
  executor previously considered only completed/failed nodes and replayed the immutable refusal.
- Added a small generic guard in `platform/execution/clue_execution/executor.py`: an active drive
  encountering durable blocked nodes emits `execution.failed`, reason `node_blocked`, with their
  node keys. Initial `awaiting_input` behavior and original refusal history remain unchanged.
- Real journal/executor regression first timed out on old code, then passed with the guard. It
  covers a corrected sibling operation, gate closure, terminal replay, no duplicate blocked
  attempt, and no false completion. No live rows, providers, services, or journal rewrites.
- On the existing disposable database, executor + journal checks: 27 passed, one unrelated
  failure in `test_authenticated_authority_is_durable_and_cannot_change_on_replay` on
  `execution_node_authority_membership_actor_fk`. Baseline confirmed by loading HEAD's original
  execute method only in the test process; same failure. No fixture repair.
- A broader execution run started before the parent narrowed verification and was interrupted;
  no full-suite result is claimed. Ruff check/format and diff whitespace checks passed.
- Changes left uncommitted for parent review and controlled runtime recovery.
- Parent independently reran the entire executor test file on the dedicated disposable database:
  all 20 tests passed. Reviewed the fail-closed guard and bounded replay regression. Recovery will
  restart only this checkout's four fleet workers after checking that the completed-turn stall is
  the only active task; the existing durable child request must resume without another prompt.
