"""PB-B4 slice 1 — the M5/M6 phase registration surfaces (``clue_api.phase_wiring``, D3).

Offline construction assertions: each ``build_*`` yields the right handler under the right phase,
and each ``register_*`` registers it **snapshot-wrapped** when a ``storage`` backend is passed and
bare when ``None`` (the born-snapshot-wrapped, storage-required-keyword posture) — construction
only, no DB, so these run in the offline ``make check`` suite.
"""

from __future__ import annotations

from clue_api.phase_wiring import (
    build_discovery_handler,
    build_icp_confirmed_handler,
    build_reverse_profiling_handler,
    build_scoring_handler,
    build_tier_checkpoint_handler,
    register_discovery_handler,
    register_icp_confirmed_handler,
    register_reverse_profiling_handler,
    register_scoring_handler,
    register_tier_checkpoint_handler,
)
from clue_api.storage_wiring import SnapshotBindingPhaseHandler
from clue_core import PhaseHandler, ProjectPhase
from clue_research.discovery_scoring.discovery import ChannelRegistry
from clue_research.durable import PhaseHandlerRegistry
from clue_research.stage0.icp_handler import IcpConfirmedHandler
from clue_research.stage0.reverse_profiling_handler import ReverseProfilingHandler
from tests.api.test_storage_wiring import FakeStorage


def test_build_handlers_declare_their_phases() -> None:
    assert build_reverse_profiling_handler().phase is ProjectPhase.REVERSE_PROFILING
    assert isinstance(build_reverse_profiling_handler(), ReverseProfilingHandler)
    assert build_icp_confirmed_handler().phase is ProjectPhase.ICP_CONFIRMED
    assert isinstance(build_icp_confirmed_handler(), IcpConfirmedHandler)
    assert build_discovery_handler(channels=ChannelRegistry()).phase is ProjectPhase.DISCOVERY
    assert build_scoring_handler().phase is ProjectPhase.SCORING
    assert build_tier_checkpoint_handler().phase is ProjectPhase.TIER_CHECKPOINT


def _register_all(registry: PhaseHandlerRegistry, *, storage: FakeStorage | None) -> None:
    register_reverse_profiling_handler(storage=storage, register=registry.register)
    register_icp_confirmed_handler(storage=storage, register=registry.register)
    register_discovery_handler(
        channels=ChannelRegistry(), storage=storage, register=registry.register
    )
    register_scoring_handler(storage=storage, register=registry.register)
    register_tier_checkpoint_handler(storage=storage, register=registry.register)


_M5_M6_PHASES = (
    ProjectPhase.REVERSE_PROFILING,
    ProjectPhase.ICP_CONFIRMED,
    ProjectPhase.DISCOVERY,
    ProjectPhase.SCORING,
    ProjectPhase.TIER_CHECKPOINT,
)


def test_register_wraps_in_snapshot_binding_when_storage_passed() -> None:
    """With a ``storage`` backend, every M5/M6 phase registers **wrapped** in the per-run
    snapshot-binding handler (born snapshot-wrapped, D3) — under its own phase (last-write-wins)."""
    registry = PhaseHandlerRegistry()
    _register_all(registry, storage=FakeStorage())
    assert registry.phases() == frozenset(_M5_M6_PHASES)
    for phase in _M5_M6_PHASES:
        handler = registry.get(phase)
        assert isinstance(handler, SnapshotBindingPhaseHandler), phase
        assert handler.phase is phase


def test_register_leaves_handler_unwrapped_when_storage_none() -> None:
    """``storage=None`` is the written opt-out — the bare handler is registered (pre-B2 path)."""
    registry = PhaseHandlerRegistry()
    _register_all(registry, storage=None)
    assert registry.phases() == frozenset(_M5_M6_PHASES)
    for phase in _M5_M6_PHASES:
        handler = registry.get(phase)
        assert not isinstance(handler, SnapshotBindingPhaseHandler), phase
        assert handler is not None and handler.phase is phase


def test_register_defaults_to_the_process_registry() -> None:
    """``register`` defaults to the process-default binder (like the other ``register_*`` surfaces);
    the returned object is a ``core.PhaseHandler`` for the phase."""
    handler = register_scoring_handler(storage=None, register=lambda _h: None)
    assert isinstance(handler, PhaseHandler)
    assert handler.phase is ProjectPhase.SCORING
