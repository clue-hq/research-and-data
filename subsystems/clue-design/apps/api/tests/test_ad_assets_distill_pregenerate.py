"""Distillation bounds and pre-generation discipline (Brand Ad Assets v1, W2).

No network, no database, no engine — both modules take their model call as a seam.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from lumen_ingestion.ad_library.distill import (
    CARD_SCHEMA_VERSION,
    MAX_PROSE_CHARS,
    NullAdDnaDistiller,
    bounded_card,
    resolve_distiller,
)
from lumen_ingestion.ad_library.distill import _CARD_SCHEMA as CARD_SCHEMA
from lumen_ingestion.ad_library.distill import _SYSTEM_PROMPT as DISTILL_PROMPT
from lumen_ingestion.ad_library.pregenerate import (
    BACKGROUND_ONLY_CLAUSE,
    MAX_REFERENCE_IMAGES,
    PROSE_IN_PROMPT_CHARS,
    background_prompt_for,
    pregenerate_for_card,
)

PROSE = (
    "Most of these ads are one flat deep-green field with nothing behind the type. "
    "The headline is heavy and sits on the left. A lime accent shows up once, on the "
    "button, and nowhere else. The logo sits bottom left, reversed out of the green."
)


def _group(name: str, **overrides: Any) -> dict:
    base: dict[str, Any] = {"name": name, "creative_ids": ["adcre_a", "adcre_b"]}
    base.update(overrides)
    return base


def _card_payload(**overrides: Any) -> dict:
    base: dict[str, Any] = {"prose": PROSE, "style_groups": [_group("Deep Green")]}
    base.update(overrides)
    return base


# --- the card's shape and bounds -------------------------------------------------------------


def test_a_well_formed_payload_becomes_a_stamped_prose_card() -> None:
    """Founder rulings 2026-08-26 and 2026-10-30: the card is a DESCRIPTION, and no ad is
    grouped any more. ``style_groups`` stays in the payload, always empty, so stored cards keep
    their version-2 shape."""
    card = bounded_card(_card_payload())
    assert card is not None
    payload = card.to_json()
    assert payload["schema_version"] == CARD_SCHEMA_VERSION == 2
    assert payload["prose"] == PROSE
    assert payload["style_groups"] == []
    # The five-field taxonomy is gone, not merely unused.
    assert "visual_systems" not in payload
    for retired in ("layout_skeleton", "ground_treatment", "accent_spend", "type_feel"):
        assert retired not in json.dumps(payload)


def test_the_prose_is_truncated_to_the_bound() -> None:
    """A card rides every ad turn's opening context; an unbounded one is a permanent tax."""
    card = bounded_card(_card_payload(prose="x" * (MAX_PROSE_CHARS * 3)))
    assert card is not None
    assert len(card.prose) == MAX_PROSE_CHARS


def test_a_card_that_describes_nothing_is_none_not_an_empty_card() -> None:
    """RED CASE. An empty card recorded as a version tells every later turn that this brand's
    ads look like nothing in particular — a confident lie about a distillation that failed."""
    assert bounded_card({"prose": "", "style_groups": [_group("Deep Green")]}) is None
    assert bounded_card({"prose": "   ", "style_groups": []}) is None
    assert bounded_card({"style_groups": [_group("Deep Green")]}) is None
    assert bounded_card("not a payload") is None
    assert bounded_card(None) is None


# --- the vision prompt -----------------------------------------------------------------------


def test_the_vision_prompt_asks_for_a_description_and_not_a_form() -> None:
    """RED CASE for the ruling: a field-by-field ask makes the model answer questions the ads
    may not answer, and a confidently-filled empty field is worse than an honest sentence."""
    assert "in your own plain words" in DISTILL_PROMPT
    assert "Do not invent a rule the ads do not show you." in DISTILL_PROMPT
    # The coverage nudge is present AND explicitly soft.
    for nudge in ("how an ad is laid out", "how colour behaves", "what the imagery is like"):
        assert nudge in DISTILL_PROMPT
    assert "Treat that as a nudge, not a checklist." in DISTILL_PROMPT


def test_the_response_schema_pins_the_envelope_and_no_longer_pins_the_content() -> None:
    """RED CASE for the ruling, at the place it was actually enforced. Parsing still needs a
    schema; what the schema must NOT do any more is make five named fields mandatory — a
    required field is exactly what forces a confident answer to a question the ads never
    asked. ``prose`` is one free-text field and the only one (no group link since 2026-10-30)."""
    assert set(CARD_SCHEMA["required"]) == {"prose"}
    assert CARD_SCHEMA["properties"] == {"prose": {"type": "string"}}
    for retired in ("layout_skeleton", "ground_treatment", "accent_spend", "type_feel"):
        assert retired not in json.dumps(CARD_SCHEMA)


# --- the distiller seam ----------------------------------------------------------------------


def test_the_null_distiller_reads_as_not_attempted() -> None:
    """OFF is OFF — never N failures. ``active`` is what the job's step reporting keys on."""
    distiller = NullAdDnaDistiller()
    assert distiller.active is False
    assert distiller.distil([]) is None


def test_the_flag_gates_the_distiller_even_with_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED CASE: no code path may reach a model call with the lane switched off."""
    from py_lumen_config import settings

    monkeypatch.setattr(settings, "openrouter_api_key", "a-key", raising=False)
    monkeypatch.setattr(settings, "lumen_brand_ad_assets", False, raising=False)
    assert resolve_distiller().active is False

    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    assert resolve_distiller().active is True

    # A live flag with no key is still off — the same rule the describer has.
    monkeypatch.setattr(settings, "openrouter_api_key", "  ", raising=False)
    assert resolve_distiller().active is False


# --- pre-generation prompts ------------------------------------------------------------------


def test_every_prompt_is_background_only() -> None:
    """RED CASE: a generated ground with baked-in type is a ground the engine cannot use."""
    prompt = background_prompt_for(
        _group("Deep Green"), prose=PROSE, shape_label="wide ground", brand_name="Ramp"
    )
    assert BACKGROUND_ONLY_CLAUSE in prompt
    for forbidden in ("No text", "no logo", "no people", "no user interface"):
        assert forbidden in prompt


def test_the_prompt_is_anchored_in_the_cards_own_description() -> None:
    """Generation conditioned on what the brand's ads actually look like, not on a typed
    adjective — the prose IS the substance now that the five-field taxonomy is gone."""
    prompt = background_prompt_for(
        _group("Deep Green"), prose=PROSE, shape_label="square ground", brand_name="Ramp"
    )
    assert "one flat deep-green field" in prompt
    assert "A lime accent shows up once" in prompt
    assert "Ramp" in prompt
    assert "Deep Green" in prompt


def test_the_prose_riding_an_image_prompt_is_bounded_separately() -> None:
    """An agent's opening-context budget is not an image model's prompt budget: past a
    paragraph or two an image prompt stops steering and starts averaging."""
    prompt = background_prompt_for(
        _group("Deep Green"),
        prose="z" * (PROSE_IN_PROMPT_CHARS * 4),
        shape_label="wide ground",
        brand_name=None,
    )
    assert prompt.count("z") == PROSE_IN_PROMPT_CHARS


# --- pre-generation mechanics ----------------------------------------------------------------


@dataclass
class _Generated:
    image_bytes: bytes
    mime_type: str = "image/png"
    model: str = "test/image-model"
    provenance: dict | None = None
    license: dict | None = None
    width: int | None = 1920
    height: int | None = 1080
    aspect_ratio_honored: bool | None = True


class _FakeCore:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def ingest_asset(self, store_root: str, bytes_base64: str, asset_id: str, label: str, **kw: Any):
        self.calls.append({"asset_id": asset_id, "label": label, **kw})
        return {"asset": {"record": {"id": asset_id, "label": label, "media": {}}}}


def _generator(calls: list[dict[str, Any]]):
    counter = {"n": 0}

    def generate(**kwargs: Any) -> _Generated:
        counter["n"] += 1
        calls.append(kwargs)
        return _Generated(image_bytes=b"\x89PNG\r\n\x1a\n" + str(counter["n"]).encode())

    return generate


def test_each_named_system_gets_its_own_bounded_set_of_assets() -> None:
    card = _card_payload(style_groups=[_group("A"), _group("B")])
    calls: list[dict[str, Any]] = []

    outcome = pregenerate_for_card(
        card,
        core=_FakeCore(),
        cache_dir="/tmp/engine-cache",
        generate=_generator(calls),
        assets_per_system=2,
    )

    assert len(outcome.assets) == 4
    assert {asset.visual_system for asset in outcome.assets} == {"A", "B"}
    assert [call["aspect_ratio"] for call in calls] == ["16:9", "1:1", "16:9", "1:1"]
    links = outcome.links()
    assert all(link["visual_system"] and link["prompt"] for link in links)


def test_the_harvested_creatives_condition_the_generation_and_are_capped() -> None:
    calls: list[dict[str, Any]] = []
    references = [(b"ref%d" % n, "image/png") for n in range(MAX_REFERENCE_IMAGES + 3)]

    pregenerate_for_card(
        _card_payload(style_groups=[_group("A")]),
        core=_FakeCore(),
        cache_dir="/tmp/engine-cache",
        generate=_generator(calls),
        reference_images=references,
        assets_per_system=1,
    )

    assert len(calls[0]["reference_images"]) == MAX_REFERENCE_IMAGES


def test_one_failed_generation_does_not_lose_the_others() -> None:
    """RED CASE: a provider hiccup mid-pre-generation must cost one asset, not the lane."""
    calls: list[dict[str, Any]] = []
    good = _generator(calls)

    def generate(**kwargs: Any) -> _Generated:
        if kwargs.get("aspect_ratio") == "1:1":
            raise RuntimeError("provider exploded")
        return good(**kwargs)

    outcome = pregenerate_for_card(
        _card_payload(style_groups=[_group("A"), _group("B")]),
        core=_FakeCore(),
        cache_dir="/tmp/engine-cache",
        generate=generate,
        assets_per_system=2,
    )

    assert len(outcome.assets) == 2
    assert [target for target, _reason in outcome.failures] == ["A:1:1", "B:1:1"]


def test_a_text_only_reply_is_recorded_rather_than_registered() -> None:
    """The provider's own no_image retry is upstream; an empty result still must not
    become a zero-byte asset row."""

    def generate(**kwargs: Any) -> _Generated:
        return _Generated(image_bytes=b"")

    outcome = pregenerate_for_card(
        _card_payload(style_groups=[_group("A")]),
        core=_FakeCore(),
        cache_dir="/tmp/engine-cache",
        generate=generate,
        assets_per_system=1,
    )
    assert outcome.assets == []
    assert outcome.failures == [("A:16:9", "image_model.no_image")]


def test_an_asset_already_in_the_generation_ledger_is_reused_without_paying_again() -> None:
    """RED CASE: without the pre-spend probe, a re-offered job re-pays for every asset.

    Every generated image has different bytes and therefore a different content-derived asset
    id, so byte-level dedup cannot save a retry — only the ledger key can, and only if it is
    consulted BEFORE the provider call.
    """
    calls: list[dict[str, Any]] = []
    claimed = {"asset": {"id": "asset_gen_already_here", "media": {}}}

    outcome = pregenerate_for_card(
        _card_payload(style_groups=[_group("A")]),
        core=_FakeCore(),
        cache_dir="/tmp/engine-cache",
        generate=_generator(calls),
        assets_per_system=1,
        generation_key_for=lambda **kwargs: "ledger-key",
        find_generated=lambda key: claimed if key == "ledger-key" else None,
    )

    assert calls == [], "the model must not be called when the ledger already holds the asset"
    assert [asset.asset_id for asset in outcome.assets] == ["asset_gen_already_here"]
    assert outcome.assets[0].generation["reused_from_generation_ledger"] is True
    # A re-used asset is already registered; it must not claim the key a second time.
    assert outcome.assets[0].generation_key is None


def test_a_ledger_miss_still_generates_and_carries_the_key_for_the_claim() -> None:
    calls: list[dict[str, Any]] = []
    outcome = pregenerate_for_card(
        _card_payload(style_groups=[_group("A")]),
        core=_FakeCore(),
        cache_dir="/tmp/engine-cache",
        generate=_generator(calls),
        assets_per_system=1,
        generation_key_for=lambda **kwargs: "ledger-key",
        find_generated=lambda key: None,
    )
    assert len(calls) == 1
    assert outcome.assets[0].generation_key == "ledger-key"


def test_the_real_returned_dimensions_are_recorded_not_the_requested_ones() -> None:
    """W1.7(b): a caller must never be misled by its own ask."""
    calls: list[dict[str, Any]] = []

    def generate(**kwargs: Any) -> _Generated:
        del kwargs
        return _Generated(
            image_bytes=b"\x89PNG\r\n\x1a\nx", width=1024, height=1024, aspect_ratio_honored=False
        )

    outcome = pregenerate_for_card(
        _card_payload(style_groups=[_group("A")]),
        core=_FakeCore(),
        cache_dir="/tmp/engine-cache",
        generate=generate,
        assets_per_system=1,
    )
    generation = outcome.assets[0].generation
    assert generation["aspect_ratio"] == "16:9"
    assert (generation["width"], generation["height"]) == (1024, 1024)
    assert generation["aspect_ratio_honored"] is False
    assert calls == []
