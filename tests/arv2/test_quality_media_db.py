"""Media support survives real writes, correction, evidence projection and cold recovery."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2 import media_store
from clue_api.arv2.account_research_store import create_job
from clue_api.arv2.display.evidence import _evidence_ref
from clue_api.arv2.media_types import Candidate, Quality, Segment
from clue_api.arv2.quality_claims import TranscriptProposal, submit_proposal
from clue_api.arv2.quality_coverage import coverage
from clue_api.arv2.quality_evidence import EvidenceUnavailable, TextSupport, grant_manifest
from clue_api.arv2.quality_media import (
    SpeakerIntroduction,
    TranscriptSupport,
    index_transcripts,
    read_transcript,
)
from clue_api.arv2.research_operations import OperationScope
from clue_core import IdentityBinding, UseClass
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.identity import insert_contact_entity
from clue_storage.fs import FsStorage
from tests.arv2.test_quality_claims_db import assessment, setup
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


@pytest.mark.parametrize("attributed", [True, False])
def test_transcript_speaker_qualification_repair_and_refusal_replay(tmp_path, attributed):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            op, account, context = await setup(conn, storage)
            contact = await insert_contact_entity(
                conn, account_entity_id=account.account_id, full_name="Alex Fixture"
            )
            jid = uuid4()
            await create_job(
                conn,
                job_id=jid,
                run_id=op.run_id,
                workspace_id=op.workspace_id,
                account_entity_id=op.account_id,
                subject_type="person",
                subject_entity_id=contact,
                profile_sha256="a" * 64,
            )
            job = replace(
                account,
                job_id=jid,
                subject_kind="person",
                contact_id=contact,
                person_name="Alex Fixture",
                catalog_version="v4",
            )
            pop = OperationScope(op.workspace_id, op.run_id, jid, op.account_id)
            rt = SimpleNamespace(
                scope=job,
                operation_scope=pop,
                storage=storage,
                settings=SimpleNamespace(arv2_person_media_max_items=8),
            )
            item = await media_store.item_for(
                rt, conn, Candidate(url="https://fixture.test/episode")
            )
            await media_store.bind_item(rt, conn, item["item_id"], "inspect interview")
            intro = "I am Alex Fixture. "
            quote = "We need better intake tools."
            value = intro + quote
            version = await media_store.save_transcript(
                rt,
                conn,
                item_id=item["item_id"],
                value=value,
                segments=[
                    Segment(start=0, end=len(value), speaker="Guest", attribution="model_inferred")
                ],
                quality=Quality(
                    coverage="full" if attributed else "partial",
                    warnings=[] if attributed else ["repeated wording"],
                ),
                method="fixture",
                operation_id=uuid4(),
            )
            (source,) = await index_transcripts(conn, storage, pop)
            grant = await grant_manifest(conn, pop, consumer_id=uuid4())
            view = await read_transcript(conn, FsStorage(tmp_path), grant, version)
            assert view["segments"][0]["attribution"] == "model_inferred"
            proposal = TranscriptProposal(
                operation_key="statement",
                field_key="contact.intake_view",
                value=quote,
                claim_kind="attributed_statement",
                support=(
                    TranscriptSupport(
                        source_id=source.source_id,
                        version_ref=version,
                        start=len(intro),
                        end=len(value),
                        quote=quote,
                        introduction=SpeakerIntroduction(
                            speaker_label="Guest",
                            passage=TextSupport(
                                source_id=source.source_id, start=0, end=len(intro), quote=intro
                            ),
                        )
                        if attributed
                        else None,
                    ),
                ),
                assessment=assessment(),
                identity_binding=IdentityBinding.STRONG,
                use_class=UseClass.PROFESSIONAL_PUBLIC,
            )
            result = await submit_proposal(
                conn, storage, job, grant, proposal, context_id=context, actor_ref="test-specialist"
            )
            assert result.status == ("supported" if attributed else "qualified")
            rows = await claims_for(
                conn,
                contact,
                scope=WorkspaceScope.for_workspace(op.workspace_id),
                include_superseded=True,
            )
            # Qualified rows have an explicit history reader; ordinary facts omit them.
            if not rows:
                from clue_research.claimstore.quality import inspectable_claims_by_ids

                rows = list(
                    (
                        await inspectable_claims_by_ids(
                            conn,
                            [result.claim_id],
                            scope=WorkspaceScope.for_workspace(op.workspace_id),
                        )
                    ).values()
                )
            claim = next(c for c in rows if c.id == result.claim_id)
            ev = _evidence_ref(claim)
            assert ev.media_timestamp is None
            assert bool(ev.quote) == attributed
            assert ev.outreach_safe == attributed
            assert any("Timestamp unavailable" in q for q in ev.qualifications)
            bad = proposal.model_copy(
                update={
                    "operation_key": "bad-version",
                    "support": (proposal.support[0].model_copy(update={"version_ref": uuid4()}),),
                }
            )
            refusal = await submit_proposal(
                conn, storage, job, grant, bad, context_id=context, actor_ref="test-specialist"
            )
            assert refusal.status == "refused"
            assert (
                await submit_proposal(
                    conn, storage, job, grant, bad, context_id=context, actor_ref="test-specialist"
                )
            ).replayed
            with pytest.raises(EvidenceUnavailable, match="valid versions"):
                await read_transcript(conn, storage, grant, uuid4())
            repair = await media_store.save_transcript(
                rt,
                conn,
                item_id=item["item_id"],
                value="Corrected interview.",
                segments=[Segment(start=0, end=20)],
                quality=Quality(coverage="full"),
                method="fixture",
                operation_id=uuid4(),
                supersedes=version,
            )
            state = (
                await conn.execute(
                    text("SELECT conclusion FROM claim_quality_current WHERE claim_id=:id"),
                    {"id": result.claim_id},
                )
            ).scalar_one()
            assert state == "unresolved"
            assert not await claims_for(
                conn, contact, scope=WorkspaceScope.for_workspace(op.workspace_id)
            )
            assert (await read_transcript(conn, storage, grant, version))["current_version"] == str(
                repair
            )
            measured = await coverage(conn, job, context)
            assert measured["missing_pages"] == ["contact"]
            assert any(
                r["status"] == "refused" and r["count"] == 1 for r in measured["proposal_outcomes"]
            )

    run_async(case())


class _LockProbe(FsStorage):
    """At every storage call, asks a second connection whether the account manifest row is held."""

    def __init__(self, root, engine, scope):
        super().__init__(root)
        self._engine, self._scope, self.held = engine, scope, []

    async def _probe(self):
        from sqlalchemy.exc import DBAPIError

        async with self._engine.connect() as other:
            await other.begin()
            try:
                await other.execute(
                    text(
                        "SELECT 1 FROM arv2_evidence_manifest WHERE workspace_id=:ws "
                        "AND run_id=:run AND account_id=:account FOR UPDATE NOWAIT"
                    ),
                    {
                        "ws": self._scope.workspace_id,
                        "run": self._scope.run_id,
                        "account": self._scope.account_id,
                    },
                )
                self.held.append(False)
            except DBAPIError:
                self.held.append(True)
            await other.rollback()

    async def get(self, key):
        await self._probe()
        return await super().get(key)

    async def put(self, key, data, *, media_type):
        await self._probe()
        await super().put(key, data, media_type=media_type)


def test_index_transcripts_never_holds_the_account_lock_across_storage(tmp_path, monkeypatch):
    """Research slowness review 2026-10-04: index_transcripts runs after every media tool call and
    published each transcript as it went, so the account lock taken by the first publish stayed
    held across every later transcript's reads and uploads, blocking the account's other jobs."""
    from functools import partial

    from clue_api.arv2.quality_evidence import persist_source
    from clue_db import db_lifespan
    from clue_research.claimstore import load_core_pack
    from tests.arv2 import test_quality_evidence_db as evidence

    monkeypatch.setattr(
        evidence,
        "seed_icp_fixture",
        partial(evidence.seed_icp_fixture, workspace_id=f"tx-{uuid4()}", user_id=f"u-{uuid4()}"),
    )

    async def case():
        async with db_lifespan() as engine:
            fs = FsStorage(tmp_path)
            async with engine.begin() as conn:
                await load_core_pack(conn)
                op, account, _ = await setup(conn, fs)
                contact = await insert_contact_entity(
                    conn, account_entity_id=account.account_id, full_name="Alex Fixture"
                )
                jid = uuid4()
                await create_job(
                    conn,
                    job_id=jid,
                    run_id=op.run_id,
                    workspace_id=op.workspace_id,
                    account_entity_id=op.account_id,
                    subject_type="person",
                    subject_entity_id=contact,
                    profile_sha256="a" * 64,
                )
                job = replace(
                    account,
                    job_id=jid,
                    subject_kind="person",
                    contact_id=contact,
                    person_name="Alex Fixture",
                    catalog_version="v4",
                )
                pop = OperationScope(op.workspace_id, op.run_id, jid, op.account_id)
                rt = SimpleNamespace(
                    scope=job,
                    operation_scope=pop,
                    storage=fs,
                    settings=SimpleNamespace(arv2_person_media_max_items=8),
                )
                # A committed source, so the account's manifest row exists to be probed.
                await persist_source(
                    conn,
                    fs,
                    pop,
                    kind="web_snapshot",
                    body="An earlier page.",
                    original_key=None,
                    origin_locator="fixture",
                    observed_at=evidence.NOW,
                    source_url="https://fixture.test/page",
                )
                for n in range(3):
                    item = await media_store.item_for(
                        rt, conn, Candidate(url=f"https://fixture.test/episode-{n}")
                    )
                    await media_store.bind_item(rt, conn, item["item_id"], "inspect interview")
                    value = f"Episode {n}: we need better intake tools."
                    await media_store.save_transcript(
                        rt,
                        conn,
                        item_id=item["item_id"],
                        value=value,
                        segments=[Segment(start=0, end=len(value), speaker="Guest")],
                        quality=Quality(coverage="full", warnings=[]),
                        method="fixture",
                        operation_id=uuid4(),
                    )
            probe = _LockProbe(tmp_path, engine, pop)
            async with engine.begin() as conn:
                sources = await index_transcripts(conn, probe, pop)
            assert len(sources) == 3
            assert probe.held and not any(probe.held), probe.held

    run_async(case())
