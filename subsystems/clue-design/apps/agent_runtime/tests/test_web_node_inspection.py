"""Bounded active-page node reads and safe read/edit round trips against the real helper."""

from __future__ import annotations

import copy
import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools.web_substrate import LumenWebTools, make_web_view_tool
from lumen_api.core import CoreClient

REPO_ROOT = Path(__file__).resolve().parents[3]
HTML = """
<section id="hero" class="bg-light">
  <h1 id="headline">A human-approved headline</h1>
  <p id="body" class="text-muted">Original body</p>
  <a id="cta" data-button="secondary" href="https://example.test/start"
     target="_blank" class="mt-4">Start here</a>
</section>
<section id="proof"><p id="untouched">Keep this section.</p></section>
"""


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refused(*args, **kwargs):
        raise AssertionError("node inspection tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", refused)


def _tools(tmp_path: Path, *, doc_id: str = "doc_inspection") -> LumenWebTools:
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace",
        asset_store_root=tmp_path / "assets",
    )
    seed = CoreClient(repo_root=REPO_ROOT).web_new_doc(doc_id, "Scoped edits", None)["web_doc"]
    tools = LumenWebTools(config, "Inspect before editing", initial_web_doc=seed)
    result = json.loads(tools.author_web_page(HTML))
    assert result["status"] == "ok", result
    return tools


def _read(tools: LumenWebTools, node_id: str, *, can_render: bool = False) -> dict:
    blocks = make_web_view_tool(tools, can_render=can_render).invoke({"target": f"node:{node_id}"})
    assert isinstance(blocks, list) and len(blocks) == 1, blocks
    assert blocks[0]["type"] == "text", blocks
    text = blocks[0]["text"]
    assert text.startswith("{"), f"Expected a node snapshot/refusal, got: {text}"
    return json.loads(text)


def _ops(tools: LumenWebTools, operations: list[dict]) -> None:
    result = json.loads(tools.web_ops(json.dumps(operations)))
    assert result["status"] == "ok", result


def test_node_view_returns_exact_active_node_and_local_snapshot_identity(tmp_path):
    tools = _tools(tmp_path)
    snapshot = _read(tools, "cta")
    assert snapshot["status"] == "ok" and snapshot["complete"] is True
    assert snapshot["scope"] == "current_turn_in_memory"
    assert snapshot["document_id"] == "doc_inspection"
    assert snapshot["page_id"] == "home"
    assert snapshot["run_id"] == tools.run_id
    assert snapshot["local_document_version"] == tools._doc_version
    assert snapshot["persisted_revision_checked"] is False
    assert "revision" not in snapshot and "persisted_revision" not in snapshot
    assert snapshot["parent_id"] == "hero" and snapshot["child_ids"] == []
    node = snapshot["node"]
    assert node["id"] == "cta" and node["kind"] == "button"
    assert node["label"] == "Start here" and node["variant"] == "secondary"
    assert node["href"] == "https://example.test/start" and node["new_tab"] is True
    assert node["classes"] == "mt-4"
    assert "A human-approved headline" not in json.dumps(snapshot)
    assert "Keep this section." not in json.dumps(snapshot)


def test_read_modify_button_preserves_other_properties_and_reads_latest_memory(tmp_path):
    tools = _tools(tmp_path)
    before = copy.deepcopy(tools.web_doc)
    snapshot = _read(tools, "cta")
    props = {
        key: value
        for key, value in snapshot["node"].items()
        if key not in {"id", "classes", "children", "name", "slot_key"}
    }
    props.update(label="Request access", href="https://example.test/request")
    _ops(tools, [{"kind": "set_node_props", "page_id": "home", "id": "cta", "props": props}])
    current = _read(tools, "cta")
    assert current["local_document_version"] > snapshot["local_document_version"]
    assert current["node"]["label"] == "Request access"
    assert current["node"]["href"] == "https://example.test/request"
    assert current["node"]["variant"] == "secondary"
    assert current["node"]["new_tab"] is True and current["node"]["classes"] == "mt-4"
    assert snapshot["node"]["label"] == "Start here"  # old response stays immutable
    before["pages"][0]["nodes"]["cta"].update(
        label="Request access", href="https://example.test/request"
    )
    assert tools.web_doc == before


def test_rich_text_read_edit_round_trip_preserves_list_marks_and_account_variable(tmp_path):
    tools = _tools(tmp_path)
    rich_text = {
        "schema_version": 1,
        "blocks": [
            {"type": "paragraph", "children": [{"type": "text", "text": "Opening sentence."}]},
            {
                "type": "list",
                "list_type": "unordered",
                "items": [
                    {
                        "children": [
                            {"type": "text", "text": "Keep emphasis", "marks": {"bold": True}}
                        ]
                    },
                    {
                        "children": [
                            {"type": "variable", "key": "account.name", "fallback": "Customer"}
                        ]
                    },
                ],
            },
        ],
    }
    _ops(tools, [{"kind": "set_rich_text", "page_id": "home", "id": "body", "content": rich_text}])
    snapshot = _read(tools, "body")
    assert snapshot["node"]["content"] == rich_text
    preserved_list = copy.deepcopy(snapshot["node"]["content"]["blocks"][1])
    edited = snapshot["node"]["content"]
    edited["blocks"][0]["children"][0]["text"] = "Only this sentence changed."
    assert tools._home_page()["nodes"]["body"]["content"] == rich_text
    _ops(tools, [{"kind": "set_rich_text", "page_id": "home", "id": "body", "content": edited}])
    result = _read(tools, "body")["node"]
    assert result["content"]["blocks"][0]["children"][0]["text"] == "Only this sentence changed."
    assert result["content"]["blocks"][1] == preserved_list
    assert result["classes"] == "text-muted"


def test_fragment_and_component_pins_are_read_exactly_without_registry_expansion(tmp_path):
    tools = _tools(tmp_path)
    fragment = {
        "id": "pin",
        "kind": "fragment",
        "classes": "w-full",
        "fragment_id": "frag_0123456789abcdef",
        "slots": {"title": {"text": "For {{account.name}}"}, "visible": {"visible": True}},
        "text_overrides": {
            ":nth-child(1)": {
                "text": "Human wording",
                "bold": True,
                "italic": False,
                "underline": False,
            }
        },
    }
    component = {
        "id": "calculator",
        "kind": "custom_component",
        "classes": "w-full",
        "slug": "capacity",
        "artifact_id": "ccart_" + "a" * 64,
        "props": {"seats": 20},
    }
    for index, node in enumerate((fragment, component)):
        _ops(
            tools,
            [
                {
                    "kind": "insert_node",
                    "page_id": "home",
                    "parent": "hero",
                    "index": index,
                    "nodes": [node],
                    "root": node["id"],
                }
            ],
        )
    assert _read(tools, "pin")["node"] == fragment
    assert _read(tools, "calculator")["node"] == component
    assert _read(tools, "hero")["child_ids"] == ["pin", "calculator", "headline", "body", "cta"]
    assert _read(tools, "root")["parent_id"] is None


def test_node_lookup_is_exact_and_never_searches_other_pages_or_documents(tmp_path):
    tools = _tools(tmp_path / "one")
    foreign = _tools(tmp_path / "other", doc_id="unrelated_document")
    _ops(
        foreign,
        [
            {
                "kind": "set_text",
                "page_id": "home",
                "id": "body",
                "content": "OTHER WORKSPACE PRIVATE COPY",
            }
        ],
    )
    added = json.loads(tools.add_page("details", "Details", "/details"))
    assert added["status"] == "ok"
    missing = _read(tools, "cta")
    assert missing["status"] == "error" and missing["complete"] is False
    assert missing["code"] == "web_node.unknown_node"
    assert "Start here" not in json.dumps(missing)
    assert "unrelated_document" not in json.dumps(missing)
    assert "OTHER WORKSPACE" not in json.dumps(missing)
    _ops(
        tools,
        [
            {
                "kind": "insert_node",
                "page_id": "details",
                "parent": "root_details",
                "index": 0,
                "nodes": [
                    {"id": "detail", "kind": "section", "classes": "", "children": ["cta"]},
                    {
                        "id": "cta",
                        "kind": "button",
                        "classes": "",
                        "label": "Details action",
                        "variant": "primary",
                        "href": "https://example.test/details",
                        "new_tab": False,
                    },
                ],
                "root": "detail",
            }
        ],
    )
    assert _read(tools, "cta")["node"]["label"] == "Details action"
    assert json.loads(tools.switch_page("home"))["status"] == "ok"
    assert _read(tools, "cta")["node"]["label"] == "Start here"
    for partial in ("ct", "Start here", " cta", "cta "):
        assert _read(tools, partial)["code"] == "web_node.unknown_node"


@pytest.mark.parametrize(
    "malformation", ["node_alias", "multiple_parents", "duplicate_page", "node_key_mismatch"]
)
def test_ambiguous_or_inconsistent_local_identity_refuses_without_partial_content(
    tmp_path, malformation
):
    tools = _tools(tmp_path)
    page = tools._home_page()
    if malformation == "node_alias":
        page["nodes"]["alias"] = copy.deepcopy(page["nodes"]["cta"])
    elif malformation == "multiple_parents":
        page["nodes"]["proof"]["children"].append("cta")
    elif malformation == "duplicate_page":
        tools.web_doc["pages"].append(copy.deepcopy(page))
    else:
        page["nodes"]["cta"]["id"] = "a_different_id"
    before = copy.deepcopy(tools.web_doc)
    result = _read(tools, "cta")
    assert result["status"] == "error" and result["complete"] is False
    assert result["code"] in {"web_node.ambiguous_page", "web_node.ambiguous_node"}
    assert "node" not in result and "Start here" not in json.dumps(result)
    assert tools.web_doc == before


def test_unknown_or_empty_node_id_refuses_without_an_unbounded_node_menu(tmp_path):
    tools = _tools(tmp_path)
    for target in ("missing", "", "x" * 100_000):
        result = _read(tools, target)
        assert result["status"] == "error" and result["complete"] is False
        assert "node" not in result and len(json.dumps(result).encode()) < 4096


def test_oversized_utf8_node_is_refused_whole_and_can_not_be_used_as_partial_props(tmp_path):
    tools = _tools(tmp_path)
    _ops(tools, [{"kind": "set_text", "page_id": "home", "id": "body", "content": "界" * 24_000}])
    result = _read(tools, "body")
    assert result["status"] == "error" and result["complete"] is False
    assert result["code"] == "web_node.too_large"
    assert result["required_bytes"] > result["limit_bytes"]
    assert "node" not in result and "content" not in result
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) <= result["limit_bytes"]


def test_node_read_is_read_only_and_works_for_non_rendering_roles(tmp_path):
    tools = _tools(tmp_path)
    before = copy.deepcopy(
        (
            tools.web_doc,
            tools.operations_ledger,
            tools._doc_version,
            tools._mutations_since_render,
            tools._preview_by_width,
            tools._state_captures,
            tools.iteration,
            tools.page_id,
        )
    )
    reader_result = _read(tools, "cta", can_render=False)
    director_result = _read(tools, "cta", can_render=True)
    assert reader_result == director_result
    after = (
        tools.web_doc,
        tools.operations_ledger,
        tools._doc_version,
        tools._mutations_since_render,
        tools._preview_by_width,
        tools._state_captures,
        tools.iteration,
        tools.page_id,
    )
    assert after == before
    assert tools._browser is None and tools._pw is None


def test_node_reader_uses_reentrant_tool_lock_and_waits_for_the_writer(tmp_path):
    tools = _tools(tmp_path)
    # Direct invocation from an already serialized call must not deadlock.
    with tools.tool_lock:
        assert _read(tools, "cta")["status"] == "ok"
    entered = threading.Event()
    finished = threading.Event()

    def read_in_thread():
        entered.set()
        try:
            return _read(tools, "cta")
        finally:
            finished.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with tools.tool_lock:
            pending = pool.submit(read_in_thread)
            assert entered.wait(2)
            assert not finished.wait(0.05), "read escaped the writer's tool lock"
            _ops(
                tools,
                [
                    {
                        "kind": "set_node_props",
                        "page_id": "home",
                        "id": "cta",
                        "props": {
                            "kind": "button",
                            "label": "After writer",
                            "variant": "secondary",
                            "href": "https://example.test/start",
                            "new_tab": True,
                        },
                    }
                ],
            )
        assert pending.result(timeout=3)["node"]["label"] == "After writer"
