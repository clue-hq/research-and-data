"""c8 project card turn ref role

Revision ID: 933c7b604f1c
Revises: 6a7f8eed5b23
Create Date: 2026-08-01 11:22:51.301283+00:00

PC-C8 §10 retires the ``stage_snapshot``/``readiness_snapshot`` pair on ``AgentConstitution`` in
favour of one ``project_card_ref``. ``agent_artifact_ref.ref_role`` is a table CHECK — not a
Postgres enum, and no reader matches on the retired strings (``DbAgentReplayReader`` and the
agent projection both select every role and only order by it) — so the flip is one constraint swap.

The rows already written under the retired roles are **kept**: ``agent_artifact_ref`` carries an
``execution_reject_append_only_mutation`` trigger, so deleting audit rows to satisfy a vocabulary
change is not a move this schema allows. The new constraint is therefore added ``NOT VALID``: every
*new* row is checked against the current vocabulary, while the historical rows stay readable as the
audit they are. That is the honest shape of retiring a value in an append-only table — the
alternative (leaving the retired strings legal) would let a future writer resurrect them.

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
revision: str = "933c7b604f1c"
down_revision: str | None = "6a7f8eed5b23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SHARED_ROLES = (
    "'budget_envelope'",
    "'resource_manifest'",
    "'user_message'",
    "'attachment'",
    "'context_materialization'",
    "'history_body'",
    "'model_input'",
    "'model_output'",
    "'final_message'",
    "'output'",
    "'assumption'",
    "'next_action'",
    "'workspace_output'",
)
_RETIRED_ROLES = ("'stage_snapshot'", "'readiness_snapshot'")
_CARD_ROLE = ("'project_card'",)


def _swap_role_check(allowed: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE agent_artifact_ref DROP CONSTRAINT agent_artifact_ref_role")
    op.execute(
        "ALTER TABLE agent_artifact_ref ADD CONSTRAINT agent_artifact_ref_role "
        f"CHECK (ref_role IN ({', '.join(allowed)})) NOT VALID"
    )


def upgrade() -> None:
    _swap_role_check(_CARD_ROLE + _SHARED_ROLES)


def downgrade() -> None:
    _swap_role_check(_RETIRED_ROLES + _SHARED_ROLES)
