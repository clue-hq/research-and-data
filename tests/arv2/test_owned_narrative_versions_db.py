"""Missing/stale version refusals preserve pages and recover from real input receipts."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_json_dossier import (
    DossierInput,
    FinishDossierTool,
    SaveDossierSectionTool,
    SaveSectionInput,
)
from clue_api.arv2.quality_owned_narrative import (
    ReadNarrativeInput,
    ReadNarrativeInputsTool,
    WriteNarrativeInput,
    WriteResearchNarrativeTool,
)
from clue_api.arv2.quality_page_tools import PublishPageOutput
from clue_api.arv2.research_operations import OperationScope
from clue_core import ExecutionId, OperationId
from tests.arv2.test_dossier_json import finding
from tests.arv2.test_quality_execution_db import execution
from tests.arv2.test_quality_json_dossier_db import invoke
from tests.arv2.test_quality_owned_narrative_db import call, draft
from tests.arv2.test_quality_person_release_db import initial
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


@pytest.mark.parametrize("person", [False, True])
def test_version_refusal_recovery_and_page_preservation(tmp_path, person):
    from clue_api.arv2.display.recipes import load_display_recipes

    async def case():
        async with rollback_conn() as conn:
            parent, child, cid, storage, ctx, gen, path = await initial(conn, tmp_path)
            parent = replace(parent, input_refs={"quality_recipe_version": 24})
            child = replace(child, input_refs={**child.input_refs, "quality_recipe_version": 24})
            await load_display_recipes(conn)
            # Own incomplete import gets the correct remedy, not a version-change claim.
            refused = await call(
                WriteResearchNarrativeTool,
                parent,
                storage,
                ctx,
                WriteNarrativeInput(dossier_version=1, pages=[]),
            )
            assert refused["error_code"] == "narrative_import_incomplete"
            assert "finish_dossier" in refused["recovery"]
            await invoke(FinishDossierTool, parent, storage, ctx, DossierInput())
            job = parent
            if person:
                job = child
                op = OperationScope(job.workspace_id, job.run_id, job.job_id, job.account_id)
                eid = await execution(conn, op, job.project_id)
                await bind_execution(
                    conn,
                    op,
                    execution_id=eid,
                    context_id=cid,
                    role="account_research",
                    limits=Allowance(100, 100, 10),
                )
                ctx = replace(ctx, execution_id=ExecutionId(eid), operation_id=OperationId(uuid4()))
                await invoke(
                    SaveDossierSectionTool,
                    job,
                    storage,
                    ctx,
                    SaveSectionInput(section="Voice", findings=[finding(source_paths=[path])]),
                )
                await invoke(FinishDossierTool, job, storage, ctx, DossierInput())
            meta = await call(ReadNarrativeInputsTool, job, storage, ctx, ReadNarrativeInput())
            good = draft(meta, person).model_dump(mode="json")

            async def blocks():
                return (
                    await conn.execute(
                        text(
                            "SELECT display_block_id, to_jsonb(display_block) FROM display_block "
                            "WHERE workspace_id=:ws ORDER BY display_block_id"
                        ),
                        {"ws": job.workspace_id},
                    )
                ).all()

            async def refuse(raw, code):
                before = await blocks()
                result = await call(
                    WriteResearchNarrativeTool,
                    job,
                    storage,
                    ctx,
                    WriteNarrativeInput.model_validate(raw),
                )
                PublishPageOutput.model_validate_json(json.dumps(result))
                assert result["status"] == "refused", result
                assert result["error_code"] == code, result
                assert not result["block_ids"]
                assert len(json.dumps(result).encode()) < 16384
                assert await blocks() == before
                return result

            if person:
                # Omission and explicit null must report the exact missing argument,
                # even when there are no parent citations at all.
                for missing in ("omit", "null"):
                    raw = json.loads(json.dumps(good))
                    for page in raw["pages"]:
                        for section in page["sections"]:
                            for item in section["items"]:
                                for sentence in item["body"]:
                                    sentence["account_finding_ids"] = []
                    if missing == "omit":
                        raw.pop("account_dossier_version")
                    else:
                        raw["account_dossier_version"] = None
                    result = await refuse(raw, "narrative_account_dossier_version_missing")
                    assert "Copy account_dossier_version" in result["recovery"]
                    assert "Preserve your draft" in result["recovery"]
                    assert "changed" not in result["recovery"]
                stale = {**good, "account_dossier_version": meta["account_dossier_version"] + 1}
                result = await refuse(stale, "narrative_account_dossier_version_stale")
                assert (
                    f"current parent version {meta['account_dossier_version']}"
                    in result["recovery"]
                )
                assert "review the changed parent dossier" in result["recovery"]
            else:
                await refuse(
                    {**good, "account_dossier_version": 1},
                    "narrative_account_dossier_version_unexpected",
                )
                # Account callers are still allowed to omit the parent-only field.
                good.pop("account_dossier_version")
            stale = {**good, "dossier_version": meta["dossier_version"] + 1}
            await refuse(stale, "narrative_dossier_version_stale")

            # A refresh returns the same unchanged versions. Corrected writes succeed
            # without research, new imports, or prose changes, and replay is idempotent.
            refreshed = await call(ReadNarrativeInputsTool, job, storage, ctx, ReadNarrativeInput())
            assert refreshed == meta
            result = await call(
                WriteResearchNarrativeTool,
                job,
                storage,
                ctx,
                WriteNarrativeInput.model_validate(good),
            )
            assert result["status"] == "published", result
            after = await blocks()
            assert after
            assert (
                await call(
                    WriteResearchNarrativeTool,
                    job,
                    storage,
                    ctx,
                    WriteNarrativeInput.model_validate(good),
                )
                == result
            )
            assert await blocks() == after
            # A later stale write cannot overwrite the successfully published content.
            await refuse(stale, "narrative_dossier_version_stale")

    run_async(case())


def test_governed_person_agent_receives_missing_version_feedback_and_recovers(
    tmp_path, monkeypatch
):
    """Exercise C5 receipts, the next model turn, publication and successful finalization."""
    from clue_agents import ScriptedAgentChatModel
    from tests.arv2 import test_quality_owned_narrative_db as native
    from tests.arv2.test_quality_runtime_db import call as model_call

    original_generate = ScriptedAgentChatModel._generate
    original_draft = native.draft
    writes = []
    feedback = []

    def generate(self, messages, *args, **kwargs):
        if self._cursor == 0:
            self.responses = (
                *self.responses[:2],
                model_call("read_narrative_inputs", {}, "refresh"),
                model_call("write_research_narrative", {}, "corrected-write"),
                *self.responses[2:],
            )
        if any("narrative_account_dossier_version_missing" in str(m.content) for m in messages):
            feedback.append(True)
        return original_generate(self, messages, *args, **kwargs)

    def draft_with_one_omission(meta, person=False):
        result = original_draft(meta, person)
        writes.append(result)
        if len(writes) == 1:
            return result.model_copy(update={"account_dossier_version": None})
        assert feedback, "The model must receive actionable feedback before its corrected write"
        return result

    monkeypatch.setattr(ScriptedAgentChatModel, "_generate", generate)
    monkeypatch.setattr(native, "draft", draft_with_one_omission)
    native.test_native_researcher_writes_pages_without_specialist_and_replays(
        tmp_path, monkeypatch, person=True, version=24
    )
    assert len(writes) == 2 and feedback
