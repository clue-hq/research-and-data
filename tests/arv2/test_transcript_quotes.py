"""The self-introduction check is gone: a transcript claim is no longer marked unsafe or demoted
because nobody said "I'm <name>" (founder rulings 2026-11-09)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from uuid import uuid4

from clue_api.arv2.claim_writer import ClaimDraft
from clue_api.arv2.display.evidence import resolve_evidence
from clue_api.arv2.media_claims import attach
from clue_api.arv2.quality_media import TranscriptSupport
from clue_api.footprint.media_types import Quality, Segment, TranscriptSource
from clue_core import EntityId, EntityType, ExtractionMethod, ResearchMode, new_run_id
from tests.arv2.display.test_evidence import _claim

TEXT = "Host: welcome. We were moving fast on zero trust."
SPEAKER = {"state": "answered", "label": "Speaker 1", "label_probabilities": {"Speaker 1": 0.9}}


def _person_runtime():
    contact = uuid4()
    return SimpleNamespace(scope=SimpleNamespace(subject_kind="person", contact_id=contact))


def _draft():
    return ClaimDraft(
        entity_id=EntityId(uuid.uuid4()),
        entity_type=EntityType.CONTACT,
        field_key="contact.facet.voice_quote",
        value_json="We were moving fast on zero trust.",
        extraction_method=ExtractionMethod.SCRAPE,
        run_id=new_run_id(),
        research_mode=ResearchMode.CONTACT_PROFILING,
        workspace_id="ws",
        source_url="https://example.com/ep",
        evidence_span="We were moving fast on zero trust.",
    )


def _saved():
    return {
        "text": TEXT,
        "segments": [
            Segment(start=0, end=15, speaker="Speaker 0"),
            Segment(start=15, end=len(TEXT), speaker="Speaker 1"),
        ],
        "quality": Quality(coverage="full").model_dump(mode="json"),
        "superseded": False,
        "quotes": [],
        "text_key": "k",
        "source_url": "https://example.com/ep",
    }


def test_transcript_claim_outreach_safe_without_introduction():
    source = TranscriptSource(version_ref=uuid4(), start=0, end=len(TEXT))
    out = attach(_draft(), source, _saved(), _person_runtime(), speaker=SPEAKER)
    assert out.outreach_safe is True
    assert out.markers["media"]["attribution"] == "unverified"
    assert out.markers["media"]["speaker_check"] == SPEAKER


def test_display_keeps_transcript_quote_as_quote():
    claim = _claim(
        source_key="research:transcript",
        write_markers={
            "quality_required": True,
            "claim_kind": "observation",
            "media": {"attribution": "unverified", "version_ref": str(uuid4())},
        },
    )
    ref = resolve_evidence([claim])[0]
    assert ref.source_kind == "primary_quote" and ref.quote == "We buy tools that show us the buyer"


def test_no_introduction_field():
    assert "introduction" not in TranscriptSupport.model_fields
    import clue_api.arv2.quality_media as quality_media

    assert not hasattr(quality_media, "SpeakerIntroduction")


def test_only_recipes_2_to_5_fail_to_resolve():
    from clue_api.quality_research_wiring import quality_profiles, quality_tools

    tools = quality_tools(None, None, purge=False)
    failing = set()
    for version in range(1, 44):
        for person in (False, True):
            try:
                quality_profiles(tools, version=version, person=person)
            except Exception:
                failing.add(version)
    assert failing == {2, 3, 4, 5}
