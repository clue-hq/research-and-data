"""m9_3 faithfulness_verdict answering_model

Revision ID: 11299b862da3
Revises: a3f352f32954
Create Date: 2026-06-24 16:53:54.980442+00:00

[M9.3×M12] The faithfulness judge stamps the **requested** ``judge_model`` on the verdict row — and
keeps it as the ``(claim_id, judge_model, prompt_version)`` cache key, stable across an OpenRouter
fallback. But when ``GatewayConfig.fallback_model`` is set and the primary errors, the model that
*actually answered* (``core.gateway.Completion.model``) differs, and M12's provenance index ("judged
faithful by ``<model>@<prompt_version>``") would then name a model that did not produce the verdict.

This adds an ``answering_model`` column recorded from ``completion.model`` (the id that answered),
leaving ``judge_model`` (the requested id) as the cache key. M12.2 cites ``answering_model``.

The column is **nullable** (existing rows predate it; new judgments always supply it) and
**backfilled** to ``judge_model`` for historical rows — before any fallback existed, the answering
model *was* the requested one, so this is correct, not a placeholder. ``downgrade()`` cleanly drops
it (CI runs up → down → up). No enum, no trigger, no ``claim`` ALTER.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "11299b862da3"
down_revision: str | None = "a3f352f32954"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE faithfulness_verdict ADD COLUMN answering_model text")
    op.execute(
        "COMMENT ON COLUMN faithfulness_verdict.answering_model IS "
        "'M9.3: the gateway model id that ACTUALLY answered (core.gateway.Completion.model) — "
        "differs from judge_model (the REQUESTED id, the cache key) only on an OpenRouter "
        "fallback. Cited by M12.2 provenance (judged faithful by <answering_model>@<version>). "
        "Nullable: historical rows predate it and are backfilled to judge_model.'"
    )
    # Backfill: pre-fallback rows had answering == requested.
    op.execute(
        "UPDATE faithfulness_verdict SET answering_model = judge_model "
        "WHERE answering_model IS NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE faithfulness_verdict DROP COLUMN IF EXISTS answering_model")
