"""The ICP-synthesis feedback field set (M5.2).

ICP synthesis (M5.2) confirms a client-edited proposal into a versioned ``ICPSpec`` (owned by M3.1)
and must persist the **suggested-vs-confirmed diff** as labeled feedback — the corrections-as-
training-data discipline (substrate §9/§10): when a client removes a proposed signal or drops a
dimension, that correction is a signal the scoring/extraction loop (M13) learns from.

Beat-0 gives M5 **no new tables**, so the diff lives **claim-native** — exactly like the
``client.kb_version`` ledger in M5.1. One registered field, :data:`ICP_CONFIRM_DIFF`, holds the diff
as a typed claim on the client's ``account_entity``; its value carries
``{icp_key, icp_version, diff, ...}`` and every confirm appends a new (immutable) claim, so the
confirm history of an ICP is queryable and append-only with the rest of the store.

The field sits in the ``icp.*`` namespace, which the registry classifies as a vertical *pack*
(:class:`~clue_core.field.FieldClass.PACK`); a ``<pack>.*`` field has no safe default
reuse-scope (ENG-165 fail-closed), so it **declares** ``reuse_scope=TENANT_PRIVATE`` — an ICP is
client-tuned and never amortizes across tenants (the stamping side is
:data:`~clue_research.stage0.reuse.ICP_REUSE_POLICY`).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import FieldDef, PassKind, ReuseScope
from clue_research.claimstore import SeedField, load_pack

# --- the icp-synthesis feedback namespace ----------------------------------
ICP_PACK = "icp"

# The suggested-vs-confirmed diff marker (M5.2). Written directly by ``confirm_icp`` (never resolved
# through the waterfall) so its ``tier_plan`` is empty. Its value carries
# ``{icp_key, icp_version, diff}``; one immutable claim per confirm (append-only confirm history).
ICP_CONFIRM_DIFF = "icp.confirm_diff"

ICP_FEEDBACK_PACK: tuple[SeedField, ...] = (
    SeedField(
        field_def=FieldDef(
            field_key=ICP_CONFIRM_DIFF,
            value_type="object",
            tier_plan=(),
            pass_kind=PassKind.SCORING,
            reuse_scope=ReuseScope.TENANT_PRIVATE,
        ),
        value_schema={
            "type": "object",
            "required": ["icp_key", "icp_version"],
            "properties": {
                "icp_key": {"type": "string"},
                "icp_version": {"type": "integer"},
            },
        },
        description=(
            "ICP confirm diff {icp_key, icp_version, diff} — the suggested-vs-confirmed correction "
            "persisted claim-native as labeled feedback (M5.2; substrate §9/§10)."
        ),
        pack=ICP_PACK,
    ),
)


async def load_icp_feedback_pack(conn: AsyncConnection) -> None:
    """Register the ICP-synthesis feedback field set (idempotent). Must run before
    :func:`~clue_research.stage0.icp_confirm.confirm_icp` writes any ``icp.*`` claim, since
    ``insert_claim`` validates the field against the registry."""
    await load_pack(conn, ICP_FEEDBACK_PACK)
