"""A4 exit gate: the safety floor over a written draft, and the verbatim annotation.

Everything here is pure — a draft the runner could have produced, checked against the section
input it was written from. No provider, no database. The floor is the last mechanical guarantee
before a page is stored: an ``outreach_safe=false`` fact may appear only in the three restricted
sections, whatever the model wrote.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from clue_api.arv2.display.floor import (
    apply_floor,
    check_floor,
    forbidden_aliases_for,
    verbatim_annotations,
)
from clue_api.arv2.display.gather import SectionInput
from clue_api.arv2.display.recipes import recipes_for
from clue_api.arv2.display.render import DisplayClaim
from clue_api.arv2.display.runner import SectionDraft

SAFE = "claim-safe"
UNSAFE = "claim-unsafe"


def _claim(
    claim_id: str,
    *,
    value: str,
    quote: str | None = None,
    outreach_safe: bool = True,
    field_key: str = "contact.facet.recent_post",
) -> DisplayClaim:
    return DisplayClaim(
        claim_id=claim_id,
        field_key=field_key,
        value=value,
        quote=quote,
        observed_at="2026-06-17",
        priority=2,
        outreach_safe=outreach_safe,
        subject="Vari Kaur",
        media_timestamp=None,
        use_class=None,
        source_url=None,
        entity_id="e",
        extraction_method="llm",
        source_key="exa_search",
        collected_at=datetime(2026, 6, 18, tzinfo=UTC),
    )


SAFE_CLAIM = _claim(SAFE, value="We are hiring 77 ABM specialists", quote="hiring 77 people")
UNSAFE_CLAIM = _claim(
    UNSAFE,
    value="Cisco acquisition rumor, refuted",
    outreach_safe=False,
    field_key="account.reputation_risk",
)


def _section(
    section_key: str, claims: Sequence[DisplayClaim], *, page: str = "contact"
) -> SectionInput:
    recipe = next(item for item in recipes_for(page) if item.section_key == section_key)
    return SectionInput(recipe=recipe, claims=tuple(claims), deduped={})


def _sentence(text: str, *claim_ids: str) -> dict[str, object]:
    return {"text": text, "claimIds": list(claim_ids)}


def _item(
    item_id: str, h2: str, body: list[dict[str, object]], **rest: object
) -> dict[str, object]:
    return {
        "id": item_id,
        "h2": h2,
        "body": body,
        "sendLine": None,
        "contactRefs": [],
        "priority": 2,
        "newSinceLastVisit": False,
        **rest,
    }


def _draft(
    items: list[dict[str, object]],
    *,
    section_key: str = "openers",
    intro: list[dict[str, object]] | None = None,
    cited: list[str] | None = None,
) -> SectionDraft:
    return SectionDraft(
        section_key=section_key,
        intro=intro or [],
        items=items,
        cited_claim_ids=cited if cited is not None else [SAFE, UNSAFE],
        checks={},
        aliases={"c1": SAFE, "c2": UNSAFE},
        cost=None,
        model="x-ai/grok-4-fast",
        raw_refs=(),
    )


# -- the floor ---------------------------------------------------------------------------------


def test_an_unsafe_claim_cited_outside_a_restricted_section_is_a_violation() -> None:
    section = _section("openers", [SAFE_CLAIM, UNSAFE_CLAIM])
    draft = _draft(
        [
            _item("openers-1", "A safe opener", [_sentence("They are hiring.", SAFE)]),
            _item("openers-2", "The rumor", [_sentence("There is a rumor.", UNSAFE)]),
        ]
    )
    report = check_floor(draft, section)
    assert report.ok is False
    assert report.unsafe_outside_restricted == (UNSAFE,)
    assert report.offending_item_ids == ("openers-2",)


def test_the_same_claim_in_a_restricted_section_is_exactly_where_it_belongs() -> None:
    section = _section("do-not-mention", [UNSAFE_CLAIM])
    draft = _draft(
        [_item("do-not-mention-1", "The rumor", [_sentence("Never raise it.", UNSAFE)])],
        section_key="do-not-mention",
    )
    report = check_floor(draft, section)
    assert report.ok is True
    assert report.unsafe_outside_restricted == ()
    assert report.offending_item_ids == ()


def test_a_send_line_and_a_segment_are_checked_like_any_other_citation() -> None:
    section = _section("openers", [SAFE_CLAIM, UNSAFE_CLAIM])
    draft = _draft(
        [
            _item(
                "openers-1",
                "A safe headline",
                [
                    {
                        "text": "They are hiring fast.",
                        "claimIds": [SAFE],
                        "segments": [{"text": "They are hiring fast.", "claimIds": [UNSAFE]}],
                    }
                ],
            ),
            _item(
                "openers-2",
                "Another",
                [_sentence("Safe.", SAFE)],
                sendLine={"channel": "In your email", "text": "Paste me.", "claimIds": [UNSAFE]},
            ),
        ]
    )
    report = check_floor(draft, section)
    assert report.offending_item_ids == ("openers-1", "openers-2")


def test_apply_floor_drops_the_item_and_recomputes_what_the_page_cites() -> None:
    section = _section("openers", [SAFE_CLAIM, UNSAFE_CLAIM])
    draft = _draft(
        [
            _item("openers-1", "A safe opener", [_sentence("They are hiring.", SAFE)]),
            _item("openers-2", "The rumor", [_sentence("There is a rumor.", UNSAFE)]),
        ]
    )
    cleaned = apply_floor(draft, check_floor(draft, section))
    assert [item["id"] for item in cleaned.items] == ["openers-1"]
    assert cleaned.cited_claim_ids == [SAFE]
    assert cleaned.checks["floor_dropped_items"] == 1
    assert draft.checks == {}  # the original draft is untouched


def test_apply_floor_drops_an_offending_intro_sentence_and_keeps_the_rest() -> None:
    section = _section("why-they-fit", [SAFE_CLAIM, UNSAFE_CLAIM], page="overview")
    draft = _draft(
        [_item("why-they-fit-1", "Fit", [_sentence("They are hiring.", SAFE)])],
        section_key="why-they-fit",
        intro=[_sentence("They are hiring.", SAFE), _sentence("There is a rumor.", UNSAFE)],
    )
    cleaned = apply_floor(draft, check_floor(draft, section))
    assert cleaned.intro == [_sentence("They are hiring.", SAFE)]
    assert cleaned.items and cleaned.cited_claim_ids == [SAFE]
    assert cleaned.checks["floor_dropped_items"] == 0


def test_a_clean_draft_passes_through_apply_floor_unchanged_but_records_the_zero() -> None:
    section = _section("openers", [SAFE_CLAIM])
    draft = _draft(
        [_item("openers-1", "A safe opener", [_sentence("They are hiring.", SAFE)])],
        cited=[SAFE],
    )
    report = check_floor(draft, section)
    assert report.ok is True
    cleaned = apply_floor(draft, report)
    assert cleaned.items == draft.items
    assert cleaned.checks["floor_dropped_items"] == 0


def test_forbidden_aliases_for_names_the_aliases_the_regenerate_call_must_avoid() -> None:
    section = _section("openers", [SAFE_CLAIM, UNSAFE_CLAIM])
    draft = _draft([_item("openers-1", "The rumor", [_sentence("A rumor.", UNSAFE)])])
    report = check_floor(draft, section)
    assert forbidden_aliases_for(report, draft.aliases) == ["c2"]
    assert forbidden_aliases_for(check_floor(_draft([]), section), draft.aliases) == []


# -- the verbatim annotation -------------------------------------------------------------------


def test_a_verbatim_quote_is_exact_and_a_paraphrase_in_quotes_is_not_found() -> None:
    section = _section("openers", [SAFE_CLAIM])
    draft = _draft(
        [
            _item(
                "openers-1",
                'He wrote "hiring 77 ABM specialists" last month',
                [_sentence('He said they are "growing the team aggressively now".', SAFE)],
            )
        ],
        cited=[SAFE],
    )
    annotations = verbatim_annotations(draft, section)
    assert annotations["quotes"] == 2
    assert annotations["exact"] == 1
    assert annotations["not_found"] == 1


def test_a_number_in_the_claims_passes_and_an_invented_one_is_missing() -> None:
    section = _section("openers", [SAFE_CLAIM])
    draft = _draft(
        [
            _item(
                "openers-1",
                "Hiring 77 specialists",
                [_sentence("They plan 999 more hires and 7 offices.", SAFE)],
            )
        ],
        cited=[SAFE],
    )
    annotations = verbatim_annotations(draft, section)
    assert annotations["numbers"] == 2  # 77 and 999; 7 is below the threshold
    assert annotations["numbers_missing"] == 1


def test_a_short_quoted_span_is_not_counted_and_curly_quotes_are() -> None:
    section = _section("openers", [SAFE_CLAIM])
    draft = _draft(
        [
            _item(
                "openers-1",
                'They said "no" today',
                [_sentence("He wrote “are hiring 77 ABM specialists” now.", SAFE)],
            )
        ],
        cited=[SAFE],
    )
    annotations = verbatim_annotations(draft, section)
    assert annotations["quotes"] == 1
    assert annotations["exact"] == 1
