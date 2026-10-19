"""LumenWebTools unit coverage.

Two layers: pure-Python token-name derivation (no helper), and the
author_web_page happy path against the REAL core helper (deterministic — HTML
ingest only, no LLM or browser).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools import view as view_mod
from lumen_agent.tools import web_substrate as ws
from lumen_agent.tools.web_substrate import (
    _MAX_DIALOG_CAPTURES,
    LumenWebTools,
    _interactive_capture_plan,
    sanitize_token_name,
    web_theme_token_names,
)

if TYPE_CHECKING:
    from PIL import Image

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


# --- the Tailwind browser runtime search path (G7) ---------------------------
#
# Regression cover for the missing-runtime defect: the preview render inlines
# this file, and without it every screenshot loses its whole layout layer while
# still looking like a page — so the visual reviewer grades a broken render as a
# real one. Before G7 exactly one (gitignored, unproduced) path was consulted.


def _write(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("/* runtime */", encoding="utf-8")
    return path


def test_tailwind_runtime_prefers_the_vendored_editor_copy(tmp_path, monkeypatch):
    monkeypatch.delenv("LUMEN_TAILWIND_RUNTIME", raising=False)
    vendored = _write(
        tmp_path / "apps" / "editor" / "public" / "vendor" / "tailwind-browser.js"
    )
    _write(
        tmp_path
        / "apps"
        / "editor"
        / "node_modules"
        / "@tailwindcss"
        / "browser"
        / "dist"
        / "index.global.js"
    )
    assert ws.tailwind_runtime_path(tmp_path) == vendored


def test_tailwind_runtime_falls_back_to_the_installed_package(tmp_path, monkeypatch):
    # The fleet worker never runs the editor's npm scripts, so a plain
    # `npm install` under apps/editor must be enough on its own.
    monkeypatch.delenv("LUMEN_TAILWIND_RUNTIME", raising=False)
    installed = _write(
        tmp_path
        / "apps"
        / "editor"
        / "node_modules"
        / "@tailwindcss"
        / "browser"
        / "dist"
        / "index.global.js"
    )
    assert ws.tailwind_runtime_path(tmp_path) == installed


def test_tailwind_runtime_env_override_wins(tmp_path, monkeypatch):
    _write(tmp_path / "apps" / "editor" / "public" / "vendor" / "tailwind-browser.js")
    elsewhere = _write(tmp_path / "image" / "tailwind.js")
    monkeypatch.setenv("LUMEN_TAILWIND_RUNTIME", str(elsewhere))
    assert ws.tailwind_runtime_path(tmp_path) == elsewhere


def test_tailwind_runtime_env_override_pointing_nowhere_does_not_fall_through(
    tmp_path, monkeypatch
):
    # An operator who named a path must be told it is wrong, not silently
    # handed a different runtime.
    _write(tmp_path / "apps" / "editor" / "public" / "vendor" / "tailwind-browser.js")
    monkeypatch.setenv("LUMEN_TAILWIND_RUNTIME", str(tmp_path / "nope.js"))
    assert ws.tailwind_runtime_path(tmp_path) is None


def test_tailwind_runtime_absent_everywhere_is_none(tmp_path, monkeypatch):
    monkeypatch.delenv("LUMEN_TAILWIND_RUNTIME", raising=False)
    assert ws.tailwind_runtime_path(tmp_path) is None


def test_tailwind_runtime_resolves_in_this_checkout(monkeypatch):
    # The end the defect was actually about: from the real repo root, with no
    # override, SOMETHING supplies the runtime. `apps/editor`'s npm install is
    # the design subsystem's documented dev prerequisite (its own test gate
    # already requires the wasm build from the same tree).
    monkeypatch.delenv("LUMEN_TAILWIND_RUNTIME", raising=False)
    resolved = ws.tailwind_runtime_path(REPO_ROOT)
    if not (REPO_ROOT / "apps" / "editor" / "node_modules").is_dir():
        pytest.skip("apps/editor dependencies are not installed in this checkout")
    assert resolved is not None and resolved.is_file()


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


def _hex_color(value="#00525C"):
    return {"value": {"default": {"kind": "hex", "value": value}}}


def test_web_theme_token_names_appends_sanitized_kit_colors():
    kit = {
        "tokens": {
            "colors": {
                # a duplicate of a semantic name is not repeated
                "primary": _hex_color(),
                "Surface.Brand": _hex_color(),
                "palette.primary.500": _hex_color("#30D8A7"),
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


# W1.3 — the prompt may never advertise a token the compiled theme did not emit.
# The Rust compiler (crates/lumen-web/src/theme.rs:113-131) skips a kit color on
# TWO rules: its sanitized name already exists, and it does not resolve to a
# concrete color (LUMW0302). Python replicated only the first, so a broken alias
# chain became a token name the author was invited to use and the lint rejected.


def test_web_theme_token_names_skips_a_color_that_does_not_resolve():
    kit = {
        "tokens": {
            "colors": {
                "brand.teal": _hex_color(),
                # alias chain into a token the kit does not carry → LUMW0302
                "brand.ghost": {"value": {"default": {"kind": "alias", "token": "gone"}}},
            }
        }
    }
    names = web_theme_token_names(kit).split()
    assert "brand-teal" in names
    assert "brand-ghost" not in names


def test_web_theme_token_names_resolves_through_an_alias_chain():
    kit = {
        "tokens": {
            "colors": {
                "brand.base": _hex_color(),
                "brand.hop": {"value": {"default": {"kind": "alias", "token": "brand.base"}}},
            }
        }
    }
    assert "brand-hop" in web_theme_token_names(kit).split()


def test_web_theme_token_names_skips_a_cyclic_alias():
    kit = {
        "tokens": {
            "colors": {
                "a.one": {"value": {"default": {"kind": "alias", "token": "a.two"}}},
                "a.two": {"value": {"default": {"kind": "alias", "token": "a.one"}}},
            }
        }
    }
    names = web_theme_token_names(kit).split()
    assert "a-one" not in names and "a-two" not in names


def test_web_theme_token_names_keeps_an_unresolvable_name_available_to_a_later_color():
    """Rust never inserts the skipped name, so a LATER kit color that sanitizes
    to the same thing still gets its token. Skipping must not poison the name."""
    kit = {
        "tokens": {
            "colors": {
                "brand.ghost": {"value": {"default": {"kind": "alias", "token": "gone"}}},
                "Brand.Ghost": _hex_color(),
            }
        }
    }
    assert web_theme_token_names(kit).split().count("brand-ghost") == 1


def test_web_theme_token_names_unchanged_for_a_healthy_kit():
    """Byte-stability guard: a kit whose colors all resolve and never collide
    yields exactly the string this seam has always produced."""
    kit = {
        "tokens": {
            "colors": {
                "surface.brand": _hex_color(),
                "palette.primary.500": _hex_color("#30D8A7"),
                "text.primary": {
                    "value": {
                        "default": {"kind": "oklch", "l": 0.2, "c": 0.02, "h": 200.0, "alpha": 1.0}
                    }
                },
            }
        }
    }
    assert web_theme_token_names(kit) == (
        "primary accent dark light card muted border inverse "
        "surface-brand palette-primary-500 text-primary"
    )


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
    before = json.loads(json.dumps(tools.web_doc))
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
    assert tools.operations_ledger
    assert {operation["kind"] for operation in tools.operations_ledger} == {
        "insert_node"
    }
    replay = tools.core.web_apply_ops(before, tools.operations_ledger)
    assert replay["web_doc"] == tools.web_doc


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
    operation_count_before = len(tools.operations_ledger)

    result = json.loads(tools.author_web_subtree("beta", BETA_REPLACEMENT))
    assert result["status"] == "ok", result
    assert result["section"] == "beta"
    assert result["roots"] == ["beta"]
    assert tools._doc_version == version_before + 1
    turn_operations = tools.operations_ledger[operation_count_before:]
    assert [operation["kind"] for operation in turn_operations] == [
        "remove_node",
        "insert_node",
    ]

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
        child.get("text") == "Beta reworked"
        for node in nodes_after.values()
        for block in (node.get("content") or {}).get("blocks", [])
        for child in block.get("children", [])
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
    operation_count_before = len(tools.operations_ledger)
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
    assert len(tools.operations_ledger) == operation_count_before
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


# --- patch_web_page (repair a rejected submission) against the real helper ---

# A page whose ONLY error is a raw hex color class — rejected by author_web_page,
# then repairable by swapping the hex for a semantic token.
REJECTED_PAGE_HTML = (
    '<section id="s"><div class="bg-[#ff0000]"><p>x</p></div></section>'
)


def test_patch_web_page_repairs_rejected_page(tmp_path: Path):
    tools = _tools(tmp_path)
    rejected = json.loads(tools.author_web_page(REJECTED_PAGE_HTML))
    assert rejected["status"] == "rejected", rejected
    # The rejected submission is now pending, carrying the SUBMITTED html.
    assert tools._last_rejected_authoring is not None
    assert tools._last_rejected_authoring["tool"] == "author_web_page"
    assert tools._last_rejected_authoring["html"] == REJECTED_PAGE_HTML
    version_before = tools._doc_version

    # A patch swapping the raw hex for a semantic token → the resubmission is
    # ACCEPTED, the doc is updated, and the pending rejection is cleared.
    result = json.loads(
        tools.patch_web_page(
            json.dumps([{"old_string": "bg-[#ff0000]", "new_string": "bg-primary"}])
        )
    )
    assert result["status"] == "ok", result
    assert result["repaired_via"] == "patch"
    assert result["patches_applied"] == 1
    assert tools._doc_version == version_before + 1
    assert tools._last_rejected_authoring is None
    # The section is really installed now.
    assert (tools._home_page().get("nodes") or {}).get("s")


def test_patch_web_page_no_pending_on_fresh_substrate(tmp_path: Path):
    tools = _tools(tmp_path)
    result = json.loads(
        tools.patch_web_page(json.dumps([{"old_string": "a", "new_string": "b"}]))
    )
    assert result["status"] == "error", result
    assert result["error_code"] == "patch.no_pending"


def test_patch_web_page_no_pending_after_successful_author(tmp_path: Path):
    tools = _tools(tmp_path)
    # A rejection leaves a pending submission…
    assert json.loads(tools.author_web_page(REJECTED_PAGE_HTML))["status"] == "rejected"
    assert tools._last_rejected_authoring is not None
    # …but a subsequent SUCCESSFUL author clears the stale pending.
    assert json.loads(tools.author_web_page(SAMPLE_HTML))["status"] == "ok"
    assert tools._last_rejected_authoring is None
    result = json.loads(
        tools.patch_web_page(json.dumps([{"old_string": "a", "new_string": "b"}]))
    )
    assert result["status"] == "error", result
    assert result["error_code"] == "patch.no_pending"


def test_patch_web_page_not_found(tmp_path: Path):
    tools = _tools(tmp_path)
    json.loads(tools.author_web_page(REJECTED_PAGE_HTML))
    result = json.loads(
        tools.patch_web_page(
            json.dumps([{"old_string": "not-present-anywhere", "new_string": "x"}])
        )
    )
    assert result["status"] == "error", result
    assert result["error_code"] == "patch.not_found"
    assert "patch 0" in result["message"]
    # The stored submission is untouched by a failed patch.
    assert tools._last_rejected_authoring["html"] == REJECTED_PAGE_HTML


def test_patch_web_page_ambiguous_then_replace_all(tmp_path: Path):
    tools = _tools(tmp_path)
    # Two identical raw-hex classes: a bare patch matches both → ambiguous.
    html = (
        '<section id="s">'
        '<div class="bg-[#ff0000]"><p>a</p></div>'
        '<div class="bg-[#ff0000]"><p>b</p></div>'
        "</section>"
    )
    assert json.loads(tools.author_web_page(html))["status"] == "rejected"
    ambiguous = json.loads(
        tools.patch_web_page(
            json.dumps([{"old_string": "bg-[#ff0000]", "new_string": "bg-primary"}])
        )
    )
    assert ambiguous["status"] == "error", ambiguous
    assert ambiguous["error_code"] == "patch.ambiguous"
    assert "occurs 2 times" in ambiguous["message"]
    # Stored submission unchanged after the ambiguous rejection.
    assert tools._last_rejected_authoring["html"] == html
    # A follow-up corrected patch (replace_all) still works from the same state.
    fixed = json.loads(
        tools.patch_web_page(
            json.dumps(
                [
                    {
                        "old_string": "bg-[#ff0000]",
                        "new_string": "bg-primary",
                        "replace_all": True,
                    }
                ]
            )
        )
    )
    assert fixed["status"] == "ok", fixed
    assert fixed["repaired_via"] == "patch"
    assert tools._last_rejected_authoring is None


def test_patch_web_page_bad_input_variants(tmp_path: Path):
    tools = _tools(tmp_path)
    json.loads(tools.author_web_page(REJECTED_PAGE_HTML))

    def err(patches_json: str) -> dict:
        return json.loads(tools.patch_web_page(patches_json))

    # Not a JSON array.
    assert err("{not json")["error_code"] == "patch.bad_input"
    # A JSON object, not an array.
    assert err(json.dumps({"old_string": "a", "new_string": "b"}))["error_code"] == "patch.bad_input"
    # Empty array.
    assert err(json.dumps([]))["error_code"] == "patch.bad_input"
    # Entry not an object.
    assert err(json.dumps(["nope"]))["error_code"] == "patch.bad_input"
    # Missing / non-string new_string.
    assert err(json.dumps([{"old_string": "a"}]))["error_code"] == "patch.bad_input"
    assert err(json.dumps([{"old_string": "a", "new_string": 3}]))["error_code"] == "patch.bad_input"
    # Empty old_string.
    assert err(json.dumps([{"old_string": "", "new_string": "b"}]))["error_code"] == "patch.bad_input"
    # old_string == new_string (no-op).
    assert err(json.dumps([{"old_string": "a", "new_string": "a"}]))["error_code"] == "patch.bad_input"
    # A failed validation never touches the doc or the stored submission.
    assert tools._doc_version == 0
    assert tools._last_rejected_authoring["html"] == REJECTED_PAGE_HTML


def test_patch_web_page_two_rounds(tmp_path: Path):
    tools = _tools(tmp_path)
    assert json.loads(tools.author_web_page(REJECTED_PAGE_HTML))["status"] == "rejected"

    # Round 1: the patch fixes the first hex but INTRODUCES a second raw hex →
    # still rejected, and the stored html is updated to the patched version.
    round1 = json.loads(
        tools.patch_web_page(
            json.dumps([{"old_string": "bg-[#ff0000]", "new_string": "bg-[#00ff00]"}])
        )
    )
    assert round1["status"] == "rejected", round1
    assert tools._last_rejected_authoring is not None
    assert "bg-[#00ff00]" in tools._last_rejected_authoring["html"]
    assert "bg-[#ff0000]" not in tools._last_rejected_authoring["html"]

    # Round 2: a patch against the UPDATED stored html fixes the remaining hex.
    round2 = json.loads(
        tools.patch_web_page(
            json.dumps([{"old_string": "bg-[#00ff00]", "new_string": "bg-primary"}])
        )
    )
    assert round2["status"] == "ok", round2
    assert round2["repaired_via"] == "patch"
    assert tools._last_rejected_authoring is None
    assert (tools._home_page().get("nodes") or {}).get("s")


def test_patch_web_page_repairs_rejected_subtree(tmp_path: Path):
    tools = _seed_two_sections(tmp_path)
    # A scoped edit on "beta" with a raw hex → rejected, pending as a subtree.
    rejected = json.loads(
        tools.author_web_subtree(
            "beta",
            '<section id="beta"><div class="bg-[#ff0000]"><p>x</p></div></section>',
        )
    )
    assert rejected["status"] == "rejected", rejected
    assert tools._last_rejected_authoring["tool"] == "author_web_subtree"
    assert tools._last_rejected_authoring["node_id"] == "beta"
    version_before = tools._doc_version

    result = json.loads(
        tools.patch_web_page(
            json.dumps([{"old_string": "bg-[#ff0000]", "new_string": "bg-primary"}])
        )
    )
    assert result["status"] == "ok", result
    assert result["section"] == "beta"
    assert result["repaired_via"] == "patch"
    assert tools._doc_version == version_before + 1
    assert tools._last_rejected_authoring is None
    # The alpha section is still present; beta was replaced in place.
    page = tools._home_page()
    root = (page.get("nodes") or {}).get(page.get("root")) or {}
    assert list(root.get("children") or []) == ["alpha", "beta"]


# --- web_ops (surgical repair batch) against the real helper -----------------


def test_web_ops_set_node_classes_applies(tmp_path: Path):
    tools = _seed_two_sections(tmp_path)
    nodes_before = tools._home_page().get("nodes") or {}
    assert nodes_before["alpha_body"].get("classes") == "text-muted"
    title_classes_before = nodes_before["alpha_title"].get("classes")
    beta_before = _subtree(nodes_before, "beta")
    version_before = tools._doc_version
    operation_count_before = len(tools.operations_ledger)

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
    assert tools.operations_ledger[operation_count_before:] == [
        {
            "kind": "set_node_classes",
            "page_id": "home",
            "id": "alpha_body",
            "classes": "text-primary font-bold",
        }
    ]

    nodes_after = tools._home_page().get("nodes") or {}
    # The targeted node's class string is replaced wholesale.
    assert nodes_after["alpha_body"].get("classes") == "text-primary font-bold"
    # A sibling and the whole other section are byte-identical.
    assert nodes_after["alpha_title"].get("classes") == title_classes_before
    assert _subtree(nodes_after, "beta") == beta_before


def test_web_ops_set_rich_text_preserves_typed_list_structure(tmp_path: Path):
    tools = _seed_two_sections(tmp_path)
    nodes_before = tools._home_page().get("nodes") or {}
    alpha_title_before = nodes_before["alpha_title"]
    beta_before = _subtree(nodes_before, "beta")
    structured = {
        "schema_version": 1,
        "blocks": [
            {
                "type": "paragraph",
                "children": [{"type": "text", "text": "Intro"}],
            },
            {
                "type": "list",
                "list_type": "unordered",
                "items": [
                    {"children": [{"type": "text", "text": "First"}]},
                    {
                        "children": [
                            {
                                "type": "variable",
                                "key": "account.name",
                                "fallback": "Customer",
                            }
                        ]
                    },
                ],
            },
        ],
    }
    result = json.loads(
        tools.web_ops(
            json.dumps(
                [
                    {
                        "kind": "set_rich_text",
                        "page_id": "home",
                        "id": "alpha_body",
                        "content": structured,
                    }
                ]
            )
        )
    )
    assert result["status"] == "ok", result
    nodes_after = tools._home_page().get("nodes") or {}
    assert nodes_after["alpha_body"]["content"] == structured
    assert nodes_after["alpha_title"] == alpha_title_before
    assert _subtree(nodes_after, "beta") == beta_before
    assert tools.operations_ledger[-1]["kind"] == "set_rich_text"


def test_web_ops_contract_teaches_structured_text_preservation():
    contract = LumenWebTools.web_ops.__doc__ or ""
    assert "set_rich_text" in contract
    assert "preserve every unaffected block/list/mark/variable" in contract
    assert "heading variants accept exactly one paragraph" in contract


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
        "schema_version": 1,
        "id": "doc_web_test",
        "title": "Test site",
        "theme": {},
        "custom_css": "",
        "pages": [
            {
                "id": "home",
                "name": "Home",
                "route": "/",
                "root": "root",
                "nodes": {
                    "root": {
                        "id": "root",
                        "kind": "container",
                        "classes": "",
                        "new_tab": False,
                    }
                },
            }
        ],
        "assets": {},
    }
    return LumenWebTools(config, "Build a page", initial_web_doc=seed)


# --- grounded page, asset search, provenance -------------------------------


def test_extract_grounded_page_strips_scripts_and_absolutizes_links():
    page = ws._extract_grounded_page(
        requested_url="https://example.test/about",
        final_url="https://example.test/about",
        status=200,
        content_type="text/html; charset=utf-8",
        body=(
            b"<html><head><title> About Acme </title><style>.x{}</style></head>"
            b"<body><h1>Acme facts</h1><script>ignore me</script>"
            b"<a href='/proof#team'>Proof</a><a href='mailto:x@y.test'>Mail</a>"
            b"</body></html>"
        ),
        retrieved_at="2026-07-30T00:00:00+00:00",
    )
    assert page["kind"] == "page"
    assert page["content_trust"] == "untrusted_evidence"
    assert page["title"] == "About Acme"
    assert "Acme facts" in page["text"]
    assert "ignore me" not in page["text"]
    assert page["links"] == [
        {"url": "https://example.test/proof", "text": "Proof"}
    ]
    assert page["retrieved_at"] == "2026-07-30T00:00:00+00:00"
    assert len(page["content_sha256"]) == 64


def test_fetch_page_registers_exact_source_and_trace(tmp_path: Path, monkeypatch):
    tools = _bare_tools(tmp_path)
    fetched = {
        "source_id": "page_grounded",
        "kind": "page",
        "requested_url": "https://example.test",
        "final_url": "https://example.test/",
        "retrieved_at": "2026-07-30T00:00:00+00:00",
        "http_status": 200,
        "content_type": "text/html",
        "content_sha256": "a" * 64,
        "title": "Example",
        "text": "Grounded copy",
        "links": [],
        "truncated": False,
        "diagnostics": [],
    }
    monkeypatch.setattr(ws, "_fetch_grounded_page", lambda url: fetched)

    result = json.loads(tools.fetch_page("https://example.test"))
    assert result["status"] == "ok"
    assert result["source_id"] == "page_grounded"
    assert tools.grounding_report()["sources"] == [fetched]
    trace = (tools.trace_dir / "trace.jsonl").read_text()
    assert "web_page_fetched" in trace


def test_fetch_page_surfaces_blocked_url_without_source(tmp_path: Path, monkeypatch):
    tools = _bare_tools(tmp_path)

    def blocked(_url: str):
        raise ws.CaptureError("LUMI0501", "blocked url — private address")

    monkeypatch.setattr(ws, "_fetch_grounded_page", blocked)
    result = json.loads(tools.fetch_page("http://127.0.0.1/private"))
    assert result["status"] == "error"
    assert result["error_code"] == "page_fetch.blocked"
    assert tools.grounding_report()["sources"] == []


def _library_logo_entry() -> tuple[str, dict]:
    record = json.loads(
        (REPO_ROOT / "crates/lumen-core/fixtures/assets/uploaded_logo_asset.json").read_text()
    )
    return record["id"], {
        "record": record,
        "title": "Acme primary logo",
        "description": "A navy Acme wordmark.",
        "usage": "Use on light backgrounds.",
        "tags": ["wordmark"],
        "created_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-02T00:00:00Z",
    }


def test_search_assets_matches_descriptions_and_returns_provenance(tmp_path: Path):
    asset_id, entry = _library_logo_entry()
    tools = _bare_tools(tmp_path, asset_library={asset_id: entry})
    before = json.dumps(tools.web_doc, sort_keys=True)

    result = json.loads(tools.search_assets("navy wordmark", kind="logo"))
    assert result["status"] == "ok"
    assert result["count"] == 1
    match = result["results"][0]
    assert match["asset_id"] == asset_id
    assert match["license"]["name"] == "client_owned"
    assert match["provenance"]["source_label"] == "manual upload"
    assert json.dumps(tools.web_doc, sort_keys=True) == before
    assert tools.grounding_report()["sources"][0]["asset_id"] == asset_id


def test_use_library_asset_preserves_record_and_auto_cites(tmp_path: Path):
    asset_id, entry = _library_logo_entry()
    tools = _bare_tools(tmp_path, asset_library={asset_id: entry})

    result = json.loads(
        tools.asset(
            action="use_library_asset",
            asset_id=asset_id,
            alt="Acme",
        )
    )
    assert result["status"] == "ok"
    assert result["asset_id"] == asset_id
    assert result["citation_id"] == "citation_1"
    stored = tools.web_doc["assets"][asset_id]
    assert stored["license"] == entry["record"]["license"]
    assert stored["provenance"] == entry["record"]["provenance"]
    assert stored["media"]["digest"] == entry["record"]["media"]["digest"]
    assert tools.operations_ledger[-1] == {
        "kind": "upsert_asset",
        "record": entry["record"],
    }
    report = tools.grounding_report()
    assert report["citations"][0]["source_ids"] == [result["source_id"]]


def test_provenance_validates_sources_and_current_nodes(tmp_path: Path, monkeypatch):
    tools = _bare_tools(tmp_path)
    fetched = {
        "source_id": "page_grounded",
        "kind": "page",
        "requested_url": "https://example.test",
        "final_url": "https://example.test",
        "retrieved_at": "2026-07-30T00:00:00+00:00",
        "http_status": 200,
        "content_type": "text/html",
        "content_sha256": "b" * 64,
        "title": "Example",
        "text": "Fact",
        "links": [],
        "truncated": False,
        "diagnostics": [],
    }
    monkeypatch.setattr(ws, "_fetch_grounded_page", lambda url: fetched)
    json.loads(tools.fetch_page("https://example.test"))

    unknown_source = json.loads(
        tools.provenance(
            action="cite",
            source_ids_json='["missing"]',
            note="Unsupported",
        )
    )
    assert unknown_source["error_code"] == "provenance.unknown_source"
    unknown_node = json.loads(
        tools.provenance(
            action="cite",
            source_ids_json='["page_grounded"]',
            note="Supports the hero claim.",
            node_ids_json='["missing"]',
        )
    )
    assert unknown_node["error_code"] == "provenance.unknown_node"

    cited = json.loads(
        tools.provenance(
            action="cite",
            source_ids_json='["page_grounded"]',
            note="Supports the page claim.",
            node_ids_json='["root"]',
        )
    )
    assert cited["status"] == "ok"
    assert cited["citation"]["node_ids"] == ["root"]


def test_finalize_writes_grounding_ledger(tmp_path: Path, monkeypatch):
    tools = _bare_tools(tmp_path)
    monkeypatch.setattr(
        ws,
        "_fetch_grounded_page",
        lambda url: {
            "source_id": "page_grounded",
            "kind": "page",
            "requested_url": url,
            "final_url": url,
            "retrieved_at": "2026-07-30T00:00:00+00:00",
            "http_status": 200,
            "content_type": "text/plain",
            "content_sha256": "c" * 64,
            "title": "",
            "text": "Evidence",
            "links": [],
            "truncated": False,
            "diagnostics": [],
        },
    )
    json.loads(tools.fetch_page("https://example.test/evidence"))
    final = json.loads(tools.finalize_web_run("accepted", "done"))
    assert final["grounding_source_count"] == 1
    assert final["provenance_citation_count"] == 0
    report = json.loads((tools.trace_dir / "final_grounding.json").read_text())
    assert report["sources"][0]["source_id"] == "page_grounded"


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
    assert plan["has_nav"] is False
    assert plan["tabs"] == []


def test_interactive_capture_plan_empty_when_component_free():
    nodes = {
        "root": {"kind": "section", "children": ["t"]},
        "t": {"kind": "text", "content": "x"},
    }
    plan = _interactive_capture_plan(_doc_with_nodes(nodes))
    assert plan == {"dialogs": [], "has_accordion": False, "has_nav": False, "tabs": []}


def test_interactive_capture_plan_finds_nav_and_multichild_tabs_only():
    # A nav_menu → has_nav; two tabs components, but only the one with ≥2
    # children is listed (a single-tab strip has nothing to switch to).
    nodes = {
        "root": {"kind": "section", "children": ["nav", "t_one", "t_many"]},
        "nav": {"kind": "component", "component": "nav_menu"},
        "t_one": {"kind": "component", "component": "tabs", "children": ["p1"]},
        "t_many": {
            "kind": "component",
            "component": "tabs",
            "children": ["q1", "q2", "q3"],
        },
    }
    plan = _interactive_capture_plan(_doc_with_nodes(nodes))
    assert plan["has_nav"] is True
    assert plan["tabs"] == ["t_many"]
    assert plan["dialogs"] == []
    assert plan["has_accordion"] is False


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


# --- G5: every web view image rides the MANY-IMAGE ceiling ------------------
#
# The web review conversation is many-image by construction: one render is three
# widths plus state captures, and the orchestrator's history keeps every image it
# has ever viewed. Past 20 images in one request the provider's per-image
# dimension limit drops to 2000px, and the first realistic chat-driven landing
# page died there after ~28 minutes ("...exceed max allowed size for many-image
# requests: 2000 pixels", messages.1.content.39, run_c6f4485…). Clamping at the
# attach point is the whole fix: a late clamp cannot help, because the earlier
# oversized images are already sitting in the history the request replays.


def _emitted_image(blocks: list) -> "Image.Image":
    from PIL import Image

    payload = [b for b in blocks if b.get("type") == "image"][0]["data"]
    return Image.open(io.BytesIO(base64.b64decode(payload)))


def _seed_page_capture(tmp_path: Path, tools: LumenWebTools, width: int, size) -> None:
    from PIL import Image

    path = tmp_path / f"preview_{width}.png"
    Image.new("RGB", size, "white").save(path)
    tools._preview_by_width[width] = str(path)
    tools._preview_doc_version = tools._doc_version
    tools._preview_iteration = 1
    tools._preview_media_ready = True


def test_web_view_preview_clamps_to_the_many_image_ceiling(tmp_path: Path):
    tools = _bare_tools(tmp_path)
    # The observed whole-page capture of an ordinary landing page.
    _seed_page_capture(tmp_path, tools, 1440, (1440, 14325))
    emitted = _emitted_image(tools._view_content("preview:1440"))
    assert max(emitted.size) <= view_mod._VISION_MANY_IMAGE_MAX_PX
    assert abs((emitted.size[0] / emitted.size[1]) - (1440 / 14325)) < 0.005


def test_web_preview_tile_crops_saved_pixels_before_normalization(tmp_path: Path, monkeypatch):
    """A real narrow/tall capture must stay legible, not become a 102px strip."""
    from PIL import Image, ImageDraw

    tools = _bare_tools(tmp_path)
    _seed_page_capture(tmp_path, tools, 375, (379, 7464))
    path = Path(tools._preview_by_width[375])
    with Image.open(path) as source:
        drawing = ImageDraw.Draw(source)
        drawing.rectangle((0, 1100, 378, 1699), fill="red")
        drawing.rectangle((0, 1700, 378, 2299), fill="blue")
        source.save(path)
    original = path.read_bytes()
    doc_before = json.dumps(tools.web_doc, sort_keys=True)
    version_before = tools._doc_version

    def must_not_render(*args, **kwargs):
        raise AssertionError("viewing a saved tile must never render")

    monkeypatch.setattr(tools, "render_web_preview", must_not_render)
    # Invoke the same callable exposed to a non-rendering reviewer.
    blocks = ws.make_web_view_tool(tools, can_render=False).invoke(
        {"target": "preview:375:tile:1"}
    )
    tile = _emitted_image(blocks)
    assert tile.size == (512, 1621)
    assert tile.getpixel((256, 200)) == (255, 0, 0)
    assert tile.getpixel((256, 1400)) == (0, 0, 255)
    meta = json.loads(blocks[0]["text"])
    assert meta["source"] == {
        "target": "preview:375",
        "sha256": hashlib.sha256(original).hexdigest(),
        "pixel_width": 379,
        "pixel_height": 7464,
        "render_iteration": 1,
        "local_document_version": version_before,
    }
    assert meta["crop"] == {"x": 0, "y": 1100, "width": 379, "height": 1200}
    assert meta["tile"] == {"index": 1, "count": 7, "height": 1200, "overlap": 100}
    assert meta["document_id"] == "doc_web_test"
    assert meta["page_id"] == "home"
    assert meta["run_id"] == tools.run_id
    assert meta["persisted_revision_checked"] is False
    assert meta["coverage"] == {
        "scope": "this_call_only",
        "other_tile_index_ranges": [[0, 0], [2, 6]],
        "next_target": "preview:375:tile:2",
        "complete_source_shown": False,
    }
    assert path.read_bytes() == original
    assert list(tmp_path.glob("*.png")) == [path]
    assert json.dumps(tools.web_doc, sort_keys=True) == doc_before
    assert tools._doc_version == version_before
    assert tools.operations_ledger == []


@pytest.mark.parametrize(
    ("size", "index", "crop", "count"),
    [
        ((379, 7464), 6, {"x": 0, "y": 6600, "width": 379, "height": 864}, 7),
        ((768, 1200), 0, {"x": 0, "y": 0, "width": 768, "height": 1200}, 1),
        ((1440, 600), 0, {"x": 0, "y": 0, "width": 1440, "height": 600}, 1),
    ],
)
def test_web_preview_tile_bounds_cover_tail_and_short_pages(tmp_path, size, index, crop, count):
    tools = _bare_tools(tmp_path)
    _seed_page_capture(tmp_path, tools, 375, size)
    blocks = tools._view_content(f"preview:375:tile:{index}")
    meta = json.loads(blocks[0]["text"])
    assert meta["crop"] == crop
    assert meta["tile"]["count"] == count
    assert meta["coverage"]["next_target"] is None
    assert meta["coverage"]["complete_source_shown"] is (count == 1)
    assert meta["coverage"]["other_tile_index_ranges"] == ([] if count == 1 else [[0, 5]])
    assert max(_emitted_image(blocks).size) <= view_mod._VISION_MANY_IMAGE_MAX_PX
    refused = tools._view_content(f"preview:375:tile:{count}")
    assert len(refused) == 1
    assert "out of range" in refused[0]["text"]


@pytest.mark.parametrize("suffix", ["-1", "1.5", "0:extra", "../secret.png", "9" * 100])
def test_web_preview_tile_invalid_indexes_never_open_a_file(tmp_path, monkeypatch, suffix):
    tools = _bare_tools(tmp_path)

    def must_not_open(*args, **kwargs):
        raise AssertionError("malformed targets must be rejected before image access")

    monkeypatch.setattr(Path, "read_bytes", must_not_open)
    blocks = tools._view_content(f"preview:375:tile:{suffix}")
    assert len(blocks) == 1
    assert "invalid preview tile target" in blocks[0]["text"]


def test_web_preview_tiles_use_only_registered_capture_and_existing_stale_guards(tmp_path):
    tools = _bare_tools(tmp_path)
    # An unregistered file with the expected name is not enough to expose pixels.
    (tmp_path / "preview_375.png").write_bytes(b"unreadable")
    missing = tools._view_content("preview:375:tile:0", can_render=False)
    assert "no preview rendered" in missing[0]["text"]
    tools._preview_by_width[375] = str(tmp_path / "preview_375.png")
    tools._preview_doc_version = tools._doc_version
    tools._doc_version += 1
    # The unreadable bytes prove the stale guard runs before image decoding.
    for can_render in (False, True):
        stale = tools._view_content("preview:375:tile:0", can_render=can_render)
        assert len(stale) == 1
        assert "STALE" in stale[0]["text"]
        assert ("render_web_preview" in stale[0]["text"]) is can_render
        assert ("END YOUR REPLY" in stale[0]["text"]) is not can_render
    unsupported = tools._view_content("preview:1024:tile:0")
    assert "unknown preview width" in unsupported[0]["text"]


def test_web_preview_tile_reports_new_snapshot_identity_without_carrying_coverage(tmp_path):
    from PIL import Image

    tools = _bare_tools(tmp_path)
    _seed_page_capture(tmp_path, tools, 375, (379, 2400))
    first = json.loads(tools._view_content("preview:375:tile:0")[0]["text"])
    path = Path(tools._preview_by_width[375])
    Image.new("RGB", (379, 2400), "red").save(path)
    tools._doc_version += 1
    tools._preview_doc_version = tools._doc_version
    tools._preview_iteration = 2
    second = json.loads(tools._view_content("preview:375:tile:0")[0]["text"])
    assert second["source"]["sha256"] != first["source"]["sha256"]
    assert second["source"]["render_iteration"] == 2
    assert second["source"]["local_document_version"] == tools._doc_version
    assert second["coverage"] == first["coverage"]
    assert second["coverage"]["other_tile_index_ranges"] == [[1, 2]]


def _review_report(tools):
    return json.loads(tools._view_content("review")[0]["text"])


def test_review_report_retains_render_and_comparison_limits(tmp_path):
    tools = _bare_tools(tmp_path)
    tools._review_observations.record_walk(tools.page_id, tools._doc_version, {
        "evidence_settled": True, "advice_available": False,
        "comparison": {"status": "ok", "bands": [], "skipped": [
            {"fragment_id": "frag_footer", "because": "no_reference_geometry"},
        ]},
    })
    tools._state_capture_limits = {
        "page_id": tools.page_id, "version": tools._doc_version,
        "error": None, "omitted": {"tabs": ["omitted_tab"]},
    }
    report = _review_report(tools)
    codes = {item["code"] for item in report["gaps"]}
    assert {"review.preview_unsettled", "review.advice_unavailable",
            "review.source_bands_uncompared", "review.state_capture_incomplete"} <= codes
    assert report["clone_review"]["comparison"]["skipped"][0]["fragment_id"] == "frag_footer"
    assert report["quality_verdict"] == "not_computed"


def test_review_report_accumulates_readable_tiles_without_accepting_the_page(tmp_path):
    tools = _bare_tools(tmp_path)
    for width in (1440, 768, 375):
        _seed_page_capture(tmp_path, tools, width, (width, 2400))
        tools._view_content(f"preview:{width}")
    tools._view_content("preview:375:tile:0")
    tools._view_content("preview:375:tile:0")
    report = _review_report(tools)
    phone = report["previews"]["375"]
    assert phone["overview_shown"] is True
    assert phone["shown_tile_indexes"] == [0]
    assert phone["unseen_tile_index_ranges"] == [[1, 2]]
    assert report["quality_verdict"] == "not_computed"
    for width in (1440, 768, 375):
        for index in range(3):
            tools._view_content(f"preview:{width}:tile:{index}")
    report = _review_report(tools)
    assert report["status"] == "observations_recorded"
    assert report["quality_verdict"] == "not_computed"
    assert all(row["readable_coverage_complete"] for row in report["previews"].values())


def test_review_receipts_are_invalidated_by_document_revision_and_changed_pixels(tmp_path):
    from PIL import Image

    tools = _bare_tools(tmp_path)
    _seed_page_capture(tmp_path, tools, 375, (375, 500))
    tools._view_content("preview:375")
    assert _review_report(tools)["previews"]["375"]["readable_coverage_complete"]
    Image.new("RGB", (375, 500), "red").save(tools._preview_by_width[375])
    assert not _review_report(tools)["previews"]["375"]["readable_coverage_complete"]
    tools._view_content("preview:375")
    tools._doc_version += 1
    report = _review_report(tools)
    assert report["previews"]["375"]["status"] == "stale"
    assert report["previews"]["375"]["shown_tile_indexes"] == []


def test_state_view_refuses_stale_capture_and_supports_readable_strips(tmp_path):
    from PIL import Image

    tools = _bare_tools(tmp_path)
    path = _seed_state_capture(tmp_path, tools)
    Image.new("RGB", (1440, 3500), "white").save(path)
    tools._preview_doc_version = tools._doc_version
    tools._preview_iteration = 1
    blocks = tools._view_content("state:0:tile:1")
    meta = json.loads(blocks[0]["text"])
    assert meta["source"]["target"] == "state:0"
    assert _review_report(tools)["states"]["0"]["shown_tile_indexes"] == [1]
    tools._doc_version += 1
    assert "STALE" in tools._view_content("state:0")[0]["text"]
    assert "STALE" in tools._view_content("state:0:tile:1")[0]["text"]


def test_finalization_persists_observed_review_gaps_without_blocking_draft_save(tmp_path):
    tools = _bare_tools(tmp_path)
    _seed_page_capture(tmp_path, tools, 375, (375, 2400))
    tools._view_content("preview:375:tile:0")
    result = json.loads(tools.finalize_web_run("completed_with_warnings", "Draft saved"))
    assert result["status"] == "ok"
    evidence = result["review_evidence"]
    assert evidence["status"] == "incomplete"
    assert evidence["previews"]["375"]["unseen_tile_index_ranges"] == [[1, 2]]
    saved = json.loads((tools.turn_dir / "final.json").read_text())
    assert saved["review_evidence"] == evidence


def test_web_view_state_capture_clamps_to_the_many_image_ceiling(tmp_path: Path):
    from PIL import Image

    tools = _bare_tools(tmp_path)
    path = tmp_path / "state_1440_dialog.png"
    Image.new("RGB", (1440, 9000), "white").save(path)
    tools._state_captures = [
        {"kind": "dialog-open", "node_id": "dlg_1", "width": 1440, "path": str(path)}
    ]
    emitted = _emitted_image(tools._view_content("state:0"))
    assert max(emitted.size) <= view_mod._VISION_MANY_IMAGE_MAX_PX


def test_six_review_rounds_of_three_widths_all_ride_under_the_ceiling(tmp_path: Path):
    """The founder's review budget is 6 reviewer delegations and one render is
    three widths — so a full turn's history holds well over the 20-image
    threshold. Every one of them must be legal, not just the last."""
    tools = _bare_tools(tmp_path)
    sizes = {1440: (1440, 14325), 768: (768, 8095), 375: (375, 11200)}
    emitted = []
    for _round in range(6):
        for width, size in sizes.items():
            _seed_page_capture(tmp_path, tools, width, size)
            emitted.append(_emitted_image(tools._view_content(f"preview:{width}")))
    assert len(emitted) == 18
    # 18 previews + the orchestrator's own between-round looks is what actually
    # crossed 20 live; the assertion that matters is that EVERY image is legal.
    assert all(max(img.size) <= view_mod._VISION_MANY_IMAGE_MAX_PX for img in emitted)


# --- render_web_preview unchanged guard (the L4b analogue) -------------------


def test_render_web_preview_unchanged_guard(tmp_path: Path, monkeypatch):
    tools = _bare_tools(tmp_path)
    # Seed standing previews for EVERY width, stamped at the current doc version
    # — the exact precondition the guard short-circuits on.
    for width in ws._PREVIEW_WIDTHS:
        tools._preview_by_width[width] = str(tmp_path / f"preview_{width}.png")
    tools._preview_doc_version = tools._doc_version
    tools._preview_iteration = 1
    tools._preview_media_ready = True
    iteration_before = tools.iteration

    def _must_not_render(*args, **kwargs):
        raise AssertionError("web_render must not be called on an unchanged doc")

    monkeypatch.setattr(tools.core, "web_render", _must_not_render)

    result = json.loads(tools.render_web_preview())
    assert result["unchanged"] is True
    assert result["status"] == "ok"
    # Same paths, in width order; the state-capture list is echoed.
    assert result["preview_paths"] == [
        tools._preview_by_width[w] for w in ws._PREVIEW_WIDTHS
    ]
    assert result["diagnostics"] == []
    # No iteration bump — the guard did no work.
    assert tools.iteration == iteration_before
    assert "web_preview_unchanged" in _trace_events(tools)

    # Mutate the doc version → the guard no longer fires, so the normal path is
    # taken and the (now raising) core.web_render is reached; the render-failure
    # envelope surfaces, proving the guard was bypassed.
    from lumen_api.core import CoreError

    def _raise(*args, **kwargs):
        raise CoreError("helper.boom", "render exploded", [])

    monkeypatch.setattr(tools.core, "web_render", _raise)
    tools._doc_version += 1
    after = json.loads(tools.render_web_preview())
    assert after["status"] == "error"
    assert after["error_code"] == "web_render.failed"


def test_unsettled_media_preview_is_not_reused_for_an_unchanged_document(tmp_path, monkeypatch):
    tools = _bare_tools(tmp_path)
    for width in ws._PREVIEW_WIDTHS:
        tools._preview_by_width[width] = str(tmp_path / f"preview_{width}.png")
    tools._preview_doc_version = tools._doc_version
    tools._preview_media_ready = False
    from lumen_api.core import CoreError

    def failed_render(*args, **kwargs):
        raise CoreError("helper.unavailable", "render retry reached", [])

    monkeypatch.setattr(tools.core, "web_render", failed_render)
    result = json.loads(tools.render_web_preview())
    assert result.get("unchanged") is not True
    assert result["error_code"] == "web_render.failed"


# --- between-renders edit budget + role-aware stale views --------------------
# Live failure 2026-07-29: an author round churned blind for 14 minutes (16
# subtree rewrites) because stale views told it to call render_web_preview —
# an orchestrator-only tool — and nothing bounded the round.


def test_round_budget_refuses_mutations_then_render_reopens(tmp_path: Path, monkeypatch):
    tools = _bare_tools(tmp_path)
    tools._mutations_since_render = ws._ROUND_MUTATION_BUDGET

    refused_ops = json.loads(tools.web_ops('[{"kind": "set_text"}]'))
    assert refused_ops["status"] == "error"
    assert refused_ops["error_code"] == "round.budget_exhausted"
    assert "END YOUR REPLY" in refused_ops["message"]

    refused_page = json.loads(tools.author_web_page("<section id='s'><p>x</p></section>"))
    assert refused_page["error_code"] == "round.budget_exhausted"

    # The trace event records once per exhausted round, not per refused call.
    assert _trace_events(tools).count("web_round_budget_exhausted") == 1

    # A render means control is back with the orchestrator — the guard's
    # unchanged path is enough to prove the reset (no browser needed).
    for width in ws._PREVIEW_WIDTHS:
        path = tmp_path / f"preview_{width}.png"
        path.write_bytes(b"png")
        tools._preview_by_width[width] = str(path)
    tools._preview_doc_version = tools._doc_version
    tools._preview_iteration = 1
    tools._preview_media_ready = True
    assert json.loads(tools.render_web_preview())["status"] == "ok"
    assert tools._mutations_since_render == 0

    # Mutating calls flow again; a call past the parse gate charges the budget.
    after = json.loads(tools.web_ops("not json"))
    assert after["error_code"] == "web_ops.bad_json"
    assert tools._mutations_since_render == 1


def test_stale_view_refusal_is_role_aware(tmp_path: Path):
    tools = _bare_tools(tmp_path)
    preview = tmp_path / "preview_1440.png"
    preview.write_bytes(b"png")
    tools._preview_by_width[1440] = str(preview)
    tools._preview_doc_version = tools._doc_version
    tools._doc_version += 1  # the doc mutated after the render → stale

    orchestrator_text = tools._view_content("preview:1440", can_render=True)[0]["text"]
    assert "render_web_preview" in orchestrator_text

    subagent_text = tools._view_content("preview:1440", can_render=False)[0]["text"]
    assert "render_web_preview" not in subagent_text
    assert "END YOUR REPLY" in subagent_text

    # The no-preview refusal follows the same rule.
    tools._preview_by_width.clear()
    no_preview_sub = tools._view_content("preview:1440", can_render=False)[0]["text"]
    assert "render_web_preview" not in no_preview_sub


# --- render thread affinity + renderer circuit breaker -----------------------
# Live failure 2026-07-29 (run_841ee2c8): the kept-alive browser was launched
# on one framework pool thread; every later render ran on another and died on
# Playwright's greenlet guard ("cannot switch to a different thread"), and the
# orchestrator burned ~25 retry model calls before giving up on its own.


def test_all_playwright_work_runs_on_one_dedicated_thread(tmp_path: Path, monkeypatch):
    import threading as _threading

    tools = _bare_tools(tmp_path)
    # The helper render is not under test — return bare HTML.
    monkeypatch.setattr(
        tools.core, "web_render", lambda *a, **k: {"html": "<html></html>", "diagnostics": []}
    )
    capture_threads: list[int] = []

    def fake_capture(html, iter_dir, diagnostics):
        capture_threads.append(_threading.get_ident())
        return ([], None, {})

    monkeypatch.setattr(tools, "_capture_pass", fake_capture)

    assert json.loads(tools.render_web_preview())["status"] == "ok"
    tools._doc_version += 1  # defeat the unchanged guard
    assert json.loads(tools.render_web_preview())["status"] == "ok"

    caller = _threading.get_ident()
    assert len(capture_threads) == 2
    # Same dedicated thread both times, and never the caller's thread.
    assert capture_threads[0] == capture_threads[1] != caller
    assert capture_threads[0] == tools._run_on_render_thread(_threading.get_ident)


def test_greenlet_thread_fault_counts_as_dead_browser():
    error = Exception("cannot switch to a different thread (which happens to have exited)")
    assert LumenWebTools._looks_like_dead_browser(error)


def test_render_circuit_breaker_opens_after_consecutive_failures(
    tmp_path: Path, monkeypatch
):
    tools = _bare_tools(tmp_path)
    monkeypatch.setattr(
        tools.core, "web_render", lambda *a, **k: {"html": "<html></html>", "diagnostics": []}
    )
    calls = {"n": 0}

    def broken_capture(html, iter_dir, diagnostics):
        calls["n"] += 1
        raise ValueError("capture exploded")

    monkeypatch.setattr(tools, "_capture_pass", broken_capture)

    for attempt in range(ws._RENDER_FAILURE_LIMIT):
        tools._doc_version += 1
        result = json.loads(tools.render_web_preview())
        assert result["error_code"] == "web_preview.capture_failed"

    # Breaker open: no further capture attempt, an explicit finalize demand.
    tools._doc_version += 1
    refused = json.loads(tools.render_web_preview())
    assert refused["error_code"] == "web_preview.renderer_down"
    assert "finalize_web_run" in refused["message"]
    assert calls["n"] == ws._RENDER_FAILURE_LIMIT
    assert "web_preview_render_circuit_open" in _trace_events(tools)

    # A later successful pass (e.g. after a process-level fix) resets the
    # breaker — prove the reset path by clearing the counter as success does.
    monkeypatch.setattr(tools, "_capture_pass", lambda *a: ([], None, {}))
    tools._consecutive_render_failures = ws._RENDER_FAILURE_LIMIT - 1
    tools._doc_version += 1
    assert json.loads(tools.render_web_preview())["status"] == "ok"
    assert tools._consecutive_render_failures == 0


# --- browser reuse: _close_browser + finalize teardown ----------------------


def test_close_browser_idempotent_without_playwright(tmp_path: Path):
    # A fresh substrate never started Playwright; closing (twice) is a safe no-op.
    tools = _bare_tools(tmp_path)
    assert tools._browser is None and tools._pw is None
    tools._close_browser()
    tools._close_browser()
    assert tools._browser is None and tools._pw is None


class _RecordingBrowser:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _RecordingPw:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_finalize_web_run_closes_browser(tmp_path: Path):
    tools = _bare_tools(tmp_path)
    browser = _RecordingBrowser()
    pw = _RecordingPw()
    tools._browser = browser
    tools._pw = pw

    result = json.loads(tools.finalize_web_run("accepted", "done"))
    assert result["status"] == "ok"
    # Both handles were closed/stopped and reset to None.
    assert browser.closed is True
    assert pw.stopped is True
    assert tools._browser is None and tools._pw is None


# --- P5 account personalization: use_account_asset + view("account") --------

# Smallest valid PNG (1x1) — a real logo the helper can ingest + upsert.
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)


def _ingest_account_logo(config, asset_id: str = "acc_logo_1") -> dict:
    """Ingest a logo into the config's asset store and return its engine
    AssetRecord — the shape the API's resolve_account_assets manifests."""
    from lumen_api.core import CoreClient

    core = CoreClient(repo_root=REPO_ROOT)
    ingest = core.ingest_asset(
        store_root=str(config.effective_asset_store_root),
        bytes_base64=base64.b64encode(_TINY_PNG).decode("ascii"),
        asset_id=asset_id,
        label="Account logo",
        declared_mime_type="image/png",
        kind="raster_image",
        raise_on_error=False,
    )
    assert ingest.get("ok"), ingest
    return ingest["asset"]["record"]


def _account_tools(
    tmp_path: Path, *, logo_id: str | None = "acc_logo_1", in_manifest: bool = True
) -> LumenWebTools:
    """LumenWebTools with a TARGET ACCOUNT over the REAL helper (upsert path)."""
    from lumen_api.core import CoreClient

    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT), trace_dir=tmp_path / "workspace_root"
    )
    account_assets = None
    if logo_id and in_manifest:
        record = _ingest_account_logo(config, logo_id)
        account_assets = {logo_id: {"record": record, "title": "Account logo"}}
    account_card = {
        "name": "Privia Health",
        "domain": "privia.com",
        "logo_asset_id": logo_id,
        "data": {},
        "notes": None,
    }
    config = replace(config, account_card=account_card, account_assets=account_assets)
    core = CoreClient(repo_root=REPO_ROOT)
    seed = core.web_new_doc("doc_acct_test", "Test site", None)["web_doc"]
    return LumenWebTools(config, "Personalize the page", initial_web_doc=seed)


def test_use_account_asset_registers_logo(tmp_path: Path):
    tools = _account_tools(tmp_path)
    result = json.loads(tools.asset("use_account_asset", alt="Privia logo"))
    assert result["status"] == "ok", result
    assert result["asset_id"] == "acc_logo_1"
    # The logo record now lives in the working doc's asset map.
    assert "acc_logo_1" in (tools.web_doc.get("assets") or {})
    assert tools._doc_version == 1


def test_use_account_asset_errors_without_account_card(tmp_path: Path):
    tools = _bare_tools(tmp_path)  # no account_card
    result = json.loads(tools.asset("use_account_asset"))
    assert result["status"] == "error"
    assert result["error_code"] == "asset.no_account"


def test_use_account_asset_errors_without_logo(tmp_path: Path):
    # An account with no logo id: honest "no logo", not a crash.
    tools = _account_tools(tmp_path, logo_id=None)
    result = json.loads(tools.asset("use_account_asset"))
    assert result["status"] == "error"
    assert result["error_code"] == "asset.no_account_logo"


def test_use_account_asset_errors_when_logo_missing_from_manifest(tmp_path: Path):
    # The card names a logo but the by-value manifest lacks its record.
    tools = _account_tools(tmp_path, in_manifest=False)
    result = json.loads(tools.asset("use_account_asset"))
    assert result["status"] == "error"
    assert result["error_code"] == "asset.no_account_logo"


def test_view_account_returns_card(tmp_path: Path):
    card = {
        "name": "Privia Health",
        "domain": "privia.com",
        "logo_asset_id": None,
        "data": {"cta": "Book a demo"},
        "notes": "context",
    }
    tools = _bare_tools(tmp_path, account_card=card)
    blocks = tools._view_content("account")
    assert len(blocks) == 1
    text = blocks[0]["text"]
    assert "Privia Health" in text
    assert "Book a demo" in text


def test_view_account_none_when_unpersonalized(tmp_path: Path):
    tools = _bare_tools(tmp_path)  # no account
    blocks = tools._view_content("account")
    assert "No target account" in blocks[0]["text"]


# --- D1: asset(action="generate_image") on the web lane ---------------------
#
# This path had ZERO coverage and had never once succeeded: the stub request
# sent `"brand_notes": None`, and `AssetGenerationConstraints.brand_notes` is a
# `Vec<String>` behind `#[serde(default)]` — which fires on an ABSENT key, never
# on an explicit null. Every call died with
# `invalid type: null, expected a sequence`, so the web author got
# `asset.image_failed` for every image it ever tried to generate.


def test_generate_image_falls_back_to_the_stub_provider(tmp_path: Path, monkeypatch):
    """No T2I model configured → the deterministic stub still produces a real,
    registered asset. RED before the brand_notes fix (serde rejected the null)."""
    monkeypatch.setattr(ws, "image_provider", None)
    tools = _tools(tmp_path)

    result = json.loads(tools.asset(action="generate_image", prompt="A calm hero field"))

    assert result["status"] == "ok", result
    asset_id = result["asset_id"]
    assert asset_id in (tools.web_doc.get("assets") or {})
    assert result["mode"] == "placeholder"


def test_generate_image_request_never_sends_a_null_for_a_rust_vec(tmp_path: Path, monkeypatch):
    """Shape guard on the stub request: every field the Rust side types as a
    `Vec` must ride as a list (or be absent), never as an explicit `null` —
    `#[serde(default)]` does not cover null."""
    monkeypatch.setattr(ws, "image_provider", None)
    tools = _tools(tmp_path)
    captured: dict = {}

    real = tools.core.generate_asset

    def spy(**kwargs):
        captured.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(tools.core, "generate_asset", spy)
    json.loads(tools.asset(action="generate_image", prompt="A calm hero field"))

    constraints = captured["request"]["constraints"]
    assert isinstance(constraints["brand_notes"], list), constraints
    # No sibling in the request may be an explicit null for a Vec-typed field.
    for key in ("brand_notes", "reference_asset_ids"):
        assert constraints.get(key, []) is not None


def test_generate_image_uses_the_configured_model_when_available(tmp_path: Path, monkeypatch):
    """With a configured provider the real T2I result is ingested and registered,
    and the reported mode/model name the model — not the placeholder."""
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )

    class _FakeProvider:
        @staticmethod
        def is_configured():
            return True

        @staticmethod
        def generate(**kwargs):
            captured.update(kwargs)
            return ws_result

    captured: dict = {}

    class _Result:
        image_bytes = png
        mime_type = "image/png"
        model = "google/gemini-3.1-flash-image"
        provenance = {"created_by": "agent", "notes": []}
        license = None

    ws_result = _Result()
    monkeypatch.setattr(ws, "image_provider", _FakeProvider)
    tools = _tools(tmp_path)

    result = json.loads(
        tools.asset(action="generate_image", prompt="A calm hero field", aspect_ratio="16:9")
    )

    assert result["status"] == "ok", result
    assert result["mode"] == "model"
    assert result["model"] == "google/gemini-3.1-flash-image"
    assert result["asset_id"] in (tools.web_doc.get("assets") or {})
    # brand_notes rides as a LIST even when the caller has none to give.
    assert isinstance(captured["brand_notes"], list)
    assert captured["aspect_ratio"] == "16:9"


def test_generate_image_aspect_ratio_reaches_the_images_api_body(tmp_path: Path, monkeypatch):
    """FOUNDER RULE (2026-08-23): the deepagent must be able to specify the
    aspect ratio. The neighbouring test stops at the provider seam; this one runs
    the REAL `image_provider` on the gpt-image-2 (`IMAGE_MODEL_API_STYLE=images`)
    transport with only the ProviderCaller transport mocked, so the whole chain —
    `asset(aspect_ratio=...)` → `_generate_image_record` → `generate` →
    `_invoke_images_api` → the wire body's STRUCTURED `aspect_ratio` — is pinned
    end to end. Its `21:9` also proves the closed-enum snap survives the trip:
    the agent asks for an unsupported 5:2 and the endpoint sees a legal member.
    """
    from lumen_api import image_provider as real_image_provider
    from lumen_api import spend
    from py_lumen_config import settings

    from clue_spend import HttpResponse, LedgerStamp

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    monkeypatch.setattr(settings, "image_model_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "image_model_api_key", "test-key")
    monkeypatch.setattr(settings, "image_model_id", "openai/gpt-image-2")
    monkeypatch.setattr(settings, "image_model_api_style", "images")
    monkeypatch.setattr(real_image_provider, "is_configured", lambda: True)
    monkeypatch.setattr(ws, "image_provider", real_image_provider)

    captured: dict = {}

    class Transport:
        def send(self, request):
            assert request.method == "POST"
            assert request.headers["Authorization"] == "Bearer test-key"
            captured.update(url=request.url, json=json.loads(request.body))
            return HttpResponse(
                status=200,
                headers={"content-type": "application/json"},
                body=json.dumps({
                    "data": [{"b64_json": base64.b64encode(png).decode("ascii")}]
                }).encode("utf-8"),
            )

    tools = _tools(tmp_path)
    with spend.spend_scope(
        LedgerStamp(workspace_id="ws_image_ratio_test"), transport=Transport()
    ):
        result = json.loads(
            tools.asset(action="generate_image", prompt="A calm hero field", aspect_ratio="5:2")
        )

    assert result["status"] == "ok", result
    assert result["mode"] == "model"
    assert captured["url"] == "https://openrouter.ai/api/v1/images"
    assert captured["json"]["aspect_ratio"] == "21:9"
    assert captured["json"]["quality"] == "high"
    assert captured["json"]["background"] == "auto"
    assert "messages" not in captured["json"]


def test_generate_image_records_a_diagnostic_when_the_model_fails(tmp_path: Path, monkeypatch):
    """A real-provider failure degrades to the stub LOUDLY: the page still gets
    an image, and the tool reports why the model did not serve it. Before the fix
    this was a bare `except Exception: pass` — a silent swallow."""

    class _BrokenProvider:
        @staticmethod
        def is_configured():
            return True

        @staticmethod
        def generate(**kwargs):
            raise RuntimeError("upstream 502")

    monkeypatch.setattr(ws, "image_provider", _BrokenProvider)
    tools = _tools(tmp_path)

    result = json.loads(tools.asset(action="generate_image", prompt="A calm hero field"))

    assert result["status"] == "ok", result
    assert result["mode"] == "placeholder"
    messages = " ".join(str(d.get("message", "")) for d in result.get("diagnostics") or [])
    assert "placeholder" in messages.lower()
    assert "RuntimeError" in messages or "502" in messages


def _brand_kit_with_style(*, images: dict | None = None) -> dict:
    return {
        "id": "brand_kit_web_test",
        "version": 1,
        "name": "Acme",
        "tokens": {
            "colors": {
                "surface.brand": {
                    "value": {"default": {"kind": "hex", "value": "#231d40"}}
                }
            },
            "typography": {},
        },
        "assets": {"fonts": {}, "logos": {}, "images": images or {}},
        "constraints": {"tone": ["precise", "calm"], "imagery": ["No lifestyle stock"]},
        "brief": {
            "schema_version": 1,
            "characterization": {
                "words": ["precise", "product-led", "infrastructural"],
                "support": "Every band is a product surface.",
                "confidence": "high",
            },
        },
    }


def test_generated_imagery_is_conditioned_on_the_brand(tmp_path: Path, monkeypatch):
    """The founder's actual complaint behind D2: generated imagery must look like
    THIS brand's imagery. The kit's characterization, imagery rules, tone, and
    palette ride every generation as style direction."""
    captured: dict = {}

    class _Provider:
        @staticmethod
        def is_configured():
            return True

        @staticmethod
        def generate(**kwargs):
            captured.update(kwargs)
            raise RuntimeError("stop here — the request is what this test judges")

    monkeypatch.setattr(ws, "image_provider", _Provider)
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        brand_kit=_brand_kit_with_style(),
    )
    from lumen_api.core import CoreClient

    core = CoreClient(repo_root=REPO_ROOT)
    seed = core.web_new_doc("doc_web_brand", "Test site", None)["web_doc"]
    tools = LumenWebTools(config, "Build a page", initial_web_doc=seed)

    json.loads(tools.asset(action="generate_image", prompt="A hero field"))

    notes = captured["brand_notes"]
    assert isinstance(notes, list) and notes
    joined = " | ".join(notes)
    assert "precise, product-led, infrastructural" in joined
    assert "No lifestyle stock" in joined
    assert "brand tone: precise, calm" in joined
    assert "#231d40" in joined


def test_brand_style_references_never_include_a_logo(tmp_path: Path):
    """A logo passed as a STYLE reference gets drawn into the picture. Only the
    kit's brand IMAGES may condition a generation."""
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        brand_kit=_brand_kit_with_style(),  # logos present, images empty
        brand_kit_assets={"logo_asset": {"record": {"id": "logo_asset"}}},
    )
    tools = _bare_tools(tmp_path)
    tools.config = config
    references, labels = tools._brand_style_references()
    assert references is None
    assert labels == []


def test_brand_style_references_skip_assets_whose_bytes_are_gone(tmp_path: Path):
    """A kit published elsewhere is a normal state — degrade to a plain
    text-conditioned generation, never an error."""
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        brand_kit=_brand_kit_with_style(
            images={"hero": {"asset_id": "img_hero", "title": "Hero texture"}}
        ),
        brand_kit_assets={
            "img_hero": {
                "record": {
                    "id": "img_hero",
                    "media": {"digest": {"algorithm": "sha256", "value": "f" * 64}},
                }
            }
        },
    )
    tools = _bare_tools(tmp_path)
    tools.config = config
    references, labels = tools._brand_style_references()
    assert references is None
    assert labels == []


def test_brand_style_references_carry_the_kits_own_image_bytes(tmp_path: Path):
    """The bonus the founder asked for: when the kit ships real brand imagery,
    those pixels ride the generation as STYLE anchors."""
    store_root = tmp_path / "asset-store"
    digest = "a" * 64
    blob = store_root / "sha256" / digest[:2] / digest
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(_TINY_PNG)

    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        asset_store_root=store_root,
        brand_kit=_brand_kit_with_style(
            images={"hero": {"asset_id": "img_hero", "title": "Hero texture"}}
        ),
        brand_kit_assets={
            "img_hero": {
                "record": {
                    "id": "img_hero",
                    "media": {
                        "mime_type": "image/png",
                        "digest": {"algorithm": "sha256", "value": digest},
                    },
                    "raster": {"pixel_width": 2048, "pixel_height": 1024},
                }
            }
        },
    )
    tools = _bare_tools(tmp_path)
    tools.config = config
    references, labels = tools._brand_style_references()
    assert references == [(_TINY_PNG, "image/png")]
    assert labels == ["Hero texture"]


# --- style-anchor selection: ordering and the resolution floor --------------
#
# Two defects found on the approved kits, 2026-08-20. Both silently degraded
# every generated image on every page.


def _style_image_entry(
    tmp_path: Path, asset_id: str, *, width: int, height: int
) -> tuple[Path, dict]:
    """A kit image whose bytes really exist in a per-test store, so the picker
    reaches its ordering/floor decisions instead of skipping on missing blobs."""
    store_root = tmp_path / "asset-store"
    digest = hashlib.sha256(asset_id.encode()).hexdigest()
    blob = store_root / "sha256" / digest[:2] / digest
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(_TINY_PNG)
    return store_root, {
        "record": {
            "id": asset_id,
            "media": {
                "mime_type": "image/png",
                "digest": {"algorithm": "sha256", "value": digest},
            },
            "raster": {"pixel_width": width, "pixel_height": height},
        }
    }


def test_a_kits_image_ordinal_is_read_numerically_not_alphabetically(tmp_path: Path):
    """`img.{n}` is the ingestion pipeline's own quality ranking (emit.py numbers
    an evidence list already sorted by area then file size, descending). A STRING
    sort orders `img.1, img.10, img.11, … img.2`, so the second style anchor was
    always `img.10` and `img.2` was unreachable at _BRAND_REFERENCE_MAX = 2.
    On the approved v6 kit that made a 296x124 thumbnail half the conditioning of
    every generated image."""
    store_root = None
    manifest: dict = {}
    images: dict = {}
    for ordinal in (1, 2, 10, 11):
        asset_id = f"asset_{ordinal}"
        store_root, entry = _style_image_entry(
            tmp_path, asset_id, width=2048, height=1024
        )
        manifest[asset_id] = entry
        images[f"img.{ordinal}"] = {"asset_id": asset_id, "title": f"Image {ordinal}"}

    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        asset_store_root=store_root,
        brand_kit=_brand_kit_with_style(images=images),
        brand_kit_assets=manifest,
    )
    tools = _bare_tools(tmp_path)
    tools.config = config

    _, labels = tools._brand_style_references()

    assert labels == ["Image 1", "Image 2"]


def test_a_key_that_is_not_an_ordinal_sorts_last_rather_than_raising(tmp_path: Path):
    """A kit shape we do not recognize must degrade, never crash a turn."""
    store_root, ordinal_entry = _style_image_entry(
        tmp_path, "asset_ordinal", width=2048, height=1024
    )
    _, odd_entry = _style_image_entry(tmp_path, "asset_odd", width=2048, height=1024)

    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        asset_store_root=store_root,
        brand_kit=_brand_kit_with_style(
            images={
                "hero-banner": {"asset_id": "asset_odd", "title": "Odd key"},
                "img.9": {"asset_id": "asset_ordinal", "title": "Ranked"},
            }
        ),
        brand_kit_assets={"asset_odd": odd_entry, "asset_ordinal": ordinal_entry},
    )
    tools = _bare_tools(tmp_path)
    tools.config = config

    _, labels = tools._brand_style_references()

    assert labels == ["Ranked", "Odd key"]


def test_a_low_resolution_image_may_not_anchor_a_generation(tmp_path: Path):
    """Kit v8 carries a 64x64 icon and a QR code. Conditioning a hero on those is
    worse than conditioning on nothing — and the picker must NOT backfill down
    the ranking to reach _BRAND_REFERENCE_MAX."""
    store_root, big = _style_image_entry(tmp_path, "asset_big", width=2048, height=1024)
    _, icon = _style_image_entry(tmp_path, "asset_icon", width=64, height=64)
    _, qr = _style_image_entry(tmp_path, "asset_qr", width=296, height=124)

    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        asset_store_root=store_root,
        brand_kit=_brand_kit_with_style(
            images={
                "img.1": {"asset_id": "asset_big", "title": "Hero"},
                "img.2": {"asset_id": "asset_icon", "title": "Icon"},
                "img.3": {"asset_id": "asset_qr", "title": "QR"},
            }
        ),
        brand_kit_assets={"asset_big": big, "asset_icon": icon, "asset_qr": qr},
    )
    tools = _bare_tools(tmp_path)
    tools.config = config

    references, labels = tools._brand_style_references()

    assert labels == ["Hero"]
    assert references is not None and len(references) == 1


def test_a_kit_of_only_thumbnails_yields_no_anchors_at_all(tmp_path: Path):
    """Fewer anchors — or none — is the correct outcome; the generation then runs
    plain text-conditioned, which is what the caller already handles."""
    store_root, icon = _style_image_entry(tmp_path, "asset_icon", width=64, height=64)
    _, qr = _style_image_entry(tmp_path, "asset_qr", width=296, height=124)

    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        asset_store_root=store_root,
        brand_kit=_brand_kit_with_style(
            images={
                "img.1": {"asset_id": "asset_icon", "title": "Icon"},
                "img.2": {"asset_id": "asset_qr", "title": "QR"},
            }
        ),
        brand_kit_assets={"asset_icon": icon, "asset_qr": qr},
    )
    tools = _bare_tools(tmp_path)
    tools.config = config

    references, labels = tools._brand_style_references()

    assert references is None
    assert labels == []


def test_an_image_with_no_recorded_dimensions_does_not_clear_the_floor(tmp_path: Path):
    """Unknown is not "good enough" for something that steers every generation."""
    store_root, entry = _style_image_entry(
        tmp_path, "asset_unknown", width=2048, height=1024
    )
    entry["record"].pop("raster")

    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        asset_store_root=store_root,
        brand_kit=_brand_kit_with_style(
            images={"img.1": {"asset_id": "asset_unknown", "title": "Unknown"}}
        ),
        brand_kit_assets={"asset_unknown": entry},
    )
    tools = _bare_tools(tmp_path)
    tools.config = config

    references, labels = tools._brand_style_references()

    assert references is None
    assert labels == []


def test_generate_image_reports_when_no_model_is_configured(tmp_path: Path, monkeypatch):
    """The honest 'you are getting a placeholder because nothing is wired' note."""

    class _UnconfiguredProvider:
        @staticmethod
        def is_configured():
            return False

    monkeypatch.setattr(ws, "image_provider", _UnconfiguredProvider)
    tools = _tools(tmp_path)

    result = json.loads(tools.asset(action="generate_image", prompt="A calm hero field"))

    assert result["status"] == "ok", result
    assert result["mode"] == "placeholder"
    messages = " ".join(str(d.get("message", "")) for d in result.get("diagnostics") or [])
    assert "IMAGE_MODEL" in messages


# --- the advice channel: LUMW0306 reaches the agent, in its own bucket -------
#
# Advice used to land in `warnings`, and the author prompt calls warnings
# mandatory work — so an advisory line arrived as an obligation. These pin the
# split, and the one finding that rides it.

ACME_KIT_PATH = REPO_ROOT / "crates/lumen-core/fixtures/brand_kits/acme_full.json"

RAW_GEOMETRY_HTML = """
<section id="cards" class="bg-light">
  <div class="mx-auto max-w-[1200px] px-6 py-20 flex flex-col gap-6">
    <div class="rounded-2xl shadow-lg p-6"><p class="text-muted">First card.</p></div>
    <div class="rounded-2xl shadow-lg p-6"><p class="text-muted">Second card.</p></div>
  </div>
</section>
"""


def _kit(briefed: bool) -> dict:
    kit = json.loads(ACME_KIT_PATH.read_text(encoding="utf-8"))
    if briefed:
        kit["brief"] = {
            "schema_version": 1,
            "characterization": {"words": ["measured", "calm"]},
        }
    return kit


def _kitted_tools(tmp_path: Path, *, briefed: bool) -> LumenWebTools:
    from lumen_api.core import CoreClient

    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        brand_kit=_kit(briefed),
    )
    core = CoreClient(repo_root=REPO_ROOT)
    seed = core.web_new_doc("doc_web_test", "Test site", None)["web_doc"]
    return LumenWebTools(config, "Build a page", initial_web_doc=seed)


def _codes(diagnostics) -> list[str]:
    return [d.get("code") for d in diagnostics or []]


def test_briefed_kit_advice_is_its_own_bucket(tmp_path: Path):
    tools = _kitted_tools(tmp_path, briefed=True)
    result = json.loads(tools.author_web_page(RAW_GEOMETRY_HTML))

    assert result["status"] == "ok", result
    # The finding arrives as advice…
    assert "LUMW0306" in _codes(result["advice"]), result
    assert all(d.get("severity") == "advice" for d in result["advice"]), result
    # …and never as work.
    assert "LUMW0306" not in _codes(result["warnings"]), result
    assert all(d.get("severity") != "advice" for d in result["warnings"]), result
    # One line per raw class across both cards, naming the class.
    messages = " ".join(str(d.get("message")) for d in result["advice"])
    assert messages.count("`rounded-2xl`") == 1, messages
    assert "`shadow-lg`" in messages, messages

    # The trace keeps the whole non-error picture.
    lines = (tools.trace_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    traced = [
        code
        for line in lines
        for code in _codes(json.loads(line).get("diagnostics"))
    ]
    assert "LUMW0306" in traced


def test_an_unbriefed_kit_authors_the_same_page_without_advice(tmp_path: Path):
    tools = _kitted_tools(tmp_path, briefed=False)
    result = json.loads(tools.author_web_page(RAW_GEOMETRY_HTML))

    assert result["status"] == "ok", result
    assert "LUMW0306" not in _codes(result["advice"]), result
    assert "LUMW0306" not in _codes(result["warnings"]), result
    body = tools.trace_dir.joinpath("trace.jsonl").read_text(encoding="utf-8")
    assert "LUMW0306" not in body


def test_geometry_advice_never_rejects_a_page(tmp_path: Path):
    """A page saturated with raw geometry on a briefed kit still stores."""
    tools = _kitted_tools(tmp_path, briefed=True)
    saturated = "\n".join(
        f'<section id="s{index}" class="rounded-2xl shadow-lg">'
        f'<div class="rounded-2xl shadow-xl p-6"><p>Card {index}.</p></div></section>'
        for index in range(8)
    )
    result = json.loads(tools.author_web_page(saturated))

    assert result["status"] == "ok", result
    assert result["installed_nodes"] > 0
    assert tools._doc_version == 1
    assert result["advice"], "the advice should still be reported"


REJECTED_GEOMETRY_HTML = """
<section id="cards" class="bg-light">
  <div class="mx-auto max-w-[1200px] px-6 py-20 flex flex-col gap-6">
    <div class="rounded-2xl shadow-lg p-6 bg-[#ff0000]"><p class="text-muted">First card.</p></div>
    <div class="rounded-2xl shadow-lg p-6"><p class="text-muted">Second card.</p></div>
  </div>
</section>
"""


def test_a_rejection_hands_back_work_only_and_advice_separately(tmp_path: Path):
    """The turn where this matters most: a briefed kit, one genuine error, and
    raw geometry everywhere. `create-website` says "fix ALL the diagnostics in
    ONE patch call" — so an advisory line inside `diagnostics` would spend the
    repair round rewriting radii nobody asked to change."""
    tools = _kitted_tools(tmp_path, briefed=True)
    result = json.loads(tools.author_web_page(REJECTED_GEOMETRY_HTML))

    assert result["status"] == "rejected", result
    # The work list is the work: the raw hex, and nothing advisory.
    assert "LUMW0210" in _codes(result["diagnostics"]), result
    assert "LUMW0306" not in _codes(result["diagnostics"]), result
    assert all(
        d.get("severity") != "advice" for d in result["diagnostics"]
    ), result
    # The advice is still delivered — under its own key.
    assert "LUMW0306" in _codes(result["advice"]), result

    # And the patch flow repairs from the same work-only list.
    pending = tools._last_rejected_authoring
    assert pending is not None
    assert "LUMW0210" in _codes(pending["diagnostics"])
    assert "LUMW0306" not in _codes(pending["diagnostics"])
    assert all(d.get("severity") != "advice" for d in pending["diagnostics"])

    # Nothing was stored, exactly as before.
    assert tools._doc_version == 0
    assert not (tools._home_page().get("nodes") or {}).get("cards")


def test_an_unbriefed_rejection_carries_no_geometry_advice(tmp_path: Path):
    """Same markup, no brief: the rejection still separates the two species —
    this kit's LUMW0305 theme-geometry fallbacks are advice too — but nothing
    about the author's raw radii is said."""
    tools = _kitted_tools(tmp_path, briefed=False)
    result = json.loads(tools.author_web_page(REJECTED_GEOMETRY_HTML))

    assert result["status"] == "rejected", result
    assert "LUMW0210" in _codes(result["diagnostics"])
    assert "LUMW0306" not in _codes(result["advice"]), result
    assert "LUMW0306" not in _codes(result["diagnostics"]), result
    assert all(d.get("severity") != "advice" for d in result["diagnostics"])
    # The patch flow repairs from exactly what the agent was handed.
    assert result["diagnostics"] == tools._last_rejected_authoring["diagnostics"]


# --- registered-but-unplaced assets survive a full-page ingest (solo run, 2026-09-04) -----


def test_unplaced_registered_asset_survives_full_page_author_and_replay(
    tmp_path: Path, monkeypatch
):
    """The commit gate's own invariant, red before the carry-forward fix.

    On the live Ramp ABM solo run (2026-09-04), the accepted full-page ingest came back
    WITHOUT an asset that was registered mid-turn but not referenced by the final markup,
    while the append-only operations ledger kept its ``upsert_asset`` — so the API's
    replay-equality gate refused the whole turn (``web_turn.operations_incomplete``) and a
    finished 16-minute page was discarded. The exact core-side drop condition depends on
    live-only state (brand kit present), so this test simulates the drop AT THE SEAM: the
    ingest response is stripped of unreferenced assets, and the accept path must still
    guarantee that (a) a registered asset survives and (b) replaying the ledger reproduces
    the working doc byte for byte — which is what the API commits on.
    """
    tools = _tools(tmp_path)
    real_ingest = tools.core.web_ingest_html

    def pruning_ingest(*args, **kwargs):
        response = real_ingest(*args, **kwargs)
        web_doc = response.get("web_doc")
        if isinstance(web_doc, dict) and isinstance(web_doc.get("assets"), dict):
            referenced = json.dumps(web_doc.get("pages"))
            web_doc["assets"] = {
                asset_id: record
                for asset_id, record in web_doc["assets"].items()
                if asset_id in referenced
            }
        return response

    monkeypatch.setattr(tools.core, "web_ingest_html", pruning_ingest)
    record = {
        "id": "asset_ing_0123456789abcdef",
        "kind": "raster_image",
        "status": "ready",
        "tags": ["test"],
        "label": "registered-but-never-placed.png",
        "media": {
            "digest": {
                "value": "01fbbe4cbdccae8288fe7592a1dad5ae5159aae70915dbed012b72a864eb09b8",
                "algorithm": "sha256",
            },
            "filename": "registered-but-never-placed.png",
            "location": {
                "url": None,
                "provider": "clue-storage",
                "opaque_ref": "test/registered-but-never-placed",
            },
            "mime_type": "image/png",
            "thumbnail": None,
            "byte_length": 1024,
        },
        "raster": {
            "dpi_x": None,
            "dpi_y": None,
            "has_alpha": True,
            "pixel_width": 64,
            "aspect_ratio": 1.0,
            "pixel_height": 64,
            "color_profile": None,
        },
        "source": {"kind": "uploaded", "source_asset_id": None, "label": "test upload"},
        "provenance": {
            "notes": [],
            "confidence": 1.0,
            "created_at": "2026-09-04T00:00:00+00:00",
            "created_by": "test",
            "source_label": "test",
        },
        "font": None,
        "logo": None,
        "vector": None,
        "license": None,
    }
    before_registration = json.loads(json.dumps(tools.web_doc))
    registered = tools._register_asset_record(
        record, origin="test", label=record["label"], alt=None, extra={}
    )
    assert registered, "registration itself must succeed for this test to mean anything"
    assert "asset_ing_0123456789abcdef" in (tools.web_doc.get("assets") or {})

    # The full-page author does NOT reference the registered asset.
    result = json.loads(tools.author_web_page(SAMPLE_HTML))
    assert result["status"] == "ok", result

    # The registered asset survived the ingest...
    assert "asset_ing_0123456789abcdef" in (tools.web_doc.get("assets") or {}), (
        "a registered asset must survive a full-page ingest — dropping it while the "
        "ledger keeps its upsert is exactly the replay divergence that failed the turn"
    )
    # ...and the ledger reproduces the working doc, which is what the API commits on.
    replay = tools.core.web_apply_ops(before_registration, tools.operations_ledger)
    assert replay["web_doc"] == tools.web_doc
