"""The coded compliance pass (substance §5, prompt rules 4–6): the floor the code decides.

Every test here is pure — hand-built drafts in, kept drafts and a log out — because the pass is the
one place a person claim can be dropped or rewritten and the founder must be able to read exactly
what it does to a sentence without a database in the way.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from clue_api.arv2.claim_writer import ClaimDraft
from clue_api.arv2.person_compliance import (
    KEYWORDS,
    SENSITIVITY_CATEGORIES,
    apply_person_floor,
)
from clue_core import EntityId, EntityType, ExtractionMethod, ResearchMode, RunId

CONTACT_ID = EntityId(uuid4())
RUN_ID = RunId(uuid4())


def _draft(
    field_key: str = "contact.facet.hobby",
    value: Any = "He runs ultramarathons at the weekend.",
    **overrides: Any,
) -> ClaimDraft:
    base: dict[str, Any] = {
        "entity_id": CONTACT_ID,
        "entity_type": EntityType.CONTACT,
        "field_key": field_key,
        "value_json": value,
        "extraction_method": ExtractionMethod.LLM_SYNTHESIS,
        "run_id": RUN_ID,
        "research_mode": ResearchMode.CONTACT_PROFILING,
        "workspace_id": "ws-1",
        "source_url": "https://nickfisher.dev/about",
        "evidence_span": "I run ultramarathons at the weekend",
    }
    base.update(overrides)
    return ClaimDraft(**base)


def _rules(log: list[dict[str, str]]) -> list[tuple[str, str]]:
    return [(row["action"], row["rule"]) for row in log]


# -- the shape of the log -------------------------------------------------------------------------


def test_a_clean_draft_passes_through_untouched_and_logs_nothing() -> None:
    draft = _draft()

    kept, log = apply_person_floor([draft], purge_unevidenced=False)

    assert kept == [draft] and log == []


def test_every_log_row_is_four_strings() -> None:
    kept, log = apply_person_floor(
        [
            _draft(value="Call me on +1 (415) 555-0132."),
            _draft(value="He runs ultras. He was diagnosed with cancer in 2019."),
            _draft(value="I grew up in Lagos and moved here at nineteen."),
        ],
        purge_unevidenced=False,
    )

    assert log, "three offending drafts produce at least three rows"
    for row in log:
        assert set(row) == {"action", "field_key", "rule", "detail"}
        assert all(isinstance(part, str) and part for part in row.values())
    assert len(kept) == 2, "only the phone draft is dropped"


# -- rule 1: personal contact details --------------------------------------------------------------


def test_a_phone_number_in_a_value_drops_the_draft() -> None:
    kept, log = apply_person_floor(
        [_draft(field_key="contact.facet.self_summary", value="Reach me on +1 (415) 555-0132.")],
        purge_unevidenced=False,
    )

    assert kept == []
    assert _rules(log) == [("dropped", "personal_contact_detail")]
    assert "phone" in log[0]["detail"]


def test_a_year_range_is_not_a_phone_number() -> None:
    kept, _ = apply_person_floor(
        [_draft(value="VP Product Marketing at Sysdig 2021-2024.")], purge_unevidenced=False
    )

    assert len(kept) == 1


def test_two_years_and_a_headcount_in_one_sentence_are_not_a_phone_number() -> None:
    """The scan must not merge numbers that merely stand near each other.

    Nine to fifteen digits is a phone number, and a sentence like this holds fourteen across three
    unrelated numbers. Merging them dropped the person agent's most valuable output — this exact
    value, an evidenced ``self_summary``, was removed as a "personal contact detail".
    """
    kept, log = apply_person_floor(
        [
            _draft(
                field_key="contact.facet.self_summary",
                value="Grew the team from 12 to 250 people between 2019 and 2024.",
            )
        ],
        purge_unevidenced=False,
    )

    assert len(kept) == 1 and log == []


def test_a_voice_quote_with_its_media_timestamp_is_not_a_phone_number() -> None:
    """``voice_quote`` is *required* to carry ``media_timestamp`` inside its value, so nearly every
    quoted claim used to land in the digit band."""
    kept, log = apply_person_floor(
        [
            _draft(
                field_key="contact.facet.voice_quote",
                value={
                    "quote": "In 2023 we cut onboarding from 30 days to 3 days.",
                    "media_timestamp": "01:12:33",
                },
            )
        ],
        purge_unevidenced=False,
    )

    assert len(kept) == 1 and log == []


def test_a_career_history_of_two_roles_with_dates_is_not_a_phone_number() -> None:
    """``career_history`` is the source of the next person job's identity lock; losing it whole to
    a run of dates would break the lock as well as the page."""
    kept, log = apply_person_floor(
        [
            _draft(
                field_key="contact.facet.career_history",
                value=[
                    {"org": "Acme", "role": "VP", "start": "2015-01-01"},
                    {"org": "Beta", "role": "Dir", "start": "2019-06"},
                ],
            )
        ],
        purge_unevidenced=False,
    )

    assert len(kept) == 1 and log == []


def test_a_uuid_is_not_a_phone_number() -> None:
    """``contact.reports_to`` carries a uuid; its digit runs must not read as a phone number."""
    kept, log = apply_person_floor(
        [
            _draft(
                field_key="contact.reports_to",
                value={"name": "Dana Reyes", "contact_id": "3f2a1b4c-9d8e-4f2a-8b1c-0123456789ab"},
                evidence_span="I report to Dana Reyes, our CMO",
            )
        ],
        purge_unevidenced=False,
    )

    assert len(kept) == 1 and log == []


def test_a_labelled_phone_number_is_still_found() -> None:
    kept, _ = apply_person_floor([_draft(value="tel: +1 (415) 555-0132")], purge_unevidenced=False)

    assert kept == []


@pytest.mark.parametrize(
    "value",
    [
        "Reach me on +1 415 555 0134 any time.",
        "My direct line is 415-555-0134.",
        "Mobile 07700 900123",
        "Reach me at 415 555 0134.",
        "Direct 4155550134",
    ],
    ids=[
        "international-prefix",
        "dash-separated-tail",
        "uk-five-plus-six",
        "grouped-space-national",
        "contiguous-ten-digits",
    ],
)
def test_a_phone_number_carrying_its_own_shape_is_still_found(value: str) -> None:
    """Each of the shapes that says "phone" without a label: the signal is on the number itself."""
    kept, log = apply_person_floor([_draft(value=value)], purge_unevidenced=False)

    assert kept == [] and _rules(log) == [("dropped", "personal_contact_detail")]


@pytest.mark.parametrize(
    ("field_key", "value"),
    [
        (
            "contact.facet.conference_talk",
            ["RSA 2023 (Apr 24) — Detection at scale", "Black Hat 2024 — Purple teaming"],
        ),
        ("contact.facet.career_history", ["Acme 2019-06", "Beta 2021", "Cogent 2024"]),
        (
            "contact.facet.self_summary",
            "Grew the team from 12 to 250 people between 2019 and 2024.",
        ),
    ],
    ids=["talk-list", "career-dates", "counts-and-years"],
)
def test_years_dates_and_counts_carry_no_phone_signal(field_key: str, value: object) -> None:
    """The live R3 run's dropped rows. A digit count alone is not a phone number.

    The token fence only splits at *letter* tokens, so whitespace-separated years and dates still
    merged into one nine-to-fifteen-digit run: four talk / appearance rows and a career history
    were dropped whole as "personal contact detail". None of them carries a phone signal.
    """
    kept, log = apply_person_floor(
        [_draft(field_key=field_key, value=value)], purge_unevidenced=False
    )

    assert len(kept) == 1 and log == []


def test_a_phone_word_beside_the_number_is_still_enough_without_any_grouping() -> None:
    """The word rule stands on its own: this number carries none of the shapes above."""
    kept, log = apply_person_floor(
        [_draft(value="My cell is 020 7946 0958.")], purge_unevidenced=False
    )

    assert kept == [] and _rules(log) == [("dropped", "personal_contact_detail")]


def test_a_phone_word_in_one_leaf_does_not_make_another_leafs_years_a_phone_number() -> None:
    """The word must be beside the number, and the leaves are read apart.

    A talk row titled "Mobile threat landscape" sitting beside a row of appearance years is the
    live shape this rule kept dropping: the pass joined every leaf into one line, that line had no
    terminal punctuation so it was one "sentence", and the title's word made the years a phone
    number. Each leaf is now scanned on its own, and the word must be within thirty characters.
    """
    draft = _draft(
        field_key="contact.facet.conference_talk",
        value=[{"talk": "Mobile threat landscape", "appearances": "2019 2021 2024"}],
    )

    kept, log = apply_person_floor([draft], purge_unevidenced=False)

    assert kept == [draft] and log == []


def test_an_email_address_outside_the_work_email_field_drops_the_draft() -> None:
    kept, log = apply_person_floor(
        [_draft(value="Write to nick.fisher@gmail.com about the book.")], purge_unevidenced=False
    )

    assert kept == [] and _rules(log) == [("dropped", "personal_contact_detail")]


def test_the_work_email_field_is_the_one_place_an_email_is_allowed() -> None:
    draft = _draft(field_key="core.work_email", value="nick@probook.ai")

    kept, log = apply_person_floor([draft], purge_unevidenced=False)

    assert kept == [draft] and log == []


def test_a_street_address_in_a_quote_drops_the_draft() -> None:
    kept, log = apply_person_floor(
        [_draft(evidence_span="He works from 221 Baker Street most days.")],
        purge_unevidenced=False,
    )

    assert kept == [] and _rules(log) == [("dropped", "personal_contact_detail")]


def test_an_address_ending_the_clause_is_still_found() -> None:
    """``court`` is an ordinary noun as well as a thoroughfare, so it needs the comma; the address
    shape itself is unchanged."""
    kept, log = apply_person_floor(
        [_draft(evidence_span="Post it to 14 Elm Court, Springfield.")],
        purge_unevidenced=False,
    )

    assert kept == [] and _rules(log) == [("dropped", "personal_contact_detail")]


def test_a_thoroughfare_word_used_as_an_ordinary_noun_is_not_an_address() -> None:
    kept, log = apply_person_floor(
        [_draft(value="He led 3 Product Lines Way beyond target this year.")],
        purge_unevidenced=False,
    )

    assert len(kept) == 1 and log == []


def test_a_year_beside_a_place_name_is_not_a_house_number() -> None:
    kept, log = apply_person_floor(
        [_draft(value="Joined in 2019 Acme Corp St. Louis office.")], purge_unevidenced=False
    )

    assert len(kept) == 1 and log == []


def test_an_idiom_with_a_number_is_not_a_street_address() -> None:
    kept, log = apply_person_floor(
        [_draft(value="He says 5 people found a way. It became 3 steps on the road.")],
        purge_unevidenced=False,
    )

    assert len(kept) == 1 and log == []


# -- rule 2: minors --------------------------------------------------------------------------------


def test_a_minors_sentence_is_removed_and_the_rest_of_the_value_is_kept() -> None:
    kept, log = apply_person_floor(
        [
            _draft(
                value="He runs ultramarathons. He coaches his daughter's team on Sundays.",
                evidence_span="I run ultramarathons. I coach my daughter's team on Sundays.",
            )
        ],
        purge_unevidenced=False,
    )

    [survivor] = kept
    assert survivor.value_json == "He runs ultramarathons."
    assert survivor.evidence_span == "I run ultramarathons."
    assert survivor.markers["redacted"] == "minors"
    assert _rules(log) == [("redacted", "minors")]


def test_a_value_that_is_only_a_minors_sentence_drops_the_draft() -> None:
    kept, log = apply_person_floor(
        [_draft(value="He posts about his kids most weeks.")], purge_unevidenced=False
    )

    assert kept == [] and _rules(log) == [("dropped", "minors")]


# -- rule 3: the sensitivity floor -----------------------------------------------------------------


def test_a_health_sentence_inside_a_two_sentence_hobby_is_redacted_and_the_other_kept() -> None:
    kept, log = apply_person_floor(
        [
            _draft(
                value="He runs ultramarathons. He came back to it after chemotherapy in 2019.",
                evidence_span="I run ultras. I came back to it after chemotherapy in 2019.",
            )
        ],
        purge_unevidenced=False,
    )

    [survivor] = kept
    assert survivor.value_json == "He runs ultramarathons."
    assert survivor.evidence_span == "I run ultras."
    assert survivor.markers["redacted"] == "health"
    assert _rules(log) == [("redacted", "health")]


@pytest.mark.parametrize("category", SENSITIVITY_CATEGORIES)
def test_every_sensitivity_category_redacts_its_own_sentence_and_names_itself(
    category: str,
) -> None:
    keyword = KEYWORDS[category][0]

    kept, log = apply_person_floor(
        [_draft(value=f"He runs ultramarathons. A sentence about {keyword} follows.")],
        purge_unevidenced=False,
    )

    [survivor] = kept
    assert survivor.value_json == "He runs ultramarathons."
    assert survivor.markers["redacted"] == category
    assert _rules(log) == [("redacted", category)]


def test_a_draft_whose_whole_value_matched_the_floor_is_dropped() -> None:
    kept, log = apply_person_floor(
        [_draft(value="He was arrested at a protest in 2018.")], purge_unevidenced=False
    )

    assert kept == []
    assert [row["action"] for row in log] == ["dropped"]
    assert log[0]["rule"] in {"politics", "criminal"}


def test_two_categories_in_one_value_leave_a_list_marker() -> None:
    kept, log = apply_person_floor(
        [
            _draft(
                value=(
                    "He runs ultramarathons. He is a practising catholic. "
                    "He was diagnosed with diabetes."
                )
            )
        ],
        purge_unevidenced=False,
    )

    [survivor] = kept
    assert survivor.value_json == "He runs ultramarathons."
    assert survivor.markers["redacted"] == ["health", "faith"]
    assert sorted(_rules(log)) == [("redacted", "faith"), ("redacted", "health")]


# -- rule 4: origin as biography -------------------------------------------------------------------


def test_a_first_person_origin_story_is_kept_unsafe_and_marked() -> None:
    kept, log = apply_person_floor(
        [
            _draft(
                field_key="contact.facet.self_summary",
                value="He grew up in Lagos and moved here at nineteen.",
                evidence_span="I grew up in Lagos and moved here at nineteen.",
            )
        ],
        purge_unevidenced=False,
    )

    [survivor] = kept
    assert survivor.value_json == "He grew up in Lagos and moved here at nineteen."
    assert survivor.outreach_safe is False
    assert survivor.markers["origin_biography"] is True
    assert _rules(log) == [("unsafe", "origin_biography")]


# -- rule 5: self-announced milestones -------------------------------------------------------------


def test_a_wedding_post_is_kept_unsafe_and_marked_a_self_announced_milestone() -> None:
    kept, log = apply_person_floor(
        [
            _draft(
                field_key="contact.facet.recent_post",
                value="He posted that he got married in June.",
                evidence_span="We got married in June!",
            )
        ],
        purge_unevidenced=False,
    )

    [survivor] = kept
    assert survivor.outreach_safe is False
    assert survivor.markers["self_announced_milestone"] is True
    assert _rules(log) == [("unsafe", "self_announced_milestone")]


def test_a_baby_post_is_both_redacted_by_the_minors_rule_and_marked_unsafe() -> None:
    kept, log = apply_person_floor(
        [
            _draft(
                field_key="contact.facet.recent_post",
                value="He shipped the new pricing page. He welcomed a baby in March.",
                evidence_span="We shipped pricing. We welcomed a baby in March.",
            )
        ],
        purge_unevidenced=False,
    )

    [survivor] = kept
    assert survivor.value_json == "He shipped the new pricing page."
    assert survivor.markers["redacted"] == "minors"
    assert survivor.markers["self_announced_milestone"] is True
    assert survivor.outreach_safe is False
    assert _rules(log) == [("redacted", "minors"), ("unsafe", "self_announced_milestone")]


# -- rule 6: unevidenced rows ----------------------------------------------------------------------


def test_a_claim_with_a_quote_but_no_url_is_marked_unevidenced_and_kept() -> None:
    kept, log = apply_person_floor([_draft(source_url=None)], purge_unevidenced=False)

    [survivor] = kept
    assert survivor.markers["unevidenced"] is True
    assert _rules(log) == [("marked", "unevidenced")]
    assert "url" in log[0]["detail"]


def test_a_claim_with_no_quote_is_marked_unevidenced_and_kept() -> None:
    kept, log = apply_person_floor([_draft(evidence_span=None)], purge_unevidenced=False)

    assert len(kept) == 1 and kept[0].markers["unevidenced"] is True


def test_the_unevidenced_row_is_dropped_when_the_purge_flag_is_on() -> None:
    kept, log = apply_person_floor([_draft(source_url=None)], purge_unevidenced=True)

    assert kept == [] and _rules(log) == [("dropped", "unevidenced")]


def test_a_provider_record_is_never_unevidenced_even_when_the_purge_is_on() -> None:
    """A provider record is evidenced by the record, which is not a page a human can open. Rule 6
    exempts it: with the purge on, the un-exempt path would delete the lane's whole deterministic
    spine — title, headline, location, badges, network stats, career history and the work email.
    """
    record = _draft(
        field_key="contact.current_title",
        value="VP of Marketing",
        extraction_method=ExtractionMethod.API,
        source_url=None,
        evidence_span=None,
    )

    kept, log = apply_person_floor([record], purge_unevidenced=True)

    assert kept == [record] and log == []


def test_the_hooks_claim_is_never_unevidenced_even_when_the_purge_is_on() -> None:
    """The hooks are the agent's reading of claims already in the store, so they cite nothing by
    design."""
    hooks = _draft(
        field_key="contact.facet.hooks",
        value=["ultramarathons", "the pipeline book"],
        source_url=None,
        evidence_span=None,
    )

    kept, log = apply_person_floor([hooks], purge_unevidenced=True)

    assert kept == [hooks] and log == []


def test_an_ordinary_person_claim_missing_only_the_url_is_still_purged() -> None:
    """The exemptions are by shape, not a hole in rule 6: an LLM-synthesised claim with a quote and
    no URL is still purged when the operator turns the purge on."""
    kept, log = apply_person_floor(
        [_draft(field_key="contact.facet.hobby", source_url=None)], purge_unevidenced=True
    )

    assert kept == [] and _rules(log) == [("dropped", "unevidenced")]


# -- rule 7: hooks and openers resting on an unsafe fact -------------------------------------------


def test_an_opener_resting_on_the_origin_claim_is_dropped() -> None:
    origin = _draft(
        field_key="contact.facet.self_summary",
        value={
            "text": "Twenty years in developer tools.",
            "context": "He grew up in Lagos and moved here at nineteen.",
        },
        evidence_span="Twenty years in developer tools.",
    )
    opener = _draft(
        field_key="contact.facet.openers",
        value=["Twenty years in developer tools is a long run."],
        evidence_span="Twenty years in developer tools.",
    )

    kept, log = apply_person_floor([origin, opener], purge_unevidenced=False)

    assert [d.field_key for d in kept] == ["contact.facet.self_summary"]
    assert ("dropped", "unsafe_hook") in _rules(log)


def test_a_hook_that_matches_the_floor_itself_is_dropped() -> None:
    kept, log = apply_person_floor(
        [
            _draft(
                field_key="contact.facet.hooks",
                value=["his wedding in June", "ultramarathons"],
            )
        ],
        purge_unevidenced=False,
    )

    assert kept == [] and ("dropped", "unsafe_hook") in _rules(log)


def test_a_clean_opener_beside_an_unsafe_claim_survives() -> None:
    origin = _draft(
        field_key="contact.facet.self_summary",
        value="He grew up in Lagos and moved here at nineteen.",
        evidence_span="I grew up in Lagos and moved here at nineteen.",
    )
    opener = _draft(
        field_key="contact.facet.openers",
        value=["Saw you wrote The Pipeline Book."],
        evidence_span="I wrote The Pipeline Book last winter.",
    )

    kept, _ = apply_person_floor([origin, opener], purge_unevidenced=False)

    assert [d.field_key for d in kept] == [
        "contact.facet.self_summary",
        "contact.facet.openers",
    ]


# -- the value shapes ------------------------------------------------------------------------------


def test_a_list_value_loses_only_the_offending_item() -> None:
    kept, _ = apply_person_floor(
        [_draft(value=["ultramarathons", "coaching his son's football team"])],
        purge_unevidenced=False,
    )

    [survivor] = kept
    assert survivor.value_json == ["ultramarathons"]


def test_a_list_that_empties_drops_the_draft() -> None:
    kept, log = apply_person_floor(
        [_draft(value=["coaching his son's football team"])], purge_unevidenced=False
    )

    assert kept == [] and _rules(log) == [("dropped", "minors")]


def test_an_object_value_is_redacted_leaf_by_leaf() -> None:
    kept, _ = apply_person_floor(
        [
            _draft(
                field_key="contact.facet.voice_quote",
                value={
                    "text": "We shipped it in a week.",
                    "context": "He said it after chemotherapy. Then he laughed.",
                    "media_url": "https://example.com/ep/1",
                },
                evidence_span="We shipped it in a week.",
            )
        ],
        purge_unevidenced=False,
    )

    [survivor] = kept
    assert survivor.value_json == {
        "text": "We shipped it in a week.",
        "context": "Then he laughed.",
        "media_url": "https://example.com/ep/1",
    }


def test_an_object_whose_text_leaf_empties_drops_the_draft() -> None:
    kept, log = apply_person_floor(
        [
            _draft(
                field_key="contact.facet.voice_quote",
                value={"text": "My son turns four today.", "media_url": "https://e.dev/1"},
            )
        ],
        purge_unevidenced=False,
    )

    assert kept == [] and _rules(log) == [("dropped", "minors")]


def test_a_list_of_objects_loses_only_the_offending_entry() -> None:
    kept, _ = apply_person_floor(
        [
            _draft(
                field_key="contact.facet.career_history",
                value=[
                    {"org": "Sysdig", "role": "VP Product Marketing"},
                    {"org": "Probook", "role": "He took it after his surgery."},
                ],
            )
        ],
        purge_unevidenced=False,
    )

    [survivor] = kept
    assert survivor.value_json == [{"org": "Sysdig", "role": "VP Product Marketing"}]


# -- the failure law -------------------------------------------------------------------------------


def test_an_unreadable_value_passes_through_untouched_and_is_logged() -> None:
    draft = _draft(value={"a set is not a json value"})  # type: ignore[arg-type]

    kept, log = apply_person_floor([draft], purge_unevidenced=False)

    assert kept == [draft]
    assert _rules(log) == [("skipped", "unreadable_value")]


def test_the_pass_never_raises_on_a_batch_it_cannot_read() -> None:
    drafts = [_draft(value=object()), _draft()]  # type: ignore[arg-type]

    kept, log = apply_person_floor(drafts, purge_unevidenced=False)

    assert len(kept) == 2 and _rules(log) == [("skipped", "unreadable_value")]
