from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .custom_component_contract import custom_component_slug_is_valid


JsonObject = Dict[str, Any]
MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"

# Website-mode undo depth: the newest N batch ids are retained on the undo
# stack; older entries fall off (their envelopes stay in the log for history,
# they are just no longer one-click undoable). Matches the editor's expectation
# of a bounded undo history.
WEB_UNDO_STACK_CAP = 50


class NotFoundError(KeyError):
    def __init__(self, resource_type: str, resource_id: str) -> None:
        super().__init__(resource_type, resource_id)
        self.resource_type = resource_type
        self.resource_id = resource_id

    def __str__(self) -> str:
        return f"{self.resource_type} {self.resource_id} was not found"


class WebDocumentVersionConflict(RuntimeError):
    """A website write lost its optimistic-concurrency race.

    Raised from the repository rather than only checked at the HTTP boundary so
    background agent workers and foreground editor writes share the same atomic
    compare-and-swap protection.
    """

    def __init__(self, document_id: str, expected: int, current: int) -> None:
        super().__init__(
            f"document {document_id} expected version {expected}, current version is {current}"
        )
        self.document_id = document_id
        self.expected = expected
        self.current = current


class CustomComponentArtifactConflict(RuntimeError):
    """An immutable artifact id was reused with different stored metadata."""

    def __init__(self, artifact_id: str) -> None:
        super().__init__(
            f"custom component artifact {artifact_id} already exists with different content"
        )
        self.artifact_id = artifact_id


class CustomComponentSourceVersionConflict(RuntimeError):
    """A component source write or compile targeted a stale source version."""

    def __init__(self, slug: str, expected: int, current: int) -> None:
        super().__init__(
            f"custom component {slug} expected source version {expected}, "
            f"current version is {current}"
        )
        self.slug = slug
        self.expected = expected
        self.current = current


class CustomComponentReferenceError(RuntimeError):
    """A document write introduced an unresolved or cross-account artifact."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        node_id: str,
        artifact_id: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.node_id = node_id
        self.artifact_id = artifact_id


def canonical_custom_component_blob(
    label: str,
    blob: Any,
    *,
    allow_empty: bool = False,
) -> JsonObject:
    if not isinstance(blob, dict):
        raise ValueError(f"{label} blob record must be an object")
    digest = str(blob.get("value") or "")
    opaque_ref = str(blob.get("opaque_ref") or "")
    byte_length = blob.get("byte_length")
    minimum = 0 if allow_empty else 1
    if (
        blob.get("algorithm") != "sha256"
        or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest)
        or opaque_ref != f"sha256/{digest[:2]}/{digest}"
        or not isinstance(byte_length, int)
        or isinstance(byte_length, bool)
        or byte_length < minimum
    ):
        qualifier = "canonical" if allow_empty else "non-empty canonical"
        raise ValueError(f"{label} blob must be a {qualifier} sha256 store record")
    return {
        "algorithm": "sha256",
        "value": digest,
        "opaque_ref": opaque_ref,
        "byte_length": byte_length,
    }


# The ONE `assets`-table column list + row builder: create_asset_record
# (canonical upsert) and register_scene_assets (scene promotion) both write
# through these, so a schema addition cannot silently diverge between the
# two write paths.
ASSET_ROW_COLUMNS = (
    "asset_id, label, kind, status, mime_type, digest_algorithm,"
    " digest_value, byte_length, filename, tags_json, record_json,"
    " created_at, updated_at"
)
ASSET_ROW_PLACEHOLDERS = ",".join("?" for _ in ASSET_ROW_COLUMNS.split(","))


def asset_row_values(record: "JsonObject", now: str) -> tuple:
    media = record.get("media") or {}
    digest = media.get("digest") or {}
    return (
        record["id"],
        record.get("label") or "",
        record.get("kind") or "other",
        record.get("status") or "ready",
        media.get("mime_type"),
        digest.get("algorithm"),
        digest.get("value"),
        media.get("byte_length"),
        media.get("filename"),
        encode(record.get("tags") or []),
        encode(record),
        now,
        now,
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(database_path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    # An async agent run writes progress events from a background thread while
    # the SSE endpoint reads them from another connection. Wait for a busy
    # lock rather than erroring instantly (strictly safer; no semantic change).
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def run_migrations(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(database_path) as connection:
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            connection.executescript(migration.read_text())
        ensure_column(
            connection,
            "documents",
            "effective_brand_mode_json",
            "TEXT",
        )
        ensure_column(connection, "operation_log", "batch_id", "TEXT")
        ensure_column(connection, "documents", "undo_stack_json", "TEXT")
        ensure_column(connection, "documents", "redo_stack_json", "TEXT")
        ensure_column(connection, "web_publishes", "publish_id", "TEXT")
        ensure_column(
            connection,
            "web_publishes",
            "previous_publish_id",
            "TEXT",
        )
        # 2e: per-document standing instructions injected into every agent turn.
        ensure_column(connection, "documents", "agent_instructions", "TEXT")
        # Per-document advanced opt-out (0/1): when set, the editor skips the
        # handoff-absolute freeze seams so agent auto-layout stays live.
        ensure_column(connection, "documents", "layout_managed_editing", "INTEGER")
        # Website mode: a document is either a Rust engine 'scene' or a 'web'
        # WebDoc payload (both live in current_scene_json). The column lets
        # reads branch on kind without sniffing the blob; scene is the default
        # so every pre-existing row keeps its meaning.
        ensure_column(
            connection, "documents", "doc_kind", "TEXT NOT NULL DEFAULT 'scene'"
        )
        # P5 personalization (D4): a web document may be a reusable TEMPLATE and
        # a DERIVED doc records its template + the account it was derived for.
        # is_template=0 keeps every pre-existing row an ordinary doc; the rest
        # are NULL until a clone/derive sets them.
        ensure_column(
            connection, "documents", "is_template", "INTEGER NOT NULL DEFAULT 0"
        )
        ensure_column(connection, "documents", "template_document_id", "TEXT")
        ensure_column(connection, "documents", "template_doc_version", "INTEGER")
        ensure_column(connection, "documents", "account_id", "TEXT")
        # P6.2 compiler/source state. Existing P6.1 families deterministically
        # remain at source_version=0 with no fabricated source snapshot.
        ensure_column(
            connection,
            "custom_components",
            "source_version",
            "INTEGER NOT NULL DEFAULT 0",
        )
        ensure_column(
            connection,
            "custom_components",
            "current_source_revision_id",
            "TEXT",
        )
        for column, definition in (
            ("css_digest_algorithm", "TEXT"),
            ("css_digest_value", "TEXT"),
            ("css_opaque_ref", "TEXT"),
            ("css_byte_length", "INTEGER"),
            ("first_frame_digest_algorithm", "TEXT"),
            ("first_frame_digest_value", "TEXT"),
            ("first_frame_opaque_ref", "TEXT"),
            ("first_frame_byte_length", "INTEGER"),
        ):
            ensure_column(
                connection,
                "custom_component_artifacts",
                column,
                definition,
            )
        # Bulk print controls: the resolved export profile a batch runs with
        # (NULL = format-default artifacts, the pre-profile behavior).
        ensure_column(connection, "instance_batches", "export_profile_json", "TEXT")
        backfill_edit_envelopes(connection)


def backfill_edit_envelopes(connection: sqlite3.Connection) -> None:
    """Wrap pre-envelope operation rows as anonymous version-0 envelopes.

    Idempotent: only operation rows that have never been stamped with a
    batch_id are wrapped, one envelope per row, and stamping happens in the
    same transaction so a re-run finds nothing to do. Version-0 envelopes
    have no intent or inverse and are not undoable.
    """
    connection.execute(
        """
        INSERT OR IGNORE INTO edit_envelopes (
          batch_id, document_id, seq, envelope_version, actor_kind, actor_id,
          source, operations_json, created_at
        )
        SELECT
          'backfill_' || document_id || '_' || sequence,
          document_id, sequence, 0, actor_kind, actor_id, source,
          '[' || operation_json || ']', created_at
        FROM operation_log
        WHERE batch_id IS NULL
        """
    )
    connection.execute(
        """
        UPDATE operation_log
        SET batch_id = 'backfill_' || document_id || '_' || sequence
        WHERE batch_id IS NULL
        """
    )
    connection.commit()


def ensure_column(
    connection: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


class Repository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_document(
        self,
        scene: JsonObject,
        brand_kit: Optional[JsonObject] = None,
        effective_brand_source: Optional[str] = None,
        effective_brand_mode: Optional[JsonObject] = None,
        doc_kind: str = "scene",
        template_document_id: Optional[str] = None,
        template_doc_version: Optional[int] = None,
        account_id: Optional[str] = None,
    ) -> JsonObject:
        now = utc_now()
        # A WebDoc carries id/title at the top level and has no `meta` wrapper;
        # a scene carries them under `meta`. Both blobs still land in
        # current_scene_json (column reuse) — doc_kind is the discriminant.
        if doc_kind == "web":
            document_id = scene["id"]
            title = scene["title"]
            status = "draft"
            brand_ref = (scene.get("theme") or {}).get("brand_kit")
        else:
            document_id = scene["meta"]["id"]
            title = scene["meta"]["title"]
            status = scene_status(scene)
            brand_ref = scene["meta"].get("brand_kit")
        if doc_kind == "web":
            self.validate_custom_component_reference_changes(
                before_web_doc={},
                after_web_doc=scene,
                account_id=account_id,
            )
        effective_source = effective_brand_source
        effective_id = brand_ref["id"] if brand_ref else None
        effective_version = brand_ref["version"] if brand_ref else None
        if brand_kit is not None:
            effective_source = effective_source or "document"
            effective_id = brand_kit.get("id")
            effective_version = brand_kit.get("version")

        self.connection.execute(
            """
            INSERT INTO documents (
              id, title, status, doc_kind, current_scene_json, current_version,
              effective_brand_kit_source, effective_brand_kit_id,
              effective_brand_kit_version, effective_brand_mode_json,
              brand_kit_json, template_document_id, template_doc_version,
              account_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                title,
                status,
                doc_kind,
                encode(scene),
                effective_source,
                effective_id,
                effective_version,
                encode_optional(effective_brand_mode),
                encode_optional(brand_kit),
                template_document_id,
                template_doc_version,
                account_id,
                now,
                now,
            ),
        )
        self.connection.commit()
        return self.require_document(document_id)

    def require_document(self, document_id: str) -> JsonObject:
        row = self.connection.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("document", document_id)
        return document_from_row(row)

    def create_brand_kit(
        self,
        brand_kit: JsonObject,
        brand_summary: JsonObject,
        diagnostics: List[JsonObject],
        source: str,
    ) -> JsonObject:
        now = utc_now()
        brand_kit_id = str(brand_kit["id"])
        version = int(brand_kit["version"])
        self.connection.execute(
            """
            INSERT INTO brand_kits (
              brand_kit_id, version, name, approval_status, product_ready,
              source, brand_kit_json, brand_summary_json, diagnostics_json,
              created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                brand_kit_id,
                version,
                brand_kit["name"],
                brand_kit.get("approval_status"),
                1 if brand_summary.get("product_ready") else 0,
                source,
                encode(brand_kit),
                encode(brand_summary),
                encode(diagnostics),
                now,
                now,
            ),
        )
        self.connection.commit()
        return self.require_brand_kit(brand_kit_id, version)

    def list_brand_kits(self, all_versions: bool = False) -> List[JsonObject]:
        if all_versions:
            rows = self.connection.execute(
                """
                SELECT * FROM brand_kits
                ORDER BY brand_kit_id ASC, version DESC
                """
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT brand_kits.* FROM brand_kits
                INNER JOIN (
                  SELECT brand_kit_id, MAX(version) AS latest_version
                  FROM brand_kits
                  GROUP BY brand_kit_id
                ) latest
                ON brand_kits.brand_kit_id = latest.brand_kit_id
                AND brand_kits.version = latest.latest_version
                ORDER BY brand_kits.brand_kit_id ASC
                """
            ).fetchall()
        return [brand_kit_from_row(row) for row in rows]

    def require_brand_kit(
        self, brand_kit_id: str, version: Optional[int] = None
    ) -> JsonObject:
        if version is None:
            row = self.connection.execute(
                """
                SELECT * FROM brand_kits
                WHERE brand_kit_id = ?
                ORDER BY version DESC
                LIMIT 1
                """,
                (brand_kit_id,),
            ).fetchone()
        else:
            row = self.connection.execute(
                """
                SELECT * FROM brand_kits
                WHERE brand_kit_id = ? AND version = ?
                """,
                (brand_kit_id, version),
            ).fetchone()
        if row is None:
            raise NotFoundError("brand_kit", brand_kit_id)
        return brand_kit_from_row(row)

    def update_brand_kit_approval(
        self, brand_kit_id: str, approval_status: str
    ) -> JsonObject:
        """Set the approval state on the latest version of a kit.

        Updates BOTH the ``approval_status`` column and the mirrored
        ``brand_kit_json.approval_status`` so the persisted kit JSON stays
        consistent with the row. Raises ``NotFoundError`` for an unknown kit.
        """
        record = self.require_brand_kit(brand_kit_id)
        version = int(record["version"])
        brand_kit = record["brand_kit"]
        brand_kit["approval_status"] = approval_status
        self.connection.execute(
            """
            UPDATE brand_kits
            SET approval_status = ?, brand_kit_json = ?, updated_at = ?
            WHERE brand_kit_id = ? AND version = ?
            """,
            (
                approval_status,
                encode(brand_kit),
                utc_now(),
                brand_kit_id,
                version,
            ),
        )
        self.connection.commit()
        return self.require_brand_kit(brand_kit_id, version)

    def create_brand_compatibility_report(
        self,
        report_id: str,
        from_brand_kit: JsonObject,
        to_brand_kit: JsonObject,
        report: JsonObject,
        diagnostics: List[JsonObject],
    ) -> JsonObject:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO brand_compatibility_reports (
              report_id, from_brand_kit_id, from_version, to_brand_kit_id,
              to_version, report_json, diagnostics_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                from_brand_kit["id"],
                int(from_brand_kit["version"]),
                to_brand_kit["id"],
                int(to_brand_kit["version"]),
                encode(report),
                encode(diagnostics),
                now,
            ),
        )
        self.connection.commit()
        return self.require_brand_compatibility_report(report_id)

    def require_brand_compatibility_report(self, report_id: str) -> JsonObject:
        row = self.connection.execute(
            "SELECT * FROM brand_compatibility_reports WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("brand_compatibility_report", report_id)
        return brand_compatibility_report_from_row(row)

    def replace_scene(
        self,
        document_id: str,
        scene: JsonObject,
        diagnostics: List[JsonObject],
    ) -> JsonObject:
        now = utc_now()
        with self.connection:
            document = self.require_document(document_id)
            self.connection.execute(
                """
                UPDATE documents
                SET title = ?, status = ?, current_scene_json = ?,
                    current_version = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    scene["meta"]["title"],
                    scene_status(scene),
                    encode(scene),
                    document["current_version"] + 1,
                    now,
                    document_id,
                ),
            )
            self.store_diagnostics(document_id, "structural", diagnostics, commit=False)
            self.register_scene_assets(scene, commit=False)
        return self.require_document(document_id)

    def register_scene_assets(self, scene: JsonObject, commit: bool = True) -> int:
        """Registry promotion for every locally stored asset the scene
        carries. Every scene-persist path funnels through this, so an asset
        any producer put into a scene (the deepagent's generated imagery,
        edits, QR codes) is servable through the registry-backed endpoints
        and visible in the asset library — the instance-derivation path's
        "generated assets become first-class library records" promotion,
        generalized to all scenes.

        Two write modes, both curation-safe:
        - UNSEEN asset id → insert the full row.
        - EXISTING id whose scene digest DIFFERS → refresh only the
          byte-identity columns (mime/digest/length/filename and the
          record's media block), so regenerate-in-place keeps the registry
          serving the CURRENT pixels. Curated columns (label, kind, status,
          tags) are never touched by a scene write.

        Returns the number of rows written."""
        assets = scene.get("assets")
        if not isinstance(assets, dict) or not assets:
            return 0
        candidates: Dict[str, JsonObject] = {}
        for asset_id, record in assets.items():
            if not isinstance(record, dict):
                continue
            # Engine invariant: scene.assets keys by the record's own id.
            # A mismatched entry is malformed — never fabricate a registry
            # row under a key the record itself does not claim.
            if record.get("id") != asset_id:
                continue
            media = record.get("media") or {}
            location = media.get("location") or {}
            if location.get("provider") != "local-store" or not location.get("opaque_ref"):
                continue
            candidates[str(asset_id)] = record
        if not candidates:
            return 0
        # Chunked lookup: scenes can carry arbitrarily many assets, and this
        # runs inside the document-save transaction — exceeding SQLite's
        # host-parameter limit here would roll back the user's save.
        existing: Dict[str, Tuple[Optional[str], str]] = {}
        ids = list(candidates)
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            placeholders = ",".join("?" for _ in chunk)
            for row in self.connection.execute(
                f"SELECT asset_id, digest_value, record_json FROM assets"
                f" WHERE asset_id IN ({placeholders})",
                tuple(chunk),
            ):
                existing[row[0]] = (row[1], row[2])
        now = utc_now()
        written = 0
        for asset_id, record in candidates.items():
            media = record.get("media") or {}
            digest = media.get("digest") or {}
            if asset_id not in existing:
                cursor = self.connection.execute(
                    f"INSERT OR IGNORE INTO assets ({ASSET_ROW_COLUMNS})"
                    f" VALUES ({ASSET_ROW_PLACEHOLDERS})",
                    asset_row_values(record, now),
                )
                written += max(cursor.rowcount, 0)
                continue
            stored_digest, stored_record_json = existing[asset_id]
            new_digest = digest.get("value")
            if not new_digest or new_digest == stored_digest:
                continue
            # Regenerate-in-place: refresh byte identity, preserve curation.
            # record_json is patched (media block only), not replaced — the
            # stored record may carry curated fields a scene write must not
            # clobber.
            stored_record = decode(stored_record_json)
            stored_record["media"] = media
            cursor = self.connection.execute(
                """
                UPDATE assets
                SET mime_type = ?, digest_algorithm = ?, digest_value = ?,
                    byte_length = ?, filename = ?, record_json = ?, updated_at = ?
                WHERE asset_id = ?
                """,
                (
                    media.get("mime_type"),
                    digest.get("algorithm"),
                    new_digest,
                    media.get("byte_length"),
                    media.get("filename"),
                    encode(stored_record),
                    now,
                    asset_id,
                ),
            )
            written += max(cursor.rowcount, 0)
        if commit:
            self.connection.commit()
        return written

    def update_document_state(
        self,
        document_id: str,
        scene: JsonObject,
        diagnostics: List[JsonObject],
        operations: Iterable[JsonObject],
        source: str,
        actor_kind: str,
        actor_id: Optional[str],
        diagnostic_kind: str,
        effective_brand: Optional[Tuple[str, Optional[JsonObject], Optional[JsonObject]]],
        envelope: Optional[JsonObject] = None,
    ) -> JsonObject:
        operations = list(operations)
        now = utc_now()
        with self.connection:
            document = self.require_document(document_id)
            base_revision = document["current_version"]
            version = document["current_version"] + len(operations)
            if not operations:
                version = document["current_version"]

            brand_source = document.get("effective_brand_kit_source")
            brand_id = document.get("effective_brand_kit_id")
            brand_version = document.get("effective_brand_kit_version")
            brand_mode = document.get("effective_brand_mode")
            brand_json = document.get("brand_kit")
            if effective_brand is not None:
                brand_source, brand_kit, brand_mode = effective_brand
                brand_id = brand_kit.get("id") if brand_kit else None
                brand_version = brand_kit.get("version") if brand_kit else None
                if (
                    brand_source
                    in {
                        "request",
                        "document",
                        "generated_default",
                        "brand_kit_library",
                        # K0.5: an ops-attached kit (scene.meta only) resolved
                        # via the scene ref persists onto the row here, so the
                        # document converges with the dedicated attach route
                        # after its first successful preflight.
                        "scene_ref",
                    }
                    and brand_kit
                ):
                    brand_json = brand_kit

            batch_id = None
            batch = None
            undo_stack = list(document.get("undo_stack") or [])
            redo_stack = list(document.get("redo_stack") or [])
            if operations:
                batch = dict(envelope or {})
                batch_id = batch.get("batch_id") or new_batch_id()
                batch["batch_id"] = batch_id
                batch.setdefault("intent", diagnostic_kind)
                batch.setdefault("base_revision", base_revision)
                batch["operations"] = operations
                reverts = batch.get("reverts_batch_id")
                reapplies = batch.get("reapplies_batch_id")
                if reverts:
                    # Undo: the reverted batch leaves the undo stack and
                    # becomes redoable. The undo envelope itself is not
                    # stacked; undoing an undo is redo.
                    if reverts in undo_stack:
                        undo_stack.remove(reverts)
                    redo_stack.append(reverts)
                elif reapplies:
                    if reapplies in redo_stack:
                        redo_stack.remove(reapplies)
                    undo_stack.append(reapplies)
                else:
                    undo_stack.append(batch_id)
                    redo_stack = []

            self.connection.execute(
                """
                UPDATE documents
                SET title = ?, status = ?, current_scene_json = ?,
                    current_version = ?, effective_brand_kit_source = ?,
                    effective_brand_kit_id = ?, effective_brand_kit_version = ?,
                    effective_brand_mode_json = ?, brand_kit_json = ?,
                    undo_stack_json = ?, redo_stack_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    scene["meta"]["title"],
                    scene_status(scene),
                    encode(scene),
                    version,
                    brand_source,
                    brand_id,
                    brand_version,
                    encode_optional(brand_mode),
                    encode_optional(brand_json),
                    encode(undo_stack),
                    encode(redo_stack),
                    now,
                    document_id,
                ),
            )
            if batch is not None:
                self.append_envelope(
                    document_id,
                    batch,
                    source,
                    actor_kind,
                    actor_id,
                    commit=False,
                )
            self.append_operations(
                document_id,
                operations,
                source,
                actor_kind,
                actor_id,
                diagnostics,
                batch_id=batch_id,
                commit=False,
            )
            self.store_diagnostics(document_id, diagnostic_kind, diagnostics, commit=False)
            self.register_scene_assets(scene, commit=False)
        return self.require_document(document_id)

    def update_web_document(
        self,
        document_id: str,
        web_doc: JsonObject,
        *,
        intent: Optional[str],
        checkpoint_label: Optional[str],
        operations: List[JsonObject],
        inverse_operations: Optional[List[JsonObject]],
        actor_kind: str = "agent",
        source: str = "agent",
        push_undo: bool = True,
        reverts_batch_id: Optional[str] = None,
        reapplies_batch_id: Optional[str] = None,
        expected_base_version: Optional[int] = None,
    ) -> JsonObject:
        """Persist a website-mode write: replace the stored WebDoc and append an
        invertible edit envelope through the SAME machinery a scene write uses
        (append_envelope + append_operations + a monotonic next_*_sequence), so
        the web history shares the documents/edit_envelopes tables and stays
        replayable later.

        Undo bookkeeping mirrors the scene stacks (documents.undo_stack_json /
        redo_stack_json), which for web docs are the authoritative source of the
        active undo/redo path — nothing is derived from envelope ordering:
        - a normal write (`push_undo=True`, no reverts/reapplies) pushes the new
          batch_id onto the undo stack (capped at WEB_UNDO_STACK_CAP, oldest
          dropped) and clears the redo stack.
        - `reverts_batch_id` (an undo step) removes the reverted batch from the
          undo stack and pushes it onto the redo stack; the revert envelope
          itself is NOT stacked (undoing an undo is redo).
        - `reapplies_batch_id` (a redo step) removes it from the redo stack and
          pushes it back onto the undo stack.
        - `push_undo=False` writes without touching either stack.

        Deliberately NOT reused from update_document_state (a WebDoc is not a
        scene, so the scene-specific pieces are unsafe or meaningless here):
        - register_scene_assets — a WebDoc's `assets` map is a different shape
          (keyed AssetRecords, no scene node graph); its bytes already live in
          the shared asset store, so there is nothing to promote.
        - effective-brand columns — a web turn does not recompute an effective
          scene brand; the theme ref on the WebDoc is the source of truth.

        Manual edits and current agent turns both persist real WebOperation
        batches with the helper's checked inverse_operations. Historical rows
        may still contain a `replace_web_doc` marker; undo/redo retains a legacy
        compatibility branch for those envelopes.
        """
        now = utc_now()
        with self.connection:
            document = self.require_document(document_id)
            base_revision = document["current_version"]
            if (
                expected_base_version is not None
                and base_revision != expected_base_version
            ):
                raise WebDocumentVersionConflict(
                    document_id, expected_base_version, base_revision
                )
            self.validate_custom_component_reference_changes(
                before_web_doc=document["scene"],
                after_web_doc=web_doc,
                account_id=document.get("account_id"),
            )
            version = base_revision + 1
            batch_id = new_batch_id()
            undo_stack = list(document.get("undo_stack") or [])
            redo_stack = list(document.get("redo_stack") or [])
            if reverts_batch_id:
                if reverts_batch_id in undo_stack:
                    undo_stack.remove(reverts_batch_id)
                redo_stack.append(reverts_batch_id)
            elif reapplies_batch_id:
                if reapplies_batch_id in redo_stack:
                    redo_stack.remove(reapplies_batch_id)
                undo_stack.append(reapplies_batch_id)
            elif push_undo:
                undo_stack.append(batch_id)
                if len(undo_stack) > WEB_UNDO_STACK_CAP:
                    undo_stack = undo_stack[-WEB_UNDO_STACK_CAP:]
                redo_stack = []
            envelope = {
                "batch_id": batch_id,
                "base_revision": base_revision,
                "intent": intent,
                "checkpoint_label": checkpoint_label,
                "operations": operations,
                "inverse_operations": inverse_operations,
                "reverts_batch_id": reverts_batch_id,
                "reapplies_batch_id": reapplies_batch_id,
            }
            if expected_base_version is None:
                cursor = self.connection.execute(
                    """
                    UPDATE documents
                    SET title = ?, current_scene_json = ?, current_version = ?,
                        undo_stack_json = ?, redo_stack_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        web_doc["title"],
                        encode(web_doc),
                        version,
                        encode(undo_stack),
                        encode(redo_stack),
                        now,
                        document_id,
                    ),
                )
            else:
                # The version predicate closes the race between the read above
                # and this write when another connection commits in between.
                cursor = self.connection.execute(
                    """
                    UPDATE documents
                    SET title = ?, current_scene_json = ?, current_version = ?,
                        undo_stack_json = ?, redo_stack_json = ?, updated_at = ?
                    WHERE id = ? AND current_version = ?
                    """,
                    (
                        web_doc["title"],
                        encode(web_doc),
                        version,
                        encode(undo_stack),
                        encode(redo_stack),
                        now,
                        document_id,
                        expected_base_version,
                    ),
                )
            if cursor.rowcount != 1:
                current = self.require_document(document_id)["current_version"]
                raise WebDocumentVersionConflict(
                    document_id,
                    expected_base_version
                    if expected_base_version is not None
                    else base_revision,
                    current,
                )
            self.append_envelope(
                document_id,
                envelope,
                source,
                actor_kind,
                None,
                commit=False,
            )
            self.append_operations(
                document_id,
                operations,
                source,
                actor_kind,
                None,
                [],
                batch_id=batch_id,
                commit=False,
            )
        return self.require_document(document_id)

    def append_operations(
        self,
        document_id: str,
        operations: Iterable[JsonObject],
        source: str,
        actor_kind: str,
        actor_id: Optional[str],
        diagnostics: List[JsonObject],
        batch_id: Optional[str] = None,
        commit: bool = True,
    ) -> None:
        next_sequence = self.next_operation_sequence(document_id)
        now = utc_now()
        rows = []
        for offset, operation in enumerate(operations):
            rows.append(
                (
                    document_id,
                    next_sequence + offset,
                    encode(operation),
                    actor_kind,
                    actor_id,
                    source,
                    encode(diagnostics),
                    batch_id,
                    now,
                )
            )
        self.connection.executemany(
            """
            INSERT INTO operation_log (
              document_id, sequence, operation_json, actor_kind, actor_id,
              source, diagnostics_json, batch_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        if commit:
            self.connection.commit()

    def append_envelope(
        self,
        document_id: str,
        envelope: JsonObject,
        source: str,
        actor_kind: str,
        actor_id: Optional[str],
        commit: bool = True,
    ) -> str:
        batch_id = envelope.get("batch_id") or new_batch_id()
        self.connection.execute(
            """
            INSERT INTO edit_envelopes (
              batch_id, document_id, seq, envelope_version, base_revision,
              actor_kind, actor_id, source, intent, checkpoint_label,
              touched_targets_json, operations_json, inverse_operations_json,
              lineage_json, reverts_batch_id, reapplies_batch_id, created_at
            )
            VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                document_id,
                self.next_envelope_sequence(document_id),
                envelope.get("base_revision"),
                actor_kind,
                actor_id,
                source,
                envelope.get("intent"),
                envelope.get("checkpoint_label"),
                encode(envelope.get("touched_targets") or []),
                encode(envelope.get("operations") or []),
                encode_optional(envelope.get("inverse_operations")),
                encode_optional(envelope.get("lineage")),
                envelope.get("reverts_batch_id"),
                envelope.get("reapplies_batch_id"),
                utc_now(),
            ),
        )
        if commit:
            self.connection.commit()
        return batch_id

    def next_envelope_sequence(self, document_id: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM edit_envelopes WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        return int(row["max_seq"]) + 1

    def list_envelopes(
        self,
        document_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
        newest_first: bool = True,
    ) -> List[JsonObject]:
        self.require_document(document_id)
        order = "DESC" if newest_first else "ASC"
        query = f"""
            SELECT * FROM edit_envelopes
            WHERE document_id = ?
            ORDER BY seq {order}
        """
        params: List[Any] = [document_id]
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        rows = self.connection.execute(query, params).fetchall()
        return [envelope_from_row(row) for row in rows]

    def require_envelope(self, document_id: str, batch_id: str) -> JsonObject:
        row = self.connection.execute(
            "SELECT * FROM edit_envelopes WHERE document_id = ? AND batch_id = ?",
            (document_id, batch_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("edit_envelope", batch_id)
        return envelope_from_row(row)

    def list_operations(self, document_id: str) -> List[JsonObject]:
        self.require_document(document_id)
        rows = self.connection.execute(
            """
            SELECT * FROM operation_log
            WHERE document_id = ?
            ORDER BY sequence ASC
            """,
            (document_id,),
        ).fetchall()
        return [operation_from_row(row) for row in rows]

    def next_operation_sequence(self, document_id: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM operation_log WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        return int(row["max_sequence"]) + 1

    def set_agent_instructions(
        self, document_id: str, instructions: Optional[str]
    ) -> JsonObject:
        self.require_document(document_id)
        self.connection.execute(
            "UPDATE documents SET agent_instructions = ?, updated_at = ? WHERE id = ?",
            (instructions, utc_now(), document_id),
        )
        self.connection.commit()
        return self.require_document(document_id)

    def set_layout_managed_editing(
        self, document_id: str, enabled: bool
    ) -> JsonObject:
        self.require_document(document_id)
        self.connection.execute(
            "UPDATE documents SET layout_managed_editing = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, utc_now(), document_id),
        )
        self.connection.commit()
        return self.require_document(document_id)

    # --- Agent runs: async turns + their durable SSE event stream ---

    def create_run(self, run_id: str, document_id: Optional[str]) -> JsonObject:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO agent_runs (run_id, status, document_id, result_json, created_at, updated_at)
            VALUES (?, 'running', ?, NULL, ?, ?)
            """,
            (run_id, document_id, now, now),
        )
        self.connection.commit()
        return self.require_run(run_id)

    def next_run_event_seq(self, run_id: str) -> int:
        # Only the run's own background thread appends its events, so MAX+1
        # is race-free (mirrors next_operation_sequence per document).
        row = self.connection.execute(
            "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM run_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return int(row["max_seq"]) + 1

    def append_run_event(self, run_id: str, event_type: str, data: JsonObject) -> int:
        seq = self.next_run_event_seq(run_id)
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO run_events (run_id, seq, event_type, data_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, seq, event_type, encode(data or {}), now),
        )
        self.connection.execute(
            "UPDATE agent_runs SET updated_at = ? WHERE run_id = ?",
            (now, run_id),
        )
        self.connection.commit()
        return seq

    def set_run_result(
        self, run_id: str, status: str, result: Optional[JsonObject]
    ) -> None:
        now = utc_now()
        self.connection.execute(
            "UPDATE agent_runs SET status = ?, result_json = ?, updated_at = ? WHERE run_id = ?",
            (status, encode_optional(result), now, run_id),
        )
        self.connection.commit()

    def get_run(self, run_id: str) -> Optional[JsonObject]:
        row = self.connection.execute(
            "SELECT * FROM agent_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return agent_run_from_row(row) if row is not None else None

    def list_running_runs(self) -> List[JsonObject]:
        """Runs still marked 'running', joined with their document's doc_kind
        (None when the run has no document). Turns execute only on daemon
        threads inside the live API process, so at startup every 'running'
        row is an orphan by construction — the startup sweep fails them."""
        rows = self.connection.execute(
            """
            SELECT r.run_id, r.document_id, d.doc_kind
            FROM agent_runs r LEFT JOIN documents d ON d.id = r.document_id
            WHERE r.status = 'running'
            ORDER BY r.created_at ASC
            """
        ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "document_id": row["document_id"],
                "doc_kind": row["doc_kind"],
            }
            for row in rows
        ]

    def require_run(self, run_id: str) -> JsonObject:
        run = self.get_run(run_id)
        if run is None:
            raise NotFoundError("agent_run", run_id)
        return run

    def list_run_events(self, run_id: str, after_seq: int = 0) -> List[JsonObject]:
        rows = self.connection.execute(
            """
            SELECT * FROM run_events
            WHERE run_id = ? AND seq > ?
            ORDER BY seq ASC
            """,
            (run_id, after_seq),
        ).fetchall()
        return [run_event_from_row(row) for row in rows]

    def create_snapshot(
        self, document_id: str, snapshot_id: str, reason: str
    ) -> JsonObject:
        document = self.require_document(document_id)
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO snapshots (snapshot_id, document_id, version, scene_json, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                document_id,
                document["current_version"],
                encode(document["scene"]),
                reason,
                now,
            ),
        )
        self.connection.commit()
        return self.require_snapshot(document_id, snapshot_id)

    def list_snapshots(self, document_id: str) -> List[JsonObject]:
        self.require_document(document_id)
        rows = self.connection.execute(
            """
            SELECT * FROM snapshots
            WHERE document_id = ?
            ORDER BY created_at ASC
            """,
            (document_id,),
        ).fetchall()
        return [snapshot_from_row(row) for row in rows]

    def require_snapshot(self, document_id: str, snapshot_id: str) -> JsonObject:
        row = self.connection.execute(
            "SELECT * FROM snapshots WHERE document_id = ? AND snapshot_id = ?",
            (document_id, snapshot_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("snapshot", snapshot_id)
        return snapshot_from_row(row)

    def create_template_revision(
        self,
        document_id: str,
        template_revision_id: str,
        source_snapshot_id: Optional[str],
        scene: JsonObject,
        slot_summary: List[JsonObject],
    ) -> JsonObject:
        document = self.require_document(document_id)
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO template_revisions (
              template_revision_id, document_id, source_snapshot_id, version,
              scene_json, export_profiles_json, slot_summary_json, brand_ref_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                template_revision_id,
                document_id,
                source_snapshot_id,
                document["current_version"] + 1,
                encode(scene),
                encode(scene.get("export_profiles", [])),
                encode(slot_summary),
                encode_optional(scene.get("meta", {}).get("brand_kit")),
                now,
            ),
        )
        self.connection.commit()
        return self.require_template_revision(template_revision_id)

    def require_template_revision(self, template_revision_id: str) -> JsonObject:
        row = self.connection.execute(
            "SELECT * FROM template_revisions WHERE template_revision_id = ?",
            (template_revision_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("template_revision", template_revision_id)
        return template_revision_from_row(row)

    def create_asset_metadata(self, payload: JsonObject) -> JsonObject:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO asset_metadata (
              asset_id, document_id, kind, filename, source_uri, mime_type,
              width, height, dpi, provenance_json, licensing_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["asset_id"],
                payload.get("document_id"),
                payload["kind"],
                payload.get("filename"),
                payload.get("source_uri"),
                payload.get("mime_type"),
                payload.get("width"),
                payload.get("height"),
                payload.get("dpi"),
                encode(payload.get("provenance") or {}),
                encode(payload.get("licensing") or {}),
                now,
            ),
        )
        self.connection.commit()
        return self.require_asset_metadata(payload["asset_id"])

    def require_asset_metadata(self, asset_id: str) -> JsonObject:
        row = self.connection.execute(
            "SELECT * FROM asset_metadata WHERE asset_id = ?", (asset_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("asset", asset_id)
        return asset_from_row(row)

    def create_asset_record(self, record: JsonObject) -> JsonObject:
        self.connection.execute(
            f"""
            INSERT INTO assets ({ASSET_ROW_COLUMNS})
            VALUES ({ASSET_ROW_PLACEHOLDERS})
            ON CONFLICT(asset_id) DO UPDATE SET
              label = excluded.label,
              kind = excluded.kind,
              status = excluded.status,
              mime_type = excluded.mime_type,
              digest_algorithm = excluded.digest_algorithm,
              digest_value = excluded.digest_value,
              byte_length = excluded.byte_length,
              filename = excluded.filename,
              tags_json = excluded.tags_json,
              record_json = excluded.record_json,
              updated_at = excluded.updated_at
            """,
            asset_row_values(record, utc_now()),
        )
        self.connection.commit()
        return self.require_asset_record(record["id"])

    def require_asset_record(self, asset_id: str) -> JsonObject:
        row = self.connection.execute(
            "SELECT * FROM assets WHERE asset_id = ?", (asset_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("asset", asset_id)
        return asset_record_from_row(row)

    def list_asset_records(
        self,
        kind: Optional[str] = None,
        q: Optional[str] = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> List[JsonObject]:
        clauses: List[str] = []
        params: List[Any] = []
        if not include_archived:
            clauses.append("status != 'archived'")
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if q:
            like = f"%{q.lower()}%"
            clauses.append(
                "(LOWER(label) LIKE ? OR LOWER(COALESCE(filename, '')) LIKE ?"
                " OR LOWER(tags_json) LIKE ?)"
            )
            params.extend([like, like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.connection.execute(
            f"""
            SELECT * FROM assets {where}
            ORDER BY updated_at DESC, asset_id
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
        return [asset_record_from_row(row) for row in rows]

    def update_asset_status(self, asset_id: str, status: str) -> JsonObject:
        stored = self.require_asset_record(asset_id)
        record = stored["asset"]
        record["status"] = status
        self.connection.execute(
            "UPDATE assets SET status = ?, record_json = ?, updated_at = ? WHERE asset_id = ?",
            (status, encode(record), utc_now(), asset_id),
        )
        self.connection.commit()
        return self.require_asset_record(asset_id)

    def delete_asset_record(self, asset_id: str) -> None:
        self.require_asset_record(asset_id)
        self.connection.execute("DELETE FROM assets WHERE asset_id = ?", (asset_id,))
        self.connection.commit()

    def count_assets_with_digest(
        self, digest_value: str, exclude_asset_id: Optional[str] = None
    ) -> int:
        # record_json LIKE keeps thumbnail digests visible too: any record
        # whose canonical JSON mentions the digest still references it.
        params: List[Any] = [f"%{digest_value}%"]
        clause = "record_json LIKE ?"
        if exclude_asset_id:
            clause += " AND asset_id != ?"
            params.append(exclude_asset_id)
        row = self.connection.execute(
            f"SELECT COUNT(*) AS n FROM assets WHERE {clause}", params
        ).fetchone()
        return int(row["n"])

    def count_documents_referencing(self, needle: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE current_scene_json LIKE ?",
            (f"%{needle}%",),
        ).fetchone()
        return int(row["n"])

    # ------------------------------------------------------------------
    # Phase G personalization runtime (slice G8)
    # ------------------------------------------------------------------

    def upsert_binding_set(
        self,
        binding: JsonObject,
        status: str,
        diagnostics: List[JsonObject],
    ) -> JsonObject:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO binding_sets (
              binding_set_id, template_revision_id, binding_json, status,
              diagnostics_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(binding_set_id) DO UPDATE SET
              template_revision_id = excluded.template_revision_id,
              binding_json = excluded.binding_json,
              status = excluded.status,
              diagnostics_json = excluded.diagnostics_json,
              updated_at = excluded.updated_at
            """,
            (
                binding["binding_set_id"],
                binding["template_revision_id"],
                encode(binding),
                status,
                encode(diagnostics),
                now,
                now,
            ),
        )
        self.connection.commit()
        return self.require_binding_set(binding["binding_set_id"])

    def require_binding_set(self, binding_set_id: str) -> JsonObject:
        row = self.connection.execute(
            "SELECT * FROM binding_sets WHERE binding_set_id = ?",
            (binding_set_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("binding_set", binding_set_id)
        return binding_set_from_row(row)

    def list_binding_sets(
        self, template_revision_id: Optional[str] = None
    ) -> List[JsonObject]:
        if template_revision_id is None:
            rows = self.connection.execute(
                "SELECT * FROM binding_sets ORDER BY binding_set_id"
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM binding_sets
                WHERE template_revision_id = ?
                ORDER BY binding_set_id
                """,
                (template_revision_id,),
            ).fetchall()
        return [binding_set_from_row(row) for row in rows]

    def delete_binding_set(self, binding_set_id: str) -> None:
        self.require_binding_set(binding_set_id)
        self.connection.execute(
            "DELETE FROM binding_sets WHERE binding_set_id = ?",
            (binding_set_id,),
        )
        self.connection.commit()

    def upsert_instance(self, instance: JsonObject) -> JsonObject:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO instances (
              instance_id, template_revision_id, binding_set_id, batch_id,
              status, fit_status, derived_scene_json, diagnostics_json,
              audit_json, fit_report_json, artifacts_json,
              generated_assets_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(instance_id) DO UPDATE SET
              batch_id = excluded.batch_id,
              status = excluded.status,
              fit_status = excluded.fit_status,
              derived_scene_json = excluded.derived_scene_json,
              diagnostics_json = excluded.diagnostics_json,
              audit_json = excluded.audit_json,
              fit_report_json = excluded.fit_report_json,
              artifacts_json = excluded.artifacts_json,
              generated_assets_json = excluded.generated_assets_json,
              updated_at = excluded.updated_at
            """,
            (
                instance["instance_id"],
                instance["template_revision_id"],
                instance["binding_set_id"],
                instance.get("batch_id"),
                instance["status"],
                instance["fit_status"],
                encode(instance["derived_scene"]),
                encode(instance.get("diagnostics", [])),
                encode(instance.get("audit", [])),
                encode(instance.get("fit_report", {})),
                encode(instance.get("artifacts", [])),
                encode(instance.get("generated_assets", {})),
                now,
                now,
            ),
        )
        self.connection.commit()
        return self.require_instance(instance["instance_id"])

    def require_instance(self, instance_id: str) -> JsonObject:
        row = self.connection.execute(
            "SELECT * FROM instances WHERE instance_id = ?", (instance_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("instance", instance_id)
        return instance_from_row(row)

    def list_instances(
        self,
        template_revision_id: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> List[JsonObject]:
        clauses: List[str] = []
        params: List[Any] = []
        if template_revision_id is not None:
            clauses.append("template_revision_id = ?")
            params.append(template_revision_id)
        if batch_id is not None:
            clauses.append("batch_id = ?")
            params.append(batch_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.connection.execute(
            f"SELECT * FROM instances {where} ORDER BY instance_id", params
        ).fetchall()
        return [instance_from_row(row) for row in rows]

    def create_batch(self, batch: JsonObject) -> JsonObject:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO instance_batches (
              batch_id, template_revision_id, status, binding_set_ids_json,
              export_formats_json, export_profile_json, chunk_size, cursor,
              counts_json, manifest_json, diagnostics_json, created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch["batch_id"],
                batch["template_revision_id"],
                batch["status"],
                encode(batch["binding_set_ids"]),
                encode(batch["export_formats"]),
                encode_optional(batch.get("export_profile")),
                batch["chunk_size"],
                batch["cursor"],
                encode(batch.get("counts", {})),
                encode(batch.get("manifest", [])),
                encode(batch.get("diagnostics", [])),
                now,
                now,
            ),
        )
        self.connection.commit()
        return self.require_batch(batch["batch_id"])

    def update_batch_progress(
        self,
        batch_id: str,
        cursor: int,
        status: str,
        counts: JsonObject,
        manifest: List[JsonObject],
        diagnostics: List[JsonObject],
    ) -> JsonObject:
        self.connection.execute(
            """
            UPDATE instance_batches
            SET cursor = ?, status = ?, counts_json = ?, manifest_json = ?,
                diagnostics_json = ?, updated_at = ?
            WHERE batch_id = ?
            """,
            (
                cursor,
                status,
                encode(counts),
                encode(manifest),
                encode(diagnostics),
                utc_now(),
                batch_id,
            ),
        )
        self.connection.commit()
        return self.require_batch(batch_id)

    def require_batch(self, batch_id: str) -> JsonObject:
        row = self.connection.execute(
            "SELECT * FROM instance_batches WHERE batch_id = ?", (batch_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("instance_batch", batch_id)
        return batch_from_row(row)

    def upsert_repair_request(self, repair: JsonObject) -> JsonObject:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO repair_queue (
              repair_id, template_revision_id, slot_key, node_id,
              binding_set_id, instance_id, reason, status, created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(repair_id) DO UPDATE SET
              instance_id = excluded.instance_id,
              reason = excluded.reason,
              updated_at = excluded.updated_at
            """,
            (
                repair["repair_id"],
                repair["template_revision_id"],
                repair["slot_key"],
                repair["node_id"],
                repair["binding_set_id"],
                repair.get("instance_id"),
                repair["reason"],
                repair.get("status", "open"),
                now,
                now,
            ),
        )
        self.connection.commit()
        row = self.connection.execute(
            "SELECT * FROM repair_queue WHERE repair_id = ?",
            (repair["repair_id"],),
        ).fetchone()
        return repair_from_row(row)

    def list_repair_queue(
        self, template_revision_id: str, status: Optional[str] = None
    ) -> List[JsonObject]:
        if status is None:
            rows = self.connection.execute(
                """
                SELECT * FROM repair_queue
                WHERE template_revision_id = ?
                ORDER BY repair_id
                """,
                (template_revision_id,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM repair_queue
                WHERE template_revision_id = ? AND status = ?
                ORDER BY repair_id
                """,
                (template_revision_id, status),
            ).fetchall()
        return [repair_from_row(row) for row in rows]

    def store_diagnostics(
        self,
        document_id: str,
        kind: str,
        diagnostics: List[JsonObject],
        commit: bool = True,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO document_diagnostics (document_id, kind, diagnostics_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (document_id, kind, encode(diagnostics), utc_now()),
        )
        if commit:
            self.connection.commit()

    def latest_diagnostics(
        self, document_id: str, kind: Optional[str] = None
    ) -> Optional[JsonObject]:
        self.require_document(document_id)
        if kind is None:
            row = self.connection.execute(
                """
                SELECT * FROM document_diagnostics
                WHERE document_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (document_id,),
            ).fetchone()
        else:
            row = self.connection.execute(
                """
                SELECT * FROM document_diagnostics
                WHERE document_id = ? AND kind = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (document_id, kind),
            ).fetchone()
        return diagnostics_from_row(row) if row else None

    # --- Website-mode publishes ------------------------------------------- #

    def register_web_publish_revision(
        self, revision: JsonObject
    ) -> JsonObject:
        """Append one immutable, content-identified publish package."""

        self.connection.execute(
            """
            INSERT OR IGNORE INTO web_publish_revisions (
              publish_id, slug, document_id, doc_version, html, html_digest,
              manifest_json, manifest_digest, package_digest, runtime_version,
              created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision["publish_id"],
                revision["slug"],
                revision["document_id"],
                revision["doc_version"],
                revision["html"],
                revision["html_digest"],
                encode(revision["manifest"]),
                revision["manifest_digest"],
                revision["package_digest"],
                revision.get("runtime_version"),
                revision.get("created_at") or utc_now(),
            ),
        )
        self.connection.commit()
        stored = self.require_web_publish_revision(revision["publish_id"])
        comparable = {
            key: stored.get(key)
            for key in (
                "publish_id",
                "slug",
                "document_id",
                "doc_version",
                "html",
                "html_digest",
                "manifest",
                "manifest_digest",
                "package_digest",
                "runtime_version",
            )
        }
        expected = {
            key: revision.get(key)
            for key in comparable
        }
        if comparable != expected:
            raise ValueError(
                f"publish id {revision['publish_id']} already exists with different content"
            )
        return stored

    def require_web_publish_revision(self, publish_id: str) -> JsonObject:
        row = self.connection.execute(
            "SELECT * FROM web_publish_revisions WHERE publish_id = ?",
            (publish_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("web_publish_revision", publish_id)
        return web_publish_revision_from_row(row)

    def upsert_web_publish(
        self,
        slug: str,
        document_id: str,
        doc_version: int,
        html: str,
        runtime_version: Optional[int],
        publish_id: Optional[str] = None,
    ) -> JsonObject:
        """Publish (or republish) ``slug``. On an existing row the current
        html/doc_version move into previous_* (the single-step rollback buffer)
        and the new payload becomes current, status 'active' — all in one atomic
        UPSERT so a republish can never observe a half-swapped row."""
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO web_publishes (
              slug, document_id, doc_version, html, previous_html,
              previous_doc_version, runtime_version, status, created_at, updated_at,
              publish_id, previous_publish_id
            )
            VALUES (?, ?, ?, ?, NULL, NULL, ?, 'active', ?, ?, ?, NULL)
            ON CONFLICT(slug) DO UPDATE SET
              document_id = excluded.document_id,
              doc_version = excluded.doc_version,
              html = excluded.html,
              previous_html = web_publishes.html,
              previous_doc_version = web_publishes.doc_version,
              previous_publish_id = web_publishes.publish_id,
              publish_id = excluded.publish_id,
              runtime_version = excluded.runtime_version,
              status = 'active',
              updated_at = excluded.updated_at
            """,
            (
                slug,
                document_id,
                doc_version,
                html,
                runtime_version,
                now,
                now,
                publish_id,
            ),
        )
        self.connection.commit()
        return self.require_web_publish(slug)

    def require_web_publish(self, slug: str) -> JsonObject:
        publish = self.get_web_publish(slug)
        if publish is None:
            raise NotFoundError("web_publish", slug)
        return publish

    def get_web_publish(self, slug: str) -> Optional[JsonObject]:
        row = self.connection.execute(
            "SELECT * FROM web_publishes WHERE slug = ?", (slug,)
        ).fetchone()
        if row is None:
            return None
        publish = web_publish_from_row(row)
        publish_id = publish.get("publish_id")
        if isinstance(publish_id, str):
            revision = self.require_web_publish_revision(publish_id)
            publish.update(
                {
                    "html": revision["html"],
                    "doc_version": revision["doc_version"],
                    "runtime_version": revision["runtime_version"],
                    "manifest": revision["manifest"],
                    "manifest_digest": revision["manifest_digest"],
                    "package_digest": revision["package_digest"],
                    "html_digest": revision["html_digest"],
                }
            )
        return publish

    def get_web_publish_for_document(self, document_id: str) -> Optional[JsonObject]:
        row = self.connection.execute(
            """
            SELECT * FROM web_publishes
            WHERE document_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (document_id,),
        ).fetchone()
        return self.get_web_publish(row["slug"]) if row else None

    def set_web_publish_status(
        self, slug: str, status: str
    ) -> Optional[JsonObject]:
        cursor = self.connection.execute(
            "UPDATE web_publishes SET status = ?, updated_at = ? WHERE slug = ?",
            (status, utc_now(), slug),
        )
        self.connection.commit()
        if cursor.rowcount == 0:
            return None
        return self.get_web_publish(slug)

    def rollback_web_publish(self, slug: str) -> Any:
        """Swap current and previous html/doc_version (a one-step undo of the
        last publish) and re-activate. Returns the updated publish dict, or a
        string marker: 'not_found' (unknown slug) or 'no_previous' (nothing to
        roll back to)."""
        row = self.connection.execute(
            "SELECT * FROM web_publishes WHERE slug = ?", (slug,)
        ).fetchone()
        if row is None:
            return "not_found"
        if row["previous_html"] is None:
            return "no_previous"
        # A single UPDATE evaluates every SET expression against the ORIGINAL
        # row, so reading and writing html/previous_html in one statement swaps
        # them atomically.
        self.connection.execute(
            """
            UPDATE web_publishes SET
              html = previous_html,
              doc_version = previous_doc_version,
              previous_html = html,
              previous_doc_version = doc_version,
              publish_id = previous_publish_id,
              previous_publish_id = publish_id,
              status = 'active',
              updated_at = ?
            WHERE slug = ?
            """,
            (utc_now(), slug),
        )
        self.connection.commit()
        return self.require_web_publish(slug)

    # --- P6 custom-component immutable registry ---------------------------- #

    def register_custom_component_artifact(
        self, artifact: JsonObject
    ) -> JsonObject:
        """Persist one successful compile artifact.

        There is deliberately no update method. An exact retry is idempotent;
        reusing the content-derived id with different metadata is a hard
        conflict. The caller stores source/bundle bytes before invoking this
        seam, so every committed row points at durable content-addressed bytes.
        """

        account_id = str(artifact["account_id"])
        slug = str(artifact["slug"])
        artifact_id = str(artifact["artifact_id"])
        source_blob = canonical_custom_component_blob(
            "source", artifact["source"]
        )
        bundle_blob = canonical_custom_component_blob(
            "bundle", artifact["bundle"]
        )
        css_blob = (
            canonical_custom_component_blob(
                "css", artifact["css"], allow_empty=True
            )
            if artifact.get("css") is not None
            else None
        )
        first_frame_blob = (
            canonical_custom_component_blob(
                "first_frame",
                artifact["first_frame"],
                allow_empty=True,
            )
            if artifact.get("first_frame") is not None
            else None
        )
        if (css_blob is None) != (first_frame_blob is None):
            raise ValueError(
                "css and first_frame blob records must be supplied together"
            )
        manifest = artifact.get("manifest", {})
        provenance = artifact.get("provenance", {})
        self.require_web_account(account_id)
        if not custom_component_slug_is_valid(slug):
            raise ValueError(
                "custom component slug must be 1–64 lowercase kebab-case characters"
            )
        if not isinstance(manifest, dict) or not isinstance(provenance, dict):
            raise ValueError("custom component manifest and provenance must be objects")
        if (
            not artifact_id.startswith("ccart_")
            or len(artifact_id) != len("ccart_") + 64
            or any(ch not in "0123456789abcdef" for ch in artifact_id[len("ccart_") :])
        ):
            raise ValueError("artifact_id must be ccart_<lowercase sha256>")
        now = utc_now()
        candidate = {
            "artifact_id": artifact_id,
            "account_id": account_id,
            "slug": slug,
            "source": source_blob,
            "bundle": bundle_blob,
            "css": css_blob,
            "first_frame": first_frame_blob,
            "manifest": manifest,
            "provenance": provenance,
        }
        existing = self.get_custom_component_artifact(artifact_id)
        if existing is not None:
            comparable = {
                key: existing[key]
                for key in (
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
            }
            if comparable != candidate:
                raise CustomComponentArtifactConflict(artifact_id)
            return existing

        with self.connection:
            self.connection.execute(
                """
                INSERT INTO custom_components (
                  account_id, slug, created_at, updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(account_id, slug) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (account_id, slug, now, now),
            )
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO custom_component_artifacts (
                  artifact_id, account_id, slug,
                  source_digest_algorithm, source_digest_value,
                  source_opaque_ref, source_byte_length,
                  bundle_digest_algorithm, bundle_digest_value,
                  bundle_opaque_ref, bundle_byte_length,
                  css_digest_algorithm, css_digest_value,
                  css_opaque_ref, css_byte_length,
                  first_frame_digest_algorithm, first_frame_digest_value,
                  first_frame_opaque_ref, first_frame_byte_length,
                  manifest_json, provenance_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    account_id,
                    slug,
                    "sha256",
                    source_blob["value"],
                    source_blob["opaque_ref"],
                    source_blob["byte_length"],
                    "sha256",
                    bundle_blob["value"],
                    bundle_blob["opaque_ref"],
                    bundle_blob["byte_length"],
                    css_blob["algorithm"] if css_blob else None,
                    css_blob["value"] if css_blob else None,
                    css_blob["opaque_ref"] if css_blob else None,
                    css_blob["byte_length"] if css_blob else None,
                    first_frame_blob["algorithm"] if first_frame_blob else None,
                    first_frame_blob["value"] if first_frame_blob else None,
                    first_frame_blob["opaque_ref"] if first_frame_blob else None,
                    first_frame_blob["byte_length"] if first_frame_blob else None,
                    encode(manifest),
                    encode(provenance),
                    now,
                ),
            )
        stored = self.get_custom_component_artifact(artifact_id)
        if stored is None:
            raise RuntimeError(
                f"custom component artifact {artifact_id} was not persisted"
            )
        comparable = {
            key: stored[key]
            for key in (
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
        }
        if cursor.rowcount == 0 and comparable != candidate:
            raise CustomComponentArtifactConflict(artifact_id)
        return stored

    def get_custom_component_artifact(
        self, artifact_id: str
    ) -> Optional[JsonObject]:
        row = self.connection.execute(
            "SELECT * FROM custom_component_artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        return custom_component_artifact_from_row(row) if row is not None else None

    def get_custom_component_artifact_for_account(
        self, account_id: str, artifact_id: str
    ) -> Optional[JsonObject]:
        row = self.connection.execute(
            """
            SELECT * FROM custom_component_artifacts
            WHERE account_id = ? AND artifact_id = ?
            """,
            (account_id, artifact_id),
        ).fetchone()
        return custom_component_artifact_from_row(row) if row is not None else None

    def require_custom_component_artifact(
        self, account_id: str, artifact_id: str
    ) -> JsonObject:
        artifact = self.get_custom_component_artifact_for_account(
            account_id, artifact_id
        )
        if artifact is None:
            raise NotFoundError("custom_component_artifact", artifact_id)
        return artifact

    def list_custom_component_artifacts(
        self, account_id: str, slug: Optional[str] = None
    ) -> List[JsonObject]:
        if slug is None:
            rows = self.connection.execute(
                """
                SELECT * FROM custom_component_artifacts
                WHERE account_id = ?
                ORDER BY created_at DESC, artifact_id DESC
                """,
                (account_id,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM custom_component_artifacts
                WHERE account_id = ? AND slug = ?
                ORDER BY created_at DESC, artifact_id DESC
                """,
                (account_id, slug),
            ).fetchall()
        return [custom_component_artifact_from_row(row) for row in rows]

    def list_custom_components(self, account_id: str) -> List[JsonObject]:
        rows = self.connection.execute(
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
                FROM custom_component_artifacts AS newest
                WHERE newest.account_id = component.account_id
                  AND newest.slug = component.slug
                ORDER BY newest.created_at DESC, newest.artifact_id DESC
                LIMIT 1
              ) AS latest_artifact_id
            FROM custom_components AS component
            LEFT JOIN custom_component_artifacts AS artifact
              ON artifact.account_id = component.account_id
             AND artifact.slug = component.slug
            WHERE component.account_id = ?
            GROUP BY component.account_id, component.slug
            ORDER BY component.slug ASC
            """,
            (account_id,),
        ).fetchall()
        return [
            {
                "account_id": row["account_id"],
                "slug": row["slug"],
                "source_version": row["source_version"],
                "current_source_revision_id": row["current_source_revision_id"],
                "artifact_count": row["artifact_count"],
                # Convenience for listing only. Documents may never store
                # "latest"; attach operations use a concrete artifact id.
                "latest_artifact_id": row["latest_artifact_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def get_custom_component(
        self, account_id: str, slug: str
    ) -> Optional[JsonObject]:
        row = self.connection.execute(
            """
            SELECT * FROM custom_components
            WHERE account_id = ? AND slug = ?
            """,
            (account_id, slug),
        ).fetchone()
        if row is None:
            return None
        artifacts = self.list_custom_component_artifacts(account_id, slug)
        return {
            "account_id": row["account_id"],
            "slug": row["slug"],
            "source_version": row["source_version"],
            "current_source_revision_id": row["current_source_revision_id"],
            "artifacts": artifacts,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def require_custom_component(self, account_id: str, slug: str) -> JsonObject:
        component = self.get_custom_component(account_id, slug)
        if component is None:
            raise NotFoundError("custom_component", slug)
        return component

    def create_custom_component_source_revision(
        self,
        source: JsonObject,
        *,
        expected_version: int,
    ) -> JsonObject:
        """Atomically append an immutable source revision with CAS versioning."""

        account_id = str(source["account_id"])
        slug = str(source["slug"])
        revision_id = str(source["revision_id"])
        entry_path = str(source["entry_path"])
        snapshot = canonical_custom_component_blob(
            "source snapshot", source["snapshot"]
        )
        files_manifest = source.get("files_manifest")
        provenance = source.get("provenance", {})
        self.require_web_account(account_id)
        if not custom_component_slug_is_valid(slug):
            raise ValueError(
                "custom component slug must be 1–64 lowercase kebab-case characters"
            )
        if (
            not revision_id.startswith("ccsrc_")
            or len(revision_id) != len("ccsrc_") + 64
            or any(
                ch not in "0123456789abcdef"
                for ch in revision_id[len("ccsrc_") :]
            )
        ):
            raise ValueError("revision_id must be ccsrc_<lowercase sha256>")
        if (
            not isinstance(expected_version, int)
            or isinstance(expected_version, bool)
            or expected_version < 0
        ):
            raise ValueError("expected_version must be a non-negative integer")
        if not isinstance(files_manifest, dict) or not isinstance(provenance, dict):
            raise ValueError("files_manifest and provenance must be objects")

        now = utc_now()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                """
                SELECT source_version
                FROM custom_components
                WHERE account_id = ? AND slug = ?
                """,
                (account_id, slug),
            ).fetchone()
            current_version = int(row["source_version"]) if row else 0
            if current_version != expected_version:
                raise CustomComponentSourceVersionConflict(
                    slug, expected_version, current_version
                )
            if row is None:
                self.connection.execute(
                    """
                    INSERT INTO custom_components (
                      account_id, slug, source_version,
                      current_source_revision_id, created_at, updated_at
                    )
                    VALUES (?, ?, 0, NULL, ?, ?)
                    """,
                    (account_id, slug, now, now),
                )
            next_version = current_version + 1
            self.connection.execute(
                """
                INSERT INTO custom_component_source_revisions (
                  revision_id, account_id, slug, source_version, entry_path,
                  snapshot_digest_algorithm, snapshot_digest_value,
                  snapshot_opaque_ref, snapshot_byte_length,
                  files_manifest_json, provenance_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    account_id,
                    slug,
                    next_version,
                    entry_path,
                    snapshot["algorithm"],
                    snapshot["value"],
                    snapshot["opaque_ref"],
                    snapshot["byte_length"],
                    encode(files_manifest),
                    encode(provenance),
                    now,
                ),
            )
            cursor = self.connection.execute(
                """
                UPDATE custom_components
                SET source_version = ?, current_source_revision_id = ?,
                    updated_at = ?
                WHERE account_id = ? AND slug = ? AND source_version = ?
                """,
                (
                    next_version,
                    revision_id,
                    now,
                    account_id,
                    slug,
                    current_version,
                ),
            )
            if cursor.rowcount != 1:
                current = self.connection.execute(
                    """
                    SELECT source_version FROM custom_components
                    WHERE account_id = ? AND slug = ?
                    """,
                    (account_id, slug),
                ).fetchone()
                raise CustomComponentSourceVersionConflict(
                    slug,
                    expected_version,
                    int(current["source_version"]) if current else 0,
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.require_custom_component_source_revision(
            account_id, revision_id
        )

    def get_custom_component_source_revision(
        self, account_id: str, revision_id: str
    ) -> Optional[JsonObject]:
        row = self.connection.execute(
            """
            SELECT * FROM custom_component_source_revisions
            WHERE account_id = ? AND revision_id = ?
            """,
            (account_id, revision_id),
        ).fetchone()
        return (
            custom_component_source_revision_from_row(row)
            if row is not None
            else None
        )

    def require_custom_component_source_revision(
        self, account_id: str, revision_id: str
    ) -> JsonObject:
        revision = self.get_custom_component_source_revision(
            account_id, revision_id
        )
        if revision is None:
            raise NotFoundError("custom_component_source_revision", revision_id)
        return revision

    def get_current_custom_component_source(
        self, account_id: str, slug: str
    ) -> Optional[JsonObject]:
        row = self.connection.execute(
            """
            SELECT revision.*
            FROM custom_components AS component
            JOIN custom_component_source_revisions AS revision
              ON revision.revision_id = component.current_source_revision_id
            WHERE component.account_id = ? AND component.slug = ?
            """,
            (account_id, slug),
        ).fetchone()
        return (
            custom_component_source_revision_from_row(row)
            if row is not None
            else None
        )

    def list_custom_component_source_revisions(
        self, account_id: str, slug: str
    ) -> List[JsonObject]:
        rows = self.connection.execute(
            """
            SELECT * FROM custom_component_source_revisions
            WHERE account_id = ? AND slug = ?
            ORDER BY source_version DESC
            """,
            (account_id, slug),
        ).fetchall()
        return [custom_component_source_revision_from_row(row) for row in rows]

    def record_custom_component_compilation(
        self, compilation: JsonObject
    ) -> JsonObject:
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
            or any(
                ch not in "0123456789abcdef"
                for ch in compilation_id[len("cccmp_") :]
            )
        ):
            raise ValueError("compilation_id must be cccmp_<32 lowercase hex>")
        if status not in {"succeeded", "failed", "transient_error"}:
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
        revision = self.require_custom_component_source_revision(
            account_id, revision_id
        )
        if (
            revision["slug"] != slug
            or revision["source_version"] != source_version
        ):
            raise ValueError("compile source revision identity does not match")
        if status == "succeeded":
            if not isinstance(artifact_id, str):
                raise ValueError("successful compile requires an artifact id")
            artifact = self.require_custom_component_artifact(
                account_id, artifact_id
            )
            if artifact["slug"] != slug:
                raise ValueError("compile artifact slug does not match")
        elif artifact_id is not None:
            raise ValueError("failed compile cannot reference an artifact")

        self.connection.execute(
            """
            INSERT INTO custom_component_compilations (
              compilation_id, account_id, slug, source_revision_id,
              source_version, status, compiler_protocol_version,
              compiler_version, diagnostics_json, artifact_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                compilation_id,
                account_id,
                slug,
                revision_id,
                source_version,
                status,
                protocol_version,
                compiler_version,
                encode(diagnostics),
                artifact_id,
                utc_now(),
            ),
        )
        self.connection.commit()
        return self.require_custom_component_compilation(
            account_id, compilation_id
        )

    def require_custom_component_compilation(
        self, account_id: str, compilation_id: str
    ) -> JsonObject:
        row = self.connection.execute(
            """
            SELECT * FROM custom_component_compilations
            WHERE account_id = ? AND compilation_id = ?
            """,
            (account_id, compilation_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("custom_component_compilation", compilation_id)
        return custom_component_compilation_from_row(row)

    def list_custom_component_compilations(
        self, account_id: str, slug: str
    ) -> List[JsonObject]:
        rows = self.connection.execute(
            """
            SELECT * FROM custom_component_compilations
            WHERE account_id = ? AND slug = ?
            ORDER BY created_at DESC, compilation_id DESC
            """,
            (account_id, slug),
        ).fetchall()
        return [custom_component_compilation_from_row(row) for row in rows]

    def list_custom_component_usages(
        self, account_id: str, slug: str
    ) -> List[JsonObject]:
        """Return exact document/node pins for one account-local component.

        The SQL account predicate is the tenancy boundary. The JSON walk then
        performs an exact kind/slug match (rather than trusting a broad LIKE)
        and returns only location/version metadata, never another document's
        source or page content.
        """

        rows = self.connection.execute(
            """
            SELECT id, title, current_version, current_scene_json
            FROM documents
            WHERE doc_kind = 'web' AND account_id = ?
            ORDER BY updated_at DESC, id ASC
            """,
            (account_id,),
        ).fetchall()
        usages: List[JsonObject] = []
        for row in rows:
            web_doc = decode(row["current_scene_json"])
            for (page_id, node_id), node in sorted(
                custom_component_nodes(web_doc).items()
            ):
                if node.get("slug") != slug:
                    continue
                usages.append(
                    {
                        "document_id": row["id"],
                        "document_title": row["title"],
                        "document_version": row["current_version"],
                        "page_id": page_id,
                        "node_id": node_id,
                        "artifact_id": node.get("artifact_id"),
                    }
                )
        return usages

    def validate_custom_component_reference_changes(
        self,
        *,
        before_web_doc: JsonObject,
        after_web_doc: JsonObject,
        account_id: Optional[str],
    ) -> None:
        """Resolve every newly introduced/re-pinned artifact.

        Existing missing pins remain loadable and render as placeholders; an
        unrelated edit does not become impossible because old registry data is
        unavailable. A new node, duplicate, or changed slug/artifact pair must
        resolve in the document's exact account.
        """

        before_nodes = custom_component_nodes(before_web_doc)
        after_nodes = custom_component_nodes(after_web_doc)
        before = custom_component_references(before_web_doc)
        after = custom_component_references(after_web_doc)
        resolved: Dict[Tuple[str, str], JsonObject] = {}

        def resolve(
            location: Tuple[str, str],
            node_id: str,
            slug: str,
            artifact_id: str,
        ) -> JsonObject:
            cached = resolved.get(location)
            if cached is not None:
                return cached
            if account_id is None:
                raise CustomComponentReferenceError(
                    "custom_component.account_required",
                    "the website must belong to an account before attaching a custom component",
                    node_id=node_id,
                    artifact_id=artifact_id,
                )
            if self.get_web_account(account_id) is None:
                raise CustomComponentReferenceError(
                    "custom_component.account_unresolved",
                    f"website account {account_id!r} was not found",
                    node_id=node_id,
                    artifact_id=artifact_id,
                )
            artifact = self.get_custom_component_artifact(artifact_id)
            if artifact is None:
                raise CustomComponentReferenceError(
                    "custom_component.artifact_unresolved",
                    f"custom component artifact {artifact_id!r} was not found",
                    node_id=node_id,
                    artifact_id=artifact_id,
                )
            if artifact["account_id"] != account_id:
                raise CustomComponentReferenceError(
                    "custom_component.artifact_forbidden",
                    "custom component artifact belongs to a different account",
                    node_id=node_id,
                    artifact_id=artifact_id,
                )
            if artifact["slug"] != slug:
                raise CustomComponentReferenceError(
                    "custom_component.artifact_slug_mismatch",
                    (
                        f"artifact {artifact_id!r} belongs to slug "
                        f"{artifact['slug']!r}, not {slug!r}"
                    ),
                    node_id=node_id,
                    artifact_id=artifact_id,
                )
            resolved[location] = artifact
            return artifact

        for location, (node_id, slug, artifact_id) in after.items():
            previous = before.get(location)
            if previous == (node_id, slug, artifact_id):
                continue
            resolve(location, node_id, slug, artifact_id)

        # SetNodeProps carries the whole custom-component value. Validate every
        # changed prop map against the exact pinned artifact's generated schema;
        # unchanged legacy/missing nodes remain movable and resizable.
        for location, node in after_nodes.items():
            previous = before_nodes.get(location)
            if (
                previous is not None
                and previous.get("slug") == node.get("slug")
                and previous.get("artifact_id") == node.get("artifact_id")
                and previous.get("props") == node.get("props")
            ):
                continue
            node_id = str(node.get("id") or location[1])
            slug = str(node.get("slug") or "")
            artifact_id = str(node.get("artifact_id") or "")
            artifact = resolve(location, node_id, slug, artifact_id)
            issue = custom_component_props_schema_issue(
                node.get("props"), artifact.get("manifest")
            )
            if issue is not None:
                raise CustomComponentReferenceError(
                    "custom_component.props_invalid",
                    f"custom component props do not match the pinned artifact: {issue}",
                    node_id=node_id,
                    artifact_id=artifact_id,
                )

    # --- Website-mode personalization accounts (P5 D3) -------------------- #

    def create_web_account(
        self,
        account_id: str,
        name: str,
        domain: Optional[str],
        logo_asset_id: Optional[str],
        data: JsonObject,
        notes: Optional[str],
    ) -> JsonObject:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO web_accounts (
              account_id, name, domain, logo_asset_id, data_json, notes,
              created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                name,
                domain,
                logo_asset_id,
                encode(data or {}),
                notes,
                now,
                now,
            ),
        )
        self.connection.commit()
        return self.require_web_account(account_id)

    def get_web_account(self, account_id: str) -> Optional[JsonObject]:
        row = self.connection.execute(
            "SELECT * FROM web_accounts WHERE account_id = ?", (account_id,)
        ).fetchone()
        return web_account_from_row(row) if row is not None else None

    def require_web_account(self, account_id: str) -> JsonObject:
        account = self.get_web_account(account_id)
        if account is None:
            raise NotFoundError("web_account", account_id)
        return account

    def list_web_accounts(self) -> List[JsonObject]:
        rows = self.connection.execute(
            "SELECT * FROM web_accounts ORDER BY name COLLATE NOCASE ASC, account_id ASC"
        ).fetchall()
        return [web_account_from_row(row) for row in rows]

    def update_web_account(self, account_id: str, patch: JsonObject) -> JsonObject:
        """Partial update: only keys present in `patch` are written (the endpoint
        validates them first). `data` replaces the map wholesale when present."""
        account = self.require_web_account(account_id)
        columns = {
            "name": patch["name"] if "name" in patch else account["name"],
            "domain": patch["domain"] if "domain" in patch else account["domain"],
            "logo_asset_id": patch["logo_asset_id"]
            if "logo_asset_id" in patch
            else account["logo_asset_id"],
            "data_json": encode(patch["data"] if "data" in patch else account["data"]),
            "notes": patch["notes"] if "notes" in patch else account["notes"],
        }
        self.connection.execute(
            """
            UPDATE web_accounts
            SET name = ?, domain = ?, logo_asset_id = ?, data_json = ?,
                notes = ?, updated_at = ?
            WHERE account_id = ?
            """,
            (
                columns["name"],
                columns["domain"],
                columns["logo_asset_id"],
                columns["data_json"],
                columns["notes"],
                utc_now(),
                account_id,
            ),
        )
        self.connection.commit()
        return self.require_web_account(account_id)

    def delete_web_account(self, account_id: str) -> None:
        self.require_web_account(account_id)
        self.connection.execute(
            "DELETE FROM web_accounts WHERE account_id = ?", (account_id,)
        )
        self.connection.commit()

    # --- Website-mode templates (P5 D4) ---------------------------------- #

    def create_web_template(
        self, web_doc: JsonObject, account_id: Optional[str] = None
    ) -> JsonObject:
        """Insert a NEW web documents row as a template: fresh undo/redo stacks,
        version 0, is_template=1. `web_doc` already carries the minted id + title
        (the endpoint clones + relabels it); the theme/brand ref rides in the
        payload and mirrors onto the effective-brand columns, exactly as
        create_document's web path does. An account-scoped custom-component pin
        keeps that account on the template; account-free templates continue to
        behave exactly as before."""
        now = utc_now()
        document_id = web_doc["id"]
        title = web_doc["title"]
        brand_ref = (web_doc.get("theme") or {}).get("brand_kit")
        self.validate_custom_component_reference_changes(
            before_web_doc={},
            after_web_doc=web_doc,
            account_id=account_id,
        )
        self.connection.execute(
            """
            INSERT INTO documents (
              id, title, status, doc_kind, current_scene_json, current_version,
              effective_brand_kit_source, effective_brand_kit_id,
              effective_brand_kit_version, is_template, account_id,
              created_at, updated_at
            )
            VALUES (?, ?, 'draft', 'web', ?, 0, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                document_id,
                title,
                encode(web_doc),
                None,
                brand_ref["id"] if brand_ref else None,
                brand_ref["version"] if brand_ref else None,
                account_id,
                now,
                now,
            ),
        )
        self.connection.commit()
        return self.require_document(document_id)

    def list_web_templates(self) -> List[JsonObject]:
        rows = self.connection.execute(
            """
            SELECT * FROM documents
            WHERE doc_kind = 'web' AND is_template = 1
            ORDER BY updated_at DESC, id ASC
            """
        ).fetchall()
        return [document_from_row(row) for row in rows]

    # --- Website-mode personalization batches (P5 D5) --------------------- #

    def create_web_batch(self, batch: JsonObject) -> JsonObject:
        """Insert a new bulk derive/publish batch. `cursor` persists per chunk
        so an interrupted batch resumes exactly where it stopped; per-account
        results live in manifest_json. counts are computed from the manifest on
        read — nothing to keep in sync here."""
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO web_batches (
              batch_id, template_document_id, template_doc_version, status,
              account_ids_json, publish, slug_base, cursor, manifest_json,
              created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch["batch_id"],
                batch["template_document_id"],
                batch["template_doc_version"],
                batch["status"],
                encode(batch["account_ids"]),
                1 if batch.get("publish", True) else 0,
                batch.get("slug_base"),
                batch.get("cursor", 0),
                encode(batch.get("manifest", [])),
                now,
                now,
            ),
        )
        self.connection.commit()
        return self.require_web_batch(batch["batch_id"])

    def update_web_batch_progress(
        self, batch_id: str, cursor: int, status: str, manifest: List[JsonObject]
    ) -> JsonObject:
        self.connection.execute(
            """
            UPDATE web_batches
            SET cursor = ?, status = ?, manifest_json = ?, updated_at = ?
            WHERE batch_id = ?
            """,
            (cursor, status, encode(manifest), utc_now(), batch_id),
        )
        self.connection.commit()
        return self.require_web_batch(batch_id)

    def require_web_batch(self, batch_id: str) -> JsonObject:
        row = self.connection.execute(
            "SELECT * FROM web_batches WHERE batch_id = ?", (batch_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("web_batch", batch_id)
        return web_batch_from_row(row)


def encode(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def encode_optional(value: Any) -> Optional[str]:
    return None if value is None else encode(value)


def decode(value: str) -> Any:
    return json.loads(value)


def decode_optional(value: Optional[str]) -> Any:
    return None if value is None else decode(value)


def scene_status(scene: JsonObject) -> str:
    status = scene.get("meta", {}).get("status", {})
    if isinstance(status, dict):
        return str(status.get("kind", "draft"))
    return str(status)


def document_from_row(row: sqlite3.Row) -> JsonObject:
    columns = row.keys()
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "doc_kind": row["doc_kind"] if "doc_kind" in columns else "scene",
        "current_version": row["current_version"],
        "scene": decode(row["current_scene_json"]),
        "effective_brand_kit_source": row["effective_brand_kit_source"],
        "effective_brand_kit_id": row["effective_brand_kit_id"],
        "effective_brand_kit_version": row["effective_brand_kit_version"],
        "effective_brand_mode": decode_optional(row["effective_brand_mode_json"]),
        "brand_kit": decode_optional(row["brand_kit_json"]),
        "undo_stack": decode_optional(row["undo_stack_json"])
        if "undo_stack_json" in columns
        else None,
        "redo_stack": decode_optional(row["redo_stack_json"])
        if "redo_stack_json" in columns
        else None,
        "agent_instructions": row["agent_instructions"]
        if "agent_instructions" in columns
        else None,
        "layout_managed_editing": bool(row["layout_managed_editing"])
        if "layout_managed_editing" in columns
        else False,
        # P5 personalization (D4): template/derived provenance. Column-guarded
        # so a row read before the migration ran still decodes.
        "is_template": bool(row["is_template"]) if "is_template" in columns else False,
        "template_document_id": row["template_document_id"]
        if "template_document_id" in columns
        else None,
        "template_doc_version": row["template_doc_version"]
        if "template_doc_version" in columns
        else None,
        "account_id": row["account_id"] if "account_id" in columns else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def web_publish_from_row(row: sqlite3.Row) -> JsonObject:
    record = {
        "slug": row["slug"],
        "document_id": row["document_id"],
        "doc_version": row["doc_version"],
        "html": row["html"],
        "previous_html": row["previous_html"],
        "previous_doc_version": row["previous_doc_version"],
        "runtime_version": row["runtime_version"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    keys = set(row.keys())
    record["publish_id"] = row["publish_id"] if "publish_id" in keys else None
    record["previous_publish_id"] = (
        row["previous_publish_id"] if "previous_publish_id" in keys else None
    )
    return record


def web_publish_revision_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "publish_id": row["publish_id"],
        "slug": row["slug"],
        "document_id": row["document_id"],
        "doc_version": row["doc_version"],
        "html": row["html"],
        "html_digest": row["html_digest"],
        "manifest": decode(row["manifest_json"]),
        "manifest_digest": row["manifest_digest"],
        "package_digest": row["package_digest"],
        "runtime_version": row["runtime_version"],
        "created_at": row["created_at"],
    }


def web_account_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "account_id": row["account_id"],
        "name": row["name"],
        "domain": row["domain"],
        "logo_asset_id": row["logo_asset_id"],
        "data": decode(row["data_json"]),
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def custom_component_nodes(
    web_doc: JsonObject,
) -> Dict[Tuple[str, str], JsonObject]:
    nodes_by_location: Dict[Tuple[str, str], JsonObject] = {}
    pages = web_doc.get("pages")
    if not isinstance(pages, list):
        return nodes_by_location
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_id = page.get("id")
        nodes = page.get("nodes")
        if not isinstance(page_id, str) or not isinstance(nodes, dict):
            continue
        for node_id, node in nodes.items():
            if (
                isinstance(node_id, str)
                and isinstance(node, dict)
                and node.get("kind") == "custom_component"
            ):
                nodes_by_location[(page_id, node_id)] = node
    return nodes_by_location


def custom_component_props_schema_issue(
    props: Any, manifest: Any
) -> Optional[str]:
    if not isinstance(props, dict):
        return "props must be an object"
    # P6.1 fixture/backfill artifacts deliberately predate generated schemas.
    # They remain movable/duplicable; only compiler-v2 artifacts participate in
    # generated-control validation and the executable P6.3 runtime.
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
        return None
    schema = manifest.get("props_schema") if isinstance(manifest, dict) else None
    properties = schema.get("properties") if isinstance(schema, dict) else None
    required = schema.get("required", []) if isinstance(schema, dict) else []
    if (
        not isinstance(schema, dict)
        or schema.get("type") != "object"
        or not isinstance(properties, dict)
        or not isinstance(required, list)
        or any(not isinstance(name, str) for name in required)
    ):
        return "artifact has no usable generated prop schema"
    unknown = sorted(set(props) - set(properties))
    if unknown:
        return f"unknown prop {unknown[0]!r}"
    missing = sorted(name for name in required if name not in props)
    if missing:
        return f"required prop {missing[0]!r} is missing"
    for name, value in sorted(props.items()):
        field = properties.get(name)
        if not isinstance(field, dict):
            return f"prop {name!r} has no field schema"
        expected = field.get("type")
        valid = (
            (expected == "string" and isinstance(value, str))
            or (
                expected == "number"
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            )
            or (expected == "boolean" and isinstance(value, bool))
        )
        if not valid:
            return f"prop {name!r} must be {expected}"
        enum = field.get("enum")
        if enum is not None and (
            not isinstance(enum, list) or value not in enum
        ):
            return f"prop {name!r} is not one of its allowed values"
    return None


def custom_component_references(
    web_doc: JsonObject,
) -> Dict[Tuple[str, str], Tuple[str, str, str]]:
    """Index every pinned custom-component node by page and node id.

    Location is stable across ordinary move/reparent/resize edits, so those
    operations do not re-resolve an unchanged artifact. Duplicate mints a new
    node id and therefore is correctly treated as a new reference.
    """

    references: Dict[Tuple[str, str], Tuple[str, str, str]] = {}
    for (page_id, node_id), node in custom_component_nodes(web_doc).items():
        slug = node.get("slug")
        artifact_id = node.get("artifact_id")
        if isinstance(slug, str) and isinstance(artifact_id, str):
            references[(page_id, node_id)] = (
                node_id,
                slug,
                artifact_id,
            )
    return references


def custom_component_artifact_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "artifact_id": row["artifact_id"],
        "account_id": row["account_id"],
        "slug": row["slug"],
        "source": {
            "algorithm": row["source_digest_algorithm"],
            "value": row["source_digest_value"],
            "opaque_ref": row["source_opaque_ref"],
            "byte_length": row["source_byte_length"],
        },
        "bundle": {
            "algorithm": row["bundle_digest_algorithm"],
            "value": row["bundle_digest_value"],
            "opaque_ref": row["bundle_opaque_ref"],
            "byte_length": row["bundle_byte_length"],
        },
        "css": optional_custom_component_blob_from_row(row, "css"),
        "first_frame": optional_custom_component_blob_from_row(
            row, "first_frame"
        ),
        "manifest": decode(row["manifest_json"]),
        "provenance": decode(row["provenance_json"]),
        "created_at": row["created_at"],
    }


def optional_custom_component_blob_from_row(
    row: sqlite3.Row, prefix: str
) -> Optional[JsonObject]:
    digest = row[f"{prefix}_digest_value"]
    if digest is None:
        return None
    return {
        "algorithm": row[f"{prefix}_digest_algorithm"],
        "value": digest,
        "opaque_ref": row[f"{prefix}_opaque_ref"],
        "byte_length": row[f"{prefix}_byte_length"],
    }


def custom_component_source_revision_from_row(
    row: sqlite3.Row,
) -> JsonObject:
    return {
        "revision_id": row["revision_id"],
        "account_id": row["account_id"],
        "slug": row["slug"],
        "source_version": row["source_version"],
        "entry_path": row["entry_path"],
        "snapshot": {
            "algorithm": row["snapshot_digest_algorithm"],
            "value": row["snapshot_digest_value"],
            "opaque_ref": row["snapshot_opaque_ref"],
            "byte_length": row["snapshot_byte_length"],
        },
        "files_manifest": decode(row["files_manifest_json"]),
        "provenance": decode(row["provenance_json"]),
        "created_at": row["created_at"],
    }


def custom_component_compilation_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "compilation_id": row["compilation_id"],
        "account_id": row["account_id"],
        "slug": row["slug"],
        "source_revision_id": row["source_revision_id"],
        "source_version": row["source_version"],
        "status": row["status"],
        "compiler_protocol_version": row["compiler_protocol_version"],
        "compiler_version": row["compiler_version"],
        "diagnostics": decode(row["diagnostics_json"]),
        "artifact_id": row["artifact_id"],
        "created_at": row["created_at"],
    }


def web_batch_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "batch_id": row["batch_id"],
        "template_document_id": row["template_document_id"],
        "template_doc_version": row["template_doc_version"],
        "status": row["status"],
        "account_ids": decode(row["account_ids_json"]),
        "publish": bool(row["publish"]),
        "slug_base": row["slug_base"],
        "cursor": row["cursor"],
        "manifest": decode(row["manifest_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def brand_kit_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "brand_kit_id": row["brand_kit_id"],
        "version": row["version"],
        "name": row["name"],
        "approval_status": row["approval_status"],
        "product_ready": bool(row["product_ready"]),
        "source": row["source"],
        "brand_kit": decode(row["brand_kit_json"]),
        "brand_summary": decode(row["brand_summary_json"]),
        "diagnostics": decode(row["diagnostics_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def brand_compatibility_report_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "report_id": row["report_id"],
        "from_ref": {
            "id": row["from_brand_kit_id"],
            "version": row["from_version"],
        },
        "to_ref": {
            "id": row["to_brand_kit_id"],
            "version": row["to_version"],
        },
        "report": decode(row["report_json"]),
        "diagnostics": decode(row["diagnostics_json"]),
        "created_at": row["created_at"],
    }


def operation_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "document_id": row["document_id"],
        "sequence": row["sequence"],
        "operation": decode(row["operation_json"]),
        "actor": {"kind": row["actor_kind"], "id": row["actor_id"]},
        "source": row["source"],
        "diagnostics": decode(row["diagnostics_json"]),
        "batch_id": row["batch_id"] if "batch_id" in row.keys() else None,
        "created_at": row["created_at"],
    }


def envelope_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "batch_id": row["batch_id"],
        "document_id": row["document_id"],
        "seq": row["seq"],
        "envelope_version": row["envelope_version"],
        "base_revision": row["base_revision"],
        "actor": {"kind": row["actor_kind"], "id": row["actor_id"]},
        "source": row["source"],
        "intent": row["intent"],
        "checkpoint_label": row["checkpoint_label"],
        "touched_targets": decode(row["touched_targets_json"]),
        "operations": decode(row["operations_json"]),
        "inverse_operations": decode_optional(row["inverse_operations_json"]),
        "lineage": decode_optional(row["lineage_json"]),
        "reverts_batch_id": row["reverts_batch_id"],
        "reapplies_batch_id": row["reapplies_batch_id"],
        "created_at": row["created_at"],
    }


def agent_run_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "run_id": row["run_id"],
        "status": row["status"],
        "document_id": row["document_id"],
        "result": decode_optional(row["result_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def run_event_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "seq": row["seq"],
        "type": row["event_type"],
        "data": decode(row["data_json"]),
        "created_at": row["created_at"],
    }


def new_batch_id() -> str:
    return f"batch_{uuid.uuid4().hex[:12]}"


def snapshot_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "snapshot_id": row["snapshot_id"],
        "document_id": row["document_id"],
        "version": row["version"],
        "scene": decode(row["scene_json"]),
        "reason": row["reason"],
        "created_at": row["created_at"],
    }


def template_revision_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "template_revision_id": row["template_revision_id"],
        "document_id": row["document_id"],
        "source_snapshot_id": row["source_snapshot_id"],
        "version": row["version"],
        "scene": decode(row["scene_json"]),
        "export_profiles": decode(row["export_profiles_json"]),
        "slot_summary": decode(row["slot_summary_json"]),
        "brand_ref": decode_optional(row["brand_ref_json"]),
        "created_at": row["created_at"],
    }


def asset_record_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "asset": decode(row["record_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def binding_set_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "binding_set_id": row["binding_set_id"],
        "template_revision_id": row["template_revision_id"],
        "binding_set": decode(row["binding_json"]),
        "status": row["status"],
        "diagnostics": decode(row["diagnostics_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def instance_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "instance_id": row["instance_id"],
        "template_revision_id": row["template_revision_id"],
        "binding_set_id": row["binding_set_id"],
        "batch_id": row["batch_id"],
        "status": row["status"],
        "fit_status": row["fit_status"],
        "derived_scene": decode(row["derived_scene_json"]),
        "diagnostics": decode(row["diagnostics_json"]),
        "audit": decode(row["audit_json"]),
        "fit_report": decode(row["fit_report_json"]),
        "artifacts": decode(row["artifacts_json"]),
        "generated_assets": decode(row["generated_assets_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def batch_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "batch_id": row["batch_id"],
        "template_revision_id": row["template_revision_id"],
        "status": row["status"],
        "binding_set_ids": decode(row["binding_set_ids_json"]),
        "export_formats": decode(row["export_formats_json"]),
        "export_profile": decode_optional(row["export_profile_json"]),
        "chunk_size": row["chunk_size"],
        "cursor": row["cursor"],
        "counts": decode(row["counts_json"]),
        "manifest": decode(row["manifest_json"]),
        "diagnostics": decode(row["diagnostics_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def repair_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "repair_id": row["repair_id"],
        "template_revision_id": row["template_revision_id"],
        "slot_key": row["slot_key"],
        "node_id": row["node_id"],
        "binding_set_id": row["binding_set_id"],
        "instance_id": row["instance_id"],
        "reason": row["reason"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def asset_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "asset_id": row["asset_id"],
        "document_id": row["document_id"],
        "kind": row["kind"],
        "filename": row["filename"],
        "source_uri": row["source_uri"],
        "mime_type": row["mime_type"],
        "width": row["width"],
        "height": row["height"],
        "dpi": row["dpi"],
        "provenance": decode(row["provenance_json"]),
        "licensing": decode(row["licensing_json"]),
        "created_at": row["created_at"],
    }


def diagnostics_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "document_id": row["document_id"],
        "kind": row["kind"],
        "diagnostics": decode(row["diagnostics_json"]),
        "created_at": row["created_at"],
    }
