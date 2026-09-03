"""Workspace-handle DAL (F5 task 14) — the DNS label a workspace's published sites hang off.

Founder ruling R-F5-5 (default): a published site lives at ``{handle}.pages.cluehq.ai/{slug}``.
The handle is DERIVED from the workspace's name, a human may change it while nothing has been
published, and the FIRST PUBLISH LOCKS IT. That lock is the reason this module exists: a public
URL is something a marketer pastes into an email, and the host segment of a URL already in the
world cannot be allowed to move.

Three rules shape every function below.

* **``ensure`` never overwrites.** It is the read every address-building call site makes, on
  every publish and every publish-state GET, so it has to be idempotent in the strong sense: if
  a row exists it is returned untouched, and the derivation from ``workspace.name`` runs exactly
  once in a workspace's life. A human's chosen handle is never clawed back to the default.
* **The default never collides silently.** Two workspaces genuinely named the same thing derive
  the same label; the second one gets ``-<last 4 of its workspace id>`` rather than the first
  one's row. The insert is ``ON CONFLICT DO NOTHING`` and the retry is decided by RE-READING —
  never by letting an IntegrityError poison the caller's transaction.
* **Refusals are typed, and they happen BEFORE the database sees them.** ``handle_locked`` /
  ``handle_invalid`` / ``handle_taken`` are ``ValueError``s the API turns into 409 / 422 / 409.
  A shape violation that reached the CHECK constraint would abort the transaction and surface as
  a 500, which is the wrong answer to "that is not a valid subdomain".

The shape itself is a hostname segment — lowercase alphanumerics with inner dashes, 1 or 3..63
characters — and it is enforced twice on purpose: here, so the caller gets a domain error, and
by ``design_workspace_handle_shape``, so nothing else can ever store an unroutable label.

Reserved labels are refused outright: they are the names the hosting domain needs for itself,
and a tenant who took ``www`` or ``api`` would shadow infrastructure rather than get a site.

Callers own the transaction (one logical operation = one transaction — the O5 rule); nothing
here commits.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, iso

__all__ = [
    "RESERVED_HANDLES",
    "ensure_workspace_handle",
    "get_workspace_by_handle",
    "get_workspace_handle",
    "lock_workspace_handle",
    "set_workspace_handle",
    "shape_handle",
]

#: Labels the hosting domain needs for itself. A tenant holding one of these would shadow
#: infrastructure (``www.pages…``, ``api.pages…``) rather than own a site.
RESERVED_HANDLES = frozenset({"www", "app", "api", "admin", "pages", "static", "assets", "mail"})

#: The DNS-label contract, mirroring ``design_workspace_handle_shape`` exactly. Note that a
#: two-character label is NOT valid under it (the optional group needs at least three): the
#: shaper below therefore never produces one.
HANDLE_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$")

_MAX_LABEL = 63


def _id_suffix(workspace_id: str) -> str:
    """The disambiguating tail: the last four alphanumerics of the workspace id.

    Opaque on purpose. It exists to break a tie between two identically-named workspaces, and a
    handle is public — leaking a readable fragment of internal identity into a hostname would be
    a worse trade than four hex characters.
    """
    tail = re.sub(r"[^a-z0-9]+", "", (workspace_id or "")[-4:].lower())
    return tail or "0000"


def shape_handle(value: str | None, *, workspace_id: str) -> str:
    """Fold arbitrary text into a valid DNS label. Total: it ALWAYS returns a storable handle.

    Used only for the DERIVED default (a workspace name is prose — ``"Acme Robotics, Inc."``);
    a handle a human typed is validated, never silently reshaped, by
    :func:`set_workspace_handle`. Too short (or empty) is padded with the workspace-id suffix
    rather than rejected, because there is no caller to report a refusal to: this runs while
    minting a workspace's first address.
    """
    label = re.sub(r"[^a-z0-9]+", "-", (value or "").lower())
    label = re.sub(r"-+", "-", label).strip("-")[:_MAX_LABEL].strip("-")
    if len(label) < 3:
        label = f"{label}-{_id_suffix(workspace_id)}".strip("-")[:_MAX_LABEL]
    return label


def _suffixed(handle: str, workspace_id: str) -> str:
    """``handle-<id suffix>``, clamped so the result is still a legal label."""
    suffix = _id_suffix(workspace_id)
    base = handle[: _MAX_LABEL - len(suffix) - 1].strip("-")
    return f"{base}-{suffix}" if base else suffix


def _from_row(row: Any) -> JsonObject:
    return {
        "workspace_id": row.workspace_id,
        "handle": row.handle,
        # The derived boolean the API and the editor actually branch on; ``locked_at`` stays
        # available for "since when?".
        "locked": row.locked_at is not None,
        "locked_at": iso(row.locked_at),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


async def get_workspace_handle(conn: AsyncConnection, *, workspace_id: str) -> JsonObject | None:
    """This workspace's handle row, or ``None`` when it has never had one."""
    row = (
        await conn.execute(
            text("SELECT * FROM design_workspace_handle WHERE workspace_id = :w"),
            {"w": workspace_id},
        )
    ).first()
    return None if row is None else _from_row(row)


async def ensure_workspace_handle(
    conn: AsyncConnection, *, workspace_id: str, default_from: str | None = None
) -> JsonObject:
    """The workspace's handle, minting the derived default the first time.

    ``default_from`` defaults to the platform ``workspace.name`` — the handle is derived from
    what a human called the workspace, not from its opaque id. An unknown workspace (no row) or
    a nameless one still gets a handle, from the id suffix alone; refusing here would mean a
    publish could not name where it just put a site.

    Idempotent in the strong sense: an existing row is returned UNCHANGED, so the two address
    call sites (publish, publish-state) can call this on every request without ever undoing a
    rename. The derived default is tried once, and once more with ``-<id suffix>`` if the bare
    label is already somebody else's; a reserved default skips straight to the suffixed form,
    since the plain word is not available to any tenant.
    """
    existing = await get_workspace_handle(conn, workspace_id=workspace_id)
    if existing is not None:
        return existing

    source = default_from
    if source is None:
        row = (
            await conn.execute(
                text("SELECT name FROM workspace WHERE workspace_id = :w"),
                {"w": workspace_id},
            )
        ).first()
        source = None if row is None else row.name

    candidate = shape_handle(source, workspace_id=workspace_id)
    suffixed = _suffixed(candidate, workspace_id)
    # The last resort is the shaped WORKSPACE ID, which is unique by construction. It exists
    # because ``ensure`` is on the publish path: a workspace whose name AND whose four-character
    # tie-break were both already taken would otherwise fail its every publish with a 500,
    # permanently. Two same-named workspaces whose ids share their last four characters is a
    # birthday collision, not a fantasy, so the fallback is cheap insurance for an ugly failure.
    attempts = [suffixed] if candidate in RESERVED_HANDLES else [candidate, suffixed]
    attempts.append(shape_handle(workspace_id, workspace_id=workspace_id))
    for handle in attempts:
        inserted = (
            await conn.execute(
                text(
                    "INSERT INTO design_workspace_handle (workspace_id, handle)"
                    " VALUES (:w, :h) ON CONFLICT DO NOTHING RETURNING *"
                ),
                {"w": workspace_id, "h": handle},
            )
        ).first()
        if inserted is not None:
            return _from_row(inserted)
        # ``DO NOTHING`` swallowed either conflict. Re-reading tells us which: our own row
        # exists (a concurrent ensure won the race — its answer is the answer), or the label
        # belongs to somebody else and the next attempt disambiguates it.
        concurrent = await get_workspace_handle(conn, workspace_id=workspace_id)
        if concurrent is not None:
            return concurrent
    raise ValueError("handle_taken")


async def set_workspace_handle(
    conn: AsyncConnection, *, workspace_id: str, handle: str
) -> JsonObject:
    """Choose the handle. Refused once the first publish has locked it.

    Whitespace is trimmed and the label is lowercased — a DNS label is case-insensitive by
    definition, so that is normalization, not a guess at what the caller meant — and everything
    else is validated, never reshaped: a caller who typed ``"Acme Robotics"`` gets
    ``handle_invalid`` and a chance to choose, rather than a silent ``acme-robotics`` they never
    asked for and would have to discover from the URL.

    Raises ``ValueError`` with ``handle_invalid`` (reserved or not a DNS label),
    ``handle_locked`` (already published) or ``handle_taken`` (another workspace has it).
    """
    normalized = (handle or "").strip().lower()
    if normalized in RESERVED_HANDLES or not HANDLE_PATTERN.match(normalized):
        raise ValueError("handle_invalid")

    current = await ensure_workspace_handle(conn, workspace_id=workspace_id)
    if current["locked"]:
        raise ValueError("handle_locked")
    if current["handle"] == normalized:
        return current

    # Checked rather than caught: a UNIQUE violation would abort the caller's whole transaction,
    # and this refusal has to leave the rest of the request intact. The constraint remains the
    # hard backstop for the (tiny, human-paced) race between this read and the UPDATE.
    owner = await get_workspace_by_handle(conn, handle=normalized)
    if owner is not None and owner != workspace_id:
        raise ValueError("handle_taken")

    row = (
        await conn.execute(
            text(
                "UPDATE design_workspace_handle SET handle = :h, updated_at = now()"
                " WHERE workspace_id = :w AND locked_at IS NULL RETURNING *"
            ),
            {"w": workspace_id, "h": normalized},
        )
    ).first()
    if row is None:
        # Only reachable if the row was locked between the read above and this write — i.e. a
        # publish landed mid-request. Same answer either way.
        raise ValueError("handle_locked")
    return _from_row(row)


async def lock_workspace_handle(conn: AsyncConnection, *, workspace_id: str) -> JsonObject:
    """Freeze the handle at the first publish. Idempotent, and it MINTS one if none exists.

    A publish must never be able to serve a site off a handle that is not durably fixed, so this
    cannot presuppose a row: it ensures first, then locks. Called on every successful publish,
    which is why re-locking must be a no-op — the second publish would otherwise move
    ``locked_at`` forward and lose when the address actually became public.
    """
    current = await ensure_workspace_handle(conn, workspace_id=workspace_id)
    if current["locked"]:
        return current
    row = (
        await conn.execute(
            text(
                "UPDATE design_workspace_handle SET locked_at = now(), updated_at = now()"
                " WHERE workspace_id = :w AND locked_at IS NULL RETURNING *"
            ),
            {"w": workspace_id},
        )
    ).first()
    if row is None:  # locked concurrently; re-read is the honest answer
        return await ensure_workspace_handle(conn, workspace_id=workspace_id)
    return _from_row(row)


async def get_workspace_by_handle(conn: AsyncConnection, *, handle: str) -> str | None:
    """``handle -> workspace_id``, or ``None`` — the public host router's reverse lookup.

    The one function here that is deliberately NOT workspace-scoped: resolving which tenant a
    request's host belongs to is precisely its job, and it runs before any workspace is known.
    An unknown handle answers ``None`` (a 404 for the visitor) rather than raising.
    """
    row = (
        await conn.execute(
            text("SELECT workspace_id FROM design_workspace_handle WHERE handle = :h"),
            {"h": (handle or "").strip().lower()},
        )
    ).first()
    return None if row is None else row.workspace_id
