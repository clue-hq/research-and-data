from __future__ import annotations

import hashlib
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
        "prompt:research-specialist@v1",
        "prompt:research-specialist@v2",
        "prompt:reviewer@v1",
        "prompt:reviewer@v2",
    ]
    assert [item.ref.address for item in skills.list()] == [
        "skill:account-deep-steering@v1",
        "skill:account-deep-steering@v2",
        "skill:account-deep-steering@v3",
        "skill:account-gap-research@v1",
        "skill:account-gap-research@v2",
        "skill:account-gap-research@v3",
        "skill:artifact-review@v1",
        "skill:content-exemplar@v1",
        "skill:research-task@v1",
        "skill:research-task@v2",
        "skill:research-task@v3",
        "skill:research-task@v4",
        # Lexical, not numeric: the folder catalog sorts by address, so v10 sits beside v1.
        "skill:stage0-interview@v10",
        "skill:stage0-interview@v2",
        "skill:stage0-interview@v3",
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
        "profile:head-of-abm@v3",
        "profile:head-of-abm@v4",
        "profile:head-of-abm@v5",
        "profile:head-of-abm@v6",
        "profile:head-of-abm@v7",
        "profile:head-of-abm@v8",
        "profile:head-of-abm@v9",
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
