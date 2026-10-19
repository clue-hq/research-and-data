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
* ``style_groups`` — the ONLY structure left, and it exists for exactly one machine reason:
  reference selection at turn time needs to know which described style covers which harvested
  creatives. A group is a free-form name plus the creative ids that belong to it. Nothing
  reads a group's name for meaning except the selector, which matches it against the brief.

**Every harvested creative is sorted (founder ruling 2026-10-19).** The call used to see only the
first 12 creatives, so a brand with 50 harvested ads had 38 that no group could ever attach
(Stripe: 12 of 50 grouped; Conduit: 6 of 16). Now every creative is shown, :data:`CREATIVES_PER_CALL`
per vision call. Each call's answer must place every creative it was shown in exactly one group,
and is asked once more, naming the gaps, when it does not. Several batches are combined by one
text-only call that writes the single description and merges the batches' looks, held to the same
rule for the looks. A creative still unplaced after the second ask is left out and named on
``last_ungrouped`` — never a failed distillation.

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
:data:`MAX_PROSE_CHARS` and the groups cap at :data:`MAX_STYLE_GROUPS`. A card is pushed into
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
    "MAX_GROUP_NAME_CHARS",
    "MAX_PROSE_CHARS",
    "MAX_STYLE_GROUPS",
    "AdDnaCard",
    "AdDnaDistiller",
    "NullAdDnaDistiller",
    "OpenRouterAdDnaDistiller",
    "StyleGroup",
    "bounded_card",
    "resolve_distiller",
]

DEFAULT_TIMEOUT_S = 120.0
#: How much of an error body is threaded into the failure reason.
FAILURE_EXCERPT_MAX = 300

#: The description's length bound. Long enough for a real paragraph or three about a brand
#: that runs several looks; short enough that it stays a summary rather than becoming a spec.
MAX_PROSE_CHARS = 2400
#: A brand runs a handful of looks, not a dozen. Anything past this is the model listing
#: individual ads rather than recognising a group, which is the failure this cap absorbs.
MAX_STYLE_GROUPS = 6
#: A group's name is a label, not a sentence.
MAX_GROUP_NAME_CHARS = 80
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
class StyleGroup:
    """One described look, and the harvested creatives that show it.

    The name is free-form and comes from the model. It is a handle for a human and a match
    target for the turn-time reference selector — never a controlled vocabulary.
    """

    name: str
    creative_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdDnaCard:
    prose: str = ""
    style_groups: tuple[StyleGroup, ...] = ()
    model: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": CARD_SCHEMA_VERSION,
            "prose": self.prose,
            "style_groups": [
                {"name": group.name, "creative_ids": list(group.creative_ids)}
                for group in self.style_groups
            ],
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
    last_ungrouped: tuple[str, ...] = ()

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

    The DESCRIPTION is the card. Style groups are optional — a brand whose ads are all one look
    may honestly get none, and turn-time reference selection falls back to recency when that
    happens. A group with no name is dropped; a group whose creative ids are all unknown is
    kept, because the selector already skips ids it cannot resolve.
    """
    if not isinstance(payload, dict):
        return None
    raw_prose = payload.get("prose") or payload.get("description") or payload.get("notes")
    prose = str(raw_prose or "").strip()[:MAX_PROSE_CHARS]
    if not prose:
        return None

    groups: list[StyleGroup] = []
    raw_groups = payload.get("style_groups") or payload.get("groups") or []
    if isinstance(raw_groups, list):
        for entry in raw_groups[:MAX_STYLE_GROUPS]:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()[:MAX_GROUP_NAME_CHARS]
            if not name:
                continue
            raw_ids = entry.get("creative_ids") or entry.get("example_creative_ids") or []
            ids = tuple(
                str(item)
                for item in (raw_ids if isinstance(raw_ids, list) else [])
                if isinstance(item, (str, int))
            )[:MAX_DISTILLED_CREATIVES]
            groups.append(StyleGroup(name=name, creative_ids=ids))
    return AdDnaCard(prose=prose, style_groups=tuple(groups), model=model)


@dataclass
class OpenRouterAdDnaDistiller:
    """The multimodal distillation call. Never raises; a failure is a reason and a ``None``."""

    active: bool = field(init=False, default=False)
    model: str = field(init=False, default="")
    last_failure_reason: str | None = field(init=False, default=None)
    #: The creatives of the last distillation that no group holds, in the order they were shown.
    last_ungrouped: tuple[str, ...] = field(init=False, default=())

    def __post_init__(self) -> None:
        self.model = settings.lumen_ad_dna_model
        self._base_url = settings.openrouter_base_url
        self._api_key = settings.openrouter_api_key
        self.active = bool(settings.lumen_brand_ad_assets and self._api_key.strip())

    def distil(self, previews: list[CreativePreview]) -> AdDnaCard | None:
        self.last_failure_reason = None
        self.last_ungrouped = ()
        if not previews or not self.active:
            return None
        previews = previews[:MAX_DISTILLED_CREATIVES]
        cards: list[AdDnaCard] = []
        ungrouped: list[str] = []
        for start in range(0, len(previews), CREATIVES_PER_CALL):
            batch = previews[start : start + CREATIVES_PER_CALL]
            card, left_out = self._sort_batch(batch)
            if card is None:
                ungrouped.extend(preview.creative_id for preview in batch)
                continue
            cards.append(card)
            ungrouped.extend(left_out)
        if not cards:
            self.last_failure_reason = self.last_failure_reason or "the model described nothing"
            return None
        card = cards[0] if len(cards) == 1 else self._combine(cards, ungrouped)
        self.last_failure_reason = None
        self.last_ungrouped = tuple(ungrouped)
        return card

    def _sort_batch(self, batch: list[CreativePreview]) -> tuple[AdDnaCard | None, list[str]]:
        """One batch described and grouped, asked once more when an ad is not placed once."""
        shown = [preview.creative_id for preview in batch]
        note: str | None = None
        card: AdDnaCard | None = None
        for _attempt in range(2):
            payload = self._call(
                messages=_batch_messages(batch, note),
                schema_name="ad_dna_card",
                schema=_CARD_SCHEMA,
                label=f"ad_dna:{len(batch)} creatives",
            )
            if payload is None:
                break  # the call itself failed and its own retries are spent
            answer = bounded_card(payload, model=self.model)
            if answer is None:
                self.last_failure_reason = "the model described nothing"
                break
            card = answer
            gaps = _placement_gaps([group.creative_ids for group in card.style_groups], shown)
            if not any(gaps):
                return card, []
            note = _placement_note(*gaps, what="creative_id")
        if card is None:
            return None, shown
        groups, placed = _each_placed_once(
            [(group.name, group.creative_ids) for group in card.style_groups], shown
        )
        card = AdDnaCard(prose=card.prose, style_groups=groups, model=card.model)
        return card, [creative_id for creative_id in shown if creative_id not in placed]

    def _combine(self, cards: list[AdDnaCard], ungrouped: list[str]) -> AdDnaCard:
        """Several batches into one description and at most MAX_STYLE_GROUPS looks."""
        looks: dict[str, tuple[str, tuple[str, ...]]] = {}
        lines: list[str] = []
        for batch_number, card in enumerate(cards, start=1):
            lines += [f"Batch {batch_number} description:", card.prose, "", f"Batch {batch_number} looks:"]
            for look_number, group in enumerate(card.style_groups, start=1):
                key = f"{batch_number}.{look_number}"
                looks[key] = (group.name, group.creative_ids)
                lines.append(f"- key {key}: {group.name} ({len(group.creative_ids)} ads)")
            lines.append("")
        notes = "\n".join(lines)
        note: str | None = None
        answer: tuple[str, list[tuple[str, list[str]]]] | None = None
        for _attempt in range(2):
            parsed = _merge_answer(
                self._call(
                    messages=[
                        {"role": "system", "content": _MERGE_PROMPT},
                        {"role": "user", "content": notes + (f"\n{note}" if note else "")},
                    ],
                    schema_name="ad_dna_merge",
                    schema=_MERGE_SCHEMA,
                    label=f"ad_dna merge:{len(looks)} looks",
                )
            )
            if parsed is None:
                break
            answer = parsed
            gaps = _placement_gaps([keys for _, keys in parsed[1]], list(looks))
            if not any(gaps):
                break
            note = _placement_note(*gaps, what="batch look")
        if answer is None:
            return _union_of_batches(cards, ungrouped, model=self.model)
        prose, merged = answer
        named, placed = _each_placed_once(merged, list(looks))
        groups: list[StyleGroup] = []
        for group in named:
            creative_ids = tuple(
                creative_id for key in group.creative_ids for creative_id in looks[key][1]
            )
            if len(groups) < MAX_STYLE_GROUPS:
                groups.append(StyleGroup(name=group.name, creative_ids=creative_ids))
            else:
                ungrouped.extend(creative_ids)
        for key, (_, creative_ids) in looks.items():
            if key not in placed:
                ungrouped.extend(creative_ids)
        return AdDnaCard(prose=prose, style_groups=tuple(groups), model=self.model)

    def _call(self, *, messages: list[dict[str, Any]], schema_name: str, schema: dict, label: str) -> Any:
        """One strict-JSON chat call; the parsed answer, or ``None`` with a recorded reason."""
        from clue_spend import ProviderHalted
        from lumen_api import spend  # lazy: only the real network path needs it

        body = {
            "model": self.model,
            "messages": messages,
            # The response ENVELOPE is still schema-pinned, because parsing has to be reliable.
            # What the schema no longer does is dictate the CONTENT: `prose` is one free-text
            # field, and the only structure asked for is the group→creative_ids link.
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
        "they look like, then group them.\n\n" + manifest
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


def _placement_gaps(
    placed: list[tuple[str, ...]] | list[list[str]], expected: list[str]
) -> tuple[list[str], list[str], list[str]]:
    """(left out, in more than one group, never shown) for one answer's grouping."""
    counts: dict[str, int] = {}
    for ids in placed:
        for item in ids:
            counts[item] = counts.get(item, 0) + 1
    known = set(expected)
    missing = [item for item in expected if item not in counts]
    repeated = [item for item in expected if counts.get(item, 0) > 1]
    unknown = [item for item in counts if item not in known]
    return missing, repeated, unknown


def _placement_note(missing: list[str], repeated: list[str], unknown: list[str], *, what: str) -> str:
    parts = [f"Your previous answer did not place every {what} exactly once."]
    if missing:
        parts.append(f"Left out: {', '.join(missing)}.")
    if repeated:
        parts.append(f"In more than one group: {', '.join(repeated)}.")
    if unknown:
        parts.append(f"Not shown to you: {', '.join(unknown)}.")
    parts.append(f"Answer again, with every {what} in exactly one group.")
    return " ".join(parts)


def _each_placed_once(
    groups: list[tuple[str, Any]], expected: list[str]
) -> tuple[tuple[StyleGroup, ...], set[str]]:
    """Keep each expected item in the first group that names it; drop unknown items and empty groups."""
    known = set(expected)
    placed: set[str] = set()
    kept: list[StyleGroup] = []
    for name, items in groups:
        own = []
        for item in items:
            if item in known and item not in placed:
                placed.add(item)
                own.append(item)
        if own:
            kept.append(StyleGroup(name=name, creative_ids=tuple(own)))
    return tuple(kept), placed


def _merge_answer(payload: Any) -> tuple[str, list[tuple[str, list[str]]]] | None:
    """The combining call's prose and named looks, or ``None`` when it described nothing."""
    if not isinstance(payload, dict):
        return None
    prose = str(payload.get("prose") or "").strip()[:MAX_PROSE_CHARS]
    if not prose:
        return None
    looks: list[tuple[str, list[str]]] = []
    for entry in payload.get("style_groups") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()[:MAX_GROUP_NAME_CHARS]
        keys = entry.get("batch_looks") or []
        if name and isinstance(keys, list):
            looks.append((name, [str(key) for key in keys]))
    return prose, looks


def _union_of_batches(cards: list[AdDnaCard], ungrouped: list[str], *, model: str) -> AdDnaCard:
    """The combining call failed: the first batch's description and every batch's own looks,
    looks of the same name joined, at most MAX_STYLE_GROUPS of them."""
    by_name: dict[str, tuple[str, list[str]]] = {}
    for card in cards:
        for group in card.style_groups:
            name, ids = by_name.setdefault(group.name.lower(), (group.name, []))
            ids.extend(group.creative_ids)
    groups: list[StyleGroup] = []
    for name, ids in by_name.values():
        if len(groups) < MAX_STYLE_GROUPS:
            groups.append(StyleGroup(name=name, creative_ids=tuple(ids)))
        else:
            ungrouped.extend(ids)
    return AdDnaCard(prose=cards[0].prose, style_groups=tuple(groups), model=model)


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
    "language.\n\n"
    "Then group the creatives. Give each distinct look you described a short name a designer "
    "would recognise, and list the creative_ids that belong to it. The names are yours to "
    "choose. If the ads are all one look, that is one group with every id in it.\n\n"
    f"Put every creative_id in exactly one group, and use at most {MAX_STYLE_GROUPS} groups. "
    "If there are more looks than that, put the closest ones together."
)

_MERGE_PROMPT = (
    "You are reading notes about the static ads one brand actually published. The ads were "
    "looked at in batches, so each batch has its own description and its own named looks.\n\n"
    "Write one description of what this brand's ads look like, for a designer who is about to "
    "make a new ad for this brand and has never seen these ones. Keep what the batch "
    "descriptions say. Do not add anything they do not say. If the brand runs several looks "
    "that are clearly different from each other, describe each one.\n\n"
    "Write plainly. One idea per sentence. No jargon, no measurements, no marketing "
    "language.\n\n"
    "Then combine the batch looks into the brand's distinct looks. Batch looks that are the same "
    "look become one. Give each combined look a short name a designer would recognise, and list "
    "the keys of the batch looks it contains. Put every batch look in exactly one combined "
    f"look, and use at most {MAX_STYLE_GROUPS} combined looks. If there are more than that, "
    "put the closest ones together."
)

_MERGE_SCHEMA = {
    "type": "object",
    "properties": {
        "prose": {"type": "string"},
        "style_groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "batch_looks": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "batch_looks"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["prose", "style_groups"],
    "additionalProperties": False,
}

_CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "prose": {"type": "string"},
        "style_groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "creative_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "creative_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["prose", "style_groups"],
    "additionalProperties": False,
}
