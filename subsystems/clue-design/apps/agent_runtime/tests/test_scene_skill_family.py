"""Scene bundle selection exercises delivered files, discovery and direction joins."""

import importlib.util
import json
import re
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from agent_fixtures import FakeCoreClient, runtime_config
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.skills import _list_skills
from lumen_agent import harness, materialize
from lumen_agent.frame import build_pinned_knowledge
from lumen_agent.fs_backend import AgentWorkspaceBackend


def candidate_config(tmp_path):
    config = runtime_config(tmp_path)
    assert hasattr(config, "scene_skill_bundle"), "candidate bundle selector is missing"
    return replace(config, scene_skill_bundle="candidate", fast_loop=True)


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_legacy_delivery_excludes_candidate_sources_and_preserves_existing_bytes(tmp_path):
    config = runtime_config(tmp_path)
    materialize.materialize_agent_workspace(config)
    source = materialize._PACKAGE_KNOWLEDGE_DOCS
    expected = {p: b for p, b in files(source).items() if not p.startswith("views/")}
    assert files(config.workspace_root / "knowledge_docs") == expected
    assert "scene-brief-copy" not in dict(harness._materialized_skill_index(config))


def test_scene_view_discovers_only_scene_family_and_hides_legacy_policy(tmp_path):
    config = candidate_config(tmp_path)
    materialize.materialize_agent_workspace(config, knowledge_view="scene")
    backend = FilesystemBackend(root_dir=config.workspace_root, virtual_mode=True)
    discovered = {skill["name"] for skill in _list_skills(backend, "/.deepagent/skills/")}
    assert {
        "scene-brief-copy",
        "type-led-positioning",
        "authentic-product",
        "attributed-proof",
        "workflow-contrast",
    } <= discovered
    assert not {"create-website", "conversion-copywriting"} & discovered
    # Harness alignment I6 (founder ruling 2026-10-17): the scene agent gets its own copy of
    # clarify-design-brief, the one home of its ask policy (the clarification tool points there).
    assert "clarify-design-brief" in discovered
    clarify = (config.workspace_root / ".deepagent/skills/clarify-design-brief/SKILL.md").read_text()
    assert "up to 6 well-formed questions" in clarify and "orchestrator" not in clarify
    assert not (
        config.workspace_root / "knowledge_docs/knowledge/design/blocks/patterns.md"
    ).exists()
    assert not (config.workspace_root / "knowledge_docs/views").exists()
    assert set(dict(harness._materialized_skill_index(config))) == discovered


def test_account_adaptation_routes_to_delivered_support_without_becoming_a_family(tmp_path):
    """Catch missing registration, broken brief links, eager pinning or family promotion."""
    config = candidate_config(tmp_path)
    materialize.materialize_agent_workspace(config, knowledge_view="scene")
    backend = AgentWorkspaceBackend(config.workspace_root)
    discovered = {s["name"]: s for s in _list_skills(backend, "/.deepagent/skills/")}
    assert "account-adaptation" in discovered

    brief_path = discovered["scene-brief-copy"]["path"]
    brief = backend.download_files([brief_path])[0]
    assert brief.error is None
    targets = re.findall(r"\]\((/\.deepagent/skills/[^)]+/SKILL\.md)\)", brief.content.decode())
    support_path = discovered["account-adaptation"]["path"]
    assert support_path in targets
    support = backend.download_files([support_path])[0]
    assert support.error is None
    source = materialize._PACKAGE_KNOWLEDGE_DOCS / "views/scene/skills/account-adaptation/SKILL.md"
    assert support.content == source.read_bytes()
    identity_path = discovered["account-identity-composition"]["path"]
    assert identity_path in support.content.decode()
    identity = backend.download_files([identity_path])[0]
    assert identity.error is None
    identity_source = source.parent.parent / "account-identity-composition/SKILL.md"
    assert identity.content == identity_source.read_bytes()

    descriptor = json.loads((config.workspace_root / ".deepagent/knowledge-view.json").read_text())
    assert "account-adaptation" not in descriptor["playbooks"]
    assert "account-identity-composition" not in descriptor["playbooks"]
    catalog = backend.download_files(["/knowledge_docs/knowledge/scene/catalog.md"])[0]
    assert catalog.error is None
    family_paths = re.findall(
        r"\]\((/\.deepagent/skills/[^)]+/SKILL\.md)\)", catalog.content.decode()
    )
    assert support_path not in family_paths
    assert {discovered[name]["path"] for name in descriptor["playbooks"]} == set(family_paths)
    assert support.content.decode() not in "\n".join(dict(build_pinned_knowledge(config)).values())

    # Switching the same derived workspace back to legacy must remove the support
    # skill and preserve the complete legacy knowledge tree, including website guidance.
    materialize.materialize_agent_workspace(config)
    assert "account-adaptation" not in dict(harness._materialized_skill_index(config))
    assert backend.download_files([support_path])[0].error is not None
    assert backend.download_files([identity_path])[0].error is not None
    expected = {
        p: b for p, b in files(materialize._PACKAGE_KNOWLEDGE_DOCS).items()
        if not p.startswith("views/")
    }
    assert files(config.workspace_root / "knowledge_docs") == expected


def test_view_switch_and_override_changes_invalidate_stamp(tmp_path):
    config = runtime_config(tmp_path)
    source = tmp_path / "source"
    shutil.copytree(materialize._PACKAGE_KNOWLEDGE_DOCS, source)
    materialize.materialize_agent_workspace(config, source_knowledge_docs=source)
    stamp_path = config.workspace_root / ".deepagent/.sync-stamp"
    old = stamp_path.read_text()
    materialize.materialize_agent_workspace(
        config, source_knowledge_docs=source, knowledge_view="scene"
    )
    scene = stamp_path.read_text()
    assert scene != old
    override = source / "views/scene/AGENT.md"
    override.write_text(override.read_text() + "\nA new scene rule.\n")
    materialize.materialize_agent_workspace(
        config, source_knowledge_docs=source, knowledge_view="scene"
    )
    assert stamp_path.read_text() != scene
    assert (
        (config.workspace_root / ".deepagent/AGENTS.md").read_text().endswith("A new scene rule.\n")
    )
    materialize.materialize_agent_workspace(config, source_knowledge_docs=source)
    assert stamp_path.read_text() == old
    assert "scene-brief-copy" not in dict(harness._materialized_skill_index(config))


def test_scene_section_projection_keeps_shared_mechanics_and_replaces_policy(tmp_path):
    config = runtime_config(tmp_path)
    source = tmp_path / "source"
    (source / "views/scene").mkdir(parents=True)
    (source / "AGENT.md").write_text("router")
    (source / "grammar.md").write_text(
        "mechanics\n## Policy\nlegacy policy\n## Edits\nedit grammar\n"
    )
    (source / "replacement.md").write_text("## Policy\nscene policy\n")
    manifest = {
        "schema_version": 1,
        "skills": [],
        "playbooks": [],
        "knowledge": ["grammar.md", "replacement.md"],
        "pinned_knowledge": ["grammar.md"],
        "section_overrides": {
            "grammar.md": [
                {
                    "start": "## Policy",
                    "end": "## Edits",
                    "replacement": "replacement.md",
                }
            ]
        },
    }
    (source / "views/scene/manifest.json").write_text(json.dumps(manifest))
    materialize.materialize_agent_workspace(
        config, source_knowledge_docs=source, knowledge_view="scene"
    )
    assert (config.workspace_root / "knowledge_docs/grammar.md").read_text() == (
        "mechanics\n## Policy\nscene policy\n\n## Edits\nedit grammar\n"
    )
    materialize.materialize_agent_workspace(config, source_knowledge_docs=source)
    assert (config.workspace_root / "knowledge_docs/grammar.md").read_bytes() == (
        source / "grammar.md"
    ).read_bytes()


def test_harness_uses_scene_view_in_real_skill_discovery_and_pins(tmp_path, monkeypatch):
    import deepagents

    config = candidate_config(tmp_path)
    captured = {}
    monkeypatch.setattr(
        deepagents, "create_deep_agent", lambda **kwargs: captured.update(kwargs) or kwargs
    )
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    monkeypatch.setattr("lumen_agent.llm.init_model", lambda *args, **kwargs: object())
    materialize.materialize_agent_workspace(config)
    legacy_files = files(config.workspace_root / "knowledge_docs")
    _agent, tools = harness.create_design_deepagent("Make an ad", config)
    assert files(config.workspace_root / "knowledge_docs") == legacy_files
    assert tools.config.workspace_root != config.workspace_root
    author = next(sa for sa in captured["subagents"] if sa["name"] == "lumen-dsl-author")
    assert captured["skills"] == author["skills"] == ["/.deepagent/skills"]
    assert "scene-brief-copy" in {
        s["name"] for s in _list_skills(captured["backend"], author["skills"][0])
    }
    pins = dict(build_pinned_knowledge(tools.config))
    assert "/knowledge_docs/knowledge/scene/components.md" in pins
    for virtual, content in pins.items():
        assert content == (tools.config.workspace_root / virtual.lstrip("/")).read_text()
    candidate_files = files(tools.config.workspace_root / "knowledge_docs")
    materialize.materialize_agent_workspace(config)
    assert files(tools.config.workspace_root / "knowledge_docs") == candidate_files

    # The API/fleet adapter consumes the returned trace root, not the caller's
    # original config root. A nested candidate run must preserve its real ops.
    from lumen_api.main import agent_response_from_trace

    operation = {"kind": "update_node", "node_id": "real_layer"}
    (tools.trace_dir / "operations_ledger.json").write_text(
        json.dumps(
            {
                "entries": [
                    {"iteration": 1, "source": "compile_dsl_block", "operation": operation}
                ],
            }
        )
    )
    response = agent_response_from_trace(
        {"status": "completed_with_warnings", "run_id": tools.run_id, "summary": "Draft"},
        tools.trace_dir,
    )
    assert response["operations"] == [operation]
    assert Path(response["trace_dir"]) == tools.trace_dir


@pytest.mark.parametrize("web_solo", [False, True])
def test_interleaved_candidate_and_web_harnesses_preserve_web_context(
    tmp_path, monkeypatch, web_solo
):
    import deepagents
    from lumen_agent import harness_web
    from lumen_api.core import CoreClient

    config = replace(
        candidate_config(tmp_path),
        repo_root=Path(harness.__file__).resolve().parents[3],
        web_solo=web_solo,
    )
    captured = []
    monkeypatch.setattr(deepagents, "create_deep_agent", lambda **kwargs: captured.append(kwargs))
    monkeypatch.setattr("lumen_agent.llm.init_model", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        "lumen_agent.llm.assert_all_role_models_support_image_input", lambda _: None
    )
    monkeypatch.setattr("lumen_agent.tools.web_substrate.new_run_id", lambda: "run_web_parity")
    web_doc = CoreClient(repo_root=config.repo_root).web_new_doc("doc_parity", "Parity", None)[
        "web_doc"
    ]

    harness_web.create_web_deepagent(
        "Build a page", replace(config, scene_skill_bundle="legacy"), web_doc
    )
    legacy = captured[-1]
    legacy_index = harness._materialized_skill_index(config)
    legacy_files = files(config.workspace_root / "knowledge_docs")
    legacy_pins = build_pinned_knowledge(config)
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    _agent, scene_tools = harness.create_design_deepagent("Make an ad", config)
    scene_files = files(scene_tools.config.workspace_root / "knowledge_docs")
    harness_web.create_web_deepagent("Build a page", config, web_doc)
    current = captured[-1]
    assert legacy["system_prompt"] == current["system_prompt"]
    assert [(s["name"], s["system_prompt"], s["skills"]) for s in legacy["subagents"]] == [
        (s["name"], s["system_prompt"], s["skills"]) for s in current["subagents"]
    ]
    assert harness._materialized_skill_index(config) == legacy_index
    assert files(config.workspace_root / "knowledge_docs") == legacy_files
    assert build_pinned_knowledge(config) == legacy_pins
    assert files(scene_tools.config.workspace_root / "knowledge_docs") == scene_files


def direction_type():
    name = "lumen_agent.models.creative_direction"
    assert importlib.util.find_spec(name), "typed scene direction contract is missing"
    from lumen_agent.models.creative_direction import CreativeDirection

    return CreativeDirection


def direction():
    return {
        "schema_version": 1,
        "objective": "Explain the product",
        "audience": "Operations leaders",
        "playbook": "type-led-positioning",
        "intent": "native",
        "copy": [
            {
                "id": "headline",
                "role": "headline",
                "text": "Make the next step clear",
                "claim_kind": "positioning",
                "evidence_refs": [],
            }
        ],
        "evidence": [],
        "source_roles": [],
        "preserve": ["brand type"],
        "vary": ["copy"],
        "layers": [
            {
                "id": "title",
                "kind": "native_text",
                "purpose": "Dominant message",
                "copy_id": "headline",
                "placement": {"x": 0.1, "y": 0.2, "width": 0.8, "height": 0.5},
            }
        ],
        "placement": {"width": 1080, "height": 1080, "unit": "px"},
        "review_needs": ["Read the headline at feed size"],
        "assumptions": ["Awareness creative with no CTA"],
    }


def test_typography_only_direction_without_cta_roundtrips():
    model = direction_type().model_validate(direction())
    assert (
        model.model_validate_json(model.model_dump_json()).copy_blocks[0].text
        == "Make the next step clear"
    )


def test_scoped_logo_edit_needs_no_new_copy():
    payload = direction()
    payload.update(intent="edit", copy=[], source_roles=[{"asset_id": "real_logo", "role": "logo"}])
    payload["layers"] = [
        {
            "id": "logo",
            "kind": "authentic_image",
            "purpose": "Fix logo position",
            "asset_id": "real_logo",
            "placement": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1},
        }
    ]
    model = direction_type().model_validate(payload)
    assert model.model_dump()["copy"] == []
    payload["intent"] = "native"
    with pytest.raises(ValueError):
        direction_type().model_validate(payload)


def test_future_registered_playbook_needs_no_python_enum_change():
    payload = direction()
    payload["playbook"] = "new-reviewed-family"
    assert direction_type().model_validate(payload).playbook == "new-reviewed-family"


def test_attributed_proof_binds_quote_and_attribution_to_actual_source_record():
    payload = direction()
    payload["playbook"] = "attributed-proof"
    payload["evidence"] = [
        {
            "id": "quote_1",
            "source": "supplied-case-study.txt:12",
            "excerpt": "The handoff is clearer. — Operations lead",
        }
    ]
    payload["copy"] = [
        {
            "id": "headline",
            "role": "headline",
            "text": "The handoff is clearer.",
            "claim_kind": "quote",
            "evidence_refs": ["quote_1"],
        },
        {
            "id": "speaker",
            "role": "attribution",
            "text": "Operations lead",
            "claim_kind": "assertion",
            "evidence_refs": ["quote_1"],
        },
    ]
    payload["layers"].append(
        {
            "id": "credit",
            "kind": "native_text",
            "purpose": "Attribution",
            "copy_id": "speaker",
            "placement": {"x": 0.1, "y": 0.8, "width": 0.8, "height": 0.1},
        }
    )
    model = direction_type().model_validate(payload)
    assert model.copy_blocks[1].evidence_refs == [model.evidence[0].id]


def test_candidate_reference_scaffold_uses_the_shared_direction_record(tmp_path, monkeypatch):
    from lumen_agent.tools.substrate import LumenDesignTools
    from lumen_agent.workspace import scaffold_workspace

    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = replace(
        candidate_config(tmp_path), reference_assets={"ref_1": {"record": {}, "order": 0}}
    )
    tools = LumenDesignTools(config, "Make a new ad from this reference")
    scaffold_workspace(tools, tools.prompt)
    resource = (tools.trace_dir / "workspace/references.md").read_text()
    assert "creative-direction.json" in resource
    assert "reference-brief.md" not in resource


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-evidence",
        "unbound-copy",
        "fake-logo",
        "out-of-bounds",
        "conflicting-intent",
        "unknown-field",
        "blank-copy",
        "role-count",
        "unregistered-image-source",
        "unattributed-proof",
    ],
)
def test_invalid_direction_records_refuse(mutation):
    cls = direction_type()
    payload = direction()
    if mutation == "missing-evidence":
        payload["copy"][0].update(claim_kind="statistic", evidence_refs=["missing"])
    elif mutation == "unbound-copy":
        payload["layers"][0]["copy_id"] = "unknown"
    elif mutation == "fake-logo":
        payload["layers"].append(
            {
                "id": "logo",
                "kind": "authentic_image",
                "purpose": "Brand",
                "placement": {"x": 0, "y": 0, "width": 0.1, "height": 0.1},
            }
        )
    elif mutation == "out-of-bounds":
        payload["layers"][0]["placement"]["width"] = 0.99
    elif mutation == "conflicting-intent":
        payload["vary"] = ["brand type"]
    elif mutation == "unknown-field":
        payload["unavailable_tool"] = "magic"
    elif mutation == "blank-copy":
        payload["copy"][0]["text"] = "  "
    elif mutation == "role-count":
        payload["layers"][0].update(reference_asset_ids=["ref"], reference_roles=[])
    elif mutation == "unregistered-image-source":
        payload["layers"].append({
            "id": "product", "kind": "authentic_image", "purpose": "Product detail",
            "asset_id": "missing-product",
            "placement": {"x": 0, "y": 0, "width": 0.2, "height": 0.2},
        })
    else:
        payload["playbook"] = "attributed-proof"
        payload["copy"][0].update(claim_kind="quote", evidence_refs=[])
    with pytest.raises(ValueError):
        cls.model_validate(payload)
