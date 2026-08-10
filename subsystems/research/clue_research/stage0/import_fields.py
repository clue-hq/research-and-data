"""The field set the import entry scenario writes (M5.3).

Beat-0 gives M5 **no new tables**, so everything import persists is **claim-native** (like M5.1's
``client.kb_version`` ledger and M5.2's ``icp.confirm_diff``):

- :data:`IMPORT_BATCH` (``import.batch``) — a grouping marker on the client's ``account_entity``
  recording one import run (batch id, ICP ref, the resolved/needs-review/unresolved counts). A
  ``<pack>.*`` field has no safe default reuse-scope (ENG-165 fail-closed), so it **declares**
  ``reuse_scope=TENANT_PRIVATE`` — a client's import is tenant-private and never amortizes across
  tenants (the stamping side is :data:`~clue_research.stage0.reuse.IMPORT_REUSE_POLICY`).
- :data:`CONTACT_IMPORT_RECORD` (``contact.import_record``) — a **canonical** ``contact.*`` field
  carrying one imported contact's datum + governance tags. Because ``contact`` is a canonical
  namespace (not a vertical pack) it is registered *without* a ``pack`` (registry rule), and it is
  written via :func:`~clue_core.contact_claim`, which stamps the required
  ``identity_binding`` + ``use_class`` (Doc D §2). Its lawful basis rides in the claim value
  (forward-compatible with M10.5's planned ``claim`` provenance column) so M10 can govern it without
  M5.3 importing ``compliance``.

The per-row **resolution provenance** is written as a discovery-provenance-flavored claim on the
resolved account under the unregistered field key :data:`DISCOVERY_PROVENANCE` — ``insert_claim``
skips the field-registry check for ``ClaimFlavor.DISCOVERY`` claims (they carry admission evidence,
not a typed field value), so it needs no registration. ``matched_channel='import'`` is what keeps an
imported account distinguishable from a discovered one while otherwise shape-identical.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import FieldDef, PassKind, ResearchScope, ReuseScope
from clue_research.claimstore import SeedField, load_pack, register_field

# --- the import grouping marker (vertical pack) ----------------------------
IMPORT_PACK = "import"

# The import-batch grouping marker (M5.3). Written directly on the client entity (never resolved
# through the waterfall) so its ``tier_plan`` is empty. One immutable claim per import run.
IMPORT_BATCH = "import.batch"

IMPORT_BATCH_PACK: tuple[SeedField, ...] = (
    SeedField(
        field_def=FieldDef(
            field_key=IMPORT_BATCH,
            value_type="object",
            tier_plan=(),
            pass_kind=PassKind.SCORING,
            reuse_scope=ReuseScope.TENANT_PRIVATE,
            # A bookkeeping marker for one client import run — not researched per project (FI-2 P3).
            research_scope=ResearchScope.PROJECT_NEUTRAL,
        ),
        value_schema={
            "type": "object",
            "required": ["import_batch_id"],
            "properties": {
                "import_batch_id": {"type": "string"},
                "icp_key": {"type": "string"},
                "icp_version": {"type": "integer"},
            },
        },
        description=(
            "Import-batch grouping marker {import_batch_id, icp_key, icp_version, counts} — one "
            "client import run, persisted claim-native on the client entity (M5.3)."
        ),
        pack=IMPORT_PACK,
    ),
)

# --- the imported-contact governance record (canonical contact field) ------
# A plain ``contact.*`` fact (not a ``contact.facet.*`` personal hook) carrying one imported
# contact's datum + the Doc D §2/§4 governance envelope. Canonical namespace → registered WITHOUT a
# pack. TENANT_PRIVATE: a client's imported contact list is private (the ``contact.`` prefix is
# already in M2's default tenant-private set, so the stamp agrees with this declaration).
CONTACT_IMPORT_RECORD = "contact.import_record"

_CONTACT_IMPORT_FIELD = FieldDef(
    field_key=CONTACT_IMPORT_RECORD,
    value_type="object",
    tier_plan=(),
    pass_kind=PassKind.SCORING,
    reuse_scope=ReuseScope.TENANT_PRIVATE,
)
_CONTACT_IMPORT_SCHEMA = {
    "type": "object",
    "required": ["account_entity_id", "lawful_basis"],
    "properties": {
        "account_entity_id": {"type": "string"},
        "title": {"type": "string"},
        "email": {"type": "string"},
        "linkedin_url": {"type": "string"},
        "lawful_basis": {"type": "string"},
        "lia_ref": {"type": "string"},
        "jurisdiction": {"type": "string"},
        "import_batch_id": {"type": "string"},
        "row_index": {"type": "integer"},
    },
}

# --- the discovery-provenance field (unregistered — see module docstring) ---
DISCOVERY_PROVENANCE = "discovery.provenance"


async def load_import_pack(conn: AsyncConnection) -> None:
    """Register the import field set (idempotent). Must run before
    :func:`~clue_research.stage0.import_accounts.import_accounts` writes any ``import.*`` /
    ``contact.import_record`` claim, since ``insert_claim`` validates the field against the
    registry. The ``import.batch`` marker loads as a vertical pack; the canonical
    ``contact.import_record`` field registers directly (a canonical namespace declares no pack)."""
    await load_pack(conn, IMPORT_BATCH_PACK)
    await register_field(
        conn,
        _CONTACT_IMPORT_FIELD,
        value_schema=_CONTACT_IMPORT_SCHEMA,
        description=(
            "Imported-contact governance record {account_entity_id, title/email, lawful_basis, "
            "use_class via the claim} — Doc D §2/§4; tagged at write, governed by M10 (M5.3)."
        ),
    )
