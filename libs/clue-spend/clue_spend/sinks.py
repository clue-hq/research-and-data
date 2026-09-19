"""Where a call's raw body and its cost row go — Appendix A law 1, split into two seams.

Law 1 is: *save the raw provider response before parsing; annotate status, latency and the
request; then write the cost ledger entry.* The wrapper enforces the ordering; this module owns
the two destinations and the redaction that stands between a provider header and anything durable.

R1 ships the protocols plus a file/JSONL pair (development and tests) and an in-memory pair
(the wrapper's own unit tests). Production sinks land with D1/A7: raw bodies become ``artifact``
rows written through ``record_artifact``, and ledger rows become ``provider_call_ledger`` rows.
Nothing above these protocols changes when that happens.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol

__all__ = [
    "SECRET_HEADERS",
    "SECRET_QUERY_PARAMS",
    "CallOutcome",
    "FileRawSink",
    "JsonlLedger",
    "LedgerPhase",
    "LedgerRow",
    "LedgerSink",
    "MemoryLedger",
    "MemoryRawSink",
    "RawRecord",
    "RawRequest",
    "RawResponse",
    "RawSink",
    "SpendTotals",
    "redact_headers",
    "redact_url",
    "sha256_hex",
]

#: Header names whose value is a credential. Matched case-insensitively and masked *before* a raw
#: record is built, so no code path exists that could write a key to disk (Global Constraint 5).
#:
#: ``x-goog-upload-url`` is not an API key but is a *bearer capability*: the Files API returns it
#: from ``files.start`` and its holder can push bytes into our Gemini storage, on our billing,
#: without any other credential. A raw record is a durable artifact at D1/A7, so it is masked here.
SECRET_HEADERS: frozenset[str] = frozenset(
    {"authorization", "x-token", "x-api-key", "x-goog-api-key", "x-goog-upload-url"}
)

#: Query parameters whose value is a credential. Gemini's native API takes its key as ``?key=``,
#: and its Files API hands back a pre-authorised resumable-upload URL keyed by ``upload_id``.
SECRET_QUERY_PARAMS: frozenset[str] = frozenset({"key", "upload_id"})

_MASK = "***"

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")

#: Matches ``?key=...`` / ``&key=...`` for every credential-bearing parameter name.
_SECRET_QUERY_RE = re.compile(
    r"([?&])(" + "|".join(sorted(SECRET_QUERY_PARAMS)) + r")=[^&#]*", re.IGNORECASE
)

LedgerPhase = Literal["estimate", "result"]
CallOutcome = Literal[
    "estimate", "ok", "client_error", "retry_exhausted", "halted", "transport_error"
]


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Mask every credential-bearing header value (case-insensitive on the name).

    A name in :data:`SECRET_HEADERS` masks the whole value. Every *other* value is still run
    through :func:`redact_url`, because a header value can carry a credential in a URL of its own —
    the Files API answers ``files.start`` with an ``upload_id``-bearing capability URL, and
    redacting only the *request* URL of the next call leaves that first response header verbatim
    on disk. For a value with no credential parameter in it the substitution is a no-op, so this
    costs nothing and closes the class of leak rather than one instance of it.
    """
    return {
        name: (_MASK if name.lower() in SECRET_HEADERS else redact_url(value))
        for name, value in headers.items()
    }


def redact_url(url: str) -> str:
    """Mask the value of any credential-bearing query parameter, leaving the rest byte-identical.

    Done by substitution on the raw query rather than by re-encoding the parsed pairs: a
    re-encoded URL can differ from the one actually sent, and a raw record whose URL is not the
    URL of the call is worse than no record.
    """
    return _SECRET_QUERY_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}={_MASK}", url)


def sha256_hex(body: bytes) -> str:
    """Content address of a body — what a record carries instead of bytes it must not inline."""
    return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True)
class RawRequest:
    """The request as it is safe to persist: URL and headers already redacted.

    ``body_text`` is present only when the body is small enough to inline and is not declared
    binary; otherwise ``body_sha256`` and ``body_bytes`` stand in for it, so a base64-encoded
    audio clip is content-addressed rather than copied into the record (see
    ``calls.MAX_INLINE_REQUEST_CHARS``).
    """

    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body_text: str | None = None
    body_sha256: str | None = None
    body_bytes: int = 0


@dataclass(frozen=True)
class RawResponse:
    """The response as persisted. ``body_text`` only when it decodes as UTF-8 and is not binary."""

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body_text: str | None = None
    body_sha256: str | None = None
    body_bytes: int = 0
    body_path: str | None = None


@dataclass(frozen=True)
class RawRecord:
    """One attempt's full evidence: what was sent, what came back, how long it took."""

    call_id: str
    provider: str
    operation: str
    label: str
    attempt: int
    recorded_at: datetime
    latency_ms: int
    request: RawRequest
    response: RawResponse


@dataclass(frozen=True)
class LedgerRow:
    """One row of the cost ledger — the ``estimate`` phase before the wire, ``result`` after.

    The column set is the R1 shape of the ``provider_call_ledger`` table (master plan §4), so the
    D1/A7 database sink is a different ``LedgerSink`` implementation, not a different row.
    """

    row_id: str
    call_id: str
    phase: LedgerPhase
    provider: str
    operation: str
    label: str
    recorded_at: datetime
    http_status: int | None = None
    latency_ms: int | None = None
    attempts: int = 0
    estimate_usd: Decimal = Decimal(0)
    estimate_credits: Decimal = Decimal(0)
    estimate_media_seconds: int = 0
    cost_usd: Decimal | None = None
    credits: Decimal | None = None
    media_seconds: int | None = None
    over_ceiling: bool = False
    outcome: CallOutcome = "estimate"
    error_code: str | None = None
    provider_request_id: str | None = None
    raw_ref: str | None = None
    extras: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SpendTotals:
    """Running spend across every ``result`` row: real money, provider credits, media seconds."""

    usd: Decimal = Decimal(0)
    credits: Decimal = Decimal(0)
    media_seconds: int = 0


class RawSink(Protocol):
    """Persists one attempt's raw evidence and returns the reference the ledger row cites."""

    def save(self, record: RawRecord, body: bytes) -> str: ...


class LedgerSink(Protocol):
    """Persists one ledger row and returns its ``row_id``."""

    def record(self, row: LedgerRow) -> str: ...


def _json_default(value: object) -> object:
    """Serialise the two non-JSON types a record/row carries: ``Decimal`` and ``datetime``."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _safe_name(text: str) -> str:
    """Make a provider-supplied label safe to use as a path segment."""
    cleaned = _UNSAFE_FILENAME.sub("-", text).strip("-")
    return cleaned or "unlabelled"


class FileRawSink:
    """Writes each attempt as one JSON file, with a ``.bin`` sidecar for a binary body."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def save(self, record: RawRecord, body: bytes) -> str:
        """Law 1's persistence step. Returns the JSON file's path as the ``raw_ref``."""
        directory = self._root / _safe_name(record.provider)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = record.recorded_at.strftime("%Y%m%dT%H%M%S%f")
        stem = f"{stamp}_{_safe_name(record.label)}_a{record.attempt}"
        json_path = directory / f"{stem}.json"
        persisted = record
        if record.response.body_text is None and body:
            binary_path = directory / f"{stem}.bin"
            binary_path.write_bytes(body)
            persisted = replace(
                record, response=replace(record.response, body_path=str(binary_path))
            )
        json_path.write_text(
            json.dumps(asdict(persisted), default=_json_default, indent=2), encoding="utf-8"
        )
        return str(json_path)


class MemoryRawSink:
    """Keeps every ``(record, body)`` in order. ``raw_ref`` is ``memory:<n>``."""

    def __init__(self) -> None:
        self.records: list[tuple[RawRecord, bytes]] = []

    def save(self, record: RawRecord, body: bytes) -> str:
        self.records.append((record, body))
        return f"memory:{len(self.records) - 1}"


class JsonlLedger:
    """Appends one JSON object per row under an exclusive file lock.

    The lock is what makes the ledger safe when several account workers write the same file: an
    interleaved half-line would corrupt the one artifact that answers "what did this run cost".
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def record(self, row: LedgerRow) -> str:
        """Law 1's ledger step. Decimals are written as strings so no precision is lost."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(asdict(row), default=_json_default, sort_keys=True)
        with self._path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.write(line + "\n")
                handle.flush()
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return row.row_id


class MemoryLedger:
    """Keeps rows in a list and can total the ``result`` rows."""

    def __init__(self) -> None:
        self.rows: list[LedgerRow] = []

    def record(self, row: LedgerRow) -> str:
        self.rows.append(row)
        return row.row_id

    def totals(self) -> SpendTotals:
        """Spend across ``result`` rows only — an estimate row is a reservation, not a cost."""
        results = [row for row in self.rows if row.phase == "result"]
        return SpendTotals(
            usd=sum((row.cost_usd or Decimal(0) for row in results), Decimal(0)),
            credits=sum((row.credits or Decimal(0) for row in results), Decimal(0)),
            media_seconds=sum(row.media_seconds or 0 for row in results),
        )
