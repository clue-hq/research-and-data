"""Workspace hostnames — the registry that turns a public hostname into a workspace.

Custom-domain publishing (design 2026-09-17 §4.1). Two kinds of row live in ``workspace_hostname``:
``system`` rows (``<label>.<suffix>``, one per workspace, always active — they ARE the
workspace-slug registry) and ``custom`` rows (one customer-owned subdomain per workspace, with a
Cloudflare lifecycle owned by the S2 control plane). Everything public begins with
:func:`resolve_active_hostname`.

The pure helpers (label allocation, hostname normalisation, public origin) have no I/O so the
control plane, the backfill and the design API share one validator. The DAL follows the spine's
raw-SQL style: functions over ``AsyncConnection``, the caller owns the transaction.

Import discipline (Rule 2c): only ``clue_core`` + ``clue_db``-level dependencies — the system suffix
therefore arrives as a parameter (default :data:`DEFAULT_PAGES_SYSTEM_SUFFIX`), never from settings.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection, Iterator
from itertools import count
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import UtcDatetime

DEFAULT_PAGES_SYSTEM_SUFFIX = "pages.cluehq.ai"

HostnameKind = Literal["system", "custom"]
HostnameStatus = Literal[
    "pending_dns", "verifying_ownership", "issuing_certificate", "active", "error", "disconnecting"
]

LABEL_MIN = 3
LABEL_MAX = 40
RESERVED_LABELS: frozenset[str] = frozenset(
    {
        "app",
        "api",
        "www",
        "pages",
        "page-origin",
        "mail",
        "admin",
        "share",
        "static",
        "assets",
        "cdn",
        "status",
        "help",
        "docs",
        "dev",
        "staging",
        "test",
        "clue",
        "cluehq",
        "login",
        "auth",
        "mcp",
    }
)

_HOSTNAME_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOSTNAME_SHAPE = re.compile(rf"^{_HOSTNAME_LABEL}(?:\.{_HOSTNAME_LABEL})*$")


class WorkspaceHostname(BaseModel):
    """A ``workspace_hostname`` row (the columns S1 reads; S2 widens for the custom lifecycle)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hostname: str
    workspace_id: str
    kind: HostnameKind
    status: HostnameStatus
    created_at: UtcDatetime
    activated_at: UtcDatetime | None = None


# --- pure helpers -----------------------------------------------------------
def slugify_label(name: str) -> str:
    """NFKD-fold to ASCII, lowercase, runs of non ``[a-z0-9]`` → one hyphen, hyphens trimmed."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")


def _workspace_fragment(workspace_id: str) -> str:
    digits = re.sub(r"[^a-z0-9]", "", workspace_id.lower().removeprefix("ws_"))
    return f"ws-{digits[:8]:0<8}"


def _cut(label: str, limit: int) -> str:
    if len(label) <= limit:
        return label
    cut = label[:limit]
    hyphen = cut.rfind("-")
    if hyphen >= LABEL_MIN:
        cut = cut[:hyphen]
    return cut.strip("-")


def label_candidates(name: str, workspace_id: str) -> Iterator[str]:
    """The ordered, infinite candidate list for a workspace's system label (spec §4.1)."""
    base = slugify_label(name)
    if len(base) < LABEL_MIN:
        base = _workspace_fragment(workspace_id)
    base = _cut(base, LABEL_MAX)
    if base not in RESERVED_LABELS:
        yield base
    for n in count(2):
        suffix = f"-{n}"
        yield f"{_cut(base, LABEL_MAX - len(suffix))}{suffix}"


def allocate_label(name: str, taken: Collection[str], *, workspace_id: str) -> str:
    """The first candidate not in ``taken`` (pure; the DAL loop is the DB-backed twin)."""
    for candidate in label_candidates(name, workspace_id):
        if candidate not in taken:
            return candidate
    raise AssertionError("unreachable: label_candidates is infinite")


def normalize_hostname(value: str) -> str:
    """Lowercase, trailing dot stripped, IDNA-encoded; raises ``ValueError`` when not a hostname."""
    stripped = value.strip().rstrip(".").lower()
    if not stripped:
        raise ValueError("hostname is empty")
    try:
        encoded = stripped.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ValueError(f"hostname {value!r} is not IDNA-encodable") from error
    if len(encoded) > 253 or not _HOSTNAME_SHAPE.fullmatch(encoded):
        raise ValueError(f"hostname {value!r} is not a valid hostname")
    return encoded


def is_valid_hostname(value: str) -> bool:
    try:
        normalize_hostname(value)
    except ValueError:
        return False
    return True


def public_origin(hostname: str, *, scheme: str, port: int | None) -> str:
    """``https://acme.pages.cluehq.ai`` or, in dev, ``http://acme.pages.localhost:8040``."""
    return f"{scheme}://{hostname}" + (f":{port}" if port else "")


# --- DAL --------------------------------------------------------------------
_ROW = "hostname, workspace_id, kind, status, created_at, activated_at"


async def _system_row(conn: AsyncConnection, workspace_id: str) -> WorkspaceHostname | None:
    result = await conn.execute(
        text(f"SELECT {_ROW} FROM workspace_hostname WHERE workspace_id = :w AND kind = 'system'"),
        {"w": workspace_id},
    )
    row = result.mappings().first()
    return WorkspaceHostname(**dict(row)) if row is not None else None


async def ensure_system_hostname(
    conn: AsyncConnection, *, workspace_id: str, name: str, suffix: str
) -> WorkspaceHostname:
    """The ONE allocator. Returns the workspace's system row, inserting it on first call.

    Idempotent and race-safe: an existing row wins outright; a hostname collision moves to the
    next candidate (``ON CONFLICT (hostname) DO NOTHING``); losing the one-system-per-workspace
    race re-reads the winner. Each attempt runs in a savepoint so a conflict never poisons the
    caller's transaction. Called by :func:`clue_spine.create_workspace`, the backfill command and
    the design API's dev workspace scaffolding, so every creator gets a row without knowing about
    it.
    """
    existing = await _system_row(conn, workspace_id)
    if existing is not None:
        return existing
    for label in label_candidates(name, workspace_id):
        hostname = f"{label}.{suffix}"
        try:
            async with conn.begin_nested():
                result = await conn.execute(
                    text(
                        "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, "
                        "activated_at) VALUES (:h, :w, 'system', 'active', now()) "
                        f"ON CONFLICT (hostname) DO NOTHING RETURNING {_ROW}"
                    ),
                    {"h": hostname, "w": workspace_id},
                )
                row = result.mappings().first()
        except IntegrityError:
            winner = await _system_row(conn, workspace_id)
            if winner is not None:
                return winner
            raise
        if row is not None:
            return WorkspaceHostname(**dict(row))
    raise AssertionError("unreachable: label_candidates is infinite")


async def system_hostname(conn: AsyncConnection, workspace_id: str) -> str | None:
    row = await _system_row(conn, workspace_id)
    return row.hostname if row is not None else None


async def active_custom_hostname(conn: AsyncConnection, workspace_id: str) -> str | None:
    result = await conn.execute(
        text(
            "SELECT hostname FROM workspace_hostname "
            "WHERE workspace_id = :w AND kind = 'custom' AND status = 'active'"
        ),
        {"w": workspace_id},
    )
    row = result.first()
    return str(row[0]) if row is not None else None


async def resolve_active_hostname(conn: AsyncConnection, hostname: str) -> str | None:
    """hostname → workspace_id, for ACTIVE rows only (a provisioning custom hostname is 404)."""
    result = await conn.execute(
        text(
            "SELECT workspace_id FROM workspace_hostname WHERE hostname = :h AND status = 'active'"
        ),
        {"h": hostname},
    )
    row = result.first()
    return str(row[0]) if row is not None else None


async def workspaces_without_system_hostname(conn: AsyncConnection) -> list[tuple[str, str]]:
    result = await conn.execute(
        text(
            "SELECT w.workspace_id, w.name FROM workspace w "
            "WHERE NOT EXISTS (SELECT 1 FROM workspace_hostname h "
            "WHERE h.workspace_id = w.workspace_id AND h.kind = 'system') "
            "ORDER BY w.created_at, w.workspace_id"
        )
    )
    return [(str(r[0]), str(r[1])) for r in result.all()]


async def system_hostnames_off_suffix(conn: AsyncConnection, suffix: str) -> list[str]:
    """System rows not ending in ``.<suffix>`` — a config error to warn about at startup."""
    result = await conn.execute(
        text(
            "SELECT hostname FROM workspace_hostname WHERE kind = 'system' "
            "AND hostname NOT LIKE :pattern ORDER BY hostname"
        ),
        {"pattern": f"%.{suffix}"},
    )
    return [str(r[0]) for r in result.all()]
