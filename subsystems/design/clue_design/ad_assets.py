"""Brand Ad Assets DAL (spec ``brand-ad-assets-v1-spec.md`` §4, workstream W2).

Three artifact kinds over three tables — harvested creatives, versioned ad-DNA cards, and the
links from a card version to the imagery pre-generated from it.

The house rules this module keeps, the same ones every other ``clue_design`` module keeps:

* **Fail-closed tenancy.** Every function takes ``workspace_id`` and locates rows by it. A
  foreign-workspace id raises the same :class:`DesignNotFoundError` an absent one does.
* **Callers own the transaction** (one logical operation = one transaction, the O5 rule);
  nothing here commits.
* **Timestamps are the database's**, rendered to ISO-8601 by the mappers — with the single
  deliberate exception of ``design_ad_creative.fetched_at``, which is the caller's, because it
  records when the VENDOR served the creative and not when this row was written.

The card is append-only in the strongest sense the database can express: its UPDATE and DELETE
are refused by trigger (migration ``50ce19bf5ef7``), so :func:`create_ad_dna_card_version`
allocates the next version under a lock rather than editing anything. There is no approval
column and no approval read anywhere in this module — harvested creatives, the card and the
pre-generated assets are born active and immediately usable (ruling D5).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, as_datetime, dump_json, iso, load_json
from clue_design.errors import DesignNotFoundError

__all__ = [
    "create_ad_dna_card_version",
    "get_ad_dna_card",
    "latest_ad_dna_card",
    "link_pregenerated_assets",
    "list_ad_creatives",
    "list_pregenerated_assets",
    "record_ad_creatives",
]


# --------------------------------------------------------------------------------------
# Harvested creatives
# --------------------------------------------------------------------------------------

_CREATIVE_COLUMNS = (
    "creative_id, workspace_id, harvest_job_id, provider, ad_id, advertiser_name,"
    " advertiser_page_id, creative_url, view_details_link, headline, commentary, asset_id,"
    " fetched_at, provenance_json"
)
_CREATIVE_VALUES = (
    ":creative_id, :w, :harvest_job_id, :provider, :ad_id, :advertiser_name,"
    " :advertiser_page_id, :creative_url, :view_details_link, :headline, :commentary,"
    " :asset_id, :fetched_at, CAST(:provenance AS jsonb)"
)


def _as_datetime(value: Any) -> datetime:
    """Coerce a caller's fetch time into a real aware ``datetime``.

    The column is ``timestamptz`` and the driver binds parameters by inferred type, so a
    string does NOT survive a SQL-level ``CAST(:param AS timestamptz)`` — asyncpg rejects it
    at encode time, before Postgres ever sees the cast.

    The coercion itself lives in ``_codec`` (clone-fidelity F0.1 added a second caller-owned
    ``timestamptz`` column, ``design_site_snapshot.captured_at``, and two copies of this rule
    would be two chances to disagree about what a naive instant means).
    """
    return as_datetime(value)


def _creative_from_row(row: Any) -> JsonObject:
    return {
        "creative_id": row.creative_id,
        "harvest_job_id": row.harvest_job_id,
        "provider": row.provider,
        "ad_id": row.ad_id,
        "advertiser_name": row.advertiser_name,
        "advertiser_page_id": row.advertiser_page_id,
        "creative_url": row.creative_url,
        "view_details_link": row.view_details_link,
        "headline": row.headline,
        "commentary": row.commentary,
        "asset_id": row.asset_id,
        "fetched_at": iso(row.fetched_at),
        "provenance": load_json(row.provenance_json),
        "created_at": iso(row.created_at),
    }


async def record_ad_creatives(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    creatives: list[JsonObject],
) -> list[str]:
    """Record one harvest's creatives. Returns the creative ids that are now durable.

    An upsert on the composite key, so a re-offered job converges rather than colliding: the
    ids are content-derived from the creative URL, which means the only writer that can have
    filled a slot is an earlier attempt at this same harvest. Re-recording refreshes the
    mutable facts (which job, which asset row, when it was fetched) and leaves the identity
    alone.

    Bulk, and deliberately one statement per creative rather than one gesture in Python: a
    harvest is a dozen rows, and the loop keeps the parameter binding readable while still
    being one transaction.
    """
    written: list[str] = []
    for creative in creatives:
        creative_id = str(creative["creative_id"])
        params = {
            "creative_id": creative_id,
            "w": workspace_id,
            "harvest_job_id": str(creative["harvest_job_id"]),
            "provider": str(creative["provider"]),
            "ad_id": str(creative["ad_id"]),
            "advertiser_name": creative.get("advertiser_name"),
            "advertiser_page_id": creative.get("advertiser_page_id"),
            "creative_url": str(creative["creative_url"]),
            "view_details_link": creative.get("view_details_link"),
            "headline": creative.get("headline"),
            "commentary": creative.get("commentary"),
            "asset_id": str(creative["asset_id"]),
            "fetched_at": _as_datetime(creative["fetched_at"]),
            "provenance": dump_json(creative.get("provenance") or {}),
        }
        await conn.execute(
            text(
                f"""
                INSERT INTO design_ad_creative ({_CREATIVE_COLUMNS})
                VALUES ({_CREATIVE_VALUES})
                ON CONFLICT (creative_id, workspace_id) DO UPDATE SET
                  harvest_job_id = excluded.harvest_job_id,
                  asset_id = excluded.asset_id,
                  advertiser_name = excluded.advertiser_name,
                  advertiser_page_id = excluded.advertiser_page_id,
                  view_details_link = excluded.view_details_link,
                  headline = excluded.headline,
                  commentary = excluded.commentary,
                  fetched_at = excluded.fetched_at,
                  provenance_json = excluded.provenance_json
                """  # noqa: S608 - the column list is a module constant, never caller input
            ),
            params,
        )
        written.append(creative_id)
    return written


async def list_ad_creatives(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    harvest_job_id: str | None = None,
    limit: int = 50,
) -> list[JsonObject]:
    """This workspace's harvested creatives, newest first, optionally one job's."""
    clauses = ["workspace_id = :w"]
    params: dict[str, Any] = {"w": workspace_id, "limit": limit}
    if harvest_job_id is not None:
        clauses.append("harvest_job_id = :job")
        params["job"] = harvest_job_id
    where = " AND ".join(clauses)
    rows = await conn.execute(
        text(
            f"SELECT * FROM design_ad_creative WHERE {where}"  # noqa: S608 - clauses are literals
            " ORDER BY created_at DESC, creative_id LIMIT :limit"
        ),
        params,
    )
    return [_creative_from_row(row) for row in rows]


# --------------------------------------------------------------------------------------
# The ad-DNA card
# --------------------------------------------------------------------------------------


def _card_from_row(row: Any) -> JsonObject:
    return {
        "card_id": row.card_id,
        "version": row.version,
        "brand_kit_id": row.brand_kit_id,
        "brand_kit_version": row.brand_kit_version,
        "harvest_job_id": row.harvest_job_id,
        "model": row.model,
        "card": load_json(row.card_json),
        "source_creative_ids": load_json(row.source_creative_ids),
        "created_at": iso(row.created_at),
    }


async def create_ad_dna_card_version(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    card_id: str,
    brand_kit_id: str,
    brand_kit_version: int,
    card: JsonObject,
    source_creative_ids: list[str],
    harvest_job_id: str | None = None,
    model: str | None = None,
) -> JsonObject:
    """Append the next version of one card lineage and return it.

    The version is allocated INSIDE the write, under a lock, for the same reason
    ``clue_design.brand.publish_next_brand_kit_version`` allocates kit versions that way: two
    concurrent distillations reading ``max(version)`` and both writing ``+1`` collide on the
    primary key, and the loser's model spend is then lost to a constraint violation rather
    than to a decision.

    The lock is an ADVISORY one on the lineage key rather than the brand-kit allocator's
    lowest-row ``FOR UPDATE``, because this table's first version has no row to lock: a card
    lineage is born by this same call, so the anchor-row trick would serialize every version
    except the one race that can actually happen at birth. An advisory key exists whether or
    not any row does, is per-lineage (unrelated cards never wait on each other), and is
    released with the transaction.

    Nothing is ever updated: the trigger on this table refuses UPDATE outright (see the
    migration), which is the property that lets an ad turn cite ``(card_id, version)`` and
    still be reading, months later, exactly what it was conditioned on.
    """
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"design_ad_dna_card:{workspace_id}:{card_id}"},
    )
    # W-B1 re-drive guard (Wave-C fix #2): ONE harvest job publishes ONE card version. A
    # re-driven onboarding job (a reaper re-offering work whose holder it presumed dead, a
    # second embedded worker over the shared queue) converges on the version its first
    # execution already published, instead of minting a twin — the twin is what orphaned all
    # ten of Ramp's pre-generated grounds (linked to v1, lane serves latest = v2, 0 visible).
    # First publish wins, checked INSIDE the lock so two concurrent executions serialize.
    # A deliberate re-run is a NEW onboarding job with a new harvest_job_id and converges on
    # nothing; a publish with no job identity (harvest_job_id None) keeps append semantics.
    if harvest_job_id is not None:
        existing = await ad_dna_card_for_harvest_job(
            conn, workspace_id=workspace_id, harvest_job_id=harvest_job_id
        )
        if existing is not None:
            return existing
    current = (
        await conn.execute(
            text(
                "SELECT COALESCE(max(version), 0) AS latest FROM design_ad_dna_card"
                " WHERE card_id = :c AND workspace_id = :w"
            ),
            {"c": card_id, "w": workspace_id},
        )
    ).scalar_one()
    version = int(current) + 1
    await conn.execute(
        text(
            """
            INSERT INTO design_ad_dna_card (
              card_id, version, workspace_id, brand_kit_id, brand_kit_version,
              harvest_job_id, model, card_json, source_creative_ids
            )
            VALUES (:c, :v, :w, :bk, :bkv, :job, :model,
                    CAST(:card AS jsonb), CAST(:sources AS jsonb))
            """
        ),
        {
            "c": card_id,
            "v": version,
            "w": workspace_id,
            "bk": brand_kit_id,
            "bkv": brand_kit_version,
            "job": harvest_job_id,
            "model": model,
            "card": dump_json(card),
            "sources": dump_json(list(source_creative_ids)),
        },
    )
    return await get_ad_dna_card(conn, workspace_id=workspace_id, card_id=card_id, version=version)


async def ad_dna_card_for_harvest_job(
    conn: AsyncConnection, *, workspace_id: str, harvest_job_id: str
) -> JsonObject | None:
    """The card version one harvest job published, or ``None`` — the W-B1 convergence read.

    Oldest first: should a pre-guard database already hold twins for one job, every consumer
    converges on the FIRST publish — the one pre-generation linked its assets to.
    """
    row = (
        await conn.execute(
            text(
                "SELECT * FROM design_ad_dna_card"
                " WHERE workspace_id = :w AND harvest_job_id = :j"
                " ORDER BY created_at, version LIMIT 1"
            ),
            {"w": workspace_id, "j": harvest_job_id},
        )
    ).first()
    return _card_from_row(row) if row is not None else None


async def get_ad_dna_card(
    conn: AsyncConnection, *, workspace_id: str, card_id: str, version: int
) -> JsonObject:
    """One card version, or the fail-closed refusal."""
    row = (
        await conn.execute(
            text(
                "SELECT * FROM design_ad_dna_card"
                " WHERE card_id = :c AND version = :v AND workspace_id = :w"
            ),
            {"c": card_id, "v": version, "w": workspace_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("ad_dna_card", f"{card_id}@{version}")
    return _card_from_row(row)


async def latest_ad_dna_card(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_kit_id: str | None = None,
    card_id: str | None = None,
) -> JsonObject | None:
    """The newest card version for a lineage or a brand kit; ``None`` when there is none.

    ``None`` rather than a raise, because "this brand has not been harvested yet" is an
    ordinary state of the world for every consumer of this lane, not a caller error.
    """
    clauses = ["workspace_id = :w"]
    params: dict[str, Any] = {"w": workspace_id}
    if card_id is not None:
        clauses.append("card_id = :c")
        params["c"] = card_id
    if brand_kit_id is not None:
        clauses.append("brand_kit_id = :bk")
        params["bk"] = brand_kit_id
    where = " AND ".join(clauses)
    row = (
        await conn.execute(
            text(
                f"SELECT * FROM design_ad_dna_card WHERE {where}"  # noqa: S608 - literals
                " ORDER BY created_at DESC, version DESC LIMIT 1"
            ),
            params,
        )
    ).first()
    return None if row is None else _card_from_row(row)


# --------------------------------------------------------------------------------------
# Pre-generated imagery links
# --------------------------------------------------------------------------------------


async def link_pregenerated_assets(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    card_id: str,
    card_version: int,
    links: list[JsonObject],
) -> list[str]:
    """Attach pre-generated assets to one card version. Returns the linked asset ids.

    Idempotent per ``(card, version, asset)``: re-running a pre-generation step that already
    partly succeeded re-states the same links rather than failing on them, which is what makes
    a resumed job safe. The card version is verified first, so a link can never dangle.
    """
    await get_ad_dna_card(conn, workspace_id=workspace_id, card_id=card_id, version=card_version)
    linked: list[str] = []
    for link in links:
        await conn.execute(
            text(
                """
                INSERT INTO design_ad_pregenerated_asset (
                  card_id, card_version, asset_id, workspace_id, visual_system, prompt,
                  generation_json
                )
                VALUES (:c, :v, :a, :w, :system, :prompt, CAST(:generation AS jsonb))
                ON CONFLICT (card_id, card_version, asset_id, workspace_id) DO UPDATE SET
                  visual_system = excluded.visual_system,
                  prompt = excluded.prompt,
                  generation_json = excluded.generation_json
                """
            ),
            {
                "c": card_id,
                "v": card_version,
                "a": str(link["asset_id"]),
                "w": workspace_id,
                "system": str(link["visual_system"]),
                "prompt": str(link["prompt"]),
                "generation": dump_json(link.get("generation") or {}),
            },
        )
        linked.append(str(link["asset_id"]))
    return linked


async def list_pregenerated_assets(
    conn: AsyncConnection, *, workspace_id: str, card_id: str, card_version: int
) -> list[JsonObject]:
    rows = await conn.execute(
        text(
            "SELECT * FROM design_ad_pregenerated_asset"
            " WHERE card_id = :c AND card_version = :v AND workspace_id = :w"
            " ORDER BY visual_system, asset_id"
        ),
        {"c": card_id, "v": card_version, "w": workspace_id},
    )
    return [
        {
            "asset_id": row.asset_id,
            "visual_system": row.visual_system,
            "prompt": row.prompt,
            "generation": load_json(row.generation_json),
            "created_at": iso(row.created_at),
        }
        for row in rows
    ]


# --------------------------------------------------------------------------------------
# The turn-lane reduction (W4 offer-time freeze)
# --------------------------------------------------------------------------------------
#
# Wave-C fix #1. A design turn's ad-lane references used to be composed at CLAIM time, by
# whichever worker process happened to win the ``design_job`` row — so per-process env
# divergence silently changed what a turn saw (Wave B: flag-off audit APIs drained the shared
# queue and turns lost their references with zero log). The lane is now reduced ONCE, at
# OFFER time, by the process that validates and posts the work, and frozen into the turn
# envelope's ``config["ad_lane"]``; the claiming process consumes the frozen value verbatim.
#
# The reductions live HERE — the shared design substrate both the platform's leg dispatch and
# the design API's own routes import — so the two offerers and the legacy claim-time path can
# never drift on what "the lane" means. `lumen_api.ad_runtime` re-exports the bounds and calls
# these reducers; nothing is written twice.

#: How many creative rows a lane reduction reads. A harvest is tens of rows, not thousands,
#: and the read exists to resolve creative ids to asset ids — a lookup, not a scan.
CREATIVE_SCAN = 200

#: How many pre-generated grounds one turn's opening context names. Pre-generation writes 2
#: per style group and a card carries at most 6 groups, so twelve is the whole of a
#: well-formed lane rather than an arbitrary slice.
PREGENERATED_CONTEXT_MAX = 12

#: ``aspect_ratio`` → the words pre-generation itself used for that shape. Mirrored rather
#: than imported to keep this substrate module free of an ingestion-side import; a ratio with
#: no entry renders as the bare ratio, which is still true.
SHAPE_WORDS = {"16:9": "wide background", "1:1": "square background", "4:5": "portrait background"}


def reduce_creative_assets(creatives: list[JsonObject]) -> dict[str, str]:
    """Creative id → the design asset id holding its bytes, in the rows' given order.

    Rows arrive newest-harvested-first from :func:`list_ad_creatives`, which is also the
    deterministic fallback order the selector uses. A row missing either id contributes
    nothing — there are no bytes to reference.
    """
    return {
        str(row["creative_id"]): str(row["asset_id"])
        for row in creatives
        if row.get("creative_id") and row.get("asset_id")
    }


def reduce_creatives(rows: list[JsonObject]) -> list[JsonObject]:
    """Each harvested creative reduced to what the agent's ad list needs, in the rows' order.

    Spec 2026-10-30 (reference ads §5.5): the agent sees every ad with its headline and post
    copy. A row missing either id contributes nothing — there are no bytes to open.
    """
    return [
        {
            "creative_id": str(row["creative_id"]),
            "asset_id": str(row["asset_id"]),
            "headline": row.get("headline"),
            "commentary": row.get("commentary"),
            "created_at": row.get("created_at"),
        }
        for row in rows
        if row.get("creative_id") and row.get("asset_id")
    ]


def reduce_card_payload(card_row: Any) -> JsonObject | None:
    """The card's PAYLOAD (``card_json`` contents), not the row wrapper, or ``None``."""
    if not isinstance(card_row, dict):
        return None
    card = card_row.get("card")
    return card if isinstance(card, dict) else None


def reduce_pregenerated(
    rows: list[JsonObject] | None, *, limit: int = PREGENERATED_CONTEXT_MAX
) -> list[JsonObject]:
    """Each pre-generated background reduced to the two facts a turn's context needs."""
    listed: list[JsonObject] = []
    for row in rows or ():
        if len(listed) >= limit:
            break
        asset_id = str((row or {}).get("asset_id") or "").strip()
        if not asset_id:
            continue
        generation = row.get("generation")
        ratio = str((generation or {}).get("aspect_ratio") or "").strip()
        listed.append({"asset_id": asset_id, "shape": SHAPE_WORDS.get(ratio, ratio)})
    return listed


async def frozen_ad_lane(conn: AsyncConnection, *, workspace_id: str) -> JsonObject | None:
    """The workspace's ad lane reduced and serialized for an OFFER-time freeze.

    ``None`` when the workspace holds no referencable creatives — an ordinary state, and the
    frozen value the envelope then carries so the claiming process still knows the offer was
    decided. Runs on ONE connection, so unlike the claim-time facade there is no per-piece
    tolerance here: a database that answers the first read answers the rest, and a database
    that answers none of them should fail THIS call — the offerer decides (both call sites
    freeze ``None`` and log rather than failing the turn).
    """
    creatives = await list_ad_creatives(conn, workspace_id=workspace_id, limit=CREATIVE_SCAN)
    creative_assets = reduce_creative_assets(creatives)
    if not creative_assets:
        return None
    card_row = await latest_ad_dna_card(conn, workspace_id=workspace_id)
    pregenerated: list[JsonObject] = []
    if (
        isinstance(card_row, dict)
        and card_row.get("card_id")
        and card_row.get("version") is not None
    ):
        pregenerated = reduce_pregenerated(
            await list_pregenerated_assets(
                conn,
                workspace_id=workspace_id,
                card_id=str(card_row["card_id"]),
                card_version=int(card_row["version"]),
            )
        )
    return {
        "card": reduce_card_payload(card_row),
        "creative_assets": creative_assets,
        "pregenerated": pregenerated,
        "creatives": reduce_creatives(creatives),
    }
