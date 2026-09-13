from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from clue_agents import (
    AgentCatalogError,
    FolderProfileCatalog,
    FolderPromptCatalog,
    FolderSkillCatalog,
    ProfileCatalog,
    PromptCatalog,
    SkillCatalog,
)

CATALOG_ROOT = Path(__file__).resolve().parents[2] / "platform" / "agents" / "catalog"
LEGACY_STAGE0 = (
    Path(__file__).resolve().parents[2]
    / "platform"
    / "agents"
    / "skills"
    / "stage0-interview-v1"
    / "SKILL.md"
)


def test_real_folder_catalog_is_strict_versioned_and_provider_neutral() -> None:
    prompts = FolderPromptCatalog((CATALOG_ROOT / "prompts").resolve(strict=True))
    skills = FolderSkillCatalog((CATALOG_ROOT / "skills").resolve(strict=True))
    profiles = FolderProfileCatalog((CATALOG_ROOT / "profiles").resolve(strict=True))

    assert isinstance(prompts, PromptCatalog)
    assert isinstance(skills, SkillCatalog)
    assert isinstance(profiles, ProfileCatalog)
    assert [item.ref.address for item in prompts.list()] == [
        "prompt:account-research@v1",
        "prompt:account-research@v2",
        "prompt:account-research@v3",
        "prompt:content-drafter@v1",
        "prompt:content-drafter@v2",
        "prompt:design@v1",
        "prompt:head-of-abm@v1",
        "prompt:head-of-abm@v2",
        "prompt:head-of-abm@v3",
        "prompt:head-of-abm@v4",
        "prompt:head-of-abm@v5",
        "prompt:head-of-abm@v6",
        "prompt:head-of-abm@v7",
        "prompt:head-of-abm@v8",
        # The workspace libraries: v8 with one sentence moved from the per-turn brand seeds to the
        # mounted `brand/knowledge/`.
        "prompt:head-of-abm@v9",
        "prompt:onboarding-synthesis@v1",
        "prompt:onboarding-synthesis@v2",
        "prompt:research-specialist@v1",
        "prompt:research-specialist@v2",
        "prompt:reviewer@v1",
        "prompt:reviewer@v2",
    ]
    assert [item.ref.address for item in skills.list()] == [
        "skill:account-deep-steering@v1",
        "skill:account-deep-steering@v2",
        "skill:account-deep-steering@v3",
        "skill:account-deep-steering@v4",
        "skill:account-deep-steering@v5",
        "skill:account-deep-steering@v6",
        "skill:account-deep-steering@v7",
        "skill:account-deep-steering@v8",
        "skill:account-gap-research@v1",
        "skill:account-gap-research@v2",
        "skill:account-gap-research@v3",
        "skill:artifact-review@v1",
        "skill:audience-persona@v1",
        "skill:audience-persona@v2",
        "skill:content-exemplar@v1",
        "skill:icp-synthesis@v1",
        "skill:icp-synthesis@v2",
        "skill:icp-synthesis@v3",
        # The operating manual's generated chapters. Each is an ordinary skill so the profile pins
        # it like any other and the capability map discloses it with its path; the builder
        # (`python -m clue_api.manual_build`) is their only writer.
        "skill:manual-errors@v1",
        "skill:manual-fields@v1",
        "skill:manual-limits@v1",
        "skill:manual-tools@v1",
        "skill:research-task@v1",
        "skill:research-task@v2",
        "skill:research-task@v3",
        "skill:research-task@v4",
        # Lexical, not numeric: the folder catalog sorts by address, so v10 sits beside v1.
        "skill:stage0-interview@v10",
        "skill:stage0-interview@v11",
        "skill:stage0-interview@v12",
        "skill:stage0-interview@v13",
        "skill:stage0-interview@v14",
        "skill:stage0-interview@v15",
        "skill:stage0-interview@v16",
        "skill:stage0-interview@v17",
        "skill:stage0-interview@v18",
        "skill:stage0-interview@v19",
        "skill:stage0-interview@v2",
        "skill:stage0-interview@v20",
        "skill:stage0-interview@v21",
        "skill:stage0-interview@v22",
        "skill:stage0-interview@v23",
        "skill:stage0-interview@v24",
        "skill:stage0-interview@v25",
        # The read tools' contract repairs: v25 with the three reads' output digests (and
        # `read_project_accounts`' input digest) re-measured off the typed descriptors.
        "skill:stage0-interview@v26",
        # The read tools' hotfix: v26 with `read_account_research`'s paged/prefixed contract and
        # `read_discovery_run`'s repaired input re-measured, and the §7c/§1 text they need.
        "skill:stage0-interview@v27",
        # The thread workspace: v27 with the §1 bullet that names `scratch/` as the notebook that
        # persists across the turns of one chat.
        "skill:stage0-interview@v28",
        # The workspace libraries: v28 with §1 rewritten around the two read-only mounts —
        # `brand/knowledge/` and the project library at `project/` — instead of the per-turn seeds.
        "skill:stage0-interview@v29",
        "skill:stage0-interview@v3",
        # The brand index path: v29 with §1 naming the brand library's manifest where it is
        # actually mounted — `brand/index.json`, the tree root, beside `knowledge/`.
        "skill:stage0-interview@v30",
        "skill:stage0-interview@v4",
        "skill:stage0-interview@v5",
        "skill:stage0-interview@v6",
        "skill:stage0-interview@v7",
        "skill:stage0-interview@v8",
        "skill:stage0-interview@v9",
    ]
    assert [item.ref.address for item in profiles.list()] == [
        "profile:account-research@v1",
        "profile:account-research@v2",
        "profile:account-research@v3",
        "profile:account-research@v4",
        "profile:account-research@v5",
        "profile:content-drafter@v1",
        "profile:content-drafter@v2",
        "profile:content-drafter@v3",
        "profile:content-drafter@v4",
        "profile:content-drafter@v5",
        "profile:design@v1",
        "profile:head-of-abm@v1",
        # Lexical, not numeric: the folder catalog sorts by address, so v10 sits beside v1.
        "profile:head-of-abm@v10",
        "profile:head-of-abm@v11",
        "profile:head-of-abm@v12",
        "profile:head-of-abm@v13",
        "profile:head-of-abm@v14",
        "profile:head-of-abm@v15",
        "profile:head-of-abm@v16",
        "profile:head-of-abm@v17",
        "profile:head-of-abm@v18",
        "profile:head-of-abm@v19",
        "profile:head-of-abm@v2",
        "profile:head-of-abm@v20",
        "profile:head-of-abm@v21",
        "profile:head-of-abm@v22",
        "profile:head-of-abm@v23",
        "profile:head-of-abm@v24",
        "profile:head-of-abm@v25",
        "profile:head-of-abm@v26",
        "profile:head-of-abm@v27",
        "profile:head-of-abm@v28",
        "profile:head-of-abm@v29",
        "profile:head-of-abm@v3",
        "profile:head-of-abm@v30",
        "profile:head-of-abm@v31",
        "profile:head-of-abm@v32",
        "profile:head-of-abm@v33",
        "profile:head-of-abm@v34",
        "profile:head-of-abm@v35",
        "profile:head-of-abm@v36",
        "profile:head-of-abm@v37",
        "profile:head-of-abm@v38",
        "profile:head-of-abm@v39",
        "profile:head-of-abm@v4",
        # v40 (2026-08-27 demo-night model correction) shipped without this line; the list is
        # exhaustive, so its absence was a red assertion, not an omission this catalog tolerates.
        "profile:head-of-abm@v40",
        "profile:head-of-abm@v41",
        "profile:head-of-abm@v42",
        "profile:head-of-abm@v43",
        "profile:head-of-abm@v44",
        # ARV2 Track R, R4: v44 plus `launch_arv2_discovery@1` and stage0-interview v22.
        "profile:head-of-abm@v45",
        # ARV2 context and authoring: v45 plus `author_icp_document@1` and
        # `request_persona_synthesis@1`, and stage0-interview v23.
        "profile:head-of-abm@v46",
        # The project plan: v46 plus `write_project_document@1`, and stage0-interview v24.
        "profile:head-of-abm@v47",
        # The ARV2 reads: v47 plus `read_project_accounts@1`, `read_account_research@1` and
        # `read_discovery_run@1`, and stage0-interview v25.
        "profile:head-of-abm@v48",
        # The read tools' contract repairs: v48 with the three reads re-pinned and
        # stage0-interview v26.
        "profile:head-of-abm@v49",
        "profile:head-of-abm@v5",
        # The read tools' hotfix: v49 with the three reads re-pinned and stage0-interview v27.
        "profile:head-of-abm@v50",
        # The thread workspace: v50 with `scratch/`/`reads/` granted, `work/` dropped, the quota
        # raised for a notebook that persists, and stage0-interview v28.
        "profile:head-of-abm@v51",
        # The workspace libraries: v51 plus the `brand/` and `project/` read-only mounts, with
        # stage0-interview v29 and prompt head-of-abm v9.
        "profile:head-of-abm@v52",
        # The brand index path: v52 with stage0-interview v30.
        "profile:head-of-abm@v53",
        "profile:head-of-abm@v6",
        "profile:head-of-abm@v7",
        "profile:head-of-abm@v8",
        "profile:head-of-abm@v9",
        "profile:onboarding-synthesis@v1",
        "profile:onboarding-synthesis@v2",
        "profile:onboarding-synthesis@v3",
        "profile:research-specialist@v1",
        "profile:research-specialist@v2",
        "profile:research-specialist@v3",
        "profile:research-specialist@v4",
        "profile:research-specialist@v5",
        "profile:research-specialist@v6",
        "profile:research-specialist@v7",
        "profile:reviewer@v1",
        "profile:reviewer@v2",
        "profile:reviewer@v3",
        "profile:reviewer@v4",
        "profile:reviewer@v5",
    ]
    stage0 = skills.get("stage0-interview", "v2")
    assert "Only a human confirms" in stage0.body
    assert "confirm_project_product@1" not in {pin.address for pin in stage0.required_tools}
    assert "override_stage0_readiness@1" not in {pin.address for pin in stage0.required_tools}
    with pytest.raises(AgentCatalogError, match="unavailable"):
        prompts.get("head-of-abm", "latest")
    with pytest.raises(AgentCatalogError, match="digest changed"):
        prompts.get("head-of-abm", "v1", expected_sha256="0" * 64)


def test_stage0_v2_is_additive_and_does_not_mutate_the_used_v1_resource() -> None:
    assert hashlib.sha256(LEGACY_STAGE0.read_bytes()).hexdigest() == (
        "15576f389fb328dfc519d3b497584581181df281f80c9c6ef66cd2acd7e65461"
    )
    stage0_v2 = FolderSkillCatalog((CATALOG_ROOT / "skills").resolve(strict=True)).get(
        "stage0-interview", "v2"
    )
    assert stage0_v2.ref.sha256 == (
        "9ad718c63c913eea88ad1dd566e56a0ace4d8226341ce2072ec9cb06d4959b4f"
    )
    stage0_v3 = FolderSkillCatalog((CATALOG_ROOT / "skills").resolve(strict=True)).get(
        "stage0-interview", "v3"
    )
    assert stage0_v3.ref.sha256 == (
        "f9d069be847cfd972316a76c57f234c70c57157d13947efd55a38014abc447b7"
    )


def test_integration_preserves_pilot_history_and_mints_combined_resources() -> None:
    historical_hashes = {
        "profiles/head-of-abm/v24/profile.yaml": (
            "709e1d88715aed50220111a1e9025d78f53c97ae61096f869ac3cb1b8eb441de"
        ),
        "profiles/head-of-abm/v25/profile.yaml": (
            "ad088f21c29c1d4399ef75c17963a43d6d6051f36540864ef162dab580cae5f2"
        ),
        "skills/stage0-interview/v11/SKILL.md": (
            "aa9ad3f354bcc40b6b8ff85a2ed1cb7b4c7d7c9e1501b86fa9c68766ec1012bd"
        ),
        "skills/stage0-interview/v12/SKILL.md": (
            "2209ba1daac992285d608fbf287f82604355bf876c700d2e15b46df945fc6ea1"
        ),
    }
    for relative_path, expected_sha256 in historical_hashes.items():
        assert hashlib.sha256((CATALOG_ROOT / relative_path).read_bytes()).hexdigest() == (
            expected_sha256
        )

    recipe_root = CATALOG_ROOT.parents[1] / "execution" / "recipes"
    for filename, expected_sha256 in {
        "recipe0-stage0-v7.json": (
            "67d86848497a9f6e884961eb31f127d70a32578c10e5c07cc80272fb7a539c7a"
        ),
        "recipe0-stage0-v8.json": (
            "cbe23f9a48caa5e7672c0ddbbad9f7f5604b4c84d6b2030da0661784e771fe8e"
        ),
    }.items():
        assert hashlib.sha256((recipe_root / filename).read_bytes()).hexdigest() == expected_sha256

    profiles = FolderProfileCatalog((CATALOG_ROOT / "profiles").resolve(strict=True))
    profile = profiles.get("head-of-abm", "v35").definition
    assert [(item.name, item.version) for item in profile.skills] == [
        ("stage0-interview", "v20"),
        ("account-deep-steering", "v6"),
    ]
    required_tools = {
        "evaluate_stage0_readiness@2",
        "synthesize_icps@3",
        "open_icp_confirmation_gate@1",
        "launch_selected_account_research@1",
        "list_client_knowledge@2",
        "inspect_client_claim@2",
        "list_product_knowledge@1",
        "inspect_product_claim@1",
        "open_product_selection_gate@1",
        "open_discovery_configuration_gate@1",
        "start_confirmed_project_run@3",
    }
    assert required_tools <= {f"{item.name}@{item.version}" for item in profile.tools}

    recipe = json.loads((recipe_root / "recipe0-stage0-v15.json").read_text())
    assert recipe["version"] == 15
    assert required_tools <= set(recipe["graph"]["tool_allowlist"])

    skill = FolderSkillCatalog((CATALOG_ROOT / "skills").resolve(strict=True)).get(
        "stage0-interview", "v20"
    )
    assert "`finalize_turn.user_message`" in skill.body
    assert "normal assistant response" in skill.body
    assert "Do not place that synthesis inside the approval" in skill.body
    assert "explicitly requests a different bounded account count" in skill.body
    assert "newest approved exact scope overrides" in skill.body


def test_catalog_rejects_unknown_metadata_and_mutable_aliases(tmp_path: Path) -> None:
    copied = tmp_path / "catalog"
    shutil.copytree(CATALOG_ROOT, copied)
    prompt = copied / "prompts/head-of-abm/v1/SYSTEM.md"
    prompt.write_text(
        prompt.read_text().replace(
            "framework: deepagents",
            "unexpected_policy: true\nframework: deepagents",
        )
    )
    with pytest.raises(AgentCatalogError, match="metadata is invalid"):
        FolderPromptCatalog((copied / "prompts").resolve(strict=True))

    shutil.rmtree(copied)
    shutil.copytree(CATALOG_ROOT, copied)
    shutil.copytree(
        copied / "skills/stage0-interview/v2",
        copied / "skills/stage0-interview/latest",
    )
    with pytest.raises(AgentCatalogError, match="not immutable"):
        FolderSkillCatalog((copied / "skills").resolve(strict=True))


@pytest.mark.parametrize("attack", ["symlink", "executable", "extra"])
def test_catalog_rejects_link_executable_and_extra_files(
    tmp_path: Path,
    attack: str,
) -> None:
    copied = tmp_path / "catalog"
    shutil.copytree(CATALOG_ROOT, copied)
    resource = copied / "prompts/head-of-abm/v1/SYSTEM.md"
    if attack == "symlink":
        target = tmp_path / "outside.md"
        target.write_text("outside")
        resource.unlink()
        resource.symlink_to(target)
    elif attack == "executable":
        resource.chmod(0o755)
    else:
        (resource.parent / "unexpected.txt").write_text("extra")

    with pytest.raises(AgentCatalogError):
        FolderPromptCatalog((copied / "prompts").resolve(strict=True))


def test_profile_and_resource_folder_identity_must_match(tmp_path: Path) -> None:
    copied = tmp_path / "catalog"
    shutil.copytree(CATALOG_ROOT, copied)
    profile = copied / "profiles/reviewer/v1/profile.yaml"
    profile.write_text(profile.read_text().replace("name: reviewer", "name: other"))
    with pytest.raises(AgentCatalogError, match="differs from its folder"):
        FolderProfileCatalog((copied / "profiles").resolve(strict=True))
