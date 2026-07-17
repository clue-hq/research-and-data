"""The aspect-worker registry — aspect → :class:`~clue_core.AspectWorker` dispatch.

The orchestrator spawns workers by *aspect*, but must not import the package that implements them
(M8 owns the bodies; the import-linter independence contract forbids ``durable → profiling``). So,
exactly like the source layer's resolver binding (``sources.registry.bind_resolver``), concrete
``AspectWorker``\\s register themselves into this in-process map and the graph looks them up by the
``aspect`` string the lead planned. The registration call happens at the ``api`` composition root;
``durable`` only defines the registry and the lookup.

Last write wins, so a test or config can swap the worker behind an aspect. The registry never
imports a worker implementation — the binding is populated by callers (M8 / the api root / tests)
calling :meth:`WorkerRegistry.register`.
"""

from __future__ import annotations

from clue_core import AspectWorker


class WorkerRegistry:
    """An aspect → :class:`AspectWorker` dispatch map (M7.1).

    The orchestrator holds one registry and resolves each planned aspect's worker through it. A
    fresh registry can be constructed for isolation (tests, a per-campaign worker set); the
    process-default one (:func:`default_worker_registry`) backs the module-level binders."""

    def __init__(self) -> None:
        self._workers: dict[str, AspectWorker] = {}

    def register(self, worker: AspectWorker) -> None:
        """Bind ``worker`` to its declared ``aspect`` (last write wins)."""
        self._workers[worker.aspect] = worker

    def get(self, aspect: str) -> AspectWorker | None:
        """Return the worker bound to ``aspect``, or ``None`` if none is registered."""
        return self._workers.get(aspect)

    def aspects(self) -> frozenset[str]:
        """The set of aspects with a bound worker (diagnostics / test assertions)."""
        return frozenset(self._workers)

    def clear(self) -> None:
        self._workers.clear()


# Process-default registry. Concrete workers (M8) register here at the api composition root; the
# graph defaults to it when no explicit registry is injected.
_DEFAULT_REGISTRY = WorkerRegistry()


def default_worker_registry() -> WorkerRegistry:
    """The process-default :class:`WorkerRegistry` the graph uses when none is injected."""
    return _DEFAULT_REGISTRY


def register_aspect_worker(worker: AspectWorker) -> None:
    """Register ``worker`` into the process-default registry (the api-root binder; mirrors
    ``sources.registry.bind_resolver``)."""
    _DEFAULT_REGISTRY.register(worker)
