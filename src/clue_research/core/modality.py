"""The modality-adapter contract — ``fetch → adapt → extract`` (M0.2, alongside ``Resolver``).

A source isn't always "fetch a URL and read text" (staged-flow §7b): video/podcasts need
transcription, PDFs/journals text extraction, structured payloads parsing — *before* claim
extraction. This module defines the **three-stage, independently-swappable** contract that makes
that heterogeneity *open by registration* (like the field registry): adding "anything on the
internet" is registering a manifest (M4.2) + (if non-trivial) an adapter — never a pipeline fork
(the fork the architecture forbids).

The protocol + its value types live here in ``core`` (the shared-contracts package — the *modality*
analogue of :class:`~clue_research.core.resolver.Resolver`) so the dispatch framework
(M4.3, :mod:`clue_research.adapters`), a resolver that needs adaptation (M4.5 Firecrawl), and a
deep-pass worker (M8) all import one shape and never re-implement it. The concrete adapters, the
provider seams (``Transcriber`` / PDF extractor / scrape backend), and ``run_pipeline`` live in
:mod:`clue_research.adapters` — ``core`` imports none of them (the M0.1 kernel rule).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from clue_research.core.entity import Entity
from clue_research.core.enums import Modality, UseClass
from clue_research.core.field import FieldDef, FieldKey
from clue_research.core.primitives import Confidence, UtcDatetime


class RawArtifact(BaseModel):
    """The bytes a source's *transport* (``fetch``) returns, before any normalization.

    Modality-agnostic: a PDF's bytes, an audio file, an HTML/markdown page, a structured payload.
    ``content`` is always raw bytes (text is UTF-8 encoded) so one shape carries every modality;
    ``adapt`` turns it into :class:`NormalizedText`. ``metadata`` carries fetch facts (HTTP status,
    content length, media duration) the cost/observability surfaces read.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: str  # the reference fetched (URL / URI / path / inline id)
    media_type: str  # "application/pdf" | "text/html" | "text/markdown" | "audio/mpeg" | ...
    content: bytes
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    def text(self, encoding: str = "utf-8") -> str:
        """Decode ``content`` as text (for text/markdown/structured passthrough)."""
        return self.content.decode(encoding)


class NormalizedText(BaseModel):
    """The normalized text a source's *normalization* (``adapt``) returns — the surface claim
    extraction reads, and the source of every ``evidence_span`` (substrate §4).

    ``metadata`` carries normalization facts (page count, transcript duration/language) for the cost
    surface and the learning loop — e.g. ``{"pages": 12}`` or ``{"duration_seconds": 5400}``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    media_type: str = "text/plain"
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ClaimDraft(BaseModel):
    """A pre-write claim the *extraction* (``extract``) stage emits: a value plus the **exact
    evidence span** it was drawn from.

    It deliberately carries **no** ``source_tier`` / ``extraction_method`` / ``source_key``:
    adaptation never upgrades trust, so ``run_pipeline`` stamps those from the source's *manifest*,
    not the extractor (a transcribed-podcast claim stays its manifest tier, never tier-1). The
    ``evidence_span`` is **required and non-empty** — the draft is where the substrate §4 / M1.1
    span rule is satisfied, so a span-less "fact" cannot even be drafted.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: FieldKey
    value: JsonValue
    evidence_span: str  # the exact normalized text the value came from (REQUIRED, non-empty)
    confidence: Confidence
    source_url: str | None = None
    observed_at: UtcDatetime | None = None
    # Set by the extractor for a personal (``contact.facet.*``) claim — its use-class (Doc D §2).
    # identity_binding is stamped from the manifest (authoritative), like the M4.1 waterfall does.
    use_class: UseClass | None = None

    @field_validator("evidence_span")
    @classmethod
    def _span_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ClaimDraft.evidence_span must be non-empty (substrate §4 span rule)")
        return value


class AdaptContext(BaseModel):
    """The minimal context the dispatch framework hands an adapter's ``fetch`` / ``adapt``.

    It carries the source's identity, a credential *reference* (never the secret), the
    freshness profile, and free-form fetch params — but **not** the registry row, so ``core`` need
    not import ``sources``. ``run_pipeline`` (M4.3) builds it from the source's manifest.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str
    auth_ref: str | None = None  # a credential-store reference (e.g. "CLUE_FIRECRAWL_API_KEY")
    freshness_profile: str | None = None
    params: dict[str, JsonValue] = Field(default_factory=dict)


class GateDecision(StrEnum):
    """The expensive-modality gate verdict — a *shared* producer→consumer contract.

    The **Source Planner (M4.6)** / a deep-pass worker (M8) / the budget engine (M7) *decide*
    whether an expensive ``fetch → adapt → extract`` run (transcribe a 90-min podcast, OCR a filing)
    is worth it — gated to high-tier entities and high-weighted source classes (staged-flow §7d).
    M4.3's pipeline (:func:`clue_research.adapters.run_pipeline`) only *honors* the verdict: on
    ``SKIP`` it incurs no fetch/transcription and returns no claims.

    It lives in ``core`` (not ``adapters``) because both the producer (the planner, in
    ``clue_research.sources``) and the consumer (``clue_research.adapters``) bind to one shape — the
    shared-type rule (conventions §2). ``clue_research.adapters.GateDecision`` re-exports it, so a
    caller may import it from either seam and ``run_pipeline``'s identity check still holds.
    """

    RUN = "run"  # proceed with fetch → adapt → extract
    SKIP = "skip"  # do NOT incur the costly fetch/transcription (low tier / low-weighted source)


@runtime_checkable
class ModalityAdapter(Protocol):
    """The three-stage, independently-swappable source contract (staged-flow §7b).

    ``fetch`` (transport) → ``adapt`` (transcribe / OCR-extract / parse) → ``extract`` (claim
    extraction). Each stage is a separate seam, so swapping the transcription provider, the
    PDF extractor, or the HTML→markdown backend is a config/registration change behind
    ``run_pipeline`` — and because ``extract`` yields :class:`ClaimDraft`s with an ``evidence_span``
    while ``run_pipeline`` stamps the manifest's tier, the claim contract is identical across
    modalities ("a new modality is just another source"). ``@runtime_checkable`` lets the adapter
    registry assert conformance structurally; mypy checks the full signatures.
    """

    modality: Modality

    def fetch(self, ref: str, ctx: AdaptContext) -> RawArtifact: ...

    def adapt(self, artifact: RawArtifact, ctx: AdaptContext) -> NormalizedText: ...

    def extract(
        self, normalized: NormalizedText, entity: Entity, field: FieldDef
    ) -> list[ClaimDraft]: ...


if TYPE_CHECKING:
    # --- static conformance contract (checked by `make typecheck`, not run) ---
    # Positive: a minimal structural adapter MUST satisfy the protocol.
    class _ExampleAdapter:
        modality: Modality = Modality.TEXT

        def fetch(self, ref: str, ctx: AdaptContext) -> RawArtifact:
            return RawArtifact(ref=ref, media_type="text/plain", content=b"")

        def adapt(self, artifact: RawArtifact, ctx: AdaptContext) -> NormalizedText:
            return NormalizedText(text=artifact.text())

        def extract(
            self, normalized: NormalizedText, entity: Entity, field: FieldDef
        ) -> list[ClaimDraft]:
            return []

    _conforms: ModalityAdapter = _ExampleAdapter()

    # Negative: a class missing `modality` MUST be rejected by the type-checker. With mypy's
    # `warn_unused_ignores` (strict) this *fails the build* unless the ignore actually triggers —
    # i.e. it self-verifies that the protocol bites.
    class _MissingModality:
        def fetch(self, ref: str, ctx: AdaptContext) -> RawArtifact:
            return RawArtifact(ref=ref, media_type="text/plain", content=b"")

        def adapt(self, artifact: RawArtifact, ctx: AdaptContext) -> NormalizedText:
            return NormalizedText(text="")

        def extract(
            self, normalized: NormalizedText, entity: Entity, field: FieldDef
        ) -> list[ClaimDraft]:
            return []

    _rejected: ModalityAdapter = _MissingModality()  # type: ignore[assignment]
