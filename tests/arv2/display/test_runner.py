"""A4 exit gate: one section call, aliases resolved to uuids, a bad reply retried once.

The provider is the :class:`ScriptedTransport` the lane permits for wrapper arithmetic (Global
Constraint 3): what is asserted here is the *request the runner builds* and the *materialisation
of a reply it did not write* — neither of which a live model can be made to demonstrate on
demand. The reply bodies below are hand-written, and the section a live model writes is proven
in the block test, not here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import SecretStr

from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.display.gather import ClientContext, SectionInput, SubjectRef
from clue_api.arv2.display.prompts import PROMPT_VERSION
from clue_api.arv2.display.recipes import recipes_for
from clue_api.arv2.display.render import DisplayClaim, alias_table
from clue_api.arv2.display.runner import (
    DISPLAY_MAX_TOKENS,
    LunaSectionRunner,
    Reply,
    SectionDraft,
    materialise,
)
from clue_api.arv2.sinks import MemoryLedger, MemoryRawSink
from clue_api.arv2.transport import HttpResponse, ScriptedTransport

ACCOUNT = "a0000000-0000-0000-0000-000000000001"
VARI = "c0000000-0000-0000-0000-000000000002"
DEV = "c0000000-0000-0000-0000-000000000003"

SUBJECT = SubjectRef(
    kind="contact",
    id=VARI,
    name="Vari Kaur",
    account_id=ACCOUNT,
    account_name="Zafran Security",
    account_domain="zafran.io",
    # The vocabulary value, because that is what ``gather.committee_members`` reads out of the
    # ``contact.persona`` claim — the runner is where it becomes the word a screen prints.
    persona="champion",
    title="VP Marketing",
)
DEV_RAO = SubjectRef(
    kind="contact",
    id=DEV,
    name="Dev Rao",
    account_id=ACCOUNT,
    account_name="Zafran Security",
    account_domain="zafran.io",
    persona="blocker",
)
ACCOUNT_SUBJECT = SubjectRef(
    kind="account",
    id=ACCOUNT,
    name="Zafran Security",
    account_id=ACCOUNT,
    account_name="Zafran Security",
    account_domain="zafran.io",
)
PEOPLE = (SUBJECT, DEV_RAO)
CLIENT = ClientContext(name="Clue", what_we_sell="ABM orchestration")


def _claim(
    claim_id: str,
    *,
    field_key: str = "contact.facet.hobby",
    value: str = "Cocktail YouTuber, a side hobby",
    quote: str | None = "It is a side hobby",
    priority: int = 2,
    outreach_safe: bool = True,
    subject: str | None = "Vari Kaur",
    entity_id: str = VARI,
) -> DisplayClaim:
    return DisplayClaim(
        claim_id=claim_id,
        field_key=field_key,
        value=value,
        quote=quote,
        observed_at="2026-06-17",
        priority=priority,
        outreach_safe=outreach_safe,
        subject=subject,
        media_timestamp=None,
        use_class=None,
        source_url="https://example.test/post",
        entity_id=entity_id,
        extraction_method="llm",
        source_key="exa_search",
        collected_at=datetime(2026, 6, 18, tzinfo=UTC),
    )


HOBBY = _claim("claim-hobby", priority=1)
REQS = _claim(
    "claim-reqs",
    field_key="account.open_requisitions",
    value="7 open ABM roles",
    quote="seven open ABM roles",
    priority=3,
    subject=None,
    entity_id=ACCOUNT,
)


def _section(
    section_key: str, claims: Sequence[DisplayClaim], *, page: str = "contact"
) -> SectionInput:
    recipe = next(item for item in recipes_for(page) if item.section_key == section_key)
    return SectionInput(recipe=recipe, claims=tuple(claims), deduped={})


def _alias_of(section: SectionInput) -> dict[str, str]:
    """``{claim id: alias}`` — the runner builds the same table, so the reply can cite it."""
    _, aliases = alias_table(section.claims)
    return {claim_id: alias for alias, claim_id in aliases.items()}


def _ok(content: str, *, cost: float = 0.0044) -> HttpResponse:
    body = {
        "id": "gen-1",
        "choices": [{"message": {"content": content}}],
        "usage": {"cost": cost},
    }
    return HttpResponse(status=200, headers={}, body=json.dumps(body).encode())


def _reply_body(payload: Mapping[str, object]) -> HttpResponse:
    return _ok(json.dumps(payload))


def _runner(transport: ScriptedTransport) -> LunaSectionRunner:
    caller = ProviderCaller(
        transport=transport,
        raw_sink=MemoryRawSink(),
        ledger=MemoryLedger(),
        now=lambda: datetime.now(UTC),
    )
    return LunaSectionRunner(
        caller,
        api_key=SecretStr("test-key"),
        base_url="https://openrouter.ai/api/v1",
        model="x-ai/grok-4-fast",
        timeout_s=90.0,
    )


def _write(
    responses: Sequence[HttpResponse],
    section: SectionInput,
    *,
    subject: SubjectRef = SUBJECT,
    people: Sequence[SubjectRef] = PEOPLE,
) -> tuple[SectionDraft, ScriptedTransport]:
    transport = ScriptedTransport(list(responses))
    page = section.recipe.page
    draft = _runner(transport).write_section(
        page=page,
        subject=subject,
        client=CLIENT,
        recipes=recipes_for(page),
        section=section,
        people=people,
    )
    return draft, transport


def _sent_body(transport: ScriptedTransport, index: int = 0) -> dict[str, Any]:
    raw = transport.requests[index].body or b""
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
    return parsed


# -- the request -------------------------------------------------------------------------------


def test_the_request_asks_for_json_at_full_effort_and_the_label_names_the_section() -> None:
    """Constraint 7: the display call never lowers reasoning effort and never pins temperature."""
    section = _section("openers", [HOBBY])
    alias = _alias_of(section)[HOBBY.claim_id]
    draft, transport = _write(
        [
            _reply_body(
                {
                    "section": {
                        "key": "openers",
                        "items": [
                            {
                                "h2": "Open with the cocktail channel",
                                "body": [{"text": "He films cocktails.", "claimIds": [alias]}],
                                "sendLine": {
                                    "channel": "In your email",
                                    "text": "Saw the cocktail channel.",
                                    "claimIds": [alias],
                                },
                            }
                        ],
                    }
                }
            )
        ],
        section,
    )

    body = _sent_body(transport)
    assert body["model"] == "x-ai/grok-4-fast"
    assert body["usage"] == {"include": True}
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] == DISPLAY_MAX_TOKENS
    assert "reasoning" not in body
    assert "temperature" not in body
    assert draft.model == "x-ai/grok-4-fast"
    assert draft.cost is not None
    assert draft.cost.cost_usd == Decimal("0.0044")
    assert draft.raw_refs == ("memory:0",)


def test_the_ledger_label_is_the_page_and_the_section() -> None:
    section = _section("openers", [HOBBY])
    transport = ScriptedTransport([_reply_body({"section": {"key": "openers", "empty": True}})])
    ledger = MemoryLedger()
    caller = ProviderCaller(
        transport=transport,
        raw_sink=MemoryRawSink(),
        ledger=ledger,
        now=lambda: datetime.now(UTC),
    )
    runner = LunaSectionRunner(
        caller,
        api_key=SecretStr("test-key"),
        base_url="https://openrouter.ai/api/v1",
        model="x-ai/grok-4-fast",
        timeout_s=90.0,
    )
    runner.write_section(
        page="contact",
        subject=SUBJECT,
        client=CLIENT,
        recipes=recipes_for("contact"),
        section=section,
        people=PEOPLE,
    )
    assert {row.label for row in ledger.rows} == {"display-contact-openers"}
    assert {row.provider for row in ledger.rows} == {"openrouter"}
    assert {row.operation for row in ledger.rows} == {"chat/completions"}


def test_forbidden_aliases_reach_the_prompt_of_the_regenerate_call() -> None:
    section = _section("openers", [HOBBY])
    alias = _alias_of(section)[HOBBY.claim_id]
    transport = ScriptedTransport([_reply_body({"section": {"key": "openers", "empty": True}})])
    _runner(transport).write_section(
        page="contact",
        subject=SUBJECT,
        client=CLIENT,
        recipes=recipes_for("contact"),
        section=section,
        people=PEOPLE,
        forbidden_aliases=[alias],
    )
    user_message = _sent_body(transport)["messages"][1]["content"]
    assert f"Your previous draft cited {alias}" in user_message


# -- materialisation ---------------------------------------------------------------------------


def test_aliases_resolve_to_claim_uuids_and_an_unknown_alias_is_named() -> None:
    section = _section("openers", [HOBBY, REQS])
    alias = _alias_of(section)[HOBBY.claim_id]
    draft, _ = _write(
        [
            _reply_body(
                {
                    "section": {
                        "key": "openers",
                        "items": [
                            {
                                "h2": "Open with the cocktail channel",
                                "body": [
                                    {"text": "He films cocktails.", "claimIds": [alias, "c99"]}
                                ],
                            }
                        ],
                    }
                }
            )
        ],
        section,
    )

    assert draft.items[0]["body"][0]["claimIds"] == [HOBBY.claim_id]
    assert draft.cited_claim_ids == [HOBBY.claim_id]
    assert draft.checks["unknown_aliases"] == ["c99"]
    assert draft.checks["aliases"] == 2
    assert draft.checks["prompt_version"] == PROMPT_VERSION
    assert draft.aliases[alias] == HOBBY.claim_id


def test_a_cited_claim_that_is_not_in_the_section_input_is_dropped_as_off_recipe() -> None:
    """The alias table cannot produce this; a page-layer regenerate reusing a stale map can."""
    section = _section("openers", [HOBBY])
    reply = Reply.model_validate(
        {
            "section": {
                "key": "openers",
                "items": [
                    {
                        "h2": "An opener",
                        "body": [{"text": "One sentence.", "claimIds": ["c1", "c2"]}],
                    }
                ],
            }
        }
    )
    intro, items, cited, checks = materialise(
        reply,
        section=section,
        aliases={"c1": HOBBY.claim_id, "c2": "claim-from-another-section"},
        people=PEOPLE,
        subject=SUBJECT,
    )
    assert intro == []
    assert items[0]["body"][0]["claimIds"] == [HOBBY.claim_id]
    assert cited == [HOBBY.claim_id]
    assert checks["off_recipe"] == ["claim-from-another-section"]


def test_priority_is_the_strongest_cited_claim_not_the_models_opinion() -> None:
    section = _section("openers", [HOBBY, REQS])
    alias = _alias_of(section)
    draft, _ = _write(
        [
            _reply_body(
                {
                    "section": {
                        "key": "openers",
                        "items": [
                            {
                                "h2": "Both claims",
                                "body": [
                                    {
                                        "text": "One sentence.",
                                        "claimIds": [alias[REQS.claim_id], alias[HOBBY.claim_id]],
                                    }
                                ],
                                "priority": 3,
                            },
                            {
                                "h2": "No claim at all",
                                "body": [{"text": "Unsourced.", "claimIds": []}],
                                "priority": 9,
                            },
                        ],
                    }
                }
            )
        ],
        section,
    )
    assert draft.items[0]["priority"] == 1  # min over the cited claims, not the model's 3
    assert draft.items[1]["priority"] == 3  # 9 is out of range and clips to the weakest
    assert draft.checks["uncited_sentences"] == 1


def test_contact_refs_resolve_case_insensitively_and_unknown_names_are_dropped() -> None:
    section = _section("openers", [HOBBY])
    alias = _alias_of(section)[HOBBY.claim_id]
    draft, _ = _write(
        [
            _reply_body(
                {
                    "section": {
                        "key": "openers",
                        "items": [
                            {
                                "h2": "An opener",
                                "body": [{"text": "One sentence.", "claimIds": [alias]}],
                                "contactRefs": [
                                    {"name": "vari kaur"},
                                    {"name": "Dev Rao"},
                                    {"name": "Nobody At All"},
                                ],
                            }
                        ],
                    }
                }
            )
        ],
        section,
    )
    # The personas are written into ``body_json`` as display text: this payload is stored and
    # served verbatim, so a raw ``champion`` here would be a raw ``champion`` on the screen
    # forever (D4-b decision 5).
    assert draft.items[0]["contactRefs"] == [
        {
            "accountId": ACCOUNT,
            "contactId": VARI,
            "name": "Vari Kaur",
            "title": "VP Marketing",
            "persona": "Champion",
        },
        {"accountId": ACCOUNT, "contactId": DEV, "name": "Dev Rao", "persona": "Blocker"},
    ]
    assert draft.checks["unresolved_refs"] == 1


def test_an_item_subject_is_dropped_outside_the_subject_section() -> None:
    item = {
        "h2": "What Dev said",
        "body": [{"text": "One sentence.", "claimIds": []}],
        "subject": {"name": "Dev Rao"},
    }
    openers = _section("openers", [HOBBY])
    other, _ = _write([_reply_body({"section": {"key": "openers", "items": [item]}})], openers)
    assert "subject" not in other.items[0]


def test_send_line_survives_only_on_the_contact_page_and_only_when_it_says_something() -> None:
    section = _section("openers", [HOBBY])
    alias = _alias_of(section)[HOBBY.claim_id]
    kept, _ = _write(
        [
            _reply_body(
                {
                    "section": {
                        "key": "openers",
                        "items": [
                            {
                                "h2": "An opener",
                                "body": [{"text": "One sentence.", "claimIds": [alias]}],
                                "sendLine": {
                                    "channel": "In your email",
                                    "text": "Saw the cocktail channel.",
                                    "claimIds": [alias],
                                },
                            },
                            {
                                "h2": "A second opener",
                                "body": [{"text": "One sentence.", "claimIds": [alias]}],
                                "sendLine": {
                                    "channel": "In your email",
                                    "text": "   ",
                                    "claimIds": [alias],
                                },
                            },
                        ],
                    }
                }
            )
        ],
        section,
    )
    assert kept.items[0]["sendLine"] == {
        "channel": "In your email",
        "text": "Saw the cocktail channel.",
        "claimIds": [HOBBY.claim_id],
    }
    assert kept.items[1]["sendLine"] is None

    insights = _section("buying-signals", [REQS], page="insights")
    alias_reqs = _alias_of(insights)[REQS.claim_id]
    dropped, _ = _write(
        [
            _reply_body(
                {
                    "section": {
                        "key": "buying-signals",
                        "items": [
                            {
                                "h2": "Seven open ABM roles",
                                "body": [{"text": "One sentence.", "claimIds": [alias_reqs]}],
                                "sendLine": {
                                    "channel": "In your email",
                                    "text": "Not allowed on this page.",
                                    "claimIds": [alias_reqs],
                                },
                            }
                        ],
                    }
                }
            )
        ],
        insights,
        subject=ACCOUNT_SUBJECT,
    )
    assert dropped.items[0]["sendLine"] is None


def test_fit_disposition_is_kept_only_on_why_they_fit() -> None:
    item = {
        "h2": "Funding",
        "body": [{"text": "One sentence.", "claimIds": []}],
        "fitDisposition": "caveat",
    }
    fit = _section("why-they-fit", [REQS], page="overview")
    kept, _ = _write(
        [_reply_body({"section": {"key": "why-they-fit", "items": [item]}})],
        fit,
        subject=ACCOUNT_SUBJECT,
    )
    assert kept.items[0]["fitDisposition"] == "caveat"

    why_now = _section("why-now", [REQS], page="overview")
    dropped, _ = _write(
        [_reply_body({"section": {"key": "why-now", "items": [item]}})],
        why_now,
        subject=ACCOUNT_SUBJECT,
    )
    assert "fitDisposition" not in dropped.items[0]


def test_intro_is_kept_only_on_a_narrative_section_and_ids_are_one_based() -> None:
    reply = {
        "intro": [{"text": "They sell vulnerability triage.", "claimIds": []}],
        "items": [
            {"h2": "First", "body": [{"text": "a", "claimIds": []}]},
            {"h2": "Second", "body": [{"text": "b", "claimIds": []}]},
        ],
    }
    narrative = _section("why-they-fit", [REQS], page="overview")
    kept, _ = _write(
        [_reply_body({"section": {"key": "why-they-fit", **reply}})],
        narrative,
        subject=ACCOUNT_SUBJECT,
    )
    assert kept.intro == [{"text": "They sell vulnerability triage.", "claimIds": []}]
    assert [item["id"] for item in kept.items] == ["why-they-fit-1", "why-they-fit-2"]
    assert all(item["newSinceLastVisit"] is False for item in kept.items)

    plain = _section("openers", [HOBBY])
    dropped, _ = _write([_reply_body({"section": {"key": "openers", **reply}})], plain)
    assert dropped.intro == []
    assert [item["id"] for item in dropped.items] == ["openers-1", "openers-2"]


def test_segments_are_kept_only_when_they_rejoin_the_sentence_exactly() -> None:
    section = _section("openers", [HOBBY])
    alias = _alias_of(section)[HOBBY.claim_id]
    draft, _ = _write(
        [
            _reply_body(
                {
                    "section": {
                        "key": "openers",
                        "items": [
                            {
                                "h2": "An opener",
                                "body": [
                                    {
                                        "text": "He films cocktails at home.",
                                        "claimIds": [alias],
                                        "segments": [
                                            {"text": "He films cocktails", "claimIds": [alias]},
                                            {"text": "at home.", "claimIds": []},
                                        ],
                                    },
                                    {
                                        "text": "He also writes about it.",
                                        "claimIds": [alias],
                                        "segments": [
                                            {"text": "Something else", "claimIds": [alias]}
                                        ],
                                    },
                                ],
                            }
                        ],
                    }
                }
            )
        ],
        section,
    )
    body = draft.items[0]["body"]
    assert body[0]["segments"] == [
        {"text": "He films cocktails", "claimIds": [HOBBY.claim_id]},
        {"text": "at home.", "claimIds": []},
    ]
    assert "segments" not in body[1]
    assert draft.checks["segments_dropped"] == 1


def test_the_control_test_sections_list_shape_is_accepted() -> None:
    section = _section("openers", [HOBBY])
    draft, _ = _write(
        [_reply_body({"sections": [{"key": "openers", "items": [], "empty": True}]})],
        section,
    )
    assert draft.items == []
    assert draft.checks["model_said_empty"] is True


def test_an_empty_section_is_a_real_answer() -> None:
    section = _section("openers", [HOBBY])
    draft, _ = _write([_reply_body({"section": {"key": "openers", "empty": True}})], section)
    assert draft.items == []
    assert draft.intro == []
    assert draft.cited_claim_ids == []
    assert draft.checks["model_said_empty"] is True
    assert draft.checks["reply_invalid"] is False


# -- the bad reply -----------------------------------------------------------------------------


def test_an_invalid_reply_is_retried_once_and_the_second_answer_is_used() -> None:
    section = _section("openers", [HOBBY])
    alias = _alias_of(section)[HOBBY.claim_id]
    good = _reply_body(
        {
            "section": {
                "key": "openers",
                "items": [{"h2": "An opener", "body": [{"text": "One.", "claimIds": [alias]}]}],
            }
        }
    )
    draft, transport = _write([_ok("not json at all {"), good], section)
    assert len(transport.requests) == 2
    assert transport.requests[0].body == transport.requests[1].body
    assert draft.checks["reply_retried"] is True
    assert draft.checks["reply_invalid"] is False
    assert draft.items[0]["h2"] == "An opener"


def test_a_reply_that_does_not_fit_the_shape_is_also_retried() -> None:
    section = _section("openers", [HOBBY])
    draft, transport = _write(
        [
            _reply_body({"section": {"items": [{"body": "not a list"}]}}),
            _reply_body({"section": {"key": "openers", "empty": True}}),
        ],
        section,
    )
    assert len(transport.requests) == 2
    assert draft.checks["reply_retried"] is True
    assert draft.checks["reply_invalid"] is False


def test_two_invalid_replies_yield_an_empty_draft_rather_than_an_exception() -> None:
    section = _section("openers", [HOBBY])
    draft, transport = _write([_ok("still not json"), _ok("nor this")], section)
    assert len(transport.requests) == 2
    assert draft.items == []
    assert draft.intro == []
    assert draft.cited_claim_ids == []
    assert draft.checks["reply_invalid"] is True
    assert draft.checks["reply_retried"] is True
    assert draft.cost is not None  # the two calls were still paid for


def test_every_draft_carries_the_lane_checks() -> None:
    section = _section("openers", [HOBBY])
    invalid, _ = _write([_ok("no"), _ok("no")], section)
    valid, _ = _write([_reply_body({"section": {"key": "openers", "empty": True}})], section)
    expected = {
        "aliases",
        "prompt_version",
        "unknown_aliases",
        "off_recipe",
        "segments_dropped",
        "unresolved_refs",
        "uncited_sentences",
        "reply_retried",
        "reply_invalid",
        "model_said_empty",
    }
    assert expected <= set(invalid.checks)
    assert expected <= set(valid.checks)
