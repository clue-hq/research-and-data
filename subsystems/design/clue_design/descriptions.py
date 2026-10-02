"""Asset-description DAL (Part II slice D2.3) — the port of the design API's description domain.

Faithful port of ``lumen_ingestion.describe.DescriptionStore`` onto ``design_asset_description``
(PD contract §5 row 11; O3 preserved this table expressly, with its full behavior), with the
D1/D2 upgrades the contract mandates:

* **Human curation wins, in SQL.** :func:`put_ai` is a CONDITIONAL upsert — its
  ``ON CONFLICT (asset_id, workspace_id) DO UPDATE`` carries
  ``WHERE design_asset_description.origin != 'human'``, so an AI caption can never overwrite a
  human-authored row (and the write is a silent no-op when it tries, exactly as before).
  :func:`put_human` is unconditional: a human always wins, over AI *and* over another human.
* **Fail-closed tenancy.** Every function takes ``workspace_id``; reads and the upsert conflict
  target are both keyed on ``(asset_id, workspace_id)`` (migration ``cf4f80537c8e``), so one
  tenant's description can never be read by, or overwritten from, another workspace.
* **The 1:1 registry FK is real now** (SQLite deliberately omitted it): a description may only
  be written for an asset that exists in the same workspace, and it cascades on asset delete.
* **``origin`` is an enum column** (``design_description_origin``), not free text.

Callers own the transaction (one logical operation = one transaction — the O5 rule); nothing
here commits. The mapper reproduces ``describe._row_to_dict`` exactly.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, iso, load_json_opt
from clue_design.asset_context import (
    OVERRIDE_FIELDS,
    AssetAnalysis,
    AssetOverrides,
    effective_context,
    fingerprint,
    merge_occurrences,
    validate_analysis,
)

_UPSERT_COLUMNS = "asset_id, workspace_id, title, description, usage, tags_json, origin, model"


def _description_from_row(row: Any) -> JsonObject:
    return effective_context(
        {
            "asset_id": row.asset_id,
            "title": row.title,
            "description": row.description,
            "usage": row.usage,
            "tags": load_json_opt(row.tags_json) or [],
            "origin": row.origin,
            "model": row.model,
            "created_at": iso(row.created_at),
            "updated_at": iso(row.updated_at),
            "analysis": load_json_opt(row.analysis_json) or {},
            "overrides": load_json_opt(row.overrides_json) or {},
            "analysis_input": load_json_opt(row.analysis_input_json) or {},
            "analyzed_input": load_json_opt(row.analyzed_input_json) or {},
            "input_fingerprint": row.input_fingerprint,
            "revision": row.revision,
            "status": row.analysis_status,
            "diagnostic": load_json_opt(row.analysis_diagnostic_json),
            "job_id": row.analysis_job_id,
        }
    )


async def get_many(
    conn: AsyncConnection, *, workspace_id: str, asset_ids: list[str]
) -> dict[str, JsonObject]:
    """The cache read: ``asset_id -> description`` for the caller's workspace only.

    One bound array (``= ANY(:ids)``) rather than the ported N placeholders — PG has no host
    parameter ceiling to chunk around.
    """
    if not asset_ids:
        return {}
    rows = await conn.execute(
        text(
            "SELECT * FROM design_asset_description"
            " WHERE workspace_id = :w AND asset_id = ANY(:ids)"
        ),
        {"w": workspace_id, "ids": list(asset_ids)},
    )
    return {row.asset_id: _description_from_row(row) for row in rows}


async def put_ai(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    asset_id: str,
    title: str,
    description: str,
    usage: str,
    tags: list[str],
    model: str,
) -> None:
    """Persist one AI caption — never overwriting a human-authored row (the ported guard)."""
    await conn.execute(
        text(
            f"""
            INSERT INTO design_asset_description ({_UPSERT_COLUMNS})
            VALUES (:a, :w, :title, :description, :usage, CAST(:tags AS jsonb),
                    CAST('ai' AS design_description_origin), :model)
            ON CONFLICT (asset_id, workspace_id) DO UPDATE SET
              title = excluded.title,
              description = excluded.description,
              usage = excluded.usage,
              tags_json = excluded.tags_json,
              origin = CAST('ai' AS design_description_origin),
              model = excluded.model,
              updated_at = now()
            WHERE design_asset_description.origin != 'human'
            """  # noqa: S608 - the column list is a module constant, never caller input
        ),
        {
            "a": asset_id,
            "w": workspace_id,
            "title": title,
            "description": description,
            "usage": usage,
            "tags": dump_json(list(tags)),
            "model": model,
        },
    )


async def merge_human(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    asset_id: str,
    title: str | None,
    description: str | None,
    usage: str | None,
    tags: list[str] | None,
) -> None:
    """Legacy patch with field-level protection; omitted fields retain their suggestions."""
    await patch_overrides(
        conn,
        workspace_id=workspace_id,
        asset_id=asset_id,
        values={
            key: value
            for key, value in {
                "title": title,
                "description": description,
                "usage": usage,
                "tags": tags,
            }.items()
            if value is not None
        },
    )


async def put_human(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    asset_id: str,
    title: str | None,
    description: str | None,
    usage: str | None,
    tags: list[str],
) -> None:
    """Legacy whole-record curation protects exactly the four supplied fields."""
    await patch_overrides(
        conn,
        workspace_id=workspace_id,
        asset_id=asset_id,
        values={"title": title, "description": description, "usage": usage, "tags": tags},
    )


async def _locked(conn: AsyncConnection, workspace_id: str, asset_id: str) -> Any:
    # The registry FK enforces tenancy even on a first write. Creating a placeholder before
    # locking serializes concurrent first edits as well as edits racing an analysis save.
    await conn.execute(
        text("""
        INSERT INTO design_asset_description (workspace_id, asset_id, origin)
        VALUES (:w, :a, 'human') ON CONFLICT (asset_id, workspace_id) DO NOTHING
    """),
        {"w": workspace_id, "a": asset_id},
    )
    return (
        await conn.execute(
            text("""
        SELECT * FROM design_asset_description
        WHERE workspace_id = :w AND asset_id = :a FOR UPDATE
    """),
            {"w": workspace_id, "a": asset_id},
        )
    ).one()


async def patch_overrides(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    asset_id: str,
    values: JsonObject,
    reset_fields: list[str] | None = None,
) -> None:
    validated = AssetOverrides.model_validate(values).model_dump(exclude_unset=True)
    resets = set(reset_fields or [])
    if not resets <= OVERRIDE_FIELDS or resets & validated.keys():
        raise ValueError("reset fields must be known and cannot also be assigned")
    row = await _locked(conn, workspace_id, asset_id)
    overrides = load_json_opt(row.overrides_json) or {}
    overrides = {key: value for key, value in overrides.items() if key not in resets}
    overrides.update(validated)
    generated = load_json_opt(row.analysis_json) or {}
    effective = {**generated, **overrides}
    note_changed = "user_note" in (resets | validated.keys())
    # Untouched legacy values remain readable before a first structured analysis.
    for key, old in (
        ("title", row.title),
        ("description", row.description),
        ("usage", row.usage),
        ("tags", load_json_opt(row.tags_json)),
    ):
        if key not in effective and key not in resets:
            effective[key] = old
    await conn.execute(
        text("""
        UPDATE design_asset_description SET overrides_json = CAST(:overrides AS jsonb),
          title = :title, description = :description, usage = :usage,
          tags_json = CAST(:tags AS jsonb),
          origin = CAST(:origin AS design_description_origin),
          model = CASE WHEN :has_overrides THEN NULL ELSE COALESCE(model, :analysis_model) END,
          analysis_status = CASE WHEN :note_changed THEN 'stale' ELSE analysis_status END,
          analysis_token = CASE WHEN :note_changed THEN NULL ELSE analysis_token END,
          revision = revision + 1, updated_at = now()
        WHERE workspace_id = :w AND asset_id = :a
    """),
        {
            "w": workspace_id,
            "a": asset_id,
            "overrides": dump_json(overrides),
            "title": effective.get("title"),
            "description": effective.get("description"),
            "usage": effective.get("usage"),
            "tags": dump_json(effective.get("tags") or []),
            "origin": "human" if overrides or not generated else "ai",
            "has_overrides": bool(overrides),
            "note_changed": note_changed,
            "analysis_model": (load_json_opt(row.analyzed_input_json) or {}).get("model"),
        },
    )


async def prepare_analysis(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    asset_id: str,
    analysis_input: JsonObject,
    job_id: str | None = None,
) -> JsonObject:
    """Merge placements under the row lock; changed evidence invalidates only AI work."""
    row = await _locked(conn, workspace_id, asset_id)
    previous = load_json_opt(row.analysis_input_json) or {}
    inputs = dict(analysis_input)
    inputs["human_context"] = {
        "user_note": (load_json_opt(row.overrides_json) or {}).get("user_note")
    }
    inputs["source_occurrences"] = merge_occurrences(
        previous.get("source_occurrences", []),
        inputs.get("source_occurrences", []),
    )
    digest = fingerprint(inputs)
    if digest != row.input_fingerprint:
        await conn.execute(
            text("""
            UPDATE design_asset_description SET analysis_input_json = CAST(:inputs AS jsonb),
              input_fingerprint = :digest, analysis_status = 'queued', analysis_token = NULL,
              analysis_job_id = :job, analysis_diagnostic_json = NULL, updated_at = now()
            WHERE workspace_id = :w AND asset_id = :a
        """),
            {
                "w": workspace_id,
                "a": asset_id,
                "inputs": dump_json(inputs),
                "digest": digest,
                "job": job_id,
            },
        )
    return (await get_many(conn, workspace_id=workspace_id, asset_ids=[asset_id]))[asset_id]


async def begin_analysis(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    asset_id: str,
    input_fingerprint: str,
    token: str,
    job_id: str | None = None,
) -> bool:
    result = await conn.execute(
        text("""
        UPDATE design_asset_description SET analysis_status = 'analyzing',
          analysis_token = :token, analysis_job_id = :job, updated_at = now()
        WHERE workspace_id = :w AND asset_id = :a AND input_fingerprint = :digest
          AND analysis_status != 'ready'
          AND (analysis_status != 'analyzing' OR analysis_job_id = :job
               OR updated_at < now() - interval '5 minutes')
        RETURNING asset_id
    """),
        {
            "w": workspace_id,
            "a": asset_id,
            "digest": input_fingerprint,
            "token": token,
            "job": job_id,
        },
    )
    return result.first() is not None


async def finish_analysis(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    asset_id: str,
    token: str,
    analysis: JsonObject | None = None,
    diagnostic: JsonObject | None = None,
    status: str = "ready",
) -> bool:
    if status not in {"ready", "failed", "unsupported"} or (status == "ready" and analysis is None):
        raise ValueError("analysis completion requires a valid terminal result")
    generated = (
        AssetAnalysis.model_validate(analysis).model_dump() if analysis is not None else None
    )
    row = await _locked(conn, workspace_id, asset_id)
    if row.analysis_token != token:
        return False  # Superseded inputs or a takeover cannot be overwritten by a late call.
    inputs = load_json_opt(row.analysis_input_json) or {}
    if generated is not None:
        generated = validate_analysis(generated, inputs.get("source_occurrences", []))
    effective = {
        **(generated or load_json_opt(row.analysis_json) or {}),
        **(load_json_opt(row.overrides_json) or {}),
    }
    await conn.execute(
        text("""
        UPDATE design_asset_description SET
          analysis_json = COALESCE(CAST(:analysis AS jsonb), analysis_json),
          analyzed_input_json = CASE WHEN :has_analysis
            THEN analysis_input_json ELSE analyzed_input_json END,
          analysis_token = NULL,
          analysis_status = :status, analysis_diagnostic_json = CAST(:diagnostic AS jsonb),
          title = :title, description = :description, usage = :usage,
          tags_json = CAST(:tags AS jsonb),
          model = :model, origin = CAST(:origin AS design_description_origin),
          revision = revision + 1, updated_at = now()
        WHERE workspace_id = :w AND asset_id = :a AND analysis_token = :token
    """),
        {
            "w": workspace_id,
            "a": asset_id,
            "token": token,
            "analysis": dump_json(generated) if generated is not None else None,
            "has_analysis": generated is not None,
            "status": status,
            "diagnostic": dump_json(diagnostic) if diagnostic else None,
            "title": effective.get("title", row.title),
            "description": effective.get("description", row.description),
            "usage": effective.get("usage", row.usage),
            "tags": dump_json(effective.get("tags", load_json_opt(row.tags_json)) or []),
            "model": inputs.get("model", "unknown"),
            "origin": "human" if load_json_opt(row.overrides_json) else "ai",
        },
    )
    return True


async def fail_queued_analysis(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    asset_ids: list[str] | None,
    job_id: str,
    reason: str,
) -> None:
    await conn.execute(
        text("""
        UPDATE design_asset_description SET analysis_status = 'failed', analysis_token = NULL,
          analysis_diagnostic_json = CAST(:diagnostic AS jsonb), updated_at = now()
        WHERE workspace_id = :w AND (:all_assets OR asset_id = ANY(:ids))
          AND analysis_job_id = :job AND analysis_status IN ('queued', 'analyzing')
    """),
        {
            "w": workspace_id,
            "ids": asset_ids or [],
            "all_assets": asset_ids is None,
            "job": job_id,
            "diagnostic": dump_json(
                {"code": "analysis_unavailable", "message": reason, "retryable": True}
            ),
        },
    )
