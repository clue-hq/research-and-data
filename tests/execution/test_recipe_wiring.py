"""C5.2 production compatibility adapters."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_api import (
    VersionedPinResource,
    build_recipe_pin_registry,
)
from clue_config import DEFAULT_STAGE0_POLICY, Config
from clue_execution import (
    CompatibilityContext,
    CompatibilityLoader,
    CompatibilityManifest,
    PinRequest,
)
from clue_research.claimstore import load_core_pack
from clue_research.icp import load_starter_packs
from clue_research.identity import insert_account_entity
from clue_research.sources import seed_source_manifests
from clue_research.stage0 import ensure_readiness_spec, load_client_knowledge_pack
from clue_storage import record_artifact
from clue_toolbelt import ToolRegistry
from tests._workspace import seed_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn
from tests.toolbelt.conftest import EchoTool


def _tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(EchoTool(), make_default=True)
    return registry


def test_composition_registers_required_adapters_and_resolves_code_resources() -> None:
    async def scenario() -> None:
        registry = build_recipe_pin_registry(
            tool_registry=_tool_registry(),
            config=Config(workspace_id="ws"),
            prompt_resources=(
                VersionedPinResource(key="stage0", version="1", payload={"template": "v1"}),
            ),
            model_policy_resources=(
                VersionedPinResource(
                    key="research",
                    version="1",
                    payload={"model": "provider/model"},
                ),
            ),
        )
        required = {
            "tool",
            "field_definition",
            "source_manifest",
            "icp_spec",
            "source_profile",
            "readiness_policy",
            "stage0_policy",
            "proposal_policy",
            "ingestion_policy",
            "coverage_policy",
            "skill",
            "prompt",
            "model_policy",
            "product_context",
            "artifact_input",
            "memory_switch",
            "memory_bundle_journal",
        }
        assert required <= set(registry.kinds())

        report = await CompatibilityLoader(registry).load(
            CompatibilityManifest(
                execution=(
                    PinRequest(kind="tool", key="echo", version="1"),
                    PinRequest(kind="stage0_policy", key="default", version="1"),
                    PinRequest(kind="skill", key="stage0-interview", version="1"),
                    PinRequest(kind="prompt", key="stage0", version="1"),
                    PinRequest(kind="model_policy", key="research", version="1"),
                )
            ),
            context=CompatibilityContext(workspace_id="ws"),
        )
        assert report.compatible
        assert [pin.kind for pin in report.pins] == sorted(pin.kind for pin in report.pins)

        unavailable = await CompatibilityLoader(registry).load(
            CompatibilityManifest(
                execution=(
                    PinRequest(kind="tool", key="echo", version="99"),
                    PinRequest(kind="prompt", key="stage0", version="99"),
                    PinRequest(kind="skill", key="missing", version="1"),
                )
            ),
            context=CompatibilityContext(workspace_id="ws"),
        )
        assert [(item.kind, item.reason) for item in unavailable.incompatibilities] == [
            ("prompt", "version_mismatch"),
            ("skill", "missing"),
            ("tool", "version_mismatch"),
        ]

    run_async(scenario())


@pytest.mark.usefixtures("require_profiling_db")
def test_database_adapters_enforce_retirement_erasure_and_live_memory_switch() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = await seed_workspace(conn, "ws-c5-pins")
            account_id = await insert_account_entity(
                conn,
                workspace_id=workspace_id,
                canonical_name="C5 Pinned Account",
                primary_domain="c5-pinned.example",
            )
            await load_core_pack(conn)
            await load_starter_packs(conn)
            await load_client_knowledge_pack(conn)
            await seed_source_manifests(conn)
            await ensure_readiness_spec(
                conn,
                workspace_id=workspace_id,
                spec=DEFAULT_STAGE0_POLICY.readiness,
            )
            await record_artifact(
                conn,
                storage_key=f"{workspace_id}/{'a' * 64}",
                workspace_id=workspace_id,
                content_sha256="a" * 64,
                media_type="application/json",
                size_bytes=2,
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO memory_switch (workspace_id, enabled, updated_by)
                    VALUES (:workspace_id, false, 'human')
                    """
                ),
                {"workspace_id": workspace_id},
            )
            registry = build_recipe_pin_registry(
                tool_registry=_tool_registry(),
                conn_factory=conn_session_factory(conn),
            )
            loader = CompatibilityLoader(registry)
            context = CompatibilityContext(workspace_id=workspace_id)

            exact = await loader.load(
                CompatibilityManifest(
                    execution=(
                        PinRequest(
                            kind="field_definition",
                            key="core.employee_count",
                            version="1",
                        ),
                        PinRequest(kind="source_manifest", key="clay", version="1"),
                        PinRequest(
                            kind="artifact_input",
                            key=f"{workspace_id}/{'a' * 64}",
                            digest="a" * 64,
                        ),
                        PinRequest(
                            kind="memory_switch",
                            key="workspace",
                            version="live",
                            required=False,
                        ),
                        PinRequest(kind="readiness_policy", key="default", version="1"),
                        PinRequest(kind="source_profile", key="frontier_ai", version="1"),
                        PinRequest(kind="account", key=str(account_id), version="1"),
                    )
                ),
                context=context,
            )
            assert exact.compatible
            assert {pin.kind: pin.status for pin in exact.pins}["memory_switch"] == "disabled"

            await conn.execute(
                text(
                    """
                    UPDATE field_definition SET active = false
                    WHERE field_key = 'core.employee_count'
                    """
                )
            )
            await conn.execute(
                text("UPDATE source_manifest SET active = false WHERE source_key = 'clay'")
            )
            retired = await loader.load(
                CompatibilityManifest(
                    execution=(
                        PinRequest(
                            kind="field_definition",
                            key="core.employee_count",
                            version="1",
                        ),
                        PinRequest(kind="source_manifest", key="clay", version="1"),
                        PinRequest(
                            kind="memory_switch",
                            key="workspace",
                            version="live",
                        ),
                    )
                ),
                context=context,
            )
            assert [(item.kind, item.reason) for item in retired.incompatibilities] == [
                ("field_definition", "retired"),
                ("memory_switch", "memory_disabled"),
                ("source_manifest", "retired"),
            ]

            unavailable = await loader.load(
                CompatibilityManifest(
                    execution=(
                        PinRequest(
                            kind="field_definition",
                            key="core.primary_domain",
                            version="99",
                        ),
                        PinRequest(kind="source_manifest", key="absent", version="1"),
                        PinRequest(kind="source_profile", key="frontier_ai", version="99"),
                    )
                ),
                context=context,
            )
            assert [(item.kind, item.reason) for item in unavailable.incompatibilities] == [
                ("field_definition", "version_mismatch"),
                ("source_manifest", "missing"),
                ("source_profile", "version_mismatch"),
            ]

    run_async(scenario())


# --- a static policy pin must hash the same in every worker process (2026-10-22) -------------

_STATIC_PIN_DIGESTS = """
import asyncio
from clue_api.recipe_wiring import VersionedPinResource, _register_static_catalog
from clue_config.ingestion import DEFAULT_INGESTION_POLICY
from clue_config.proposals import DEFAULT_PROPOSAL_POLICY
from clue_execution import CompatibilityContext, PinRequest, PinResolverRegistry

registry = PinResolverRegistry()
for kind, payload in (("proposal_policy", DEFAULT_PROPOSAL_POLICY),
                      ("ingestion_policy", DEFAULT_INGESTION_POLICY)):
    _register_static_catalog(
        registry,
        kind=kind,
        resources=(VersionedPinResource(key="default", version="1", payload=payload),),
    )
    resolver = registry.get(kind)
    observation = asyncio.run(resolver.observe(
        PinRequest(kind=kind, key="default", version="1"),
        CompatibilityContext(workspace_id="ws-1", project_id=None),
    ))
    print(observation.digest)
"""


def test_a_static_policy_pin_hashes_the_same_in_every_process() -> None:
    """The path the fleet workers take: a set inside a policy must not make two workers pin it
    under different digests (a turn taken over by another worker then fails to replay)."""
    import os
    import subprocess
    import sys

    seen = set()
    for seed in (1, 2, 3, 4, 5, 6):
        result = subprocess.run(
            [sys.executable, "-c", _STATIC_PIN_DIGESTS],
            env={**os.environ, "PYTHONHASHSEED": str(seed)},
            capture_output=True,
            text=True,
            check=True,
        )
        seen.add(tuple(result.stdout.split()))
    assert len(seen) == 1
