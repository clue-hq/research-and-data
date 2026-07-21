"""PB-B2.3 acceptance — the evidence-snapshot round-trip exit gate.

Store → content-address → retrieve byte-identical → provenance carries the artifact ref →
the evidence span resolves **offline** from the snapshot alone (re-running the pure adapt stage
over the retrieved bytes re-derives a normalized text containing the span). Plus: the sync-capture
/ async-flush seam, cache-hit ref reuse, and the waterfall's flush-before-insert path.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from clue_core import (
    Claim,
    Entity,
    EntityScope,
    EntityType,
    FieldDef,
    Modality,
    NormalizedText,
    PassKind,
    RawArtifact,
    ResearchMode,
    SourceManifest,
    account_claim,
    new_entity_id,
    new_run_id,
    revalidate_with,
)
from clue_core.claim import ExtractionMethod
from clue_research.adapters import (
    CallableClaimExtractor,
    InMemoryArtifactCache,
    PassthroughAdapter,
    run_pipeline,
    span_for,
)
from clue_research.claimstore import ALL_WORKSPACES, claims_for
from clue_research.sources import (
    RegistrySourceManifest,
    bind_resolver,
    register_source,
    resolve_field,
)
from clue_storage import (
    FsStorage,
    SnapshotSink,
    artifact_key,
    bind_snapshots,
    content_address,
    current_snapshot_sink,
    flush_snapshots,
    get_artifact,
    live_claim_count,
)
from tests.storage.conftest import rollback_conn, run_async

_MODE = ResearchMode.ACCOUNT_PROFILING
_PAGE = b"# Acme\nAcme ships reusable rockets on a weekly cadence."
_NEEDLE = "reusable rockets"


def _raw(content: bytes = _PAGE) -> RawArtifact:
    return RawArtifact(ref="https://acme.example", media_type="text/markdown", content=content)


# --- the sink (pure, no DB) ---------------------------------------------------


def test_capture_is_deterministic_and_deduped() -> None:
    sink = SnapshotSink(workspace_id="ws_1")
    key_a = sink.capture(_raw(), source_key="firecrawl_site")
    key_b = sink.capture(_raw(), source_key="firecrawl_site")
    assert key_a == key_b == artifact_key("ws_1", content_address(_PAGE))
    assert len(sink.pending) == 1  # identical bytes buffer once


def test_capture_scopes_by_workspace() -> None:
    assert SnapshotSink(workspace_id="ws_1").capture(_raw()) != SnapshotSink(
        workspace_id="ws_2"
    ).capture(_raw())
    assert SnapshotSink().capture(_raw()).startswith("public/")


# --- flush (DB + fs backend) --------------------------------------------------

pytestmark = pytest.mark.usefixtures("require_storage_db")


def test_flush_is_idempotent_and_fk_ordered(tmp_path: object) -> None:
    async def scenario() -> None:
        storage = FsStorage(str(tmp_path))
        async with rollback_conn() as conn:
            sink = SnapshotSink(workspace_id="ws_flush")
            key = sink.capture(_raw(), source_key="firecrawl_site")
            assert await flush_snapshots(conn, storage, sink) == 1
            # NOT drained: captures stay pending for the sink's (run's) lifetime, so a rolled-back
            # transaction's rows can be re-flushed by the retry (rollback survival, finding 1).
            assert len(sink.pending) == 1
            assert await storage.get(key) == _PAGE  # byte-identical
            record = await get_artifact(conn, key)
            assert record is not None
            assert record.size_bytes == len(_PAGE)
            assert record.source_key == "firecrawl_site"
            assert record.source_url == "https://acme.example"
            # Re-capture + re-flush converge on the same blob + row (content-addressed).
            sink.capture(_raw(), source_key="firecrawl_site")
            assert await flush_snapshots(conn, storage, sink) == 1
            again = await get_artifact(conn, key)
            assert again is not None and again.artifact_id == record.artifact_id

    run_async(scenario())


def test_flush_survives_rollback_and_reconverges(tmp_path: object) -> None:
    """Audit finding 1 (upload half): a transaction that flushed and then rolled back must not
    strand the run — the sink still holds the bytes, so the retry's flush restores the artifact
    row for the same content-addressed key and the claims' FK resolves again."""

    async def scenario() -> None:
        storage = FsStorage(str(tmp_path))
        sink = SnapshotSink(workspace_id="ws_retry")
        key = sink.capture(_raw(), source_key="firecrawl_site")
        async with rollback_conn() as conn:
            await flush_snapshots(conn, storage, sink)
        # The transaction rolled back: the artifact row is gone, the blob is an orphan, but the
        # capture is still pending — the divergence is recoverable, not permanent.
        assert len(sink.pending) == 1
        async with rollback_conn() as conn:
            assert await get_artifact(conn, key) is None  # the rollback took the row
            assert await flush_snapshots(conn, storage, sink) == 1  # the retry re-flushes
            assert await get_artifact(conn, key) is not None
            assert await storage.get(key) == _PAGE

    run_async(scenario())


# --- the pipeline round-trip (the exit gate) ----------------------------------


async def _register_text_source(conn: object, source_key: str, **kwargs: object) -> None:
    await register_source(
        conn,  # type: ignore[arg-type]
        RegistrySourceManifest(
            manifest=SourceManifest(
                source_key=source_key,
                modality=Modality.TEXT,
                entity_scope=EntityScope.ACCOUNT,
                yields=("account",),
                tier=2,
                cost_cents=Decimal(0),
                **kwargs,  # type: ignore[arg-type]
            ),
        ),
    )


def _extractor() -> CallableClaimExtractor:
    def fn(normalized: NormalizedText, entity: Entity, field: FieldDef) -> list:
        from clue_core import ClaimDraft

        return [
            ClaimDraft(
                field_key=field.field_key,
                value="rockets",
                evidence_span=span_for(normalized.text, _NEEDLE),
                confidence=0.9,
                source_url="https://acme.example",
            )
        ]

    return CallableClaimExtractor(fn)


def test_run_pipeline_snapshot_round_trip(tmp_path: object) -> None:
    """The B2 exit gate: a persisted pipeline claim carries an artifact ref whose stored bytes
    are byte-identical and whose evidence span re-derives offline from the snapshot alone."""

    async def scenario() -> None:
        storage = FsStorage(str(tmp_path))
        page_text = _PAGE.decode("utf-8")
        async with rollback_conn() as conn:
            await _register_text_source(conn, "official_site_txt")
            sink = SnapshotSink(workspace_id=None)
            entity = Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)
            field = FieldDef(
                field_key="account.operational_pain", value_type="str", pass_kind=PassKind.DEEP
            )
            claims = await run_pipeline(
                conn,
                "official_site_txt",
                page_text,  # InlineBytesFetcher: the ref IS the page content
                entity,
                field,
                run_id=new_run_id(),
                research_mode=_MODE,
                extractor=_extractor(),
                snapshots=sink,
                storage=storage,
            )
            assert len(claims) == 1
            key = claims[0].artifact_key
            assert key is not None

            # 1. retrieve byte-identical
            stored = await storage.get(key)
            assert stored == page_text.encode("utf-8")
            # 2. provenance resolves to the artifact row
            record = await get_artifact(conn, key)
            assert record is not None and record.content_sha256 == content_address(stored)
            # 3. the evidence span resolves OFFLINE: re-run the pure adapt stage on the snapshot
            readapted = PassthroughAdapter().adapt(
                RawArtifact(ref=key, media_type=record.media_type, content=stored),
                None,  # type: ignore[arg-type]  # PassthroughAdapter ignores the ctx
            )
            assert claims[0].evidence_span is not None
            assert claims[0].evidence_span in readapted.text
            # 4. the persisted row carries the ref (round-trips through the store)
            live = await claims_for(conn, entity.entity_id, field.field_key, scope=ALL_WORKSPACES)
            assert [c.artifact_key for c in live] == [key]
            assert await live_claim_count(conn, key) == 1

    run_async(scenario())


def test_cache_hit_reuses_the_original_artifact_key(tmp_path: object) -> None:
    async def scenario() -> None:
        storage = FsStorage(str(tmp_path))
        async with rollback_conn() as conn:
            await _register_text_source(conn, "cached_site_txt", freshness_profile="daily")
            cache = InMemoryArtifactCache()
            sink = SnapshotSink(workspace_id=None)
            entity = Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)
            field = FieldDef(
                field_key="account.operational_pain", value_type="str", pass_kind=PassKind.DEEP
            )
            page_text = _PAGE.decode("utf-8")

            async def one_run() -> list[Claim]:
                return await run_pipeline(
                    conn,
                    "cached_site_txt",
                    page_text,
                    entity,
                    field,
                    run_id=new_run_id(),
                    research_mode=_MODE,
                    extractor=_extractor(),
                    cache=cache,
                    snapshots=sink,
                    storage=storage,
                )

            first = await one_run()
            second = await one_run()  # cache hit: no re-fetch, same snapshot ref
            assert first[0].artifact_key is not None
            assert second[0].artifact_key == first[0].artifact_key

    run_async(scenario())


# --- the waterfall path (flush-before-insert) ---------------------------------


class _SnapshottingResolver:
    """A resolver double that captures its page into the shared sink (what the tier-2 scrape
    resolver does via ``run_chain``) and returns claims stamped with the snapshot's key.
    Constructed with ``sink=None`` it reads the run-scoped ambient binding at resolve time —
    the production shape (audit finding 5: a per-run sink never lives on a registered object)."""

    tier = 2

    def __init__(self, sink: SnapshotSink | None = None) -> None:
        self._sink = sink

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        sink = self._sink if self._sink is not None else current_snapshot_sink()
        assert sink is not None
        key = sink.capture(_raw(), source_key="snap_site")
        claim = account_claim(
            entity_id=entity.entity_id,
            field_key=field.field_key,
            value_json="rockets",
            source_tier=2,
            extraction_method=ExtractionMethod.SCRAPE,
            confidence=0.9,
            run_id=new_run_id(),
            research_mode=_MODE,
            source_url="https://acme.example",
            evidence_span=_NEEDLE,
        )
        return [revalidate_with(claim, artifact_key=key)]


def test_waterfall_flushes_snapshots_before_insert(tmp_path: object) -> None:
    async def scenario() -> None:
        storage = FsStorage(str(tmp_path))
        async with rollback_conn() as conn:
            await register_source(
                conn,
                RegistrySourceManifest(
                    manifest=SourceManifest(
                        source_key="snap_site",
                        modality=Modality.STRUCTURED,
                        entity_scope=EntityScope.ACCOUNT,
                        yields=("account",),
                        tier=2,
                        cost_cents=Decimal(0),
                    ),
                ),
            )
            sink = SnapshotSink(workspace_id=None)
            bind_resolver("snap_site", _SnapshottingResolver(sink))
            entity = Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)
            field = FieldDef(
                field_key="account.operational_pain",
                value_type="str",
                tier_plan=("snap_site",),
                pass_kind=PassKind.DEEP,
            )
            result = await resolve_field(
                conn,
                entity,
                field,
                mode=_MODE,
                run_id=new_run_id(),
                snapshots=sink,
                storage=storage,
            )
            assert result.claim_refs  # inserted — so the FK resolved, so the flush ran first
            key = artifact_key(None, content_address(_PAGE))
            assert await storage.exists(key)
            assert await get_artifact(conn, key) is not None
            assert await live_claim_count(conn, key) == len(result.claim_refs)

    run_async(scenario())


def test_waterfall_uses_the_run_scoped_ambient_binding(tmp_path: object) -> None:
    """Finding 5: nothing holds the sink — not the resolver (globally registered), not the
    ``resolve_field`` call. The run owner binds it to the call context; the resolver captures
    into it and the waterfall flushes it, both via the ambient binding."""

    async def scenario() -> None:
        storage = FsStorage(str(tmp_path))
        async with rollback_conn() as conn:
            await register_source(
                conn,
                RegistrySourceManifest(
                    manifest=SourceManifest(
                        source_key="snap_site",
                        modality=Modality.STRUCTURED,
                        entity_scope=EntityScope.ACCOUNT,
                        yields=("account",),
                        tier=2,
                        cost_cents=Decimal(0),
                    ),
                ),
            )
            bind_resolver("snap_site", _SnapshottingResolver())  # holds NO sink
            entity = Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)
            field = FieldDef(
                field_key="account.operational_pain",
                value_type="str",
                tier_plan=("snap_site",),
                pass_kind=PassKind.DEEP,
            )
            sink = SnapshotSink(workspace_id=None)
            with bind_snapshots(sink, storage):
                result = await resolve_field(conn, entity, field, mode=_MODE, run_id=new_run_id())
            assert result.claim_refs
            key = artifact_key(None, content_address(_PAGE))
            assert await storage.exists(key)
            assert await get_artifact(conn, key) is not None

    run_async(scenario())
