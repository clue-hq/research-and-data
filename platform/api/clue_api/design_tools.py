"""Design tool registration for the platform toolbelt (Part II slice D6, ruling R-D6-1).

A thin composition seam, the sibling of :mod:`clue_api.design_fleet`. The design tool classes and
their operation cores live in ``lumen_api.toolbelt`` — next to the design store, the web-export
pipeline and the component compiler they drive, and where ``clue_design`` may be imported without
``clue_toolbelt`` importing design (contract T1) or ``clue_design`` importing the toolbelt (S4).
This module knows their *names* and their host, never their internals.

**Why the envelopes are registered unconditionally.** ``build_agent_profile_registry`` requires
``set(tool_registry.names()) == set(C6_AGENT_TOOL_AUTHORITY)`` exactly: a registry whose shape
depends on ``design_runtime_enabled`` would make the C6 authority audit environment-dependent and
would turn flipping that switch into an ``AgentCatalogError`` at composition. So the envelopes are
always present and always audited (granted to ``AgentRole.DESIGN`` since P3.3 — see
``agent_registry_wiring``), and the
switch controls whether they are **live** instead of whether they **exist**:

* ``enabled=False`` (the default) or no storage backend ⇒ the tools are constructed with **no
  design host** and every invocation refuses ``design_runtime_not_configured`` before any write.
  That is the ``research_view_tools`` shape — present-but-refusing — chosen over absent precisely
  because absence is what breaks the audit.
* ``enabled=True`` with a storage backend ⇒ the tools are constructed with a real host, so a
  platform process that already drains design fleet work can also serve governed design writes.

The import is deliberately narrow: ``lumen_api.toolbelt`` pulls ``clue_toolbelt`` + pydantic and
nothing else (its heavy design collaborators are imported inside function bodies). An unimportable
design app is a hard, loud failure rather than a silently smaller registry — see the docstring of
:class:`clue_api.design_fleet.DesignRuntimeUnavailable` for the same stance on the fleet handler.

**Ad page-geometry helpers retired 2026-08-23 (genad2 ruling 1; plan
``docs/superpowers/plans/2026-08-23-agent-authored-pages.md``).** For one week this module also
held ``AD_FORMAT_PRESETS``, ``ad_birth_page`` and ``mint_empty_ad_document`` — a platform-side
preset table and a hand-authored artboard payload that ``open_design_leg@3`` minted an ad
document around. The founder ruled that the platform must not own page geometry at all, so a
scene birth is now a bare ``new_scene`` issued by ``design_leg_tools`` (zero pages) and the
design deepagent authors the page. They were deleted rather than generalized; only the web
minter, whose ``WebDoc`` shape carries no such geometry, still lives here.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, cast

from clue_api.design_fleet import DesignRuntimeUnavailable
from clue_obs import get_logger
from clue_storage import StorageBackend
from clue_toolbelt import Tool

log = get_logger("clue_api.design_tools")

__all__ = [
    "build_design_tools",
    "mint_empty_web_document",
]


@lru_cache(maxsize=1)
def _core_client() -> Any:
    """One Rust core client per process (it is stateless and holds a helper-binary path)."""
    from lumen_api.core import CoreClient

    return CoreClient()


def _live_host(storage: StorageBackend) -> Any:
    from lumen_api.custom_component_compiler import (
        DEFAULT_COMPILER_TIMEOUT_SECONDS,
        compile_custom_component,
        default_compiler_worker_path,
    )
    from lumen_api.toolbelt.wiring import design_tool_host

    return design_tool_host(
        storage=storage,
        core=_core_client,
        web_export_node_bin=lambda: "node",
        compiler_node_bin=lambda: "node",
        compiler_worker_path=default_compiler_worker_path,
        compiler_timeout_seconds=lambda: DEFAULT_COMPILER_TIMEOUT_SECONDS,
        compile_fn=lambda: compile_custom_component,
    )


def mint_empty_web_document(
    *,
    document_id: str,
    title: str,
    brand_kit_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mint the engine's empty ``WebDoc`` for a new website-mode document.

    The Rust engine is the ONLY author of the WebDoc shape — the design API's own
    ``POST /documents`` route does exactly this round-trip before handing the payload to the
    governed ``design_create_document`` write (``lumen_api/main.py``), and every other
    creation path (templates, derivations) mints engine-side too. Hand-assembling the JSON
    platform-side would fork the schema, so the leg's document birth (genweb slice 2) reuses
    this seam rather than inventing one.

    It is a subprocess call to ``lumen-api-helper`` (``LUMEN_CORE_HELPER``, else a ``cargo
    run`` fallback) and therefore SYNC and blocking — callers on an event loop must hop a
    thread. ``brand_kit_ref`` is the ``{"id", "version"}`` shape the theme carries; ``None``
    leaves ``theme`` empty, which is what lets the DAL's creation contract stamp the
    workspace's latest approved kit at birth.
    """

    return cast(
        dict[str, Any],
        _core_client().web_new_doc(document_id, title, brand_kit_ref)["web_doc"],
    )


def build_design_tools(
    *,
    enabled: bool,
    storage: StorageBackend | None = None,
) -> tuple[Tool, ...]:
    """Return the design subsystem's governed write tools (live iff ``enabled`` + storage)."""
    try:
        from lumen_api.toolbelt import DESIGN_TOOL_NAMES
        from lumen_api.toolbelt import build_design_tools as _build
    except Exception as error:  # pragma: no cover - deployment shape, not logic
        raise DesignRuntimeUnavailable(
            "the design toolbelt envelopes are part of the platform's write-authority surface "
            "but lumen_api.toolbelt cannot be imported; install the design app "
            "(subsystems/clue-design/apps/api)"
        ) from error
    # `lumen_api` is an external boundary to the platform's type check (pyproject's
    # follow_imports="skip" override — the design tree is out of the root mypy graph until
    # Part-I Step-2), so the factory's return is `Any` here. The cast is the seam, and the
    # registry's own `register()` re-checks the descriptor at construction.
    if not enabled or storage is None:
        return cast(tuple[Tool, ...], _build(None))
    log.info("design_tools.live", tools=list(DESIGN_TOOL_NAMES))
    return cast(tuple[Tool, ...], _build(_live_host(storage)))


def is_default_design_tool(tool: Tool) -> bool:
    from lumen_api.toolbelt.factory import is_default_design_tool as is_default

    return bool(is_default(tool))
