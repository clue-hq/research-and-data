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
              brand_kit_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
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
    ) -> JsonObject:
        """Persist a website-mode turn's result: replace the stored WebDoc and
        append an invertible edit envelope through the SAME machinery a scene
        write uses (append_envelope + append_operations + a monotonic
        next_*_sequence), so the web history shares the documents/edit_envelopes
        tables and stays replayable later.

        Deliberately NOT reused from update_document_state (a WebDoc is not a
        scene, so the scene-specific pieces are unsafe or meaningless here):
        - register_scene_assets — a WebDoc's `assets` map is a different shape
          (keyed AssetRecords, no scene node graph); its bytes already live in
          the shared asset store, so there is nothing to promote.
        - undo_stack/redo_stack — those columns model the scene engine's
          batch-id undo stacks; web undo/redo will ride the envelope's
          inverse_operations (stored below), not the scene stacks.
        - effective-brand columns — a web turn does not recompute an effective
          scene brand; the theme ref on the WebDoc is the source of truth.

        The forward op is the marker `[{"kind":"replace_web_doc"}]` (the new doc
        is the row's current_scene_json); the inverse carries the PRIOR doc so a
        future undo is a pure whole-document swap.
        """
        now = utc_now()
        with self.connection:
            document = self.require_document(document_id)
            base_revision = document["current_version"]
            version = base_revision + 1
            batch_id = new_batch_id()
            envelope = {
                "batch_id": batch_id,
                "base_revision": base_revision,
                "intent": intent,
                "checkpoint_label": checkpoint_label,
                "operations": operations,
                "inverse_operations": inverse_operations,
            }
            self.connection.execute(
                """
                UPDATE documents
                SET title = ?, current_scene_json = ?, current_version = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    web_doc["title"],
                    encode(web_doc),
                    version,
                    now,
                    document_id,
                ),
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
