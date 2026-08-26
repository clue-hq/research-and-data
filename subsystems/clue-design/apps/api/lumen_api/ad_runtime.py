"""W4 — the Brand Ad Assets lane at TURN time (spec ``brand-ad-assets-v1-spec.md`` §4, §5 W4).

W2 populates the lane at onboarding: harvested creatives with durable bytes, one immutable
prose ad-DNA card per harvest, and pre-generated imagery. This module is the other end — the
two things a scene design turn takes out of that lane:

1. **References.** When the lane holds harvested creatives and the human attached nothing, the
   turn is conditioned on the brand's OWN published ads instead of on nothing. Up to four
   (:data:`AUTO_REFERENCE_MAX`, the cap ruling), chosen by :func:`select_reference_asset_ids`.
2. **The description.** The card's prose rides the turn's opening context as advisory text,
   next to the brand card. It is context, never a gate and never a required structure — ruling
   D5 stands: no approval gates and no mechanical guards on the agent.

**Everything here is off unless ``LUMEN_BRAND_AD_ASSETS`` is on.** :func:`read_ad_lane` returns
``None`` on a flag-off process before it touches a database, so a flag-off turn issues no query,
makes no model call, and composes byte-identically to a pre-W4 one.

**Nothing here reaches the composition corpus.** That corpus is dormant by ruling: W4 does not
load it, does not cite it and does not point the agent at it.

SELECTION, STATED LOUDLY BECAUSE IT IS THE INTERESTING CHOICE. v1 is the simplest mechanism
that is honest about what it knows:

* If the card names style groups, ONE cheap bounded text call asks which group's name best fits
  this turn's brief, and that group's creatives are attached. The names came from the vision
  pass, so this is matching prose against prose — the thing a language model is actually good
  at — rather than inventing a similarity metric over pixels.
* One group means there is nothing to choose, so the call is skipped.
* Anything else — no card, no groups, a call that fails, a group whose creatives are all
  unresolvable — falls back DETERMINISTICALLY to the most recently harvested creatives. The
  fallback is not an error path; a brand with one look genuinely has nothing to select between,
  and the most recent harvest is the most current statement of what its ads look like.

The selector never raises. A reference the human did not ask for must never be able to fail a
turn — that asymmetry against the manual path (where an unresolvable attachment is a loud 422,
because it is explicit user intent) is deliberate and is enforced at the call site in
``main.resolve_auto_ad_references``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from py_lumen_config import settings
from py_lumen_obs import get_logger

JsonObject = dict[str, Any]

logger = get_logger("lumen_api.ad_runtime")

__all__ = [
    "AUTO_REFERENCE_MAX",
    "CREATIVE_SCAN",
    "AdLane",
    "choose_style_group",
    "context_card",
    "read_ad_lane",
    "select_reference_asset_ids",
]

#: How many harvested creatives one turn is conditioned on. Mirrors
#: ``main.REFERENCE_ASSETS_MAX`` — the cap-4 ruling (2026-08-24) is one number for the manual
#: and the automatic path alike, and a test pins the two constants together. Declared here
#: rather than imported because ``main`` imports THIS module, not the other way round.
AUTO_REFERENCE_MAX = 4

#: How many creative rows the selector reads. A harvest is tens of rows, not thousands, and
#: the read exists to resolve creative ids to asset ids — it is a lookup, not a scan.
CREATIVE_SCAN = 200

#: The selection call's output bound. The answer is one group name.
SELECT_MAX_TOKENS = 32
SELECT_TIMEOUT_S = 20.0
#: How much of the brief the selection call sees. It is choosing between a handful of short
#: names; the first paragraph of the ask is more than enough to do that.
SELECT_BRIEF_CHARS = 1200


@dataclass(frozen=True)
class AdLane:
    """What this workspace's ad-assets lane holds right now.

    ``card`` is the card's PAYLOAD (the ``card_json`` column's contents — ``prose`` plus
    ``style_groups``), not the row wrapper, because that payload is what both consumers want.
    ``creative_assets`` maps creative id → the design asset id holding its bytes, in
    newest-harvested-first order, which is also the deterministic fallback order.
    """

    card: Optional[JsonObject]
    creative_assets: dict[str, str]

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
    creative_assets = {
        str(row["creative_id"]): str(row["asset_id"])
        for row in creatives
        if row.get("creative_id") and row.get("asset_id")
    }
    if not creative_assets:
        return None
    try:
        row = store.latest_card()
    except Exception:  # noqa: BLE001 - a card read failure still leaves usable creatives
        logger.warning("ad_dna_card_unreadable", workspace_id=workspace_id)
        row = None
    card = (row or {}).get("card") if isinstance(row, dict) else None
    return AdLane(card=card if isinstance(card, dict) else None, creative_assets=creative_assets)


def select_reference_asset_ids(
    brief: str,
    lane: AdLane,
    *,
    choose: Optional[Callable[[str, list[str]], Optional[str]]] = None,
    limit: int = AUTO_REFERENCE_MAX,
) -> list[str]:
    """Up to ``limit`` asset ids from the lane, best-matched to this turn's brief.

    ``choose`` is the group-picking seam (default :func:`choose_style_group`), injected so the
    suites can drive both branches — the match and the fallback — without a model call.
    """
    if limit <= 0 or not lane.has_creatives:
        return []
    recency = list(lane.creative_assets.values())

    groups = [
        group
        for group in ((lane.card or {}).get("style_groups") or [])
        if isinstance(group, dict) and str(group.get("name") or "").strip()
    ]
    if not groups:
        return recency[:limit]

    if len(groups) == 1:
        chosen: Optional[JsonObject] = groups[0]
    else:
        picker = choose if choose is not None else choose_style_group
        try:
            name = picker(brief, [str(group["name"]) for group in groups])
        except Exception:  # noqa: BLE001 - a selection failure falls back, never fails the turn
            logger.warning("ad_reference_selection_failed")
            name = None
        chosen = _group_named(groups, name)

    if chosen is not None:
        matched = [
            lane.creative_assets[str(creative_id)]
            for creative_id in (chosen.get("creative_ids") or [])
            if str(creative_id) in lane.creative_assets
        ]
        if matched:
            return matched[:limit]
        # A named group whose creatives no longer resolve (a re-harvest replaced them) is a
        # stale pointer, not a reason to attach nothing.
        logger.warning("ad_style_group_creatives_unresolvable", group=str(chosen.get("name")))
    return recency[:limit]


def _group_named(groups: list[JsonObject], name: Optional[str]) -> Optional[JsonObject]:
    """The group the model named, matched leniently — or ``None`` if it named none of them.

    Lenient because the answer is free text: a model asked for a name out of a short list
    routinely returns it quoted, trailing-stopped, or wrapped in a sentence. What it may NOT do
    is invent a group, which is why the answer is matched against the known names rather than
    trusted.
    """
    if not name:
        return None
    candidate = str(name).strip().strip('"\'.,: ').lower()
    if not candidate:
        return None
    for group in groups:
        if str(group["name"]).strip().lower() == candidate:
            return group
    for group in groups:
        known = str(group["name"]).strip().lower()
        if known and known in candidate:
            return group
    return None


def choose_style_group(brief: str, names: list[str]) -> Optional[str]:
    """One cheap, bounded text call: which of these looks fits this brief?

    Deliberately the smallest thing that can do the job — no images, a truncated brief, a
    handful of short names in, one name out, ``max_tokens`` in the tens. The creatives
    themselves are what actually steer the design; this call only decides WHICH of the brand's
    looks the turn starts from, so paying vision-model money to make it would be spending real
    tokens on a tie-break.

    Runs on the same OpenRouter gateway and the same model id the lane's distillation uses
    (``LUMEN_AD_DNA_MODEL``), so W4 introduces no new credential and no new model to configure.
    Never raises: an unkeyed process, a network failure or an unparseable answer all return
    ``None``, and the caller falls back to recency.
    """
    api_key = settings.openrouter_api_key
    if not names or not api_key.strip():
        return None
    import httpx  # lazy: only the real network path needs it

    listing = "\n".join(f"- {name}" for name in names)
    body = {
        "model": settings.lumen_ad_dna_model,
        "max_tokens": SELECT_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": _SELECT_PROMPT},
            {
                "role": "user",
                "content": (
                    f"The brief:\n{str(brief or '').strip()[:SELECT_BRIEF_CHARS]}\n\n"
                    f"The brand's looks:\n{listing}"
                ),
            },
        ],
    }
    url = settings.openrouter_base_url.rstrip("/") + "/chat/completions"
    try:
        response = httpx.post(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=SELECT_TIMEOUT_S,
        )
        if response.status_code >= 400:
            logger.warning("ad_style_group_call_failed", status=response.status_code)
            return None
        return str(response.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception:  # noqa: BLE001 - a tie-break may never fail a design turn
        logger.warning("ad_style_group_call_errored")
        return None


_SELECT_PROMPT = (
    "A brand runs several different-looking ads. You are given the names of those looks and "
    "the brief for a new ad. Pick the one look the new ad should start from. "
    "Answer with that name and nothing else. "
    "If none of them fits the brief better than the others, answer with the first name."
)


# ---------------------------------------------------------------------------------------------
# The description, on its way into the turn's opening context
# ---------------------------------------------------------------------------------------------


def context_card(lane: Optional[AdLane]) -> Optional[JsonObject]:
    """The card payload a turn carries BY VALUE, or ``None`` when there is nothing to carry.

    Already bounded at distillation (``MAX_PROSE_CHARS`` / ``MAX_STYLE_GROUPS``), so this is a
    presence check rather than a second truncation — one bound in one place. A lane with
    creatives but no card returns ``None``: the references still ride, and the turn simply gets
    no description, which is honest.
    """
    if lane is None or not isinstance(lane.card, dict):
        return None
    prose = str(lane.card.get("prose") or "").strip()
    return lane.card if prose else None
