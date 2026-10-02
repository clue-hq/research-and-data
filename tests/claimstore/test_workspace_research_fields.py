"""Human research instructions persist in the workspace registry, never the global vocabulary."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clue_api.arv2.account_research_store import read_account_catalog, read_person_catalog
from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter
from clue_core import EntityType, ExtractionMethod, FieldDef, PassKind, ResearchMode, new_run_id
from clue_research.claimstore import (
    ResearchFieldInputError,
    ResearchFieldKeyTaken,
    WorkspaceDynamicClientKbErasedError,
    WorkspaceFieldDefinitionError,
    WorkspaceFieldRetiredError,
    get_field,
    register_field,
    register_workspace_research_field,
    retire_workspace_field,
    update_workspace_research_field,
)
from clue_research.identity import insert_account_entity
from tests._workspace import seed_workspace

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def create(
    conn, ws, *, entity="accounts", label="Uses Salesforce", description="Find CRM evidence."
):
    return await register_workspace_research_field(
        conn,
        workspace_id=ws,
        entity=entity,
        label=label,
        description=description,
        created_by="human:test-owner",
    )


def test_workspace_menus_editing_and_database_shape_guard():
    async def scenario():
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, "research-field-one")
            other = await seed_workspace(conn, "research-field-two")
            field = await create(conn, ws)
            key = field.field_def.field_key
            assert key == "account.uses_salesforce"
            assert field.label == "Uses Salesforce" and field.pack is None
            assert field.created_at and field.promoted_from_proposal_id is None
            assert await get_field(conn, key) is None
            await create(conn, other, description="A different workspace instruction.")
            await create(
                conn, ws, entity="contacts", label="Public talk", description="Find their talk."
            )
            assert (await read_account_catalog(conn, workspace_id=ws)).spec(
                key
            ).description == "Find CRM evidence."
            assert (
                (await read_account_catalog(conn, workspace_id=other))
                .spec(key)
                .description.startswith("A different")
            )
            person_keys = (await read_person_catalog(conn, workspace_id=ws)).keys()
            assert key not in person_keys
            assert "contact.public_talk" in person_keys
            changed = await update_workspace_research_field(
                conn, workspace_id=ws, field_key=key, label="Salesforce CRM"
            )
            assert changed.definition_version == 2 and changed.description == field.description
            unchanged = await update_workspace_research_field(conn, workspace_id=ws, field_key=key)
            assert unchanged.definition_version == 2
            with pytest.raises(DBAPIError, match="immutable"):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "UPDATE workspace_field_definition SET "
                            "label='changed', definition_version=definition_version+1, "
                            "value_type='string' "
                            "WHERE workspace_id=:ws AND field_key=:key"
                        ),
                        {"ws": ws, "key": key},
                    )
            with pytest.raises(ResearchFieldKeyTaken):
                await create(conn, ws)
            with pytest.raises(ResearchFieldInputError):
                await create(conn, ws, label="!!!")
            with pytest.raises(ResearchFieldInputError):
                await create(conn, ws, label="Another", description="  ")
            with pytest.raises(ResearchFieldKeyTaken):
                await create(conn, ws, label="Recent funding")
            with pytest.raises(WorkspaceFieldDefinitionError, match="reserved"):
                await register_field(
                    conn, FieldDef(field_key=key, value_type="json", pass_kind=PassKind.DEEP)
                )

    run_async(scenario())


def test_retirement_cannot_be_resurrected_by_the_lenient_writer():
    async def scenario():
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, "research-field-retire")
            field = await create(conn, ws)
            key = field.field_def.field_key
            account = await insert_account_entity(
                conn, canonical_name="Example", workspace_id=ws, primary_domain="example.com"
            )
            draft = ClaimDraft(
                entity_id=account,
                entity_type=EntityType.ACCOUNT,
                field_key=key,
                value_json={"uses": True},
                workspace_id=ws,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                extraction_method=ExtractionMethod.API,
                source_url="https://example.com",
            )
            writer = LenientClaimWriter(lenient=True)
            receipt = await writer.write(conn, draft)
            assert not receipt.registered_field
            await retire_workspace_field(
                conn,
                workspace_id=ws,
                field_key=key,
                retired_by="human:test-owner",
                reason="settings",
            )
            account_keys = (await read_account_catalog(conn, workspace_id=ws)).keys()
            assert key not in account_keys
            with pytest.raises(WorkspaceFieldRetiredError):
                await writer.write(conn, draft)
            with pytest.raises(ResearchFieldKeyTaken):
                await create(conn, ws)
            with pytest.raises(WorkspaceFieldRetiredError):
                await update_workspace_research_field(
                    conn, workspace_id=ws, field_key=key, description="Try to restore it."
                )
            assert await get_field(conn, key) is None
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM claim WHERE id=:id"), {"id": receipt.claim_id}
                )
            ).scalar_one() == 1

    run_async(scenario())


def test_erasure_removes_research_vocabulary_and_blocks_all_resurrection_paths():
    from clue_research.compliance.workspace_erasure import erase_workspace_dynamic_client_kb

    async def scenario():
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, "research-field-erasure")
            field = await create(conn, ws)
            key = field.field_def.field_key
            account = await insert_account_entity(
                conn, canonical_name="Example", workspace_id=ws, primary_domain="example.com"
            )
            draft = ClaimDraft(
                entity_id=account,
                entity_type=EntityType.ACCOUNT,
                field_key=key,
                value_json="An attributed observation",
                workspace_id=ws,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                extraction_method=ExtractionMethod.API,
                source_url="https://example.com",
            )
            writer = LenientClaimWriter(lenient=True)
            await writer.write(conn, draft)
            await erase_workspace_dynamic_client_kb(conn, workspace_id=ws, erased_by="human:test")
            remaining_keys = (await read_account_catalog(conn, workspace_id=ws)).keys()
            assert key not in remaining_keys
            with pytest.raises(WorkspaceDynamicClientKbErasedError):
                await create(conn, ws)
            with pytest.raises(WorkspaceDynamicClientKbErasedError):
                await update_workspace_research_field(
                    conn, workspace_id=ws, field_key=key, label="New"
                )
            with pytest.raises(WorkspaceDynamicClientKbErasedError):
                await retire_workspace_field(
                    conn, workspace_id=ws, field_key=key, retired_by="human:test", reason="settings"
                )
            with pytest.raises(WorkspaceDynamicClientKbErasedError):
                await writer.write(conn, draft)
            assert await get_field(conn, key) is None

    run_async(scenario())


def test_concurrent_edits_retirement_and_claim_gate_share_transaction_locks():
    """Separate connections prove a committed retirement cannot race an accepted write."""
    import uuid

    from clue_core import ReuseScope
    from clue_db import db_lifespan
    from clue_research.claimstore.registry import check_claim_writable

    async def scenario():
        ws = f"research-race-{uuid.uuid4().hex}"
        async with db_lifespan() as engine:
            async with engine.begin() as setup:
                await seed_workspace(setup, ws)
                field = await create(setup, ws)
            key = field.field_def.field_key
            try:
                async with engine.connect() as first, engine.connect() as second:
                    await update_workspace_research_field(
                        first, workspace_id=ws, field_key=key, label="Renamed CRM"
                    )
                    await second.execute(text("SET LOCAL lock_timeout = '100ms'"))
                    with pytest.raises(DBAPIError, match="lock timeout"):
                        await update_workspace_research_field(
                            second, workspace_id=ws, field_key=key, description="New instruction"
                        )
                    await second.rollback()
                    await first.commit()
                    updated = await update_workspace_research_field(
                        second, workspace_id=ws, field_key=key, description="New instruction"
                    )
                    assert updated.label == "Renamed CRM" and updated.definition_version == 3
                    await second.commit()
                    await check_claim_writable(
                        first,
                        field_key=key,
                        value_json=True,
                        reuse_scope=ReuseScope.TENANT_PRIVATE,
                        workspace_id=ws,
                        product_id=None,
                    )
                    await second.execute(text("SET LOCAL lock_timeout = '100ms'"))
                    with pytest.raises(DBAPIError, match="lock timeout"):
                        await retire_workspace_field(
                            second,
                            workspace_id=ws,
                            field_key=key,
                            retired_by="human:test",
                            reason="settings",
                        )
                    await second.rollback()
                    await first.commit()
                    await retire_workspace_field(
                        second,
                        workspace_id=ws,
                        field_key=key,
                        retired_by="human:test",
                        reason="settings",
                    )
                    await second.commit()
                    with pytest.raises(WorkspaceFieldRetiredError):
                        await check_claim_writable(
                            first,
                            field_key=key,
                            value_json=True,
                            reuse_scope=ReuseScope.TENANT_PRIVATE,
                            workspace_id=ws,
                            product_id=None,
                        )
                    await first.rollback()
            finally:
                # Only this UUID-scoped fixture is removed; no claim was inserted.
                async with engine.begin() as cleanup:
                    for table in (
                        "workspace_field_retirement",
                        "workspace_field_definition",
                        "workspace",
                    ):
                        await cleanup.execute(
                            text(f"DELETE FROM {table} WHERE workspace_id=:ws"), {"ws": ws}
                        )

    run_async(scenario())


def test_global_registration_waits_for_workspace_registration_before_checking_collision():
    import uuid

    from clue_db import db_lifespan

    async def scenario():
        ws = f"research-registration-{uuid.uuid4().hex}"
        label = f"Race {uuid.uuid4().hex}"
        async with (
            db_lifespan() as engine,
            engine.connect() as first,
            engine.connect() as second,
        ):
            await seed_workspace(first, ws)
            field = await create(first, ws, label=label)
            key = field.field_def.field_key
            try:
                await second.execute(text("SET LOCAL lock_timeout = '100ms'"))
                with pytest.raises(DBAPIError, match="lock timeout"):
                    await register_field(
                        second, FieldDef(field_key=key, value_type="json", pass_kind=PassKind.DEEP)
                    )
                await second.rollback()
                await first.commit()
                with pytest.raises(WorkspaceFieldDefinitionError, match="reserved"):
                    await register_field(
                        second, FieldDef(field_key=key, value_type="json", pass_kind=PassKind.DEEP)
                    )
                await second.rollback()
            finally:
                await first.rollback()
                async with engine.begin() as cleanup:
                    await cleanup.execute(
                        text("DELETE FROM workspace_field_definition WHERE workspace_id=:ws"),
                        {"ws": ws},
                    )
                    await cleanup.execute(
                        text("DELETE FROM workspace WHERE workspace_id=:ws"), {"ws": ws}
                    )

    run_async(scenario())


def test_populated_research_fields_refuse_lossy_migration_rollback():
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/3a75cb367c2b_workspace_research_fields_settings.py"
    )
    spec = importlib.util.spec_from_file_location("research_field_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    async def scenario():
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, "research-rollback-guard")
            await create(conn, ws)

            def downgrade(sync_conn):
                with Operations.context(MigrationContext.configure(sync_conn)):
                    migration.downgrade()

            with pytest.raises(DBAPIError, match="Research fields exist"):
                async with conn.begin_nested():
                    await conn.run_sync(downgrade)

    run_async(scenario())


def test_agent_proposal_is_neutral_scoped_and_never_global():
    from clue_research.claimstore.registry import register_agent_research_field

    async def scenario():
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, "quality-proposal")
            other = await seed_workspace(conn, "quality-proposal-other")
            result = await register_agent_research_field(
                conn,
                workspace_id=ws,
                field_key="account.custom_quality_example",
                run_id="run-test",
            )
            assert result.description == (
                "Proposed research field: custom quality example. "
                "Meaning requires review; not evidence."
            )
            assert any(
                f.key == "account.custom_quality_example"
                for f in (await read_account_catalog(conn, workspace_id=ws)).account
            )
            assert not any(
                f.key == "account.custom_quality_example"
                for f in (await read_account_catalog(conn, workspace_id=other)).account
            )
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM field_definition "
                        "WHERE field_key='account.custom_quality_example'"
                    )
                )
            ).scalar_one() == 0
            with pytest.raises(WorkspaceFieldDefinitionError):
                await register_agent_research_field(
                    conn,
                    workspace_id=ws,
                    field_key="client.unrelated",
                    run_id="run-test",
                )

    run_async(scenario())
