"""write_section (Lane B Task 15): a new section through the section port, placed by name."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from lumen_agent.site.tools import SiteTools
from lumen_agent.site.workspace import materialize_workspace, read_site_files
from site_fixtures import FakeSections, garner_site, inputs_for

SOURCE = 'export const schema = z.object({ id: z.string(), surface: z.string(), quote: z.string() });'


def _tools(tmp_path: Path, sections) -> SiteTools:
    workspace = tmp_path / "workspace"
    inputs = inputs_for(sections=sections)
    site = garner_site()
    materialize_workspace(workspace, inputs, site=site)
    return SiteTools(workspace=workspace, inputs=inputs, base_site=site, retry_delay_s=0)


def test_a_written_section_joins_the_turn_and_its_catalog(tmp_path: Path) -> None:
    sections = FakeSections()
    tools = _tools(tmp_path, sections)
    result = tools.write_section("StepsBand", SOURCE)
    assert result.startswith(
        'WRITTEN: StepsBand is ready for this site. Place it in a page with "type": "StepsBand" and these props:\n'
    )
    assert sections.calls == [("StepsBand", SOURCE)]
    assert tools.sections["StepsBand"].digest == "e" * 64
    assert "## StepsBand" in (tools.workspace / "catalog" / "seller-components.md").read_text()
    assert tools.events[-1]["kind"] == "section_written" and tools.events[-1]["digest"] == "e" * 64


def test_a_placed_section_is_pinned_when_the_site_is_read_back(tmp_path: Path) -> None:
    tools = _tools(tmp_path, FakeSections())
    tools.write_section("StepsBand", SOURCE)
    page = json.loads((tools.workspace / "page.json").read_text())
    page["content"].append({"type": "StepsBand", "props": {"id": "steps", "surface": "page", "quote": "Fewer surprises."}})
    (tools.workspace / "page.json").write_text(json.dumps(page))
    assert read_site_files(tools.workspace, tools.base_site, tools.sections)["agent_sections"] == {"StepsBand": "e" * 64}


def test_check_errors_come_back_as_a_list_to_fix(tmp_path: Path) -> None:
    error = 'class "text-red-500" is a Tailwind palette colour; use the brand\'s text-ink-*, bg-surface-* or border-line-*'
    tools = _tools(tmp_path, FakeSections(errors=[error]))
    assert tools.write_section("StepsBand", SOURCE) == f"NOT WRITTEN (fix these, then call write_section again):\n- {error}"
    assert "StepsBand" not in tools.sections


def test_names_are_checked_before_anything_compiles(tmp_path: Path) -> None:
    sections = FakeSections()
    tools = _tools(tmp_path, sections)
    assert tools.write_section("stepsBand", SOURCE) == "NOT WRITTEN: a section name is PascalCase letters and digits, for example StepsBand."
    assert tools.write_section("CtaBand", SOURCE) == "NOT WRITTEN: CtaBand is one of the built-in sections; choose another name."
    assert sections.calls == []


def test_a_toolchain_that_cannot_answer_reads_as_the_check_crashing(tmp_path: Path) -> None:
    class Broken:
        def compile(self, *, name, source):
            raise RuntimeError("tsc is not installed")

    assert _tools(tmp_path, Broken()).write_section("StepsBand", SOURCE) == "NOT WRITTEN: the check crashed: tsc is not installed"


def _site_placing_pinned_steps_band(tmp_path: Path, sections) -> SiteTools:
    """A site whose home page places StepsBand, pinned at an older digest ("a" * 64)."""

    from lumen_agent.site.inputs import SiteSection

    site = garner_site()
    site["pages"] = {**site["pages"], "/": copy.deepcopy(site["pages"]["/"])}
    site["pages"]["/"]["content"].append(
        {"type": "StepsBand", "props": {"id": "steps", "surface": "page", "quote": "Fewer surprises."}})
    site["agent_sections"] = {"StepsBand": "a" * 64}
    pinned = SiteSection(name="StepsBand", digest="a" * 64, props_schema={"type": "object"}, module_js="export {}", css="",
                         source="export function StepsBand() { return null; }")
    workspace = tmp_path / "workspace"
    inputs = inputs_for(sections=sections, agent_sections={"StepsBand": pinned})
    materialize_workspace(workspace, inputs, site=site)
    return SiteTools(workspace=workspace, inputs=inputs, base_site=site, retry_delay_s=0)


def test_rewriting_a_placed_section_under_its_own_name_changes_the_site(tmp_path: Path) -> None:
    """The NAV Logistics header (2026-10-28): a section rewritten under the name the page already
    places changes no page file, yet the page now shows new code, so the turn must save it."""

    tools = _site_placing_pinned_steps_band(tmp_path, FakeSections())
    assert tools.site_unchanged()
    tools.write_section("StepsBand", SOURCE)
    assert not tools.site_unchanged()
    assert read_site_files(tools.workspace, tools.base_site, tools.sections)["agent_sections"] == {"StepsBand": "e" * 64}


def test_a_written_section_no_page_places_leaves_the_site_unchanged(tmp_path: Path) -> None:
    tools = _tools(tmp_path, FakeSections())
    tools.write_section("StepsBand", SOURCE)
    assert tools.site_unchanged()


def test_the_agent_reads_the_code_of_the_sections_its_page_pins(tmp_path: Path) -> None:
    """The NAV Logistics header was rewritten from scratch twice: the agent saw only its props. Each
    pinned section's own code is now in the workspace, and its catalog entry says where."""

    tools = _site_placing_pinned_steps_band(tmp_path, FakeSections())
    code = tools.workspace / "catalog" / "sections" / "StepsBand.tsx"
    assert code.read_text() == "export function StepsBand() { return null; }"
    entry = (tools.workspace / "catalog" / "seller-components.md").read_text()
    assert "Its code is in `catalog/sections/StepsBand.tsx`." in entry


def test_a_written_section_leaves_its_code_where_the_agent_reads_it(tmp_path: Path) -> None:
    tools = _tools(tmp_path, FakeSections())
    tools.write_section("StepsBand", SOURCE)
    assert (tools.workspace / "catalog" / "sections" / "StepsBand.tsx").read_text() == SOURCE
    assert tools.sections["StepsBand"].source == SOURCE
    assert "Its code is in `catalog/sections/StepsBand.tsx`." in (
        tools.workspace / "catalog" / "seller-components.md").read_text()


def test_a_section_whose_code_is_unknown_gets_no_code_file(tmp_path: Path) -> None:
    from lumen_agent.site.inputs import SiteSection

    pinned = SiteSection(name="OldBand", digest="a" * 64, props_schema={"type": "object"}, module_js="export {}", css="")
    workspace = tmp_path / "workspace"
    materialize_workspace(workspace, inputs_for(agent_sections={"OldBand": pinned}), site=garner_site())
    assert not (workspace / "catalog" / "sections").exists()
    assert "catalog/sections" not in (workspace / "catalog" / "seller-components.md").read_text()
