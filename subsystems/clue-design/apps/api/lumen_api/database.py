from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


JsonObject = Dict[str, Any]
MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


class NotFoundError(KeyError):
    def __init__(self, resource_type: str, resource_id: str) -> None:
        super().__init__(resource_type, resource_id)
        self.resource_type = resource_type
        self.resource_id = resource_id

    def __str__(self) -> str:
        return f"{self.resource_type} {self.resource_id} was not found"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
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
    ) -> JsonObject:
        now = utc_now()
        document_id = scene["meta"]["id"]
        title = scene["meta"]["title"]
        status = scene_status(scene)
        brand_ref = scene["meta"].get("brand_kit")
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
              id, title, status, current_scene_json, current_version,
              effective_brand_kit_source, effective_brand_kit_id,
              effective_brand_kit_version, effective_brand_mode_json,
              brand_kit_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                title,
                status,
                encode(scene),
                effective_source,
                effective_id,
                effective_version,
                encode_optional(effective_brand_mode),
                encode_optional(brand_kit),
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
        return self.require_document(document_id)

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
                    in {"request", "document", "generated_default", "brand_kit_library"}
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
        now = utc_now()
        media = record.get("media") or {}
        digest = media.get("digest") or {}
        self.connection.execute(
            """
            INSERT INTO assets (
              asset_id, label, kind, status, mime_type, digest_algorithm,
              digest_value, byte_length, filename, tags_json, record_json,
              created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            (
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
            ),
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
