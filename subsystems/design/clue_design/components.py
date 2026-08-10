"""Custom-component registry DAL (Part II slice D2.4B) — the port of the design API's P6
``custom_components`` / ``_source_revisions`` / ``_artifacts`` / ``_compilations`` domain.

Faithful port of ``lumen_api.database.Repository``'s custom-component methods onto
``design_custom_component`` + ``design_custom_component_source_revision`` / ``_artifact`` /
``_compilation`` (PD contract §5 rows 23–26), with the D1/D2 upgrades the contract mandates:

* **Fail-closed tenancy.** Every function takes ``workspace_id``; the component identity is
  ``(workspace_id, account_id, slug)`` and every child row is located by its id *and* the
  workspace. A foreign-workspace artifact/revision/compilation raises the same
  :class:`DesignNotFoundError` an absent one does, so a cross-tenant pin can never resolve.
* **Real FKs where SQLite validated by convention.** Components CASCADE off
  ``design_account`` (deleting an account now takes its components, revisions, artifacts and
  compilations with it — the SQLite era orphaned them); revisions/artifacts CASCADE off the
  component; a compilation's ``source_revision_id`` is a real FK and its ``artifact_id`` is
  ``ON DELETE SET NULL`` instead of dangling.
* **Immutability is structural.** ``_source_revision``, ``_artifact`` and ``_compilation`` all
  reject UPDATE by trigger, and content addresses are CHECKed (``ccsrc_``/``ccart_<sha256>``).
  This module is therefore INSERT-only on those three tables — as the SQLite code already was.
  The ONE permitted mutation is the ``design_custom_component`` identity row's own pointer
  (``source_version`` / ``current_source_revision_id`` / ``updated_at``), which is exactly what
  the CAS advance writes.

**Where input validation lives.** Blob canonicalization, slug shape and content-address shape
are the design API's *contract* (``lumen_api.custom_component_contract`` /
``canonical_custom_component_blob``), not storage rules; the caller validates and hands this
module an already-canonical candidate, exactly as the document write path already validates
component references before calling the DAL. Storage-side checks that need the database
(account existence, artifact/revision identity agreement, the source-version CAS, the immutable
id's equal-content rule) live here, in the write's own transaction.

Callers own the transaction (one logical operation = one transaction — the O5 rule); nothing
here commits. Mappers reproduce ``custom_component_artifact_from_row`` /
``custom_component_source_revision_from_row`` / ``custom_component_compilation_from_row``
exactly, with ISO-string timestamps.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, iso, load_json
from clue_design.accounts import require_web_account
from clue_design.errors import (
    DesignArtifactConflictError,
    DesignNotFoundError,
    DesignSourceVersionConflictError,
)

# The columns the ported equal-content check compares when an artifact id is re-registered.
_ARTIFACT_COMPARABLE = (
    "artifact_id",
    "account_id",
    "slug",
    "source",
    "bundle",
    "css",
    "first_frame",
    "manifest",
    "provenance",
)

_COMPILE_STATUSES = frozenset({"succeeded", "failed", "transient_error"})


def _blob(row: Any, prefix: str) -> JsonObject:
    return {
        "algorithm": getattr(row, f"{prefix}_digest_algorithm"),
        "value": getattr(row, f"{prefix}_digest_value"),
        "opaque_ref": getattr(row, f"{prefix}_opaque_ref"),
        "byte_length": getattr(row, f"{prefix}_byte_length"),
    }


def _optional_blob(row: Any, prefix: str) -> JsonObject | None:
    if getattr(row, f"{prefix}_digest_value") is None:
        return None
    return _blob(row, prefix)


def _artifact_from_row(row: Any) -> JsonObject:
    return {
        "artifact_id": row.artifact_id,
        "account_id": row.account_id,
        "slug": row.slug,
        "source": _blob(row, "source"),
        "bundle": _blob(row, "bundle"),
        "css": _optional_blob(row, "css"),
        "first_frame": _optional_blob(row, "first_frame"),
        "manifest": load_json(row.manifest_json),
        "provenance": load_json(row.provenance_json),
        "created_at": iso(row.created_at),
    }


def _source_revision_from_row(row: Any) -> JsonObject:
    return {
        "revision_id": row.revision_id,
        "account_id": row.account_id,
        "slug": row.slug,
        "source_version": row.source_version,
        "entry_path": row.entry_path,
        "snapshot": _blob(row, "snapshot"),
        "files_manifest": load_json(row.files_manifest_json),
        "provenance": load_json(row.provenance_json),
        "created_at": iso(row.created_at),
    }


def _compilation_from_row(row: Any) -> JsonObject:
    return {
        "compilation_id": row.compilation_id,
        "account_id": row.account_id,
        "slug": row.slug,
        "source_revision_id": row.source_revision_id,
        "source_version": row.source_version,
        "status": row.status,
        "compiler_protocol_version": row.compiler_protocol_version,
        "compiler_version": row.compiler_version,
        "diagnostics": load_json(row.diagnostics_json),
        "artifact_id": row.artifact_id,
        "created_at": iso(row.created_at),
    }


# --- component identity ----------------------------------------------------------------------


async def _touch_component(
    conn: AsyncConnection, *, workspace_id: str, account_id: str, slug: str
) -> None:
    """Ensure the identity row exists (ported ``ON CONFLICT … DO UPDATE SET updated_at``)."""
    await conn.execute(
        text(
            """
            INSERT INTO design_custom_component (workspace_id, account_id, slug)
            VALUES (:w, :a, :s)
            ON CONFLICT (workspace_id, account_id, slug) DO UPDATE SET updated_at = now()
            """
        ),
        {"w": workspace_id, "a": account_id, "s": slug},
    )


async def get_custom_component(
    conn: AsyncConnection, *, workspace_id: str, account_id: str, slug: str
) -> JsonObject | None:
    """One component with its full artifact list, or ``None``."""
    row = (
        await conn.execute(
            text(
                "SELECT * FROM design_custom_component"
                " WHERE workspace_id = :w AND account_id = :a AND slug = :s"
            ),
            {"w": workspace_id, "a": account_id, "s": slug},
        )
    ).first()
    if row is None:
        return None
    artifacts = await list_custom_component_artifacts(
        conn, workspace_id=workspace_id, account_id=account_id, slug=slug
    )
    return {
        "account_id": row.account_id,
        "slug": row.slug,
        "source_version": row.source_version,
        "current_source_revision_id": row.current_source_revision_id,
        "artifacts": artifacts,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


async def require_custom_component(
    conn: AsyncConnection, *, workspace_id: str, account_id: str, slug: str
) -> JsonObject:
    """Fetch or raise — the fail-closed read every component-scoped endpoint gates on."""
    component = await get_custom_component(
        conn, workspace_id=workspace_id, account_id=account_id, slug=slug
    )
    if component is None:
        raise DesignNotFoundError("custom_component", slug)
    return component


async def list_custom_components(
    conn: AsyncConnection, *, workspace_id: str, account_id: str
) -> list[JsonObject]:
    """The account's components with artifact counts and the newest artifact id (ported SQL)."""
    rows = await conn.execute(
        text(
            """
            SELECT
              component.account_id,
              component.slug,
              component.source_version,
              component.current_source_revision_id,
              component.created_at,
              component.updated_at,
              COUNT(artifact.artifact_id) AS artifact_count,
              (
                SELECT newest.artifact_id
                FROM design_custom_component_artifact AS newest
                WHERE newest.workspace_id = component.workspace_id
                  AND newest.account_id = component.account_id
                  AND newest.slug = component.slug
                ORDER BY newest.created_at DESC, newest.artifact_id DESC
                LIMIT 1
              ) AS latest_artifact_id
            FROM design_custom_component AS component
            LEFT JOIN design_custom_component_artifact AS artifact
              ON artifact.workspace_id = component.workspace_id
             AND artifact.account_id = component.account_id
             AND artifact.slug = component.slug
            WHERE component.workspace_id = :w AND component.account_id = :a
            GROUP BY component.workspace_id, component.account_id, component.slug
            ORDER BY component.slug ASC
            """
        ),
        {"w": workspace_id, "a": account_id},
    )
    return [
        {
            "account_id": row.account_id,
            "slug": row.slug,
            "source_version": row.source_version,
            "current_source_revision_id": row.current_source_revision_id,
            "artifact_count": row.artifact_count,
            # Convenience for listing only. Documents may never store "latest"; attach
            # operations use a concrete artifact id.
            "latest_artifact_id": row.latest_artifact_id,
            "created_at": iso(row.created_at),
            "updated_at": iso(row.updated_at),
        }
        for row in rows
    ]


# --- artifacts (immutable, content-addressed) -------------------------------------------------


async def get_custom_component_artifact(
    conn: AsyncConnection, *, workspace_id: str, artifact_id: str
) -> JsonObject | None:
    """Workspace-scoped artifact lookup by id alone — the reference-validation read."""
    row = (
        await conn.execute(
            text(
                "SELECT * FROM design_custom_component_artifact"
                " WHERE artifact_id = :i AND workspace_id = :w"
            ),
            {"i": artifact_id, "w": workspace_id},
        )
    ).first()
    return None if row is None else _artifact_from_row(row)


async def get_custom_component_artifact_for_account(
    conn: AsyncConnection, *, workspace_id: str, account_id: str, artifact_id: str
) -> JsonObject | None:
    """The account-scoped lookup: an artifact of another account resolves to ``None``."""
    row = (
        await conn.execute(
            text(
                "SELECT * FROM design_custom_component_artifact"
                " WHERE workspace_id = :w AND account_id = :a AND artifact_id = :i"
            ),
            {"w": workspace_id, "a": account_id, "i": artifact_id},
        )
    ).first()
    return None if row is None else _artifact_from_row(row)


async def require_custom_component_artifact(
    conn: AsyncConnection, *, workspace_id: str, account_id: str, artifact_id: str
) -> JsonObject:
    """Fetch or raise, account-scoped."""
    artifact = await get_custom_component_artifact_for_account(
        conn, workspace_id=workspace_id, account_id=account_id, artifact_id=artifact_id
    )
    if artifact is None:
        raise DesignNotFoundError("custom_component_artifact", artifact_id)
    return artifact


async def list_custom_component_artifacts(
    conn: AsyncConnection, *, workspace_id: str, account_id: str, slug: str | None = None
) -> list[JsonObject]:
    """Newest-first artifacts for an account, optionally narrowed to one component."""
    clause = "" if slug is None else " AND slug = :s"
    params: dict[str, Any] = {"w": workspace_id, "a": account_id}
    if slug is not None:
        params["s"] = slug
    rows = await conn.execute(
        text(
            "SELECT * FROM design_custom_component_artifact"
            f" WHERE workspace_id = :w AND account_id = :a{clause}"
            " ORDER BY created_at DESC, artifact_id DESC"
        ),
        params,
    )
    return [_artifact_from_row(row) for row in rows]


async def register_custom_component_artifact(
    conn: AsyncConnection, *, workspace_id: str, candidate: JsonObject
) -> JsonObject:
    """Persist one successful compile artifact (INSERT-only; ported).

    There is deliberately no update method — the row is immutable by trigger. An exact retry is
    idempotent; re-using the content-derived id with different metadata raises
    :class:`DesignArtifactConflictError`. ``candidate`` is the caller-canonicalized record (the
    blob groups already validated); the account must exist *in this workspace*, which is now
    also a real FK through the component identity row.
    """
    account_id = str(candidate["account_id"])
    slug = str(candidate["slug"])
    artifact_id = str(candidate["artifact_id"])
    await require_web_account(conn, workspace_id=workspace_id, account_id=account_id)

    existing = await get_custom_component_artifact(
        conn, workspace_id=workspace_id, artifact_id=artifact_id
    )
    if existing is not None:
        if {key: existing[key] for key in _ARTIFACT_COMPARABLE} != candidate:
            raise DesignArtifactConflictError("custom component artifact", artifact_id)
        return existing

    await _touch_component(conn, workspace_id=workspace_id, account_id=account_id, slug=slug)
    css = candidate["css"]
    first_frame = candidate["first_frame"]
    result = await conn.execute(
        text(
            """
            INSERT INTO design_custom_component_artifact (
              artifact_id, workspace_id, account_id, slug,
              source_digest_algorithm, source_digest_value,
              source_opaque_ref, source_byte_length,
              bundle_digest_algorithm, bundle_digest_value,
              bundle_opaque_ref, bundle_byte_length,
              css_digest_algorithm, css_digest_value, css_opaque_ref, css_byte_length,
              first_frame_digest_algorithm, first_frame_digest_value,
              first_frame_opaque_ref, first_frame_byte_length,
              manifest_json, provenance_json
            )
            VALUES (
              :i, :w, :a, :s,
              :src_alg, :src_val, :src_ref, :src_len,
              :bun_alg, :bun_val, :bun_ref, :bun_len,
              :css_alg, :css_val, :css_ref, :css_len,
              :ff_alg, :ff_val, :ff_ref, :ff_len,
              CAST(:manifest AS jsonb), CAST(:provenance AS jsonb)
            )
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "i": artifact_id,
            "w": workspace_id,
            "a": account_id,
            "s": slug,
            "src_alg": candidate["source"]["algorithm"],
            "src_val": candidate["source"]["value"],
            "src_ref": candidate["source"]["opaque_ref"],
            "src_len": candidate["source"]["byte_length"],
            "bun_alg": candidate["bundle"]["algorithm"],
            "bun_val": candidate["bundle"]["value"],
            "bun_ref": candidate["bundle"]["opaque_ref"],
            "bun_len": candidate["bundle"]["byte_length"],
            "css_alg": css["algorithm"] if css else None,
            "css_val": css["value"] if css else None,
            "css_ref": css["opaque_ref"] if css else None,
            "css_len": css["byte_length"] if css else None,
            "ff_alg": first_frame["algorithm"] if first_frame else None,
            "ff_val": first_frame["value"] if first_frame else None,
            "ff_ref": first_frame["opaque_ref"] if first_frame else None,
            "ff_len": first_frame["byte_length"] if first_frame else None,
            "manifest": dump_json(candidate["manifest"]),
            "provenance": dump_json(candidate["provenance"]),
        },
    )
    stored = await get_custom_component_artifact(
        conn, workspace_id=workspace_id, artifact_id=artifact_id
    )
    if stored is None:
        raise RuntimeError(f"custom component artifact {artifact_id} was not persisted")
    if result.rowcount == 0 and {key: stored[key] for key in _ARTIFACT_COMPARABLE} != candidate:
        raise DesignArtifactConflictError("custom component artifact", artifact_id)
    return stored


# --- source revisions (immutable, CAS-versioned) ----------------------------------------------


async def get_custom_component_source_revision(
    conn: AsyncConnection, *, workspace_id: str, account_id: str, revision_id: str
) -> JsonObject | None:
    row = (
        await conn.execute(
            text(
                "SELECT * FROM design_custom_component_source_revision"
                " WHERE workspace_id = :w AND account_id = :a AND revision_id = :r"
            ),
            {"w": workspace_id, "a": account_id, "r": revision_id},
        )
    ).first()
    return None if row is None else _source_revision_from_row(row)


async def require_custom_component_source_revision(
    conn: AsyncConnection, *, workspace_id: str, account_id: str, revision_id: str
) -> JsonObject:
    revision = await get_custom_component_source_revision(
        conn, workspace_id=workspace_id, account_id=account_id, revision_id=revision_id
    )
    if revision is None:
        raise DesignNotFoundError("custom_component_source_revision", revision_id)
    return revision


async def get_current_custom_component_source(
    conn: AsyncConnection, *, workspace_id: str, account_id: str, slug: str
) -> JsonObject | None:
    """The revision the component identity row currently pins (``None`` when it pins none)."""
    row = (
        await conn.execute(
            text(
                """
                SELECT revision.*
                FROM design_custom_component AS component
                JOIN design_custom_component_source_revision AS revision
                  ON revision.revision_id = component.current_source_revision_id
                 AND revision.workspace_id = component.workspace_id
                WHERE component.workspace_id = :w
                  AND component.account_id = :a
                  AND component.slug = :s
                """
            ),
            {"w": workspace_id, "a": account_id, "s": slug},
        )
    ).first()
    return None if row is None else _source_revision_from_row(row)


async def list_custom_component_source_revisions(
    conn: AsyncConnection, *, workspace_id: str, account_id: str, slug: str
) -> list[JsonObject]:
    rows = await conn.execute(
        text(
            "SELECT * FROM design_custom_component_source_revision"
            " WHERE workspace_id = :w AND account_id = :a AND slug = :s"
            " ORDER BY source_version DESC"
        ),
        {"w": workspace_id, "a": account_id, "s": slug},
    )
    return [_source_revision_from_row(row) for row in rows]


async def create_custom_component_source_revision(
    conn: AsyncConnection, *, workspace_id: str, candidate: JsonObject, expected_version: int
) -> JsonObject:
    """Atomically append an immutable source revision with CAS versioning (ported).

    SQLite serialized this with ``BEGIN IMMEDIATE``; Postgres takes the identity row's lock
    explicitly (``SELECT … FOR UPDATE``) inside the caller's transaction, so two concurrent
    writers against the same component queue rather than interleave. The CAS is still checked
    twice — once against the locked read, once as the ``WHERE source_version = <current>``
    guard on the advance — so a lost race is a
    :class:`DesignSourceVersionConflictError`, never a silently skipped version.
    """
    account_id = str(candidate["account_id"])
    slug = str(candidate["slug"])
    revision_id = str(candidate["revision_id"])
    await require_web_account(conn, workspace_id=workspace_id, account_id=account_id)

    current_version = await _locked_source_version(
        conn, workspace_id=workspace_id, account_id=account_id, slug=slug
    )
    if current_version is None:
        if expected_version != 0:
            raise DesignSourceVersionConflictError(slug, expected_version, 0)
        # First revision: mint the identity row at version 0, then re-lock it (a concurrent
        # creator's row wins the conflict and we CAS against ITS state, never a stale zero).
        await conn.execute(
            text(
                "INSERT INTO design_custom_component (workspace_id, account_id, slug)"
                " VALUES (:w, :a, :s) ON CONFLICT (workspace_id, account_id, slug) DO NOTHING"
            ),
            {"w": workspace_id, "a": account_id, "s": slug},
        )
        current_version = await _locked_source_version(
            conn, workspace_id=workspace_id, account_id=account_id, slug=slug
        )
        if current_version is None:
            raise RuntimeError(f"custom component {slug} identity row was not persisted")
    if current_version != expected_version:
        raise DesignSourceVersionConflictError(slug, expected_version, current_version)

    next_version = current_version + 1
    await conn.execute(
        text(
            """
            INSERT INTO design_custom_component_source_revision (
              revision_id, workspace_id, account_id, slug, source_version, entry_path,
              snapshot_digest_algorithm, snapshot_digest_value,
              snapshot_opaque_ref, snapshot_byte_length,
              files_manifest_json, provenance_json
            )
            VALUES (:r, :w, :a, :s, :version, :entry,
                    :snap_alg, :snap_val, :snap_ref, :snap_len,
                    CAST(:files AS jsonb), CAST(:provenance AS jsonb))
            """
        ),
        {
            "r": revision_id,
            "w": workspace_id,
            "a": account_id,
            "s": slug,
            "version": next_version,
            "entry": str(candidate["entry_path"]),
            "snap_alg": candidate["snapshot"]["algorithm"],
            "snap_val": candidate["snapshot"]["value"],
            "snap_ref": candidate["snapshot"]["opaque_ref"],
            "snap_len": candidate["snapshot"]["byte_length"],
            "files": dump_json(candidate["files_manifest"]),
            "provenance": dump_json(candidate["provenance"]),
        },
    )
    # The ONE permitted mutation on this domain: the identity row's pointer advance.
    result = await conn.execute(
        text(
            """
            UPDATE design_custom_component
            SET source_version = :next, current_source_revision_id = :r, updated_at = now()
            WHERE workspace_id = :w AND account_id = :a AND slug = :s
              AND source_version = :current
            """
        ),
        {
            "next": next_version,
            "r": revision_id,
            "w": workspace_id,
            "a": account_id,
            "s": slug,
            "current": current_version,
        },
    )
    if result.rowcount != 1:
        observed = await _locked_source_version(
            conn, workspace_id=workspace_id, account_id=account_id, slug=slug
        )
        raise DesignSourceVersionConflictError(
            slug, expected_version, 0 if observed is None else observed
        )
    return await require_custom_component_source_revision(
        conn, workspace_id=workspace_id, account_id=account_id, revision_id=revision_id
    )


async def _locked_source_version(
    conn: AsyncConnection, *, workspace_id: str, account_id: str, slug: str
) -> int | None:
    row = (
        await conn.execute(
            text(
                "SELECT source_version FROM design_custom_component"
                " WHERE workspace_id = :w AND account_id = :a AND slug = :s FOR UPDATE"
            ),
            {"w": workspace_id, "a": account_id, "s": slug},
        )
    ).first()
    return None if row is None else int(row.source_version)


# --- compilations (immutable outcomes) --------------------------------------------------------


async def require_custom_component_compilation(
    conn: AsyncConnection, *, workspace_id: str, account_id: str, compilation_id: str
) -> JsonObject:
    row = (
        await conn.execute(
            text(
                "SELECT * FROM design_custom_component_compilation"
                " WHERE workspace_id = :w AND account_id = :a AND compilation_id = :c"
            ),
            {"w": workspace_id, "a": account_id, "c": compilation_id},
        )
    ).first()
    if row is None:
        raise DesignNotFoundError("custom_component_compilation", compilation_id)
    return _compilation_from_row(row)


async def list_custom_component_compilations(
    conn: AsyncConnection, *, workspace_id: str, account_id: str, slug: str
) -> list[JsonObject]:
    rows = await conn.execute(
        text(
            "SELECT * FROM design_custom_component_compilation"
            " WHERE workspace_id = :w AND account_id = :a AND slug = :s"
            " ORDER BY created_at DESC, compilation_id DESC"
        ),
        {"w": workspace_id, "a": account_id, "s": slug},
    )
    return [_compilation_from_row(row) for row in rows]


async def record_custom_component_compilation(
    conn: AsyncConnection, *, workspace_id: str, compilation: JsonObject
) -> JsonObject:
    """Append one immutable compiler outcome (INSERT-only; ported validation verbatim).

    The identity checks that need the database — the named source revision exists *in this
    workspace and account* and agrees on slug/version, and a successful compile's artifact
    exists and carries the same slug — run inside the write's own transaction, so a compile row
    can never cite a revision or artifact that is not there.
    """
    account_id = str(compilation["account_id"])
    slug = str(compilation["slug"])
    compilation_id = str(compilation["compilation_id"])
    revision_id = str(compilation["source_revision_id"])
    source_version = compilation["source_version"]
    status = str(compilation["status"])
    protocol_version = compilation["compiler_protocol_version"]
    compiler_version = str(compilation["compiler_version"])
    diagnostics = compilation.get("diagnostics", [])
    artifact_id = compilation.get("artifact_id")

    if (
        not compilation_id.startswith("cccmp_")
        or len(compilation_id) != len("cccmp_") + 32
        or any(ch not in "0123456789abcdef" for ch in compilation_id[len("cccmp_") :])
    ):
        raise ValueError("compilation_id must be cccmp_<32 lowercase hex>")
    if status not in _COMPILE_STATUSES:
        raise ValueError("compile status is invalid")
    if not isinstance(diagnostics, list):
        raise ValueError("compile diagnostics must be an array")
    if (
        not isinstance(source_version, int)
        or isinstance(source_version, bool)
        or source_version <= 0
        or not isinstance(protocol_version, int)
        or isinstance(protocol_version, bool)
        or protocol_version <= 0
        or not compiler_version
    ):
        raise ValueError("compile version fields are invalid")

    revision = await require_custom_component_source_revision(
        conn, workspace_id=workspace_id, account_id=account_id, revision_id=revision_id
    )
    if revision["slug"] != slug or revision["source_version"] != source_version:
        raise ValueError("compile source revision identity does not match")
    if status == "succeeded":
        if not isinstance(artifact_id, str):
            raise ValueError("successful compile requires an artifact id")
        artifact = await require_custom_component_artifact(
            conn, workspace_id=workspace_id, account_id=account_id, artifact_id=artifact_id
        )
        if artifact["slug"] != slug:
            raise ValueError("compile artifact slug does not match")
    elif artifact_id is not None:
        raise ValueError("failed compile cannot reference an artifact")

    await conn.execute(
        text(
            """
            INSERT INTO design_custom_component_compilation (
              compilation_id, workspace_id, account_id, slug, source_revision_id,
              source_version, status, compiler_protocol_version, compiler_version,
              diagnostics_json, artifact_id
            )
            VALUES (:c, :w, :a, :s, :r, :version,
                    CAST(:status AS design_compilation_status),
                    :protocol, :compiler, CAST(:diagnostics AS jsonb), :i)
            """
        ),
        {
            "c": compilation_id,
            "w": workspace_id,
            "a": account_id,
            "s": slug,
            "r": revision_id,
            "version": source_version,
            "status": status,
            "protocol": protocol_version,
            "compiler": compiler_version,
            "diagnostics": dump_json(diagnostics),
            "i": artifact_id,
        },
    )
    return await require_custom_component_compilation(
        conn, workspace_id=workspace_id, account_id=account_id, compilation_id=compilation_id
    )
