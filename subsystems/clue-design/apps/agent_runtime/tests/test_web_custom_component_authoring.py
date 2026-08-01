"""P6.4 Deep Agent custom-component authoring and scope safety."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent import harness_web
from lumen_agent.tools.web_substrate import LumenWebTools
from lumen_api.core import CoreClient


REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_A = "ccart_" + "a" * 64
ARTIFACT_B = "ccart_" + "b" * 64
TWO_SECTIONS = """
<section id="alpha" class="bg-light">
  <div id="alpha_box" class="p-8">
    <h2 id="alpha_title">Alpha</h2>
  </div>
</section>
<section id="beta" class="bg-card">
  <div id="beta_box" class="p-8">
    <h2 id="beta_title">Beta</h2>
  </div>
</section>
"""


class FakeRegistry:
    account_id = "acc_alpha"
    document_id = "doc_alpha"

    def __init__(self) -> None:
        self.sources: dict[str, dict] = {}
        self.compile_results: list[dict] = []
        self.compile_calls: list[tuple[str, int]] = []
        self.resolve_calls: list[tuple[str, str, dict | None]] = []

    def projection(self):
        return {
            "schema_version": 1,
            "account_id": self.account_id,
            "components": [
                {
                    "slug": slug,
                    "source_version": item["version"],
                    "revision_id": item["revision_id"],
                    "files": item["files"],
                }
                for slug, item in sorted(self.sources.items())
            ],
        }

    def list_attachable(self):
        return {
            "schema_version": 1,
            "account_id": self.account_id,
            "components": [],
        }

    def inspect(self, slug: str):
        item = self.sources[slug]
        return {
            "schema_version": 1,
            "account_id": self.account_id,
            "component": {
                "slug": slug,
                "source_version": item["version"],
                "current_source_revision_id": item["revision_id"],
            },
            "source": {
                "source_version": item["version"],
                "revision_id": item["revision_id"],
                "provenance": item.get("provenance") or {},
            },
            "files": item["files"],
            "artifacts": [],
            "compilations": [],
            "usages": [],
        }

    def write_source(
        self, *, slug: str, expected_version: int, files: dict, provenance: dict
    ):
        current = self.sources.get(slug, {}).get("version", 0)
        if expected_version != current:
            error = RuntimeError(
                f"expected source version {expected_version}, current is {current}"
            )
            error.expected = expected_version
            error.current = current
            raise error
        version = current + 1
        revision_id = f"ccsrc_{version:064x}"
        self.sources[slug] = {
            "version": version,
            "revision_id": revision_id,
            "files": dict(files),
            "provenance": provenance,
        }
        return {
            "schema_version": 1,
            "component": {"slug": slug, "source_version": version},
            "source": {
                "slug": slug,
                "source_version": version,
                "revision_id": revision_id,
            },
        }

    def compile_once(self, *, slug: str, source_version: int, actor: dict):
        self.compile_calls.append((slug, source_version))
        return self.compile_results.pop(0)

    def resolve_attachable(
        self, *, slug: str, artifact_id: str, props: dict | None
    ):
        self.resolve_calls.append((slug, artifact_id, props))
        if artifact_id not in {ARTIFACT_A, ARTIFACT_B}:
            raise ValueError("artifact has no durable successful compilation record")
        effective = {"headline": "Default"}
        effective.update(props or {})
        return {
            "schema_version": 1,
            "artifact": {
                "artifact_id": artifact_id,
                "slug": slug,
                "manifest": {"schema_version": 2},
            },
            "compilation": {"status": "succeeded", "artifact_id": artifact_id},
            "props": effective,
        }


def compile_result(
    status: str, *, artifact_id: str = ARTIFACT_A, sequence: int = 1
) -> dict:
    return {
        "schema_version": 1,
        "compile_status": status,
        "compilation": {
            "compilation_id": f"cccmp_{sequence:032x}",
            "status": "succeeded" if status == "success" else status,
            "diagnostics": (
                []
                if status == "success"
                else [
                    {
                        "code": "CCT1001",
                        "severity": "error",
                        "message": status,
                    }
                ]
            ),
        },
        "artifact": (
            {
                "artifact_id": artifact_id,
                "source": {"value": "1" * 64},
                "bundle": {"value": "2" * 64},
            }
            if status == "success"
            else None
        ),
    }


def tools_for(
    tmp_path: Path,
    registry: FakeRegistry,
    *,
    prompt: str = "Build a custom visual.",
    targets: list[str] | None = None,
) -> LumenWebTools:
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace",
        custom_component_registry=registry,
        custom_component_account_id=registry.account_id,
        custom_component_document_id=registry.document_id,
        turn_target_node_ids=targets,
    )
    core = CoreClient(repo_root=REPO_ROOT)
    web_doc = core.web_new_doc("doc_alpha", "Alpha", None)["web_doc"]
    return LumenWebTools(config, prompt, initial_web_doc=web_doc)


def trace_events(tools: LumenWebTools) -> list[dict]:
    path = tools.trace_dir / "trace.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_source_write_requires_ladder_gap_and_endpoint_provenance(
    tmp_path: Path,
):
    registry = FakeRegistry()
    endpoint = "https://customer.test/forms/submit"
    tools = tools_for(
        tmp_path,
        registry,
        prompt=f"Use this exact form endpoint: {endpoint}",
    )
    source = (
        "export default function Form(){"
        f"return <form action=\"{endpoint}\">Send</form>"
        "}"
    )
    files_json = json.dumps({"lead-form.tsx": source})

    missing_gap = json.loads(
        tools.write_custom_component_source(
            "lead-form", 0, files_json, "", "[]"
        )
    )
    assert missing_gap["error_code"] == "custom_component.ladder_gap_required"
    unclaimed = json.loads(
        tools.write_custom_component_source(
            "lead-form",
            0,
            files_json,
            "Palette and platform forms cannot submit this validated endpoint.",
            "[]",
        )
    )
    assert unclaimed["error_code"] == "custom_component.endpoint_unverified"
    assert registry.sources == {}

    written = json.loads(
        tools.write_custom_component_source(
            "lead-form",
            0,
            files_json,
            "Palette has no input fields, platform components have no form, "
            "and an embed cannot provide the required first-party UI.",
            json.dumps(
                [{"endpoint": endpoint, "provenance": "user_provided"}]
            ),
        )
    )
    assert written["status"] == "ok"
    assert written["source"]["source_version"] == 1
    assert (
        tools.custom_component_projection_root
        / "lead-form"
        / "lead-form.tsx"
    ).read_text() == source
    provenance = registry.sources["lead-form"]["provenance"]
    assert provenance["actor"]["id"] == tools.run_id
    assert provenance["document_id"] == "doc_alpha"
    events = [event["event"] for event in trace_events(tools)]
    assert "ladder_gap" in events
    assert "custom_component_source_written" in events

    # A later run rematerializes source from the same durable gateway.
    later = tools_for(tmp_path / "later", registry)
    assert (
        later.custom_component_projection_root
        / "lead-form"
        / "lead-form.tsx"
    ).read_text() == source
    preserved = json.loads(
        later.write_custom_component_source(
            "lead-form",
            1,
            files_json,
            "The same first-party form still exceeds palette/platform/embed "
            "capabilities; this revision changes no endpoint.",
            json.dumps(
                [{"endpoint": endpoint, "provenance": "user_provided"}]
            ),
        )
    )
    assert preserved["status"] == "ok"
    assert preserved["source"]["source_version"] == 2


def test_placeholder_endpoint_is_obvious_and_forced_into_finalize_summary(
    tmp_path: Path,
):
    registry = FakeRegistry()
    tools = tools_for(tmp_path, registry)
    placeholder = "https://example.com/PLACEHOLDER-booking"
    result = json.loads(
        tools.write_custom_component_source(
            "booking-card",
            0,
            json.dumps(
                {
                    "booking-card.tsx": (
                        "export default function Booking(){"
                        f"return <a href=\"{placeholder}\">Book</a>"
                        "}"
                    )
                }
            ),
            "Palette and platform nodes cannot express the required custom "
            "booking visualization; no real embed endpoint was supplied.",
            json.dumps(
                [
                    {
                        "endpoint": placeholder,
                        "provenance": "placeholder",
                    }
                ]
            ),
        )
    )
    assert result["status"] == "ok"
    finalized = json.loads(
        tools.finalize_web_run("completed_with_warnings", "Component built.")
    )
    assert placeholder in finalized["summary"]
    assert finalized["custom_component_placeholder_endpoints"] == [placeholder]
    assert finalized["ladder_gap"]


def test_compile_requires_repair_and_bounds_transient_retries(tmp_path: Path):
    registry = FakeRegistry()
    tools = tools_for(tmp_path, registry)
    registry.compile_results = [compile_result("failed")]

    failed = json.loads(tools.compile_custom_component("chart", 1))
    assert failed["status"] == "repair_required"
    refused = json.loads(tools.compile_custom_component("chart", 1))
    assert refused["error_code"] == "custom_component.source_repair_required"
    assert registry.compile_calls == [("chart", 1)]

    # A new source write clears the deterministic repair guard.
    registry.sources["chart"] = {
        "version": 1,
        "revision_id": "ccsrc_" + "1" * 64,
        "files": {"chart.tsx": "export default function Chart(){return null;}"},
        "provenance": {},
    }
    written = json.loads(
        tools.write_custom_component_source(
            "chart",
            1,
            json.dumps(
                {
                    "chart.tsx": (
                        "export default function Chart(){return <svg />;}"
                    )
                }
            ),
            "Palette lacks computed SVG geometry, platform components do not "
            "draw charts, and an embed would surrender theme/prop editing.",
        )
    )
    assert written["source"]["source_version"] == 2
    registry.compile_results = [
        compile_result("transient_error", sequence=2),
        compile_result("transient_error", sequence=3),
        compile_result("success", artifact_id=ARTIFACT_B, sequence=4),
    ]
    compiled = json.loads(tools.compile_custom_component("chart", 2))
    assert compiled["status"] == "ok"
    assert compiled["artifact"]["artifact_id"] == ARTIFACT_B
    assert [attempt["status"] for attempt in compiled["attempts"]] == [
        "transient_error",
        "transient_error",
        "success",
    ]
    assert registry.compile_calls[-3:] == [
        ("chart", 2),
        ("chart", 2),
        ("chart", 2),
    ]
    assert "custom_component_artifact_created" in [
        event["event"] for event in trace_events(tools)
    ]


def test_attach_and_repin_are_checked_scoped_operations_only(tmp_path: Path):
    registry = FakeRegistry()
    tools = tools_for(
        tmp_path, registry, targets=["alpha_title"]
    )
    assert json.loads(tools.author_web_page(TWO_SECTIONS))["status"] == "ok"
    before_source = dict(registry.sources)
    before_ledger = len(tools.operations_ledger)

    outside = json.loads(
        tools.place_custom_component(
            "attach",
            "metric-card",
            ARTIFACT_A,
            parent_node_id="beta_box",
            index=1,
        )
    )
    assert outside["error_code"] == "custom_component.scope_violation"
    assert len(tools.operations_ledger) == before_ledger

    attached = json.loads(
        tools.place_custom_component(
            "attach",
            "metric-card",
            ARTIFACT_A,
            parent_node_id="alpha_box",
            index=1,
            props_json=json.dumps({"headline": "Account metric"}),
        )
    )
    assert attached["status"] == "ok"
    node_id = attached["node_ids"][0]
    assert tools._home_page()["nodes"][node_id]["artifact_id"] == ARTIFACT_A
    assert registry.sources == before_source
    attach_op = tools.operations_ledger[-1]
    assert attach_op["kind"] == "insert_node"
    assert attach_op["parent"] == "alpha_box"

    tools.config = replace(
        tools.config, turn_target_node_ids=[node_id]
    )
    repinned = json.loads(
        tools.place_custom_component(
            "repin",
            "metric-card",
            ARTIFACT_B,
            target_node_ids_json=json.dumps([node_id]),
        )
    )
    assert repinned["status"] == "ok"
    assert tools._home_page()["nodes"][node_id]["artifact_id"] == ARTIFACT_B
    assert tools.operations_ledger[-1] == {
        "kind": "set_node_props",
        "page_id": "home",
        "id": node_id,
        "props": {
            "kind": "custom_component",
            "slug": "metric-card",
            "artifact_id": ARTIFACT_B,
            "props": {"headline": "Account metric"},
        },
    }
    assert registry.sources == before_source
    events = trace_events(tools)
    assert "custom_component_attached" in [event["event"] for event in events]
    assert "custom_component_repinned" in [event["event"] for event in events]
    repin_payload = next(
        event["payload"]
        for event in events
        if event["event"] == "custom_component_repinned"
    )
    assert repin_payload["source_mutated"] is False
    assert repin_payload["target_node_ids"] == [node_id]


def test_uncompiled_artifact_cannot_be_attached(tmp_path: Path):
    registry = FakeRegistry()
    tools = tools_for(tmp_path, registry)
    assert json.loads(tools.author_web_page(TWO_SECTIONS))["status"] == "ok"
    before = json.loads(json.dumps(tools.web_doc))
    rejected = json.loads(
        tools.place_custom_component(
            "attach",
            "metric-card",
            "ccart_" + "c" * 64,
            parent_node_id="alpha_box",
            index=1,
        )
    )
    assert rejected["error_code"] == "custom_component.artifact_not_attachable"
    assert tools.web_doc == before


def test_web_harness_exposes_read_tools_to_orchestrator_and_full_flow_to_author(
    tmp_path: Path, monkeypatch
):
    import deepagents
    import lumen_agent.llm as llm

    registry = FakeRegistry()
    captured: dict = {}
    marker = object()

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return marker

    monkeypatch.setattr(deepagents, "create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(
        harness_web, "materialize_agent_workspace", lambda _config: None
    )
    monkeypatch.setattr(
        harness_web,
        "_instrument",
        lambda _config, _tools, _model, role: f"{role}-model",
    )
    monkeypatch.setattr(
        llm, "assert_all_role_models_support_image_input", lambda _config: None
    )
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace",
        custom_component_registry=registry,
        custom_component_account_id=registry.account_id,
        custom_component_document_id=registry.document_id,
    )
    web_doc = CoreClient(repo_root=REPO_ROOT).web_new_doc(
        "doc_alpha", "Alpha", None
    )["web_doc"]
    agent, tools = harness_web.create_web_deepagent(
        "Build a chart.", config, web_doc
    )
    assert agent is marker
    author = next(
        subagent
        for subagent in captured["subagents"]
        if subagent["name"] == "lumen-web-author"
    )
    author_names = {
        getattr(tool, "__name__", getattr(tool, "name", ""))
        for tool in author["tools"]
    }
    assert {
        "list_custom_components",
        "inspect_custom_component",
        "write_custom_component_source",
        "compile_custom_component",
        "place_custom_component",
    }.issubset(author_names)
    orchestrator_names = {
        getattr(tool, "__name__", getattr(tool, "name", ""))
        for tool in captured["tools"]
    }
    assert {
        "list_custom_components",
        "inspect_custom_component",
    }.issubset(orchestrator_names)
    assert "write_custom_component_source" not in orchestrator_names
    backend = captured["backend"]
    projection = backend.read("/custom_components/.registry.json")
    assert projection.error is None
    assert tools.custom_component_projection_root.exists()
