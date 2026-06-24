"""The ``account.value_narrative`` field-class — Output 4's atomic unit (M12.1).

The value narrative is *not* a free-text dossier: each per-``(account, persona)`` argument is
itself a **claim-with-provenance** (substrate §0/§8), so it is verified by the same machinery as
every other claim. This module registers the single field the positioning step writes —
``account.value_narrative`` — as a ``field_definition`` row (open-by-registration, conventions
§2), separate from ``CORE_PACK``.

Three things make this field-def deliberate:

* **``reuse_scope=TENANT_PRIVATE`` is declared, not inherited.** ``account.value_narrative`` is a
  ``FieldClass.ACCOUNT`` field, whose class default is ``PUBLIC_FOOTPRINT`` (firmographic facts
  amortize across clients) — but a value narrative is *client-tuned synthesis over the client's
  own Knowledge Base*, so it must never leak cross-tenant (substrate §2; the M2×M6/M8 reuse-scope
  hazard). We declare the scope on the ``FieldDef`` (M2.5/ENG-165 W1 — declaration is
  authoritative over the prefix heuristic) and the positioner stamps every written claim via
  :data:`clue_research.narrative.reuse.NARRATIVE_REUSE_POLICY`. Belt and braces: the claim-write
  boundary (``check_claim_writable``) refuses a public claim to this private field.
* **No ``tier_plan``.** Like the committee fields, the narrative is produced by a dedicated graph
  node (the M12.1 positioner), not the M4 waterfall, so the source layer never tries to "resolve"
  it.
* **It is tier-4, judge-gated.** Every narrative claim is ``llm_synthesis`` / tier-4 with a
  mandatory ``evidence_span``, promoted only by the M9.3 faithfulness judge
  (``gate="faithfulness"``; corroboration does not apply to a unique synthesis, so
  ``single_source_sufficient=True``).

Wire :func:`load_narrative_pack` at the ``api`` composition root (it is appended to
``RESEARCH_PACK_LOADERS`` by ``api.narrative_wiring``); until then the M12 tests load it per-txn.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import SeedField, load_pack
from clue_research.core import FieldDef, PassKind, Persona, ReuseScope

# --- field key (conventions §3: account.* namespace, the value-narrative output) -------------
VALUE_NARRATIVE = "account.value_narrative"

# The closed persona domain carried inside ``value_json`` ((account, persona) keying — conventions
# §3).
_PERSONA_VALUES: list[str] = [p.value for p in Persona]

# A ``value_json`` is the per-(account, persona) argument plus the keys that scope/label it:
# - ``persona``: which committee lens this argument is shaped for (the (account, persona) key);
# - ``argument``: the grounded "why our client matters / which angle" — the substance the judge
#   scores;
# - ``angle_label``: a short human-legible tag for the angle (e.g. "roi", "architecture-fit");
# - ``icp_spec_version``: the ICP a narrative is scoped to (D5 multi-ICP — an account under two ICPs
#   gets a narrative per ICP; carried here because the claim row has no icp column, and it is what
#   re-synthesis supersession keys on alongside (account, persona)). ``additionalProperties`` is
#   left open so the shape can grow additively without a migration.
_VALUE_NARRATIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["persona", "argument", "icp_spec_version"],
    "properties": {
        "persona": {"type": "string", "enum": _PERSONA_VALUES},
        "argument": {"type": "string"},
        "angle_label": {"type": "string"},
        "icp_spec_version": {"type": "integer"},
    },
}

NARRATIVE_PACK: tuple[SeedField, ...] = (
    SeedField(
        field_def=FieldDef(
            field_key=VALUE_NARRATIVE,
            value_type="object",
            tier_plan=(),  # produced by the M12.1 positioner, not the M4 waterfall
            pass_kind=PassKind.DEEP,
            freshness_ttl=timedelta(days=90),
            gate="faithfulness",  # promoted by the M9.3 judge, not corroboration
            # Declared TENANT_PRIVATE: a client-tuned narrative must never amortize cross-tenant
            # (FieldClass.ACCOUNT default is PUBLIC_FOOTPRINT — the leak hazard this closes).
            reuse_scope=ReuseScope.TENANT_PRIVATE,
        ),
        value_schema=_VALUE_NARRATIVE_SCHEMA,
        # A unique synthesis cannot be corroborated by independent sources — the faithfulness
        # judge is its accuracy gate (M9.3), so a single grounded synthesis is sufficient.
        single_source_sufficient=True,
        corroboration_min=1,
        description=(
            "Per-(account, persona) value narrative — Output 4 (overview §1/§3; substrate §8). "
            "A tier-4 llm_synthesis claim-with-provenance; TENANT_PRIVATE (client-tuned)."
        ),
    ),
)

# The field keys this pack registers (for consumers/tests that need the set without re-deriving it).
NARRATIVE_FIELD_KEYS: tuple[str, ...] = tuple(s.field_def.field_key for s in NARRATIVE_PACK)


async def load_narrative_pack(conn: AsyncConnection) -> None:
    """Register the ``account.value_narrative`` field (idempotent; re-loading is a no-op).

    Additive and namespaced — never collides with ``CORE_PACK`` / ``DEEP_PROFILING_PACK`` / the
    committee or icp packs. Wire at the ``api`` composition root via
    :func:`clue_research.api.narrative_wiring.register_narrative_wiring` (appended to
    ``RESEARCH_PACK_LOADERS``); until then the M12 tests load it per-transaction.
    """
    await load_pack(conn, NARRATIVE_PACK)
