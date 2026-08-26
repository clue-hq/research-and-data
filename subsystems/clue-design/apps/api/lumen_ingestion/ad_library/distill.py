"""Distillation: one vision pass over the harvested creatives → the ad-DNA card (spec §4.2).

The card is what every later ad turn is conditioned on, so it is deliberately SMALL and
deliberately PLAIN. It names the brand's visual systems — a real brand runs several; Ramp runs
four — and for each one says, in ordinary words, what the layout skeleton is, how the ground is
treated, where the accent colour is spent, where the logo sits, and how the type feels. It does
not carry pixels, coordinates, or a template.

Everything about this module is the shape of ``lumen_ingestion.describe``, on purpose: the same
OpenRouter chat-completions gateway, the same downscaled-preview channel, the same
strict-JSON-schema response, the same "off is off, not N failures" ``active`` gate, and the same
never-raise posture (a distillation that fails returns ``None`` with a reason, so the harvest it
was given stays exactly as durable as it was).

Bounds are enforced HERE rather than trusted from the model: at most
:data:`MAX_VISUAL_SYSTEMS` systems, each field truncated to :data:`MAX_FIELD_CHARS`. A card is
pushed into every ad turn's opening context, so an unbounded one is a permanent tax on every
run the brand ever does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from py_lumen_config import settings

__all__ = [
    "MAX_FIELD_CHARS",
    "MAX_PREVIEW_CREATIVES",
    "MAX_VISUAL_SYSTEMS",
    "AdDnaCard",
    "AdDnaDistiller",
    "NullAdDnaDistiller",
    "OpenRouterAdDnaDistiller",
    "VisualSystem",
    "bounded_card",
    "resolve_distiller",
]

DEFAULT_TIMEOUT_S = 120.0
#: How much of an error body is threaded into the failure reason.
FAILURE_EXCERPT_MAX = 300

#: A brand runs a handful of systems, not a dozen. Anything past this is the model listing
#: individual ads rather than recognising a system, which is the failure this cap absorbs.
MAX_VISUAL_SYSTEMS = 6
#: Per-field length. One or two plain sentences; the card is a summary, never a spec.
MAX_FIELD_CHARS = 400
#: How many creatives ride the vision call. Beyond this the context cost climbs while the
#: marginal creative teaches the model nothing new about the brand's systems.
MAX_PREVIEW_CREATIVES = 12

#: The card's shape version, stamped into every card so a later reader can tell what it is
#: looking at without inferring it from which keys happen to be present.
CARD_SCHEMA_VERSION = 1

_SYSTEM_FIELDS = (
    "layout_skeleton",
    "ground_treatment",
    "accent_spend",
    "logo_placement",
    "type_feel",
)


@dataclass(frozen=True)
class VisualSystem:
    name: str
    layout_skeleton: str = ""
    ground_treatment: str = ""
    accent_spend: str = ""
    logo_placement: str = ""
    type_feel: str = ""
    example_creative_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdDnaCard:
    visual_systems: tuple[VisualSystem, ...] = ()
    notes: str = ""
    model: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": CARD_SCHEMA_VERSION,
            "visual_systems": [
                {
                    "name": system.name,
                    **{name: getattr(system, name) for name in _SYSTEM_FIELDS},
                    "example_creative_ids": list(system.example_creative_ids),
                }
                for system in self.visual_systems
            ],
            "notes": self.notes,
        }


@runtime_checkable
class AdDnaDistiller(Protocol):
    """Turn creative previews into a card, or ``None`` when it could not."""

    #: Whether distillation can actually run. OFF is OFF — an unkeyed or disabled distiller
    #: must read as "not attempted", never as "attempted and produced nothing".
    active: bool
    model: str

    def distil(self, previews: list["CreativePreview"]) -> AdDnaCard | None: ...


@dataclass(frozen=True)
class CreativePreview:
    """One creative as the vision call sees it: an id, some words, and a downscaled image."""

    creative_id: str
    image_b64: str
    mime_type: str
    caption: str = ""


@dataclass
class NullAdDnaDistiller:
    """The default everywhere, including tests. Never calls anything."""

    active: bool = False
    model: str = "null"
    last_failure_reason: str | None = None

    def distil(self, previews: list[CreativePreview]) -> AdDnaCard | None:
        del previews
        return None


def resolve_distiller() -> AdDnaDistiller:
    """The configured distiller: the real one when the lane and a key are on, else the null one.

    Mirrors ``lumen_ingestion.describe.resolve_describer``. The flag is checked here as well as
    at the route, so no code path can reach a model call with the lane switched off.
    """
    if settings.lumen_brand_ad_assets and settings.openrouter_api_key.strip():
        return OpenRouterAdDnaDistiller()
    return NullAdDnaDistiller()


def bounded_card(payload: Any, *, model: str | None = None) -> AdDnaCard | None:
    """Coerce a model payload into a bounded card, or ``None`` when it names no system.

    ``None`` rather than an empty card is load-bearing: an empty card recorded as a version
    would tell every later ad turn that this brand HAS no visual system, which is a confident
    lie about a distillation that simply failed. The governed publish tool refuses an empty
    card for the same reason.
    """
    if isinstance(payload, dict):
        raw_systems = payload.get("visual_systems") or payload.get("systems") or []
        notes = str(payload.get("notes") or "")[:MAX_FIELD_CHARS]
    elif isinstance(payload, list):
        raw_systems = payload
        notes = ""
    else:
        return None

    systems: list[VisualSystem] = []
    for entry in raw_systems[:MAX_VISUAL_SYSTEMS]:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()[:80]
        if not name:
            continue
        examples = entry.get("example_creative_ids") or entry.get("examples") or []
        systems.append(
            VisualSystem(
                name=name,
                **{
                    key: str(entry.get(key) or "").strip()[:MAX_FIELD_CHARS]
                    for key in _SYSTEM_FIELDS
                },
                example_creative_ids=tuple(
                    str(item) for item in examples if isinstance(item, (str, int))
                )[:MAX_PREVIEW_CREATIVES],
            )
        )
    if not systems:
        return None
    return AdDnaCard(visual_systems=tuple(systems), notes=notes, model=model)


@dataclass
class OpenRouterAdDnaDistiller:
    """The multimodal distillation call. Never raises; a failure is a reason and a ``None``."""

    active: bool = field(init=False, default=False)
    model: str = field(init=False, default="")
    last_failure_reason: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.model = settings.lumen_ad_dna_model
        self._base_url = settings.openrouter_base_url
        self._api_key = settings.openrouter_api_key
        self.active = bool(settings.lumen_brand_ad_assets and self._api_key.strip())

    def distil(self, previews: list[CreativePreview]) -> AdDnaCard | None:
        self.last_failure_reason = None
        if not previews or not self.active:
            return None
        payload = self._invoke(previews[:MAX_PREVIEW_CREATIVES])
        if payload is None:
            return None
        card = bounded_card(payload, model=self.model)
        if card is None:
            self.last_failure_reason = "the model named no visual system"
        return card

    def _invoke(self, previews: list[CreativePreview]) -> Any:
        import httpx  # lazy: only the real network path needs it

        manifest = "\n".join(
            f"{index}. creative_id={preview.creative_id}"
            + (f" — {preview.caption}" if preview.caption else "")
            for index, preview in enumerate(previews, start=1)
        )
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "These are the static ads one brand actually published. Identify the "
                    "distinct VISUAL SYSTEMS the brand runs and describe each one.\n\n"
                    + manifest
                ),
            }
        ]
        for preview in previews:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{preview.mime_type};base64,{preview.image_b64}"
                    },
                }
            )

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "ad_dna_card", "strict": True, "schema": _CARD_SCHEMA},
            },
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = self._base_url.rstrip("/") + "/chat/completions"
        for attempt in range(2):
            try:
                response = httpx.post(url, json=body, headers=headers, timeout=DEFAULT_TIMEOUT_S)
                if response.status_code >= 400:
                    self.last_failure_reason = (
                        f"HTTP {response.status_code} (attempt {attempt + 1}): "
                        f"{response.text[:FAILURE_EXCERPT_MAX]}"
                    )
                    continue
                raw = response.json()["choices"][0]["message"]["content"]
                self.last_failure_reason = None
                return json.loads(raw)
            except Exception as error:  # noqa: BLE001 - a distillation failure is never fatal
                self.last_failure_reason = (
                    f"{type(error).__name__} (attempt {attempt + 1}): "
                    f"{str(error)[:FAILURE_EXCERPT_MAX]}"
                )
                continue
        return None


def previews_for(
    creatives: list[Any],
    *,
    downscale: Any = None,
) -> list[CreativePreview]:
    """Build the vision call's inputs from harvested creatives.

    ``downscale`` is the same seam ``describe._downscale_preview`` is: injected so the pure
    assembly can be tested without Pillow, and defaulted to the description engine's own
    downscaler so there is exactly one implementation of "make a preview" in this app.
    """
    if downscale is None:
        from lumen_ingestion.describe import _downscale_preview as downscale

    previews: list[CreativePreview] = []
    for creative in creatives[:MAX_PREVIEW_CREATIVES]:
        encoded = downscale(creative.image_bytes)
        if encoded is None:
            # A preview that cannot be built is a creative the model simply does not see; the
            # harvest keeps it either way, because its value is as a reference attachment.
            continue
        previews.append(
            CreativePreview(
                creative_id=creative.creative_id,
                image_b64=encoded,
                mime_type="image/png",
                caption=(creative.ad.headline_title or creative.ad.image_alt_text or "")[:160],
            )
        )
    return previews


_SYSTEM_PROMPT = (
    "You read a brand's published static ads and describe the visual systems behind them. "
    "A visual system is a repeatable way the brand builds an ad — not one ad, and not a "
    "theme. A real brand usually runs between two and five. For each system, describe: the "
    "layout skeleton (what sits where, in plain words); the ground treatment (flat colour, "
    "photograph, gradient, texture); where the accent colour is spent and how sparingly; "
    "where the logo sits and on what; and how the type feels (weight, size relationships, "
    "case). Write plainly, one idea per sentence, no jargon and no measurements. Name each "
    "system with a short descriptive label the brand's own team would recognise. List the "
    "creative_ids that belong to each system. Return valid JSON matching the schema."
)

_CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "visual_systems": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "layout_skeleton": {"type": "string"},
                    "ground_treatment": {"type": "string"},
                    "accent_spend": {"type": "string"},
                    "logo_placement": {"type": "string"},
                    "type_feel": {"type": "string"},
                    "example_creative_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "name",
                    "layout_skeleton",
                    "ground_treatment",
                    "accent_spend",
                    "logo_placement",
                    "type_feel",
                    "example_creative_ids",
                ],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["visual_systems", "notes"],
    "additionalProperties": False,
}
