"""Design job envelopes (Part II slice D5) — the frozen, by-value work descriptions.

One design job = one envelope. The envelope is captured when the work is *enqueued* and never
edited afterwards, so a worker that takes the job over after a restart replays the same unit of
work rather than re-reading state that has since moved. This is the ``entity_research_job``
authority-envelope discipline (M8D R2) applied to the design subsystem: the fleet carries ONE
mechanical kind (``design_job``) and the envelope alone says which shape of work it is.

Four discriminants, one tagged union on ``kind``:

* ``agent_turn`` / ``web_turn`` → :class:`DesignTurnEnvelope` (one design-agent turn; the two
  differ by which runtime harness executes them, which is why ``kind`` mirrors
  ``clue_design.enums.DesignRunKind`` rather than collapsing to a single tag).
* ``ingestion`` → :class:`DesignIngestionEnvelope` (one brand-kit ingestion job).
* ``asset_analysis`` → :class:`AssetAnalysisEnvelope` (one image, bound to its parent generation).

**Purity (Rule S4).** This module imports only pydantic, the stdlib, and this package's own
enums — deliberately NOT ``clue_fleet``. The design substrate may not learn the queue exists;
translating an envelope into a fleet task (and back) is the composition root's job, in the
handler that Round B adds. That is also why ``work_id`` is a plain ``UUID`` here and not the
fleet's ``WorkId`` newtype.

**``config`` is opaque on purpose.** A turn's by-value context is a large, fast-moving bag
(brand kit, fonts spec, resolved reference assets, account card, asset library, target node ids,
model selection, base version, …) owned by the design runtime's own request models. Schema-ing
every key here would fork those models and make every runtime change a substrate migration. The
envelope validates what the *platform* must be able to trust — the tenancy anchor, the
discriminant, the identifiers — and carries the rest verbatim as a JSON object.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from clue_design.enums import DesignIngestionKind

#: The opaque by-value payload every envelope carries (a JSON object, never a bare scalar).
type ConfigPayload = dict[str, Any]


class _DesignEnvelopeBase(BaseModel):
    """Shared, always-validated head of every design envelope.

    Frozen (``frozen=True``) because the envelope is the immutable authority for the job, and
    ``extra="forbid"`` so a caller cannot smuggle a field past the contract by misspelling it —
    unstructured context belongs in ``config``, which is explicitly opaque.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The fleet work id this envelope is dispatched under. Stored on the design row too, so the
    #: envelope and the row can always be re-joined without trusting the queue.
    work_id: UUID
    #: The tenancy anchor. Required and non-empty on EVERY envelope: a design job with no
    #: workspace is unexecutable, and the D2.5A seam refuses work it cannot scope.
    workspace_id: str = Field(min_length=1)
    #: The by-value context the worker executes from (see the module docstring).
    config: ConfigPayload = Field(default_factory=dict)


class DesignTurnEnvelope(_DesignEnvelopeBase):
    """One design-agent turn — the ``agent_turn`` (scene) and ``web_turn`` (web) shapes.

    ``checkpoint_thread_id`` is the LangGraph thread the turn runs on and, per the D5 ruling,
    equals ``run_id``: the design run IS the checkpoint thread, so a resumed turn resumes the
    same graph instead of starting a second one beside it.
    """

    kind: Literal["agent_turn", "web_turn"]
    run_id: str = Field(min_length=1)
    checkpoint_thread_id: str = Field(min_length=1)
    #: The platform project this turn's spend belongs to, when the offerer has one (lane 3
    #: slice 5). Additive and optional because the model is ``extra="forbid"`` — a frozen
    #: pre-slice-5 envelope replays unchanged and stamps its ledger rows with the workspace
    #: alone. The design runtime itself never reads it: it is carried for the drain's
    #: ``LedgerStamp``, so a design turn's money joins the project it was spent for.
    project_id: str | None = None
    #: The document the turn edits, when it names one. Nullable for the same reason the column
    #: is: the shipped async-turn route legitimately carries a document id that is not stored.
    document_id: str | None = None


class DesignIngestionEnvelope(_DesignEnvelopeBase):
    """One brand-kit ingestion job (website / pdf / asset upload).

    Ingestion has no LangGraph thread — it is a pipeline, not an agent turn — so it carries the
    job id and the input kind instead. Its staged inputs live in ``design_ingestion_job.
    request_json`` as platform-storage digests (D4), which is what makes a requeued job able to
    re-read the same bytes.
    """

    kind: Literal["ingestion"]
    job_id: str = Field(min_length=1)
    ingestion_kind: DesignIngestionKind


class AssetAnalysisEnvelope(_DesignEnvelopeBase):
    """One image, fenced by both its own fleet lease and its parent ingestion."""

    kind: Literal["asset_analysis"] = "asset_analysis"
    job_id: str = Field(min_length=1)
    parent_generation: int = Field(ge=1)
    asset_id: str = Field(min_length=1)
    target: ConfigPayload


#: The tagged union a design fleet task carries. Round B's handler parses the stored envelope
#: through this alias and dispatches on the validated model, never on a raw dict lookup.
type DesignJobEnvelope = Annotated[
    DesignTurnEnvelope | DesignIngestionEnvelope | AssetAnalysisEnvelope,
    Field(discriminator="kind"),
]

__all__ = [
    "ConfigPayload",
    "AssetAnalysisEnvelope",
    "DesignIngestionEnvelope",
    "DesignJobEnvelope",
    "DesignTurnEnvelope",
]
