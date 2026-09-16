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
"""

from __future__ import annotations

import base64
import json
import threading
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import ArtifactRef
from clue_api.provider_incidents import record_failure, record_success
from clue_core.provider_failures import ProviderFailure

from .sinks import LedgerRow, RawRecord, sha256_hex

__all__ = [
    "ArtifactSink",
    "BufferedLedger",
    "BufferedRawSink",
    "DrainReport",
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


class ArtifactSink(Protocol):
    """The durable artifact store, named by the one method this module calls (O3's shape)."""

    async def persist_body(
        self, *, workspace_id: str, data: bytes, media_type: str
    ) -> ArtifactRef: ...


class BufferedRawSink:
    """A :class:`~clue_api.arv2.sinks.RawSink` that holds attempts until the async side drains.

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
    """A :class:`~clue_api.arv2.sinks.LedgerSink` that holds rows until the async side drains."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buffered: list[LedgerRow] = []

    def record(self, row: LedgerRow) -> str:
        with self._lock:
            self._buffered.append(row)
        return row.row_id

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
    row is a reservation made before the wire, never money."""

    rows: int
    artifacts: int
    cost_usd: Decimal
    credits: Decimal
    media_seconds: int


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


async def drain_provider_calls(
    conn: AsyncConnection,
    *,
    raw: BufferedRawSink,
    ledger: BufferedLedger,
    artifacts: ArtifactSink,
    stamp: LedgerStamp,
) -> DrainReport:
    """Persist every buffered raw body and ledger row, and report what this drain cost.

    Bytes first, then the rows that cite them — a ledger row never names an artifact key that does
    not exist yet. When two attempts shared a body they share a ``raw_ref``; the last artifact
    written for that reference is the one the rows cite (they differ only in record metadata).
    """
    keys: dict[str, str] = {}
    persisted = 0
    for ref, record, body in raw.drain():
        artifact = await artifacts.persist_body(
            workspace_id=stamp.workspace_id,
            data=artifact_payload(record, body),
            media_type="application/json",
        )
        keys[ref] = artifact.artifact_key
        persisted += 1

    rows = ledger.drain()
    for row in rows:
        await conn.execute(_INSERT_LEDGER, _ledger_params(row, stamp=stamp, keys=keys))

    await _record_incidents(conn, rows, stamp=stamp)

    results = [row for row in rows if row.phase == "result"]
    return DrainReport(
        rows=len(rows),
        artifacts=persisted,
        cost_usd=sum((row.cost_usd or Decimal(0) for row in results), Decimal(0)),
        credits=sum((row.credits or Decimal(0) for row in results), Decimal(0)),
        media_seconds=sum(row.media_seconds or 0 for row in results),
    )


def _surface_for(row: LedgerRow, stamp: LedgerStamp) -> str:
    """Which product surface this spend was for — the word an incident's breakdown counts under."""
    if stamp.job_id is not None:
        return "research_job"
    if row.operation == "chat/completions" and row.label.startswith("display-"):
        return "display_section"
    if stamp.project_run_id is not None:
        return "discovery"
    if row.label.startswith("onboarding"):
        return "onboarding"
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


async def _record_incidents(
    conn: AsyncConnection, rows: Sequence[LedgerRow], *, stamp: LedgerStamp
) -> None:
    """After the rows are in: every stamped failure lands on an incident, every provider with an
    ``ok`` result closes its incidents. Successes are folded per provider so a batch of thirty
    good rows costs one indexed UPDATE, and closes run AFTER failures so a batch that holds both
    (a retry that finally worked) ends closed, which is what the provider's last word was."""
    results = [row for row in rows if row.phase == "result"]
    for row in results:
        failure = _stamped_failure(row)
        if failure is not None:
            await record_failure(
                conn,
                failure,
                surface=_surface_for(row, stamp),
                workspace_id=stamp.workspace_id,
                now=row.recorded_at,
            )
    recovered: dict[str, datetime] = {}
    for row in results:
        if row.outcome == "ok" and _stamped_failure(row) is None:
            seen = recovered.get(row.provider, row.recorded_at)
            recovered[row.provider] = max(seen, row.recorded_at)
    for provider, at in recovered.items():
        await record_success(conn, provider, now=at)


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
