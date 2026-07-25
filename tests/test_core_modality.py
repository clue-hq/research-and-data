"""M4.3 acceptance (core contract): the ModalityAdapter protocol + its value types (M0.2).

DB-free. The three-stage protocol is checkable; ``ClaimDraft`` enforces the substrate §4
span rule (non-empty evidence span) at construction so a span-less "fact" cannot even be drafted.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_core import (
    AdaptContext,
    ClaimDraft,
    Modality,
    ModalityAdapter,
    NormalizedText,
    RawArtifact,
    UseClass,
)


class _Adapter:
    modality = Modality.TEXT

    def fetch(self, ref: str, ctx: AdaptContext) -> RawArtifact:
        return RawArtifact(ref=ref, media_type="text/plain", content=ref.encode())

    def adapt(self, artifact: RawArtifact, ctx: AdaptContext) -> NormalizedText:
        return NormalizedText(text=artifact.text())


def test_modality_adapter_is_runtime_checkable() -> None:
    assert isinstance(_Adapter(), ModalityAdapter)

    class _NoModality:
        def fetch(self, ref: str, ctx: AdaptContext) -> RawArtifact:
            return RawArtifact(ref=ref, media_type="text/plain", content=b"")

        def adapt(self, artifact: RawArtifact, ctx: AdaptContext) -> NormalizedText:
            return NormalizedText(text="")

    # missing the `modality` data member -> not structurally an adapter
    assert not isinstance(_NoModality(), ModalityAdapter)


def test_raw_artifact_round_trips_text() -> None:
    art = RawArtifact(ref="inline", media_type="text/plain", content="héllo".encode())
    assert art.text() == "héllo"


def test_claim_draft_requires_non_empty_evidence_span() -> None:
    # a value with a real span is fine
    draft = ClaimDraft(
        field_key="account.operational_pain",
        value="legacy ETL",
        evidence_span="legacy ETL pain",
        confidence=0.7,
    )
    assert draft.evidence_span == "legacy ETL pain"
    # an empty / whitespace span is rejected at construction (substrate §4)
    with pytest.raises(ValidationError, match="evidence_span must be non-empty"):
        ClaimDraft(
            field_key="account.operational_pain", value="x", evidence_span="   ", confidence=0.5
        )


def test_claim_draft_carries_use_class_for_personal_data() -> None:
    draft = ClaimDraft(
        field_key="contact.facet.recent_post",
        value="spoke at KubeCon",
        evidence_span="spoke at KubeCon",
        confidence=0.6,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
    )
    assert draft.use_class is UseClass.PROFESSIONAL_PUBLIC


def test_adapt_context_carries_a_reference_not_a_secret() -> None:
    ctx = AdaptContext(source_key="firecrawl_site", auth_ref="CLUE_FIRECRAWL_API_KEY")
    # auth_ref is a reference (env-var name), never a secret value
    assert ctx.auth_ref == "CLUE_FIRECRAWL_API_KEY"
    assert ctx.params == {}


def test_example_adapter_fetch_adapt_pipeline() -> None:
    # exercises the normalizer's two stages (the M8/M4.5 call shape); extraction is a separate
    # per-call ClaimExtractor seam, not a method on the adapter.
    adapter = _Adapter()
    art = adapter.fetch("some text", AdaptContext(source_key="x"))
    normalized = adapter.adapt(art, AdaptContext(source_key="x"))
    assert normalized.text == "some text"
