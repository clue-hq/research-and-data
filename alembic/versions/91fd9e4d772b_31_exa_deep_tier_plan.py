"""Contract §3.1: the Exa-Deep-owned account rows declare exa_deep in their field tier plan.

Revision ID: 91fd9e4d772b
Revises: 99923d6527c3
Create Date: 2026-08-18 18:09:21.709026+00:00

Five §3.1 rows name Exa Deep as an owner while their registered ``field_definition.tier_plan``
never did: ``core.industry``, ``core.company_about``, ``core.annual_revenue``,
``account.total_funding``, ``account.recent_funding``. The composed Exa account action refuses any
field whose effective tier plan does not name its own source key — a *suspending* integrity error,
not a governed refusal — so on a comprehensive 21-field run those rows could be planned, authorized
and requested, and then kill the job instead of resolving. The CORE_PACK seed rows now declare
``exa_deep`` last (tier discipline: the structured tier-1 sources keep their position, synthesis
stays the last resort), and this data migration aligns the durable rows a long-lived database
already carries — ``register_field`` refuses an in-place redefinition, so without it every pack
load on such a database would fail.

``sumble_organizations`` is deliberately **not** added to the two funding rows even though §3.1
also names it: the pinned Sumble v9 organization action cannot request funding attributes at all
(see ``resolvers.sumble.SUMBLE_SUPPORTED_FIELD_KEYS_BY_SOURCE``), and a tier plan is a statement
about what a source can actually answer.

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "91fd9e4d772b"
down_revision: str | None = "99923d6527c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ``field_key`` -> (tier plan before, tier plan after). Exact declarations, not an append rule:
#: a row whose stored plan is neither shape is left untouched (a deliberate local override).
_TIER_PLANS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "core.industry",
        ("sumble_organizations", "apollo", "exa"),
        ("sumble_organizations", "apollo", "exa", "exa_deep"),
    ),
    (
        "core.company_about",
        ("sumble_organizations", "exa_websets"),
        ("sumble_organizations", "exa_websets", "exa_deep"),
    ),
    (
        "core.annual_revenue",
        ("apollo", "sumble_organizations", "exa"),
        ("apollo", "sumble_organizations", "exa", "exa_deep"),
    ),
    (
        "account.total_funding",
        ("apollo", "exa_websets"),
        ("apollo", "exa_websets", "exa_deep"),
    ),
    (
        "account.recent_funding",
        ("apollo", "exa"),
        ("apollo", "exa", "exa_deep"),
    ),
)

_UPDATE = sa.text(
    "UPDATE field_definition SET tier_plan = CAST(:new AS jsonb) "
    "WHERE field_key = :field_key AND tier_plan = CAST(:old AS jsonb)"
)


def _retier(*, forward: bool) -> None:
    connection = op.get_bind()
    for field_key, before, after in _TIER_PLANS:
        old, new = (before, after) if forward else (after, before)
        connection.execute(
            _UPDATE,
            {
                "field_key": field_key,
                "old": json.dumps(list(old)),
                "new": json.dumps(list(new)),
            },
        )


def upgrade() -> None:
    _retier(forward=True)


def downgrade() -> None:
    _retier(forward=False)
