"""LumenWebTools unit coverage.

Two layers: pure-Python token-name derivation (no helper), and the
author_web_page happy path against the REAL core helper (deterministic — HTML
ingest only, no LLM or browser).
"""

from __future__ import annotations

import base64
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


# --- render_web_preview unchanged guard (the L4b analogue) -------------------


def test_render_web_preview_unchanged_guard(tmp_path: Path, monkeypatch):
    tools = _bare_tools(tmp_path)
    # Seed standing previews for EVERY width, stamped at the current doc version
    # — the exact precondition the guard short-circuits on.
    for width in ws._PREVIEW_WIDTHS:
        tools._preview_by_width[width] = str(tmp_path / f"preview_{width}.png")
    tools._preview_doc_version = tools._doc_version
    tools._preview_iteration = 1
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
