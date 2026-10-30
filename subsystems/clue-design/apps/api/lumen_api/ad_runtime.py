"""W4 — the Brand Ad Assets lane at TURN time (spec ``brand-ad-assets-v1-spec.md`` §4, §5 W4).

W2 populates the lane at onboarding: harvested creatives with durable bytes, one immutable
prose ad-DNA card per harvest, and pre-generated imagery. This module is the other end — what a
scene design turn takes out of that lane:

1. **The ads.** Every harvested creative with its headline and post copy, so the agent's ad
   list (spec 2026-10-30, reference ads §5.5) can name them all. Nothing is auto-attached any
   more (§5.4): the agent opens the ads it wants; only the person's own attachments are
   references.
2. **The description.** The card's prose rides the turn's opening context as advisory text,
   next to the brand card. It is context, never a gate and never a required structure — ruling
   D5 stands: no approval gates and no mechanical guards on the agent.
3. **The pre-generated backgrounds** (W5/R2-D). The imagery pre-generation made for the active
   card is NAMED in that same advisory block — id and shape — so the agent knows it exists.

**Everything here is off unless ``LUMEN_BRAND_AD_ASSETS`` is on.** :func:`read_ad_lane` returns
``None`` on a flag-off process before it touches a database, so a flag-off turn issues no query,
makes no model call, and composes byte-identically to a pre-W4 one.

**Nothing here reaches the composition corpus.** That corpus is dormant by ruling: W4 does not
load it, does not cite it and does not point the agent at it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from clue_design.ad_assets import (
    CREATIVE_SCAN,
    PREGENERATED_CONTEXT_MAX,
    reduce_card_payload,
    reduce_creative_assets,
    reduce_creatives,
    reduce_pregenerated,
)
from py_lumen_config import settings
from py_lumen_obs import get_logger

JsonObject = dict[str, Any]

logger = get_logger("lumen_api.ad_runtime")

__all__ = [
    "CREATIVE_SCAN",
    "FROZEN_LANE_ABSENT",
    "PREGENERATED_CONTEXT_MAX",
    "AdLane",
    "context_brand_ads",
    "context_card",
    "context_pregenerated",
    "frozen_lane_payload",
    "lane_from_frozen",
    "lane_to_frozen",
    "read_ad_lane",
    "resolve_turn_ad_lane",
]

# ``CREATIVE_SCAN`` and ``PREGENERATED_CONTEXT_MAX`` now live in
# ``clue_design.ad_assets`` (the W4 offer-time-freeze home) and are re-exported
# above so every existing importer keeps working; the reductions they bound are
# the shared ones both offerers and this module call.

@dataclass(frozen=True)
class AdLane:
    """What this workspace's ad-assets lane holds right now.

    ``card`` is the card's PAYLOAD (the ``card_json`` column's contents — ``prose``, plus an
    always-empty ``style_groups`` since 2026-10-30), not the row wrapper. ``creative_assets``
    maps creative id → the design asset id holding its bytes, newest harvested first.

    ``pregenerated`` holds the backgrounds pre-generation made for the ACTIVE card, each reduced
    to its id and shape. ``creatives`` holds every creative with its headline, post copy and
    harvest time, for the agent's ad list (spec 2026-10-30, reference ads §5.5).
    """

    card: Optional[JsonObject]
    creative_assets: dict[str, str]
    pregenerated: tuple[JsonObject, ...] = ()
    creatives: tuple[JsonObject, ...] = ()

    @property
    def has_creatives(self) -> bool:
        return bool(self.creative_assets)


def read_ad_lane(workspace_id: str, *, store: Any = None) -> Optional[AdLane]:
    """This workspace's lane, or ``None`` when there is nothing to take from it.

    ``None`` and not an empty lane, for the same reason ``resolve_scene_turn_asset_library``
    returns ``None`` on an empty library: the caller's whole job is "leave the turn alone
    unless there is something real here", and an empty object would make every caller
    re-derive that check.

    Tolerant by construction. A workspace that never onboarded ads, an unreachable database,
    a lane whose rows are half-written — all of them are "no lane", never a failed turn. The
    turn simply designs without the brand's ads, which is the pre-W4 behaviour.
    """
    if not settings.lumen_brand_ad_assets:
        return None
    try:
        if store is None:
            from lumen_ingestion.ad_library.store import AdAssetsStore

            store = AdAssetsStore(workspace_id=workspace_id)
        creatives = store.list_creatives(limit=CREATIVE_SCAN)
    except Exception:  # noqa: BLE001 - the lane is advisory; it may never fail a turn
        logger.warning("ad_lane_unreadable", workspace_id=workspace_id)
        return None
    creative_assets = reduce_creative_assets(creatives)
    if not creative_assets:
        return None
    try:
        row = store.latest_card()
    except Exception:  # noqa: BLE001 - a card read failure still leaves usable creatives
        logger.warning("ad_dna_card_unreadable", workspace_id=workspace_id)
        row = None
    return AdLane(
        card=reduce_card_payload(row),
        creative_assets=creative_assets,
        pregenerated=_read_pregenerated(store, row, workspace_id=workspace_id),
        creatives=tuple(reduce_creatives(creatives)),
    )


def _read_pregenerated(
    store: Any, card_row: Any, *, workspace_id: str
) -> tuple[JsonObject, ...]:
    """The grounds pre-generation made for THIS card version, reduced to two facts each.

    W5/R2-D. Pre-generation writes these rows at onboarding and links them to the card version
    they were anchored on, and until now nothing at turn time ever read them: the whole of the
    W5 Ramp turn contains no reference to any ``asset_gen_*`` id, so ~23 minutes of paid image
    work was invisible to the agent that could have placed it.

    Pinned to the ACTIVE card version, not to the lineage. A ground was generated from one
    card's prose, so a later harvest that re-described the brand supersedes it — offering the
    old version's imagery alongside the new description would be advertising an answer to a
    question the brand no longer asks.

    Tolerant like every other read here: a lane whose card row is half-written, or a database
    that will not answer, yields no listing and never a failed turn.
    """
    if not isinstance(card_row, dict):
        return ()
    card_id = card_row.get("card_id")
    version = card_row.get("version")
    if not card_id or version is None:
        return ()
    try:
        rows = store.list_pregenerated(card_id=str(card_id), card_version=int(version))
    except Exception:  # noqa: BLE001 - the listing is advisory; it may never fail a turn
        logger.warning("ad_pregenerated_unreadable", workspace_id=workspace_id)
        return ()

    return tuple(reduce_pregenerated(rows))


# --- the W4 offer-time freeze (Wave-C fix #1) ---------------------------------------------
#
# The lane used to be composed at CLAIM time by whichever worker process won the
# ``design_job`` row, so per-process env divergence silently changed what a turn saw (Wave B:
# flag-off audit APIs drained the shared queue; turns lost their references with zero log —
# the path was silent when it declined, by design). The offerer now freezes the lane into the
# envelope's ``config["ad_lane"]`` and the claiming process consumes it verbatim: the offer
# is the truth, and a claiming process's flags cannot change what the turn sees.

#: Sentinel distinguishing "the envelope carries no ``ad_lane`` key" (a LEGACY envelope,
#: posted before offer-time freezing — fall back to claim-time composition) from a frozen
#: ``None`` (= the offerer decided: no lane for this turn). Same pattern as
#: ``main._REFERENCES_UNRESOLVED``.
FROZEN_LANE_ABSENT = object()


def lane_to_frozen(lane: Optional[AdLane]) -> Optional[JsonObject]:
    """The lane serialized for an envelope, or ``None`` — always JSON-safe."""
    if lane is None:
        return None
    return {
        "card": dict(lane.card) if isinstance(lane.card, dict) else None,
        "creative_assets": dict(lane.creative_assets),
        "pregenerated": [dict(entry) for entry in lane.pregenerated],
        "creatives": [dict(entry) for entry in lane.creatives],
    }


def frozen_lane_payload(workspace_id: str, *, store: Any = None) -> Optional[JsonObject]:
    """What an OFFERER writes into ``config["ad_lane"]``: the lane by value, or ``None``.

    ``None`` both when the flag is off in the offering process and when the workspace simply
    holds no creatives — either way the offer is decided, and the claiming process will not
    re-litigate it. Rides :func:`read_ad_lane`, so it inherits the flag gate and the
    tolerant-by-construction posture: a lane that cannot be read is a turn without the lane,
    never a failed offer.
    """
    return lane_to_frozen(read_ad_lane(workspace_id, store=store))


def lane_from_frozen(value: Any) -> Optional[AdLane]:
    """An :class:`AdLane` from a frozen envelope value; tolerant of foreign shapes.

    A malformed frozen value yields ``None`` with a warning rather than a failed turn — the
    same asymmetry-against-the-manual-path rule as everything else in this module: nothing
    the human did not explicitly ask for may fail their turn.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        logger.warning("ad_lane_frozen_malformed", value_type=type(value).__name__)
        return None
    raw_assets = value.get("creative_assets")
    creative_assets = (
        {str(k): str(v) for k, v in raw_assets.items() if k and v}
        if isinstance(raw_assets, dict)
        else {}
    )
    if not creative_assets:
        return None
    card = value.get("card")
    raw_pregenerated = value.get("pregenerated")
    pregenerated = tuple(
        dict(entry) for entry in raw_pregenerated if isinstance(entry, dict)
    ) if isinstance(raw_pregenerated, list) else ()
    raw_creatives = value.get("creatives")
    if isinstance(raw_creatives, list):
        creatives = tuple(reduce_creatives([e for e in raw_creatives if isinstance(e, dict)]))
    else:
        # A lane frozen before 2026-10-30 carries no headline or copy: list the ads blank.
        creatives = tuple(
            {"creative_id": creative_id, "asset_id": asset_id, "headline": None,
             "commentary": None, "created_at": None}
            for creative_id, asset_id in creative_assets.items()
        )
    return AdLane(
        card=card if isinstance(card, dict) else None,
        creative_assets=creative_assets,
        pregenerated=pregenerated,
        creatives=creatives,
    )


def resolve_turn_ad_lane(
    frozen: Any = FROZEN_LANE_ABSENT, *, workspace_id: str, store: Any = None
) -> Optional[AdLane]:
    """The lane a CLAIMED turn runs with — frozen truth first, legacy compose second.

    A frozen value (including a frozen ``None``) is consumed verbatim: no flag check, no
    database read — the offering process already decided, and this is exactly what makes the
    turn's behaviour independent of which worker claimed it.

    Only a LEGACY envelope (no ``ad_lane`` key) falls back to claim-time composition, and
    that fallback is no longer allowed to be silent: a flag-off claiming process now says
    LOUDLY that it cannot see the lane — the Wave-B failure shape (flag-off temp workers
    silently stripping references from turns queued by a flag-on deployment) can never again
    present as "nothing happened".
    """
    if frozen is not FROZEN_LANE_ABSENT:
        return lane_from_frozen(frozen)
    if not settings.lumen_brand_ad_assets:
        logger.warning(
            "ad_lane_flag_off_in_claiming_process",
            workspace_id=workspace_id,
            detail=(
                "legacy envelope carries no frozen ad_lane and this process's "
                "LUMEN_BRAND_AD_ASSETS is off; if the offering deployment had the lane on, "
                "this turn's ad list and description were just silently lost (Wave-B W-B2 shape)"
            ),
        )
        return None
    return read_ad_lane(workspace_id, store=store)


def context_pregenerated(lane: Optional[AdLane]) -> Optional[list[JsonObject]]:
    """The pre-generated grounds a turn carries BY VALUE, or ``None`` when there are none.

    ``None`` rather than an empty list, matching ``context_card`` and every other by-value
    channel here: absence is what keeps a lane-less turn byte-identical to a pre-W4 one.
    """
    if lane is None or not lane.pregenerated:
        return None
    return [dict(entry) for entry in lane.pregenerated]


# ---------------------------------------------------------------------------------------------
# The description, on its way into the turn's opening context
# ---------------------------------------------------------------------------------------------


def context_card(lane: Optional[AdLane]) -> Optional[JsonObject]:
    """The card payload a turn carries BY VALUE, or ``None`` when there is nothing to carry.

    Already bounded at distillation (``MAX_PROSE_CHARS``), so this is a
    presence check rather than a second truncation — one bound in one place. A lane with
    creatives but no card returns ``None``: the ads are still listed, and the turn simply gets
    no description, which is honest.
    """
    if lane is None or not isinstance(lane.card, dict):
        return None
    prose = str(lane.card.get("prose") or "").strip()
    return lane.card if prose else None


# ---------------------------------------------------------------------------------------------
# The brand's ads, listed for the agent (spec 2026-10-30, reference ads §5.5)
# ---------------------------------------------------------------------------------------------


def context_brand_ads(
    lane: Optional[AdLane], asset_library: Optional[JsonObject]
) -> Optional[list[JsonObject]]:
    """Every ad of the brand the agent can open this turn, newest first, or ``None``.

    Two sources, one list: the harvested creatives (with their headline and post copy), and
    every other library asset whose shown type is ``ad`` — which, since only code and people
    may call an asset an ad, means a person marked it. A harvested ad is listed while its
    library entry is in this turn's library and its type is ``ad`` or not yet known (no
    description); a person who retyped it removes it. Needs no lane: a person's own ads are
    listed when the harvest lane is off.
    """
    from lumen_agent.engine_mirror import record_pixel_dims

    library = asset_library or {}
    ads: list[JsonObject] = []

    def row(asset_id: str, entry: JsonObject, source: str, creative: JsonObject) -> JsonObject:
        dims = record_pixel_dims(entry.get("record") or {}) or (None, None)
        return {
            "asset_id": asset_id,
            "from": source,
            "headline": creative.get("headline"),
            "commentary": creative.get("commentary"),
            "title": entry.get("title"),
            "description": entry.get("description"),
            "width": dims[0],
            "height": dims[1],
            "created_at": creative.get("created_at") or entry.get("created_at"),
        }

    harvested: set[str] = set()
    for creative in (lane.creatives if lane is not None else ()):
        asset_id = str(creative.get("asset_id") or "")
        entry = library.get(asset_id)
        if not isinstance(entry, dict) or asset_id in harvested:
            continue
        harvested.add(asset_id)
        if entry.get("creative_type") in (None, "ad"):
            ads.append(row(asset_id, entry, "linkedin_ad", creative))
    for asset_id, entry in library.items():
        if asset_id not in harvested and isinstance(entry, dict) and entry.get("creative_type") == "ad":
            ads.append(row(asset_id, entry, "marked_by_person", {}))
    if not ads:
        return None
    dated = sorted((ad for ad in ads if ad["created_at"]), key=lambda ad: str(ad["created_at"]), reverse=True)
    return dated + [ad for ad in ads if not ad["created_at"]]
