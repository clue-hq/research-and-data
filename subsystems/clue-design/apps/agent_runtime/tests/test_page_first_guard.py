"""Editor Quality Plan 2, item C: the asset tools refuse on a pageless scene BEFORE spending.

Run `run_0452aae9…` fetched a logo and generated a hero image before any page existed; every
registration was refused by the engine (LUMV0100) AFTER the vendor/model had been paid. The
guard moves that refusal in front of the spend: a pageless scene costs one tool call, never an
image generation or a vendor request.
"""

from __future__ import annotations

import json
import types

import pytest

from agent_fixtures import FakeCoreClient, runtime_config
from lumen_agent.tools import logo_fetch
from lumen_agent.tools.substrate import PAGE_REQUIRED_CODE, LumenDesignTools


@pytest.fixture()
def tools(tmp_path, monkeypatch) -> LumenDesignTools:
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    return LumenDesignTools(runtime_config(tmp_path), "Make a LinkedIn ad")


def _give_page(tools: LumenDesignTools) -> None:
    """FakeCoreClient.compile_dsl_into_scene plants `page_test`; any source will do."""
    tools.compile_dsl_block("page page_test size(1080,1080,px)")
    assert tools.scene["pages"], "fixture must have planted a page"


def _install_counting_image_model(monkeypatch) -> dict:
    calls = {"n": 0}

    def fake_generate(**kwargs):
        calls["n"] += 1
        return types.SimpleNamespace(
            image_bytes=b"\x89PNG-generated-bytes",
            mime_type="image/png",
            model="test/image-model",
            provenance={"created_by": "agent", "source_label": "image generation", "notes": []},
        )

    stub = types.SimpleNamespace(
        is_configured=lambda: True,
        configured_model_id=lambda: "test/image-model",
        generate=fake_generate,
    )
    monkeypatch.setattr("lumen_agent.tools.substrate.image_provider", stub)
    return calls


def test_generate_image_refuses_on_a_pageless_scene_without_calling_the_model(tools, monkeypatch):
    calls = _install_counting_image_model(monkeypatch)
    assert tools.scene["pages"] == {}

    result = json.loads(tools.generate_image("a calm clinic reception"))

    assert result["status"] == "error"
    assert result["error_code"] == PAGE_REQUIRED_CODE == "scene.page_required"
    assert result["message"] == (
        "generate_image refused: the scene has no page/artboard yet, so nothing can be "
        "registered in it."
    )
    assert result["hint"] == (
        "Author the page first — compile_dsl_block with a `page <id> size(...)` line, the "
        "whole design in one block — then call generate_image again."
    )
    assert calls["n"] == 0, "the model must not be paid for a pageless scene"


def test_generate_image_calls_the_model_once_when_a_page_exists(tools, monkeypatch):
    calls = _install_counting_image_model(monkeypatch)
    _give_page(tools)

    result = json.loads(tools.generate_image("a calm clinic reception"))

    assert result["image"]["status"] == "ok"
    assert calls["n"] == 1


def test_generate_qr_refuses_on_a_pageless_scene_without_calling_the_core(tools, monkeypatch):
    calls = {"n": 0}

    def fake_generate_qr(**kwargs):
        calls["n"] += 1
        raise AssertionError("must not be reached on a pageless scene")

    monkeypatch.setattr(tools.core, "generate_qr", fake_generate_qr, raising=False)

    result = json.loads(tools.generate_qr("https://example.com"))

    assert result["status"] == "error"
    assert result["error_code"] == "scene.page_required"
    assert result["message"].startswith("generate_qr refused:")
    assert result["hint"].endswith("then call generate_qr again.")
    assert calls["n"] == 0


def test_fetch_logo_refuses_on_a_pageless_scene_without_calling_the_vendor(tools, monkeypatch):
    calls = {"n": 0}

    def fake_family(requested, **kwargs):
        calls["n"] += 1
        raise AssertionError("must not be reached on a pageless scene")

    monkeypatch.setattr(logo_fetch, "fetch_logo_family", fake_family)

    result = json.loads(tools.fetch_logo("ramp.com", "Ramp"))

    assert result["status"] == "error"
    assert result["error_code"] == "scene.page_required"
    assert result["message"].startswith("fetch_logo refused:")
    assert result["hint"].endswith("then call fetch_logo again.")
    assert calls["n"] == 0


def test_the_refusal_is_recorded_in_the_trace(tools, monkeypatch):
    _install_counting_image_model(monkeypatch)
    recorded: list[tuple] = []
    original = tools.record

    def spy(role, event, **kwargs):
        recorded.append((role, event, kwargs))
        return original(role, event, **kwargs)

    monkeypatch.setattr(tools, "record", spy)

    tools.generate_image("a hero")

    events = [event for _, event, _ in recorded]
    assert "generate_image_refused_pageless" in events
    payload = next(k for _, e, k in recorded if e == "generate_image_refused_pageless")["payload"]
    assert payload["error_code"] == "scene.page_required"
