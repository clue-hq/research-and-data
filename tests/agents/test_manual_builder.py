"""The operating-manual builder: the four generated chapters, and the drift gate.

Offline by construction. The toolbelt is composed with every capability absent
(``build_toolbelt(storage=None, gateway=None)``) because a descriptor is a static contract: the
chapter is rendered from the tool's declared shape, never from a live service.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from clue_agents.manual import build as manual
from clue_api.manual_build import build_facts, load_toolbelt, main

PROFILE_NAME = "head-of-abm"
#: The profile the builder itself describes. It tracked `v54` — the version that first disclosed
#: the manual — until `open_design_leg@4` stopped being registered (the tool promoted to `@5` in
#: place, as every promotion on this entry has), which made an older profile's exact grant
#: unresolvable against the live belt and this fixture fail on a tool that no longer exists. The
#: fixture follows the builder's own pin instead, so it always describes a grant the belt serves.
PROFILE_VERSION = manual.PROFILE_VERSION


@pytest.fixture(scope="module")
def toolbelt() -> object:
    return load_toolbelt()


@pytest.fixture(scope="module")
def profile() -> object:
    return manual.load_profile(manual.DEFAULT_CATALOG_ROOT, PROFILE_NAME, PROFILE_VERSION)


@pytest.fixture(scope="module")
def notes() -> dict[str, object]:
    return manual.load_notes(manual.DEFAULT_CATALOG_ROOT)


def test_tools_chapter_has_one_section_per_granted_tool_in_profile_order(
    toolbelt: object, profile: object, notes: dict[str, object]
) -> None:
    chapter = manual.build_tools_chapter(toolbelt, profile, notes)
    granted = [pin.name for pin in profile.tools]  # type: ignore[attr-defined]
    # v61 replaces the two ICP/product gate tools with one automatic targeting tool.
    # 21 since head-of-abm@v62 granted web_search@1; 18 since v68 dropped three retired-lane tools;
    # 19 since v71 granted manage_products@1; 23 since v76 granted the four CRM-integration tools;
    # 26 since v77 granted the three CRM write tools.
    assert len(granted) == 26

    headings = [line[3:].strip() for line in chapter.body.splitlines() if line.startswith("## ")]
    # Every granted tool, in profile order, then the two fixed sections.
    assert headings[: len(granted)] == [
        f"{pin.name}@{pin.version}"
        for pin in profile.tools  # type: ignore[attr-defined]
    ]
    assert headings[len(granted) :] == ["The framework file tools", "finalize_turn"]

    sections = _sections(chapter.body)
    for name in granted:
        section = sections[next(k for k in sections if k.startswith(f"{name}@"))]
        for code in notes[name]["refusals"]:  # type: ignore[index]
            assert code in section, f"{name} chapter is missing refusal code {code}"


def test_a_granted_tool_with_no_notes_entry_fails_the_build(
    toolbelt: object, profile: object, notes: dict[str, object]
) -> None:
    stripped = {key: value for key, value in notes.items() if key != "read_account_research"}
    with pytest.raises(manual.ManualBuildError) as excinfo:
        manual.build_tools_chapter(toolbelt, profile, stripped)
    assert "read_account_research" in str(excinfo.value)


def test_render_skill_rewrites_chapter_tokens_to_materialized_paths() -> None:
    chapter = manual.Chapter(
        name="tools",
        summary="Manual: a test chapter.",
        body="Terms are defined in manual:glossary.\n",
    )
    rendered = manual.render_skill(chapter, version="v1", links=manual.materialized_links("v1"))
    assert ".deepagent/skills/manual-glossary/v1/SKILL.md" in rendered
    assert "manual:glossary" not in rendered
    assert rendered.startswith('---\nschema_version: "1"\nkind: skill\nname: manual-tools\n')


def test_render_skill_refuses_an_unknown_chapter_token() -> None:
    chapter = manual.Chapter(name="tools", summary="Manual: x.", body="see manual:nowhere\n")
    with pytest.raises(manual.ManualBuildError):
        manual.render_skill(chapter, version="v1", links=manual.materialized_links("v1"))


def test_check_exits_one_when_a_committed_chapter_is_altered(tmp_path: Path) -> None:
    copied = tmp_path / "catalog"
    shutil.copytree(manual.DEFAULT_CATALOG_ROOT, copied)
    assert main(["--check", "--catalog-root", str(copied)]) == 0

    altered = copied / "skills" / "manual-limits" / manual.MANUAL_VERSION / "SKILL.md"
    altered.write_bytes(altered.read_bytes() + b"\ndrifted\n")
    assert main(["--check", "--catalog-root", str(copied)]) == 1


def test_link_rewrites_the_handwritten_chapters_once_and_leaves_the_generated_ones_alone(
    tmp_path: Path,
) -> None:
    """`--link` is the hand-written half's rewriter: idempotent, and never the builder's files."""

    copied = tmp_path / "catalog"
    shutil.copytree(manual.DEFAULT_CATALOG_ROOT, copied)
    generated_before = {
        name: manual.chapter_path(copied, name, manual.MANUAL_VERSION).read_bytes()
        for name in manual.GENERATED_CHAPTERS
    }

    target = manual.chapter_path(copied, "glossary", manual.MANUAL_VERSION)
    target.write_text(target.read_text() + "\nA turn is manual:turn.\n", encoding="utf-8")

    assert main(["--link", "--catalog-root", str(copied)]) == 0
    linked = target.read_text(encoding="utf-8")
    assert f"`.deepagent/skills/manual-turn/{manual.MANUAL_VERSION}/SKILL.md`" in linked
    assert "manual:turn" not in linked

    # A second pass has nothing left to match, so the bytes do not move.
    assert main(["--link", "--catalog-root", str(copied)]) == 0
    assert target.read_text(encoding="utf-8") == linked

    for name, payload in generated_before.items():
        assert manual.chapter_path(copied, name, manual.MANUAL_VERSION).read_bytes() == payload, (
            f"--link rewrote the generated chapter manual-{name}; render_skill owns its tokens"
        )


def test_link_refuses_a_token_that_names_no_chapter(tmp_path: Path) -> None:
    copied = tmp_path / "catalog"
    shutil.copytree(manual.DEFAULT_CATALOG_ROOT, copied)
    target = manual.chapter_path(copied, "glossary", manual.MANUAL_VERSION)
    target.write_text(target.read_text() + "\nSee manual:nowhere.\n", encoding="utf-8")

    with pytest.raises(manual.ManualBuildError, match="manual:nowhere, which is not a chapter"):
        main(["--link", "--catalog-root", str(copied)])


def test_committed_chapters_equal_a_fresh_build(toolbelt: object) -> None:
    rendered = manual.build_chapters(
        toolbelt=toolbelt,
        facts=build_facts(),
        catalog_root=manual.DEFAULT_CATALOG_ROOT,
    )
    assert sorted(rendered) == ["errors", "fields", "limits", "tools"]
    for name, text in rendered.items():
        path = manual.chapter_path(manual.DEFAULT_CATALOG_ROOT, name, manual.MANUAL_VERSION)
        assert path.read_bytes() == text.encode(), f"manual-{name} is stale; run `make manual`"


def test_every_generated_summary_fits_the_capability_map(toolbelt: object) -> None:
    chapters = manual.build_chapter_objects(
        toolbelt=toolbelt,
        facts=build_facts(),
        catalog_root=manual.DEFAULT_CATALOG_ROOT,
    )
    assert len(chapters) == 4
    for chapter in chapters.values():
        assert chapter.summary.startswith("Manual: ")
        assert len(chapter.summary) <= 160, chapter.summary


def _sections(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {key: "\n".join(value) for key, value in sections.items()}


@pytest.mark.parametrize("gate", ["crm_write_permission", ""])
def test_a_tool_that_opens_a_card_spells_out_the_link_the_chat_recognises(gate: str) -> None:
    """The chat draws a card only for ``object_type == "agent_gate"`` (CRM card, 2026-10-22)."""

    line = manual._gate_line(gate)

    assert line.startswith("- Opens a human gate: yes")
    assert (
        'Put it into `open_gate_refs` as `{object_type: "agent_gate", object_id: <the gate id it '
        "returns>}` when you finalize, or the human never sees the card." in line
    )
