"""Pre-generation: one background from each of up to four of the brand's ads (spec §4.3, §5 W2).

Generated offline against the brand's own harvested creatives, so a later ad turn has something
to place instead of having to invent a ground mid-run.

**One background per ad (founder ruling 2026-10-30, reference ads spec §6).** Backgrounds used to
be made per style group, every one seeing the same handful of ads. There are no groups now: each
of the first :data:`ADS_TO_GENERATE_FROM` ads gets one background, made with that ad as its only
reference and told to imitate its background, in the shape closest to the ad's own. The card's
prose still rides every prompt. The durable link column is still called ``visual_system``
(migration ``50ce19bf5ef7``) and now carries the source ad's creative id — the column keeps its W2
name because renaming it would be a migration that buys nothing.

**Nothing about the model call is new here.** It goes through the hardened provider seam W1.4
and W1.7 built: the resolved image model id, ``aspect_ratio`` riding ``image_config``
structurally, one retry on a text-only ``image_model.no_image`` reply, and honest reporting of
the dimensions the model actually returned. This module only decides WHAT to ask for and what
to do with the answer.

**Prompt discipline: background only.** The engine supplies structure, typography and tokens
(spec §1); the image model supplies atmosphere. So every prompt built here is explicitly told
to produce no text, no logo, no wordmark and no UI — a generated ground with baked-in type is a
ground the engine cannot lay type on.

**A failed generation is never fatal.** Each asset is attempted independently and a failure is
recorded and skipped, exactly as one rotten creative URL is during harvest. The harvest and the
card are already durable by the time this runs; losing them to a provider hiccup would be the
worst trade in the lane.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ADS_TO_GENERATE_FROM",
    "PROSE_IN_PROMPT_CHARS",
    "PregeneratedAsset",
    "PregenerationOutcome",
    "background_prompt_for",
    "pregenerate_for_ads",
    "shape_for",
]

JsonObject = dict[str, Any]

#: How many of the brand's ads get a background each (founder 2026-10-30: "make 3-4 from 3-4
#: different ads"). Each background is made from ONE ad, so the set differs the way the ads do.
ADS_TO_GENERATE_FROM = 4

#: How much of the card's prose rides one image prompt. The card is bounded for the AGENT's
#: opening context, which is a different budget from an image model's prompt: past a paragraph
#: or two an image prompt stops steering and starts averaging.
PROSE_IN_PROMPT_CHARS = 900

#: The (aspect_ratio, label) shapes a background can take; each takes its ad's nearest one.
ASSET_SHAPES = (
    ("16:9", "wide"),
    ("1:1", "square"),
    ("4:5", "portrait"),
)


@dataclass(frozen=True)
class PregeneratedAsset:
    asset_id: str
    visual_system: str
    prompt: str
    record: JsonObject
    generation_key: str | None
    generation: JsonObject


@dataclass
class PregenerationOutcome:
    assets: list[PregeneratedAsset] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)

    def links(self) -> list[JsonObject]:
        """The rows :func:`clue_design.ad_assets.link_pregenerated_assets` wants."""
        return [
            {
                "asset_id": asset.asset_id,
                "visual_system": asset.visual_system,
                "prompt": asset.prompt,
                "generation": asset.generation,
            }
            for asset in self.assets
        ]


def background_prompt_for(*, prose: str, shape_label: str, brand_name: str | None) -> str:
    """One background's prompt, sent with ONE of the brand's ads attached.

    Founder-approved wording (2026-10-30): imitate the attached ad's background and leave out
    everything placed on top of it. The card's prose still rides along so the background
    belongs to the brand's family, not only to the one ad.
    """
    brand = f"{brand_name}'s" if brand_name else "a brand's"
    parts = [
        f"A {shape_label} background for {brand} advertising.",
        "The attached image is one of the brand's published ads.",
        "Imitate that ad's background: its colours, gradients, textures, shapes, light and mood.",
        "Leave out everything placed on top of it: its words, logo, people, product shots and "
        "screenshots.",
    ]
    described = _bounded(str(prose or "").strip())
    if described:
        ending = "" if described.endswith(("!", "?")) else "."
        parts.append(f"The brand's published ads, described: {described.removesuffix('.')}{ending}")
    parts.append(
        "Produce a background image only. No text of any kind, no letters, no numbers, no "
        "wordmark, no logo, no watermark, no user interface."
    )
    return " ".join(parts)


def _bounded(prose: str) -> str:
    """At most ``PROSE_IN_PROMPT_CHARS`` of the prose, cut between words where it has any."""
    if len(prose) <= PROSE_IN_PROMPT_CHARS:
        return prose
    cut = prose[:PROSE_IN_PROMPT_CHARS]
    if not prose[PROSE_IN_PROMPT_CHARS].isspace() and " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip()


def shape_for(image_bytes: bytes) -> tuple[str, str]:
    """The ``ASSET_SHAPES`` entry closest to an ad's own ratio; square when it cannot be read."""
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            width, height = image.size
    except Exception:  # noqa: BLE001 - an unreadable ad still gets a background
        return ASSET_SHAPES[1]
    if not width or not height:
        return ASSET_SHAPES[1]
    ratio = width / height

    def distance(shape: tuple[str, str]) -> float:
        across, down = (int(part) for part in shape[0].split(":"))
        return abs(ratio - across / down)

    return min(ASSET_SHAPES, key=distance)


def pregenerate_for_ads(
    card: JsonObject,
    *,
    ads: list[tuple[str, bytes, str]],
    core: Any,
    cache_dir: str,
    generate: Callable[..., Any],
    brand_name: str | None = None,
    generation_key_for: Callable[..., str] | None = None,
    find_generated: Callable[[str], JsonObject | None] | None = None,
    max_bytes: int | None = None,
) -> PregenerationOutcome:
    """One background from each of the first :data:`ADS_TO_GENERATE_FROM` different ads.

    ``ads`` is ``(creative_id, image_bytes, mime_type)`` per harvested ad, in the harvest's
    order. Each generation is sent that one ad as its only reference image, takes the shape
    closest to it, and is linked under its creative id (``visual_system``, the W2 column name).

    ``generate`` is the image provider's ``generate`` — injected rather than imported so a test
    never has to be one monkeypatch away from a real model call. ``core`` is the ingestion
    lane's recording core proxy, so the generated bytes get durable custody. The registry row
    itself is written by the CALLER through the governed ``design_register_generated_asset``
    tool: this function produces records and links, it does not write to the database.
    """
    outcome = PregenerationOutcome()
    prose = str(card.get("prose") or "")
    # Different ads only: two identical images would make two identical backgrounds.
    chosen: dict[str, tuple[str, bytes, str]] = {}
    for ad in ads:
        if len(chosen) >= ADS_TO_GENERATE_FROM:
            break
        chosen.setdefault(_digest(ad[1]), ad)
    for creative_id, ad_bytes, ad_mime in chosen.values():
        aspect_ratio, shape_label = shape_for(ad_bytes)
        prompt = background_prompt_for(prose=prose, shape_label=shape_label, brand_name=brand_name)
        generation_key = (
            generation_key_for(
                prompt=prompt, aspect_ratio=aspect_ratio, reference_digest=_digest(ad_bytes)
            )
            if generation_key_for is not None
            else None
        )
        # PRE-SPEND PROBE, the ``/assets/generate`` route's own pattern and for its own reason:
        # this is the read that AVOIDS the model call, so it has to happen before it. Every
        # generated image has different bytes and therefore a different content-derived asset
        # id, so without the ledger a re-offered job silently pays for the whole set again.
        if generation_key and find_generated is not None:
            claimed = find_generated(generation_key)
            if claimed:
                outcome.assets.append(_claimed_asset(claimed, creative_id, prompt, aspect_ratio, 1))
                continue
        try:
            generated = generate(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                reference_images=[(ad_bytes, ad_mime)],
            )
        except Exception as error:  # noqa: BLE001 - a typed provider failure or anything else
            outcome.failures.append((creative_id, _reason(error)))
            continue

        image_bytes = getattr(generated, "image_bytes", b"")
        if not image_bytes:
            outcome.failures.append((creative_id, "image_model.no_image"))
            continue

        asset_id = f"asset_gen_{_digest(image_bytes)[:16]}"
        response = core.ingest_asset(
            cache_dir,
            base64.b64encode(image_bytes).decode("ascii"),
            asset_id,
            f"{creative_id} — {shape_label} background"[:120],
            declared_mime_type=getattr(generated, "mime_type", None),
            kind="raster_image",
            license=getattr(generated, "license", None),
            provenance=getattr(generated, "provenance", None),
            source={
                "kind": "generated",
                "request_id": asset_id,
                "model": getattr(generated, "model", None),
            },
            tags=["ad-pregenerated", f"source-ad:{creative_id}"],
            max_bytes=max_bytes,
            raise_on_error=False,
        )
        record = ((response or {}).get("asset") or {}).get("record") or {}
        if not record.get("id"):
            outcome.failures.append((creative_id, "asset_ingest_failed"))
            continue

        outcome.assets.append(
            PregeneratedAsset(
                asset_id=str(record["id"]),
                visual_system=creative_id,
                prompt=prompt,
                record=record,
                generation_key=generation_key,
                generation={
                    "model": getattr(generated, "model", None),
                    "aspect_ratio": aspect_ratio,
                    # W1.7(b): the model's REAL dimensions, not the ones we asked for.
                    "width": getattr(generated, "width", None),
                    "height": getattr(generated, "height", None),
                    "aspect_ratio_honored": getattr(generated, "aspect_ratio_honored", None),
                    "reference_count": 1,
                },
            )
        )
    return outcome


def _claimed_asset(
    claimed: JsonObject, system: str, prompt: str, aspect_ratio: str, reference_count: int
) -> PregeneratedAsset:
    """One asset an earlier attempt already generated and claimed, re-used as-is."""
    record = claimed.get("asset") or claimed
    return PregeneratedAsset(
        asset_id=str(record["id"]),
        visual_system=system,
        prompt=prompt,
        record=record,
        generation_key=None,
        generation={
            "model": None,
            "aspect_ratio": aspect_ratio,
            "reference_count": reference_count,
            # Truthful about WHY there was no spend, rather than reporting a fresh generation.
            "reused_from_generation_ledger": True,
        },
    )


def _reason(error: BaseException) -> str:
    code = getattr(error, "code", None)
    return str(code) if code else f"{type(error).__name__}: {error}"


def _digest(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()
