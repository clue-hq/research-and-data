"""S3.1 durable production context-scope acceptance.

These are real PostgreSQL receipts attached to real submitted turns.  The test advances both the
product-specific and company-wide Client-KB sequences around a retry, proving that the same turn
cannot drift while a later turn observes the new company version.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_scope_pin import (
    COMPANY_ACCOUNT_WIDE_KNOWLEDGE_SCOPE_V1,
    COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V2,
    COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V3,
    get_agent_turn_scope_pin,
    load_or_create_agent_turn_scope_pin,
)
from clue_api.agent_turn_submission import insert_submission
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.client_context_binding import bind_workspace_client
from clue_api.thread_store import create_thread
from clue_core import EntityId, OnboardingInputKind
from clue_research.stage0 import (
    CLIENT_KNOWLEDGE_FIELDS,
    PRODUCT_KNOWLEDGE_FIELDS,
    ClientInput,
    VolunteeredMaterial,
    reverse_profile,
    submit_onboarding_input,
)
from clue_spine import create_brand, create_product, create_project
from clue_storage import FsStorage
from tests._identity import seed_principal
from tests._workspace import seed_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


async def _capture_submission(
    conn: AsyncConnection,
    *,
    artifacts: DurableAgentArtifactStore,
    workspace_id: str,
    project_id: str,
    brand_id: str,
    product_id: str | None,
    client_entity_id: EntityId,
    label: str,
):
    user_id = f"user-s31-{workspace_id}"
    membership_id = f"membership-s31-{workspace_id}"
    principal = await seed_principal(
        conn,
        workspace_id=workspace_id,
        user_id=user_id,
        membership_id=membership_id,
    )
    thread_id = f"thread-s31-{label}-{uuid4().hex[:8]}"
    await create_thread(
        conn,
        thread_id=thread_id,
        workspace_id=workspace_id,
        project_id=project_id,
        created_by_user_id=principal.user_id,
        created_via_membership_id=principal.membership_id,
    )
    body = f"S3.1 turn {label}".encode()
    message = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=body,
        media_type="text/plain",
    )
    captured = await submit_onboarding_input(
        conn,
        workspace_id=workspace_id,
        brand_id=brand_id,
        product_id=product_id,
        project_id=project_id,
        client_entity_id=client_entity_id,
        kind=OnboardingInputKind.USER_TURN,
        artifact_key=message.artifact_key,
        content_sha256=message.sha256,
        actor="human",
    )
    turn_id = uuid4()
    submission, created = await insert_submission(
        conn,
        turn_id=turn_id,
        workspace_id=workspace_id,
        project_id=project_id,
        thread_id=thread_id,
        submitted_by_user_id=principal.user_id,
        submitted_via_membership_id=principal.membership_id,
        onboarding_input_id=captured.onboarding_input_id,
        message_artifact_key=message.artifact_key,
        message_sha256=message.sha256,
        idempotency_key=f"s31-{label}-{turn_id}",
    )
    assert created is True
    return submission


def test_turn_pin_freezes_independent_company_product_pair_and_preserves_v1_replay(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = f"production-context-s31-{uuid4().hex[:8]}"
            await seed_workspace(conn, workspace_id)
            brand = await create_brand(conn, workspace_id=workspace_id, name="S3.1 Brand")
            product = await create_product(
                conn,
                workspace_id=workspace_id,
                brand_id=brand.brand_id,
                name="S3.1 Product",
            )
            project = await create_project(
                conn,
                workspace_id=workspace_id,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                name="S3.1 Project",
            )
            first_profile = await reverse_profile(
                conn,
                ClientInput(
                    name="S3.1 Company",
                    website=f"https://{workspace_id}.example",
                    materials=(
                        VolunteeredMaterial(
                            kind="onboarding",
                            label="company v1",
                            content="Company-wide facts v1.",
                            asserted_fields={
                                key: f"company v1 {key}" for key in CLIENT_KNOWLEDGE_FIELDS
                            },
                        ),
                    ),
                ),
                workspace_id=workspace_id,
                product_id=None,
                budget_cap_cents=Decimal(0),
                max_source_tier=0,
            )
            # A higher product-specific version must not become the company-wide production pin.
            product_profile = first_profile
            for revision in (1, 2):
                product_profile = await reverse_profile(
                    conn,
                    ClientInput(
                        name="S3.1 Company",
                        website=f"https://{workspace_id}.example",
                        materials=(
                            VolunteeredMaterial(
                                kind="product_context",
                                label=f"product v{revision}",
                                content="Product-only facts.",
                                asserted_fields={
                                    key: (
                                        f"product v{revision} {key}"
                                        if key
                                        in {
                                            "client.product_overview",
                                            "client.product_differentiator",
                                            "client.product_positioning",
                                        }
                                        else {"summary": f"product v{revision} {key}"}
                                    )
                                    for key in PRODUCT_KNOWLEDGE_FIELDS
                                },
                            ),
                        ),
                    ),
                    workspace_id=workspace_id,
                    product_id=product.product_id,
                    knowledge_scope="product",
                    budget_cap_cents=Decimal(0),
                    max_source_tier=0,
                )
            assert product_profile.ref.client_kb_version == 2
            await bind_workspace_client(
                conn,
                workspace_id=workspace_id,
                client_entity_id=first_profile.ref.client_entity_id,
            )
            artifacts = DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / "scope-pin"),
                conn_factory=conn_session_factory(conn),
            )
            first_turn = await _capture_submission(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                project_id=project.project_id,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                client_entity_id=first_profile.ref.client_entity_id,
                label="first",
            )
            pin_v1, created = await load_or_create_agent_turn_scope_pin(
                conn,
                submission=first_turn,
            )
            assert created is True
            assert pin_v1.workspace_id == workspace_id
            assert pin_v1.project_id == project.project_id
            assert pin_v1.product_id == product.product_id
            assert pin_v1.client_entity_id == first_profile.ref.client_entity_id
            assert pin_v1.client_kb_version == first_profile.ref.client_kb_version
            assert pin_v1.product_kb_version == product_profile.ref.client_kb_version
            assert (
                pin_v1.knowledge_scope_policy_version
                == COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V3
            )

            # The row is the retry authority, so neither an ordinary update nor a delete may
            # rewrite history. Exercise the database trigger directly rather than relying on the
            # repository to avoid emitting those statements.
            with pytest.raises(DBAPIError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "UPDATE agent_turn_scope_pin SET client_kb_version=NULL "
                            "WHERE turn_id=:turn"
                        ),
                        {"turn": pin_v1.turn_id},
                    )
            with pytest.raises(DBAPIError):
                async with conn.begin_nested():
                    await conn.execute(
                        text("DELETE FROM agent_turn_scope_pin WHERE turn_id=:turn"),
                        {"turn": pin_v1.turn_id},
                    )

            background = await reverse_profile(
                conn,
                ClientInput(
                    name="S3.1 Company",
                    website=f"https://{workspace_id}.example",
                    materials=(
                        VolunteeredMaterial(
                            kind="background_recon",
                            label="company v2",
                            content="Background recon publishes company v2.",
                            asserted_fields={
                                key: f"company v2 {key}" for key in CLIENT_KNOWLEDGE_FIELDS
                            },
                        ),
                    ),
                ),
                workspace_id=workspace_id,
                product_id=None,
                budget_cap_cents=Decimal(0),
                max_source_tier=0,
            )
            assert background.ref.client_kb_version == first_profile.ref.client_kb_version + 1
            product_background = await reverse_profile(
                conn,
                ClientInput(
                    name="S3.1 Company",
                    website=f"https://{workspace_id}.example",
                    materials=(
                        VolunteeredMaterial(
                            kind="background_product_recon",
                            label="product v3",
                            content="Background recon publishes product v3.",
                            asserted_fields={
                                key: (
                                    f"product v3 {key}"
                                    if key
                                    in {
                                        "client.product_overview",
                                        "client.product_differentiator",
                                        "client.product_positioning",
                                    }
                                    else {"summary": f"product v3 {key}"}
                                )
                                for key in PRODUCT_KNOWLEDGE_FIELDS
                            },
                        ),
                    ),
                ),
                workspace_id=workspace_id,
                product_id=product.product_id,
                knowledge_scope="product",
                budget_cap_cents=Decimal(0),
                max_source_tier=0,
            )
            assert product_background.ref.client_kb_version == 3

            retry_pin, retry_created = await load_or_create_agent_turn_scope_pin(
                conn,
                submission=first_turn,
            )
            assert retry_created is False
            assert retry_pin == pin_v1

            next_turn = await _capture_submission(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                project_id=project.project_id,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                client_entity_id=first_profile.ref.client_entity_id,
                label="next",
            )
            pin_v2, next_created = await load_or_create_agent_turn_scope_pin(
                conn,
                submission=next_turn,
            )
            assert next_created is True
            assert pin_v2.client_kb_version == background.ref.client_kb_version
            assert pin_v2.product_kb_version == product_background.ref.client_kb_version
            assert pin_v2.turn_id != pin_v1.turn_id
            assert (
                pin_v2.knowledge_scope_policy_version
                == COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V3
            )

            # Historical V1 rows stay readable as exactly company-only receipts. They are not
            # upgraded in place or reinterpreted as containing the current product marker.
            legacy_turn = await _capture_submission(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                project_id=project.project_id,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                client_entity_id=first_profile.ref.client_entity_id,
                label="legacy-v1",
            )
            await conn.execute(
                text(
                    "INSERT INTO agent_turn_scope_pin "
                    "(turn_id, workspace_id, project_id, project_name, project_status, brand_id, "
                    "product_id, client_entity_id, client_kb_version, product_kb_version, "
                    "knowledge_scope_policy_version) VALUES "
                    "(:turn, :workspace, :project, :name, :status, :brand, :product, :client, "
                    ":company_version, NULL, :policy)"
                ),
                {
                    "turn": legacy_turn.turn_id,
                    "workspace": workspace_id,
                    "project": project.project_id,
                    "name": project.name,
                    "status": project.status,
                    "brand": brand.brand_id,
                    "product": product.product_id,
                    "client": first_profile.ref.client_entity_id,
                    "company_version": first_profile.ref.client_kb_version,
                    "policy": COMPANY_ACCOUNT_WIDE_KNOWLEDGE_SCOPE_V1,
                },
            )
            legacy_pin = await get_agent_turn_scope_pin(
                conn,
                workspace_id=workspace_id,
                turn_id=legacy_turn.turn_id,
            )
            assert legacy_pin is not None
            assert legacy_pin.product_id == product.product_id
            assert legacy_pin.product_kb_version is None
            assert (
                legacy_pin.knowledge_scope_policy_version == COMPANY_ACCOUNT_WIDE_KNOWLEDGE_SCOPE_V1
            )

            # V2's selected-without-knowledge state remains readable as immutable history. The
            # same shape is forbidden for a newly-authored V3 receipt.
            historical_v2_turn = await _capture_submission(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                project_id=project.project_id,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                client_entity_id=first_profile.ref.client_entity_id,
                label="historical-v2-without-product-kb",
            )
            pin_values = {
                "turn": historical_v2_turn.turn_id,
                "workspace": workspace_id,
                "project": project.project_id,
                "name": project.name,
                "status": project.status,
                "brand": brand.brand_id,
                "product": product.product_id,
                "client": first_profile.ref.client_entity_id,
                "company_version": first_profile.ref.client_kb_version,
            }
            await conn.execute(
                text(
                    "INSERT INTO agent_turn_scope_pin "
                    "(turn_id, workspace_id, project_id, project_name, project_status, brand_id, "
                    "product_id, client_entity_id, client_kb_version, product_kb_version, "
                    "knowledge_scope_policy_version) VALUES "
                    "(:turn, :workspace, :project, :name, :status, :brand, :product, :client, "
                    ":company_version, NULL, 'company-and-selected-product-v2')"
                ),
                pin_values,
            )
            historical_v2_pin = await get_agent_turn_scope_pin(
                conn,
                workspace_id=workspace_id,
                turn_id=historical_v2_turn.turn_id,
            )
            assert historical_v2_pin is not None
            assert historical_v2_pin.product_kb_version is None
            assert (
                historical_v2_pin.knowledge_scope_policy_version
                == COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V2
            )

            invalid_v3_turn = await _capture_submission(
                conn,
                artifacts=artifacts,
                workspace_id=workspace_id,
                project_id=project.project_id,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                client_entity_id=first_profile.ref.client_entity_id,
                label="invalid-v3-without-product-kb",
            )
            with pytest.raises(DBAPIError, match="agent_turn_scope_pin_policy_shape"):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "INSERT INTO agent_turn_scope_pin "
                            "(turn_id, workspace_id, project_id, project_name, project_status, "
                            "brand_id, product_id, client_entity_id, client_kb_version, "
                            "product_kb_version, knowledge_scope_policy_version) VALUES "
                            "(:turn, :workspace, :project, :name, :status, :brand, :product, "
                            ":client, :company_version, NULL, "
                            "'company-and-selected-product-required-v3')"
                        ),
                        {**pin_values, "turn": invalid_v3_turn.turn_id},
                    )

            # Workspace isolation is fail-closed and does not disclose the foreign row.
            assert (
                await get_agent_turn_scope_pin(
                    conn,
                    workspace_id="foreign-workspace",
                    turn_id=pin_v1.turn_id,
                )
                is None
            )

    run_async(scenario())
