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
from collections.abc import Collection, Iterator, Sequence
from datetime import datetime
from itertools import count
from typing import Literal

import tldextract
from pydantic import BaseModel, ConfigDict
from sqlalchemy import bindparam, text
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
        # Review finding K3-8: the site editor's own subdomain (edit.<domain>).
        "edit",
        "editor",
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
    # Set by the workspace's first publish (:func:`lock_system_hostname`); NULL = never published.
    # Only ever set on a system row; a locked label refuses :func:`replace_system_label`.
    locked_at: UtcDatetime | None = None


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


# --- custom hostnames: validation (spec §7.3) --------------------------------
_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), fallback_to_snapshot=True)
_LABEL_SHAPE = re.compile(rf"^[a-z0-9](?:[a-z0-9-]{{{LABEL_MIN - 2},{LABEL_MAX - 2}}}[a-z0-9])$")


class HostnameRefused(ValueError):
    """A hostname or label the control plane refuses, with its closed-set code (spec §7.3)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def registrable_domain(hostname: str) -> str:
    """The public-suffix registrable domain (``acme.co.uk`` for ``go.acme.co.uk``). Offline: the
    bundled snapshot only, never a network fetch. An unknown suffix falls back to the last two
    labels."""
    parts = _EXTRACT(hostname)
    if parts.suffix and parts.domain:
        return f"{parts.domain}.{parts.suffix}"
    labels = hostname.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else hostname


def parse_suffixes(raw: str) -> tuple[str, ...]:
    """A comma-separated suffix list from the environment, lowercased, without empty entries."""
    return tuple(
        dict.fromkeys(
            part.strip().lower().strip(".") for part in raw.split(",") if part.strip().strip(".")
        )
    )


def validate_custom_hostname(
    value: str, *, system_suffix: str, legacy_suffixes: Sequence[str] = ()
) -> str:
    """Normalise and refuse with the spec §7.3 codes. Returns the normalised hostname.

    Order is invalid → reserved → apex. Our own zone apexes match BOTH the apex rule and the
    reserved rule, and must report ``hostname_reserved`` — "this is ours", not "pick a subdomain",
    since no subdomain of them can be connected either. Reserved is the narrower rule and is tested
    first. Wave 2 Contract 9: the registrable domain of the system suffix AND of every legacy
    suffix is reserved, so ``cluehq.ai`` stays unconnectable after published pages move to their
    own domain.
    """
    try:
        hostname = normalize_hostname(value)
    except ValueError as error:
        raise HostnameRefused("hostname_invalid", f"{value!r} is not a valid hostname") from error
    for ours in dict.fromkeys(
        registrable_domain(suffix) for suffix in (system_suffix, *legacy_suffixes) if suffix
    ):
        if hostname == ours or hostname.endswith("." + ours):
            raise HostnameRefused(
                "hostname_reserved", f"Hostnames under {ours} cannot be connected."
            )
    registrable = registrable_domain(hostname)
    if hostname == registrable:
        raise HostnameRefused(
            "hostname_is_apex",
            f"A dedicated subdomain such as go.{registrable} is required; the bare domain "
            f"{registrable} cannot be connected.",
        )
    return hostname


def validate_label(label: str) -> str:
    """A Clue-address label an admin picks by hand (spec §4.1 A1): 3–40 of ``[a-z0-9-]``, no edge
    hyphen, not reserved."""
    if not _LABEL_SHAPE.fullmatch(label):
        raise HostnameRefused(
            "label_invalid",
            "Use 3–40 lowercase letters, digits or hyphens, not starting or ending with a hyphen.",
        )
    if label in RESERVED_LABELS:
        raise HostnameRefused("label_reserved", f"{label!r} is reserved.")
    return label


# --- DAL --------------------------------------------------------------------
_ROW = "hostname, workspace_id, kind, status, created_at, activated_at, locked_at"


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


async def backfill_system_hostnames(
    conn: AsyncConnection, *, suffix: str, dry_run: bool = False
) -> dict[str, int]:
    """Give every workspace without a system row one (idempotent; safe to re-run at deploy)."""
    missing = await workspaces_without_system_hostname(conn)
    written = 0
    if not dry_run:
        for workspace_id, name in missing:
            await ensure_system_hostname(conn, workspace_id=workspace_id, name=name, suffix=suffix)
            written += 1
    off_suffix = await system_hostnames_off_suffix(conn, suffix)
    return {"missing": len(missing), "written": written, "off_suffix": len(off_suffix)}


async def move_system_hostnames(
    conn: AsyncConnection, *, from_suffix: str, to_suffix: str, apply: bool = False
) -> dict[str, object]:
    """Rewrite every system hostname under ``from_suffix`` to the same label under ``to_suffix``
    (Wave 2 Contract 9). The label is kept, so ``locked_at`` keeps its promise; the old host keeps
    answering through the edge Worker's 301. A dry run unless ``apply``; it refuses to write when
    any new hostname is already taken, and then nothing moves."""
    old = from_suffix.lower().strip(".")
    new = to_suffix.lower().strip(".")
    if not old or not new or old == new:
        raise ValueError("from_suffix and to_suffix must be non-empty and different")
    rows = await conn.execute(
        text(
            "SELECT hostname FROM workspace_hostname WHERE kind = 'system' "
            "AND right(hostname, :n) = :tail ORDER BY hostname"
        ),
        {"n": len(old) + 1, "tail": "." + old},
    )
    moves = [(str(row[0]), str(row[0])[: -len(old)] + new) for row in rows.all()]
    collisions: list[str] = []
    if moves:
        taken = await conn.execute(
            text("SELECT hostname FROM workspace_hostname WHERE hostname IN :targets").bindparams(
                bindparam("targets", expanding=True)
            ),
            {"targets": [target for _old, target in moves]},
        )
        collisions = sorted(str(row[0]) for row in taken.all())
    applied = bool(apply and moves and not collisions)
    if applied:
        for previous, target in moves:
            await conn.execute(
                text(
                    "UPDATE workspace_hostname SET hostname = :new, updated_at = now() "
                    "WHERE hostname = :old AND kind = 'system'"
                ),
                {"new": target, "old": previous},
            )
    return {
        "from_suffix": old,
        "to_suffix": new,
        "rows": len(moves),
        "collisions": collisions,
        "applied": applied,
        "sample": [{"from": previous, "to": target} for previous, target in moves[:5]],
    }


# --- custom hostnames: DAL (spec §4.1, §7) -----------------------------------
_CUSTOM_ROW = (
    "hostname, workspace_id, status, cf_custom_hostname_id, cname_target, ownership_txt_name, "
    "ownership_txt_value, observed_cname, observed_txt_present, last_checked_at, last_error_code, "
    "last_error_detail, created_at, updated_at, activated_at"
)


class CustomHostname(BaseModel):
    """A ``custom`` ``workspace_hostname`` row — the whole Cloudflare lifecycle (spec §7)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hostname: str
    workspace_id: str
    status: HostnameStatus
    cf_custom_hostname_id: str | None
    cname_target: str
    ownership_txt_name: str
    ownership_txt_value: str
    observed_cname: str | None
    observed_txt_present: bool | None
    last_checked_at: UtcDatetime | None
    last_error_code: str | None
    last_error_detail: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    activated_at: UtcDatetime | None


async def get_custom_hostname(conn: AsyncConnection, workspace_id: str) -> CustomHostname | None:
    result = await conn.execute(
        text(
            f"SELECT {_CUSTOM_ROW} FROM workspace_hostname "
            "WHERE workspace_id = :w AND kind = 'custom'"
        ),
        {"w": workspace_id},
    )
    row = result.mappings().first()
    return CustomHostname(**dict(row)) if row is not None else None


async def hostname_exists(conn: AsyncConnection, hostname: str) -> bool:
    result = await conn.execute(
        text("SELECT 1 FROM workspace_hostname WHERE hostname = :h"), {"h": hostname}
    )
    return result.first() is not None


async def insert_custom_hostname(
    conn: AsyncConnection, *, workspace_id: str, hostname: str, cname_target: str
) -> CustomHostname:
    """The connect insert (spec §7.3): ``pending_dns`` with placeholder ownership columns so the
    ``workspace_hostname_custom_columns`` CHECK holds until Cloudflare answers. The primary key and
    the one-custom-per-workspace index are the arbiters — a loser gets ``IntegrityError``."""
    result = await conn.execute(
        text(
            "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, cname_target, "
            "ownership_txt_name, ownership_txt_value) VALUES (:h, :w, 'custom', 'pending_dns', :t, "
            f"'pending', 'pending') RETURNING {_CUSTOM_ROW}"
        ),
        {"h": hostname, "w": workspace_id, "t": cname_target},
    )
    return CustomHostname(**dict(result.mappings().one()))


async def set_custom_hostname_provider(
    conn: AsyncConnection,
    *,
    hostname: str,
    cf_custom_hostname_id: str,
    ownership_txt_name: str,
    ownership_txt_value: str,
) -> None:
    """Stamp what Cloudflare answered with (its id and the ownership TXT record to publish)."""
    await conn.execute(
        text(
            "UPDATE workspace_hostname SET cf_custom_hostname_id = :i, ownership_txt_name = :n, "
            "ownership_txt_value = :v, updated_at = now() WHERE hostname = :h AND kind = 'custom'"
        ),
        {
            "i": cf_custom_hostname_id,
            "n": ownership_txt_name,
            "v": ownership_txt_value,
            "h": hostname,
        },
    )


async def record_custom_hostname_check(
    conn: AsyncConnection,
    *,
    hostname: str,
    status: HostnameStatus,
    observed_cname: str | None,
    observed_txt_present: bool | None,
    last_error_code: str | None,
    last_error_detail: str | None,
    checked_at: datetime,
) -> CustomHostname:
    """Record one status derivation (spec §7.4). ``activated_at`` is stamped the FIRST time the
    hostname reaches ``active`` and never moved again."""
    result = await conn.execute(
        text(
            "UPDATE workspace_hostname SET status = :s, observed_cname = :c, "
            "observed_txt_present = :p, last_checked_at = :at, last_error_code = :ec, "
            "last_error_detail = :ed, updated_at = now(), activated_at = CASE WHEN :s = 'active' "
            "THEN COALESCE(activated_at, now()) ELSE activated_at END "
            f"WHERE hostname = :h AND kind = 'custom' RETURNING {_CUSTOM_ROW}"
        ),
        {
            "s": status,
            "c": observed_cname,
            "p": observed_txt_present,
            "at": checked_at,
            "ec": last_error_code,
            "ed": last_error_detail,
            "h": hostname,
        },
    )
    return CustomHostname(**dict(result.mappings().one()))


async def set_custom_hostname_status(
    conn: AsyncConnection, *, hostname: str, status: HostnameStatus
) -> None:
    await conn.execute(
        text(
            "UPDATE workspace_hostname SET status = :s, updated_at = now() "
            "WHERE hostname = :h AND kind = 'custom'"
        ),
        {"s": status, "h": hostname},
    )


async def delete_custom_hostname(conn: AsyncConnection, *, hostname: str) -> bool:
    """Disconnect (spec §7): the row goes, the hostname is free. ``False`` when nothing matched."""
    result = await conn.execute(
        text("DELETE FROM workspace_hostname WHERE hostname = :h AND kind = 'custom'"),
        {"h": hostname},
    )
    return bool(result.rowcount)


async def lock_system_hostname(conn: AsyncConnection, *, workspace_id: str) -> WorkspaceHostname:
    """First publish freezes the label (F5 R-F5-5, adopted 2026-09-28): a published URL is out in
    the world, so its host segment must not move. Idempotent: an already-locked row keeps its
    original ``locked_at``."""
    result = await conn.execute(
        text(
            "UPDATE workspace_hostname SET locked_at = COALESCE(locked_at, now()), "
            f"updated_at = now() WHERE workspace_id = :w AND kind = 'system' RETURNING {_ROW}"
        ),
        {"w": workspace_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HostnameRefused(
            "system_hostname_missing",
            f"Workspace {workspace_id!r} has no system hostname; "
            "run `make pages-backfill-hostnames`.",
        )
    return WorkspaceHostname(**dict(row))


async def replace_system_label(
    conn: AsyncConnection, *, workspace_id: str, label: str, suffix: str
) -> WorkspaceHostname:
    """Label change (spec §4.1, A1): delete the old system row and insert the new one in ONE
    transaction. The old label is free immediately; there is no redirect. Refused with
    ``label_locked`` once the workspace has published (:func:`lock_system_hostname`)."""
    validate_label(label)
    # FOR UPDATE: a concurrent first publish (lock_system_hostname) waits for this transaction or
    # this read waits for it — the label can never be swapped out from under a publish.
    locked = await conn.execute(
        text(
            "SELECT locked_at FROM workspace_hostname WHERE workspace_id = :w AND kind = 'system' "
            "FOR UPDATE"
        ),
        {"w": workspace_id},
    )
    if locked.scalar() is not None:
        raise HostnameRefused(
            "label_locked", "This address has already published a site, so its label is fixed."
        )
    hostname = f"{label}.{suffix}"
    try:
        async with conn.begin_nested():
            await conn.execute(
                text("DELETE FROM workspace_hostname WHERE workspace_id = :w AND kind = 'system'"),
                {"w": workspace_id},
            )
            result = await conn.execute(
                text(
                    "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, "
                    f"activated_at) VALUES (:h, :w, 'system', 'active', now()) RETURNING {_ROW}"
                ),
                {"h": hostname, "w": workspace_id},
            )
    except IntegrityError as error:
        raise HostnameRefused("label_taken", f"{label!r} is already in use.") from error
    return WorkspaceHostname(**dict(result.mappings().one()))
