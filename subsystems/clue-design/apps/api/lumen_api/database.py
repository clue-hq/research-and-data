from __future__ import annotations

import json
import sqlite3
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


class Repository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_document(
        self,
        scene: JsonObject,
        brand_kit: Optional[JsonObject] = None,
        effective_brand_source: Optional[str] = None,
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
              effective_brand_kit_version, brand_kit_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                title,
                status,
                encode(scene),
                effective_source,
                effective_id,
                effective_version,
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
        effective_brand: Optional[Tuple[str, Optional[JsonObject]]],
    ) -> JsonObject:
        operations = list(operations)
        now = utc_now()
        with self.connection:
            document = self.require_document(document_id)
            version = document["current_version"] + len(operations)
            if not operations:
                version = document["current_version"]

            brand_source = document.get("effective_brand_kit_source")
            brand_id = document.get("effective_brand_kit_id")
            brand_version = document.get("effective_brand_kit_version")
            brand_json = document.get("brand_kit")
            if effective_brand is not None:
                brand_source, brand_kit = effective_brand
                brand_id = brand_kit.get("id") if brand_kit else None
                brand_version = brand_kit.get("version") if brand_kit else None
                if brand_source in {"request", "document", "generated_default"} and brand_kit:
                    brand_json = brand_kit

            self.connection.execute(
                """
                UPDATE documents
                SET title = ?, status = ?, current_scene_json = ?,
                    current_version = ?, effective_brand_kit_source = ?,
                    effective_brand_kit_id = ?, effective_brand_kit_version = ?,
                    brand_kit_json = ?, updated_at = ?
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
                    encode_optional(brand_json),
                    now,
                    document_id,
                ),
            )
            self.append_operations(
                document_id,
                operations,
                source,
                actor_kind,
                actor_id,
                diagnostics,
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
                    now,
                )
            )
        self.connection.executemany(
            """
            INSERT INTO operation_log (
              document_id, sequence, operation_json, actor_kind, actor_id,
              source, diagnostics_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        if commit:
            self.connection.commit()

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
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "current_version": row["current_version"],
        "scene": decode(row["current_scene_json"]),
        "effective_brand_kit_source": row["effective_brand_kit_source"],
        "effective_brand_kit_id": row["effective_brand_kit_id"],
        "effective_brand_kit_version": row["effective_brand_kit_version"],
        "brand_kit": decode_optional(row["brand_kit_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def operation_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "document_id": row["document_id"],
        "sequence": row["sequence"],
        "operation": decode(row["operation_json"]),
        "actor": {"kind": row["actor_kind"], "id": row["actor_id"]},
        "source": row["source"],
        "diagnostics": decode(row["diagnostics_json"]),
        "created_at": row["created_at"],
    }


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
