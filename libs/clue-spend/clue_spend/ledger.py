"""Production sinks for the R1 caller: buffer in the worker thread, land in the DB after the hop.

``ProviderCaller`` is synchronous and runs inside ``asyncio.to_thread``; its sinks are called from
that thread. Writing to Postgres from there would need a loop hand-off inside a lock the driver
already holds, so the sinks only buffer, and the async side drains them right after the hop: raw
bodies to the artifact store (one artifact per attempt: the ``RawRecord`` as JSON plus the body,
base64 when not UTF-8), ledger rows to ``provider_call_ledger`` with the job stamp.

``provider_call_ledger.entity_research_job_id`` carries the R2 ``arv2_research_job.job_id``, a
discovery run id, or (slice 1b) an onboarding run id — the column was named by D1 before R2
existed; its meaning is "the job that spent", and it is NULL for spend with no job (a display
page, a chat-turn tool).
A call in flight when the runtime cap fires drains at finalization (Task 5 waits, bounded, for
in-flight hops); a lost lease can lose that hop's rows — recorded as the known residual.

Lane 3 slice 5 moved this module out of ``clue_api.arv2`` so the design subsystem can drain into
the same one ledger. What was platform-specific about it — recording a provider *incident* from a
stamped failure — left with it: the drain now takes an optional :data:`FailureHook` and the
platform binds its own recorder at the call site (``clue_api.arv2.provider_ledger``).
"""

from __future__ import annotations

import base64
import json
import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core.provider_failures import ProviderFailure

from .sinks import LedgerRow, RawRecord, sha256_hex

__all__ = [
    "ArtifactRefLike",
    "ArtifactSink",
    "BufferedLedger",
    "BufferedRawSink",
    "DrainReport",
    "FailureHook",
    "LedgerStamp",
    "artifact_payload",
    "drain_provider_calls",
    "ledger_id_for",
]

#: The namespace prefix that turns an R1 ``row_id`` into this table's primary key. Deterministic,
#: so draining the same buffered row twice is one row, not two (the drain runs inside the driver's
#: transaction and can be retried after a rollback).
_LEDGER_ID_PREFIX = "arv2-ledger:"

_INSERT_LEDGER = text(
    "INSERT INTO provider_call_ledger (ledger_id, call_id, workspace_id, project_id, "
    " project_run_id, entity_research_job_id, provider, operation, label, phase, http_status, "
    " latency_ms, attempts, estimate_usd, estimate_credits, estimate_media_seconds, cost_usd, "
    " credits, media_seconds, over_ceiling, outcome, error_code, provider_request_id, "
    " response_artifact_key, extras_json, recorded_at) "
    "VALUES (:ledger_id, :call_id, :workspace_id, :project_id, :project_run_id, :job_id, "
    " :provider, :operation, :label, :phase, :http_status, :latency_ms, :attempts, :estimate_usd, "
    " :estimate_credits, :estimate_media_seconds, :cost_usd, :credits, :media_seconds, "
    " :over_ceiling, :outcome, :error_code, :provider_request_id, :response_artifact_key, "
    " CAST(:extras_json AS jsonb), :recorded_at) "
    "ON CONFLICT (ledger_id) DO NOTHING"
)


class ArtifactRefLike(Protocol):
    """The one fact this module reads off a persisted artifact: the key a ledger row cites.

    Structural rather than the platform's ``clue_agents.contracts.ArtifactRef``, because the seam
    lives in a library now and a library may not import a platform contract. Every existing sink
    (which returns the real ``ArtifactRef``) satisfies it unchanged.
    """

    @property
    def artifact_key(self) -> str: ...


class ArtifactSink(Protocol):
    """The durable artifact store, named by the one method this module calls (O3's shape)."""

    async def persist_body(
        self, *, workspace_id: str, data: bytes, media_type: str
    ) -> ArtifactRefLike: ...


#: Called once per failed **result** row, after every row of the drain is inserted:
#: ``(conn, row, stamp, surface)``. It exists so a platform can hang its own follow-up — the
#: platform's provider-incident recorder — off a drain the library performs, without this module
#: knowing that recorder exists. ``None`` (the default) means the drain only writes rows.
FailureHook = Callable[[AsyncConnection, LedgerRow, "LedgerStamp", str], Awaitable[None]]


class BufferedRawSink:
    """A :class:`~clue_spend.sinks.RawSink` that holds attempts until the async side drains.

    The ``raw_ref`` is the body's content address, so two attempts that came back byte-identical
    share one reference (and one artifact) — the ledger row cites the bytes, not the attempt.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buffered: list[tuple[str, RawRecord, bytes]] = []

    def save(self, record: RawRecord, body: bytes) -> str:
        ref = f"raw:{sha256_hex(body)}"
        with self._lock:
            self._buffered.append((ref, record, body))
        return ref

    def drain(self) -> list[tuple[str, RawRecord, bytes]]:
        """Every ``(raw_ref, record, body)`` buffered since the last drain, in order."""
        with self._lock:
            drained = list(self._buffered)
            self._buffered.clear()
        return drained


class BufferedLedger:
    """A :class:`~clue_spend.sinks.LedgerSink` that holds rows until the async side drains."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buffered: list[LedgerRow] = []

    def record(self, row: LedgerRow) -> str:
        with self._lock:
            self._buffered.append(row)
        return row.row_id

    @property
    def rows(self) -> tuple[LedgerRow, ...]:
        """A non-destructive snapshot of what is buffered, under the same name
        :class:`~clue_spend.sinks.MemoryLedger` uses.

        A caller that has to *read* the row its own call just wrote — the design image provider
        naming the ledger row on its generation receipt — cannot use :meth:`drain`, which empties
        the buffer the unit of work still has to land.
        """
        with self._lock:
            return tuple(self._buffered)

    def drain(self) -> list[LedgerRow]:
        with self._lock:
            drained = list(self._buffered)
            self._buffered.clear()
        return drained


@dataclass(frozen=True)
class LedgerStamp:
    """Whose spend this is. ``workspace_id`` is the one fact every row carries; the project, the
    project run and the job are stamped when the spender has them and left NULL when it does not
    (slice 1b: an onboarding run stamps its own id as the job; a display page or a chat-turn tool
    stamps the workspace alone)."""

    workspace_id: str
    project_id: str | None = None
    project_run_id: str | None = None
    job_id: UUID | None = None


@dataclass(frozen=True)
class DrainReport:
    """What one drain landed. The three spend numbers are the ``result`` rows only — an estimate
    row is a reservation made before the wire, never money.

    ``result_rows`` carries those settled rows themselves, in drain order. A caller that has to
    reason about the *batch* rather than about one row reads them: the platform's incident
    recorder closes a provider's incidents only when that provider's last word in the batch was a
    success, and a per-row hook can never see that. Defaulted, so a hand-built report still
    validates.
    """

    rows: int
    artifacts: int
    cost_usd: Decimal
    credits: Decimal
    media_seconds: int
    result_rows: tuple[LedgerRow, ...] = field(default_factory=tuple)
    raw_artifact_keys: Mapping[str, str] = field(default_factory=dict)
    #: artifact key -> the exact bytes stored under it, for this drain only: a caller indexing the
    #: batch right away (W2-16) uses them instead of downloading what it has just written. Freed
    #: with the report.
    raw_bodies: Mapping[str, bytes] = field(default_factory=dict)


def ledger_id_for(row_id: str) -> UUID:
    """The table's primary key for an R1 ledger row id — deterministic, so a redrain is a no-op."""
    return uuid5(NAMESPACE_URL, f"{_LEDGER_ID_PREFIX}{row_id}")


def artifact_payload(record: RawRecord, body: bytes) -> bytes:
    """One attempt as stored bytes: the record, plus the body inline or base64-encoded.

    Both body fields are always present so a reader never has to guess which one a record used:
    a UTF-8 body fills ``body_utf8`` and leaves ``body_base64`` null, anything else the reverse.
    """
    try:
        body_utf8: str | None = body.decode("utf-8")
    except UnicodeDecodeError:
        body_utf8 = None
    payload = {
        "record": asdict(record),
        "body_utf8": body_utf8,
        "body_base64": None if body_utf8 is not None else base64.b64encode(body).decode("ascii"),
    }
    return json.dumps(payload, sort_keys=True, default=_json_default).encode("utf-8")


def _json_default(value: object) -> str:
    """The two non-JSON types a raw record carries: ``datetime`` (ISO-8601) and ``Decimal``."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _call_uuid(call_id: str) -> UUID:
    """``call_id`` as the table's uuid. R1 mints ``str(uuid4())``; anything else is derived.

    A derived id is still stable and still groups a call's estimate and result rows together, so a
    foreign ledger row (a replay, a hand-written fixture) lands rather than raising.
    """
    try:
        return UUID(call_id)
    except ValueError:
        return uuid5(NAMESPACE_URL, call_id)


@dataclass(frozen=True)
class HeldDrain:
    """A drain's first half: the raw bodies already stored and the ledger rows taken from the
    buffer, before any row is written. :func:`record_drain` writes the rows."""

    rows: tuple[LedgerRow, ...]
    raw_artifact_keys: Mapping[str, str]
    raw_bodies: Mapping[str, bytes]
    artifacts: int

    @property
    def result_rows(self) -> tuple[LedgerRow, ...]:
        return tuple(row for row in self.rows if row.phase == "result")


async def hold_drain(
    *,
    raw: BufferedRawSink,
    ledger: BufferedLedger,
    artifacts: ArtifactSink | None,
    stamp: LedgerStamp,
) -> HeldDrain:
    """Store every buffered raw body and take the buffered ledger rows, without a connection of
    the caller's: the artifact sink records each body's row itself (before its upload). A caller
    that holds a scarce connection for the rows (W2-15 option B) runs this first, outside it."""
    keys: dict[str, str] = {}
    bodies: dict[str, bytes] = {}
    persisted = 0
    for ref, record, body in raw.drain():
        if artifacts is None:
            continue
        data = artifact_payload(record, body)
        artifact = await artifacts.persist_body(
            workspace_id=stamp.workspace_id,
            data=data,
            media_type="application/json",
        )
        keys[ref] = artifact.artifact_key
        bodies[artifact.artifact_key] = data
        persisted += 1
    return HeldDrain(tuple(ledger.drain()), keys, bodies, persisted)


async def record_drain(
    conn: AsyncConnection,
    held: HeldDrain,
    *,
    stamp: LedgerStamp,
    on_failure: FailureHook | None = None,
) -> DrainReport:
    """Write a held drain's ledger rows, citing the bodies it stored, and report its spend."""
    for row in held.rows:
        await conn.execute(
            _INSERT_LEDGER, _ledger_params(row, stamp=stamp, keys=held.raw_artifact_keys)
        )

    results = held.result_rows
    if on_failure is not None:
        for row in results:
            if _stamped_failure(row) is not None:
                await on_failure(conn, row, stamp, _surface_for(row, stamp))

    return DrainReport(
        rows=len(held.rows),
        artifacts=held.artifacts,
        cost_usd=sum((row.cost_usd or Decimal(0) for row in results), Decimal(0)),
        credits=sum((row.credits or Decimal(0) for row in results), Decimal(0)),
        media_seconds=sum(row.media_seconds or 0 for row in results),
        result_rows=results,
        raw_artifact_keys=held.raw_artifact_keys,
        raw_bodies=held.raw_bodies,
    )


async def drain_provider_calls(
    conn: AsyncConnection,
    *,
    raw: BufferedRawSink,
    ledger: BufferedLedger,
    artifacts: ArtifactSink | None,
    stamp: LedgerStamp,
    on_failure: FailureHook | None = None,
    held: HeldDrain | None = None,
) -> DrainReport:
    """Persist every buffered raw body and ledger row, and report what this drain cost.

    Bytes first, then the rows that cite them — a ledger row never names an artifact key that does
    not exist yet. When two attempts shared a body they share a ``raw_ref``; the last artifact
    written for that reference is the one the rows cite (they differ only in record metadata).

    ``artifacts=None`` drains the raw buffer without persisting anything from it: the rows land
    with ``response_artifact_key`` NULL. That is for a caller whose bodies already live somewhere
    durable of its own — the money trail is still complete, it just cites nothing here.

    ``on_failure``, when given, is awaited once per failed result row after every row is inserted,
    with the surface :func:`_surface_for` computed for it.

    ``held`` is a :func:`hold_drain` the caller already ran (bodies stored, rows taken); only its
    rows are written here.
    """
    if held is None:
        held = await hold_drain(raw=raw, ledger=ledger, artifacts=artifacts, stamp=stamp)
    return await record_drain(conn, held, stamp=stamp, on_failure=on_failure)


def _surface_for(row: LedgerRow, stamp: LedgerStamp) -> str:
    """Which product surface this spend was for — the word an incident's breakdown counts under.

    The label is read before the stamp, because an onboarding run stamps *its own id* as the job
    (the ``LedgerStamp`` docstring's slice-1b note): asking ``job_id`` first would file every
    onboarding call under ``research_job`` and the onboarding surface would never appear.

    The design operations are read before everything, for the same reason one step further out: a
    design turn carries no ARV2 stamp at all, so every branch below would fall through to the raw
    operation and the design surfaces would never be named. ``design.ingestion.*`` is separated
    from the rest because brand-kit ingestion is a one-off cost with a different owner than a
    marketer's turn, and an incident breakdown that folded them would answer neither question.
    """
    if row.operation.startswith("design.ingestion."):
        return "design_ingestion"
    if row.operation.startswith("design."):
        return "design_turn"
    if row.label.startswith("onboarding"):
        return "onboarding"
    if stamp.job_id is not None:
        return "research_job"
    if row.operation == "chat/completions" and row.label.startswith("display-"):
        return "display_section"
    if stamp.project_run_id is not None:
        return "discovery"
    return row.operation


def _stamped_failure(row: LedgerRow) -> ProviderFailure | None:
    """The classification R1 stamped on a failing result row, or ``None`` when the row is fine."""
    stamped = row.extras.get("provider_failure")
    if not isinstance(stamped, Mapping):
        return None
    try:
        return ProviderFailure(
            row.provider,
            stamped["kind"],
            stamped["reason"],
            str(stamped.get("message", "")),
        )
    except KeyError:
        return None


def _ledger_params(
    row: LedgerRow, *, stamp: LedgerStamp, keys: Mapping[str, str]
) -> dict[str, object]:
    """One row's bind parameters. ``raw_ref`` becomes ``response_artifact_key``; a row with no raw
    reference (every estimate row) cites nothing rather than the previous row's bytes."""
    return {
        "ledger_id": ledger_id_for(row.row_id),
        "call_id": _call_uuid(row.call_id),
        "workspace_id": stamp.workspace_id,
        "project_id": stamp.project_id,
        "project_run_id": stamp.project_run_id,
        "job_id": stamp.job_id,
        "provider": row.provider,
        "operation": row.operation,
        "label": row.label,
        "phase": row.phase,
        "http_status": row.http_status,
        "latency_ms": row.latency_ms,
        "attempts": row.attempts,
        "estimate_usd": row.estimate_usd,
        "estimate_credits": row.estimate_credits,
        "estimate_media_seconds": row.estimate_media_seconds,
        "cost_usd": row.cost_usd,
        "credits": row.credits,
        "media_seconds": row.media_seconds,
        "over_ceiling": row.over_ceiling,
        "outcome": row.outcome,
        "error_code": row.error_code,
        "provider_request_id": row.provider_request_id,
        "response_artifact_key": keys.get(row.raw_ref) if row.raw_ref else None,
        "extras_json": json.dumps(dict(row.extras), sort_keys=True, default=_json_default)
        if row.extras
        else None,
        "recorded_at": row.recorded_at,
    }
