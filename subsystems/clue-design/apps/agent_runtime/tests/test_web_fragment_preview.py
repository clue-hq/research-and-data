"""The agent's in-loop preview renders cloned sections too (clone-fidelity F1.3).

A fragment that renders in the editor and vanishes from the agent's screenshot is a specific,
nasty failure: the visual reviewer judges a page with a hole in it, the author "fixes" the hole,
and the fix is nonsense. The two preview paths therefore thread the SAME two things into
``core.web_render`` — the artifact map and the concatenated scoped CSS — and this file pins the
agent half.

The runtime never reads the API database (the rule ``asset_library`` already follows), so the
package arrives BY VALUE in the turn config. These tests build one by hand, exactly as
``run_web_agent_turn`` does at composition, and then render through the real engine.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools.web_substrate import LumenWebTools

REPO_ROOT = Path(__file__).resolve().parents[3]

FRAGMENT_ID = "frag_0123456789abcdef"
WRAPPER = "lumen-frag-0123456789abcdef"
SENTINEL = "Care, on your terms"
FRAGMENT_HTML = (
    f'<section class="clone-hero"><h1 data-lumen-slot="headline">{SENTINEL}</h1></section>'
)
FRAGMENT_CSS = f".{WRAPPER} .clone-hero {{ padding: 64px }}"


def _package(slot_kinds: dict | None = None) -> dict:
    return {
        "schema_version": 1,
        "fragments": {
            FRAGMENT_ID: {
                "html": FRAGMENT_HTML,
                "css": FRAGMENT_CSS,
                "slot_kinds": dict(slot_kinds or {}),
            }
        },
        "missing": [],
    }


def _seed(*, with_fragment: bool = True, slots: dict | None = None) -> dict:
    nodes: dict = {
        "root": {
            "id": "root",
            "kind": "container",
            "classes": "",
            "new_tab": False,
            "children": ["frg_hero"] if with_fragment else [],
        }
    }
    if with_fragment:
        nodes["frg_hero"] = {
            "id": "frg_hero",
            "kind": "fragment",
            "classes": "w-full py-12",
            "fragment_id": FRAGMENT_ID,
            "slots": dict(slots or {}),
        }
    return {
        "schema_version": 1,
        "id": "doc_web_fragment",
        "title": "Test site",
        "theme": {},
        "custom_css": "",
        "pages": [
            {"id": "home", "name": "Home", "route": "/", "root": "root", "nodes": nodes}
        ],
        "assets": {},
    }


def _tools(
    tmp_path: Path,
    *,
    with_fragment: bool = True,
    package: dict | None = None,
    slots: dict | None = None,
):
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        fragment_render_package=package,
    )
    return LumenWebTools(
        config,
        "Build a page",
        initial_web_doc=_seed(with_fragment=with_fragment, slots=slots),
    )


def _captured_render_kwargs(tools) -> dict:
    """The kwargs `render_web_preview` hands the engine.

    Raising out of `web_render` is the cheapest capture point: the tool returns its error
    envelope, so nothing reaches Playwright and the test stays hermetic (the pattern
    `test_web_asset_base_url` established).
    """
    from lumen_api.core import CoreError

    captured: dict = {}
    real_core = tools.core

    class _RecordingCore:
        def __getattr__(self, name):
            return getattr(real_core, name)

        def web_render(self, *args, **kwargs):
            captured.update(kwargs)
            captured["_args"] = args
            raise CoreError("test.stop", "stop here — the kwargs are what this test judges")

    tools.core = _RecordingCore()
    result = json.loads(tools.render_web_preview())
    assert result["status"] == "error"
    tools.core = real_core
    return captured


def _replay(tools, captured: dict) -> dict:
    """Re-run the captured call against the REAL engine — the same doc, the same kwargs."""
    kwargs = {key: value for key, value in captured.items() if key != "_args"}
    return tools.core.web_render(*captured["_args"], **kwargs)


def test_the_config_carries_the_resolved_package_by_value():
    """The runtime is fleet work with no database handle; the API resolves, the config carries."""
    config = AgentRuntimeConfig.from_env(REPO_ROOT)
    assert "fragment_render_package" in set(config.__dataclass_fields__)
    assert config.fragment_render_package is None


def test_the_preview_render_is_handed_the_artifact_map_and_the_scoped_sheet(tmp_path: Path):
    tools = _tools(tmp_path, package=_package())
    captured = _captured_render_kwargs(tools)
    # Markup plus the slot kinds the engine cannot know on its own (F1.4).
    assert captured["fragments"] == {
        FRAGMENT_ID: {"html": FRAGMENT_HTML, "slot_kinds": {}}
    }
    assert FRAGMENT_CSS in captured["fragment_css"]
    assert f"/* fragment {FRAGMENT_ID} */" in captured["fragment_css"]


def test_the_agent_preview_actually_renders_the_cloned_section(tmp_path: Path):
    """Through the real engine, with the real kwargs the tool composes."""
    tools = _tools(tmp_path, package=_package())
    captured = _captured_render_kwargs(tools)
    html = _replay(tools, captured).get("html") or ""

    assert f'<div class="lumen-fragment {WRAPPER} w-full py-12"' in html
    assert SENTINEL in html
    css_at = html.index(FRAGMENT_CSS)
    assert css_at < html.index("</head>"), "scoped CSS belongs in the head"


def test_the_agent_preview_substitutes_a_bound_slot_like_the_editor_does(tmp_path: Path):
    """F1.4 on the second preview path. A section that personalizes in the editor and shows the
    clone's own words in the agent's screenshot would have the agent iterating against a page no
    visitor ever sees."""
    tools = _tools(
        tmp_path,
        package=_package({"headline": "text"}),
        slots={"headline": {"text": "Talk to us"}},
    )
    captured = _captured_render_kwargs(tools)
    assert captured["fragments"][FRAGMENT_ID]["slot_kinds"] == {"headline": "text"}

    html = _replay(tools, captured).get("html") or ""
    assert '<h1 data-lumen-slot="headline">Talk to us</h1>' in html
    assert SENTINEL not in html


def test_a_turn_with_no_fragment_package_renders_exactly_as_before(tmp_path: Path):
    tools = _tools(tmp_path, with_fragment=False, package=None)
    captured = _captured_render_kwargs(tools)
    assert captured["fragments"] == {}
    assert captured["fragment_css"] is None


def test_a_fragment_the_turn_could_not_resolve_still_renders_a_page(tmp_path: Path):
    """The dead-pin promise holds on this path too: a placeholder and a loud diagnostic, never a
    failed render."""
    tools = _tools(tmp_path, package={"schema_version": 1, "fragments": {}, "missing": [FRAGMENT_ID]})
    captured = _captured_render_kwargs(tools)
    assert captured["fragments"] == {}
    response = _replay(tools, captured)
    html = response.get("html") or ""
    assert 'data-fragment-placeholder="true"' in html
    assert SENTINEL not in html
    codes = [diagnostic["code"] for diagnostic in response.get("diagnostics") or []]
    assert "LUMW0412" in codes


def test_a_node_added_mid_turn_that_the_package_never_saw_degrades_rather_than_lies(
    tmp_path: Path,
):
    """The package is resolved once, at composition. Anything the doc gains afterwards that the
    package does not carry renders the placeholder — the map is never improvised into."""
    tools = _tools(tmp_path, package=_package())
    page = tools.web_doc["pages"][0]
    page["nodes"]["frg_two"] = {
        "id": "frg_two",
        "kind": "fragment",
        "classes": "",
        "fragment_id": "frag_fedcba9876543210",
    }
    page["nodes"]["root"]["children"] = ["frg_hero", "frg_two"]
    captured = _captured_render_kwargs(tools)
    assert set(captured["fragments"]) == {FRAGMENT_ID}
    response = _replay(tools, captured)
    assert 'data-fragment-placeholder="true"' in (response.get("html") or "")


def test_a_package_from_a_shape_this_worker_does_not_know_is_refused_not_improvised(
    tmp_path: Path,
):
    """F1.5: the package's `schema_version` finally MEANS something.

    It was written and never read — a number nobody checked. The shape it guards is real: the
    package travels by value inside a turn's config, so a worker draining a queue can be running
    older code than the API that built the package. Reading a newer shape with older rules is
    exactly the "improvise" this project refuses everywhere else, so the map is dropped whole:
    the page renders placeholders (loud, LUMW0412) and a diagnostic names the two versions.
    """
    tools = _tools(tmp_path, package={**_package(), "schema_version": 999})

    captured = _captured_render_kwargs(tools)
    assert captured["fragments"] == {}
    assert captured["fragment_css"] is None

    response = _replay(tools, captured)
    assert SENTINEL not in (response.get("html") or "")
    assert 'data-fragment-placeholder="true"' in (response.get("html") or "")

    diagnostics = tools._fragment_diagnostics()
    assert any(
        diagnostic["code"] == "fragment.package_schema_unknown"
        and "999" in diagnostic["message"]
        for diagnostic in diagnostics
    ), diagnostics


def test_a_package_of_the_known_shape_is_read_normally(tmp_path: Path):
    """The guard must not fire on the shape it was written for."""
    tools = _tools(tmp_path, package=_package())
    assert set(_captured_render_kwargs(tools)["fragments"]) == {FRAGMENT_ID}
    assert not [
        diagnostic
        for diagnostic in tools._fragment_diagnostics()
        if diagnostic["code"] == "fragment.package_schema_unknown"
    ]


# --------------------------------------------------------------------------- #
# The artifact's OWN bytes in the agent's preview (phase fix wave, FIX 1)
# --------------------------------------------------------------------------- #

OWNED_DIGEST = "ab" * 32
OWNED_HTML = (
    '<section class="clone-hero">'
    f'<img class="clone-art" src="/asset-store/{OWNED_DIGEST}" alt="">'
    f'<h1 data-lumen-slot="headline">{SENTINEL}</h1></section>'
)
OWNED_CSS = (
    f'.{WRAPPER} .clone-hero {{ background-image: url("/asset-store/{OWNED_DIGEST}") }}'
)


def _owned_package() -> dict:
    return {
        "schema_version": 1,
        "fragments": {
            FRAGMENT_ID: {
                "html": OWNED_HTML,
                "css": OWNED_CSS,
                "slot_kinds": {},
                "asset_digests": [OWNED_DIGEST],
            }
        },
        "missing": [],
    }


def test_the_agents_preview_fetches_an_artifacts_own_image_from_the_asset_origin(
    tmp_path: Path,
):
    """The walk caught this in PIXELS: every image inside a cloned section was broken in the
    screenshots a reviewer judges.

    Playwright renders through `set_content`, which has no document origin, so the artifact's
    stored root-relative `/asset-store/<digest>` resolved against nothing. A slot-bound asset
    went through the engine's `asset_base_url` and was always fine — which is precisely how the
    broken class hid: the one asset kind anybody probed was the one that worked.
    """
    tools = _tools(tmp_path, package=_owned_package())
    captured = _captured_render_kwargs(tools)

    base = tools.asset_base_url.rstrip("/")
    assert f'src="{base}/{OWNED_DIGEST}"' in captured["fragments"][FRAGMENT_ID]["html"]
    assert f'url("{base}/{OWNED_DIGEST}")' in captured["fragment_css"]
    assert f'src="/asset-store/{OWNED_DIGEST}"' not in captured["fragments"][FRAGMENT_ID]["html"]

    # …and the real engine emits what it was handed, so the page carries the fetchable URL.
    response = _replay(tools, captured)
    assert f"{base}/{OWNED_DIGEST}" in (response.get("html") or "")


def test_the_preflight_probes_an_artifact_owned_reference_not_just_a_slot_asset(
    tmp_path: Path,
):
    """The probe must cover the class that broke.

    The preflight proved the asset ORIGIN serves bytes by building `{base}/{digest}` itself —
    which is exactly the URL the rebase produces, so it answered 200 whether or not the render
    map had been rebased at all. It could never have caught this. It now probes the reference as
    it ACTUALLY APPEARS in the markup this turn will render, so an un-rebased artifact reference
    is a loud finding rather than a green light.
    """
    tools = _tools(tmp_path, package=_owned_package())
    urls = tools._fragment_asset_probe_urls()
    assert urls == [f"{tools.asset_base_url.rstrip('/')}/{OWNED_DIGEST}"]

    # The red state — the bug this wave fixed — is recognised as unfetchable rather than probed.
    assert tools._unfetchable_probe_urls([f"/asset-store/{OWNED_DIGEST}"]) == [
        f"/asset-store/{OWNED_DIGEST}"
    ]
    assert tools._unfetchable_probe_urls(urls) == []
