"""The adapter registry — modality handling as data, not code (M4.3 / ENG-116).

The sibling of the M4.2 source registry's resolver binding: an in-process ``key -> ModalityAdapter``
map the dispatch (``run_pipeline``) selects from. A key is either a **modality** name (``"text"`` …,
for the modality-default adapter) or a **source-specific** adapter key (the manifest's
``requires_adapter``, e.g. ``"firecrawl_html"``). Adding a new modality or a new extractor for an
existing one is a :func:`register_adapter` call — **no pipeline fork** (staged-flow §7b), invisible
to the waterfall (M4.1) and to callers (M8) beyond the claims returned.

Like the resolver binding, this is populated by the owning code (M4.5 registers ``firecrawl_html``;
M8 registers long-tail adapters), so the framework never imports a concrete adapter at module load.
"""

from __future__ import annotations

from clue_core import ModalityAdapter


class AdapterNotRegisteredError(LookupError):
    """No :class:`~clue_core.ModalityAdapter` is registered for a key.

    Raised by :func:`get_adapter` and surfaced by ``run_pipeline`` for a source whose modality needs
    an adapter (pdf/audio/video) but none is registered — a clear misconfiguration, not a crash on
    bad data (the waterfall's tier-4 "no_resolver" is the analogous *expected* empty).
    """


_ADAPTERS: dict[str, ModalityAdapter] = {}


def register_adapter(key: str, adapter: ModalityAdapter) -> None:
    """Register ``adapter`` under ``key`` (a modality name or a source ``requires_adapter`` key).

    Last write wins, so a test/config can swap the implementation behind a key. Asserts structural
    conformance to the :class:`~clue_core.ModalityAdapter` protocol up front, so a
    misregistration fails at registration rather than mid-pipeline.
    """
    if not isinstance(adapter, ModalityAdapter):
        raise TypeError(
            f"object registered for adapter key {key!r} does not satisfy the ModalityAdapter "
            "protocol (needs `modality` + fetch/adapt/extract)"
        )
    _ADAPTERS[key] = adapter


def get_adapter(key: str) -> ModalityAdapter:
    """The adapter registered under ``key``; raise :class:`AdapterNotRegisteredError` if none."""
    adapter = _ADAPTERS.get(key)
    if adapter is None:
        raise AdapterNotRegisteredError(f"no modality adapter registered for key {key!r}")
    return adapter


def unregister_adapter(key: str) -> None:
    """Remove an adapter registration (no-op if absent)."""
    _ADAPTERS.pop(key, None)


def clear_adapters() -> None:
    """Drop all adapter registrations (test isolation; the map is module-global)."""
    _ADAPTERS.clear()


def is_adapter_registered(key: str) -> bool:
    """True if an adapter is registered under ``key``."""
    return key in _ADAPTERS


def registered_adapter_keys() -> set[str]:
    """All registered adapter keys (for diagnostics / introspection)."""
    return set(_ADAPTERS)
