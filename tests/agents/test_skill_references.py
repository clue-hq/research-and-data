"""Pinned skill references render identically in model prompts and frozen workspace files."""

import hashlib
import json
from dataclasses import replace

import pytest
import yaml

from clue_agents import AgentResourceMaterializer, AgentRole, ResourceKind, WorkspaceSecurityError
from clue_agents.resources import (
    ResourceBody,
    build_agent_resource_manifest,
    render_skill_references,
)
from clue_api.quality_research_wiring import CATALOG_ROOT, quality_profiles, quality_tools
from tests.agents.workspace_helpers import make_workspace, policy, resource_ref, resource_snapshot


def test_only_named_skill_paths_are_rendered_without_general_template_evaluation():
    skill = resource_ref(ResourceKind.SKILL, "account-dossier", b"skill")
    text = (
        "Read {{skills.account_dossier.path}} / {{ skills.account-dossier.path }}; {{account_name}}"
    )
    path = "/.deepagent/skills/account-dossier/1.0.0/SKILL.md"
    assert render_skill_references(text, (skill,)) == f"Read {path} / {path}; {{{{account_name}}}}"
    with pytest.raises(WorkspaceSecurityError, match="ambiguous"):
        render_skill_references(text, (skill, skill.model_copy(update={"version": "v2"})))
    with pytest.raises(WorkspaceSecurityError, match="ambiguous"):
        render_skill_references(text, (skill, skill.model_copy(update={"name": "account_dossier"})))


@pytest.mark.parametrize(
    "text",
    ["{{skills.missing.path}}", "{{skills.account_dossier.body}}", "{{skills.account_dossier.path"],
)
def test_missing_or_malformed_references_do_not_reach_the_model(text):
    with pytest.raises(WorkspaceSecurityError):
        render_skill_references(text, ())


@pytest.mark.parametrize("person", [False, True])
def test_real_research_prompt_and_skill_reads_match_materialized_pinned_files(tmp_path, person):
    resolved = quality_profiles(
        quality_tools(None, None, purge=False), version=21, person=person
    ).resolve(AgentRole.ACCOUNT_RESEARCH)
    snapshot = resolved.resource_snapshot
    historical = quality_profiles(
        quality_tools(None, None, purge=False), version=20, person=person
    ).resolve(AgentRole.ACCOUNT_RESEARCH)
    # This release changes references only. Comparing the actual instruction text catches
    # misplaced placeholders (e.g. pointing the narrative step at the dossier skill).
    assert resolved.prompt_body == historical.prompt_body.replace(
        "/person-dossier/v3/SKILL.md", "/person-dossier/v4/SKILL.md"
    )
    historical_by_name = {skill.ref.name: skill for skill in historical.skills}
    for skill in resolved.skills:
        assert resolved.open_skill(skill.ref.address) == historical.open_skill(
            historical_by_name[skill.ref.name].ref.address
        )
    for body in historical.resource_snapshot.bodies:
        assert historical.resource_snapshot.rendered_content(body) == body.content
    prompt_source = next(b for b in snapshot.bodies if b.ref.kind is ResourceKind.PROMPT)
    assert b"{{skills." in prompt_source.content
    assert "{{skills." not in resolved.prompt_body
    harness = make_workspace(
        tmp_path,
        active_policy=policy(max_total_bytes=1048576, max_file_bytes=262144, max_file_count=100),
    )
    try:
        materializer = AgentResourceMaterializer()
        materializer.materialize(lease=harness.lease, snapshot=snapshot)
        for skill in resolved.profile.skills:
            content = (harness.thread_path / skill.materialized_path).read_text()
            assert "{{skills." not in content
            assert resolved.open_skill(skill.resource.address) in content
        prompt_path = (
            harness.thread_path
            / ".deepagent/prompts"
            / snapshot.manifest.prompt.name
            / snapshot.manifest.prompt.version
            / "SYSTEM.md"
        )
        assert resolved.prompt_body in prompt_path.read_text()
        records = json.loads(
            (harness.thread_path / ".deepagent/rendered-resources.json").read_text()
        )["resources"]
        for record in records:
            assert (
                hashlib.sha256((harness.thread_path / record["path"]).read_bytes()).hexdigest()
                == record["rendered_sha256"]
            )
            assert record["source_sha256"] != record["rendered_sha256"]
        # Source audit pin remains the template hash. Cold resume repairs the derived bytes.
        assert hashlib.sha256(prompt_source.content).hexdigest() == snapshot.manifest.prompt.sha256
        prompt_path.chmod(0o600)
        prompt_path.write_text("tampered")
        prompt_path.chmod(0o400)
        materializer.verify_materialized(lease=harness.lease, snapshot=snapshot)
        assert resolved.prompt_body in prompt_path.read_text()
    finally:
        harness.close()


def test_profile_update_retargets_prompt_and_skill_links_while_preserving_old_snapshot(
    tmp_path,
):
    tools = quality_tools(None, None, purge=False)
    old = quality_profiles(tools, version=21).resolve(AgentRole.ACCOUNT_RESEARCH)
    # Copy only this profile's exact resources into an isolated catalog.
    for path, content in [(b.ref, b.content) for b in old.resource_snapshot.bodies]:
        kind = {
            ResourceKind.PROFILE: ("profiles", "profile.yaml"),
            ResourceKind.PROMPT: ("prompts", "SYSTEM.md"),
            ResourceKind.SKILL: ("skills", "SKILL.md"),
        }[path.kind]
        dest = tmp_path / kind[0] / path.name / path.version / kind[1]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    profile_path = tmp_path / "profiles/quality-account-research/v21/profile.yaml"
    profile = yaml.safe_load(profile_path.read_text())
    original = (CATALOG_ROOT / "skills/claim-ready-account-dossier/v2/SKILL.md").read_text()
    newer = original.replace("version: v2\n", "version: v99\n", 1)
    dest = tmp_path / "skills/claim-ready-account-dossier/v99/SKILL.md"
    dest.parent.mkdir(parents=True)
    dest.write_text(newer)
    # Merely adding a draft does not change selection.
    unchanged = quality_profiles(tools, tmp_path, version=21).resolve(AgentRole.ACCOUNT_RESEARCH)
    assert unchanged.prompt_body == old.prompt_body
    for skill in profile["skills"]:
        if skill["name"] == "claim-ready-account-dossier":
            skill.update(version="v99", sha256=hashlib.sha256(newer.encode()).hexdigest())
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False))
    new = quality_profiles(tools, tmp_path, version=21).resolve(AgentRole.ACCOUNT_RESEARCH)
    assert new.profile.prompt == old.profile.prompt
    assert "/claim-ready-account-dossier/v99/SKILL.md" in new.prompt_body
    account_skill = next(s for s in new.profile.skills if s.resource.name == "account-dossier")
    assert "/claim-ready-account-dossier/v99/SKILL.md" in new.open_skill(
        account_skill.resource.address
    )
    assert "/claim-ready-account-dossier/v2/SKILL.md" in old.prompt_body
    assert dict(old.resource_snapshot.materialized_entries()) != dict(
        new.resource_snapshot.materialized_entries()
    )
    # Undeclared references fail at resolution, even when that skill exists on disk.
    profile["skills"] = [s for s in profile["skills"] if s["name"] != "claim-ready-account-dossier"]
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False))
    with pytest.raises(WorkspaceSecurityError, match="not mounted"):
        quality_profiles(tools, tmp_path, version=21)


def test_historical_snapshot_keeps_exact_bytes_and_has_no_rendered_metadata():
    snapshot, _ = resource_snapshot()
    entries = dict(snapshot.materialized_entries())
    assert ".deepagent/rendered-resources.json" not in entries
    for body in snapshot.bodies:
        assert snapshot.rendered_content(body) == body.content
    # Skill-to-skill errors are checked even if the prompt itself has no placeholders.
    bodies = []
    for body in snapshot.bodies:
        if body.ref.kind is ResourceKind.SKILL:
            content = b"Read {{skills.unmounted.path}}"
            ref = body.ref.model_copy(update={"sha256": hashlib.sha256(content).hexdigest()})
            bodies.append(ResourceBody(ref, content, body.media_type))
        else:
            bodies.append(body)
    manifest = build_agent_resource_manifest(
        role=snapshot.manifest.role,
        profile=snapshot.manifest.profile,
        prompt=snapshot.manifest.prompt,
        skills=(bodies[-1].ref,),
        tools=(),
    )
    with pytest.raises(WorkspaceSecurityError, match="not mounted"):
        replace(snapshot, manifest=manifest, bodies=tuple(bodies))


@pytest.mark.parametrize("person", [False, True])
def test_approved_editorial_promotion_mounts_shared_skill_without_changing_research(
    tmp_path, person
):
    from clue_api.arv2.account_research_catalog import bundle_pin
    from clue_api.arv2.quality_catalog import load_quality_resources

    tools = quality_tools(None, None, purge=False)
    previous = quality_profiles(tools, version=22, person=person).resolve(
        AgentRole.ACCOUNT_RESEARCH
    )
    current = quality_profiles(tools, version=23, person=person).resolve(AgentRole.ACCOUNT_RESEARCH)
    narrative_name = "person-research-narrative" if person else "account-research-narrative"
    skills = {s.ref.name: s for s in current.skills}
    assert skills[narrative_name].ref.version == "v2"
    assert skills["research-narrative-editorial"].ref.version == "v1"
    assert next(s for s in previous.skills if s.ref.name == narrative_name).ref.version == "v1"
    assert "research-narrative-editorial" not in {s.ref.name for s in previous.skills}
    # The promotion is editorial only: preserve prompt template, grants, model and workspace.
    assert current.profile.model_dump(exclude={"version", "skills"}) == previous.profile.model_dump(
        exclude={"version", "skills"}
    )
    assert current.prompt_body == previous.prompt_body.replace(
        f"/{narrative_name}/v1/SKILL.md", f"/{narrative_name}/v2/SKILL.md"
    )
    for skill in previous.skills:
        if skill.ref.name != narrative_name:
            assert skills[skill.ref.name].ref == skill.ref
    shared_path = "/.deepagent/skills/research-narrative-editorial/v1/SKILL.md"
    assert shared_path in current.open_skill(skills[narrative_name].ref.address)
    old_bundle = load_quality_resources("person" if person else "account", version=22)
    assert (
        load_quality_resources(
            "person" if person else "account", expected_pin=bundle_pin(old_bundle)
        )
        == old_bundle
    )
    harness = make_workspace(
        tmp_path,
        active_policy=policy(max_total_bytes=1048576, max_file_bytes=262144, max_file_count=100),
    )
    try:
        materializer = AgentResourceMaterializer()
        materializer.materialize(lease=harness.lease, snapshot=current.resource_snapshot)
        materializer.verify_materialized(lease=harness.lease, snapshot=current.resource_snapshot)
        for skill in current.profile.skills:
            text = (harness.thread_path / skill.materialized_path).read_text()
            assert "{{skills." not in text
            assert current.open_skill(skill.resource.address) in text
        assert (harness.thread_path / shared_path.lstrip("/")).is_file()
    finally:
        harness.close()
