"""C7.1 one-way DSAR redaction for faithfulness rationale.

Revision ID: 4dad5551c2f7
Revises: a7eb7cbbcbc2
Create Date: 2026-07-27 16:38:39.187401+00:00

Faithfulness rationales may repeat personal evidence text. The verdict, score, model, prompt,
trace/cost metadata, and claim linkage remain useful non-body audit facts after a data-subject
erasure, but the free-form rationale must not. This migration makes ``rationale`` nullable and adds
bounded one-way redaction metadata. Claim reachability remains the existing indexed
``faithfulness_verdict.claim_id -> claim.entity_id`` path, so no second copy of the text or subject
identity is introduced.

The coherence CHECK permits exactly two states: retained text with no redaction metadata, or NULL
text with both redaction timestamp and reason. ``downgrade`` preserves one-way erasure by replacing
already-redacted NULL bodies with the empty string before restoring the historical NOT NULL shape;
it never reconstructs deleted personal text.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4dad5551c2f7"
down_revision: str | None = "a7eb7cbbcbc2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE faithfulness_verdict "
        "ADD COLUMN rationale_redacted_at timestamptz, "
        "ADD COLUMN rationale_redaction_reason text"
    )
    op.execute("ALTER TABLE faithfulness_verdict ALTER COLUMN rationale DROP NOT NULL")
    op.execute(
        """
        ALTER TABLE faithfulness_verdict
        ADD CONSTRAINT faithfulness_verdict_rationale_redaction_coherent CHECK (
            (
                rationale IS NOT NULL
                AND rationale_redacted_at IS NULL
                AND rationale_redaction_reason IS NULL
            )
            OR
            (
                rationale IS NULL
                AND rationale_redacted_at IS NOT NULL
                AND rationale_redaction_reason IS NOT NULL
                AND length(btrim(rationale_redaction_reason)) > 0
            )
        )
        """
    )
    op.execute(
        "COMMENT ON COLUMN faithfulness_verdict.rationale_redacted_at IS "
        "'C7.1 one-way DSAR redaction time. NULL while rationale text is retained.'"
    )
    op.execute(
        "COMMENT ON COLUMN faithfulness_verdict.rationale_redaction_reason IS "
        "'C7.1 bounded tombstone reason for one-way rationale erasure; "
        "never copied rationale text.'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE faithfulness_verdict "
        "DROP CONSTRAINT IF EXISTS faithfulness_verdict_rationale_redaction_coherent"
    )
    # Schema reversal cannot and must not reconstruct erased personal text.
    op.execute("UPDATE faithfulness_verdict SET rationale = '' WHERE rationale IS NULL")
    op.execute("ALTER TABLE faithfulness_verdict ALTER COLUMN rationale SET NOT NULL")
    op.execute(
        "ALTER TABLE faithfulness_verdict "
        "DROP COLUMN IF EXISTS rationale_redaction_reason, "
        "DROP COLUMN IF EXISTS rationale_redacted_at"
    )
