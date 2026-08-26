"""Pre-generation: brand-coherent imagery per named visual system (spec §4.3, §5 W2).

One to three assets per system, generated offline against the brand's own harvested creatives,
so a later ad turn has something to place instead of having to invent a ground mid-run.

**Nothing about the model call is new here.** It goes through the hardened provider seam W1.4
and W1.7 built: the resolved image model id, ``aspect_ratio`` riding ``image_config``
structurally, one retry on a text-only ``image_model.no_image`` reply, and honest reporting of
the dimensions the model actually returned. This module only decides WHAT to ask for and what
to do with the answer.

**Prompt discipline: background only.** The engine supplies structure, typography and tokens
(spec §1); the image model supplies atmosphere. So every prompt built here is explicitly told
to produce no text, no logo, no wordmark, no UI and no people — a generated ground with baked-in
type is a ground the engine cannot lay type on, and it is the single most common way generated
ad imagery becomes unusable.

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
    "ASSETS_PER_SYSTEM",
    "MAX_REFERENCE_IMAGES",
    "PregeneratedAsset",
    "PregenerationOutcome",
    "background_prompt_for",
    "pregenerate_for_card",
]

JsonObject = dict[str, Any]

#: Assets per named visual system (spec §4.3: "2–3 assets"). Two by default — one wide ground
#: and one square — because a system that gets three near-identical grounds has not gained a
#: choice, it has gained two more things to scroll past in the library manifest.
ASSETS_PER_SYSTEM = 2

#: How many harvested creatives condition one generation call. The cap mirrors the runtime's
#: own ``REFERENCE_ASSETS_MAX``: past four, references dilute rather than steer (ruling D1).
MAX_REFERENCE_IMAGES = 4

#: The (aspect_ratio, label) pairs each system is asked for, in order.
ASSET_SHAPES = (
    ("16:9", "wide ground"),
    ("1:1", "square ground"),
    ("4:5", "portrait ground"),
)

#: Appended to every prompt. Not negotiable and not per-system: the division of labour between
#: the image model and the engine is a property of the pipeline, not of a brand's taste.
BACKGROUND_ONLY_CLAUSE = (
    "Produce a background image only. No text of any kind, no letters, no numbers, no "
    "wordmark, no logo, no watermark, no user interface, no charts, no people and no faces. "
    "Leave the composition open in the middle so type and a card can be laid over it later."
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


def background_prompt_for(system: JsonObject, *, shape_label: str, brand_name: str | None) -> str:
    """One system's background prompt, in the brand's own words from the card.

    The card's plain-language fields ARE the prompt's substance — that is the whole point of
    distilling it. Anchoring generation in the brand's measured ground treatment and accent
    spend, rather than in an adjective someone typed, is what makes the output a member of the
    brand's system instead of a generically pretty image.
    """
    parts: list[str] = []
    if brand_name:
        parts.append(f"A {shape_label} for {brand_name}'s advertising.")
    else:
        parts.append(f"A {shape_label} for a brand's advertising.")
    ground = str(system.get("ground_treatment") or "").strip()
    if ground:
        parts.append(f"Ground treatment: {ground}")
    accent = str(system.get("accent_spend") or "").strip()
    if accent:
        parts.append(f"Accent colour, used sparingly: {accent}")
    name = str(system.get("name") or "").strip()
    if name:
        parts.append(f"This belongs to the brand's '{name}' visual system.")
    parts.append(BACKGROUND_ONLY_CLAUSE)
    return " ".join(parts)


def pregenerate_for_card(
    card: JsonObject,
    *,
    core: Any,
    cache_dir: str,
    generate: Callable[..., Any],
    reference_images: list[tuple[bytes, str]] | None = None,
    brand_name: str | None = None,
    assets_per_system: int = ASSETS_PER_SYSTEM,
    generation_key_for: Callable[..., str] | None = None,
    find_generated: Callable[[str], JsonObject | None] | None = None,
    max_bytes: int | None = None,
) -> PregenerationOutcome:
    """Generate imagery for every named visual system on one card.

    ``generate`` is the image provider's ``generate`` — injected rather than imported so a test
    never has to be one monkeypatch away from a real model call, and so the caller keeps the
    choice of which hardened entry point is used.

    ``core`` is the ingestion lane's recording core proxy, so the generated bytes get durable
    custody and a re-pointed record location on the way past, exactly as harvested creative
    bytes do. The registry row itself is written by the CALLER through the governed
    ``design_register_generated_asset`` tool: this function produces records and links, it does
    not write to the database.
    """
    outcome = PregenerationOutcome()
    systems = card.get("visual_systems") or []
    references = (reference_images or [])[:MAX_REFERENCE_IMAGES]

    for system in systems:
        if not isinstance(system, dict):
            continue
        name = str(system.get("name") or "").strip()
        if not name:
            continue
        for aspect_ratio, shape_label in ASSET_SHAPES[: max(0, assets_per_system)]:
            prompt = background_prompt_for(
                system, shape_label=shape_label, brand_name=brand_name
            )
            generation_key = (
                generation_key_for(prompt=prompt, aspect_ratio=aspect_ratio)
                if generation_key_for is not None
                else None
            )
            # PRE-SPEND PROBE, the ``/assets/generate`` route's own pattern and for its own
            # reason: this is the read that AVOIDS the model call, so it has to happen before
            # it. It matters most on the path nobody plans for — the reaper re-offering a job
            # whose worker died after generating — because every generated image has different
            # bytes and therefore a different content-derived asset id, so without the ledger a
            # re-offer silently pays for the whole set again.
            if generation_key and find_generated is not None:
                claimed = find_generated(generation_key)
                if claimed:
                    outcome.assets.append(
                        _claimed_asset(claimed, name, prompt, aspect_ratio, len(references))
                    )
                    continue
            try:
                generated = generate(
                    prompt=prompt,
                    aspect_ratio=aspect_ratio,
                    reference_images=references or None,
                )
            except Exception as error:  # noqa: BLE001 - a typed provider failure or anything else
                outcome.failures.append((f"{name}:{aspect_ratio}", _reason(error)))
                continue

            image_bytes = getattr(generated, "image_bytes", b"")
            if not image_bytes:
                outcome.failures.append((f"{name}:{aspect_ratio}", "image_model.no_image"))
                continue

            asset_id = f"asset_gen_{_digest(image_bytes)[:16]}"
            response = core.ingest_asset(
                cache_dir,
                base64.b64encode(image_bytes).decode("ascii"),
                asset_id,
                f"{name} — {shape_label}"[:120],
                declared_mime_type=getattr(generated, "mime_type", None),
                kind="raster_image",
                license=getattr(generated, "license", None),
                provenance=getattr(generated, "provenance", None),
                source={
                    "kind": "generated",
                    "request_id": asset_id,
                    "model": getattr(generated, "model", None),
                },
                tags=["ad-pregenerated", f"visual-system:{name}"],
                max_bytes=max_bytes,
                raise_on_error=False,
            )
            record = ((response or {}).get("asset") or {}).get("record") or {}
            if not record.get("id"):
                outcome.failures.append((f"{name}:{aspect_ratio}", "asset_ingest_failed"))
                continue

            outcome.assets.append(
                PregeneratedAsset(
                    asset_id=str(record["id"]),
                    visual_system=name,
                    prompt=prompt,
                    record=record,
                    generation_key=generation_key,
                    generation={
                        "model": getattr(generated, "model", None),
                        "aspect_ratio": aspect_ratio,
                        # W1.7(b): the model's REAL dimensions, not the ones we asked for.
                        "width": getattr(generated, "width", None),
                        "height": getattr(generated, "height", None),
                        "aspect_ratio_honored": getattr(
                            generated, "aspect_ratio_honored", None
                        ),
                        "reference_count": len(references),
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
