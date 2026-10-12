"""Shared shape for every governed design tool (Part II slice D6, rulings R-D6-1/R-D6-3).

D6's gate is "every design mutation behind a registered, precondition-checked, idempotency-keyed
tool". The tool *envelope* is the platform's (``clue_toolbelt``); what lives here is the design
side of the contract:

* :class:`DesignToolHost` — the seam through which a tool reaches the design app's collaborators
  (the workspace-scoped row store and byte store, the Rust core client, the node binaries). Every
  member is a **thunk**, resolved at invoke time rather than snapshotted at construction, because
  the design API's own suites mutate ``app.state`` (and monkeypatch
  ``main.compile_custom_component``) *after* ``create_app`` returns. A snapshotting host would
  silently ignore those seams.
* :class:`DesignTool` — the small base every design tool subclasses: it owns the "is the design
  runtime configured?" refusal and the ``asyncio.to_thread`` hop that runs the synchronous
  operation core off the invocation's event loop.

**Why the cores are synchronous.** The design app is synchronous by design (the O5 bridge — see
``design_store``): a route is a ``def``, and every store call is one ``asyncio.run`` of one DAL
coroutine. D6 does not re-shape that (Part IV / Part-I Step-2 own the async surface work), so a
tool body runs the same synchronous core the route used to call inline, handed to
``asyncio.to_thread`` so the invoker's loop is never blocked and so the core's own bridge calls
land on a thread that owns no loop (``design_store.run_isolated``'s fast path).

**Reference-only outputs (Doc A §3a).** A design tool returns ids/keys/digests/versions — never
HTML, never a scene, never component bytes. The REST routes re-read the rows they need to
assemble their (unchanged) response bodies from those references.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clue_toolbelt import (
    PreconditionFailure,
    Tool,
    ToolContext,
    ToolInput,
    ToolOutput,
    ToolResult,
)

__all__ = [
    "DESIGN_RUNTIME_NOT_CONFIGURED",
    "DesignTool",
    "DesignToolHost",
    "design_runtime_unconfigured",
]

#: The single reason code every design tool refuses with when this process holds no design
#: runtime. It is what the platform composition root registers (``clue_api.design_tools``): the
#: envelopes are always present in the platform registry — so the C6 authority audit stays a
#: complete, static statement about every write the platform can name — but they are inert until
#: the design app itself composes them with a real host.
DESIGN_RUNTIME_NOT_CONFIGURED = "design_runtime_not_configured"


@dataclass(frozen=True, slots=True)
class DesignToolHost:
    """The design app's collaborators, as thunks (see the module docstring).

    ``repository``/``blobs`` take a workspace id rather than being pre-bound, because tenancy
    comes from :class:`~clue_toolbelt.ToolContext` (never from a tool argument) and one host
    serves every tenant the process sees.

    The optional members are the collaborators only some tools need; a host that omits one is a
    host whose tools must not be invoked (the design API always supplies all of them).
    """

    repository: Callable[[str], Any]
    blobs: Callable[[str], Any]
    #: This workspace's engine materialization cache (D4). Needed only by the byte-destroying
    #: tool (``design_delete_asset``), which unlinks the cache mirror after durable custody has
    #: released the blob — the transient copy must not outlive the durable one.
    engine_cache_dir: Callable[[str], str] | None = None
    core: Callable[[], Any] | None = None
    web_export_node_bin: Callable[[], str] | None = None
    compiler_node_bin: Callable[[], str] | None = None
    compiler_worker_path: Callable[[], Path] | None = None
    compiler_timeout_seconds: Callable[[], float] | None = None
    compile_fn: Callable[[], Callable[..., dict[str, Any]]] | None = None
    #: Puck sites (Wave 2): the BrandData builder and the agent-section store (lumen_api.
    #: site_doc_inputs). Lane B2/B6 compose the real ones; the defaults refuse honestly.
    site_brand_loader: Callable[[], Callable[..., Any]] | None = None
    site_section_loader: Callable[[], Callable[..., Any]] | None = None

    def need(self, name: str) -> Any:
        """Resolve one required thunk, loudly."""
        thunk = getattr(self, name)
        if thunk is None:
            raise RuntimeError(f"the design tool host has no {name!r} collaborator")
        return thunk()


def design_runtime_unconfigured() -> tuple[PreconditionFailure, ...]:
    """The one refusal a host-less design tool makes — loud, never a silent-empty success."""
    return (
        PreconditionFailure(
            reason_code=DESIGN_RUNTIME_NOT_CONFIGURED,
            message=(
                "the design runtime is not composed in this process; design writes are served "
                "by the design API (set CLUE_DESIGN_RUNTIME_ENABLED and deploy "
                "subsystems/clue-design/apps/api)"
            ),
        ),
    )


class DesignTool(Tool):
    """Base for the design subsystem's governed write tools."""

    def __init__(self, host: DesignToolHost | None) -> None:
        self._host = host

    @property
    def host(self) -> DesignToolHost:
        if self._host is None:  # pragma: no cover - the precondition refuses first
            raise RuntimeError("invoke() ran without a configured design tool host")
        return self._host

    @property
    def configured(self) -> bool:
        return self._host is not None

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        """Refuse when unconfigured, else delegate to the tool's own synchronous checks.

        The design checks read through the synchronous ``HybridRepository`` (the O5 bridge), so
        they run on a worker thread exactly like the invoke body does.
        """
        if not self.configured:
            return design_runtime_unconfigured()
        return await asyncio.to_thread(self.check, inputs, ctx)

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        """Synchronous preconditions. Default: none beyond "the runtime exists"."""
        del inputs, ctx
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        output = await asyncio.to_thread(self.run, inputs, ctx)
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=output.model_dump(mode="json"),
        )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        """The synchronous operation core. Returns the tool's typed, reference-only output."""
        raise NotImplementedError
