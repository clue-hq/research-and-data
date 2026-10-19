"""The wording of ``project/status.md`` and ``project/decisions.md``.

Both renderers are pure functions over facts, so what the model reads is pinned here without a
database. Two properties matter beyond the words: every section is present even when it is empty
(an absent section reads as "not asked", an empty one reads as "not done yet"), and nothing is
stamped with the compile time — every timestamp in the file is a row's own.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from clue_api.arv2.discovery_store import PENDING_DISPOSITION, SHOWN_DISPOSITIONS
from clue_api.arv2.icp_confirmation import ProjectIcpPin
from clue_api.project_status import (
    DecisionItem,
    DiscoveryFacts,
    PersonaRunFacts,
    ProjectDocumentFacts,
    ProjectStatusFacts,
    ResearchJobFacts,
    ResearchRunFacts,
    render_decisions_markdown,
    render_status_markdown,
)
from clue_core import OnboardingInputKind
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
        personas=(),
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
        "## Personas",
        "## Project documents",
    ):
        assert heading in text
    assert "Not confirmed." in text
    assert "No discovery run yet." in text
    assert "No research run yet." in text
    assert "No persona run yet." in text
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
            end_reason=None,
            excluded=0,
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
    assert "- Key: `gi-groups` (version 3) — `brand/knowledge/audience/icp-gi-groups.md`" in text
    assert "- Selection version 2: `prd_a`, `prd_b`" in text
    assert "- Accounts in this project: 7" in text
    assert "- Latest run `00000000-0000-0000-0000-000000000002`: completed" in text
    assert "asked 20, found 18, verified 18, shown 12, excluded 0, approved 7" in text
    # A run from before the brief carries no end reason, and none is invented for it.
    assert "ended" not in text
    assert (
        "- Run `00000000-0000-0000-0000-000000000003`: in_progress, effort full, 1/2 finished"
        in text
    )
    assert "  - Goodman Campbell: completed (member_research), 4 person jobs" in text
    assert "  - Acme Health: in_progress (synthesis), 0 person jobs" in text
    assert "2026-09-12T08:30:00+00:00" in text


def test_a_discovery_run_reports_why_it_ended_and_how_many_a_gate_excluded() -> None:
    """The run the Head of ABM launched from its brief ends for a reason, and the companies its
    gates excluded are counted apart — never among the shown ones."""

    text = render_status_markdown(
        _facts(
            discovery=DiscoveryFacts(
                run_id=UUID(int=2),
                status="completed",
                asked=40,
                found=30,
                verified=30,
                shown=8,
                approved=0,
                started_at=_T,
                finished_at=_T,
                end_reason="round_cap",
                excluded=19,
            )
        )
    )
    assert "asked 40, found 30, verified 30, shown 8, excluded 19, approved 0" in text
    assert "  - ended: round cap" in text


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
    assert text.index("we want new logos") < text.index("exclude academic")
    provenance = [
        json.loads(line.removeprefix("  - Provenance: "))
        for line in text.splitlines()
        if line.startswith("  - Provenance: ")
    ]
    assert len(provenance) == 2
    assert all(item["input_actor"] is None for item in provenance)
    assert all(item["statement_id"] is None for item in provenance)


def test_decision_render_keeps_capture_author_separate_from_recorder() -> None:
    rendered = render_decisions_markdown(
        (
            DecisionItem(
                "preference.logo",
                "Place the target logo above the hero.",
                statement_id=UUID(int=11),
                onboarding_input_id=UUID(int=12),
                input_kind=OnboardingInputKind.USER_TURN,
                input_actor="human",
                recorded_by_actor="agent",
                input_created_at=_T,
                created_at=_T,
                entity_id=UUID(int=13),
                correction_of_id=UUID(int=14),
                input_source_ref='thread:example\n"quoted reference"',
            ),
        )
    )
    provenance = json.loads(
        next(
            line.removeprefix("  - Provenance: ")
            for line in rendered.splitlines()
            if line.startswith("  - Provenance: ")
        )
    )
    scope = json.loads(
        next(
            line.removeprefix("  - Scope: ")
            for line in rendered.splitlines()
            if line.startswith("  - Scope: ")
        )
    )
    assert provenance["input_actor"] == "human"
    assert provenance["recorded_by_actor"] == "agent"
    assert provenance["input_id"] == "00000000-0000-0000-0000-00000000000c"
    assert provenance["statement_id"] == "00000000-0000-0000-0000-00000000000b"
    assert scope["entity_id"] == "00000000-0000-0000-0000-00000000000d"
    assert scope["correction_of_id"] == "00000000-0000-0000-0000-00000000000e"
    assert scope["input_source_ref"] == 'thread:example\n"quoted reference"'
    assert scope["route_ref"] is None


def test_the_plan_line_and_the_documents_line_name_one_document_at_one_path() -> None:
    """Ruling F: a project document has exactly one workspace path, wherever it is mentioned.

    The plan is looked up by its folder-qualified row path (``project/plan.md``) and rendered
    twice — once under ``## Plan`` and once under ``## Project documents``. Rendering the row path
    below the prefix verbatim would advertise ``project/project/plan.md`` in one of them, a path
    nothing serves: the model would read a broken link and report the plan as missing.
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
    assert "project/project/" not in text
    assert "- Version 2, updated 2026-09-12T08:30:00+00:00 — `project/plan.md`" in text
    assert "- `project/plan.md` — version 2, ready, updated 2026-09-12T08:30:00+00:00" in text
    # A document in any other folder keeps that folder below the prefix.
    assert (
        "- `project/audience/icp-gi.md` — version 1, ready, "
        "updated 2026-09-12T08:30:00+00:00" in text
    )


def test_the_plan_is_the_document_pinned_as_the_plan_wherever_it_lives() -> None:
    """The plan is a **role**, not a path (founder ruling 2026-09-14).

    The agent writes documents anywhere under ``project/``, and the human's one answer — "pin this
    as the plan" — is recorded as ``role: plan`` in the document's own front matter. The status file
    reads that role, so a plan the agent kept somewhere else is still the project's plan here.
    """

    text = render_status_markdown(
        _facts(
            documents=(
                ProjectDocumentFacts(
                    path="notes/the-q4-motion.md",
                    version=3,
                    status="ready",
                    updated_at=_T,
                    role="plan",
                    title="The Q4 motion",
                ),
                ProjectDocumentFacts(
                    path="audience/icp-gi.md", version=1, status="ready", updated_at=_T
                ),
            )
        )
    )
    assert (
        "- Version 3, updated 2026-09-12T08:30:00+00:00 — `project/notes/the-q4-motion.md`" in text
    )


def test_with_no_pinned_role_the_plan_falls_back_to_the_path_the_skills_suggest() -> None:
    """The old path is a default, not a rule: every plan written before roles existed is at it."""

    text = render_status_markdown(
        _facts(
            documents=(
                ProjectDocumentFacts(
                    path="project/plan.md", version=2, status="ready", updated_at=_T
                ),
            )
        )
    )
    assert "- Version 2, updated 2026-09-12T08:30:00+00:00 — `project/plan.md`" in text


def test_a_surface_that_serves_one_version_per_path_says_the_newer_one_exists_in_words() -> None:
    """W3: the project library holds one file per path, so it cannot name a ``.vN`` sibling.

    The per-turn seeds carry a superseded pin's newer version as a real, version-qualified file
    and give it its own line. The library does not — it is the project's *settled* state — so the
    line names the plain path it really serves and reports the newer version as a sentence. A file
    name is a promise the reader can open; a sentence is not.
    """

    text = render_status_markdown(
        _facts(
            documents=(
                ProjectDocumentFacts(
                    path="audience/icp-gi.md",
                    version=1,
                    status="confirmed",
                    updated_at=_T,
                    newer_version=2,
                    newer_status="proposed",
                ),
            )
        )
    )
    assert "icp-gi.v2.md" not in text
    assert (
        "- `project/audience/icp-gi.md` — version 1, confirmed, "
        "updated 2026-09-12T08:30:00+00:00 (newer version v2 proposed)" in text
    )


def test_the_confirmed_icp_line_names_the_prefix_of_the_pins_own_scope() -> None:
    """I1: a project-local pinned ICP is not in the brand's folder, and must not be named there.

    ``ProjectIcpPin`` carries the pinned document's scope. A project-scoped variant materializes
    in the project library at ``project/`` — the brand library skips it deliberately — so
    rendering it under the brand prefix advertises a path nothing serves. status.md is the first
    file the agent opens on a thread, so it would send it to read a file that does not exist, and
    the agent would then report its own confirmed ICP as missing.
    """

    def _pin(project_id: str | None) -> ProjectIcpPin:
        return ProjectIcpPin(
            document_id=UUID(int=1),
            icp_key="gi-dac",
            artifact_key="ws/aa",
            artifact_sha256="a" * 64,
            product_selection_version=1,
            version=2,
            path="audience/icp-gi-dac.md",
            project_id=project_id,
        )

    brand = render_status_markdown(_facts(icp=_pin(None)))
    assert "- Key: `gi-dac` (version 2) — `brand/knowledge/audience/icp-gi-dac.md`" in brand
    assert "project/audience/icp-gi-dac.md" not in brand

    project = render_status_markdown(_facts(icp=_pin("prj_1")))
    assert "- Key: `gi-dac` (version 2) — `project/audience/icp-gi-dac.md`" in project
    assert "brand/knowledge/" not in project


def test_the_personas_section_lists_this_projects_persona_runs_or_says_there_are_none() -> None:
    """M3: a personas run that failed or finished with gaps has to be visible somewhere.

    The agent opens one through ``request_persona_synthesis@1``, is told "it is running", and the
    run then lives entirely on the fleet: ``read_current_run`` filters ``kind = 'full'``, and the
    tool returned long before the run settled. Without this section a run that failed is visible
    to nobody — the agent keeps reporting work that will never land, and the human waits for a
    document that will never appear.
    """

    text = render_status_markdown(
        _facts(
            personas=(
                PersonaRunFacts(
                    run_id=UUID(int=11),
                    status="completed_with_gaps",
                    requested_at=_T,
                    finished_at=_T,
                ),
                PersonaRunFacts(
                    run_id=UUID(int=12), status="running", requested_at=_T, finished_at=None
                ),
            )
        )
    )
    assert "No persona run yet." not in text
    assert (
        "- Run `00000000-0000-0000-0000-00000000000b`: completed_with_gaps, requested "
        "2026-09-12T08:30:00+00:00, finished 2026-09-12T08:30:00+00:00" in text
    )
    # An open run is honestly open: an em dash, not a guessed finish time.
    assert (
        "- Run `00000000-0000-0000-0000-00000000000c`: running, requested "
        "2026-09-12T08:30:00+00:00, finished —" in text
    )
    # The section sits between Research and Project documents, so the file stays one story.
    assert (
        text.index("## Research") < text.index("## Personas") < text.index("## Project documents")
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
    # An excluded company was judged, but it is never shown.
    assert "excluded" not in SHOWN_DISPOSITIONS
    # "verified" is the complement of pending, not a vocabulary of its own.
    assert PENDING_DISPOSITION == "pending"
