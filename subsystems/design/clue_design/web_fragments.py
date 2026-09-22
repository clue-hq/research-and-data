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
at all is a different fragment. The mutable columns are the ones that are ROW-LEVEL JUDGEMENTS
rather than content — ``status`` (draft / approved / deprecated / dormant: has a human blessed
this section for reuse, retired it, or is the source site hiding it?) and, since F3.0, the
``degraded`` marker that says a harvested clone is broken — and the database enforces that split
with a trigger. The lineage pair ``derived_from``/``derived_reason`` is born with the row and
frozen with the artifact: how a fragment came to exist is not a judgement anyone gets to revise.

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
from clue_design.errors import (
    DesignFragmentActivationError,
    DesignFragmentPreviewError,
    DesignNotFoundError,
)

#: The row-level lifecycle, mirroring ``design_brand_approval_status`` (see the migration's
#: docstring for why ``generated_unreviewed`` is not among them). Kept here as the ONE Python
#: spelling of the CHECK the migration installs.
#:
#: ``dormant`` is F3.0's addition (founder ruling D-F8): a section the source site HIDES, kept
#: rather than dropped, and kept where nothing automatic can release it — the kit cascade moves
#: only ``draft`` ⇄ ``approved``, agent discovery is approved-only, the document-write gate pins
#: only ``approved``. The one door out is :func:`set_web_fragment_status`, and it is a door a
#: human opens.
FRAGMENT_STATUS_DRAFT = "draft"
FRAGMENT_STATUS_APPROVED = "approved"
FRAGMENT_STATUS_DEPRECATED = "deprecated"
FRAGMENT_STATUS_DORMANT = "dormant"

FRAGMENT_STATUSES = (
    FRAGMENT_STATUS_DRAFT,
    FRAGMENT_STATUS_APPROVED,
    FRAGMENT_STATUS_DEPRECATED,
    FRAGMENT_STATUS_DORMANT,
)

#: Leaving dormancy for one of these means the section is about to be USABLE — ``approved`` pins
#: today, ``draft`` is one kit approval away from pinning — so both need the preview D-F8 asks
#: for. ``deprecated`` is the opposite of use and is always allowed.
_ACTIVATING_STATUSES = frozenset({FRAGMENT_STATUS_DRAFT, FRAGMENT_STATUS_APPROVED})

#: What a fragment may be BORN as (F3.0, ruling R-I5). A narrower set than the vocabulary, and
#: deliberately so: ``approved`` is what a HUMAN says by approving the brand kit a section was
#: cloned into, and the document-write pin gate is built on that meaning. A producer that could
#: mint straight to ``approved`` would put a cloned section on a page without anybody having
#: looked at it — not by defeating the gate but by walking around it. ``deprecated`` is excluded
#: for the mirror reason: retiring something at the moment of its creation is not a lifecycle,
#: it is a write nobody needed.
#:
#: A repair (F3.1) is therefore born ``draft`` like every other clone and released through the
#: same human surface. If that turns out to need its own release path, it gets one explicitly.
BIRTH_STATUSES = (FRAGMENT_STATUS_DRAFT, FRAGMENT_STATUS_DORMANT)

_COLUMNS = (
    "fragment_id, workspace_id, source_kit_id, source_kit_version, source_url, section_role, "
    "label, status, payload_digest, preview_digest, preview_basis, provenance_json, degraded, "
    "degraded_reason, derived_from, derived_reason, created_at, updated_at"
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
        # How the picture that is actually THERE was made (F3.2, ruling P-7). NULL means "the
        # mint's own crop"; the mint's account of it is in the provenance. A picture attached
        # later says so here, because the provenance is frozen and is about the mint, not
        # about a photograph taken afterwards.
        "preview_basis": row.preview_basis,
        "provenance": load_json(row.provenance_json),
        "degraded": bool(row.degraded),
        "degraded_reason": row.degraded_reason,
        "derived_from": row.derived_from,
        "derived_reason": row.derived_reason,
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
    status: str = FRAGMENT_STATUS_DRAFT,
    degraded: bool = False,
    degraded_reason: str | None = None,
    derived_from: str | None = None,
    derived_reason: str | None = None,
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

    **``status``, the degraded marker and the lineage pair are born here and only here** (F3.0).
    They are not content — the id is the sha256 of the artifact and none of them enters it — so
    they fall under the same first-writer-wins rule the label and the provenance do. Two
    consequences worth stating rather than discovering: a section already minted ``draft`` that a
    later capture finds hidden keeps its ``draft`` (which is right — a human may have activated
    it since), and a repair whose sanitized output happens to be byte-identical to an existing
    fragment converges onto that row and keeps ITS lineage. Both are the price of content
    addressing, and both leave the row honest about what it actually holds.
    """
    require_birth_status(status)
    require_degraded_pair(degraded, degraded_reason)
    require_derived_pair(derived_from, derived_reason)
    if derived_from is not None:
        await require_derivable(
            conn,
            workspace_id=workspace_id,
            fragment_id=fragment_id,
            derived_from=derived_from,
        )
    await conn.execute(
        text(
            """
            INSERT INTO design_web_fragment
              (fragment_id, workspace_id, source_kit_id, source_kit_version, source_url,
               section_role, label, status, payload_digest, preview_digest, provenance_json,
               degraded, degraded_reason, derived_from, derived_reason)
            VALUES
              (:fragment_id, :workspace_id, :source_kit_id, :source_kit_version, :source_url,
               :section_role, :label, :status, :payload_digest, :preview_digest,
               CAST(:provenance AS jsonb),
               :degraded, :degraded_reason, :derived_from, :derived_reason)
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
            "status": status,
            "payload_digest": payload_digest,
            "preview_digest": preview_digest,
            "provenance": dump_json(provenance),
            "degraded": bool(degraded),
            "degraded_reason": degraded_reason,
            "derived_from": derived_from,
            "derived_reason": derived_reason,
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
    # Ingestion publishes automatically approved kits before minting their sections. Apply
    # that exact version's release policy to late arrivals and replayed captures as well.
    # Reuse the cascade so dormant, deprecated and individually reviewed repairs stay untouched.
    if row["status"] == FRAGMENT_STATUS_DRAFT and row["derived_from"] is None:
        kit_approved = (
            await conn.execute(
                text(
                    "SELECT approval_status = 'approved' FROM design_brand_kit"
                    " WHERE workspace_id = :w AND brand_kit_id = :k AND version = :v"
                    " FOR SHARE"
                ),
                {"w": workspace_id, "k": row["source_kit_id"], "v": row["source_kit_version"]},
            )
        ).scalar_one_or_none()
        if kit_approved:
            await sync_kit_fragment_approval(
                conn,
                workspace_id=workspace_id,
                brand_kit_id=row["source_kit_id"],
                brand_kit_version=row["source_kit_version"],
                approved=True,
            )
            row = await get_web_fragment(conn, workspace_id=workspace_id, fragment_id=fragment_id)
    return row


def require_known_status(status: str) -> None:
    """The status vocabulary, checked in the ONE place it is spelled.

    Public because the registry seam re-raises it as a ``FragmentRefused`` — the rule is written
    here, worded here, and translated there, rather than being written twice and drifting.
    """
    if status not in FRAGMENT_STATUSES:
        raise ValueError(
            f"fragment status must be one of {', '.join(FRAGMENT_STATUSES)}: {status!r}"
        )


def require_birth_status(status: str) -> None:
    """A fragment is born ``draft`` or ``dormant`` — never straight into a human's decision.

    Separate from :func:`require_known_status` because they answer different questions: that one
    asks "is this a status?", this asks "may a producer CREATE a row in it?". See
    :data:`BIRTH_STATUSES`.
    """
    require_known_status(status)
    if status not in BIRTH_STATUSES:
        raise ValueError(
            f"a fragment is born one of {', '.join(BIRTH_STATUSES)} — {status!r} is a decision "
            "about an existing section (a human approves cloned sections by approving the brand "
            "kit they came from, and retires them one at a time)"
        )


def require_degraded_pair(degraded: bool, degraded_reason: str | None) -> None:
    """A degraded marker carries its reason, or it is not a marker (D-F6)."""
    has_reason = bool((degraded_reason or "").strip())
    if bool(degraded) != has_reason:
        raise ValueError(
            "a degraded fragment names the reason it is degraded, and an undegraded one names "
            f"none: degraded={bool(degraded)!r}, degraded_reason={degraded_reason!r}"
        )


def require_derived_pair(derived_from: str | None, derived_reason: str | None) -> None:
    """A repair names what it repairs AND why, or neither (D-F6)."""
    has_reason = bool((derived_reason or "").strip())
    if (derived_from is not None) != has_reason:
        raise ValueError(
            "a derived fragment names both the fragment it was derived from and the reason, or "
            f"neither: derived_from={derived_from!r}, derived_reason={derived_reason!r}"
        )


async def require_derivable(
    conn: AsyncConnection, *, workspace_id: str, fragment_id: str, derived_from: str
) -> None:
    """The lineage pointer resolves to a fragment THIS workspace holds, or the write refuses.

    The composite self-FK the migration installs says the same thing structurally; this says it
    first, so a caller gets a sentence about lineage rather than a driver's constraint name. Both
    exist on purpose — the FK is what makes it true of every writer, this is what makes it
    legible to the one writer we have.
    """
    if derived_from == fragment_id:
        raise ValueError(
            f"fragment {fragment_id} cannot be derived from itself — a repair is a NEW fragment"
        )
    found = await find_web_fragment(conn, workspace_id=workspace_id, fragment_id=derived_from)
    if found is None:
        raise ValueError(
            f"derived_from names {derived_from!r}, which this workspace does not hold — a repair "
            "must point at a fragment that exists here (a fragment id is a global content "
            "address, so another tenant's id is not this workspace's fragment)"
        )


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
    row = await find_web_fragment(conn, workspace_id=workspace_id, fragment_id=fragment_id)
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


async def list_web_fragment_lineage(
    conn: AsyncConnection, *, workspace_id: str, fragment_id: str
) -> list[JsonObject]:
    """One fragment's whole repair FAMILY — itself, every ancestor, every descendant.

    The lineage question ("which repair of this band should the page carry?") is answered by
    :func:`lumen_api.agent_cloned_sections.resolve_fragment_lineages`, which is a pure function of
    a row set. Handing it every row the workspace holds answers the question correctly and reads
    a whole library to do it; handing it this reads the family. The two answers are identical
    because the resolver never looks outside a family: roots are found by walking ``derived_from``
    and families never intersect.

    Two recursive halves, and both are needed. UP first, through ``derived_from``, because the
    row asked about may be a repair-of-a-repair and its siblings hang off an ancestor. Then DOWN
    from everything found, through the partial index the F3.0 migration installed on
    ``(workspace_id, derived_from)``, which is what makes this a lookup rather than a scan.

    Statuses are not filtered. A repair is born ``draft`` (ruling R-I5) and a retired one is
    ``deprecated``, and the resolution rule (R-X1) walks links of ANY status on purpose — a
    filtered read here would silently re-decide the rule at the database.

    An id this workspace does not hold returns ``[]``, like the rest of this module: absent and
    another tenant's are the same answer.
    """
    rows = await conn.execute(
        text(
            f"""
            WITH RECURSIVE ancestry AS (
                SELECT fragment_id, derived_from
                  FROM design_web_fragment
                 WHERE workspace_id = :workspace_id AND fragment_id = :fragment_id
                 UNION
                SELECT parent.fragment_id, parent.derived_from
                  FROM design_web_fragment parent
                  JOIN ancestry ON parent.fragment_id = ancestry.derived_from
                 WHERE parent.workspace_id = :workspace_id
            ),
            family AS (
                SELECT fragment_id FROM ancestry
                 UNION
                SELECT child.fragment_id
                  FROM design_web_fragment child
                  JOIN family ON child.derived_from = family.fragment_id
                 WHERE child.workspace_id = :workspace_id
            )
            SELECT {_COLUMNS}
              FROM design_web_fragment
             WHERE workspace_id = :workspace_id
               AND fragment_id IN (SELECT fragment_id FROM family)
             ORDER BY created_at DESC, fragment_id
            """
        ),
        {"workspace_id": workspace_id, "fragment_id": fragment_id},
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

    Four deliberate limits:

    * only ``draft`` ⇄ ``approved`` move. ``deprecated`` is a decision about ONE section, and a
      kit-wide approval must not quietly undo the narrower, more specific one.
    * **``dormant`` is untouched, in both directions** (D-F8, F3.0). A section the source site
      hides is never auto-approved — the whole reason dormancy is a STATUS rather than a flag on
      a draft is that this query, the only automatic releaser there is, names the statuses it
      moves and cannot name that one. Waking a dormant section is a human act with its own gate
      (:func:`set_web_fragment_status`, which asks for a usable preview first).
    * **a REPAIR is untouched, in both directions** (FOUNDER RULING R-X9, 2026-08-29). A row with
      ``derived_from`` set is somebody's composed replacement for a broken band, and the founder's
      words are "require individual approval for each repair; brand-kit approval should not
      silently approve later repairs". So the cascade stops at ``derived_from IS NULL``:
      harvested originals and composed campaign shells (which have no lineage) keep the release
      surface they have always had, and a repair is released one at a time, by a human who was
      asked, through :func:`set_web_fragment_status`.

      BOTH directions, deliberately. Individually governed is individually governed each way: an
      un-approval of the kit must not retract a repair a human released on its own evidence any
      more than an approval may release one nobody looked at. The symmetry is the point — a rule
      that only holds in the direction that happens to be dangerous today is a rule waiting to be
      surprised by tomorrow.
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
              AND derived_from IS NULL
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
    """Move one section's lifecycle flag — the human gate, and the door out of dormancy.

    Validated here rather than trusted because ``status`` reaches a CHECK constraint whose
    violation would surface as a raw ``IntegrityError`` — a caller's typo deserves the DAL's own
    typed refusal, and the tuple lives in one place (:data:`FRAGMENT_STATUSES`).

    **Activation has a second condition** (D-F8, F3.0). A ``dormant`` section leaving for
    ``draft`` or ``approved`` is about to become usable, and the founder ruling is that a human
    may only make that call with a usable preview in front of them — so a dormant row with no
    ``preview_digest`` is refused with :class:`DesignFragmentActivationError` rather than woken.
    ``draft`` is gated alongside ``approved`` because it is one kit approval away from pinning:
    gating only the last step would leave a route around the gate rather than through it.
    Retirement (``deprecated``) is never gated — the preview protects USE, and retiring is the
    opposite of using.
    """
    require_known_status(status)
    current = await get_web_fragment(conn, workspace_id=workspace_id, fragment_id=fragment_id)
    if (
        current["status"] == FRAGMENT_STATUS_DORMANT
        and status in _ACTIVATING_STATUSES
        and not current.get("preview_digest")
    ):
        raise DesignFragmentActivationError(
            fragment_id,
            "no_preview",
            f"fragment {fragment_id} is hidden on its source site and carries no preview image, "
            f"so it cannot be activated to {status!r}: a human activates a dormant clone by "
            "looking at it, and there is nothing here to look at",
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


async def attach_web_fragment_preview(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    fragment_id: str,
    preview_digest: str,
    preview_basis: str,
) -> JsonObject:
    """Give a fragment that has no preview one — once, and never again (F3.2, ruling P-7).

    The third permitted write, and the narrowest: NULL → a digest **and the kind of picture it
    is**. A row that already carries a preview is refused HERE with a sentence, and refused again
    by the trigger the migration installs, for the same reason the lineage rule is written twice —
    one makes it legible to the writer we have, the other makes it true of every writer.

    **The basis is written here because it is a fact about THIS picture.** ``provenance_json``
    records what the MINT saw and is frozen with the artifact, which is right — but a picture
    taken afterwards is not the mint's picture, and reading the mint's word for it mislabels two
    real rows: a repair, whose provenance names no basis at all, and a section the capture
    measured but could not crop, whose provenance says ``measured`` while it holds no picture. On
    the second one, taking provenance's word would present an isolation render our own engine drew
    as a crop of the live site, which is the exact substitution P-7 forbids.

    **Why the column can move at all.** ``preview_digest`` is part of the artifact's identity
    bytes, so it is content in the sense that changing it at MINT time makes a different fragment.
    What is attached here is not that: a section the source site hides was never rendered, so the
    capture holds no pixels of it and the row is born with nothing to look at — and D-F8 makes
    "something to look at" the condition a human activates it on. The picture attached later is
    an isolation render OF the artifact's own bytes, taken after the fact, and the payload's own
    record of what was minted is untouched. Adding a fact is not editing one.

    The two callers are the two rows that can never have a preview at birth: a dormant clone
    (D-F8) and a composed repair (ruling R17-2, where the human releasing it is otherwise
    approving a section nobody can see).
    """
    if not (preview_digest or "").strip():
        raise ValueError("a preview digest is the sha256 of the bytes stored, not an empty string")
    if not (preview_basis or "").strip():
        raise ValueError(
            "an attached preview names how it was made — an unlabelled picture is the thing "
            "ruling P-7 exists to prevent"
        )
    current = await get_web_fragment(conn, workspace_id=workspace_id, fragment_id=fragment_id)
    if current.get("preview_digest"):
        raise _preview_present(fragment_id)
    result = await conn.execute(
        text(
            "UPDATE design_web_fragment "
            "SET preview_digest = :preview_digest, preview_basis = :preview_basis, "
            "    updated_at = now() "
            "WHERE fragment_id = :fragment_id AND workspace_id = :workspace_id "
            "AND preview_digest IS NULL"
        ),
        {
            "preview_digest": preview_digest,
            "preview_basis": preview_basis,
            "fragment_id": fragment_id,
            "workspace_id": workspace_id,
        },
    )
    if result.rowcount == 0:
        # The read above passed and the write matched nothing, so a concurrent attach won the
        # race between them: the predicate is re-evaluated under the row lock, and the loser's
        # UPDATE quietly matches zero rows without the trigger ever firing (no row changed).
        # Left unchecked this is the one path that returns 200 carrying somebody ELSE'S picture,
        # with neither refusal this function promises. Both pictures are of the same artifact, so
        # the harm is small — but "attached once" is a claim, and a claim that is silently false
        # under concurrency is worse than a slower one that is true.
        raise _preview_present(fragment_id)
    return await get_web_fragment(conn, workspace_id=workspace_id, fragment_id=fragment_id)


def _preview_present(fragment_id: str) -> DesignFragmentPreviewError:
    """The one refusal for "this row already has a picture", however it was discovered.

    Written once because :func:`attach_web_fragment_preview` discovers it twice — by reading the
    row, and by an UPDATE that matches nothing because somebody else got there in between — and
    the caller is owed the same sentence either way.
    """
    return DesignFragmentPreviewError(
        fragment_id,
        "already_present",
        f"fragment {fragment_id} already carries a preview: a preview is attached once and "
        "never replaced, because a human's decision was made against the picture that is "
        "there. Mint a new fragment rather than re-picturing this one",
    )


async def set_web_fragment_degraded(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    fragment_id: str,
    degraded: bool,
    reason: str | None = None,
) -> JsonObject:
    """Record that this harvested clone is broken, and why — or that it is not (D-F6).

    ORTHOGONAL to ``status`` on purpose, and that is the whole ruling: the harvested original
    stays IMMUTABLE evidence and stays ``approved`` while it is the only thing that exists, so a
    page can keep pinning it until its repair is minted. Folding brokenness into the lifecycle
    would have forced a choice between "a human blessed this" and "this is broken", and the two
    are both true of a degraded original at the same time.

    Mutable, unlike the lineage pair beside it, because it is a JUDGEMENT rather than an origin:
    minting makes one from the dead-height detector, and F3.3's behavioural review gate makes
    later ones from a page it actually walked. The migration's trigger relaxation admits exactly
    this pair and nothing else.
    """
    require_degraded_pair(degraded, reason)
    result = await conn.execute(
        text(
            "UPDATE design_web_fragment "
            "SET degraded = :degraded, degraded_reason = :reason, updated_at = now() "
            "WHERE fragment_id = :fragment_id AND workspace_id = :workspace_id"
        ),
        {
            "degraded": bool(degraded),
            "reason": reason if degraded else None,
            "fragment_id": fragment_id,
            "workspace_id": workspace_id,
        },
    )
    if result.rowcount == 0:
        raise DesignNotFoundError("design_web_fragment", fragment_id)
    return await get_web_fragment(conn, workspace_id=workspace_id, fragment_id=fragment_id)
