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
from lumen_agent.tools.web_substrate import (
    LumenWebTools,
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
