"""Fragment-registry DAL (clone-fidelity F1.2) — what one cloned section IS, kept.

``design_web_fragment`` holds one row per verbatim cloned website section: the digest of its
immutable artifact payload, the digest of its preview image, and the provenance that says which
brand kit, which page and which role it came from. The BYTES are not here — the payload is one
content-addressed JSON blob in the design blob namespace behind
:func:`clue_design.storage.register_design_bytes` under ``source_key = "design_web_fragment"``,
which is what makes re-harvesting an unchanged section cost one row and no bytes.

**The id is the content.** ``fragment_id`` is ``frag_`` plus the first sixteen hex characters of
the sha256 over the artifact's canonical identity, so creation is the ONLY payload write: a
re-mint of the same section converges onto the row it already wrote, and a section that changed
at all is a different fragment. The single mutable column is ``status`` (draft / approved /
deprecated — row-level metadata about whether a human has blessed the section for reuse), and
the database enforces that split with a trigger, so this module is deliberately INSERT-plus-
status-only.

Workspace-scoped and fail-closed like the rest of the DAL: a foreign-workspace fragment id
raises the same :class:`DesignNotFoundError` an absent one does, so existence never leaks across
tenants — which matters more here than usual, because the id is a global content address and a
neighbour who cloned the same public section holds the same id.

Callers own the transaction (one logical operation, one transaction — the O5 rule); nothing here
commits.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, iso, load_json
from clue_design.errors import DesignNotFoundError

#: The row-level lifecycle, mirroring ``design_brand_approval_status`` (see the migration's
#: docstring for why ``generated_unreviewed`` is not among them). Kept here as the ONE Python
#: spelling of the CHECK the migration installs.
FRAGMENT_STATUSES = ("draft", "approved", "deprecated")

_COLUMNS = (
    "fragment_id, workspace_id, source_kit_id, source_kit_version, source_url, section_role, "
    "label, status, payload_digest, preview_digest, provenance_json, created_at, updated_at"
)


def _from_row(row: Any) -> JsonObject:
    return {
        "fragment_id": row.fragment_id,
        "workspace_id": row.workspace_id,
        "source_kit_id": row.source_kit_id,
        "source_kit_version": row.source_kit_version,
        "source_url": row.source_url,
        "section_role": row.section_role,
        "label": row.label,
        "status": row.status,
        "payload_digest": row.payload_digest,
        "preview_digest": row.preview_digest,
        "provenance": load_json(row.provenance_json),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


async def insert_web_fragment(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    fragment_id: str,
    source_kit_id: str | None,
    source_kit_version: int | None,
    source_url: str,
    section_role: str,
    label: str | None,
    payload_digest: str,
    preview_digest: str | None,
    provenance: JsonObject,
) -> JsonObject:
    """Register one minted fragment. Re-registering the same id in the same workspace CONVERGES.

    ``ON CONFLICT DO NOTHING`` rather than an equal-content check: the id is derived from the
    payload, so a second insert under the same id is the same section by construction, and the
    only fields it could differ on are provenance (which harvest saw it) and the human label.
    First writer wins those — re-recording them would be an UPDATE, which the table's trigger
    refuses anyway, and losing a duplicate harvest's provenance is a smaller harm than making the
    second harvest fail.

    **The kit binding is the one exception, and it has to be.** It is not content — it records
    which capture minted this section, and it is what the brand-kit approval flow reads to decide
    whose approval releases it. Under first-writer-wins, re-ingesting a site published kit
    version 2 while the converged row still named version 1, so approving version 2 flipped
    nothing and the fragment sat ``draft`` with no surface able to release it. So the binding
    moves FORWARD: an unbound row takes the offered kit, and a row bound to an earlier version of
    the SAME lineage advances to the newer one. It never moves sideways into a different lineage
    (that is another brand's approval authority, not a newer version of this one's) and never
    backwards. ``status`` is untouched by the rebinding — the new kit's own approval decides that.
    """
    await conn.execute(
        text(
            """
            INSERT INTO design_web_fragment
              (fragment_id, workspace_id, source_kit_id, source_kit_version, source_url,
               section_role, label, payload_digest, preview_digest, provenance_json)
            VALUES
              (:fragment_id, :workspace_id, :source_kit_id, :source_kit_version, :source_url,
               :section_role, :label, :payload_digest, :preview_digest,
               CAST(:provenance AS jsonb))
            ON CONFLICT (fragment_id, workspace_id) DO NOTHING
            """
        ),
        {
            "fragment_id": fragment_id,
            "workspace_id": workspace_id,
            "source_kit_id": source_kit_id,
            "source_kit_version": source_kit_version,
            "source_url": source_url,
            "section_role": section_role,
            "label": label,
            "payload_digest": payload_digest,
            "preview_digest": preview_digest,
            "provenance": dump_json(provenance),
        },
    )
    row = await get_web_fragment(conn, workspace_id=workspace_id, fragment_id=fragment_id)
    if _kit_binding_advances(row, source_kit_id, source_kit_version):
        await conn.execute(
            text(
                """
                UPDATE design_web_fragment
                SET source_kit_id = :source_kit_id,
                    source_kit_version = :source_kit_version,
                    updated_at = now()
                WHERE fragment_id = :fragment_id AND workspace_id = :workspace_id
                """
            ),
            {
                "source_kit_id": source_kit_id,
                "source_kit_version": source_kit_version,
                "fragment_id": fragment_id,
                "workspace_id": workspace_id,
            },
        )
        row = await get_web_fragment(conn, workspace_id=workspace_id, fragment_id=fragment_id)
    return row


def _kit_binding_advances(
    row: JsonObject, source_kit_id: str | None, source_kit_version: int | None
) -> bool:
    """Is the offered kit binding a step FORWARD from the one this row already holds?

    Three answers, and the two ``False`` ones matter as much as the ``True``: nothing offered
    changes nothing; a different lineage is a different brand's decision, not a newer version of
    this one's; and an older version of the same lineage is a re-run of history, which must not
    drag an already-advanced row backwards.
    """
    if source_kit_id is None or source_kit_version is None:
        return False
    held_id = row.get("source_kit_id")
    held_version = row.get("source_kit_version")
    if held_id is None or held_version is None:
        return True
    return held_id == source_kit_id and int(source_kit_version) > int(held_version)


async def get_web_fragment(
    conn: AsyncConnection, *, workspace_id: str, fragment_id: str
) -> JsonObject:
    """One fragment row, or the fail-closed refusal (absent OR another tenant's)."""
    row = await find_web_fragment(
        conn, workspace_id=workspace_id, fragment_id=fragment_id
    )
    if row is None:
        raise DesignNotFoundError("design_web_fragment", fragment_id)
    return row


async def find_web_fragment(
    conn: AsyncConnection, *, workspace_id: str, fragment_id: str
) -> JsonObject | None:
    """The ``None``-returning lookup the document-write reference gate resolves pins with.

    Separate from :func:`get_web_fragment` for the same reason the custom-component registry has
    both: the gate distinguishes "this pin is new and unresolvable" (a refusal it words itself)
    from "this pin was already here and is missing" (which stays loadable), so it needs an answer
    rather than an exception.
    """
    row = (
        await conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM design_web_fragment "
                "WHERE fragment_id = :fragment_id AND workspace_id = :workspace_id"
            ),
            {"fragment_id": fragment_id, "workspace_id": workspace_id},
        )
    ).one_or_none()
    return None if row is None else _from_row(row)


async def list_web_fragments(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    section_role: str | None = None,
    status: str | None = None,
) -> list[JsonObject]:
    """This workspace's fragments, newest first — the editor/agent picker's read.

    Digests only; no blob is touched. A picker showing fifty sections must not read fifty
    payloads to draw a list of previews.
    """
    clauses = ["workspace_id = :workspace_id"]
    params: dict[str, Any] = {"workspace_id": workspace_id}
    if section_role is not None:
        clauses.append("section_role = :section_role")
        params["section_role"] = section_role
    if status is not None:
        clauses.append("status = :status")
        params["status"] = status
    rows = await conn.execute(
        text(
            f"SELECT {_COLUMNS} FROM design_web_fragment WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at DESC, fragment_id"
        ),
        params,
    )
    return [_from_row(row) for row in rows]


async def sync_kit_fragment_approval(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_kit_id: str,
    brand_kit_version: int,
    approved: bool,
) -> int:
    """Move one kit VERSION's fragments between ``draft`` and ``approved``. Returns the count.

    This is the human gate, and it deliberately has no surface of its own. A fragment is minted
    at website-ingestion time against the DRAFT kit that same ingestion published, so the
    decision "these cloned sections are fit to reuse" is the same decision as "this brand kit is
    fit to use" — made by the same person, about the same capture, on the screen that already
    exists. Giving fragments a second approval queue would be a second thing to forget.

    Called from :func:`clue_design.brand.update_brand_kit_approval` **inside its transaction**,
    so the kit and its fragments cannot end up disagreeing.

    Two deliberate limits:

    * only ``draft`` ⇄ ``approved`` move. ``deprecated`` is a decision about ONE section, and a
      kit-wide approval must not quietly undo the narrower, more specific one.
    * the version matters. Approval is version-specific for kits (a newer draft does not shadow
      an older approved version), and a fragment names the exact version it was minted from, so
      approving v3 says nothing about the sections cloned into v2.
    """
    target, current = ("approved", "draft") if approved else ("draft", "approved")
    result = await conn.execute(
        text(
            """
            UPDATE design_web_fragment
            SET status = :target, updated_at = now()
            WHERE workspace_id = :workspace_id
              AND source_kit_id = :brand_kit_id
              AND source_kit_version = :brand_kit_version
              AND status = :current
            """
        ),
        {
            "target": target,
            "current": current,
            "workspace_id": workspace_id,
            "brand_kit_id": brand_kit_id,
            "brand_kit_version": brand_kit_version,
        },
    )
    return int(result.rowcount or 0)


async def set_web_fragment_status(
    conn: AsyncConnection, *, workspace_id: str, fragment_id: str, status: str
) -> JsonObject:
    """The ONE permitted mutation: has a human blessed this section, or retired it.

    Validated here rather than trusted because ``status`` reaches a CHECK constraint whose
    violation would surface as a raw ``IntegrityError`` — a caller's typo deserves the DAL's own
    typed refusal, and the tuple lives in one place (:data:`FRAGMENT_STATUSES`).
    """
    if status not in FRAGMENT_STATUSES:
        raise ValueError(
            f"fragment status must be one of {', '.join(FRAGMENT_STATUSES)}: {status!r}"
        )
    result = await conn.execute(
        text(
            "UPDATE design_web_fragment SET status = :status, updated_at = now() "
            "WHERE fragment_id = :fragment_id AND workspace_id = :workspace_id"
        ),
        {"status": status, "fragment_id": fragment_id, "workspace_id": workspace_id},
    )
    if result.rowcount == 0:
        raise DesignNotFoundError("design_web_fragment", fragment_id)
    return await get_web_fragment(conn, workspace_id=workspace_id, fragment_id=fragment_id)
