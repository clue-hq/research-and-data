"""The phase-handler registry — :class:`~clue_core.CampaignPhase` → handler dispatch.

The campaign-run state machine (M7.3) advances through phases but must not import the packages that
implement them (M5/M6/M8/M9/M12 own the bodies; the import-linter independence contract forbids
``durable → discovery_scoring`` etc.). So, exactly like the aspect-worker registry
(``durable/workers.py``) and the source layer's resolver binding (``sources.registry``), concrete
:class:`~clue_core.PhaseHandler`\\s register themselves into this in-process map and the
state machine looks them up by the :class:`~clue_core.CampaignPhase` it is advancing.
The registration call happens at the ``api`` composition root; ``durable`` only defines the registry
and the lookup, and never imports a handler implementation.

Last write wins, so a test or config can swap the handler behind a phase.
"""

from __future__ import annotations

from clue_core import CampaignPhase, PhaseHandler


class PhaseHandlerRegistry:
    """A :class:`CampaignPhase` → :class:`PhaseHandler` dispatch map (M7.3).

    The state machine holds one registry and resolves each phase's handler through it. A fresh
    registry can be constructed for isolation (tests, a per-campaign handler set); the
    process-default one (:func:`default_phase_handler_registry`) backs the module-level binders."""

    def __init__(self) -> None:
        self._handlers: dict[CampaignPhase, PhaseHandler] = {}

    def register(self, handler: PhaseHandler) -> None:
        """Bind ``handler`` to its declared ``phase`` (last write wins)."""
        self._handlers[handler.phase] = handler

    def get(self, phase: CampaignPhase) -> PhaseHandler | None:
        """Return the handler bound to ``phase``, or ``None`` if none is registered."""
        return self._handlers.get(phase)

    def phases(self) -> frozenset[CampaignPhase]:
        """The set of phases with a bound handler (diagnostics / test assertions)."""
        return frozenset(self._handlers)

    def clear(self) -> None:
        self._handlers.clear()


# Process-default registry. Concrete handlers (M5/M6/M8/M9/M12) register here at the api composition
# root; the state machine defaults to it when no explicit registry is injected.
_DEFAULT_REGISTRY = PhaseHandlerRegistry()


def default_phase_handler_registry() -> PhaseHandlerRegistry:
    """The process-default :class:`PhaseHandlerRegistry` the state machine uses when none is
    injected."""
    return _DEFAULT_REGISTRY


def register_phase_handler(handler: PhaseHandler) -> None:
    """Register ``handler`` into the process-default registry (the api-root binder; mirrors
    ``durable.register_aspect_worker`` / ``sources.registry.bind_resolver``)."""
    _DEFAULT_REGISTRY.register(handler)
