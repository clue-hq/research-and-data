"""Which knowledge documents each synthesis turn opens with, and which it merely gets on disk.

Offline: ``_select_inputs`` is a pure function over rows, so its whole rule set is testable without
a database, a turn, or a model.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from clue_api.onboarding_synthesis_wiring import (
    RegisteredIcp,
    _document_product_ids,
    _InputSelectionError,
    _objective,
    _select_inputs,
)


def _row(
    kind: str,
    path: str,
    *,
    body: str = "",
    version: int = 1,
    document_id: UUID | None = None,
) -> dict[str, Any]:
    return {
        "document_id": document_id or uuid4(),
        "path": path,
        "kind": kind,
        "version": version,
        "artifact_key": f"art/{path}",
        "artifact_sha256": "0" * 64,
        "body": body.encode(),
    }


_OVERVIEW = _row(
    "company-overview", "company/overview.md", body="---\nkind: company-overview\n---\n\nx\n"
)
_CATALOG = _row(
    "product-catalog", "product/catalog.md", body="---\nkind: product-catalog\n---\n\nx\n"
)
_REVIEWS = _row(
    "customer-reviews", "proof/customer-reviews.md", body="---\nkind: customer-reviews\n---\n\nx\n"
)
_AURA = _row(
    "product-research",
    "product/aura.md",
    body="---\nkind: product-research\nproduct_id: prd_aura\n---\n\nx\n",
)
_OTHER = _row(
    "product-research",
    "product/other.md",
    body="---\nkind: product-research\nproduct_id: prd_other\n---\n\nx\n",
)
_UNREADABLE = _row("product-research", "product/mystery.md", body="not front matter at all\n")
_PERSONA = _row(
    "audience-persona",
    "audience/persona-gi-groups.md",
    body="---\nkind: audience-persona\nicp_key: gi-groups\n---\n\nx\n",
)
_ICP_GI = _row(
    "icp-definition",
    "audience/icp-gi-groups.md",
    body="---\nkind: icp-definition\nicp_key: gi-groups\nproduct_ids: [prd_aura]\n---\n\nx\n",
)
_ICP_HOSPITALS = _row(
    "icp-definition",
    "audience/icp-hospitals.md",
    version=3,
    body="---\nkind: icp-definition\nicp_key: hospitals\nproduct_ids: [prd_other]\n---\n\nx\n",
)

_ALL = (
    _ICP_GI,
    _ICP_HOSPITALS,
    _OVERVIEW,
    _AURA,
    _CATALOG,
    _OTHER,
    _UNREADABLE,
    _REVIEWS,
    _PERSONA,
)


def _paths(rows: tuple[dict[str, Any], ...]) -> list[str]:
    return [str(row["path"]) for row in rows]


def _icp_of(row: dict[str, Any]) -> RegisteredIcp:
    return RegisteredIcp(
        document_id=UUID(str(row["document_id"])),
        icp_key=str(row["path"]).removeprefix("audience/icp-").removesuffix(".md"),
        version=int(row["version"]),
        path=str(row["path"]),
    )


def test_the_icp_turn_opens_on_the_core_three_and_every_icp_on_file() -> None:
    selected = _select_inputs(_ALL, task="icp")

    # Core first, in the order the model should meet them, then the ICPs already on file.
    assert _paths(selected.focus) == [
        "company/overview.md",
        "product/catalog.md",
        "proof/customer-reviews.md",
        "audience/icp-gi-groups.md",
        "audience/icp-hospitals.md",
    ]


def test_the_icp_turn_gets_every_product_research_file_on_disk() -> None:
    selected = _select_inputs(_ALL, task="icp")

    assert _paths(selected.seeds)[len(selected.focus) :] == [
        "product/aura.md",
        "product/mystery.md",
        "product/other.md",
    ]
    # Seeds are always a superset of focus: a document in context is also citable by path.
    assert set(_paths(selected.focus)) <= set(_paths(selected.seeds))


def test_a_persona_document_is_never_an_input_to_either_task() -> None:
    for task, icp in (("icp", None), ("persona", _icp_of(_ICP_GI))):
        selected = _select_inputs(_ALL, task=task, icp=icp)  # type: ignore[arg-type]
        assert "audience/persona-gi-groups.md" not in _paths(selected.seeds)


def test_a_persona_turn_sees_exactly_its_own_icp() -> None:
    selected = _select_inputs(_ALL, task="persona", icp=_icp_of(_ICP_GI))

    assert _paths(selected.focus) == [
        "company/overview.md",
        "product/catalog.md",
        "proof/customer-reviews.md",
        "audience/icp-gi-groups.md",
    ]


def test_a_persona_turn_gets_only_the_product_research_its_icp_names() -> None:
    selected = _select_inputs(_ALL, task="persona", icp=_icp_of(_ICP_GI))

    seeded = _paths(selected.seeds)
    assert "product/aura.md" in seeded
    assert "product/other.md" not in seeded
    # An unreadable product id is kept: we cannot tell whether it belongs to this ICP, and hiding
    # research from the turn that writes about the buyer is the worse of the two errors.
    assert "product/mystery.md" in seeded


def test_a_persona_turn_whose_icp_document_is_gone_fails_icp_document_missing() -> None:
    stranger = RegisteredIcp(
        document_id=uuid4(),
        icp_key="vanished",
        version=1,
        path="audience/icp-vanished.md",
    )

    with pytest.raises(_InputSelectionError) as caught:
        _select_inputs(_ALL, task="persona", icp=stranger)

    assert caught.value.code == "icp_document_missing"


def test_an_icp_whose_product_ids_are_unreadable_keeps_every_product_research_file() -> None:
    blind = _row("icp-definition", "audience/icp-blind.md", body="no front matter\n")
    selected = _select_inputs((*_ALL, blind), task="persona", icp=_icp_of(blind))

    assert _paths(selected.seeds)[len(selected.focus) :] == [
        "product/aura.md",
        "product/mystery.md",
        "product/other.md",
    ]


def test_product_ids_are_read_from_either_front_matter_spelling() -> None:
    assert _document_product_ids(_AURA) == frozenset({"prd_aura"})
    assert _document_product_ids(_ICP_GI) == frozenset({"prd_aura"})
    assert _document_product_ids(_UNREADABLE) is None
    # Present but empty is the same honest "cannot tell" as unparseable.
    assert _document_product_ids(_OVERVIEW) is None


def test_the_icp_objective_names_the_profiles_already_on_file() -> None:
    selected = _select_inputs(_ALL, task="icp")

    assert _objective(task="icp", icp=None, focus=selected.focus) == (
        "Task: icp. Write the ICP documents, then finalize_turn. ICPs already on file: "
        "gi-groups (inputs/brand/knowledge/audience/icp-gi-groups.md, version 1); "
        "hospitals (inputs/brand/knowledge/audience/icp-hospitals.md, version 3)."
    )


def test_a_first_run_icp_objective_names_no_profiles() -> None:
    selected = _select_inputs((_OVERVIEW, _CATALOG), task="icp")

    assert _objective(task="icp", icp=None, focus=selected.focus) == (
        "Task: icp. Write the ICP documents, then finalize_turn."
    )


def test_the_persona_objective_names_one_icp_its_file_and_its_version() -> None:
    assert _objective(task="persona", icp=_icp_of(_ICP_HOSPITALS), focus=()) == (
        "Task: persona:hospitals. The ICP is "
        "inputs/brand/knowledge/audience/icp-hospitals.md, version 3. "
        "Write outputs/audience/persona-hospitals.md, then finalize_turn."
    )
