"""Typed inputs/outputs for the Stage-0 front edge (M5).

Frozen value types the reverse-profiling pipeline (M5.1) exchanges with its callers. Kept separate
from the orchestration so the API/contract is legible on its own (the FastAPI surface and the M7
phase handler both speak these shapes). Everything keys on a resolved
:class:`~clue_research.core.primitives.EntityId`, never a free-text name (conventions §2): the
client *input* is a name+website, but the *output* reference is the resolved client entity id.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, JsonValue

from clue_research.core import CostCents, EntityId, RunId
from clue_research.stage0.fields import SurfaceClass

# --- input ------------------------------------------------------------------


class VolunteeredMaterial(BaseModel):
    """A piece of client-volunteered material (a deck, customer list, target description, …).

    Treated as **high-trust input that accelerates derivation, never a precondition** (Doc B §1):
    the facts it asserts (``asserted_fields``: ``client.*`` field_key → value) are written as
    tier-1 ``human`` claims that shortcut the waterfall. ``content`` is the raw excerpt, used as
    the claim's ``evidence_span`` so a volunteered fact is still provenance-backed. Pulling
    structured facts out of free-form prose (an LLM extraction pass) sits behind this contract —
    the caller (or a later extractor) supplies ``asserted_fields``; the no-materials path is fully
    supported (empty list).

    NOTE (scope): the substrate §8 *chunk → embed into pgvector → retrieve* ingestion of raw
    ``content`` is a registered seam, **deferred** — it needs a client-knowledge chunk store
    (a table), and Beat-0 assigns M5 no new tables. The value-bearing output (typed high-trust
    claims) is what downstream consumes; the embedding-retrieval layer can be added behind this
    type without changing it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str = "document"  # deck | customer_list | target_description | exclusions | document
    label: str | None = None  # a human label / filename for provenance
    content: str | None = None  # raw excerpt, used as evidence_span for asserted facts
    asserted_fields: dict[str, JsonValue] = {}  # client.* field_key -> high-trust value


class ClientInput(BaseModel):
    """The minimum-input contract (Doc B §1): worst case just ``name`` + ``website``. Anything else
    the client volunteers rides along in ``materials`` and accelerates — never gates — the run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    website: str
    materials: tuple[VolunteeredMaterial, ...] = ()


# --- output -----------------------------------------------------------------


class ClientKnowledgeBaseRef(BaseModel):
    """The handle to a versioned Client Knowledge Base (M5.1). The base is *just claims* in the
    shared store keyed on the resolved client entity at a ``client_kb_version``; readers (M5.2 ICP
    synthesis, M12 positioning) consume ``current_value(client_entity, field)`` and may pin to a
    version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_entity_id: EntityId
    client_kb_version: int


class SurfaceCoverage(BaseModel):
    """Per-surface-class coverage of one reverse-profiling run (Doc B §2 surfaces)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    surface_class: SurfaceClass
    attempted: bool
    filled_fields: tuple[str, ...] = ()
    empty_fields: tuple[str, ...] = ()


class CoverageReport(BaseModel):
    """A completeness read on the Client Knowledge Base (Doc C §7 spirit, applied to the client):
    which field classes are filled vs empty, so a thin profile is *visible* (the quality ceiling is
    legible)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    filled_fields: tuple[str, ...] = ()
    empty_fields: tuple[str, ...] = ()
    surfaces: tuple[SurfaceCoverage, ...] = ()

    @property
    def filled_count(self) -> int:
        return len(self.filled_fields)

    @property
    def total_count(self) -> int:
        return len(self.filled_fields) + len(self.empty_fields)


class ReverseProfileResult(BaseModel):
    """The full result of a reverse-profiling run: the versioned base reference, the run id that
    produced it, the coverage read, the spend, and whether the per-client budget cap halted it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: ClientKnowledgeBaseRef
    run_id: RunId
    coverage: CoverageReport
    cost_cents: CostCents = Decimal(0)
    fields_resolved: int = 0  # fields that gained a claim this run (materials + waterfall)
    budget_exhausted: bool = False
