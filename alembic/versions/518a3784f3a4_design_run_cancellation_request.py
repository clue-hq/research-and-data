"""design run cancellation request

Revision ID: 518a3784f3a4
Revises: 50ce19bf5ef7
Create Date: 2026-08-26 21:34:58.192755+00:00

Wave A / A3 (defect R3-D, `.context/w5-apollo-e2e-report.md` §R3.7): an in-flight design agent
turn had no stop. A doomed manual-reference run — wrong references, minutes of paid model calls
ahead of it — had to be waited out to completion because nothing in the system could ask it to
stop. This column is that ask, made DURABLE.

WHY A COLUMN AND NOT A SIGNAL. The run is driven by a fleet worker in another process (detached)
or another thread (embedded), and the request arrives on a web process that shares nothing with
it but Postgres. An in-memory flag would be invisible across that gap and would evaporate on a
worker restart or a lease takeover — and a takeover re-runs the same frozen envelope, so a
cancellation that did not survive it would silently un-cancel the run. Stamping the row means the
next worker to drive this run reads the same answer the first one did.

SHAPE. Nullable ``timestamptz``, set once and never cleared: a cancellation request is a fact
about a moment, not a mutable mode. NULL means "nobody asked"; a timestamp means "a human asked,
at this instant". The run's own ``status`` is untouched by this column — the request is not the
outcome. What the worker does about it lands in the ordinary terminal write, with the honest
``stop_reason`` inside ``result_json``.

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "518a3784f3a4"
down_revision: str | None = "50ce19bf5ef7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE design_agent_run ADD COLUMN cancel_requested_at timestamptz")
    op.execute(
        "COMMENT ON COLUMN design_agent_run.cancel_requested_at IS "
        "'When a human asked this run to stop (A3 / defect R3-D). NULL = nobody asked. "
        "Write-once: set by POST /agent/runs/{run_id}/cancel while the run is non-terminal, "
        "never cleared. The driving worker reads it at model-call boundaries and takes the "
        "graceful-finalize path; the outcome itself lives in status + result_json.stop_reason.'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE design_agent_run DROP COLUMN cancel_requested_at")
