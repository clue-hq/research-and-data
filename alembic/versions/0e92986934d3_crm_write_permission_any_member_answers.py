"""crm write permission: any workspace member answers

Revision ID: 0e92986934d3
Revises: a3b587b8fdfd
Create Date: 2026-10-21 23:53:46.168261+00:00

R-6.8 (CRM integration rulings): any member of the workspace can answer a CRM write permission
card, not only the person whose turn showed it. The answer validator installed by
``ebf28e41a6a4`` refuses an answer by anybody but the gate's addressee for every kind; this
revision keeps that rule for every other kind and lifts it for ``crm_write_permission`` only.

Unchanged for every kind, this one included: the answering turn must belong to the gate's thread
and must have been submitted by the person recorded as answering it. Membership itself is proved
by the answer route (the principal is a member of the workspace, with ``gate.respond``).

``downgrade()`` reinstalls ``ebf28e41a6a4``'s validator text exactly. Answers already recorded by
a member who was not the addressee stay: the validator checks only new answers.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0e92986934d3"
down_revision: str | None = "a3b587b8fdfd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ADDRESSEE_ONLY = """
            IF NEW.answered_by_user_id <> presented.addressee_user_id THEN
                RAISE EXCEPTION 'only the gate addressee may answer';
            END IF;"""

_ADDRESSEE_UNLESS_CRM_WRITE = """
            IF NEW.answered_by_user_id <> presented.addressee_user_id
               AND presented.kind <> 'crm_write_permission' THEN
                RAISE EXCEPTION 'only the gate addressee may answer';
            END IF;"""


def _foundation() -> ModuleType:
    (path,) = Path(__file__).parent.glob("ebf28e41a6a4_*.py")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def any_member_validator() -> str:
    """``ebf28e41a6a4``'s validator with the addressee rule lifted for CRM write cards."""
    previous: str = _foundation()._answer_validator(crm_write=True)
    if previous.count(_ADDRESSEE_ONLY) != 1:
        raise RuntimeError("the foundation validator's addressee rule was not found exactly once")
    return previous.replace(_ADDRESSEE_ONLY, _ADDRESSEE_UNLESS_CRM_WRITE)


def upgrade() -> None:
    op.execute(any_member_validator())


def downgrade() -> None:
    op.execute(_foundation()._answer_validator(crm_write=True))
