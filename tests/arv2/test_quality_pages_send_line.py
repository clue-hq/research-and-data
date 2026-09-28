"""A contact page's opener must serialize to exactly the served ``ResearchSendLine`` shape.

The owned narrative's opener is a ``CitedSentence`` (``text``, ``claimIds``, ``kind``,
``qualifications``). The served ``sendLine`` allows only ``channel``, ``text`` and ``claimIds``,
and the frontend read validates every stored block strictly, so an opener dumped whole made every
researched contact page fail to load (found live 2026-09-29).
"""

from __future__ import annotations

from uuid import uuid4

from clue_api.arv2.quality_pages import CitedItem, CitedSentence, PageSectionDraft, _body
from clue_api.frontend_read.contract_v1 import ResearchItem


def test_a_contact_opener_serializes_to_the_served_send_line_shape() -> None:
    claim_id = uuid4()
    section = PageSectionDraft(
        key="openers",
        items=(
            CitedItem(
                h2="Referral leakage",
                body=(CitedSentence(text="They map referral leakage.", claimIds=(claim_id,)),),
                send_line=CitedSentence(
                    text="Saw your referral-leakage report for South Denver GI.",
                    claimIds=(claim_id,),
                    kind="fact",
                    qualifications=("as published on their site",),
                ),
            ),
        ),
    )

    body = _body(section, people={}, gaps=(), account_id=uuid4())

    item = body["items"][0]
    assert item["sendLine"] == {
        "channel": "email",
        "text": "Saw your referral-leakage report for South Denver GI.",
        "claimIds": [str(claim_id)],
    }
    # The strict served model accepts it (this raised extra_forbidden before the fix).
    served = ResearchItem.model_validate(item)
    assert served.send_line is not None
    assert served.send_line.text.startswith("Saw your referral-leakage report")


def test_read_time_annotation_never_adds_fields_to_the_opener() -> None:
    """Advisory annotation qualifies body sentences; the opener's served shape has no such field."""
    from clue_api.arv2.quality_presentation import annotate_sentences

    claim_id = str(uuid4())
    body = {
        "intro": [],
        "items": [
            {
                "id": "openers-0",
                "h2": "Referral leakage",
                "body": [{"text": "They map referral leakage.", "claimIds": [claim_id]}],
                "sendLine": {
                    "channel": "email",
                    "text": "Saw your report.",
                    "claimIds": [claim_id],
                },
                "contactRefs": [],
                "priority": 2,
                "newSinceLastVisit": False,
            }
        ],
    }
    annotate_sentences(body, {claim_id: {"quality": "qualified"}})

    item = body["items"][0]
    assert item["body"][0]["kind"] == "qualified"  # body sentences are still annotated
    assert item["sendLine"] == {
        "channel": "email",
        "text": "Saw your report.",
        "claimIds": [claim_id],
    }
    ResearchItem.model_validate(item)
