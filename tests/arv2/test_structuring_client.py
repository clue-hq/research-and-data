"""The structuring client's post-parse layer, over a hand-written model reply.

Global Constraint 3 permits no mocked provider bodies, and none is used here: every test below
calls a *pure function* — :func:`read_structured_reply`, :func:`parse_reply_text` and the two
coercions — with a dict written by hand. Nothing pretends to be OpenRouter; the live behaviour is
proven in ``test_structuring_client_live.py`` against the real model.

What is asserted is exactly what a model must not be trusted to self-report: which keys are
registered, whether a quote is really in the bundle, whether a value fits its schema, and what an
unreadable priority means.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from clue_api.arv2.errors import RawParseError
from clue_api.arv2.structuring_client import (
    DEFAULT_PRIORITY,
    MODEL_PROPOSED_ORIGIN,
    UNREGISTERED_KEY_ORIGIN,
    FieldCatalog,
    FieldSpec,
    StructuredOutput,
    catalog_menu_text,
    check_value_schema,
    coerce_outreach_safe,
    coerce_priority,
    parse_reply_text,
    read_structured_reply,
)

BUNDLE = """=== SOURCE A: the company's own site ===
Zafran Security raised a $30M Series B led by Sequoia Capital.
Our platform finds the exploitable 2% of vulnerabilities.

=== SOURCE B: a podcast transcript ===
I started the company after twelve years of incident response work.
"""

CATALOG = FieldCatalog(
    account=(
        FieldSpec("core.account_name", "Canonical account name.", {"type": "string"}),
        FieldSpec(
            "core.employee_range",
            "Employee range.",
            {
                "type": "object",
                "required": ["label"],
                "properties": {"label": {"type": "string"}, "min": {"type": "integer"}},
            },
        ),
        FieldSpec("account.operational_pain", "Synthesized operational pain."),
    ),
    contact=(
        FieldSpec("contact.current_title", "Current professional title.", {"type": "string"}),
    ),
    facet=(
        FieldSpec(
            "contact.facet.alma_mater",
            "Schools attended.",
            {"type": "array", "items": {"type": "string"}},
        ),
    ),
)


def _reply(*claims: dict[str, object], **rest: object) -> dict[str, object]:
    return {"claims": list(claims), **rest}


def _read(reply: dict[str, object]) -> StructuredOutput:
    return read_structured_reply(reply, catalog=CATALOG, bundle=BUNDLE, model="test/model")


# -- the catalog -------------------------------------------------------------------------------


def test_the_catalog_lists_every_registered_key_across_its_three_sections() -> None:
    assert CATALOG.keys() == {
        "core.account_name",
        "core.employee_range",
        "account.operational_pain",
        "contact.current_title",
        "contact.facet.alma_mater",
    }
    assert CATALOG.spec("core.account_name") is not None
    assert CATALOG.spec("core.nonexistent") is None


def test_the_menu_renders_three_headed_sections_of_key_and_description() -> None:
    """The menu is the only place a legal key can come from, so its shape is the contract."""
    menu = catalog_menu_text(CATALOG)

    assert "ACCOUNT FIELD KEYS:" in menu
    assert "CONTACT FIELD KEYS:" in menu
    assert "CONTACT FACET (personal) FIELD KEYS:" in menu
    assert "  core.account_name — Canonical account name." in menu
    assert "  contact.facet.alma_mater — Schools attended." in menu
    assert menu.index("ACCOUNT FIELD KEYS:") < menu.index("CONTACT FIELD KEYS:")


# -- the partition -----------------------------------------------------------------------------


def test_a_claim_on_an_unregistered_key_is_moved_to_proposed_and_never_refused() -> None:
    """The evidence survives the re-filing: dropping it would throw away a real observation."""
    output = _read(
        _reply(
            {
                "field_key": "core.account_name",
                "value": "Zafran Security",
                "evidence_span": "Zafran Security raised a $30M Series B",
            },
            {
                "field_key": "account.invented_key",
                "value": "the exploitable 2%",
                "evidence_span": "finds the exploitable 2% of vulnerabilities",
                "source_url": "https://www.zafran.io/",
            },
        )
    )

    assert [claim.field_key for claim in output.claims] == ["core.account_name"]
    assert len(output.proposed) == 1
    refiled = output.proposed[0]
    assert refiled.suggested_key == "account.invented_key"
    assert refiled.origin == UNREGISTERED_KEY_ORIGIN
    assert refiled.value == "the exploitable 2%"
    assert refiled.evidence_span == "finds the exploitable 2% of vulnerabilities"
    assert refiled.source_url == "https://www.zafran.io/"


def test_a_claim_with_no_readable_field_key_is_re_filed_rather_than_dropped() -> None:
    """An unnamed key is a key the catalog does not carry — same path, same evidence kept."""
    output = _read(_reply({"value": "orphan", "evidence_span": "led by Sequoia Capital"}))

    assert output.claims == ()
    assert output.proposed[0].suggested_key == ""
    assert output.proposed[0].origin == UNREGISTERED_KEY_ORIGIN
    assert output.proposed[0].value == "orphan"


def test_the_models_own_proposals_keep_their_own_origin() -> None:
    output = _read(
        _reply(
            proposed_fields=[
                {
                    "suggested_key": "account.exploitability_focus",
                    "why": "no registered key covers this",
                    "value": "the exploitable 2%",
                    "evidence_span": "finds the exploitable 2% of vulnerabilities",
                    "source_url": "https://www.zafran.io/",
                }
            ]
        )
    )

    assert len(output.proposed) == 1
    assert output.proposed[0].origin == MODEL_PROPOSED_ORIGIN
    assert output.proposed[0].why == "no registered key covers this"


def test_negatives_and_risks_are_read_with_their_status_and_flag() -> None:
    output = _read(
        _reply(
            negatives_and_risks=[
                {
                    "what": "an acquisition rumour",
                    "status": "UNRESOLVED",
                    "evidence_span": "led by Sequoia Capital",
                    "source_url": "https://example.test/press",
                    "outreach_safe": False,
                }
            ]
        )
    )

    assert len(output.negatives) == 1
    assert output.negatives[0].status == "UNRESOLVED"
    assert output.negatives[0].outreach_safe is False


def test_a_reply_with_nothing_readable_yields_an_empty_output_not_an_error() -> None:
    """An honestly empty answer is a correct answer (the lane's core rule)."""
    output = _read({"claims": "not a list", "proposed_fields": [42, "junk"]})

    assert output.claims == ()
    assert output.proposed == ()
    assert output.negatives == ()


def test_the_call_metadata_rides_through_to_the_output() -> None:
    output = read_structured_reply(
        _reply(),
        catalog=CATALOG,
        bundle=BUNDLE,
        model="openai/gpt-5-mini",
        cost_usd=Decimal("0.0123"),
        request_id="gen-abc",
        raw_ref="/tmp/raw.json",
    )

    assert output.model == "openai/gpt-5-mini"
    assert output.cost_usd == Decimal("0.0123")
    assert output.request_id == "gen-abc"
    assert output.raw_ref == "/tmp/raw.json"


# -- the annotations ---------------------------------------------------------------------------


def test_the_verbatim_annotation_reports_exact_partial_and_not_found() -> None:
    """Appendix A law 6: the verdict is an annotation on the claim, never a reason to drop it."""
    output = _read(
        _reply(
            {
                "field_key": "core.account_name",
                "value": "Zafran Security",
                "evidence_span": "Zafran Security raised a $30M Series B led by Sequoia Capital.",
            },
            {
                "field_key": "account.operational_pain",
                "value": "vulnerability noise",
                "evidence_span": (
                    "Zafran Security raised a $30M Series B led by Sequoia Capital in 2024"
                ),
            },
            {
                "field_key": "contact.current_title",
                "value": "Chief Revenue Officer",
                "evidence_span": "She was appointed Chief Revenue Officer in March.",
            },
        )
    )

    assert [claim.evidence_verbatim for claim in output.claims] == [
        "EXACT",
        "PARTIAL",
        "NOT_FOUND",
    ]
    assert len(output.claims) == 3, "a fabricated span is annotated, not refused"


def test_schema_valid_is_true_false_or_none_for_a_field_with_no_schema() -> None:
    output = _read(
        _reply(
            {
                "field_key": "core.employee_range",
                "value": {"label": "51-200", "min": 51},
                "evidence_span": "Zafran Security",
            },
            {
                "field_key": "core.employee_range",
                "value": {"min": 51},
                "evidence_span": "Zafran Security",
            },
            {
                "field_key": "account.operational_pain",
                "value": {"anything": True},
                "evidence_span": "Zafran Security",
            },
        )
    )

    assert [claim.schema_valid for claim in output.claims] == [True, False, None]


def test_priority_defaults_to_three_and_accepts_the_poc_spelling() -> None:
    output = _read(
        _reply(
            {"field_key": "core.account_name", "value": "a", "priority": 1},
            {"field_key": "core.account_name", "value": "b", "priority": "P2"},
            {"field_key": "core.account_name", "value": "c", "priority": "3"},
            {"field_key": "core.account_name", "value": "d"},
            {"field_key": "core.account_name", "value": "e", "priority": 9},
            {"field_key": "core.account_name", "value": "f", "priority": "high"},
        )
    )

    assert [claim.priority for claim in output.claims] == [1, 2, 3, 3, 3, 3]
    assert DEFAULT_PRIORITY == 3


def test_outreach_safe_defaults_to_true_when_the_model_said_nothing_readable() -> None:
    output = _read(
        _reply(
            {"field_key": "core.account_name", "value": "a"},
            {"field_key": "core.account_name", "value": "b", "outreach_safe": False},
            {"field_key": "core.account_name", "value": "c", "outreach_safe": "false"},
            {"field_key": "core.account_name", "value": "d", "outreach_safe": 0},
        )
    )

    assert [claim.outreach_safe for claim in output.claims] == [True, False, False, True]


def test_an_absent_optional_string_is_none_rather_than_an_empty_string() -> None:
    output = _read(
        _reply(
            {
                "field_key": "core.account_name",
                "value": "Zafran Security",
                "evidence_span": "Zafran Security",
                "source_url": "  ",
                "media_timestamp": None,
                "source_kind": "company_primary",
            }
        )
    )

    claim = output.claims[0]
    assert claim.source_url is None
    assert claim.media_timestamp is None
    assert claim.source_kind == "company_primary"


# -- the coercions and the schema checker, directly ---------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, 1), (2, 2), (3, 3), ("P1", 1), ("p3", 3), (0, 3), (True, 3), (None, 3), (1.0, 3)],
)
def test_coerce_priority(value: object, expected: int) -> None:
    assert coerce_priority(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, True), (False, False), ("no", False), ("YES", True), (None, True), (1, True)],
)
def test_coerce_outreach_safe(value: object, expected: bool) -> None:
    assert coerce_outreach_safe(value) is expected


@pytest.mark.parametrize(
    ("value", "schema", "expected"),
    [
        ("text", {"type": "string"}, True),
        (7, {"type": "string"}, False),
        (7, {"type": "integer"}, True),
        (True, {"type": "integer"}, False),
        (7.5, {"type": "number"}, True),
        (["a", "b"], {"type": "array", "items": {"type": "string"}}, True),
        (["a", 2], {"type": "array", "items": {"type": "string"}}, False),
        ("1m_10m", {"type": "string", "enum": ["1m_10m", "10m_50m"]}, True),
        ("400m", {"type": "string", "enum": ["1m_10m", "10m_50m"]}, False),
        ({"label": "x"}, {"type": "object", "required": ["label"]}, True),
        ({"other": "x"}, {"type": "object", "required": ["label"]}, False),
        (
            {"label": "x", "min": "fifty"},
            {"type": "object", "properties": {"min": {"type": "integer"}}},
            False,
        ),
        ("anything", {"format": "uri"}, True),
        ("anything", None, None),
    ],
)
def test_check_value_schema(
    value: object, schema: dict[str, object] | None, expected: bool | None
) -> None:
    assert check_value_schema(value, schema) is expected


# -- the malformed reply -------------------------------------------------------------------------


def test_a_malformed_reply_raises_raw_parse_error_naming_the_saved_record() -> None:
    """Law 1 saved the body before this ran, so the failure is replayable from ``raw_ref``."""
    with pytest.raises(RawParseError) as excinfo:
        parse_reply_text("Sure! Here are the claims:", raw_ref="/tmp/raw/openrouter/x.json")

    assert excinfo.value.raw_ref == "/tmp/raw/openrouter/x.json"
    assert "/tmp/raw/openrouter/x.json" in str(excinfo.value)


def test_a_reply_that_is_json_but_not_an_object_also_raises() -> None:
    with pytest.raises(RawParseError) as excinfo:
        parse_reply_text("[1, 2, 3]", raw_ref="memory:0")

    assert excinfo.value.raw_ref == "memory:0"


def test_a_well_formed_reply_parses_to_its_mapping() -> None:
    assert parse_reply_text('{"claims": []}', raw_ref=None) == {"claims": []}
