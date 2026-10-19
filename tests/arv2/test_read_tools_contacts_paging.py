"""``read_account_research@3`` section='contacts' pages the committee by contact-page section.

Found live 2026-10-05: a contact page is 22-46 KB against a 12 KB read page, so serving whole
people dropped every trailing section (``do-not-mention`` included) with no way to page to it.
"""

from __future__ import annotations

import pytest

from clue_api.arv2.read_tools import (
    READ_REFERENCES_BUDGET_BYTES,
    AccountContactView,
    AccountOverviewSection,
    Arv2ReadRefused,
    _contacts_page,
    receipt_bytes,
)


def _section(key: str, size: int) -> AccountOverviewSection:
    return AccountOverviewSection(
        section_key=key,
        body_text="x" * size,
        body_truncated=False,
        cited_claim_ids=(),
        generated_at="",
    )


def _person(name: str, sizes: dict[str, int]) -> AccountContactView:
    return AccountContactView(
        contact_entity_id=f"id-{name}",
        name=name,
        committee_role="champion",
        title="Director",
        page_written=bool(sizes),
        sections=tuple(_section(key, size) for key, size in sizes.items()),
    )


_PAGE = {
    "why-this-person": 3000,
    "problem-right-now": 3000,
    "openers": 3000,
    "angles": 3000,
    "do-not-mention": 2500,
    "miscellaneous": 6000,
}


def _read_all(people: list[AccountContactView]) -> list[tuple[AccountContactView, ...]]:
    pages, offset = [], 0
    while offset is not None:
        page, _, offset = _contacts_page(people, offset=offset)
        pages.append(page)
    return pages


def test_every_section_of_every_person_is_reachable_in_order_within_the_budget() -> None:
    people = [_person("Ada", _PAGE), _person("Bo", _PAGE), _person("Cy", {})]
    pages = _read_all(people)

    seen: dict[str, list[str]] = {}
    for page in pages:
        assert receipt_bytes([view.model_dump() for view in page]) <= READ_REFERENCES_BUDGET_BYTES
        for view in page:
            seen.setdefault(view.name, []).extend(s.section_key for s in view.sections)
    assert seen == {"Ada": list(_PAGE), "Bo": list(_PAGE), "Cy": []}
    assert len(pages) > 1


def test_a_person_split_across_pages_says_their_page_continues() -> None:
    people = [_person("Ada", _PAGE)]
    pages = _read_all(people)
    views = [view for page in pages for view in page]

    assert all(view.name == "Ada" for view in views)
    assert [view.sections_truncated for view in views] == [True] * (len(views) - 1) + [False]


def test_a_person_with_no_page_yet_is_still_listed() -> None:
    page, more, next_offset = _contacts_page([_person("Cy", {})], offset=0)

    assert [(view.name, view.page_written, view.sections) for view in page] == [("Cy", False, ())]
    assert (more, next_offset) == (False, None)


def test_one_section_larger_than_a_page_is_clipped_to_fit_beside_its_person() -> None:
    people = [_person("Ada", {"miscellaneous": 30_000, "angles": 100})]
    first, more, next_offset = _contacts_page(people, offset=0)

    (view,) = first
    assert [s.section_key for s in view.sections] == ["miscellaneous"]
    assert view.sections[0].body_truncated is True
    assert view.sections_truncated is True
    assert receipt_bytes([v.model_dump() for v in first]) <= READ_REFERENCES_BUDGET_BYTES
    assert (more, next_offset) == (True, 1)

    second, more, next_offset = _contacts_page(people, offset=1)
    assert [s.section_key for s in second[0].sections] == ["angles"]
    assert (more, next_offset) == (False, None)


def test_an_offset_past_the_end_is_refused() -> None:
    with pytest.raises(Arv2ReadRefused) as refused:
        _contacts_page([_person("Ada", {"why-this-person": 10})], offset=5)
    assert refused.value.code == "offset_past_end"


def test_an_empty_committee_is_one_empty_page() -> None:
    assert _contacts_page([], offset=0) == ((), False, None)
