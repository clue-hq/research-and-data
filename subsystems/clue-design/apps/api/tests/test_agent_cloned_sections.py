"""The cloned-section capability one web turn gets (clone-fidelity F2.3).

The agent runtime never opens the design database. Everything it may know about the workspace's
cloned sections therefore arrives through one injected capability, exactly as the account-local
custom-component registry arrives — and this file pins what that capability will and will not say.

Two properties matter more than the rest:

* **Approved only.** Discovery lists what a human released. A ``draft`` section (minted, waiting
  on its brand kit's approval) and a ``deprecated`` one (retired) are never offered.
* **The refusal is the GATE's.** ``resolve_insertable`` does not re-decide what "approved" means;
  it asks :meth:`HybridRepository.validate_fragment_reference_changes` — the same check the
  document write makes — so a status rule can never mean one thing to the agent and another to
  the write it is heading for.

DB-backed with the suite's per-test workspace + disposable ``FsStorage``, like its F1.2 neighbour.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from clue_storage import FsStorage

from lumen_api.agent_cloned_sections import (
    DurableAgentClonedSectionRegistry,
    resolve_fragment_lineages,
)
from lumen_api.database import FragmentReferenceError
from lumen_api.design_store import DesignBlobStore, HybridRepository
from lumen_api.fragments import (
    SlotSpec,
    create_web_fragment,
    fragment_wrapper_class,
    set_web_fragment_status,
)

HERO_HTML = (
    '<section class="hero"><h1 class="head">Care, on your terms</h1>'
    '<a class="cta" href="https://insight.example/demo">Book a demo</a></section>'
)
HERO_CSS = ".hero { padding: 64px } .head { color: #123456 }"
NAV_HTML = '<nav class="nav"><a class="brand" href="/">Insight</a></nav>'
NAV_CSS = ".nav { display: flex }"
PNG = b"\x89PNG\r\n\x1a\nfake-preview-bytes"
SOURCE_URL = "https://insight.example/"

HERO_SLOTS = (
    SlotSpec(selector=".head", key="headline", kind="text"),
    SlotSpec(selector=".cta", key="cta_href", kind="href"),
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mint(
    workspace_id: str,
    storage: FsStorage,
    *,
    html: str = HERO_HTML,
    css: str = HERO_CSS,
    section_role: str = "hero",
    label: str | None = "Hero — Care, on your terms",
    slots: Any = HERO_SLOTS,
    preview: bytes | None = PNG,
    approved: bool = True,
    provenance: dict | None = None,
    **kwargs: Any,
) -> dict:
    row, _artifact = create_web_fragment(
        storage,
        workspace_id=workspace_id,
        html=html,
        css=css,
        rehosted={},
        source_url=SOURCE_URL,
        section_role=section_role,
        label=label,
        slots=slots,
        preview=preview,
        provenance=provenance
        or {"page_url": SOURCE_URL, "slots": [spec.key for spec in slots]},
        **kwargs,
    )
    if approved:
        row = set_web_fragment_status(
            workspace_id=workspace_id, fragment_id=row["fragment_id"], status="approved"
        )
    return row


def _seed_kit(workspace_id: str, kit_id: str = "brand_kit_clone_1") -> dict:
    """A real kit row — the fragment table's kit binding is a foreign key, not a label."""
    return HybridRepository(workspace_id=workspace_id).create_brand_kit(
        {"id": kit_id, "version": 3, "name": "Insight", "approval_status": "approved"},
        {},
        [],
        "website",
    )


def _registry(
    workspace_id: str, storage: FsStorage, cache_dir
) -> DurableAgentClonedSectionRegistry:
    return DurableAgentClonedSectionRegistry(
        blobs=DesignBlobStore(storage, workspace_id), cache_dir=cache_dir
    )


# --------------------------------------------------------------------------- #
# The lineage resolution matrix (ruling R-X1) — pure, table-driven, no database
# --------------------------------------------------------------------------- #
#
# The resolution rule moved three times in three review rounds, and each move was argued from a
# handful of shapes held in somebody's head. The record of what "settled" means was a table in a
# task report and a scratch probe; this is that table, executable.
#
# Ruling R-X1, stated once: a member is HEALTHY when it is approved and un-degraded. A healthy
# member is SUPERSEDED iff any descendant of it is healthy — at any depth, through links of any
# status. The REPRESENTATIVE SET is the healthy members with no healthy descendant, and it is
# necessarily an antichain. Exactly one → pin it. Two or more → ambiguous, nothing pinned. None →
# fall back to exactly ONE approved member, naming what it passed over.
#
# FOUNDER RULING R-X4 (2026-08-29) AMENDS THE LAST SENTENCE, AND ONLY THE LAST SENTENCE. Which
# approved member the fallback picks is now a deployment choice with two values:
#
#   keep_flagged (DEFAULT) — the NEWEST approved member. "Never silently return to a
#                            known-broken original": the newest repair stays selected and is
#                            reported degraded and requiring review.
#   fallback_original      — the OLDEST approved member (the pre-ruling behaviour), i.e. the
#                            harvested original where the family still has one.
#
# Every other arm is identical in both modes, which is why the matrix carries ONE expectation per
# case and an override only where the ruling actually moved the answer.
#
# Every expectation below is read off those paragraphs, not off the implementation.


def _lineage_row(
    fragment_id: str,
    *,
    status: str = "approved",
    degraded: bool = False,
    derived_from: str | None = None,
    created_at: str | None = None,
) -> dict:
    """One listing row, reduced to the four columns the resolver actually reads.

    ``created_at`` defaults to the id, which makes the ids themselves the age ordering: ``a`` is
    older than ``r1`` is older than ``r2``. The fallback branch ("oldest approved") is the only
    place ordering is load-bearing, and a case that cares states its own timestamps.
    """
    return {
        "fragment_id": fragment_id,
        "status": status,
        "degraded": degraded,
        "derived_from": derived_from,
        "created_at": created_at or fragment_id,
    }


#: ``(name, rows, {root: (representative, ambiguous, ranked_over)})`` under the DEFAULT
#: ``keep_flagged`` selection.
#:
#: The expectation is keyed by FAMILY ROOT and the test asserts three things from it: that the
#: families are exactly these, that every member of a family resolves to the same verdict, and
#: that the verdict is this one. A shape that splits into two families therefore cannot pass by
#: accident — it has to name both.
#:
#: :data:`FALLBACK_ORIGINAL_OVERRIDES` names the handful of cases where the OTHER selection
#: answers differently; every case not listed there must answer identically in both modes, and
#: the test asserts that too rather than assuming it.
LINEAGE_MATRIX: tuple[tuple[str, list[dict], dict[str, tuple]], ...] = (
    # --- the fifteen shapes ruling R-X1 was settled against ------------------------------------
    (
        "healthy unrepaired — a lone clone is its own representative",
        [_lineage_row("a")],
        {"a": ("a", (), ())},
    ),
    (
        "healthy + healthy repair — the repair supersedes the original",
        [_lineage_row("a"), _lineage_row("r1", derived_from="a")],
        {"a": ("r1", (), ())},
    ),
    (
        "X1 — a degraded middle never hides the healthy leaf below it",
        [
            _lineage_row("a"),
            _lineage_row("r1", derived_from="a", degraded=True),
            _lineage_row("r2", derived_from="r1"),
        ],
        {"a": ("r2", (), ())},
    ),
    (
        "X1 deep — two degraded middles are stepped over just the same",
        [
            _lineage_row("a"),
            _lineage_row("r1", derived_from="a", degraded=True),
            _lineage_row("r2", derived_from="r1", degraded=True),
            _lineage_row("r3", derived_from="r2"),
        ],
        {"a": ("r3", (), ())},
    ),
    (
        "X1 deprecated middle — the descendant walk crosses links of ANY status",
        [
            _lineage_row("a"),
            _lineage_row("r1", derived_from="a", status="deprecated"),
            _lineage_row("r2", derived_from="r1"),
        ],
        {"a": ("r2", (), ())},
    ),
    (
        "N1 — a degraded NEWEST repair never evicts its own healthy parent",
        [
            _lineage_row("a"),
            _lineage_row("r1", derived_from="a"),
            _lineage_row("r2", derived_from="r1", degraded=True),
        ],
        {"a": ("r1", (), ())},
    ),
    (
        "Repro A — two healthy sibling repairs are ambiguous, never a double pin",
        [
            _lineage_row("a"),
            _lineage_row("r1", derived_from="a"),
            _lineage_row("r2", derived_from="a"),
        ],
        {"a": (None, ("r1", "r2"), ())},
    ),
    (
        "Repro B — a broken root and a broken middle still resolve to the healthy leaf",
        [
            _lineage_row("a", degraded=True),
            _lineage_row("r1", derived_from="a", degraded=True),
            _lineage_row("r2", derived_from="r1"),
        ],
        {"a": ("r2", (), ())},
    ),
    (
        "R-X4 — nothing healthy anywhere keeps the NEWEST repair, flagged, never the original",
        [
            _lineage_row("a", degraded=True),
            _lineage_row("r1", derived_from="a", degraded=True),
        ],
        {"a": ("r1", (), ("a",))},
    ),
    (
        "a degraded child is the only APPROVED member — it is the fallback, and ranks over nothing",
        [
            _lineage_row("a", status="draft"),
            _lineage_row("r1", derived_from="a", degraded=True),
        ],
        {"a": ("r1", (), ())},
    ),
    (
        "the whole family degraded — the fallback names both members it passed over",
        [
            _lineage_row("a", degraded=True),
            _lineage_row("r1", derived_from="a", degraded=True),
            _lineage_row("r2", derived_from="r1", degraded=True),
        ],
        {"a": ("r2", (), ("a", "r1"))},
    ),
    (
        "a draft repair is not released, so it supersedes nothing",
        [_lineage_row("a"), _lineage_row("r1", derived_from="a", status="draft")],
        {"a": ("a", (), ())},
    ),
    (
        "a dormant leaf is not released either — D-F8 status, same answer",
        [_lineage_row("a"), _lineage_row("r1", derived_from="a", status="dormant")],
        {"a": ("a", (), ())},
    ),
    (
        "an orphan — derived_from naming a row this workspace does not hold is its own root",
        [_lineage_row("r1", derived_from="gone")],
        {"r1": ("r1", (), ())},
    ),
    (
        "a cycle terminates and every member still gets a verdict",
        [
            _lineage_row("a", derived_from="b"),
            _lineage_row("b", derived_from="a"),
        ],
        {"a": ("a", (), ()), "b": ("b", (), ())},
    ),
    # --- the edges the three review rounds asked about afterwards ------------------------------
    (
        "no rows at all",
        [],
        {},
    ),
    (
        "two unrelated clones are two families, resolved independently",
        [
            _lineage_row("a"),
            _lineage_row("b", degraded=True),
        ],
        {"a": ("a", (), ()), "b": ("b", (), ())},
    ),
    (
        "three healthy leaves are all named, sorted, and none of them is pinned",
        [
            _lineage_row("a"),
            _lineage_row("r1", derived_from="a"),
            _lineage_row("r2", derived_from="a"),
            _lineage_row("r3", derived_from="a"),
        ],
        {"a": (None, ("r1", "r2", "r3"), ())},
    ),
    (
        "an ambiguous pair on DIFFERENT branches of the same tree is still ambiguous",
        [
            _lineage_row("a"),
            _lineage_row("r1", derived_from="a", degraded=True),
            _lineage_row("r2", derived_from="r1"),
            _lineage_row("r3", derived_from="a"),
        ],
        {"a": (None, ("r2", "r3"), ())},
    ),
    (
        "one healthy branch and one wholly broken branch — the healthy branch answers alone",
        [
            _lineage_row("a"),
            _lineage_row("r1", derived_from="a"),
            _lineage_row("r2", derived_from="a", degraded=True),
        ],
        {"a": ("r1", (), ())},
    ),
    (
        "the fallback reads its age off created_at, not off the id",
        [
            _lineage_row("a", degraded=True, created_at="2026-08-02"),
            _lineage_row("r1", derived_from="a", degraded=True, created_at="2026-08-01"),
        ],
        {"a": ("a", (), ("r1",))},
    ),
    (
        "a family with no approved member at all pins nothing and blames nobody",
        [
            _lineage_row("a", status="draft"),
            _lineage_row("r1", derived_from="a", status="draft"),
        ],
        {"a": (None, (), ())},
    ),
    (
        "a deep healthy chain resolves to its tip, not to the middle",
        [
            _lineage_row("a"),
            _lineage_row("r1", derived_from="a"),
            _lineage_row("r2", derived_from="r1"),
            _lineage_row("r3", derived_from="r2"),
        ],
        {"a": ("r3", (), ())},
    ),
)


#: ``{case name: {root: (representative, ambiguous, ranked_over)}}`` under
#: ``fallback_original``, for the cases where R-X4's toggle actually changes the answer.
#:
#: There are exactly three, and all three are entirely-unhealthy families with MORE THAN ONE
#: approved member — which is the whole reach of the ruling. A family whose only approved member
#: is a broken repair has nothing to fall back TO, so it answers the same either way, and every
#: family with a healthy member never enters this arm at all.
FALLBACK_ORIGINAL_OVERRIDES: dict[str, dict[str, tuple]] = {
    "R-X4 — nothing healthy anywhere keeps the NEWEST repair, flagged, never the original": {
        "a": ("a", (), ("r1",))
    },
    "the whole family degraded — the fallback names both members it passed over": {
        "a": ("a", (), ("r1", "r2"))
    },
    "the fallback reads its age off created_at, not off the id": {"a": ("r1", (), ("a",))},
}


def _expected_degraded_fallback(rows: list[dict], root: str, parents: dict) -> bool:
    """Ruling R-X4's flag, restated from the ROWS rather than read off the implementation.

    A family is a degraded fallback when it has at least one approved member and NO healthy one
    (approved and un-degraded). That is precisely the arm the toggle governs, and it is the arm
    whose answer must reach every surface that reports degraded.
    """
    members = [row for row in rows if _root_of(row["fragment_id"], parents) == root]
    approved = [row for row in members if row["status"] == "approved"]
    healthy = [row for row in approved if not row["degraded"]]
    return bool(approved) and not healthy


def _root_of(fragment_id: str, parents: dict) -> str:
    seen: set = set()
    current = fragment_id
    while current not in seen:
        seen.add(current)
        parent = parents.get(current)
        if not isinstance(parent, str) or parent not in parents:
            return current
        current = parent
    return current


@pytest.mark.parametrize("selection", ["keep_flagged", "fallback_original"])
@pytest.mark.parametrize(
    "name, rows, expected",
    [pytest.param(name, rows, expected, id=name) for name, rows, expected in LINEAGE_MATRIX],
)
def test_the_lineage_resolution_matrix(
    name: str, rows: list[dict], expected: dict[str, tuple], selection: str
) -> None:
    """Every shape rulings R-X1 and R-X4 were settled against, under BOTH selections.

    The selection is INJECTED, never set through the environment: this is a pure function of its
    rows plus one named argument, and a test that mutated process env would be pinning the
    deployment's plumbing instead of the law.
    """
    if selection == "fallback_original":
        expected = {**expected, **FALLBACK_ORIGINAL_OVERRIDES.get(name, {})}
    parents = {row["fragment_id"]: row.get("derived_from") for row in rows}

    verdicts = resolve_fragment_lineages(list(rows), selection=selection)

    assert set(verdicts) == {row["fragment_id"] for row in rows}
    assert {verdict.root for verdict in verdicts.values()} == set(expected)

    for row in rows:
        verdict = verdicts[row["fragment_id"]]
        representative, ambiguous, ranked_over = expected[verdict.root]
        assert verdict.representative == representative
        assert verdict.ambiguous == ambiguous
        assert verdict.ranked_over == ranked_over
        assert verdict.degraded_fallback == _expected_degraded_fallback(
            rows, verdict.root, parents
        )


def test_the_default_selection_is_keep_flagged_when_nobody_names_one() -> None:
    """R-X4's default, at the seam a production caller actually uses (no argument at all).

    The whole ruling is "never silently return to a known-broken original", so the value a
    deployment gets by doing nothing is the load-bearing half of it.
    """
    from lumen_api.agent_cloned_sections import (
        DEGRADED_REPAIR_KEEP_FLAGGED,
        degraded_repair_selection,
    )

    rows = [
        _lineage_row("a", degraded=True),
        _lineage_row("r1", derived_from="a", degraded=True),
    ]

    assert degraded_repair_selection() == DEGRADED_REPAIR_KEEP_FLAGGED
    assert resolve_fragment_lineages(rows)["a"].representative == "r1"


def test_an_unrecognized_selection_refuses_rather_than_guessing() -> None:
    """The two answers differ in exactly the way the founder ruled about, so a typo may not
    quietly resolve to either one."""
    with pytest.raises(ValueError) as excinfo:
        resolve_fragment_lineages([_lineage_row("a")], selection="newest")

    assert "keep_flagged" in str(excinfo.value)
    assert "fallback_original" in str(excinfo.value)


def test_a_lineage_deeper_than_the_interpreters_stack_still_resolves() -> None:
    """A thousand-link repair-of-repair chain answers, rather than raising ``RecursionError``.

    Unreachable in practice today, and that is not the point: the walk carried a comment saying it
    was iterative while it was not, so the depth at which it stopped working was the interpreter's
    rather than one anybody had chosen. 1200 links is comfortably past the default 1000 limit.
    """
    depth = 1200
    # A HEALTHY root, so the walk is actually entered (an unhealthy row is never asked what is
    # below it), then a chain of degraded middles, then one healthy tip. The root is superseded
    # only if the descent reaches the far end.
    rows = [_lineage_row("a")]
    parent = "a"
    for index in range(depth):
        child = f"r{index:05d}"
        rows.append(_lineage_row(child, derived_from=parent, degraded=index < depth - 1))
        parent = child

    verdicts = resolve_fragment_lineages(rows)

    assert verdicts["a"].representative == parent
    assert verdicts[parent].representative == parent


def test_the_representative_set_is_always_an_antichain() -> None:
    """The property that makes "neither replaces the other" a fact rather than an assumption.

    Two members of the ambiguous set may never stand in an ancestor/descendant relation — if one
    were an ancestor of the other it would have a healthy descendant and would not be in the set
    at all. Asserted over the matrix's own shapes rather than as prose in a docstring.
    """
    for name, rows, _expected in LINEAGE_MATRIX:
        parents = {row["fragment_id"]: row.get("derived_from") for row in rows}

        def ancestors(fragment_id: str) -> set:
            seen: set = set()
            current = parents.get(fragment_id)
            while isinstance(current, str) and current in parents and current not in seen:
                seen.add(current)
                current = parents.get(current)
            return seen

        for verdict in resolve_fragment_lineages(list(rows)).values():
            for candidate in verdict.ambiguous:
                assert not (set(verdict.ambiguous) - {candidate}) & ancestors(candidate), name


# --------------------------------------------------------------------------- #
# Discovery: approved only
# --------------------------------------------------------------------------- #


def test_list_sections_returns_the_approved_rows_with_what_a_picker_needs(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    kit = _seed_kit(workspace_id)
    row = _mint(
        workspace_id,
        design_storage,
        source_kit_id=kit["brand_kit_id"],
        source_kit_version=int(kit["version"]),
    )

    listed = _registry(workspace_id, design_storage, tmp_path / "cache").list_sections()

    assert listed["schema_version"] == 1
    assert [section["fragment_id"] for section in listed["sections"]] == [
        row["fragment_id"]
    ]
    section = listed["sections"][0]
    assert section["section_role"] == "hero"
    assert section["label"] == "Hero — Care, on your terms"
    assert section["source_url"] == SOURCE_URL
    assert section["source_kit_id"] == kit["brand_kit_id"]
    assert section["source_kit_version"] == int(kit["version"])
    assert section["preview_digest"] == _sha(PNG)
    # The row's own record of what can be re-filled — no payload blob is read to list.
    assert section["slot_keys"] == ["headline", "cta_href"]


def test_a_draft_section_is_never_listed(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    _mint(workspace_id, design_storage, approved=False)

    listed = _registry(workspace_id, design_storage, tmp_path / "cache").list_sections()

    assert listed["sections"] == []


def test_a_deprecated_section_is_never_listed(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    row = _mint(workspace_id, design_storage)
    set_web_fragment_status(
        workspace_id=workspace_id,
        fragment_id=row["fragment_id"],
        status="deprecated",
    )

    listed = _registry(workspace_id, design_storage, tmp_path / "cache").list_sections()

    assert listed["sections"] == []


def test_listing_is_bounded(
    workspace_id: str, design_storage: FsStorage, tmp_path, monkeypatch
) -> None:
    for index in range(4):
        _mint(
            workspace_id,
            design_storage,
            html=f'<section class="hero"><h1 class="head">Headline {index}</h1></section>',
            slots=(SlotSpec(selector=".head", key="headline", kind="text"),),
        )
    monkeypatch.setattr(
        "lumen_api.agent_cloned_sections.CLONED_SECTION_LIST_MAX", 2, raising=True
    )

    listed = _registry(workspace_id, design_storage, tmp_path / "cache").list_sections()

    assert len(listed["sections"]) == 2


# --------------------------------------------------------------------------- #
# Describe: the slot kinds and the pixels
# --------------------------------------------------------------------------- #


def test_describe_reads_the_slot_kinds_and_materializes_the_preview(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    cache = tmp_path / "cache"
    row = _mint(workspace_id, design_storage)

    described = _registry(workspace_id, design_storage, cache).describe(
        [row["fragment_id"]]
    )

    entry = described[row["fragment_id"]]
    assert entry["slots"] == [
        {"key": "cta_href", "kind": "href"},
        {"key": "headline", "kind": "text"},
    ]
    preview_path = entry["preview_path"]
    assert preview_path is not None
    with open(preview_path, "rb") as handle:
        assert handle.read() == PNG


def test_describe_says_so_when_a_section_has_no_preview(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    row = _mint(workspace_id, design_storage, preview=None)

    described = _registry(workspace_id, design_storage, tmp_path / "cache").describe(
        [row["fragment_id"]]
    )

    assert described[row["fragment_id"]]["preview_path"] is None


def test_describe_skips_an_id_it_cannot_resolve(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    described = _registry(workspace_id, design_storage, tmp_path / "cache").describe(
        ["frag_deadbeefdeadbeef"]
    )

    assert described == {}


# --------------------------------------------------------------------------- #
# The insert gate: the refusal is the document write's own
# --------------------------------------------------------------------------- #


def test_resolve_insertable_hands_back_the_render_entry_for_an_approved_section(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    row = _mint(workspace_id, design_storage)

    resolved = _registry(workspace_id, design_storage, tmp_path / "cache").resolve_insertable(
        row["fragment_id"]
    )

    assert resolved["fragment_id"] == row["fragment_id"]
    assert resolved["section_role"] == "hero"
    assert "Care, on your terms" in resolved["render"]["html"]
    assert resolved["render"]["css"]
    assert resolved["render"]["slot_kinds"] == {"headline": "text", "cta_href": "href"}
    assert resolved["render"]["asset_digests"] == []
    assert resolved["slots"] == [
        {"key": "cta_href", "kind": "href"},
        {"key": "headline", "kind": "text"},
    ]


def test_resolve_insertable_refuses_a_draft_with_the_gates_own_code(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    row = _mint(workspace_id, design_storage, approved=False)

    with pytest.raises(FragmentReferenceError) as caught:
        _registry(workspace_id, design_storage, tmp_path / "cache").resolve_insertable(
            row["fragment_id"]
        )

    assert caught.value.code == "fragment.not_approved"
    assert caught.value.fragment_id == row["fragment_id"]
    assert "approve the brand kit" in caught.value.message


def test_resolve_insertable_refuses_a_deprecated_section(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    row = _mint(workspace_id, design_storage)
    set_web_fragment_status(
        workspace_id=workspace_id,
        fragment_id=row["fragment_id"],
        status="deprecated",
    )

    with pytest.raises(FragmentReferenceError) as caught:
        _registry(workspace_id, design_storage, tmp_path / "cache").resolve_insertable(
            row["fragment_id"]
        )

    assert caught.value.code == "fragment.not_approved"


def test_resolve_insertable_refuses_an_id_this_workspace_does_not_hold(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    with pytest.raises(FragmentReferenceError) as caught:
        _registry(workspace_id, design_storage, tmp_path / "cache").resolve_insertable(
            "frag_deadbeefdeadbeef"
        )

    assert caught.value.code == "fragment.unresolved"


def test_another_tenants_approved_section_is_neither_listed_nor_insertable(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    other = f"{workspace_id}_neighbour"
    row = _mint(other, design_storage)

    registry = _registry(workspace_id, design_storage, tmp_path / "cache")

    assert registry.list_sections()["sections"] == []
    with pytest.raises(FragmentReferenceError) as caught:
        registry.resolve_insertable(row["fragment_id"])
    assert caught.value.code == "fragment.unresolved"


# --------------------------------------------------------------------------- #
# End to end: the REAL registry driving the REAL tool
# --------------------------------------------------------------------------- #


def _web_tools(workspace_id: str, storage: FsStorage, cache_dir, tmp_path):
    """One website turn's substrate, wired to the real capability. No LLM, no browser."""
    from dataclasses import replace as dataclass_replace

    from lumen_agent.config import AgentRuntimeConfig
    from lumen_agent.tools.web_substrate import LumenWebTools

    repo_root = Path(__file__).resolve().parents[3]
    config = dataclass_replace(
        AgentRuntimeConfig.from_env(repo_root),
        trace_dir=tmp_path / "workspace_root",
        cloned_section_registry=_registry(workspace_id, storage, cache_dir),
    )
    return LumenWebTools(
        config,
        "Build a page",
        initial_web_doc={
            "schema_version": 1,
            "id": "doc_cloned_e2e",
            "title": "Test site",
            "theme": {},
            "custom_css": "",
            "pages": [
                {
                    "id": "home",
                    "name": "Home",
                    "route": "/",
                    "root": "root",
                    "nodes": {
                        "root": {
                            "id": "root",
                            "kind": "container",
                            "classes": "",
                            "new_tab": False,
                            "children": [],
                        }
                    },
                }
            ],
            "assets": {},
        },
    )


def test_the_agents_discovery_shows_the_approved_section_and_hides_the_draft(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    approved = _mint(workspace_id, design_storage)
    draft = _mint(
        workspace_id,
        design_storage,
        html=NAV_HTML,
        css=NAV_CSS,
        section_role="nav",
        label="Nav",
        slots=(),
        approved=False,
    )
    tools = _web_tools(workspace_id, design_storage, tmp_path / "cache", tmp_path)

    result = json.loads(tools.search_cloned_sections())

    ids = [row["fragment_id"] for row in result["results"]]
    assert ids == [approved["fragment_id"]]
    assert draft["fragment_id"] not in ids
    # The kinds are the artifact's own, read out of its payload — not guessed from the row.
    assert result["results"][0]["slots"] == [
        {"key": "cta_href", "kind": "href"},
        {"key": "headline", "kind": "text"},
    ]


def test_the_agent_can_pin_an_approved_section_and_it_renders(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    row = _mint(workspace_id, design_storage)
    tools = _web_tools(workspace_id, design_storage, tmp_path / "cache", tmp_path)

    result = json.loads(
        tools.insert_cloned_section(
            row["fragment_id"],
            slot_values_json=json.dumps({"headline": "Care, on Privia's terms"}),
        )
    )

    assert result["status"] == "ok"
    page = tools.web_doc["pages"][0]
    assert page["nodes"][result["section_node_id"]]["kind"] == "section"
    assert page["nodes"][result["node_id"]]["fragment_id"] == row["fragment_id"]
    rendered = tools.core.web_render(
        tools.web_doc,
        "home",
        fragments=tools._fragment_render_map(),
        fragment_css=tools._fragment_css(),
    )
    # The SLOT value won, and the section's own scoped CSS travelled with it.
    assert "Care, on Privia's terms" in (rendered.get("html") or "")
    assert fragment_wrapper_class(row["fragment_id"]) in (rendered.get("html") or "")


def test_the_agent_reading_a_draft_section_gets_the_gates_words_not_a_traceback(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    row = _mint(workspace_id, design_storage, approved=False)
    tools = _web_tools(workspace_id, design_storage, tmp_path / "cache", tmp_path)

    result = json.loads(tools.insert_cloned_section(row["fragment_id"]))

    assert result["status"] == "error"
    assert result["error_code"] == "fragment.not_approved"
    assert "approve the brand kit" in result["message"]
    assert tools.web_doc["pages"][0]["nodes"]["root"]["children"] == []


def test_approving_the_kit_turns_the_same_refusal_into_a_pin(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """The whole human gate, from the agent's side: refused, released, accepted."""
    kit = _seed_kit(workspace_id)
    row = _mint(
        workspace_id,
        design_storage,
        approved=False,
        source_kit_id=kit["brand_kit_id"],
        source_kit_version=int(kit["version"]),
    )
    tools = _web_tools(workspace_id, design_storage, tmp_path / "cache", tmp_path)
    assert (
        json.loads(tools.insert_cloned_section(row["fragment_id"]))["error_code"]
        == "fragment.not_approved"
    )

    # The real human gate: approving the KIT releases the sections cloned into that version.
    HybridRepository(workspace_id=workspace_id).update_brand_kit_approval(
        kit["brand_kit_id"], "approved"
    )

    assert json.loads(tools.insert_cloned_section(row["fragment_id"]))["status"] == "ok"


# --------------------------------------------------------------------------- #
# Composition: the turn is actually handed the capability
# --------------------------------------------------------------------------- #


class _StubBlobs:
    """The tenant byte store, stubbed. Brand-kit resolution degrades to the default kit on a
    failure, so a workspace id is all this composition path needs (the pattern
    ``test_web_turn_asset_base_url`` established)."""

    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id
        self.storage = None


def test_a_web_turn_is_handed_the_workspaces_cloned_section_capability(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without this wiring both tools refuse for the whole run and nothing says why."""
    import lumen_agent.harness_web as harness_web
    import lumen_agent.llm as agent_llm
    from lumen_api import main as main_mod

    captured: dict = {}

    def _fake_turn(
        *,
        prompt,
        config,
        initial_web_doc,
        event_sink,
        checkpointer,
        thread_id,
        cancel_requested=None,
        callbacks=None,
    ):
        captured["config"] = config
        return {
            "status": "applied",
            "outcome": "completed",
            "summary": "stubbed",
            "web_doc": initial_web_doc,
            "operations": [],
        }

    monkeypatch.setattr(harness_web, "run_deepagent_web_turn", _fake_turn)
    monkeypatch.setattr(
        agent_llm, "assert_model_supports_image_input", lambda *a, **k: None
    )

    response = main_mod.run_web_agent_turn(
        {"scene": {"schema_version": 1, "id": "doc_x", "theme": {}, "pages": [], "assets": {}}},
        "Build a landing page",
        None,
        Path(__file__).resolve().parents[3],
        workspace_id="ws_test_cloned_sections",
        blobs=_StubBlobs("ws_test_cloned_sections"),
        engine_cache_root=tmp_path / "engine-cache",
    )

    assert response["status"] == "applied", response
    registry = captured["config"].cloned_section_registry
    assert isinstance(registry, DurableAgentClonedSectionRegistry)
    # It must name THIS turn's tenant and THIS turn's engine cache: a registry pointed at another
    # workspace would offer another client's website, and one pointed at another cache would
    # stage preview bytes where the runtime never looks.
    assert registry.workspace_id == "ws_test_cloned_sections"
    assert str(registry.cache_dir).startswith(str(tmp_path / "engine-cache"))


# --------------------------------------------------------------------------- #
# F2 fix wave — W5: discovery reads like the page it came from
# --------------------------------------------------------------------------- #


def test_discovery_lists_sections_in_document_order_not_registry_recency(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """A picker's rows are a page read top to bottom. "Newest first" scattered that into the
    order the minter happened to write rows in, which carries no meaning a human can use."""
    kit = _seed_kit(workspace_id)
    for index, (role, heading) in enumerate(
        [("footer", "Footer"), ("nav", "Nav"), ("hero", "Hero")]
    ):
        _mint(
            workspace_id,
            design_storage,
            section_role=role,
            html=f'<section class="s{index}"><h1>{heading}</h1><p>Copy {index}.</p></section>',
            slots=(),
            source_kit_id=kit["brand_kit_id"],
            source_kit_version=int(kit["version"]),
            provenance={"page_url": "https://x.example/", "section_index": 2 - index},
        )

    listed = _registry(workspace_id, design_storage, tmp_path / "cache").list_sections()
    indexes = [
        section["section_index"]
        for section in listed["sections"]
        if section["section_index"] is not None
    ]
    assert indexes == sorted(indexes)
    assert "total" in listed
    assert listed["total"] >= len(listed["sections"])


def test_a_row_with_no_recorded_page_url_reports_the_page_it_is_sorted_onto(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    """Ledger T17-M3. The ordering fell back to `source_url` when the mint recorded no
    `provenance.page_url`; the projection did not. Such a row therefore sorted under its source
    url and then reported `page_url: None` — which the recreate reads as a page named "" and
    refuses as ambiguous. One fallback, so the page a section is sorted onto is the page it
    reports."""
    _seed_kit(workspace_id)
    row = _mint(
        workspace_id,
        design_storage,
        provenance={"section_index": 2, "slots": ["headline"]},
    )

    (section,) = _registry(workspace_id, design_storage, tmp_path / "cache").list_sections()[
        "sections"
    ]

    assert section["fragment_id"] == row["fragment_id"]
    assert section["page_url"] == SOURCE_URL
    assert section["source_url"] == SOURCE_URL


def test_a_campaign_variant_never_replaces_the_original_but_a_repair_does() -> None:
    """Founder ruling 2026-09-04 (third solo Ramp run): the agent refused to derive a campaign
    variant of Stripe's canonical hero because "deriving from the homepage hero would replace
    Stripe's captured band for every future pin" — and under the old resolver it was RIGHT: a
    released healthy child made the original a non-leaf, so pins of the original resolved to
    the variant. A variant is a sibling band for one campaign; only a REPAIR supersedes."""
    original = _lineage_row("a")
    variant = _lineage_row("v", derived_from="a")
    variant["derived_reason"] = (
        "repair rung 3 (static fallback); trigger unrecorded; campaign variant: one CTA, eyebrow"
    )
    verdicts = resolve_fragment_lineages([original, variant])
    # The original keeps resolving to itself; the variant is its own root, pinnable by id.
    assert verdicts["a"].representative == "a"
    assert verdicts["v"].root == "v" and verdicts["v"].representative == "v"

    repair = _lineage_row("r1", derived_from="a")
    repair["derived_reason"] = "repair rung 3 (static fallback); trigger height; inverse ink"
    verdicts = resolve_fragment_lineages([_lineage_row("a", degraded=True), repair])
    # A genuine repair still supersedes its broken original.
    assert verdicts["a"].representative == "r1"


def test_source_inspection_retains_capture_evidence_without_arbitrary_metadata(
    workspace_id: str, design_storage: FsStorage, tmp_path
) -> None:
    kit = _seed_kit(workspace_id)
    row = _mint(workspace_id, design_storage,
        source_kit_id=kit["brand_kit_id"], source_kit_version=int(kit["version"]),
        provenance={"page_url": SOURCE_URL, "snapshot_id": "snap_source",
                    "dead_height_check": {"assessed": False, "because": "no_preview"},
                    "recovery": {"fidelity_verified": False},
                    "unrelated_provider_payload": "must not reach the model"})
    source = _registry(workspace_id, design_storage, tmp_path / "cache").read_source(
        row["fragment_id"])
    assert source["source_kit_id"] == kit["brand_kit_id"]
    assert source["source_kit_bindings"]
    assert source["payload_digest"] == row["payload_digest"]
    assert source["created_at"] == row["created_at"]
    assert source["capture_evidence"]["snapshot_id"] == "snap_source"
    assert source["capture_evidence"]["dead_height_check"]["assessed"] is False
    assert source["capture_evidence"]["recovery"]["fidelity_verified"] is False
    assert "unrelated_provider_payload" not in source["capture_evidence"]
