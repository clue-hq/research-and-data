"""T3: workspace assembly, on a research block shaped like the platform's (no database)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from trials_puck_agent import workspace as ws

SPIKE = Path(__file__).resolve().parents[2]

WHY_NOW = {
    "section_key": "why-now",
    "body_text": json.dumps({
        "h1": "Why now",
        "intro": [{"claimIds": ["61ba3351-157f-53c9-a6e4-7ee89856b693"], "kind": "inference",
                   "text": "A new CHCO and cost testimony make a first call timely."}],
        "items": [{
            "h2": "Healthcare cost is on the record",
            "body": [{"claimIds": ["87b908a3-e799-5ee6-8b39-175a98e55ea9"], "kind": "quote",
                      "text": "Costs “will rise 8% in the coming school year.”"},
                     {"claimIds": ["cc0805bc-da90-57c5-b90b-785e98bee92a"], "kind": "fact",
                      "text": "The budget added $4.2 million for healthcare."}],
            "contactRefs": [{"contactId": "e78569d2", "name": "Nalisa Clark"},
                            {"contactId": "fbde4757", "name": "Michael Puntschenko"}],
        }],
    }),
    "cited_claim_ids": ["61ba3351-157f-53c9-a6e4-7ee89856b693"],
}
RESTRICTED = {"section_key": "private", "body_text": json.dumps({"h1": "Private", "restricted": True})}
TRUNCATED = {"section_key": "long", "body_text": '{"h1": "Long", "intro": [{"text": "cut off'}


@dataclass
class Doc:
    path: str
    kind: str
    body_text: str


@dataclass
class Knowledge:
    documents: list
    confirmed_icp_path: str


def test_research_becomes_plain_markdown_without_claim_ids() -> None:
    text = ws.research_markdown("SCSD: overview", [WHY_NOW, RESTRICTED, TRUNCATED])
    assert "## Why now" in text and "### Healthcare cost is on the record" in text
    assert "- (inference) A new CHCO" in text and "- (quote) Costs" in text
    assert "- The budget added $4.2 million for healthcare." in text
    assert "61ba3351" not in text and "claimIds" not in text
    assert "Private" not in text  # restricted sections stay out
    assert "cut off" in text  # a block that is not valid JSON is kept as text, not dropped


def test_people_come_from_the_contact_references() -> None:
    assert ws.research_people([WHY_NOW, WHY_NOW]) == ["Nalisa Clark", "Michael Puntschenko"]


def test_assemble_writes_the_workspace_the_prompt_describes(tmp_path: Path) -> None:
    knowledge = Knowledge(
        documents=[Doc("product/garner-core.md", "product", "Garner Core"),
                   Doc("icp/mid-market.md", "icp", "US mid-market employers")],
        confirmed_icp_path="icp/mid-market.md",
    )
    workspace = tmp_path / "workspace"
    summary = ws.assemble(
        workspace, spike_root=SPIKE, brand="garner", seller="Garner Health", site="agent-test", brief="For the page\n",
        account_name="Syracuse City School District", overview=[WHY_NOW], insights=[],
        knowledge=knowledge,
    )
    for path in ["brief.md", "research/overview.md", "research/insights.md",
                 "seller/index.md", "seller/product/garner-core.md", "catalog/index.md",
                 "catalog/sections.md", "brand/brand.md", "skills/building-with-puck/SKILL.md",
                 ".run.json"]:
        assert (workspace / path).exists(), path
    assert not (workspace / "page.json").exists() and not (workspace / "shell.json").exists()
    assert "(the confirmed ICP)" in (workspace / "seller/index.md").read_text()
    assert (workspace / "brand/brand.md").read_text().startswith("# Brand: Garner Health")
    assert summary["people_in_research"] == 2 and summary["seller_files"] == 2 and summary["clones"] > 0


def test_an_account_with_no_written_research_says_so(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    ws.assemble(
        workspace, spike_root=SPIKE, brand="conduit", seller="Conduit", site="agent-test", brief="For the page\n",
        account_name="Atrium Hospitality", overview=[], insights=[], knowledge=None,
    )
    assert "no written research" in (workspace / "research/README.md").read_text()


def test_the_site_summary_names_every_page_section_and_image(tmp_path: Path) -> None:
    site = json.loads((SPIKE / "data" / "sites" / "garner-syracuse.json").read_text())
    workspace = tmp_path / "workspace"
    (workspace / "pages").mkdir(parents=True)
    (workspace / ".run.json").write_text(json.dumps({"brand": "garner", "site": "t", "route": "/"}))
    (workspace / "page.json").write_text(json.dumps(site["pages"]["/"]))
    (workspace / "pages" / "analysis.json").write_text(json.dumps(site["pages"]["/analysis"]))
    (workspace / "shell.json").write_text(json.dumps(site["shell"]))
    text = ws.site_summary(workspace, SPIKE)
    assert "## / (page.json)" in text and "## /analysis (pages/analysis.json)" in text
    assert "Lower medical spend for SCSD" in text and "Prepared for: Syracuse City School District" in text
    assert "StatsBand on the brandSubtle surface" in text


def test_site_changes_say_what_moved_changed_and_appeared() -> None:
    before = {"/": {"content": [{"type": "A", "props": {"id": "hero", "x": 1}}, {"type": "B", "props": {"id": "proof"}}]}}
    after = {"/": {"content": [{"type": "B", "props": {"id": "proof"}}, {"type": "A", "props": {"id": "hero", "x": 2}}]},
             "/analysis": {"content": []}}
    notes = ws.site_changes(before, after)
    assert "added the page /analysis" in notes
    assert "/: changed hero (x)" in notes and "/: new order proof, hero" in notes
