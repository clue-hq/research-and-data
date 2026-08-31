"""Concept joins (Part II slice D3) — design rows onto the platform brand + account spines.

Two born-nullable columns created in D1 get stamped here, at write time:

* ``design_brand_kit.brand_id`` → ``brand (brand_id, workspace_id)`` (ruling O2: the design kit
  IS the platform's versioned brand-kit payload, so it must name the brand it belongs to).
* ``design_account.account_entity_id`` → ``account_entity (id, workspace_id)`` (ruling O1: an
  ABM target company in the design plane is the SAME company the research plane researches).

Both stamps are resolve-or-create against the target table, and both FKs are composite
``(id, workspace_id)``, so a cross-workspace stamp is unrepresentable rather than merely
refused — this module never has to check tenancy by hand on the write.

**INTERIM — this module's two CREATE paths are dev scaffolding, deliberately.**
Minting a brand row and minting an ``account_entity`` row are the jobs of the platform's
governed spine and identity-resolution services, neither of which the design API can reach
today (the design substrate imports only core/db/config/obs/storage — Rule S4 — and the design
apps have no composition-root wiring to those services until Part III). Plain SQL against
``brand`` / ``account_entity`` is the sanctioned mechanism for that gap: it is exactly how the
design tables' own FKs already reference those tables. **Part III replaces the CREATE halves
with calls to the governed services at the platform composition root; the RESOLVE halves and
the stamped columns survive that swap unchanged** — nothing downstream reads "who created this
row", only the join.

The creations stay deliberately minimal so the governed services have nothing to un-do: a
brand carries only its workspace and a placeholder name; an account entity is born
``candidate`` with a canonical name and a primary domain and no claims, aliases, or registry
ids — precisely the shape the identity service already expects to enrich.

**Why neither column is NOT NULL yet (ruling R-D3-3 — deferred to Part III, both columns):**

* ``brand_id``: a workspace may own SEVERAL brands, and a brand kit created through the design
  API carries no brand context to disambiguate them. Guessing would silently bind a kit to the
  wrong brand; NULL is the honest answer until Part III's delegation bundle carries explicit
  brand context into the design agent.
* ``account_entity_id``: an account may legitimately have no domain, and a domain is the only
  strong key this seam may match on. Name-only matching is identity resolution's job (with its
  own evidence and merge rules) and must never be faked here — so a domain-less account stays
  unjoined rather than wrongly joined.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

#: The placeholder name a resolve-or-create brand is born with (see the module docstring:
#: Part III's governed spine owns real brand creation and naming).
DEFAULT_BRAND_NAME = "Default Brand"


def _new_brand_id() -> str:
    """Mint a spine-shaped brand id — the same ``brd_<uuid4 hex>`` format ``clue_spine`` mints.

    Duplicated rather than imported on purpose: Rule S4 forbids ``clue_design`` importing
    ``clue_spine``. The format is a two-token convention, not logic, and Part III deletes this
    call site along with the interim creation path.
    """
    return "brd_" + uuid4().hex


def normalize_domain(domain: str | None) -> str | None:
    """A blank/whitespace-only domain is NO domain — never a resolvable key."""
    return (domain or "").strip() or None


async def _workspace_brand_ids(conn: AsyncConnection, *, workspace_id: str) -> list[str]:
    """The workspace's brands, capped at two — one/none/several is all the caller needs."""
    rows = await conn.execute(
        text(
            "SELECT brand_id FROM brand WHERE workspace_id = :w"
            " ORDER BY created_at ASC, brand_id ASC LIMIT 2"
        ),
        {"w": workspace_id},
    )
    return [row.brand_id for row in rows]


async def resolve_brand_id(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str | None = None
) -> str | None:
    """Resolve the brand a kit written into ``workspace_id`` belongs to (ruling R-D3-1).

    * An explicit ``brand_id`` always wins — it is the only caller-supplied brand context that
      exists, and it is validated structurally: a foreign-workspace id fails the composite FK
      ``design_brand_kit_brand_fk`` at INSERT (fail-closed, no extra probe).
    * Exactly ONE brand in the workspace → that brand (the overwhelmingly common shape today).
    * NO brand → create the interim default brand and use it. A second kit in the same
      workspace then finds exactly one brand and reuses it.
    * TWO OR MORE brands → ``None``. Ambiguous, and a wrong bind is worse than none; Part III's
      delegation bundle carries the explicit brand context that resolves it.
    """
    if brand_id is not None:
        return brand_id
    existing = await _workspace_brand_ids(conn, workspace_id=workspace_id)
    if len(existing) == 1:
        return existing[0]
    if existing:
        return None
    await conn.execute(
        text(
            "INSERT INTO brand (brand_id, workspace_id, name) VALUES (:b, :w, :n)"
            " ON CONFLICT DO NOTHING"
        ),
        {"b": _new_brand_id(), "w": workspace_id, "n": DEFAULT_BRAND_NAME},
    )
    # Re-read rather than trust the mint: a concurrent writer may have created a brand too, and
    # two brands is the ambiguous case whichever transaction made them.
    created = await _workspace_brand_ids(conn, workspace_id=workspace_id)
    return created[0] if len(created) == 1 else None


async def resolve_account_entity_id(
    conn: AsyncConnection, *, workspace_id: str, domain: str | None, name: str
) -> str | None:
    """Resolve-or-create the platform account entity a design account projects onto (R-D3-2).

    The domain is the join key and the ONLY key: ``account_entity_primary_domain_ws_key``
    (unique on ``(workspace_id, primary_domain)`` where the domain is non-null) makes it a
    workspace-local strong key. No domain → ``None``; name-only matching belongs to the
    identity service and is never faked here.

    The INSERT rides that same unique index with ``ON CONFLICT … DO NOTHING``, so a concurrent
    creator does not raise — the loser simply re-reads and stamps the winner's entity. Both
    accounts in one workspace sharing a domain therefore converge on ONE entity; the same
    domain in two workspaces yields two distinct entities (accounts are workspace-local — the
    founder ruling behind ``account_entity.workspace_id``).
    """
    key = normalize_domain(domain)
    if key is None:
        return None
    found = (
        await conn.execute(
            text("SELECT id FROM account_entity WHERE workspace_id = :w AND primary_domain = :d"),
            {"w": workspace_id, "d": key},
        )
    ).first()
    if found is not None:
        return str(found.id)
    inserted = (
        await conn.execute(
            text(
                """
                INSERT INTO account_entity (canonical_name, primary_domain, status, workspace_id)
                VALUES (:name, :d, 'candidate', :w)
                ON CONFLICT (workspace_id, primary_domain) WHERE primary_domain IS NOT NULL
                DO NOTHING
                RETURNING id
                """
            ),
            {"name": name, "d": key, "w": workspace_id},
        )
    ).first()
    if inserted is not None:
        return str(inserted.id)
    raced = (
        await conn.execute(
            text("SELECT id FROM account_entity WHERE workspace_id = :w AND primary_domain = :d"),
            {"w": workspace_id, "d": key},
        )
    ).first()
    return None if raced is None else str(raced.id)
