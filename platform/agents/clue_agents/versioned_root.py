"""The seam a *versioned* workspace mount writes through.

A read-only mount serves bytes somebody else already made durable. A versioned mount is the
other half of that bargain: the model still reads a plain tree of files, but a write under it
is not a file write at all — it is a new *version* of a document, taken by whoever owns those
documents, with an optimistic-concurrency check against the version the model last read. The
backend therefore cannot own the write; it can only hand it over and then re-read whatever the
owner made of it.

This module is that handover, and nothing more. It holds no implementation: the real writer
lives with the document store, and the backend depends only on the shape below, so the two
never import each other. The protocol is deliberately **sync** — the deepagents backend is a
sync surface called from a worker thread, so an async implementation bridges (see
:class:`clue_agents.bridge.AsyncBridge`) rather than colouring this seam.

Two outcomes, both loud. A write that lands returns a :class:`VersionedWriteOutcome` naming the
version it created, so the turn can say what it wrote rather than guess. A write that is refused
raises :class:`VersionedWriteRefused` with a machine-readable ``code``; the backend turns that
into the model-visible ``conflict: <code>: <message>`` — the code is there so the model can tell
"you are behind, read it again" from "you are not allowed to write this" without parsing prose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

__all__ = [
    "VersionedRootWriter",
    "VersionedWriteOutcome",
    "VersionedWriteRefused",
]


@dataclass(frozen=True, slots=True)
class VersionedWriteOutcome:
    """What one accepted write became: a document version, not a file.

    ``path`` is the virtual path *under the mount* (``plan.md``, never ``project/plan.md``) — the
    mount's name is the backend's business and means nothing to the document store. ``replayed``
    records that the write was recognized as one already taken (an idempotent retry of the same
    turn's operation) rather than a new version, so a resumed turn reports the truth instead of
    inventing a second version that never existed.

    ``kind`` and ``title`` are the *document's* words for itself, not the platform's: the mount
    reads them off the front matter the model wrote, so the card a human sees on the turn is named
    by the document. ``title`` defaults to ``None`` for a writer that has none to give.
    """

    path: str
    version: int
    document_id: UUID
    kind: str
    status: str
    replayed: bool
    title: str | None = None


class VersionedWriteRefused(Exception):
    """A refused write, carrying the reason in a form both the model and a test can read.

    ``code`` is the stable token (``revision_conflict`` and friends); ``message`` is the sentence
    the model is shown. Both survive onto ``str(exc)`` so a bare log line still says why.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class VersionedRootWriter(Protocol):
    """The owner of a versioned mount's documents, as the backend sees it."""

    def write(
        self,
        *,
        path: str,
        content: str,
        expected_version: int | None,
    ) -> VersionedWriteOutcome:
        """Take one write of ``path`` as a new version, or refuse it.

        ``expected_version`` is the version the *reader* had — the one the backend recorded when
        it last materialized the mount — and ``None`` means "there was no such file when I read".
        The writer compares it against the document's current version and raises
        :class:`VersionedWriteRefused` when they disagree, so a model working from a stale view
        is told to re-read rather than silently overwriting somebody else's version.

        Sync, because the deepagents backend is sync; an async implementation bridges.
        """

    def refresh(self) -> dict[str, int]:
        """Re-materialize the library and return the new ``path → version`` map.

        Called immediately after an accepted write so the mount's next write carries the version
        this one created. The returned map covers only files that *have* a version — a compiled,
        unversioned file is absent from it, which is exactly the ``None`` the writer expects for
        a path it has never versioned.
        """
