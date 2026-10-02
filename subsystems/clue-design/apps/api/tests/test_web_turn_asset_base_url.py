"""The web-turn execution path hands the agent a live asset origin.

A web turn is leased FLEET work: it runs in a detached worker with no HTTP
request, so unlike the editor's render route it cannot derive an asset base URL
from ``request.base_url``. Until 2026-08-20 nothing supplied one and the agent
substrate fell back to a hardcoded loopback URL on a port the design API stopped
using — every ``<img data-asset=…>`` in the agent's OWN preview screenshots
404'd, so the agent stripped the imagery it had placed. These tests pin the
boundary: whatever config reaches ``run_deepagent_web_turn`` carries the
configured base, and a turn with none refuses loudly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from py_lumen_config import settings

from lumen_api import main as main_mod


class _StubBlobs:
    """The tenant byte store, stubbed: brand-kit resolution is wrapped in a
    try/except that degrades to the default kit, so a workspace id is enough."""

    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id


@pytest.fixture()
def _captured_turn(monkeypatch: pytest.MonkeyPatch) -> dict:
    captured: dict = {}

    import lumen_agent.harness_web as harness_web
    import lumen_agent.llm as agent_llm

    def _fake_turn(
        *,
        prompt,
        config,
        initial_web_doc,
        event_sink,
        checkpointer,
        thread_id,
        cancel_requested=None,
        callbacks=None,
    ):
        captured["config"] = config
        return {
            "status": "applied",
            "outcome": "completed",
            "summary": "stubbed",
            "web_doc": initial_web_doc,
            "operations": [],
        }

    monkeypatch.setattr(harness_web, "run_deepagent_web_turn", _fake_turn)
    monkeypatch.setattr(
        agent_llm, "assert_model_supports_image_input", lambda *a, **k: None
    )
    return captured


def _run(tmp_path: Path, captured: dict) -> dict:
    return main_mod.run_web_agent_turn(
        {"scene": {"schema_version": 1, "id": "doc_x", "theme": {}, "pages": [], "assets": {}}},
        "Build a landing page",
        None,
        Path(__file__).resolve().parents[3],
        workspace_id="ws_test_asset_base_url",
        blobs=_StubBlobs("ws_test_asset_base_url"),
        engine_cache_root=tmp_path / "engine-cache",
    )


def test_the_web_turn_hands_the_agent_the_configured_asset_base_url(
    tmp_path: Path, _captured_turn: dict
):
    response = _run(tmp_path, _captured_turn)

    assert response["status"] == "applied", response
    config = _captured_turn["config"]
    assert config.asset_base_url == settings.asset_base_url
    assert config.asset_base_url.endswith("/asset-store")


def test_the_asset_base_url_is_never_the_port_the_api_abandoned(
    tmp_path: Path, _captured_turn: dict
):
    """The whole defect: the substrate's hardcoded fallback named port 8000,
    which nothing has served since the design API moved to 8010."""
    _run(tmp_path, _captured_turn)

    assert ":8000" not in _captured_turn["config"].asset_base_url


def test_a_turn_with_no_asset_base_url_refuses_instead_of_rendering_broken_images(
    tmp_path: Path, _captured_turn: dict, monkeypatch: pytest.MonkeyPatch
):
    """An unreachable origin is warned about and survived (that is the agent's
    preflight); an ABSENT one is a misconfiguration and fails the turn honestly
    rather than producing a page with every image silently stripped."""
    from dataclasses import replace as dc_replace

    from lumen_agent.config import AgentRuntimeConfig

    real_from_env = AgentRuntimeConfig.from_env
    monkeypatch.setattr(
        AgentRuntimeConfig,
        "from_env",
        classmethod(
            lambda cls, root=None: dc_replace(real_from_env(root), asset_base_url=None)
        ),
    )

    response = _run(tmp_path, _captured_turn)

    assert response["status"] == "failed", response
    assert "config" not in _captured_turn
    assert "asset_base_url" in str(response)


# --- the two paths that were already correct and must stay untouched --------


def test_the_editor_render_route_still_derives_its_base_from_the_request():
    """An HTTP render knows its own origin; the setting is only for off-request
    consumers. Changing this to the setting would break every deployment served
    on a host the config does not name."""
    source = Path(main_mod.__file__).read_text()
    assert 'asset_base_url = str(request.base_url).rstrip("/") + "/asset-store"' in source


def test_the_export_paths_still_use_their_own_relative_and_same_origin_bases():
    """A ZIP export resolves images from a sibling `assets/` directory and a
    publish payload from the serving origin's own `/asset-store`. Neither wants
    an absolute dev-stack URL baked in."""
    from lumen_api import web_export

    source = Path(web_export.__file__).read_text()
    # F5 multi-page export (Task 11): the ZIP base gained the per-page relative
    # hop `prefix` ("" for the root `index.html`, "../" for a `<route>/index.html`
    # subpage), so each page still resolves its own sibling `assets/` folder.
    assert 'asset_base_url=f"{prefix}assets"' in source
    assert 'asset_base_url="/asset-store"' in source
