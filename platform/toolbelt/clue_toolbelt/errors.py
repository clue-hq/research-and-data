"""Toolbelt errors — the loud, machine-readable failure surface (D5; pre-mortem #2).

A tool never returns a silent-empty success on an unmet precondition or a body conflict: it raises.
These are the three ways a toolbelt invocation refuses, each carrying enough structure for an HTTP
surface (slice 3) to map it to a status code without re-deriving anything:

* :class:`UnknownTool` — the requested tool name is not registered (→ 404).
* :class:`PreconditionFailed` — the tool's :meth:`~clue_toolbelt.Tool.preconditions` returned one or
  more :class:`~clue_toolbelt.envelope.PreconditionFailure` (each a ``reason_code`` + message); the
  write never ran (→ 409/422, caller's choice).
* :class:`IdempotencyConflict` — an ``idempotency_key`` was reused within its TTL with a *different*
  request body (D6 — same key + same body replays; same key + different body conflicts) (→ 409).
"""

from __future__ import annotations

from collections.abc import Sequence

from clue_toolbelt.envelope import PreconditionFailure

__all__ = [
    "ToolbeltError",
    "UnknownTool",
    "PreconditionFailed",
    "IdempotencyConflict",
]


class ToolbeltError(RuntimeError):
    """Base for every toolbelt-raised error (so a caller can ``except ToolbeltError`` broadly)."""


class UnknownTool(ToolbeltError):
    """The requested tool name is not registered in the :class:`~clue_toolbelt.ToolRegistry`."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"no tool registered under {name!r}")


class PreconditionFailed(ToolbeltError):
    """One or more preconditions of a tool were unmet — the invocation is refused before any write.

    Carries the full ``failures`` list (each a machine-readable ``reason_code`` + human message) so
    the caller/UI can explain *exactly* what is missing (e.g. ``no_active_icp``: "confirm an ICP
    before importing accounts") rather than seeing an empty result. This is the pre-mortem #2 guard:
    an unmet prerequisite is a loud, typed refusal, never a silent no-op."""

    def __init__(self, failures: Sequence[PreconditionFailure]) -> None:
        self.failures: tuple[PreconditionFailure, ...] = tuple(failures)
        codes = ", ".join(f.reason_code for f in self.failures) or "(none)"
        super().__init__(f"tool preconditions unmet: {codes}")

    @property
    def reason_codes(self) -> tuple[str, ...]:
        """The machine-readable codes, in order — the assertion surface for the out-of-order matrix
        test and the HTTP error body."""
        return tuple(f.reason_code for f in self.failures)


class IdempotencyConflict(ToolbeltError):
    """An ``idempotency_key`` was reused within its TTL with a *different* request body (D6).

    Same key + same body replays the stored response (safe retry); same key + a changed body is a
    client bug — the key no longer identifies the same request — so the invocation is refused rather
    than silently executed or silently replayed against a stale body."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(
            f"idempotency key {key!r} was already used within its TTL with a different request body"
        )
