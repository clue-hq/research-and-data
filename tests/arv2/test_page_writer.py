"""The separate page writer's correctness checks, reference mapping and repair loop (no network)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from uuid import UUID, uuid4

import pytest

from clue_api.arv2.page_writer import (
    SECTIONS,
    PageWriterError,
    check_pages,
    to_drafts,
    write_account_pages,
    write_checked,
    write_contact_page,
)
from clue_api.arv2.page_writer_view import Person, finding_texts, findings, render_findings

C1, C2, P1 = uuid4(), uuid4(), uuid4()
CONTACT = uuid4()

ACCOUNT_DOSSIER = {
    "document": {
        "sections": [
            {
                "section": "Benefits",
                "findings": [
                    {
                        "id": "F001",
                        "topic": "Field workforce",
                        "finding": (
                            'A post says the role "supports our field teams across every region."'
                        ),
                        "review": {"status": "supported"},
                    },
                    {
                        "id": "F002",
                        "topic": "A namesake",
                        "finding": "A different person with the same name.",
                        "review": {"status": "wrong_entity"},
                    },
                ],
            }
        ]
    },
    "receipt": {
        "entries": [{"id": "F001", "claim_id": str(C1)}, {"id": "F002", "claim_id": str(C2)}]
    },
}
PERSON_DOSSIER = {
    "document": {
        "sections": [
            {
                "section": "Role",
                "findings": [
                    {"id": "F001", "topic": "Title", "finding": "VP Total Rewards since 2022."}
                ],
            }
        ]
    },
    "receipt": {"entries": [{"id": "F001", "claim_id": str(P1)}]},
}


def _sentence(text: str, refs: Sequence[str] = (), kind: str = "fact") -> dict[str, object]:
    return {"text": text, "kind": kind, "refs": list(refs)}


def _section(key: str, **extra: object) -> dict[str, object]:
    return {"key": key, "intro": [], "items": [], "gaps": [], **extra}


def _pages(pages: Sequence[str], fill: Mapping[str, dict[str, object]] | None = None):
    return {
        "pages": [
            {"page": p, "sections": [(fill or {}).get(k) or _section(k) for k in SECTIONS[p]]}
            for p in pages
        ]
    }


TEXTS = {"F001": ACCOUNT_DOSSIER["document"]["sections"][0]["findings"][0]["finding"]}


def test_wrong_entity_findings_never_reach_the_writer() -> None:
    assert [f["id"] for _, f in findings(ACCOUNT_DOSSIER)] == ["F001"]


def test_a_complete_cited_page_passes() -> None:
    result = _pages(
        ["contact"],
        {
            "why-this-person": _section(
                "why-this-person",
                items=[
                    {
                        "h2": "Owns field support",
                        "body": [
                            _sentence('He supports "field teams across every region."', ["F001"])
                        ],
                    }
                ],
            ),
            "openers": _section(
                "openers",
                items=[
                    {
                        "h2": "Field teams",
                        "body": [_sentence("Hook on field teams.", ["F001"])],
                        "send_line": _sentence("How do field teams get support?", kind="inference"),
                    }
                ],
            ),
        },
    )
    assert check_pages(result, ["contact"], TEXTS, set()) == []


@pytest.mark.parametrize(
    ("fill", "expected"),
    [
        (
            {"why-this-person": _section("why-this-person", intro=[_sentence("x", ["F999"])])},
            "unknown refs",
        ),
        (
            {"why-this-person": _section("why-this-person", intro=[_sentence("Uncited fact.")])},
            "uncited fact",
        ),
        (
            {
                "why-this-person": _section(
                    "why-this-person",
                    intro=[_sentence('He said "we hire only robots now".', ["F001"])],
                )
            },
            "quote not in cited findings",
        ),
        (
            {
                "angles": _section(
                    "angles",
                    items=[
                        {
                            "h2": "x",
                            "body": [_sentence("y", ["F001"])],
                            "send_line": _sentence("Hi", kind="inference"),
                        }
                    ],
                )
            },
            "send_line outside contact openers",
        ),
        (
            {
                "do-not-mention": _section(
                    "do-not-mention",
                    intro=[_sentence("Do not raise his antidepressant use.", kind="inference")],
                )
            },
            "private matter",
        ),
    ],
)
def test_correctness_problems_are_reported(fill: dict[str, object], expected: str) -> None:
    errors = check_pages(_pages(["contact"], fill), ["contact"], TEXTS, set())
    assert any(expected in e for e in errors), errors


def test_company_benefit_programmes_are_not_private_matters() -> None:
    fill = {
        "why-this-person": _section(
            "why-this-person",
            intro=[_sentence("The careers page offers free therapy sessions to staff.", ["F001"])],
        )
    }
    assert check_pages(_pages(["contact"], fill), ["contact"], TEXTS, set()) == []


def test_missing_section_is_reported() -> None:
    result = _pages(["contact"])
    result["pages"][0]["sections"].pop()
    assert any("sections" in e for e in check_pages(result, ["contact"], TEXTS, set()))


def test_references_resolve_to_claim_ids_and_send_lines_survive() -> None:
    fill = {
        "openers": _section(
            "openers",
            items=[
                {
                    "h2": "Field teams",
                    "body": [_sentence("Hook.", ["F001", "A:F001"])],
                    "send_line": _sentence("Question?", kind="inference"),
                }
            ],
        )
    }
    drafts = to_drafts(_pages(["contact"], fill), {"F001": P1, "A:F001": C1})
    openers = next(s for s in drafts["contact"] if s.key == "openers")
    assert openers.items[0].body[0].claim_ids == (P1, C1)
    assert openers.items[0].send_line is not None
    assert openers.items[0].send_line.kind == "inference"


class _Model:
    def __init__(self, *replies: dict[str, object] | str) -> None:
        self.replies = [r if isinstance(r, str) else json.dumps(r) for r in replies]
        self.calls: list[list[Mapping[str, str]]] = []

    async def __call__(self, messages: Sequence[Mapping[str, str]], json_mode: bool) -> str:
        assert json_mode
        self.calls.append(list(messages))
        return self.replies.pop(0)


def test_one_repair_fixes_a_failed_check() -> None:
    async def scenario() -> None:
        bad = _pages(["contact"], {"angles": _section("angles", intro=[_sentence("x", ["F404"])])})
        good = _pages(["contact"])
        model = _Model(bad, good)
        written = await write_checked(
            model, "system", "user", lambda r: check_pages(r, ["contact"], TEXTS, set())
        )
        assert written.attempts == 2
        assert "unknown refs" in model.calls[1][-1]["content"]

    asyncio.run(scenario())


def test_two_failures_raise() -> None:
    async def scenario() -> None:
        bad = _pages(["contact"], {"angles": _section("angles", intro=[_sentence("x", ["F404"])])})
        with pytest.raises(PageWriterError, match="unknown refs"):
            await write_checked(
                _Model(bad, bad), "s", "u", lambda r: check_pages(r, ["contact"], TEXTS, set())
            )

    asyncio.run(scenario())


def test_malformed_json_gets_a_repair() -> None:
    async def scenario() -> None:
        model = _Model("not json", _pages(["contact"]))
        written = await write_checked(
            model, "s", "u", lambda r: check_pages(r, ["contact"], TEXTS, set())
        )
        assert written.attempts == 2

    asyncio.run(scenario())


def test_account_pages_cite_committee_findings_and_expose_the_story() -> None:
    async def scenario() -> None:
        person = Person(
            contact_id=CONTACT,
            name="Pat Doe",
            title="VP",
            suggested_role="champion",
            dossier=PERSON_DOSSIER,
        )
        fill = {
            "why-they-fit": _section(
                "why-they-fit",
                intro=[_sentence("The story.", ["F001", "P1:F001"])],
                items=[
                    {
                        "h2": "ICP check",
                        "body": [_sentence("US employer — met.", ["F001"])],
                        "contact_ids": [str(CONTACT)],
                    }
                ],
            )
        }
        model = _Model(_pages(["overview", "insights"], fill))
        written = await write_account_pages(
            model,
            seller_brief="Brief.",
            account_name="Acme",
            account_dossier=ACCOUNT_DOSSIER,
            people=[person],
        )
        fit = next(s for s in written.drafts["overview"] if s.key == "why-they-fit")
        assert fit.intro[0].claim_ids == (C1, P1)
        assert written.story == "The story."
        prompt = model.calls[0][1]["content"]
        assert "P1:F001" in prompt and "F002" not in prompt  # namesake withheld

    asyncio.run(scenario())


def test_contact_page_cites_account_findings_with_the_account_prefix() -> None:
    async def scenario() -> None:
        person = Person(
            contact_id=CONTACT,
            name="Pat Doe",
            title="VP",
            suggested_role=None,
            dossier=PERSON_DOSSIER,
        )
        fill = {
            "why-this-person": _section(
                "why-this-person", intro=[_sentence("Pat.", ["F001", "A:F001"])]
            )
        }
        written = await write_contact_page(
            _Model(_pages(["contact"], fill)),
            seller_brief="Brief.",
            account_name="Acme",
            account_story="Why Acme.",
            person=person,
            account_dossier=ACCOUNT_DOSSIER,
        )
        why = next(s for s in written.drafts["contact"] if s.key == "why-this-person")
        assert why.intro[0].claim_ids == (P1, C1)

    asyncio.run(scenario())


def test_contact_id_type_is_uuid() -> None:
    assert isinstance(CONTACT, UUID)


def test_structured_findings_render_as_their_words() -> None:
    dossier = {
        "document": {
            "sections": [
                {
                    "section": "Voice",
                    "findings": [
                        {
                            "id": "F001",
                            "topic": "Statement",
                            "finding": {"statement": "We keep A and B.", "context": "Interview"},
                        }
                    ],
                }
            ]
        }
    }
    rendered = render_findings(dossier)
    assert "We keep A and B." in rendered and "{" not in rendered
    assert "We keep A and B." in finding_texts(dossier)["F001"]
