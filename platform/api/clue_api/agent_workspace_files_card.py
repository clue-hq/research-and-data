"""What the agent has, how old it is, and what expired — handed to it at the start of a turn.

F3 Phase 2, WS-28 (docs/superpowers/specs/agent-workspace/, ruling AW-22; spec decision D-23).
Phase 2 lets a chat's rough work expire: a raw input's bytes go after 48 hours, a working file's
after 7 days, and only a :class:`~clue_agents.workspace_snapshot.Receipt` stays behind. An agent
that is not told cannot know — it would read its own week-old analysis and build on source data
nobody holds any more. So every turn opens on this card.

It is built from the chat's own **file list** — the snapshot manifest this turn restored — and
never from the worker's disk. The disk is a cache (ruling AW-23): what it happens to hold says
nothing about what the chat owns, and a sweep could empty it mid-sentence. The file list is the
durable answer, so it is the only one the agent is given.

The card is persisted as an ordinary L3 project-context artifact, so it is materialized beside
the turn's other context files and re-sent on a continued turn like its neighbours.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Final

from pydantic import JsonValue

from clue_agents.workspace_snapshot import UNKNOWN_RECEIPT, Receipt, SnapshotEntry, SnapshotManifest

__all__ = [
    "NOTE",
    "WORKSPACE_FILES_CARD_NAME",
    "WORKSPACE_FILES_MAX_EXPIRED",
    "WORKSPACE_FILES_MAX_LISTED",
    "WORKSPACE_FILES_MEDIA_TYPE",
    "WORKSPACE_FILES_SCHEMA_VERSION",
    "build_workspace_files_card",
]

WORKSPACE_FILES_MEDIA_TYPE: Final = "application/vnd.clue.agent-workspace-files+json"
#: The L3 context artifact's name, which is also its materialized file name. Matches
#: ``ProjectContextName``'s ``^[a-z0-9_-]+$``.
WORKSPACE_FILES_CARD_NAME: Final = "workspace_files"
WORKSPACE_FILES_SCHEMA_VERSION: Final = "1"
#: How many live files the card names. A chat with more is told the rest by count and folder
#: rather than by path: the agent still knows it has not been shown everything.
WORKSPACE_FILES_MAX_LISTED: Final = 200
#: How many expired files the card names, newest first. The expired half is the one that grows
#: without bound — an entry is kept for the chat's life (WS-25) and a CRM-heavy chat spills a
#: ``reads/`` file every turn — and all of it, receipts included, is re-sent in every turn's
#: context. Newest first because the file the agent has just lost is the one it will ask about.
WORKSPACE_FILES_MAX_EXPIRED: Final = 200

#: The one line that explains the card to the agent: the founder-approved wording of 2026-10-23
#: (Phase 2, Task 8). Agent-facing prose is reviewed, never invented here, so this string is
#: changed only by the same route.
NOTE: Final = (
    "Files are deleted by age: what a tool pulled down after 48 hours, your own working files "
    "after 7 days. outputs/ is kept for the life of the chat."
)


def build_workspace_files_card(
    manifest: SnapshotManifest | None,
    *,
    now: datetime,
) -> dict[str, JsonValue]:
    """The turn-start card of this chat's files, from its restored file list.

    ``now`` is passed in rather than read: the card is a pure function of the file list and the
    turn's own clock, so a replayed turn composes the same bytes it composed the first time.

    A ``None`` manifest — a brand-new chat, or a deployment with snapshots off — answers with an
    empty card rather than with nothing at all. "You have no files" is a true and useful thing to
    be told; silence is not.
    """

    live_entries = sorted(manifest.live(), key=lambda entry: entry.path) if manifest else ()
    expired_entries = sorted(manifest.expired(), key=_newest_first) if manifest else ()
    listed = live_entries[:WORKSPACE_FILES_MAX_LISTED]
    omitted = Counter(_folder(entry.path) for entry in live_entries[WORKSPACE_FILES_MAX_LISTED:])
    gone = expired_entries[:WORKSPACE_FILES_MAX_EXPIRED]
    omitted_expired = Counter(
        _folder(entry.path) for entry in expired_entries[WORKSPACE_FILES_MAX_EXPIRED:]
    )
    return {
        "schema_version": WORKSPACE_FILES_SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "live": [
            {
                "path": entry.path,
                "folder": _folder(entry.path),
                "size": entry.size,
                "age_hours": _age_hours(entry.written_at, now),
                "tier": entry.tier,
            }
            for entry in listed
        ],
        # Newest first and bounded: this list never shrinks on its own, so an old chat would
        # otherwise spend more of its context on files it no longer has than on the ones it does.
        "expired": [
            {
                "path": entry.path,
                "tier": entry.tier,
                # How much it held, in bytes: the founder-approved manual promises the agent this
                # for every deleted file (Task 8, text (b)), and only a CRM read's receipt counts
                # its records — so the card says it for all of them.
                "size": entry.size,
                # When it was made: the same manual line promises "when", and a receipt's
                # ``produced_at`` is filled only for a tool's read — a script's output, a working
                # file or an unknown file would otherwise say only when it was deleted.
                "written_at": _iso(entry.written_at),
                "expired_at": _iso(entry.expired_at),
                "receipt": _receipt(entry),
            }
            for entry in gone
        ],
        "omitted": dict(sorted(omitted.items())),
        "omitted_expired": dict(sorted(omitted_expired.items())),
        "note": NOTE,
    }


def _newest_first(entry: SnapshotEntry) -> tuple[float, str]:
    """Most recently expired first, with the path breaking ties so the card is deterministic.

    An entry in :meth:`~clue_agents.workspace_snapshot.SnapshotManifest.expired` always has an
    ``expired_at``; the ``0.0`` is only so the key is total.
    """

    when = entry.expired_at
    return (0.0 if when is None else -_aware(when).timestamp(), entry.path)


def _folder(path: str) -> str:
    """The top folder of a saved path — ``scratch``, ``reads``, ``work`` or ``outputs``."""

    return path.split("/", 1)[0]


def _age_hours(written_at: datetime, now: datetime) -> int:
    """Whole hours since the content was written, floored, and never below zero.

    A clock that disagrees with the one that stamped the row would otherwise hand the agent a
    negative age, which is worse than a zero: zero reads as "just now", which is what it means.
    """

    elapsed = _aware(now) - _aware(written_at)
    return max(0, int(elapsed.total_seconds() // 3600))


def _aware(value: datetime) -> datetime:
    """Times from storage are UTC; one that forgot to say so is read as UTC rather than refused."""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _receipt(entry: SnapshotEntry) -> dict[str, JsonValue]:
    """The expired file's receipt, always in full shape.

    Task 5 stamps :data:`UNKNOWN_RECEIPT` on anything it expires without one, so a null receipt
    should not reach here — but an older file list could carry one, and the agent is better served
    by an honest "unknown" than by a key that is sometimes missing.
    """

    receipt: Receipt = entry.receipt if entry.receipt is not None else UNKNOWN_RECEIPT
    return {
        "source": receipt.source,
        "operation_id": receipt.operation_id,
        "produced_at": _iso(receipt.produced_at),
        "details": dict(receipt.details),
        "read_again": receipt.read_again,
    }
