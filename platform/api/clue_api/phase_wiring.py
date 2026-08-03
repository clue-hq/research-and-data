"""Api-root registration surfaces for the M5/M6 project-run phases (PB-B4 slice 1, D3).

The M5 (Stage-0) and M6 (discovery/scoring/tiering) phase handlers *implement* the frozen
``core.PhaseHandler`` protocol but — like every phase body — are constructed and registered at the
``api`` composition root (``durable`` never imports a handler; the state machine dispatches by the
declared ``phase``). Until B4, only DEEP/VERIFICATION/HANDOFF/REVIEW had api-root
``build_*``/``register_*`` surfaces; the five setup/discovery phases did not, so a detached worker
could not drive a run past them (CLAUDE.md ``[B4×fleet]`` / ``[B2×stage0/M6]``). This module adds
them, mirroring the verification/handoff/deep wiring style:

* ``build_*`` — construct the handler, every collaborator defaulting to its production concrete.
* ``register_*`` — build it and register it (into the process-default registry, or an injected
  ``register`` — a per-run ``PhaseHandlerRegistry.register`` for the :class:`ComposingRunDriver`),
  **snapshot-wrapped** when a ``storage`` backend is passed.

**Born snapshot-wrapped (D3, ``[B2×stage0/M6]``).** ``storage`` is a *required keyword* on every
``register_*`` (same posture as ``register_deep_phase_handler`` /
``register_retention_sweeping_handoff_handler``): passing ``build_storage_backend()`` registers the
handler wrapped in the phase-generic :class:`~clue_api.storage_wiring.SnapshotBindingPhaseHandler`
so its ``run`` executes inside the run's ambient snapshot sink (the sink-less tier-2 scrape resolver
captures into it, the waterfall flushes from it); ``None`` registers it unwrapped (the pre-B2 path).
Forgetting the argument is a ``TypeError``, never a silent no-snapshot registration.

Which phases *actually fetch* (so the wrapper is load-bearing vs merely uniform):

* ``REVERSE_PROFILING`` — **fetches** (the client-KB waterfall + scrape). Wrapper load-bearing.
* ``ICP_CONFIRMED`` — pure reads (read the pinned spec → compile the field plan → estimate). Wrapper
  harmless (no capture happens), kept for uniformity.
* ``DISCOVERY`` — **fetches** (the grounded discovery channels). Wrapper load-bearing.
* ``SCORING`` — **fetches** (the Pass-A tier-1–3 scoring waterfall). Wrapper load-bearing.
* ``TIER_CHECKPOINT`` — pure reads/tiering (tier the stored scores, estimate, present the gate).
  Wrapper harmless, kept for uniformity.
"""

from __future__ import annotations

from collections.abc import Callable

from clue_api.composition import build_pre_spend_gate
from clue_api.discovery_seal import DurableDiscoveryPhaseHandler
from clue_api.storage_wiring import SnapshotBindingPhaseHandler
from clue_core import (
    FaithfulnessJudge,
    LLMGateway,
    PhaseHandler,
    PreSpendGate,
    SealedDiscoveryAccountReader,
)
from clue_db import ConnFactory, transaction
from clue_research.discovery_scoring.discovery import ChannelRegistry
from clue_research.discovery_scoring.phases import (
    DiscoveryPhaseHandler,
    ScoringPhaseHandler,
    TierCheckpointPhaseHandler,
)
from clue_research.durable import register_phase_handler
from clue_research.stage0.icp_estimate import EstimateInputs
from clue_research.stage0.icp_handler import IcpConfirmedHandler
from clue_research.stage0.reverse_profiling_handler import ReverseProfilingHandler
from clue_storage import StorageBackend

__all__ = [
    "build_reverse_profiling_handler",
    "register_reverse_profiling_handler",
    "build_icp_confirmed_handler",
    "register_icp_confirmed_handler",
    "build_discovery_handler",
    "register_discovery_handler",
    "build_scoring_handler",
    "register_scoring_handler",
    "build_tier_checkpoint_handler",
    "register_tier_checkpoint_handler",
    "snapshot_bound",
]

_Register = Callable[[PhaseHandler], None]


def snapshot_bound(handler: PhaseHandler, *, storage: StorageBackend | None) -> PhaseHandler:
    """Wrap ``handler`` in the per-run snapshot binding when a ``storage`` backend is supplied, else
    return it unwrapped. The wrapper is a transparent ``core.PhaseHandler`` for the same phase
    (last-write-wins), so the state machine sees no difference — it only makes the run's ambient
    snapshot sink live around the phase (the fetching phases capture into it)."""
    return (
        SnapshotBindingPhaseHandler(inner=handler, storage=storage)
        if storage is not None
        else handler
    )


# --- REVERSE_PROFILING (M5.1) — fetches ------------------------------------------------------


def build_reverse_profiling_handler(
    *, judge: FaithfulnessJudge | None = None
) -> ReverseProfilingHandler:
    """The ``REVERSE_PROFILING`` handler (M5.1). ``judge`` is the M9.3 faithfulness judge the
    client-KB synthesis step routes tier-4 synthesized claims through — pass a
    ``FaithfulnessJudgeImpl`` over the shared gateway in production; ``None`` runs the pipeline
    without the synthesized-claim faithfulness check (the handler tolerates it)."""
    return ReverseProfilingHandler(judge=judge)


def register_reverse_profiling_handler(
    *,
    judge: FaithfulnessJudge | None = None,
    storage: StorageBackend | None,
    register: _Register = register_phase_handler,
) -> PhaseHandler:
    """Build + register the ``REVERSE_PROFILING`` handler (snapshot-wrapped when ``storage`` is
    passed — this phase **fetches**, so the wrapper is load-bearing)."""
    handler = snapshot_bound(build_reverse_profiling_handler(judge=judge), storage=storage)
    register(handler)
    return handler


# --- ICP_CONFIRMED (M5.2) — pure reads -------------------------------------------------------


def build_icp_confirmed_handler(
    *, estimate_inputs: EstimateInputs | None = None
) -> IcpConfirmedHandler:
    """The ``ICP_CONFIRMED`` handler (M5.2). Pure reads (read the pinned spec → compile → estimate);
    ``estimate_inputs`` are the versioned cost-dial priors for the pre-run estimate."""
    return IcpConfirmedHandler(estimate_inputs=estimate_inputs)


def register_icp_confirmed_handler(
    *,
    estimate_inputs: EstimateInputs | None = None,
    storage: StorageBackend | None,
    register: _Register = register_phase_handler,
) -> PhaseHandler:
    """Build + register the ``ICP_CONFIRMED`` handler. The phase does **not** fetch (pure reads), so
    the snapshot wrapper is harmless — applied only for uniformity when ``storage`` is passed."""
    handler = snapshot_bound(
        build_icp_confirmed_handler(estimate_inputs=estimate_inputs), storage=storage
    )
    register(handler)
    return handler


# --- DISCOVERY (M6.1+M6.2) — fetches ---------------------------------------------------------


def build_discovery_handler(
    *,
    channels: ChannelRegistry,
    gateway: LLMGateway | None = None,
    durable_batches: bool = False,
    storage: StorageBackend | None = None,
    session_factory: ConnFactory = transaction,
) -> PhaseHandler:
    """The DISCOVERY handler (M6). ``channels`` is the bound set of grounded discovery channels (the
    config seam) — an **empty** :class:`ChannelRegistry` is a valid production default (no provider
    wired yet: discovery finds nothing and advances, never fabricates). ``gateway`` plans/expands
    queries (never *is* the source of an entity)."""
    legacy = DiscoveryPhaseHandler(
        channels=channels, gateway=gateway, session_factory=session_factory
    )
    if not durable_batches:
        return legacy
    if storage is None:
        raise ValueError("durable discovery batches require a storage backend")
    return DurableDiscoveryPhaseHandler(
        storage=storage,
        fallback=legacy,
        conn_factory=session_factory,
    )


def register_discovery_handler(
    *,
    channels: ChannelRegistry,
    gateway: LLMGateway | None = None,
    durable_batches: bool = False,
    session_factory: ConnFactory = transaction,
    storage: StorageBackend | None,
    register: _Register = register_phase_handler,
) -> PhaseHandler:
    """Build + register the DISCOVERY handler (snapshot-wrapped when ``storage`` is passed — this
    phase **fetches** via its channels, so the wrapper is load-bearing)."""
    handler = snapshot_bound(
        build_discovery_handler(
            channels=channels,
            gateway=gateway,
            durable_batches=durable_batches,
            storage=storage,
            session_factory=session_factory,
        ),
        storage=storage,
    )
    register(handler)
    return handler


# --- SCORING (M6.3) — fetches ----------------------------------------------------------------


def build_scoring_handler(
    *,
    pre_spend_gate: PreSpendGate | None = None,
    sealed_account_reader: SealedDiscoveryAccountReader | None = None,
    session_factory: ConnFactory = transaction,
) -> ScoringPhaseHandler:
    """The SCORING handler (M6.3): cheap deterministic-first Pass-A fit/intent scoring over every
    admitted account. Config/thresholds default to their production constants."""
    return ScoringPhaseHandler(
        pre_spend_gate=pre_spend_gate or build_pre_spend_gate(),
        sealed_account_reader=sealed_account_reader,
        session_factory=session_factory,
    )


def register_scoring_handler(
    *,
    storage: StorageBackend | None,
    pre_spend_gate: PreSpendGate | None = None,
    sealed_account_reader: SealedDiscoveryAccountReader | None = None,
    session_factory: ConnFactory = transaction,
    register: _Register = register_phase_handler,
) -> PhaseHandler:
    """Build + register the SCORING handler (snapshot-wrapped when ``storage`` is passed — the
    Pass-A waterfall **fetches**, so the wrapper is load-bearing)."""
    handler = snapshot_bound(
        build_scoring_handler(
            pre_spend_gate=pre_spend_gate,
            sealed_account_reader=sealed_account_reader,
            session_factory=session_factory,
        ),
        storage=storage,
    )
    register(handler)
    return handler


# --- TIER_CHECKPOINT (M6.4) — pure reads/tiering ---------------------------------------------


def build_tier_checkpoint_handler(
    *,
    sealed_account_reader: SealedDiscoveryAccountReader | None = None,
    session_factory: ConnFactory = transaction,
) -> TierCheckpointPhaseHandler:
    """The TIER_CHECKPOINT handler (M6.4): tier the stored Pass-A scores, estimate Pass-B cost, and
    run the durable human gate. Config defaults to its production constants."""
    return TierCheckpointPhaseHandler(
        sealed_account_reader=sealed_account_reader,
        session_factory=session_factory,
    )


def register_tier_checkpoint_handler(
    *,
    storage: StorageBackend | None,
    sealed_account_reader: SealedDiscoveryAccountReader | None = None,
    session_factory: ConnFactory = transaction,
    register: _Register = register_phase_handler,
) -> PhaseHandler:
    """Build + register the TIER_CHECKPOINT handler. The phase does **not** fetch (it tiers stored
    scores), so the snapshot wrapper is harmless — applied only for uniformity when ``storage`` is
    passed."""
    handler = snapshot_bound(
        build_tier_checkpoint_handler(
            sealed_account_reader=sealed_account_reader,
            session_factory=session_factory,
        ),
        storage=storage,
    )
    register(handler)
    return handler
