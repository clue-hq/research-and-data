"""The wording of ``inputs/project/status.md`` and ``inputs/project/decisions.md``.

Both renderers are pure functions over facts, so what the model reads is pinned here without a
database. Two properties matter beyond the words: every section is present even when it is empty
(an absent section reads as "not asked", an empty one reads as "not done yet"), and nothing is
stamped with the compile time — every timestamp in the file is a row's own.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from clue_api.arv2.discovery_store import PENDING_DISPOSITION, SHOWN_DISPOSITIONS
from clue_api.arv2.icp_confirmation import ProjectIcpPin
from clue_api.project_status import (
    DecisionItem,
    DiscoveryFacts,
    ProjectDocumentFacts,
    ProjectStatusFacts,
    ResearchJobFacts,
    ResearchRunFacts,
    render_decisions_markdown,
    render_status_markdown,
)
from clue_spine import ProjectProductSet

_T = datetime(2026, 9, 12, 8, 30, tzinfo=UTC)


def _facts(**overrides: Any) -> ProjectStatusFacts:
    base = ProjectStatusFacts(
        project_id="prj_1",
        project_name="Insight Health outreach",
        icp=None,
        product_set=None,
        account_count=0,
        discovery=None,
        research=(),
        documents=(),
    )
    return replace(base, **overrides)


def test_an_empty_project_renders_every_section_with_its_honest_absence() -> None:
    text = render_status_markdown(_facts())
    # The title names the project: a file that opens on a bare "# Project status" leaves the
    # model guessing which project it is reading, and leaves two fresh projects in one workspace
    # compiling byte-identical files that share one content-addressed artifact.
    assert text.startswith("# Project status — Insight Health outreach (`prj_1`)\n")
    for heading in (
        "## Confirmed ICP",
        "## Products",
        "## Plan",
        "## Accounts",
        "## Discovery",
        "## Research",
        "## Project documents",
    ):
        assert heading in text
    assert "Not confirmed." in text
    assert "No discovery run yet." in text
    assert "No research run yet." in text
    assert "Not written." in text
    assert "now" not in text.lower()


def test_pinned_icp_products_discovery_and_research_render_from_the_rows() -> None:
    facts = _facts(
        icp=ProjectIcpPin(
            document_id=UUID(int=1),
            icp_key="gi-groups",
            artifact_key="ws/aa",
            artifact_sha256="a" * 64,
            product_selection_version=2,
            version=3,
            path="audience/icp-gi-groups.md",
            project_id=None,
        ),
        product_set=ProjectProductSet(
            workspace_id="ws",
            project_id="prj_1",
            brand_id="brand",
            selection_version=2,
            product_ids=("prd_a", "prd_b"),
            gate_id=UUID(int=9),
            confirmed_by_user_id="usr",
            confirmed_at=_T,
        ),
        account_count=7,
        discovery=DiscoveryFacts(
            run_id=UUID(int=2),
            status="completed",
            asked=20,
            found=18,
            verified=18,
            shown=12,
            approved=7,
            started_at=_T,
            finished_at=_T,
        ),
        research=(
            ResearchRunFacts(
                run_id=UUID(int=3),
                status="in_progress",
                effort="full",
                created_at=_T,
                finished_at=None,
                jobs=(
                    ResearchJobFacts("Goodman Campbell", "completed", "member_research", 4),
                    ResearchJobFacts("Acme Health", "in_progress", "synthesis", 0),
                ),
            ),
        ),
    )
    text = render_status_markdown(facts)
    assert (
        "- Key: `gi-groups` (version 3) — `inputs/brand/knowledge/audience/icp-gi-groups.md`"
        in text
    )
    assert "- Selection version 2: `prd_a`, `prd_b`" in text
    assert "- Accounts in this project: 7" in text
    assert "- Latest run `00000000-0000-0000-0000-000000000002`: completed" in text
    assert "asked 20, found 18, verified 18, shown 12, approved 7" in text
    assert (
        "- Run `00000000-0000-0000-0000-000000000003`: in_progress, effort full, 1/2 finished"
        in text
    )
    assert "  - Goodman Campbell: completed (member_research), 4 person jobs" in text
    assert "  - Acme Health: in_progress (synthesis), 0 person jobs" in text
    assert "2026-09-12T08:30:00+00:00" in text


def test_decisions_render_one_bullet_per_statement_oldest_first_or_an_honest_empty() -> None:
    assert render_decisions_markdown(()) == (
        "# Project decisions\n\nNothing recorded yet. Record preferences, boundaries and choices "
        "through `record_interview_answer` (route `project_state`).\n"
    )
    text = render_decisions_markdown(
        (
            DecisionItem("project.outcome", "we want new logos in mid-market GI groups"),
            DecisionItem("project.icp_boundary", "exclude academic medical centres"),
        )
    )
    assert text == (
        "# Project decisions\n\n"
        '- **project.outcome** — "we want new logos in mid-market GI groups"\n'
        '- **project.icp_boundary** — "exclude academic medical centres"\n'
    )


def test_the_plan_line_and_the_documents_line_name_one_document_at_one_path() -> None:
    """Ruling F: a project document has exactly one workspace path, wherever it is mentioned.

    The plan is looked up by its folder-qualified row path (``project/plan.md``) and rendered
    twice — once under ``## Plan`` and once under ``## Project documents``. Rendering the row path
    below the prefix verbatim would advertise ``inputs/project/project/plan.md`` in one of them, a
    path nothing seeds: the model would read a broken link and report the plan as missing.
    """

    text = render_status_markdown(
        _facts(
            documents=(
                ProjectDocumentFacts(
                    path="project/plan.md", version=2, status="ready", updated_at=_T
                ),
                ProjectDocumentFacts(
                    path="audience/icp-gi.md", version=1, status="ready", updated_at=_T
                ),
            )
        )
    )
    assert "inputs/project/project/" not in text
    assert "- Version 2, updated 2026-09-12T08:30:00+00:00 — `inputs/project/plan.md`" in text
    assert (
        "- `inputs/project/plan.md` — version 2, ready, updated 2026-09-12T08:30:00+00:00" in text
    )
    # A document in any other folder keeps that folder below the prefix.
    assert (
        "- `inputs/project/audience/icp-gi.md` — version 1, ready, "
        "updated 2026-09-12T08:30:00+00:00" in text
    )


def test_the_discovery_counters_read_the_arv2_lanes_own_disposition_vocabulary() -> None:
    """status.md's ``shown`` is the driver's ``shown``, proven rather than assumed.

    The words are the same on both surfaces, so a seventh disposition that reaches the driver and
    the store but not this file would not fail anything — status.md would simply report a smaller
    number than the screen the human is looking at. This is the assertion that makes that a build
    failure instead of a quiet disagreement.
    """

    from clue_api.arv2.discovery_driver import _SHOWN

    assert frozenset(SHOWN_DISPOSITIONS) == _SHOWN
    # "verified" is the complement of pending, not a vocabulary of its own.
    assert PENDING_DISPOSITION == "pending"
