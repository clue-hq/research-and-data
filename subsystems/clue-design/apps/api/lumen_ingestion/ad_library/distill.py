"""Distillation: one vision pass over the harvested creatives → the ad-DNA card (spec §4.2).

The card is what every later ad turn is conditioned on, so it is deliberately SMALL and
deliberately PLAIN. It is a DESCRIPTION, in the model's own words, of what this brand's
published ads actually look like — the way a designer would describe them to another designer
who had not seen them. It carries no pixels, no coordinates and no template.

**Founder ruling, 2026-08-26 — the card is free prose, not a form.** An earlier W2 shape asked
the vision pass to fill in five named fields per "visual system" (layout skeleton, ground
treatment, accent spend, logo placement, type feel). That was rejected as over-specification:
a form makes the model answer questions the ads may not answer, and a confident empty field is
worse than an honest sentence. So the card is now:

* ``prose`` — the description, bounded. The vision prompt nudges toward layout, colour
  behaviour and imagery style, and says outright that the nudge is a suggestion, not a
  checklist.

**No style groups (founder ruling 2026-10-30, reference ads spec §5.3).** The card used to sort
the creatives into at most six named groups so a turn could auto-attach one group's ads. Turns no
longer auto-attach anything — the agent sees every ad and opens the ones it wants — so the card
is the description alone. ``style_groups`` stays in the stored payload, always empty, so a stored
card keeps its version-2 shape and an older card's groups are simply never shown.

**Every harvested creative is seen (founder ruling 2026-10-19).** Every creative is shown,
:data:`CREATIVES_PER_CALL` per vision call, and several batches' descriptions are combined by one
text-only call into the single description.

Versioning and provenance are unchanged: every card version is immutable, stamped with the
model that wrote it, and pinned to the creatives it was distilled from (see
``clue_design.ad_assets``). The stored column is ``jsonb``, so this shape change needs no
migration — ``schema_version`` on the payload is how a reader tells the two apart.

Everything else about this module is still the shape of ``lumen_ingestion.describe``, on
purpose: the same OpenRouter chat-completions gateway, the same downscaled-preview channel, the
same strict-JSON response envelope, the same "off is off, not N failures" ``active`` gate, and
the same never-raise posture (a distillation that fails returns ``None`` with a reason, so the
harvest it was given stays exactly as durable as it was).

Bounds are enforced HERE rather than trusted from the model: the prose truncates at
:data:`MAX_PROSE_CHARS`. A card is pushed into
every ad turn's opening context, so an unbounded one is a permanent tax on every run the brand
ever does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from py_lumen_config import settings

__all__ = [
    "CREATIVES_PER_CALL",
    "MAX_DISTILLED_CREATIVES",
    "MAX_PROSE_CHARS",
    "AdDnaCard",
    "AdDnaDistiller",
    "NullAdDnaDistiller",
    "OpenRouterAdDnaDistiller",
    "bounded_card",
    "resolve_distiller",
]

DEFAULT_TIMEOUT_S = 120.0
#: How much of an error body is threaded into the failure reason.
FAILURE_EXCERPT_MAX = 300

#: The description's length bound. Long enough for a real paragraph or three about a brand
#: that runs several looks; short enough that it stays a summary rather than becoming a spec.
MAX_PROSE_CHARS = 2400
#: How many creatives ride ONE vision call. Every creative is shown, in calls of this size; a
#: larger call costs context faster than it teaches the model about each ad.
CREATIVES_PER_CALL = 12
#: The most creatives one distillation shows, which bounds its cost. The harvest asks for 50.
MAX_DISTILLED_CREATIVES = 100

#: The card's shape version, stamped into every card so a later reader can tell what it is
#: looking at without inferring it from which keys happen to be present. Version 1 was the
#: five-field ``visual_systems`` taxonomy; version 2 is the prose card.
CARD_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class AdDnaCard:
    prose: str = ""
    model: str | None = None

    def to_json(self) -> dict[str, Any]:
        # ``style_groups`` stays, always empty: stored cards keep their version-2 shape.
        return {"schema_version": CARD_SCHEMA_VERSION, "prose": self.prose, "style_groups": []}


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
    """Coerce a model payload into a bounded card, or ``None`` when it describes nothing.

    ``None`` rather than an empty card is load-bearing: an empty card recorded as a version
    would tell every later ad turn that this brand's ads look like nothing in particular, which
    is a confident lie about a distillation that simply failed. The governed publish tool
    refuses a prose-less card for the same reason.

    The DESCRIPTION is the card; any groups a payload carries are ignored (2026-10-30).
    """
    if not isinstance(payload, dict):
        return None
    raw_prose = payload.get("prose") or payload.get("description") or payload.get("notes")
    prose = str(raw_prose or "").strip()[:MAX_PROSE_CHARS]
    if not prose:
        return None
    return AdDnaCard(prose=prose, model=model)


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
        previews = previews[:MAX_DISTILLED_CREATIVES]
        cards: list[AdDnaCard] = []
        for start in range(0, len(previews), CREATIVES_PER_CALL):
            payload = self._call(
                messages=_batch_messages(previews[start : start + CREATIVES_PER_CALL], None),
                schema_name="ad_dna_card",
                schema=_CARD_SCHEMA,
                label=f"ad_dna:{len(previews[start : start + CREATIVES_PER_CALL])} creatives",
            )
            card = bounded_card(payload, model=self.model) if payload is not None else None
            if card is not None:
                cards.append(card)
        if not cards:
            self.last_failure_reason = self.last_failure_reason or "the model described nothing"
            return None
        card = cards[0] if len(cards) == 1 else self._combine(cards)
        self.last_failure_reason = None
        return card

    def _combine(self, cards: list[AdDnaCard]) -> AdDnaCard:
        """Several batches' descriptions into one; the first batch's when the call fails."""
        notes = "\n\n".join(
            f"Batch {number} description:\n{card.prose}" for number, card in enumerate(cards, start=1)
        )
        payload = self._call(
            messages=[
                {"role": "system", "content": _MERGE_PROMPT},
                {"role": "user", "content": notes},
            ],
            schema_name="ad_dna_merge",
            schema=_MERGE_SCHEMA,
            label=f"ad_dna merge:{len(cards)} batches",
        )
        merged = bounded_card(payload, model=self.model) if payload is not None else None
        return merged if merged is not None else cards[0]

    def _call(self, *, messages: list[dict[str, Any]], schema_name: str, schema: dict, label: str) -> Any:
        """One strict-JSON chat call; the parsed answer, or ``None`` with a recorded reason."""
        from clue_spend import ProviderHalted
        from lumen_api import spend  # lazy: only the real network path needs it

        body = {
            "model": self.model,
            "messages": messages,
            # The response ENVELOPE is still schema-pinned, because parsing has to be reliable.
            # What the schema no longer does is dictate the CONTENT: `prose` is one free-text
            # field and the only one.
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        }
        # Two attempts, now the provider caller's, with an estimate row before the wire and a
        # priced result row after. ``ProviderHalted`` propagates: a distillation failure is never
        # fatal, but a provider refusing to sell is not a distillation failure.
        try:
            response = spend.openrouter_call(
                operation="design.ingestion.ad_dna",
                body=body,
                label=label,
                timeout_s=DEFAULT_TIMEOUT_S,
                api_key=self._api_key,
                base_url=self._base_url,
                max_attempts=2,
            )
            if response.status >= 400:
                excerpt = response.body.decode("utf-8", "replace")[:FAILURE_EXCERPT_MAX]
                self.last_failure_reason = f"HTTP {response.status}: {excerpt}"
                return None
            raw = json.loads(response.body)["choices"][0]["message"]["content"]
            return json.loads(raw)
        except ProviderHalted:
            raise
        except Exception as error:  # noqa: BLE001 - a distillation failure is never fatal
            self.last_failure_reason = (
                f"{type(error).__name__}: {str(error)[:FAILURE_EXCERPT_MAX]}"
            )
            return None


def _batch_messages(batch: list[CreativePreview], note: str | None) -> list[dict[str, Any]]:
    manifest = "\n".join(
        f"{index}. creative_id={preview.creative_id}"
        + (f" — {preview.caption}" if preview.caption else "")
        for index, preview in enumerate(batch, start=1)
    )
    text = (
        "These are the static ads one brand actually published. Describe what "
        "they look like.\n\n" + manifest
    )
    if note:
        text += "\n\n" + note
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for preview in batch:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{preview.mime_type};base64,{preview.image_b64}"},
            }
        )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


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
    for creative in creatives[:MAX_DISTILLED_CREATIVES]:
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
    "You are looking at the static ads one brand actually published. "
    "Describe, in your own plain words, what this brand's ads look like. "
    "Write it for a designer who is about to make a new ad for this brand and has never "
    "seen these ones.\n\n"
    "Say what is actually there. Do not invent a rule the ads do not show you. If the brand "
    "runs several looks that are clearly different from each other, say so and describe each "
    "one. If they all look like the same thing, say that instead.\n\n"
    "Things usually worth covering, when the ads actually tell you: how an ad is laid out and "
    "what sits where; how colour behaves, and which colour is used sparingly; what the "
    "imagery is like, or whether there is any; how the type feels; where the logo sits. "
    "Treat that as a nudge, not a checklist. Skip anything these ads do not answer, and say "
    "anything else you notice that a designer would want to know.\n\n"
    "Write plainly. One idea per sentence. No jargon, no measurements, no marketing "
    "language."
)

_MERGE_PROMPT = (
    "You are reading notes about the static ads one brand actually published. The ads were "
    "looked at in batches, so each batch has its own description.\n\n"
    "Write one description of what this brand's ads look like, for a designer who is about to "
    "make a new ad for this brand and has never seen these ones. Keep what the batch "
    "descriptions say. Do not add anything they do not say. If the brand runs several looks "
    "that are clearly different from each other, describe each one.\n\n"
    "Write plainly. One idea per sentence. No jargon, no measurements, no marketing "
    "language."
)

_MERGE_SCHEMA = {
    "type": "object",
    "properties": {"prose": {"type": "string"}},
    "required": ["prose"],
    "additionalProperties": False,
}

_CARD_SCHEMA = {
    "type": "object",
    "properties": {"prose": {"type": "string"}},
    "required": ["prose"],
    "additionalProperties": False,
}
