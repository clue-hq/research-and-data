"""LumenWebTools unit coverage.

Two layers: pure-Python token-name derivation (no helper), and the
author_web_page happy path against the REAL core helper (deterministic — HTML
ingest only, no LLM or browser).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools import web_substrate as ws
from lumen_agent.tools.web_substrate import (
    _MAX_DIALOG_CAPTURES,
    LumenWebTools,
    _interactive_capture_plan,
    sanitize_token_name,
    web_theme_token_names,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

SAMPLE_HTML = """
<header id="site_header" class="bg-light border-b border-border">
  <div class="mx-auto max-w-[1200px] px-6 py-4 flex items-center justify-between">
    <p data-variant="overline" class="text-primary">Acme</p>
    <a data-button="primary" href="https://acme.test/demo">Get started</a>
  </div>
</header>
<section id="hero" class="bg-light">
  <div class="mx-auto max-w-[1200px] px-6 py-24 flex flex-col items-center gap-6 text-center">
    <h1 data-variant="display" class="max-w-[820px]">Ship faster with Acme</h1>
    <p class="text-muted max-w-[640px]">Acme helps teams build and launch quickly.</p>
    <a data-button="primary" href="https://acme.test/demo">Get started</a>
  </div>
</section>
<footer id="site_footer" class="bg-dark">
  <div class="mx-auto max-w-[1200px] px-6 py-12 flex items-center justify-between">
    <p data-variant="small" class="text-inverse">Acme</p>
  </div>
</footer>
"""


# --- pure token-name derivation --------------------------------------------


def test_sanitize_token_name_mirrors_rust_rule():
    assert sanitize_token_name("Surface.Brand") == "surface-brand"
    assert sanitize_token_name("palette.primary.500") == "palette-primary-500"
    assert sanitize_token_name("Neutral_50") == "neutral-50"
    assert sanitize_token_name("--primary--") == "primary"
    # Non [a-z0-9-] characters are dropped entirely.
    assert sanitize_token_name("acc€nt!") == "accnt"
    assert sanitize_token_name("  ...  ") == ""


def test_web_theme_token_names_semantic_only_without_kit():
    assert (
        web_theme_token_names(None)
        == "primary accent dark light card muted border inverse"
    )


def test_web_theme_token_names_appends_sanitized_kit_colors():
    kit = {
        "tokens": {
            "colors": {
                # a duplicate of a semantic name is not repeated
                "primary": {},
                "Surface.Brand": {},
                "palette.primary.500": {},
            }
        }
    }
    names = web_theme_token_names(kit).split()
    # Semantic eight come first, in order.
    assert names[:8] == [
        "primary",
        "accent",
        "dark",
        "light",
        "card",
        "muted",
        "border",
        "inverse",
    ]
    assert "surface-brand" in names
    assert "palette-primary-500" in names
    # "primary" appears exactly once (semantic; the kit dup is skipped).
    assert names.count("primary") == 1


# --- author_web_page against the real helper --------------------------------


def _tools(tmp_path: Path) -> LumenWebTools:
    from lumen_api.core import CoreClient

    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT), trace_dir=tmp_path / "workspace_root"
    )
    core = CoreClient(repo_root=REPO_ROOT)
    seed = core.web_new_doc("doc_web_test", "Test site", None)["web_doc"]
    return LumenWebTools(config, "Build a page", initial_web_doc=seed)


def test_author_web_page_installs_sections(tmp_path: Path):
    tools = _tools(tmp_path)
    result = json.loads(tools.author_web_page(SAMPLE_HTML))
    assert result["status"] == "ok", result
    # header + hero + footer + their descendants.
    assert result["installed_nodes"] >= 3
    # The working doc now carries the three top-level sections.
    page = tools._home_page()
    root = (page.get("nodes") or {}).get(page.get("root")) or {}
    assert set(root.get("children") or []) == {"site_header", "hero", "site_footer"}
    # A mutation bumps the doc version (drives view staleness).
    assert tools._doc_version == 1


def test_author_web_page_rejects_raw_hex(tmp_path: Path):
    tools = _tools(tmp_path)
    before = tools._doc_version
    # A raw hex color is a hard lint error → the whole page is rejected.
    result = json.loads(
        tools.author_web_page('<section id="s"><div class="bg-[#ff0000]"><p>x</p></div></section>')
    )
    assert result["status"] == "rejected", result
    assert any(d.get("severity") == "error" for d in result["diagnostics"])
    # Nothing stored: the working doc and version are untouched.
    assert tools._doc_version == before
    assert not (tools._home_page().get("nodes") or {}).get("s")


# --- author_web_subtree (scoped edits) against the real helper --------------

TWO_SECTION_HTML = """
<section id="alpha" class="bg-light">
  <div class="mx-auto max-w-[1200px] px-6 py-24 flex flex-col gap-6">
    <h1 data-variant="display" id="alpha_title">Alpha heading</h1>
    <p class="text-muted" id="alpha_body">Alpha body copy.</p>
  </div>
</section>
<section id="beta" class="bg-card">
  <div class="mx-auto max-w-[1200px] px-6 py-24 flex flex-col gap-6">
    <h2 data-variant="h2">Beta heading</h2>
    <p class="text-muted">Beta body copy.</p>
  </div>
</section>
"""

BETA_REPLACEMENT = """
<section id="beta" class="bg-dark">
  <div class="mx-auto max-w-[1200px] px-6 py-24 flex flex-col gap-6">
    <h2 data-variant="h2" class="text-inverse">Beta reworked</h2>
    <p class="text-inverse">A different beta story.</p>
  </div>
</section>
"""

ALPHA_REPLACEMENT = """
<section id="alpha" class="bg-muted">
  <div class="mx-auto max-w-[1200px] px-6 py-24 flex flex-col gap-6">
    <h1 data-variant="display">Alpha reworked</h1>
  </div>
</section>
"""


def _subtree(nodes: dict, root: str) -> dict:
    """Deep-copied {id: node} of `root` and all its descendants."""
    out: dict = {}
    stack = [root]
    while stack:
        current = stack.pop()
        node = nodes.get(current)
        if not isinstance(node, dict):
            continue
        out[current] = json.loads(json.dumps(node))
        stack.extend(node.get("children") or [])
    return out


def _seed_two_sections(tmp_path: Path) -> LumenWebTools:
    tools = _tools(tmp_path)
    result = json.loads(tools.author_web_page(TWO_SECTION_HTML))
    assert result["status"] == "ok", result
    page = tools._home_page()
    root = (page.get("nodes") or {}).get(page.get("root")) or {}
    assert list(root.get("children") or []) == ["alpha", "beta"]
    return tools


def test_author_web_subtree_replaces_only_target_section(tmp_path: Path):
    tools = _seed_two_sections(tmp_path)
    nodes_before = (tools._home_page().get("nodes") or {})
    alpha_before = _subtree(nodes_before, "alpha")
    beta_before = _subtree(nodes_before, "beta")
    version_before = tools._doc_version

    result = json.loads(tools.author_web_subtree("beta", BETA_REPLACEMENT))
    assert result["status"] == "ok", result
    assert result["section"] == "beta"
    assert result["roots"] == ["beta"]
    assert tools._doc_version == version_before + 1

    page = tools._home_page()
    nodes_after = page.get("nodes") or {}
    root = nodes_after.get(page.get("root")) or {}
    # Section order and length preserved.
    assert list(root.get("children") or []) == ["alpha", "beta"]
    # Section 1 (alpha) is byte-identical; only section 2 (beta) changed.
    assert _subtree(nodes_after, "alpha") == alpha_before
    assert _subtree(nodes_after, "beta") != beta_before
    # The new beta copy is present.
    assert any(
        "Beta reworked" in (node.get("content") or "")
        for node in nodes_after.values()
    )


def test_author_web_subtree_resolves_child_to_section(tmp_path: Path):
    tools = _seed_two_sections(tmp_path)
    nodes = tools._home_page().get("nodes") or {}
    # Any real descendant of alpha (not alpha itself) must resolve to "alpha".
    child_ids = [i for i in _subtree(nodes, "alpha") if i != "alpha"]
    assert child_ids, "alpha has descendants"
    result = json.loads(tools.author_web_subtree(child_ids[0], ALPHA_REPLACEMENT))
    assert result["status"] == "ok", result
    assert result["section"] == "alpha"


def test_author_web_subtree_rejects_lint_violation(tmp_path: Path):
    tools = _seed_two_sections(tmp_path)
    version_before = tools._doc_version
    beta_before = _subtree(tools._home_page().get("nodes") or {}, "beta")
    # A raw hex color inside a valid section is a hard lint error → rejected.
    result = json.loads(
        tools.author_web_subtree(
            "beta",
            '<section id="beta"><div class="bg-[#ff0000]"><p>x</p></div></section>',
        )
    )
    assert result["status"] == "rejected", result
    assert any(d.get("severity") == "error" for d in result["diagnostics"])
    # Doc untouched.
    assert tools._doc_version == version_before
    assert _subtree(tools._home_page().get("nodes") or {}, "beta") == beta_before


def test_author_web_subtree_requires_section_root(tmp_path: Path):
    tools = _seed_two_sections(tmp_path)
    version_before = tools._doc_version
    # A top-level non-section replacement → not_a_section.
    result = json.loads(
        tools.author_web_subtree(
            "beta", '<div id="beta" class="bg-dark"><p>x</p></div>'
        )
    )
    assert result["status"] == "error", result
    assert result["error_code"] == "web_subtree.not_a_section"
    assert tools._doc_version == version_before


def test_author_web_subtree_unknown_node(tmp_path: Path):
    tools = _seed_two_sections(tmp_path)
    result = json.loads(tools.author_web_subtree("nope", BETA_REPLACEMENT))
    assert result["status"] == "error", result
    assert result["error_code"] == "web_subtree.unknown_node"
    # The error lists the real section ids to guide the caller.
    assert set(result["section_ids"]) == {"alpha", "beta"}


# --- web_ops (surgical repair batch) against the real helper -----------------


def test_web_ops_set_node_classes_applies(tmp_path: Path):
    tools = _seed_two_sections(tmp_path)
    nodes_before = tools._home_page().get("nodes") or {}
    assert nodes_before["alpha_body"].get("classes") == "text-muted"
    title_classes_before = nodes_before["alpha_title"].get("classes")
    beta_before = _subtree(nodes_before, "beta")
    version_before = tools._doc_version

    result = json.loads(
        tools.web_ops(
            json.dumps(
                [
                    {
                        "kind": "set_node_classes",
                        "page_id": "home",
                        "id": "alpha_body",
                        "classes": "text-primary font-bold",
                    }
                ]
            )
        )
    )
    assert result["status"] == "ok", result
    assert result["applied"] == 1
    assert tools._doc_version == version_before + 1

    nodes_after = tools._home_page().get("nodes") or {}
    # The targeted node's class string is replaced wholesale.
    assert nodes_after["alpha_body"].get("classes") == "text-primary font-bold"
    # A sibling and the whole other section are byte-identical.
    assert nodes_after["alpha_title"].get("classes") == title_classes_before
    assert _subtree(nodes_after, "beta") == beta_before


def test_web_ops_rejects_invalid_batch(tmp_path: Path):
    tools = _seed_two_sections(tmp_path)
    version_before = tools._doc_version
    nodes_before = _subtree(tools._home_page().get("nodes") or {}, "alpha")

    # set_text on a container (a section) cannot apply → the batch is rejected
    # whole and the working doc is left untouched.
    result = json.loads(
        tools.web_ops(
            json.dumps(
                [{"kind": "set_text", "page_id": "home", "id": "alpha", "content": "x"}]
            )
        )
    )
    assert result["status"] == "rejected", result
    assert any(d.get("severity") == "error" for d in result["diagnostics"])
    # Nothing stored: doc and version unchanged.
    assert tools._doc_version == version_before
    assert _subtree(tools._home_page().get("nodes") or {}, "alpha") == nodes_before


def test_web_ops_malformed_json(tmp_path: Path):
    tools = _seed_two_sections(tmp_path)
    version_before = tools._doc_version
    result = json.loads(tools.web_ops("{not valid json"))
    assert result["status"] == "error", result
    assert result["error_code"] == "web_ops.bad_json"
    # A malformed call never touches the doc.
    assert tools._doc_version == version_before


# --- lighter substrate helper (no core-helper round-trip) --------------------


def _bare_tools(tmp_path: Path, **cfg) -> LumenWebTools:
    """A LumenWebTools over a hand-seeded WebDoc so the pure-Python paths
    (capture plan, font CSS, finalize, view-state) need no core helper or
    browser. `cfg` overrides config fields (e.g. brand_fonts)."""
    from dataclasses import replace as _replace

    config = _replace(
        AgentRuntimeConfig.from_env(REPO_ROOT), trace_dir=tmp_path / "workspace_root", **cfg
    )
    seed = {
        "title": "Test site",
        "pages": [{"id": "home", "root": "root", "nodes": {"root": {"kind": "section", "children": []}}}],
        "assets": {},
    }
    return LumenWebTools(config, "Build a page", initial_web_doc=seed)


# --- _interactive_capture_plan (pure) ---------------------------------------


def _doc_with_nodes(nodes: dict) -> dict:
    return {"pages": [{"id": "home", "root": "root", "nodes": nodes}]}


def test_interactive_capture_plan_finds_dialogs_and_accordion():
    nodes = {
        "root": {"kind": "section", "children": ["d1", "acc", "d2"]},
        "d1": {"kind": "component", "component": "dialog"},
        "d2": {"kind": "component", "component": "dialog"},
        "acc": {"kind": "component", "component": "accordion"},
    }
    plan = _interactive_capture_plan(_doc_with_nodes(nodes))
    assert set(plan["dialogs"]) == {"d1", "d2"}
    assert plan["has_accordion"] is True


def test_interactive_capture_plan_empty_when_component_free():
    nodes = {
        "root": {"kind": "section", "children": ["t"]},
        "t": {"kind": "text", "content": "x"},
    }
    plan = _interactive_capture_plan(_doc_with_nodes(nodes))
    assert plan == {"dialogs": [], "has_accordion": False}


def test_interactive_capture_plan_carries_all_dialogs_over_cap():
    # The plan lists every dialog; the capture LOOP caps at _MAX_DIALOG_CAPTURES
    # (that cap lives in _capture_states, a Playwright path exercised by the live
    # gate). Here we assert the plan is complete and the slice the loop applies
    # is bounded.
    nodes = {"root": {"kind": "section", "children": ["d1", "d2", "d3", "d4"]}}
    for i in range(1, 5):
        nodes[f"d{i}"] = {"kind": "component", "component": "dialog"}
    plan = _interactive_capture_plan(_doc_with_nodes(nodes))
    assert len(plan["dialogs"]) == 4
    assert len(plan["dialogs"][:_MAX_DIALOG_CAPTURES]) == _MAX_DIALOG_CAPTURES == 3
    assert plan["dialogs"][_MAX_DIALOG_CAPTURES:] == ["d4"]


# --- _font_face_css (in-loop kit fonts) -------------------------------------


def _write_face(store: Path, digest: str, magic: bytes) -> None:
    dest = store / "sha256" / digest[:2] / digest
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(magic + b"\x00" * 32)


def test_font_face_css_embeds_face_with_weight_and_style(tmp_path: Path):
    store = tmp_path / "store"
    digest = "a" * 64
    _write_face(store, digest, b"wOF2")
    tools = _bare_tools(
        tmp_path,
        brand_fonts={
            "store_root": str(store),
            "faces": [{"digest": digest, "family": "Aeonik", "weight": 700, "style": "italic"}],
        },
    )
    css = tools._font_face_css()
    assert css is not None
    assert "font-weight:700" in css
    assert "font-style:italic" in css
    assert "data:font/woff2;base64," in css
    assert '"Aeonik"' in css
    # Cached: a second call returns the same object.
    assert tools._font_face_css() is css


def test_font_face_css_legacy_face_defaults_to_400_normal(tmp_path: Path):
    store = tmp_path / "store"
    digest = "b" * 64
    _write_face(store, digest, b"wOF2")
    tools = _bare_tools(
        tmp_path,
        brand_fonts={"store_root": str(store), "faces": [{"digest": digest, "family": "Legacy"}]},
    )
    css = tools._font_face_css()
    assert css is not None
    assert "font-weight:400" in css
    assert "font-style:normal" in css


def test_font_face_css_skips_missing_file_keeps_good_face(tmp_path: Path):
    store = tmp_path / "store"
    good, bad = "a" * 64, "b" * 64
    _write_face(store, good, b"wOF2")  # bad is never written → unreadable
    tools = _bare_tools(
        tmp_path,
        brand_fonts={
            "store_root": str(store),
            "faces": [
                {"digest": bad, "family": "Missing"},
                {"digest": good, "family": "Present"},
            ],
        },
    )
    css = tools._font_face_css()
    assert css is not None
    assert css.count("@font-face") == 1
    assert '"Present"' in css
    assert '"Missing"' not in css


def test_font_face_css_none_when_nothing_resolves(tmp_path: Path):
    store = tmp_path / "store"
    tools = _bare_tools(
        tmp_path,
        brand_fonts={"store_root": str(store), "faces": [{"digest": "c" * 64, "family": "Gone"}]},
    )
    assert tools._font_face_css() is None


def test_font_face_css_none_without_brand_fonts(tmp_path: Path):
    assert _bare_tools(tmp_path)._font_face_css() is None


def test_font_face_css_respects_byte_cap(tmp_path: Path, monkeypatch):
    store = tmp_path / "store"
    d1, d2 = "a" * 64, "b" * 64
    _write_face(store, d1, b"wOF2")
    _write_face(store, d2, b"wOF2")
    # Each face is 36 bytes → 48 base64 chars. Cap at 48 fits exactly one.
    monkeypatch.setattr(ws, "_FONT_FACE_CSS_MAX_BYTES", 48)
    tools = _bare_tools(
        tmp_path,
        brand_fonts={
            "store_root": str(store),
            "faces": [
                {"digest": d1, "family": "First"},
                {"digest": d2, "family": "Second"},
            ],
        },
    )
    css = tools._font_face_css()
    assert css is not None
    assert css.count("@font-face") == 1
    assert '"First"' in css
    assert '"Second"' not in css


# --- finalize_web_run ladder_gap --------------------------------------------


def _trace_events(tools: LumenWebTools) -> list[str]:
    lines = (tools.trace_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line).get("event") for line in lines]


def test_finalize_web_run_records_ladder_gap(tmp_path: Path):
    tools = _bare_tools(tmp_path)
    gap = "a filterable pricing table the catalogue can't express"
    result = json.loads(tools.finalize_web_run("accepted", "done", ladder_gap=gap))
    assert result["ladder_gap"] == gap
    final = json.loads((tools.trace_dir / "final.json").read_text(encoding="utf-8"))
    assert final["ladder_gap"] == gap
    assert "ladder_gap" in _trace_events(tools)


def test_finalize_web_run_without_ladder_gap(tmp_path: Path):
    tools = _bare_tools(tmp_path)
    result = json.loads(tools.finalize_web_run("accepted", "done"))
    assert "ladder_gap" not in result
    final = json.loads((tools.trace_dir / "final.json").read_text(encoding="utf-8"))
    assert "ladder_gap" not in final
    assert "ladder_gap" not in _trace_events(tools)
    # A whitespace-only gap is treated as absent.
    blank = json.loads(tools.finalize_web_run("accepted", "done", ladder_gap="   "))
    assert "ladder_gap" not in blank


# --- view("state:<n>") ------------------------------------------------------


def _seed_state_capture(tmp_path: Path, tools: LumenWebTools) -> str:
    from PIL import Image

    img_path = tmp_path / "state_1440_dialog_dlg_1.png"
    Image.new("RGB", (1440, 900), "white").save(img_path)
    tools._state_captures = [
        {"kind": "dialog-open", "node_id": "dlg_1", "width": 1440, "path": str(img_path)}
    ]
    return str(img_path)


def test_view_state_returns_image_block(tmp_path: Path):
    tools = _bare_tools(tmp_path)
    _seed_state_capture(tmp_path, tools)
    blocks = tools._view_content("state:0")
    assert blocks[0]["type"] == "text"
    assert "dialog-open" in blocks[0]["text"]
    assert "dlg_1" in blocks[0]["text"]
    assert any(b.get("type") == "image" for b in blocks)


def test_view_state_out_of_range_is_helpful(tmp_path: Path):
    tools = _bare_tools(tmp_path)
    _seed_state_capture(tmp_path, tools)
    blocks = tools._view_content("state:5")
    assert len(blocks) == 1 and blocks[0]["type"] == "text"
    assert "out of range" in blocks[0]["text"]


def test_view_state_none_captured(tmp_path: Path):
    tools = _bare_tools(tmp_path)
    blocks = tools._view_content("state:0")
    assert blocks[0]["type"] == "text"
    assert "no state captures" in blocks[0]["text"]
