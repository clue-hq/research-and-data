"""Rebuildable Postgres passage indexes and exact reads of immutable evidence."""

from __future__ import annotations

import json
import math
import re
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import text

from clue_api.arv2 import media_operations as ops
from clue_api.arv2 import media_store as store
from clue_api.arv2 import media_telemetry as telemetry
from clue_api.arv2.media_acquisition import raw_responses
from clue_api.arv2.media_types import EmbeddingContract, content_hash

RECEIPT_BYTES = 12 * 1024
CHUNKER = "unicode-byte-boundary-v1"


def chunks(value: str) -> list[tuple[int, int]]:
    """Deterministic, lossless spans. Conservative byte upper bound prevents token overflow.

    Up to 800 UTF-8 bytes is also <=800 byte-fallback tokens. Prefer a paragraph/sentence/turn
    break near 400 bytes; up to 80 bytes overlap. No tokenizer network assets are required.
    """
    result = []
    start = 0
    while start < len(value):
        end = start
        size = 0
        while end < len(value) and size + len(value[end].encode()) <= 800:
            size += len(value[end].encode())
            end += 1
        if end < len(value):
            boundaries = [m.end() + start for m in re.finditer(r"\n|[.!?]\s+", value[start:end])]
            best = [b for b in boundaries if len(value[start:b].encode()) >= 400]
            if best:
                end = best[0]
            else:
                space = value.rfind(" ", start, end)
                if space > start and len(value[start : space + 1].encode()) >= 400:
                    end = space + 1
        result.append((start, end))
        if end == len(value):
            break
        overlap = end
        while overlap > start and len(value[overlap - 1 : end].encode()) <= 80:
            overlap -= 1
        start = max(start + 1, overlap)
    return result


def vector_string(vector: list[float] | tuple[float, ...], dimensions: int) -> str:
    if len(vector) != dimensions or any(not math.isfinite(v) for v in vector):
        raise ValueError("embedding dimensions or finite-value contract mismatch")
    norm = math.sqrt(sum(v * v for v in vector))
    if norm <= 0:
        raise ValueError("zero vector")
    return "[" + ",".join(str(v / norm) for v in vector) + "]"


async def lexical_index(
    runtime: Any, conn: Any, saved: dict[str, Any], contract: EmbeddingContract
) -> UUID:
    await lock_evidence(runtime, conn, saved)
    index_id = uuid5(saved["version_id"], contract.digest)
    await conn.execute(
        text("""INSERT INTO
        arv2_media_index(workspace_id,index_id,version_id,contract,contract_sha256)
      VALUES(:ws,:id,:version,CAST(:contract AS jsonb),:sha) ON CONFLICT DO NOTHING"""),
        {
            "ws": runtime.scope.workspace_id,
            "id": index_id,
            "version": saved["version_id"],
            "contract": contract.model_dump_json(),
            "sha": contract.digest,
        },
    )
    for ordinal, (start, end) in enumerate(chunks(saved["text"])):
        await conn.execute(
            text("""INSERT INTO
        arv2_media_passage(workspace_id,index_id,ordinal,start_offset,end_offset,body)
          VALUES(:ws,:index,:ordinal,:start,:end,:body) ON CONFLICT DO NOTHING"""),
            {
                "ws": runtime.scope.workspace_id,
                "index": index_id,
                "ordinal": ordinal,
                "start": start,
                "end": end,
                "body": saved["text"][start:end],
            },
        )
    return index_id


async def lock_evidence(runtime: Any, conn: Any, saved: dict[str, Any]) -> None:
    """Serialize derived writes with erasure; a late indexer cannot restore deleted text."""
    row = await conn.execute(
        text("""SELECT storage_key FROM artifact WHERE workspace_id=:ws AND storage_key=:key
            AND erased_at IS NULL AND (expires_at IS NULL OR expires_at>now()) FOR SHARE"""),
        {"ws": runtime.scope.workspace_id, "key": saved["text_key"]},
    )
    if row.scalar_one_or_none() is None:
        raise store.unavailable("transcript became unavailable before indexing")


async def embed_batch(
    runtime: Any,
    item_id: UUID,
    values: list[str],
    *,
    request: dict[str, Any],
    query: bool = False,
    dimensions: int = 768,
) -> tuple[list[list[float]], int] | None:
    async with runtime._conn_factory() as conn:
        op, won = await ops.begin(
            runtime,
            conn,
            item_id=item_id,
            stage="query_embedding" if query else "document_embedding",
            request=request,
        )
    if won:
        try:
            result = await ops.call(
                runtime,
                op,
                "openrouter",
                lambda caller: runtime.clients.media(caller, runtime.ledger_of(caller)).embed_texts(
                    values, query=query, dimensions=dimensions
                ),
            )
        except Exception as exc:
            telemetry.record(
                runtime,
                "embedding_fallback",
                warning=True,
                operation_id=str(op["operation_id"]),
                item_id=str(item_id),
                stage=op["stage"],
                error_code=type(exc).__name__,
            )
            return None  # raw/ledger and unknown state survived; lexical path is independent.
        vectors = [list(c.vector) for c in result.chunks]
        width = result.dimensions
        async with runtime._conn_factory() as conn:
            await ops.finish(runtime, conn, op, result={"dimensions": width})
        return vectors, width
    async with runtime._conn_factory() as conn:
        bodies = await raw_responses(runtime, conn, op)
    for body in reversed(bodies):
        data = body.get("data")
        if isinstance(data, list) and len(data) == len(values):
            try:
                data = sorted(data, key=lambda r: r["index"])
                if [r["index"] for r in data] != list(range(len(values))):
                    continue
                vectors = [[float(v) for v in r["embedding"]] for r in data]
                width = len(vectors[0])
                for vector in vectors:
                    vector_string(vector, width)
                return vectors, width
            except (KeyError, ValueError, TypeError):
                continue
    return None


async def ensure_index(runtime: Any, version_id: UUID) -> dict[str, Any]:
    contract = EmbeddingContract(
        model=runtime.settings.arv2_embedding_model, dimensions=768, chunker=CHUNKER
    )
    async with runtime._conn_factory() as conn:
        saved = await store.load_transcript(runtime, conn, version_id)
        index_id = await lexical_index(runtime, conn, saved, contract)
    spans = chunks(saved["text"])
    complete = 0
    gaps = []
    for start in range(0, len(spans), 32):
        batch = spans[start : start + 32]
        result = await embed_batch(
            runtime,
            saved["item_id"],
            [saved["text"][a:b] for a, b in batch],
            request={
                "transcript_hash": saved["text_sha256"],
                "contract": contract.model_dump(),
                "batch_start": start,
                "spans": batch,
            },
            dimensions=contract.dimensions,
        )
        if result is None:
            gaps.append("embedding_batch_unavailable")
            continue
        vectors, width = result
        if width != contract.dimensions:
            if complete or start:
                gaps.append("embedding_dimension_mismatch")
                continue
            contract = contract.model_copy(update={"dimensions": width})
            async with runtime._conn_factory() as conn:
                index_id = await lexical_index(runtime, conn, saved, contract)
        async with runtime._conn_factory() as conn:
            await store.load_transcript(runtime, conn, version_id)
            await lock_evidence(runtime, conn, saved)
            for ordinal, vector in enumerate(vectors, start):
                await conn.execute(
                    text(
                        "UPDATE arv2_media_passage SET embedding=CAST(:vector AS vector) WHERE "
                        "workspace_id=:ws AND index_id=:index AND ordinal=:ordinal"
                    ),
                    {
                        "ws": runtime.scope.workspace_id,
                        "index": index_id,
                        "ordinal": ordinal,
                        "vector": vector_string(vector, width),
                    },
                )
            complete += len(vectors)
    state = "ready" if complete == len(spans) else "partial" if complete else "lexical"
    async with runtime._conn_factory() as conn:
        await conn.execute(
            text(
                "UPDATE arv2_media_index SET state=:state WHERE workspace_id=:ws AND "
                "index_id=:id AND state<>'unavailable'"
            ),
            {"ws": runtime.scope.workspace_id, "id": index_id, "state": state},
        )
    telemetry.record(
        runtime,
        "index_completed",
        version_ref=str(version_id),
        index_ref=str(index_id),
        state=state,
        passages=len(spans),
        embedded=complete,
        gap_count=len(gaps),
    )
    return {
        "index_ref": str(index_id),
        "state": state,
        "passages": len(spans),
        "embedded": complete,
        "gaps": sorted(set(gaps)),
    }


def passage_ref(index_id: UUID, ordinal: int) -> str:
    return f"{index_id}:{ordinal}"


async def open_passage(
    runtime: Any,
    *,
    version_id: UUID | None = None,
    passage: str | None = None,
    start: int = 0,
    end: int | None = None,
    neighbors: int = 0,
) -> dict[str, Any]:
    async with runtime._conn_factory() as conn:
        if passage:
            raw, ordinal_text = passage.rsplit(":", 1)
            ordinal = int(ordinal_text)
            iid = UUID(raw)
            rows = (
                (
                    await conn.execute(
                        text("""SELECT i.version_id,p.* FROM arv2_media_passage p
              JOIN arv2_media_index i USING(workspace_id,index_id) WHERE p.workspace_id=:ws
        AND p.index_id=:id
              AND ordinal BETWEEN :lo AND :hi ORDER BY ordinal"""),
                        {
                            "ws": runtime.scope.workspace_id,
                            "id": iid,
                            "lo": max(0, ordinal - neighbors),
                            "hi": ordinal + neighbors,
                        },
                    )
                )
                .mappings()
                .all()
            )
            target = next((r for r in rows if r["ordinal"] == ordinal), None)
            if target is None:
                raise store.unavailable()
            version_id = target["version_id"]
            start = rows[0]["start_offset"]
            end = rows[-1]["end_offset"]
        if version_id is None:
            raise store.unavailable("version_ref or passage_ref required")
        saved = await store.load_transcript(runtime, conn, version_id)
        if start < 0 or start >= len(saved["text"]) or end is not None and end <= start:
            raise ValueError("invalid transcript bounds")
        requested_end = min(end if end is not None else len(saved["text"]), len(saved["text"]))
        stop = min(requested_end, start + 2000)

        def result(stop: int) -> dict[str, Any]:
            return {
                "version_ref": str(version_id),
                "item_ref": str(saved["item_id"]),
                "source_url": saved["source_url"],
                "start": start,
                "end": stop,
                "text": saved["text"][start:stop],
                "segments": [
                    s.model_dump(mode="json")
                    for s in saved["segments"]
                    if s.start < stop and s.end > start
                ],
                "quality": saved["quality"],
                "superseded": saved["superseded"],
                "previous_offset": max(0, start - 2000) if start else None,
                "next_offset": stop if stop < len(saved["text"]) else None,
                "requested_end": requested_end,
                "char_count": len(saved["text"]),
            }

        output = result(stop)
        while (
            len(json.dumps(output, ensure_ascii=False).encode()) > RECEIPT_BYTES
            and stop > start + 1
        ):
            stop = start + max(1, (stop - start) // 2)
            output = result(stop)
        await store.attempt(
            runtime,
            conn,
            kind="open",
            outcome="read",
            item_id=saved["item_id"],
            version_id=version_id,
            data={"start": start, "end": stop},
        )
        return output


async def search(
    runtime: Any,
    query: str,
    *,
    item_ids: list[UUID] | None = None,
    offset: int = 0,
    limit: int = 8,
    search_ref: UUID | None = None,
) -> dict[str, Any]:
    async with runtime._conn_factory() as conn:
        await store.authority(runtime, conn)
        rows = (
            (
                await conn.execute(
                    text("""SELECT DISTINCT i.*,t.item_id,t.text_key,t.segments_key
          FROM arv2_media_index i JOIN arv2_media_transcript t USING(workspace_id,version_id)
          JOIN arv2_media_item m USING(workspace_id,item_id)
          JOIN arv2_media_attempt a ON a.workspace_id=m.workspace_id AND a.item_id=m.item_id
          WHERE i.workspace_id=:ws AND a.job_id=:job AND a.kind='binding' AND
        a.outcome<>'released'
            AND m.erased_at IS NULL AND m.expires_at>now() AND t.expires_at>now()
            AND m.current_version=t.version_id AND i.state<>'unavailable'
            AND (:all_items OR m.item_id=ANY(CAST(:items AS uuid[])))"""),
                    {
                        "ws": runtime.scope.workspace_id,
                        "job": runtime.scope.job_id,
                        "all_items": item_ids is None,
                        "items": item_ids or [],
                    },
                )
            )
            .mappings()
            .all()
        )
        # Artifact integrity and scope are checked before either lexical or semantic ranking.
        usable = []
        for row in rows:
            try:
                await store.load_transcript(runtime, conn, row["version_id"])
            except Exception:
                continue
            usable.append(dict(row))
    if not usable:
        return {"results": [], "gaps": ["no_available_transcripts"], "next_offset": None}
    # Prefer a ready/latest embedding contract, one generation per immutable version.
    chosen = {}
    for row in sorted(usable, key=lambda r: (r["state"] == "ready", r["created_at"])):
        chosen[row["version_id"]] = row
    indexes = list(chosen.values())
    ids = [r["index_id"] for r in indexes]
    if search_ref:
        async with runtime._conn_factory() as conn:
            snapshot = await store.get_attempt(runtime, conn, search_ref)
        data = snapshot["data"]
        if (
            snapshot["kind"] != "search"
            or data.get("query_hash") != content_hash(query)
            or set(data.get("index_refs", [])) != {str(i) for i in ids}
        ):
            raise store.unavailable("search scope or generation changed; start a new search")
        return await search_page(runtime, search_ref, data, offset=offset, limit=limit)
    params = {"ws": runtime.scope.workspace_id, "ids": ids, "query": query}
    async with runtime._conn_factory() as conn:
        lexical = (
            (
                await conn.execute(
                    text("""SELECT
        p.*,ts_rank_cd(search,websearch_to_tsquery('english',:query)) +
          CASE WHEN position(lower(:query) in lower(body))>0 THEN 1 ELSE 0 END AS score
          FROM arv2_media_passage p WHERE workspace_id=:ws AND index_id=ANY(CAST(:ids AS
        uuid[]))
            AND (search @@ websearch_to_tsquery('english',:query) OR position(lower(:query)
        in lower(body))>0)
          ORDER BY score DESC,index_id,ordinal LIMIT 20"""),
                    params,
                )
            )
            .mappings()
            .all()
        )
    semantic = []
    gaps = []
    by_contract = {r["contract_sha256"]: r for r in indexes}
    for row in by_contract.values():
        contract = EmbeddingContract.model_validate(row["contract"])
        if not any(
            r["state"] in {"ready", "partial"}
            for r in indexes
            if r["contract_sha256"] == row["contract_sha256"]
        ):
            gaps.append("document_embeddings_unavailable")
            continue
        if contract.model != runtime.settings.arv2_embedding_model:
            gaps.append("embedding_model_changed")
            continue
        result = await embed_batch(
            runtime,
            row["item_id"],
            [query],
            query=True,
            dimensions=contract.dimensions,
            request={
                "query_hash": content_hash(query),
                "job": str(runtime.scope.job_id),
                "contract": contract.model_dump(),
            },
        )
        if result is None or result[1] != contract.dimensions:
            gaps.append("query_embedding_unavailable")
            continue
        async with runtime._conn_factory() as conn:
            sem = (
                (
                    await conn.execute(
                        text("""SELECT p.*,1-(embedding <=> CAST(:vector AS vector)) AS
        score
              FROM arv2_media_passage p WHERE workspace_id=:ws AND index_id=ANY(CAST(:ids AS
        uuid[]))
                AND embedding IS NOT NULL ORDER BY embedding <=> CAST(:vector AS
        vector),index_id,ordinal LIMIT 20"""),
                        {
                            "ws": runtime.scope.workspace_id,
                            "ids": [
                                r["index_id"]
                                for r in indexes
                                if r["contract_sha256"] == row["contract_sha256"]
                            ],
                            "vector": vector_string(result[0][0], contract.dimensions),
                        },
                    )
                )
                .mappings()
                .all()
            )
            semantic.extend(sem)
    ranked: dict[tuple[UUID, int], dict[str, Any]] = {}
    for name, items in [
        ("lexical", lexical),
        ("semantic", sorted(semantic, key=lambda r: -r["score"])[:20]),
    ]:
        for rank, row in enumerate(items, 1):
            key = (row["index_id"], row["ordinal"])
            hit = ranked.setdefault(key, {"row": dict(row), "rrf": 0, "ranks": {}})
            hit["rrf"] += 1 / (60 + rank)
            hit["ranks"][name] = rank
    hits: list[dict[str, Any]] = []
    for hit in sorted(
        ranked.values(), key=lambda h: (-h["rrf"], str(h["row"]["index_id"]), h["row"]["ordinal"])
    ):
        r = hit["row"]
        if any(
            h["row"]["index_id"] == r["index_id"]
            and min(h["row"]["end_offset"], r["end_offset"])
            - max(h["row"]["start_offset"], r["start_offset"])
            > 0.5 * (r["end_offset"] - r["start_offset"])
            for h in hits
        ):
            continue
        hits.append(hit)
    data = {
        "query_hash": content_hash(query),
        "index_refs": [str(i) for i in ids],
        "hits": [
            {
                "passage_ref": passage_ref(h["row"]["index_id"], h["row"]["ordinal"]),
                "rank_components": h["ranks"],
                "rrf": h["rrf"],
            }
            for h in hits
        ],
        "gaps": sorted(set(gaps)),
        "mode": "hybrid" if semantic else "lexical",
    }
    async with runtime._conn_factory() as conn:
        ref = await store.attempt(runtime, conn, kind="search", outcome=data["mode"], data=data)
    return await search_page(runtime, ref, data, offset=offset, limit=limit)


async def search_page(
    runtime: Any, search_ref: UUID, data: dict[str, Any], *, offset: int, limit: int
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "search_ref": str(search_ref),
        "results": [],
        "gaps": data["gaps"],
        "mode": data["mode"],
        "next_offset": None,
    }
    for hit in data["hits"][offset : offset + limit]:
        opened = await open_passage(runtime, passage=hit["passage_ref"])
        opened.update(hit)
        candidate = {**output, "results": [*output["results"], opened]}
        if len(json.dumps(candidate, ensure_ascii=False).encode()) > RECEIPT_BYTES:
            break
        output["results"].append(opened)
    consumed = offset + len(output["results"])
    output["next_offset"] = consumed if consumed < len(data["hits"]) else None
    return output
