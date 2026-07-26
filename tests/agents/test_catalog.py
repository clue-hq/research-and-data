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
        "prompt:content-drafter@v1",
        "prompt:head-of-abm@v1",
        "prompt:research-specialist@v1",
        "prompt:reviewer@v1",
    ]
    assert [item.ref.address for item in skills.list()] == ["skill:stage0-interview@v2"]
    assert len(profiles.list()) == 4
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
