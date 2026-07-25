"""The client-knowledge field set + surface-class taxonomy (M5.1).

Reverse-profiling points the subsystem's own machinery *inward* at the client. Like every other
field in the system, the client-knowledge fields are **registered rows in the M1.3 field registry,
never hardcoded** (conventions §2 — open by registration). They sit in the ``client.*`` namespace,
which the registry classifies as a vertical *pack*
(:class:`~clue_core.field.FieldClass.PACK`), so they are loaded as a pack
(``pack="client"``) exactly like an industry pack's field set.

Two pieces live here:

* **the field set** (:data:`CLIENT_KNOWLEDGE_PACK`) — the typed ``client.*`` fields
  reverse-profiling fills (value prop, differentiators, proof points, ideal-customer evidence,
  pricing posture, …),
  plus the internal :data:`CLIENT_KB_VERSION` marker field (the version ledger lives in the claim
  store itself — no new table; see :mod:`clue_research.stage0.client_kb`);
* **the surface-class taxonomy** (:class:`SurfaceClass`, :data:`SURFACE_CLASS_FIELDS`) — Doc B §2's
  four reverse-profiling surfaces (owned surfaces, positioning & proof, third-party footprint,
  reviews-as-signal), mapped to the fields each yields, so the coverage read can report *which
  surface classes were attempted and filled* rather than a flat field list.

The per-field ``tier_plan`` is the *source profile for the client KB* expressed as data: owned
surfaces resolve through the tier-2 official-site scrape — both siblings are named
(``firecrawl_site`` paid, ``scrapling_site`` credit-free; only the backend-selected one has a
bound resolver, the other is walked past at zero spend) — the customers/CRM surface adds tier-1
``crm``; third-party and review surfaces name their tier-3 sources (wired later). TTLs are ~90
days because positioning and pricing drift (substrate §8 freshness).
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import FieldDef, PassKind, ReuseScope
from clue_research.claimstore import SeedField, load_pack

# --- the client-knowledge namespace + field keys ---------------------------
CLIENT_PACK = "client"

CLIENT_VALUE_PROP = "client.value_prop"
CLIENT_PRODUCT = "client.product"
CLIENT_DIFFERENTIATOR = "client.differentiator"
CLIENT_PRICING_POSTURE = "client.pricing_posture"
CLIENT_PROOF_POINT = "client.proof_point"
CLIENT_CUSTOMER = "client.customer"
CLIENT_ICP_EVIDENCE = "client.icp_evidence"
CLIENT_MARKET_REPUTATION = "client.market_reputation"
CLIENT_DELIVERED_VALUE = "client.delivered_value"
# Internal marker field: the Client-KB version ledger, modelled as a claim (no new table). Its
# value carries {version, run_id, ...}; see clue_research.stage0.client_kb.
CLIENT_KB_VERSION = "client.kb_version"

# The substantive client-knowledge fields reverse-profiling fills (excludes the version marker).
# M5.2 ICP synthesis and M12 positioning read these via current_value over the client entity.
CLIENT_KNOWLEDGE_FIELDS: tuple[str, ...] = (
    CLIENT_VALUE_PROP,
    CLIENT_PRODUCT,
    CLIENT_DIFFERENTIATOR,
    CLIENT_PRICING_POSTURE,
    CLIENT_PROOF_POINT,
    CLIENT_CUSTOMER,
    CLIENT_ICP_EVIDENCE,
    CLIENT_MARKET_REPUTATION,
    CLIENT_DELIVERED_VALUE,
)


def _seed(
    field_key: str,
    value_type: str,
    *,
    tier_plan: tuple[str, ...],
    value_schema: dict[str, Any],
    description: str,
    freshness_ttl: timedelta = timedelta(days=90),
) -> SeedField:
    """Build a ``client.*`` SeedField (always ``pack="client"``, scoring pass).

    Every client-knowledge field declares ``reuse_scope=TENANT_PRIVATE`` (ENG-165): a ``<pack>.*``
    field has no safe default, and the claim-write boundary (``check_claim_writable``) is
    fail-closed — an undeclared client field could not be written at all, and client-knowledge is
    tenant-private (substrate §2). The declaration is the authoritative source; the stage0 reuse
    *policy* (:mod:`clue_research.stage0.reuse`) only makes the stamping paths agree with it."""
    return SeedField(
        field_def=FieldDef(
            field_key=field_key,
            value_type=value_type,
            tier_plan=tier_plan,
            freshness_ttl=freshness_ttl,
            pass_kind=PassKind.SCORING,
            reuse_scope=ReuseScope.TENANT_PRIVATE,
        ),
        value_schema=value_schema,
        description=description,
        pack=CLIENT_PACK,
    )


_STR = {"type": "string"}
_OBJ = {"type": "object"}
_OBJ_LIST = {"type": "array", "items": {"type": "object"}}

# The registered client-knowledge field set. Loaded with ``pack="client"`` (the namespace IS the
# pack key, as register_field requires for a non-canonical namespace).
CLIENT_KNOWLEDGE_PACK: tuple[SeedField, ...] = (
    _seed(
        CLIENT_VALUE_PROP,
        "str",
        tier_plan=(
            "firecrawl_site",
            "scrapling_site",
        ),
        value_schema=_STR,
        description="What the client sells and the problem it solves (owned surfaces).",
    ),
    _seed(
        CLIENT_PRODUCT,
        "str",
        tier_plan=(
            "firecrawl_site",
            "scrapling_site",
        ),
        value_schema=_STR,
        description="Product / offering description (product, docs, pricing pages).",
    ),
    _seed(
        CLIENT_DIFFERENTIATOR,
        "str",
        tier_plan=("firecrawl_site", "scrapling_site", "g2"),
        value_schema=_STR,
        description="What differentiates the client (owned positioning + third-party category).",
    ),
    _seed(
        CLIENT_PRICING_POSTURE,
        "str",
        tier_plan=(
            "firecrawl_site",
            "scrapling_site",
        ),
        value_schema=_STR,
        description="Pricing posture / model (pricing page).",
    ),
    _seed(
        CLIENT_PROOF_POINT,
        "str",
        tier_plan=(
            "firecrawl_site",
            "scrapling_site",
        ),
        value_schema=_STR,
        description="Case study / testimonial / logo proof point (positioning & proof).",
    ),
    _seed(
        CLIENT_CUSTOMER,
        "list",
        tier_plan=("crm", "firecrawl_site", "scrapling_site"),
        value_schema=_OBJ_LIST,
        description=(
            "Existing-customer references (name/domain) from a customers page or CRM — a LIST, "
            "since a customers page yields many; these double as seed accounts for M5.4 lookalike "
            "discovery (which reads the list, not a single current_value)."
        ),
        freshness_ttl=timedelta(days=180),
    ),
    _seed(
        CLIENT_ICP_EVIDENCE,
        "object",
        tier_plan=("crm", "firecrawl_site", "scrapling_site"),
        value_schema=_OBJ,
        description="Industries / sizes / geos of existing customers (ICP evidence for M5.2).",
    ),
    _seed(
        CLIENT_MARKET_REPUTATION,
        "str",
        tier_plan=("g2", "capterra"),
        value_schema=_STR,
        description="Third-party category standing / reputation (G2 / Capterra / directories).",
    ),
    _seed(
        CLIENT_DELIVERED_VALUE,
        "str",
        tier_plan=("g2", "trustradius"),
        value_schema=_STR,
        description="What the client's own customers say they bought it for (reviews-as-signal).",
    ),
    # The version marker. tier_plan is empty: it is never resolved through the waterfall — it is
    # written directly by the reverse-profiling orchestration to label each KB version.
    SeedField(
        field_def=FieldDef(
            field_key=CLIENT_KB_VERSION,
            value_type="object",
            tier_plan=(),
            pass_kind=PassKind.SCORING,
            reuse_scope=ReuseScope.TENANT_PRIVATE,
        ),
        value_schema={
            "type": "object",
            "required": ["version", "run_id"],
            "properties": {"version": {"type": "integer"}, "run_id": {"type": "string"}},
        },
        description="Client Knowledge Base version marker {version, run_id, ...} (M5.1 ledger).",
        pack=CLIENT_PACK,
    ),
)


# --- Doc B §2 surface-class taxonomy ---------------------------------------
class SurfaceClass(StrEnum):
    """The four reverse-profiling surface classes (Doc B §2). Reverse-profiling attempts all four;
    the coverage read reports which were attempted and which yielded claims."""

    OWNED = "owned"  # website, product/pricing/docs, careers, blog (tier-2 scrape)
    POSITIONING_PROOF = "positioning_proof"  # case studies, testimonials, customers pages
    THIRD_PARTY = "third_party"  # G2 / Capterra / directories / news / social
    REVIEWS = "reviews"  # reviews-as-signal: what customers say they bought it for


# Which client fields each surface class yields (a field may be filled from more than one surface;
# it is listed under its primary surface for the coverage read).
SURFACE_CLASS_FIELDS: dict[SurfaceClass, tuple[str, ...]] = {
    SurfaceClass.OWNED: (
        CLIENT_VALUE_PROP,
        CLIENT_PRODUCT,
        CLIENT_DIFFERENTIATOR,
        CLIENT_PRICING_POSTURE,
    ),
    SurfaceClass.POSITIONING_PROOF: (
        CLIENT_PROOF_POINT,
        CLIENT_CUSTOMER,
        CLIENT_ICP_EVIDENCE,
    ),
    SurfaceClass.THIRD_PARTY: (CLIENT_MARKET_REPUTATION,),
    SurfaceClass.REVIEWS: (CLIENT_DELIVERED_VALUE,),
}


async def load_client_knowledge_pack(conn: AsyncConnection) -> None:
    """Register the client-knowledge field set (idempotent). Must run before reverse-profiling
    writes any ``client.*`` claim, since ``insert_claim`` validates the field against the
    registry."""
    await load_pack(conn, CLIENT_KNOWLEDGE_PACK)
