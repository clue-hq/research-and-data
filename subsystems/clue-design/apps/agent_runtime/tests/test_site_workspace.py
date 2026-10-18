"""The site agent's workspace (Lane B Task 5); research tests ported from the Puck spike."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from lumen_agent.site import workspace as ws
from lumen_agent.site.inputs import AccountLogo, SiteSection
from lumen_agent.site.workspace import targets_block
from site_fixtures import FakeVersions, garner_brand, garner_site, inputs_for

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
QUOTE_ID = "87b908a3-e799-5ee6-8b39-175a98e55ea9"
BUDGET_ID = "cc0805bc-da90-57c5-b90b-785e98bee92a"
INFERENCE_ID = "61ba3351-157f-53c9-a6e4-7ee89856b693"
CLAIMS = [
    {"claim_id": BUDGET_ID, "field_key": "account.research_finding",
     "value": {"topic": "Budget", "finding": "Healthcare up $4.2 million", "notes": ["The reporter's estimate."],
               "review": {"status": "supported"}},
     "source_url": "https://example.org/budget.pdf", "evidence": "", "evidence_truncated": False},
    {"claim_id": QUOTE_ID, "field_key": "account.employee_count", "value": 4108,
     "source_url": "https://example.org/nces", "evidence": "Total staff FTE 4,108.72 for the district",
     "evidence_truncated": True},
]


def test_research_becomes_plain_markdown_without_claim_ids() -> None:
    text = ws.research_markdown("SCSD: overview", [WHY_NOW, RESTRICTED, TRUNCATED])
    assert "## Why now" in text and "### Healthcare cost is on the record" in text
    assert "- (inference) A new CHCO" in text and "- (quote) Costs" in text
    assert "61ba3351" not in text and "claimIds" not in text
    assert "## Private (background only, never on the page)" in text
    assert "cut off" in text


def test_claim_labels_skip_claims_not_served_and_the_claims_file_says_what_each_says() -> None:
    labels = ws.claim_labels([WHY_NOW], served={QUOTE_ID, BUDGET_ID})
    assert labels == {QUOTE_ID: "c1", BUDGET_ID: "c2"}
    text = ws.claims_markdown("Syracuse City School District", labels, CLAIMS)
    assert "Says: Healthcare up $4.2 million\nTopic: Budget\nNotes: The reporter's estimate.\n" in text
    assert "Quote (shortened): “Total staff FTE 4,108.72 for the district”" in text
    assert QUOTE_ID not in text


def test_held_dispositions_drop_only_statements_resting_on_a_real_rule() -> None:
    """Review focus 2: a real rule drops the statement; an unverified finding or another
    entity's claim does not."""

    held = ws.held_claim_ids({
        QUOTE_ID: "served",
        BUDGET_ID: "held:outreach_unsafe",
        INFERENCE_ID: "held:unverified_finding",
        "x": "held:other_entity",
        "y": "not_found",
        "z": "held:sensitive",
    })
    assert held == {BUDGET_ID, "z"}
    text = ws.research_markdown("SCSD: overview", [WHY_NOW], {QUOTE_ID: "c1"}, held=held)
    assert "Costs “will rise 8% in the coming school year.” [c1]" in text
    assert "The budget added $4.2 million" not in text
    assert "A new CHCO" in text  # rests on an unverified finding: kept


def test_materialize_writes_the_workspace_the_prompt_describes(tmp_path: Path) -> None:
    seller = SimpleNamespace(
        documents=[SimpleNamespace(path="product/garner-core.md", kind="product", version=1,
                                   status="active", body_text="Garner Core")],
        documents_sha256="f" * 64, confirmed_icp_path=None, product_set=None,
    )
    reads = SimpleNamespace(seller_knowledge=lambda: seller)
    inputs = inputs_for(
        overview=[WHY_NOW], claims=CLAIMS, platform_reads=reads,
        project_files=[{"path": "instructions.md", "body_text": "Lead with cost."},
                       {"path": "decisions.md", "body_text": "No video."}],
    )
    workspace = tmp_path / "workspace"
    summary = ws.materialize_workspace(workspace, inputs, site=garner_site())
    for path in ["brief.md", "research/overview.md", "research/insights.md", "research/claims.md",
                 "seller/index.md", "seller/product/garner-core.md", "catalog/index.md",
                 "brand/brand.md", "skills/building-with-puck/SKILL.md",
                 "skills-e5/writing-a-section/SKILL.md", "project-context/instructions.md",
                 "project-context/decisions.md", "page.json", "pages/analysis.json", "shell.json",
                 "site.md"]:
        assert (workspace / path).exists(), path
    assert (workspace / "fetched").is_dir()
    assert summary["claims_labelled"] == 2 and summary["people_in_research"] == 2
    assert "## The account's logo (header only)\n\nNone was found." in (workspace / "brand/brand.md").read_text()


def test_materialize_rebuilds_inputs_but_keeps_memory(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    ws.materialize_workspace(workspace, inputs_for(overview=[WHY_NOW]), site=garner_site())
    (workspace / "plan.md").write_text("my plan")
    (workspace / "history.md").write_text("# history")
    (workspace / "fetched" / "story.md").write_text("Source: x")
    (workspace / "research" / "stale.md").write_text("old research")
    ws.materialize_workspace(workspace, inputs_for(), site=garner_site())
    assert not (workspace / "research" / "stale.md").exists()
    assert "no written research" in (workspace / "research" / "README.md").read_text()
    assert (workspace / "plan.md").read_text() == "my plan"
    assert (workspace / "history.md").read_text() == "# history"
    assert (workspace / "fetched" / "story.md").exists()
    assert {"research", "catalog", "brand", "page.json", "pages", "shell.json", "work", "large_tool_results"} <= ws.SESSION_REGENERATED
    assert "plan.md" not in ws.SESSION_REGENERATED and "fetched" not in ws.SESSION_REGENERATED


def test_only_a_live_workspace_gets_the_live_skills_and_they_are_rebuilt_every_request(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    ws.materialize_workspace(workspace, inputs_for(live_sites=True), site=garner_site())
    assert (workspace / "skills-live/making-a-section-interactive/SKILL.md").is_file()
    ws.materialize_workspace(workspace, inputs_for(), site=garner_site())
    assert not (workspace / "skills-live").exists()


def test_the_account_logos_are_listed_in_brand_md_and_join_the_turn_brand(tmp_path: Path) -> None:
    light = AccountLogo(cell="light_lockup", file="/asset-store/" + "1" * 64, content_type="image/svg+xml")
    other = AccountLogo(cell="unclassified", file="/asset-store/" + "2" * 64, content_type="image/png",
                        label="Dana.AI logo (site: light lockup, header)", alternative=True)
    workspace = tmp_path / "workspace"
    ws.materialize_workspace(workspace, inputs_for(account_logos=[light, other]), site=garner_site())
    brand_md = (workspace / "brand/brand.md").read_text()
    assert f"- `{light.file}`: the full logo, for light backgrounds" in brand_md
    assert brand_md.index(light.file) < brand_md.index("Other logos found for the account")
    assert f"- `{other.file}`: Dana.AI logo (site: light lockup, header)" in brand_md
    files = {a["file"] for a in ws.turn_brand(garner_brand(), [light, other])["assets"].values()}
    assert {light.file, other.file} <= files


def test_site_files_round_trip_and_agent_sections_follow_the_content(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    site = garner_site()
    ws.write_site_files(workspace, site)
    page = json.loads((workspace / "page.json").read_text())
    page["content"].append({"type": "QuoteBand", "props": {"id": "q", "surface": "muted", "quote": "A line."}})
    (workspace / "page.json").write_text(json.dumps(page))
    sections = {
        "QuoteBand": SiteSection(name="QuoteBand", digest="e" * 64, props_schema={}, module_js="", css=""),
        "Unused": SiteSection(name="Unused", digest="d" * 64, props_schema={}, module_js="", css=""),
    }
    read = ws.read_site_files(workspace, site, sections)
    assert read["id"] == site["id"] and read["title"] == site["title"]
    assert set(read["pages"]) == {"/", "/analysis"} and read["shell"] == site["shell"]
    assert read["agent_sections"] == {"QuoteBand": "e" * 64}


def test_the_site_summary_names_pages_sections_images_and_saved_versions(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ws.write_site_files(workspace, garner_site())
    versions = FakeVersions(sites={3: {}, 4: {}}).list_versions(10)
    text = ws.site_summary(workspace, garner_brand(), versions)
    assert "## / (page.json)" in text and "## /analysis (pages/analysis.json)" in text
    assert "Lower medical spend for SCSD" in text and "Prepared for: Syracuse City School District" in text
    assert "StatsBand on the brandSubtle surface" in text
    assert "## Saved versions" in text
    assert '- version 4: "request 4" (by the agent, 2026-10-11 14:02 UTC)' in text


def test_a_generated_image_is_described_by_its_prompt(tmp_path: Path) -> None:
    brand = garner_brand()
    file = "/asset-store/" + "9" * 64
    brand["assets"]["asset_gen_x"] = {"kind": "generated_image", "label": "A calm school scene",
                                      "description": "generated: A calm school scene", "mime": "image/png",
                                      "file": file, "logo": None}
    site = garner_site()
    site["pages"]["/"]["content"].append({"type": "FeatureSplit", "props": {
        "id": "gen", "surface": "page", "heading": "H", "body": "B", "image": file}})
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ws.write_site_files(workspace, site)
    assert f"{file} (generated: A calm school scene)" in ws.site_summary(workspace, brand)


def test_site_changes_and_history_say_what_happened_and_whether_it_was_saved(tmp_path: Path) -> None:
    before = {"/": {"content": [{"type": "A", "props": {"id": "hero", "x": 1}}, {"type": "B", "props": {"id": "proof"}}]}}
    after = {"/": {"content": [{"type": "B", "props": {"id": "proof"}}, {"type": "A", "props": {"id": "hero", "x": 2}}]},
             "/analysis": {"content": []}}
    notes = ws.site_changes(before, after)
    assert "added the page /analysis" in notes and "/: changed hero (x)" in notes
    ws.append_history(tmp_path, number=1, request="Warmer hero", changes=notes, shell_changed=False,
                      reply="Done.", saved=ws.saved_line(status="applied", stop_reason=None,
                                                         outcome_status="saved", version=5))
    ws.append_history(tmp_path, number=2, request="Add a page", changes=[], shell_changed=False,
                      reply="Stopped.", saved=ws.saved_line(status="failed", stop_reason="cancelled_by_request",
                                                            outcome_status=None, version=None))
    history = (tmp_path / "history.md").read_text()
    assert "## 1. Warmer hero\n- What changed: " in history and "- Saved: as version 5\n" in history
    assert "## 2. Add a page\n- What changed: nothing changed\n- The reply: Stopped.\n- Saved: no, it was stopped\n" in history
    assert ws.history_count(tmp_path) == 2
    assert ws.saved_line(status="applied", stop_reason=None, outcome_status=None, version=None) == "nothing to save"
    assert ws.saved_line(status="applied", stop_reason=None, outcome_status="conflicted", version=7) == (
        "no, the site changed while this request ran")
    assert ws.saved_line(status="failed", stop_reason="site_invalid", outcome_status=None, version=None) == (
        "no, the page was still invalid")


def test_seller_components_list_each_section_with_its_props(tmp_path: Path) -> None:
    ws.record_component(tmp_path, "QuoteBand", {"properties": {"attribution": {"type": "string"}}})
    ws.record_component(tmp_path, "StepsBand", {"properties": {}})
    text = (tmp_path / "catalog" / "seller-components.md").read_text()
    assert text.startswith("# The seller's components on this site")
    assert "## QuoteBand" in text and '"attribution"' in text and "## StepsBand" in text


def test_the_selection_block_names_each_part_in_order_with_its_note() -> None:
    block = targets_block([
        {"object_id": "site:/analysis#analysis-hero.title", "note": "1. Make it warmer."},
        {"object_id": "site:shell#header", "note": None},
        {"object_id": "site:shell#footer.ctaLabel", "note": "2. Say book a call"},
        {"object_id": "site:/#proof", "note": ""},
    ])
    assert block == (
        "The person also pointed at parts of the site:\n"
        '- Page /analysis, the section with id "analysis-hero", its "title" field. Their note: "1. Make it warmer."\n'
        "- The header. (No note.)\n"
        '- The footer, its "ctaLabel" field. Their note: "2. Say book a call"\n'
        '- Page /, the section with id "proof". (No note.)\n'
        "Work through these in the order listed. Change only these parts, unless their message asks "
        "for more. If a part is no longer on the site, say so in your report and use your judgement. "
        "In your report, say what you did for each part, or why you did not."
    )


def test_no_selection_means_no_block_and_an_odd_id_is_named_as_written() -> None:
    assert targets_block([]) == ""
    assert '- The part "site:nowhere" of the site. (No note.)' in targets_block([{"object_id": "site:nowhere", "note": None}])


def test_a_dotted_section_id_on_the_site_is_one_id_and_its_field_splits_at_the_last_dot() -> None:
    site = {"pages": {"/": {"content": [{"type": "Hero", "props": {"id": "hero.v2", "title": "Hi"}}]}},
            "shell": {"header": {"id": "header"}, "footer": {"id": "footer"}}}
    block = targets_block([{"object_id": "site:/#hero.v2", "note": None},
                           {"object_id": "site:/#hero.v2.title", "note": "Shorter"}], site=site)
    assert '- Page /, the section with id "hero.v2". (No note.)' in block
    assert '- Page /, the section with id "hero.v2", its "title" field. Their note: "Shorter"' in block


def test_the_site_summary_says_what_was_styled_by_hand(tmp_path: Path) -> None:
    """Site element inspector (plan 1): the agent sees a section's and the header's `_edits` in plain
    words, so it can keep, change or drop them when it rewrites the page."""
    site = garner_site()
    site["pages"]["/"]["content"].append({"type": "CtaBand", "props": {
        "id": "styled", "surface": "brand", "heading": "H", "buttonLabel": "Go", "buttonHref": "/",
        "_edits": {
            "heading": {"color": {"token": "text.heading"}, "fontFamily": "Garner Serif", "fontSize": 48,
                        "fontWeight": 600, "italic": True, "textAlign": "center"},
            "body": {"color": {"hex": "#0F59B0", "opacity": 80}, "underline": False},
        }}})
    site["shell"]["header"]["_edits"] = {"preparedFor": {"fontWeight": 700}}
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ws.write_site_files(workspace, site)
    text = ws.site_summary(workspace, garner_brand())
    assert ("   - styled by hand: heading — colour text.heading, Garner Serif, 48 px, Semi Bold, italic, "
            "centred") in text
    assert "   - styled by hand: body — colour #0F59B0 80%, not underlined" in text
    assert "- Header styled by hand: preparedFor — Bold" in text


def test_the_site_summary_reads_rich_text_and_links_in_plain_words(tmp_path: Path) -> None:
    """Site element inspector (plan 2): rich text shows its words with its bold, links and styled
    words named, and links that open in a new tab say so."""
    site = garner_site()
    site["pages"]["/"]["content"].append({"type": "ProofCard", "props": {
        "id": "rich", "surface": "card", "kicker": "K", "metric": "13%", "metricLabel": "less",
        "heading": 'Top <strong>results</strong> <span data-s="heading~1">here</span>',
        "body": 'See <a href="/analysis" data-new-tab="">the analysis</a> &amp; more',
        "linkLabel": "Read", "linkHref": "/analysis", "linkNewTab": True,
        "_edits": {"heading~1": {"fontWeight": 700}}}})
    site["shell"]["header"]["nav"] = [{"label": "Analysis", "href": "/analysis", "newTab": True}]
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ws.write_site_files(workspace, site)
    text = ws.site_summary(workspace, garner_brand())
    assert '   - heading: "Top results here" (bold "results"; "here" styled by hand as heading~1)' in text
    assert '   - body: "See the analysis & more" (link "the analysis" → /analysis, new tab)' in text
    assert '   - link "Read" → /analysis, new tab' in text
    assert "   - styled by hand: heading~1 — Bold" in text
    assert "- Nav links: Analysis → /analysis (new tab)" in text


def test_the_site_summary_reads_a_buttons_hand_set_look(tmp_path: Path) -> None:
    """Site element inspector (plan 3): fill, stroke, corners, padding and width in plain words."""
    site = garner_site()
    site["pages"]["/"]["content"].append({"type": "CtaBand", "props": {
        "id": "styled_cta", "surface": "brand", "heading": "H", "buttonLabel": "Go", "buttonHref": "/",
        "_edits": {
            "button": {"fill": {"token": "text.inverse"}, "borderColor": {"hex": "#0F59B0", "opacity": 100},
                       "borderWidth": 2, "radius": "pill", "padding": {"y": 12, "x": 22}, "width": "fill"},
            "button.label": {"radius": [0, 4, 8, 16], "padding": 10, "width": 240},
        }}})
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ws.write_site_files(workspace, site)
    text = ws.site_summary(workspace, garner_brand())
    assert ("   - styled by hand: button — fill text.inverse, stroke colour #0F59B0 100%, stroke 2 px, "
            "corners pill, padding 12 × 22 px, full width") in text
    assert "   - styled by hand: button.label — corners 0 / 4 / 8 / 16 px, padding 10 px, 240 px wide" in text


def test_the_site_summary_reads_box_edits(tmp_path: Path) -> None:
    """Site element inspector (plan 4): gap, content alignment, the order of a box's children and a
    hidden header part in plain words."""
    site = garner_site()
    site["pages"]["/"]["content"].append({"type": "CtaBand", "props": {
        "id": "styled_box", "surface": "brand", "heading": "H", "buttonLabel": "Go", "buttonHref": "/",
        "_edits": {
            "stats.1": {"gap": 12, "contentAlign": {"along": "row", "to": "center"}},
            "0.2": {"order": ["0.2.1", "0.2.0"]},
            "column": {"contentAlign": {"along": "stack", "to": "end"}},
        }}})
    site["shell"]["header"]["_edits"] = {"logo": {"hidden": True}}
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ws.write_site_files(workspace, site)
    text = ws.site_summary(workspace, garner_brand())
    assert "   - styled by hand: stats.1 — gap 12 px, contents centred along the row" in text
    assert "   - styled by hand: 0.2 — children in the order 0.2.1, 0.2.0" in text
    assert "   - styled by hand: column — contents to the end in the stack" in text
    assert "- Header styled by hand: logo — hidden" in text


def test_the_site_summary_reads_one_sided_padding(tmp_path: Path) -> None:
    """Live check 2026-10-18: padding may set only its top and bottom, or only its sides."""
    site = garner_site()
    site["pages"]["/"]["content"].append({"type": "CtaBand", "props": {
        "id": "padded", "surface": "brand", "heading": "H", "buttonLabel": "Go", "buttonHref": "/",
        "_edits": {"root.inner": {"padding": {"y": 120}}, "column": {"padding": {"x": 8}}}}})
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ws.write_site_files(workspace, site)
    text = ws.site_summary(workspace, garner_brand())
    assert "   - styled by hand: root.inner — padding 120 px top and bottom" in text
    assert "   - styled by hand: column — padding 8 px left and right" in text


def test_the_site_summary_reads_a_buttons_words_and_new_tab(tmp_path: Path) -> None:
    """Site element inspector (plan 3): a button's words as rich text, and whether it opens a new tab."""
    site = garner_site()
    site["pages"]["/"]["content"].append({"type": "CtaBand", "props": {
        "id": "tab_cta", "surface": "brand", "heading": "H", "buttonLabel": 'Book <strong>a demo</strong>',
        "buttonHref": "https://garnerhealth.com/demo", "buttonNewTab": True}})
    site["shell"]["header"]["ctaLabel"] = 'Request <span data-s="cta.label~1">the analysis</span>'
    site["shell"]["header"]["ctaNewTab"] = True
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ws.write_site_files(workspace, site)
    text = ws.site_summary(workspace, garner_brand())
    assert '   - button "Book a demo" (bold "a demo") → https://garnerhealth.com/demo, new tab' in text
    assert ('button "Request the analysis" ("the analysis" styled by hand as cta.label~1) → '
            'https://garnerhealth.com/provider-impact-analysis, new tab') in text
