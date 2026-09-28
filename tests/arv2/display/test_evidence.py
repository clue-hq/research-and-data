"""D2 T5 exit gate: the evidence resolver — decision 8, pure and offline.

Nothing here touches the database, a provider, or a clock: an :class:`EvidenceRef` is one stored
claim's own provenance re-shaped for the source drawer, so every rule it encodes — the folded
domain, the ``record`` kind an API claim with no url carries, the excerpt that appears *only* when
there is no quote — has to hold on a claim built by hand.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from clue_api.arv2.display.evidence import (
    EvidenceRef,
    favicon_url,
    resolve_evidence,
    source_domain,
)
from clue_core import (
    Claim,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    UseClass,
    new_claim_id,
    new_run_id,
)

WIRE_KEYS = {
    "claimId",
    "sourceUrl",
    "sourceDomain",
    "faviconUrl",
    "title",
    "quote",
    "publishedAt",
    "verifiedAt",
    "verificationKind",
    "mediaTimestamp",
    "provider",
    "outreachSafe",
}


def _claim(**overrides: Any) -> Claim:
    """One contact-facet claim, with everything the display layer reads set to a real value."""
    fields: dict[str, Any] = {
        "id": new_claim_id(),
        "entity_id": EntityId(uuid.uuid4()),
        "entity_type": EntityType.CONTACT,
        "field_key": "contact.facet.voice_quote",
        "value_json": "We buy tools that show us the buyer",
        "source_url": "https://www.YouTube.com/watch?v=1",
        "source_key": "youtube_transcript",
        "source_tier": 2,
        "extraction_method": ExtractionMethod.SCRAPE,
        "evidence_span": "We buy tools that show us the buyer",
        "confidence": 0.9,
        "observed_at": datetime(2026, 6, 17, 9, 30, tzinfo=UTC),
        "collected_at": datetime(2026, 9, 2, 11, 0, tzinfo=UTC),
        "run_id": new_run_id(),
        "research_mode": ResearchMode.CONTACT_PROFILING,
        "identity_binding": IdentityBinding.STRONG,
        "use_class": UseClass.PROFESSIONAL_PUBLIC,
    }
    fields.update(overrides)
    return Claim(**fields)


def test_the_domain_is_the_host_lowercased_with_www_folded_away() -> None:
    assert source_domain("https://www.YouTube.com/watch?v=1") == "youtube.com"
    assert source_domain("https://zafran.io/newsroom") == "zafran.io"
    assert source_domain("HTTPS://WWW.Zafran.IO") == "zafran.io"
    assert source_domain(None) is None
    assert source_domain("") is None
    assert source_domain("not a url at all") is None


def test_a_favicon_exists_only_when_a_domain_does() -> None:
    assert favicon_url("youtube.com") == (
        "https://www.google.com/s2/favicons?domain=youtube.com&sz=32"
    )
    assert favicon_url(None) is None
    assert favicon_url("") is None


def test_an_api_claim_with_no_url_is_a_record_not_a_verified_source() -> None:
    ref = resolve_evidence(
        [
            _claim(
                extraction_method=ExtractionMethod.API,
                source_tier=1,
                source_url=None,
                source_key="pdl",
            )
        ]
    )[0]
    assert ref.source_url is None
    assert ref.source_domain is None
    assert ref.favicon_url is None
    assert ref.verification_kind == "record"
    assert ref.provider == "pdl"
    wire = ref.to_wire()
    assert wire["sourceUrl"] is None
    assert wire["faviconUrl"] is None
    assert wire["verificationKind"] == "record"


def test_a_scraped_claim_with_a_url_is_verified() -> None:
    ref = resolve_evidence([_claim()])[0]
    assert ref.verification_kind == "verified"
    assert ref.source_domain == "youtube.com"
    assert ref.favicon_url is not None


def test_an_api_claim_that_kept_its_url_is_still_verified() -> None:
    """``record`` is "no source to show", not "an API said so" — the url is what decides."""
    ref = resolve_evidence(
        [
            _claim(
                extraction_method=ExtractionMethod.API,
                source_tier=1,
                source_url="https://api.pdl.com/person/1",
            )
        ]
    )[0]
    assert ref.verification_kind == "verified"


def test_the_media_wrap_keeps_the_span_as_the_quote_and_carries_its_timestamp() -> None:
    ref = resolve_evidence(
        [
            _claim(
                value_json={
                    "text": "We buy tools that show us the buyer",
                    "media_url": "https://youtu.be/zafran",
                    "media_timestamp": "12:04",
                }
            )
        ]
    )[0]
    assert ref.quote == "We buy tools that show us the buyer"
    assert ref.media_timestamp == "12:04"
    assert ref.research_excerpt is None
    assert "researchExcerpt" not in ref.to_wire()
    assert ref.to_wire()["mediaTimestamp"] == "12:04"


def test_a_claim_with_no_span_falls_back_to_a_rendered_excerpt() -> None:
    ref = resolve_evidence(
        [_claim(evidence_span=None, value_json={"round": "Series B", "amount_usd": 30000000})]
    )[0]
    assert ref.quote is None
    assert ref.research_excerpt == "amount_usd: 30000000; round: Series B"
    assert ref.to_wire()["researchExcerpt"] == "amount_usd: 30000000; round: Series B"
    assert set(ref.to_wire()) == WIRE_KEYS | {"researchExcerpt"}


def test_verified_at_is_the_observation_date_and_falls_back_to_collection() -> None:
    assert resolve_evidence([_claim()])[0].verified_at == "2026-06-17"
    assert resolve_evidence([_claim(observed_at=None)])[0].verified_at == "2026-09-02"


def test_published_at_is_read_from_the_value_when_it_parses_as_a_date() -> None:
    published = resolve_evidence([_claim(value_json={"published": "2026-06-17"})])[0]
    assert published.published_at == "2026-06-17"
    dated = resolve_evidence([_claim(value_json={"date": "2026-06-17T09:30:00Z"})])[0]
    assert dated.published_at == "2026-06-17"
    assert (
        resolve_evidence([_claim(value_json={"published": "last summer"})])[0].published_at is None
    )
    assert resolve_evidence([_claim(value_json="a plain string")])[0].published_at is None
    assert resolve_evidence([_claim()])[0].published_at is None


def test_a_title_is_read_from_the_value_under_any_of_its_three_names() -> None:
    for key in ("title", "source_title", "page_title"):
        ref = resolve_evidence([_claim(value_json={key: "Zafran raises $30M"})])[0]
        assert ref.title == "Zafran raises $30M"
    assert resolve_evidence([_claim(value_json={"title": ""})])[0].title is None
    assert resolve_evidence([_claim(value_json={"title": 7})])[0].title is None
    assert resolve_evidence([_claim(value_json=["a", "list"])])[0].title is None


def test_the_wire_shape_is_exactly_the_contract_keys() -> None:
    ref = resolve_evidence([_claim()])[0]
    wire = ref.to_wire()
    assert set(wire) == WIRE_KEYS  # no researchExcerpt: this claim has a quote
    assert wire["claimId"] == ref.claim_id
    assert wire["outreachSafe"] is True
    assert wire["provider"] == "youtube_transcript"


def test_an_unsafe_claim_carries_its_flag_rather_than_disappearing() -> None:
    ref = resolve_evidence([_claim(outreach_safe=False)])[0]
    assert ref.outreach_safe is False
    assert ref.to_wire()["outreachSafe"] is False


def test_refs_come_back_one_per_claim_ordered_by_claim_id() -> None:
    claims = [_claim() for _ in range(5)]
    refs = resolve_evidence(claims)
    assert len(refs) == 5
    assert [ref.claim_id for ref in refs] == sorted(str(claim.id) for claim in claims)
    assert all(isinstance(ref, EvidenceRef) for ref in refs)
    assert resolve_evidence([]) == []


def test_quality_report_excerpt_never_becomes_primary_quote():
    ref = resolve_evidence(
        [
            _claim(
                source_key="research:research_report",
                write_markers={
                    "quality_required": True,
                    "claim_kind": "observation",
                    "qualifications": ["Provider report; primary page not inspected"],
                },
            )
        ]
    )[0]
    assert ref.quote is None
    assert ref.source_excerpt == "We buy tools that show us the buyer"
    assert ref.source_kind == "source_excerpt"
    assert ref.qualifications == ("Provider report; primary page not inspected",)


def test_quality_value_argument_exposes_both_support_sides():
    ref = resolve_evidence(
        [
            _claim(
                source_key="research:inference",
                evidence_span=None,
                write_markers={
                    "quality_required": True,
                    "claim_kind": "inference",
                    "support": [
                        {"kind": "claims", "claim_ids": ["target-claim"]},
                        {
                            "kind": "seller_document",
                            "document_id": "seller-doc",
                            "sha256": "a" * 64,
                            "start": 0,
                            "end": 25,
                            "quote": "Automates referral intake",
                        },
                    ],
                },
            )
        ]
    )[0]
    assert ref.quote is None
    assert ref.source_kind == "inference"
    assert ref.supporting_claim_ids == ("target-claim",)
    assert ref.to_wire()["sellerPassages"][0]["quote"] == "Automates referral intake"
