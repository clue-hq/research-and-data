"""Evidence recovery and fail-closed reads against both production storage adapters."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.quality_evidence import (
    EvidenceGrant,
    EvidenceUnavailable,
    grant_manifest,
    read_source,
    revoke_grant,
)
from clue_storage import ArtifactIntegrityError, StorageError
from tests.arv2.test_quality_evidence_db import save, seed
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)
from tests.storage.conftest import backend  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_cold_grant_recovery_missing_blob_outage_and_revocation(backend):  # noqa: F811
    async def case():
        async with rollback_conn() as conn:
            scope, other = await seed(conn, backend)
            source = await save(conn, backend, scope, "Complete original " + uuid4().hex)
            foreign = await save(conn, backend, other, "Foreign original " + uuid4().hex)
            grant = await grant_manifest(conn, scope, consumer_id=uuid4())
            # Rebuild from durable IDs only: no local cache, paths or warm grant object.
            cold = EvidenceGrant(scope, grant.consumer_id, grant.grant_id)
            original = await read_source(conn, backend, cold, source.source_id)
            assert original["text"].startswith("Complete original ")
            with pytest.raises(EvidenceUnavailable):
                await read_source(conn, backend, cold, foreign.source_id)
            with pytest.raises(EvidenceUnavailable):
                await read_source(
                    conn,
                    backend,
                    replace(cold, scope=replace(scope, workspace_id="foreign")),
                    source.source_id,
                )

            class Outage:
                def __getattr__(self, key):
                    return getattr(backend, key)

                async def get(self, key):
                    raise StorageError("synthetic object-store outage")

            with pytest.raises(ArtifactIntegrityError):
                await read_source(conn, Outage(), cold, source.source_id)
            assert (await read_source(conn, backend, cold, source.source_id)) == original
            await backend.delete(source.artifact_key)
            with pytest.raises(ArtifactIntegrityError):
                await read_source(conn, backend, cold, source.source_id)
            await backend.put(
                source.artifact_key, original["text"].encode(), media_type="text/plain"
            )
            await revoke_grant(conn, cold)
            with pytest.raises(EvidenceUnavailable):
                await read_source(conn, backend, cold, source.source_id)
            assert (
                not (
                    await conn.execute(
                        text("SELECT input_refs::text FROM arv2_research_job WHERE job_id=:job"),
                        {"job": scope.job_id},
                    )
                )
                .scalar_one()
                .count(original["text"])
            )

    run_async(case())
