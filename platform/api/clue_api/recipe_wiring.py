"""C5.2 composition: production pin adapters and idempotent system-recipe seeding."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text

import clue_execution
from clue_agents import discover_skills
from clue_config import DEFAULT_STAGE0_POLICY, Config, Stage0Policy, get_config
from clue_config.coverage import DEFAULT_RESEARCH_LOOP_POLICY
from clue_config.ingestion import DEFAULT_INGESTION_POLICY
from clue_config.proposals import DEFAULT_PROPOSAL_POLICY
from clue_db import ConnFactory, transaction
from clue_execution import (
    CallablePinResolver,
    CompatibilityContext,
    CompatibilityLoader,
    DbRecipeRepository,
    PinRequest,
    PinResolverRegistry,
    RecipeDefinition,
    RecipeLifecycle,
    RecipeRevisionEventType,
    RecipeRevisionView,
    ResourceObservation,
    canonical_payload_digest,
    load_recipe_definition,
)
from clue_storage import get_artifact
from clue_toolbelt import ToolRegistry

STAGE0_POLICY_VERSION = "1"
SYSTEM_RECIPE_FILENAMES: tuple[str, ...] = (
    "recipe0-stage0-v1.json",
    "recipe0-stage0-v2.json",
    "recipe0-stage0-v3.json",
    "recipe0-stage0-v4.json",
    "recipe0-stage0-v5.json",
    # FI Lane D D4: v6 is v5 plus the Option-B kickoff chain — the agent may draft direction,
    # present its confirmation gate, and launch the research the human's confirming turn approved.
    # A promoted recipe revision is immutable, so widening the interaction slot's ceiling is a new
    # revision rather than an edit, exactly like the profile mint the same slice needed.
    "recipe0-stage0-v6.json",
    # The pilot bytes remain authoritative for colliding v7/v8: trusted @2 readiness/synthesis and
    # the durable exact-subject ICP confirmation gate. (PD-part3 P3.4's colliding v7 — v6 plus
    # ``open_design_leg@1`` — was re-versioned to v16 at the integration merge.)
    "recipe0-stage0-v7.json",
    "recipe0-stage0-v8.json",
    # Onboarding's non-conflicting v9 retains the selected-product read lineage.
    "recipe0-stage0-v9.json",
    # Integration v10 composes both lineages without rewriting any historical revision.
    "recipe0-stage0-v10.json",
    # Confirmed-run v2 derives/reuses the existing Stage-0 receipt and starts discovery internally.
    "recipe0-stage0-v11.json",
    # Provider-neutral discovery scope is derived/confirmed and pinned by start @3.
    "recipe0-stage0-v12.json",
    # Bounded ICP presentation accompanies the normal assistant message; Exa preflights pre-run.
    "recipe0-stage0-v13.json",
    # Exact current-message Account refs can inspect the governed view and detached fleet state.
    "recipe0-stage0-v14.json",
    # Plan-safe research directives retain the frozen v2 contract while new turns use @3.
    "recipe0-stage0-v15.json",
    # PD-part3 P3.4's design delegation entry (``open_design_leg@1``), re-versioned onto the v15
    # lineage at the part-iii integration merge. Same rule as v6: the C5 slot is a second,
    # independent ceiling, so a profile grant alone would show the model a tool that plan
    # validation then refuses.
    "recipe0-stage0-v16.json",
    "recipe1-classic-v1.json",
    "recipe1-classic-v2.json",
)

# Kept on disk solely so already-pinned executions can resolve their exact historical definition.
# R1 never seeds or promotes these recipes for new executions.
HISTORICAL_REPLAY_ONLY_RECIPE_FILENAMES: tuple[str, ...] = ("account-research-unit-v1.json",)


@dataclass(frozen=True, slots=True)
class VersionedPinResource:
    key: str
    version: str
    payload: object
    status: str = "active"


def _observation(
    *,
    version: str | None,
    payload: object,
    status: str = "active",
    digest: str | None = None,
    metadata: Mapping[str, str | int | bool | None] | None = None,
) -> ResourceObservation:
    return ResourceObservation(
        version=version,
        digest=digest or canonical_payload_digest(payload),
        status=status,
        metadata=dict(metadata or {}),
    )


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=False)
    return value


def _register_static_catalog(
    registry: PinResolverRegistry,
    *,
    kind: str,
    resources: Sequence[VersionedPinResource],
) -> None:
    by_key_version: dict[tuple[str, str], VersionedPinResource] = {}
    by_key: dict[str, list[VersionedPinResource]] = {}
    for item in resources:
        identity = (item.key, item.version)
        if identity in by_key_version:
            raise ValueError(f"{kind} resource {item.key!r}@{item.version} is registered twice")
        by_key_version[identity] = item
        by_key.setdefault(item.key, []).append(item)

    async def load(
        request: PinRequest,
        _context: CompatibilityContext,
    ) -> ResourceObservation | None:
        resource = (
            by_key_version.get((request.key, request.version))
            if request.version is not None
            else None
        )
        if resource is None:
            candidates = by_key.get(request.key, [])
            active = [item for item in candidates if item.status == "active"]
            resource = active[0] if len(active) == 1 else None
        if resource is None:
            return None
        return _observation(
            version=resource.version,
            payload=_jsonable(resource.payload),
            status=resource.status,
        )

    registry.register(CallablePinResolver(kind=kind, loader=load))


def build_recipe_pin_registry(
    *,
    tool_registry: ToolRegistry,
    conn_factory: ConnFactory = transaction,
    stage0_policy: Stage0Policy = DEFAULT_STAGE0_POLICY,
    config: Config | None = None,
    skill_root: Path | None = None,
    prompt_resources: Sequence[VersionedPinResource] = (),
    model_policy_resources: Sequence[VersionedPinResource] = (),
    extra_static_resources: Mapping[str, Sequence[VersionedPinResource]] | None = None,
    config_for: Callable[[str, str | None], Config] = get_config,
) -> PinResolverRegistry:
    """Register the production adapters at the API composition root.

    Database-backed resources are observed in their owning tables. Code/config resources are
    registered as explicit versioned catalogs; an unknown historical version fails honestly.
    """
    registry = PinResolverRegistry()

    async def tool(
        request: PinRequest,
        _context: CompatibilityContext,
    ) -> ResourceObservation | None:
        if request.version is None or not tool_registry.has(request.key, request.version):
            if not tool_registry.has(request.key):
                return None
            descriptor = tool_registry.descriptor(request.key)
        else:
            descriptor = tool_registry.descriptor(request.key, request.version)
        payload = {
            "address": descriptor.address,
            "input_schema_sha256": descriptor.input_schema_sha256,
            "output_schema_sha256": descriptor.output_schema_sha256,
            "replay": {
                "policy": descriptor.replay.policy.value,
                "durable_identity": descriptor.replay.durable_identity,
                "operation_id_required": descriptor.replay.operation_id_required,
                "external_boundary": descriptor.replay.external_boundary.value,
            },
            "effect_class": descriptor.effect_class.value,
            "pin_requirements": descriptor.pin_requirements,
        }
        return _observation(version=descriptor.version, payload=payload)

    registry.register(CallablePinResolver(kind="tool", loader=tool))

    async def current_registry_row(
        request: PinRequest,
        _context: CompatibilityContext,
        *,
        table: str,
        key_column: str,
    ) -> ResourceObservation | None:
        async with conn_factory() as conn:
            if request.key == "__all_active__":
                rows = (
                    (
                        await conn.execute(
                            text(
                                f"SELECT to_jsonb(t) AS payload FROM {table} t "
                                f"WHERE active ORDER BY {key_column}"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                return _observation(version="snapshot-v1", payload=list(rows))
            row = (
                (
                    await conn.execute(
                        text(
                            f"SELECT to_jsonb(t) AS payload, version, active "
                            f"FROM {table} t WHERE {key_column} = :key"
                        ),
                        {"key": request.key},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return _observation(
            version=str(row["version"]),
            payload=row["payload"],
            status="active" if row["active"] else "retired",
        )

    async def field(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        return await current_registry_row(
            request,
            context,
            table="field_definition",
            key_column="field_key",
        )

    async def source(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        return await current_registry_row(
            request,
            context,
            table="source_manifest",
            key_column="source_key",
        )

    for kind in ("field_definition", "field_registry"):
        registry.register(CallablePinResolver(kind=kind, loader=field))
    for kind in ("source_manifest", "source_registry"):
        registry.register(CallablePinResolver(kind=kind, loader=source))

    async def scoped_spine_row(
        request: PinRequest,
        context: CompatibilityContext,
        *,
        table: str,
        key_column: str,
    ) -> ResourceObservation | None:
        async with conn_factory() as conn:
            row = (
                await conn.execute(
                    text(
                        f"SELECT to_jsonb(t) AS payload FROM {table} t "
                        f"WHERE {key_column} = :key AND workspace_id = :workspace_id"
                    ),
                    {"key": request.key, "workspace_id": context.workspace_id},
                )
            ).scalar_one_or_none()
        return None if row is None else _observation(version="1", payload=row)

    def spine_loader(
        table: str,
        key_column: str,
    ) -> Callable[
        [PinRequest, CompatibilityContext],
        Awaitable[ResourceObservation | None],
    ]:
        async def load(
            request: PinRequest,
            context: CompatibilityContext,
        ) -> ResourceObservation | None:
            return await scoped_spine_row(
                request,
                context,
                table=table,
                key_column=key_column,
            )

        return load

    for kind, table, key_column in (
        ("brand", "brand", "brand_id"),
        ("product", "product", "product_id"),
        ("project", "project", "project_id"),
    ):
        registry.register(
            CallablePinResolver(
                kind=kind,
                loader=spine_loader(table, key_column),
            )
        )

    async def project_run(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        try:
            UUID(request.key)
        except ValueError:
            return None
        async with conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT run.id, run.workspace_id, run.project_id,
                                   run.icp_key, run.icp_version,
                                   run.client_entity_id, run.client_kb_version, run.product_id,
                                   run.product_context_version_id, run.readiness_decision_id,
                                   run.tier_cutoffs_json,
                                   config.configuration_sha256
                            FROM project_run run
                            LEFT JOIN project_run_discovery_configuration config
                              ON config.project_run_id = run.id
                             AND config.workspace_id = run.workspace_id
                            WHERE run.id = CAST(:key AS uuid)
                              AND run.workspace_id = :workspace_id
                            """
                        ),
                        {"key": request.key, "workspace_id": context.workspace_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        # Deliberately excludes mutable phase/status/budget counters. This pin is the immutable
        # run identity and lineage Recipe #1 is allowed to resume against.
        return _observation(version="1", payload=dict(row))

    registry.register(CallablePinResolver(kind="project_run", loader=project_run))

    async def research_directive(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        """One account-research directive **revision**, by directive id (FI Lane D D4).

        The pin kind the Option-B kickoff tools declare. Its version is the directive's own
        ``version`` column, so pinning it says "this exact revision" — which is what makes a gate,
        and then a launch, refuse a directive that was redrafted underneath them.

        The payload is deliberately the *immutable* revision identity and lineage, the same
        posture ``project_run`` takes: ``status`` / ``confirmed_by`` / ``confirmed_at`` are
        lifecycle, they move between the gate call and the launch call by design, and the tools
        that care about them check them themselves.
        """

        try:
            UUID(request.key)
        except ValueError:
            return None
        async with conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT directive_id, workspace_id, project_id, product_id,
                                   icp_key, icp_version, version, predecessor_id,
                                   canonical_json_sha256
                            FROM account_research_directive
                            WHERE directive_id = CAST(:key AS uuid)
                              AND workspace_id = :workspace_id
                            """
                        ),
                        {"key": request.key, "workspace_id": context.workspace_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return _observation(version=str(row["version"]), payload=dict(row))

    registry.register(CallablePinResolver(kind="research_directive", loader=research_directive))

    async def account_research_selection(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        """The exact account-research selection a launch authorizes — **absent before the launch**.

        ``launch_account_research@1`` declares this pin kind because a selection *is* its subject,
        but the selection does not exist until the launcher mints it: its id is derived from the
        request digest inside the launch transaction. So on the only path that matters — the first,
        real launch — this resolver correctly returns ``None`` and the caller supplies the pin as
        **optional**, which resolves to a recorded ``status='missing'`` pin rather than an
        incompatibility. Requiring it would deadlock the flow: the tool could never run, because
        the thing it is pinned to is the thing it creates.

        It still resolves truthfully once a selection exists, so a *replay* of an already-launched
        run (and any later audit of one) pins the real thing rather than a permanent absence.
        """

        try:
            UUID(request.key)
        except ValueError:
            # Includes the ``__not_supplied__`` sentinel the pin provider uses to declare the
            # absence explicitly; "there is no selection yet" is the honest observation.
            return None
        async with conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT selection_id, research_run_id, workspace_id, project_id,
                                   product_id, project_run_id, lifecycle_sha256
                            FROM entity_research_run
                            WHERE selection_id = CAST(:key AS uuid)
                              AND workspace_id = :workspace_id
                            """
                        ),
                        {"key": request.key, "workspace_id": context.workspace_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return _observation(version="1", payload=dict(row))

    registry.register(
        CallablePinResolver(kind="account_research_selection", loader=account_research_selection)
    )

    async def account(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        try:
            UUID(request.key)
        except ValueError:
            return None
        async with conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT id, workspace_id, canonical_name,
                                   primary_domain AS canonical_domain, merged_into
                            FROM account_entity
                            WHERE id = CAST(:key AS uuid) AND workspace_id = :workspace_id
                            """
                        ),
                        {"key": request.key, "workspace_id": context.workspace_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _observation(version="1", payload=dict(row))

    registry.register(CallablePinResolver(kind="account", loader=account))

    async def supervisor_policy(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        config_value = config_for(context.workspace_id, request.key)
        policy = config_value.supervisor_policy
        return _observation(
            version=policy.version,
            payload=policy,
            metadata={"icp_key": request.key},
        )

    registry.register(CallablePinResolver(kind="supervisor_policy", loader=supervisor_policy))

    async def client_kb(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        entity_id, separator, product_id = request.key.partition("|")
        if not separator or request.version is None:
            return None
        try:
            UUID(entity_id)
            version = int(request.version)
        except ValueError:
            return None
        async with conn_factory() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT id, field_key, value_json, evidence_span, run_id, product_id
                            FROM claim
                            WHERE workspace_id = :workspace_id
                              AND entity_id = CAST(:entity_id AS uuid)
                              AND (
                                  (:product_id = '-' AND product_id IS NULL)
                                  OR product_id = :product_id
                              )
                              AND (
                                  field_key <> 'client.kb_version'
                                  OR (value_json->>'version')::int = :version
                              )
                            ORDER BY field_key, id
                            """
                        ),
                        {
                            "workspace_id": context.workspace_id,
                            "entity_id": entity_id,
                            "product_id": product_id,
                            "version": version,
                        },
                    )
                )
                .mappings()
                .all()
            )
        marker = next(
            (
                row
                for row in rows
                if row["field_key"] == "client.kb_version"
                and int(row["value_json"]["version"]) == version
            ),
            None,
        )
        if marker is None:
            return None
        run_id = marker["run_id"]
        pinned = [dict(row) for row in rows if row["run_id"] == run_id]
        return _observation(version=str(version), payload=pinned)

    registry.register(CallablePinResolver(kind="client_kb", loader=client_kb))
    # Product-KB uses the same claim/version substrate but a distinct pin kind. Keeping the kinds
    # separate prevents a company-scoped tool requirement from satisfying product authority (or
    # vice versa) while reusing the one exact-version resolver implementation.
    registry.register(CallablePinResolver(kind="product_kb", loader=client_kb))

    async def readiness_decision(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        try:
            UUID(request.key)
        except ValueError:
            return None
        async with conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT to_jsonb(r) AS payload, spec_version
                            FROM readiness_decision r
                            WHERE id = CAST(:key AS uuid) AND workspace_id = :workspace_id
                            """
                        ),
                        {"key": request.key, "workspace_id": context.workspace_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return _observation(version=str(row["spec_version"]), payload=row["payload"])

    registry.register(CallablePinResolver(kind="readiness_decision", loader=readiness_decision))

    async def icp(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        try:
            version_text = request.version
            requested_version = (
                None
                if version_text is None or version_text == "__observe_current__"
                else int(version_text)
            )
        except ValueError:
            return None
        async with conn_factory() as conn:
            if requested_version is not None:
                row = (
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT to_jsonb(i) AS payload, version, status
                                FROM icp_spec i
                                WHERE workspace_id = :workspace_id
                                  AND icp_key = :key AND version = :version
                                """
                            ),
                            {
                                "workspace_id": context.workspace_id,
                                "key": request.key,
                                "version": requested_version,
                            },
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            else:
                row = None
            if row is None:
                row = (
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT to_jsonb(i) AS payload, version, status
                                FROM icp_spec i
                                WHERE workspace_id = :workspace_id AND icp_key = :key
                                ORDER BY version DESC LIMIT 1
                                """
                            ),
                            {"workspace_id": context.workspace_id, "key": request.key},
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        if row is None:
            return None
        return _observation(
            version=str(row["version"]),
            payload=row["payload"],
            metadata={"lifecycle_status": str(row["status"])},
        )

    for kind in ("icp_spec", "icp"):
        registry.register(CallablePinResolver(kind=kind, loader=icp))

    async def source_profile(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        try:
            version_text = request.version
            requested_version = (
                None
                if version_text is None or version_text == "__observe_current__"
                else int(version_text)
            )
        except ValueError:
            return None
        async with conn_factory() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT DISTINCT ON (field_class)
                                   field_class, weighted_sources, version
                            FROM source_profile
                            WHERE pack_key = :key
                              AND (
                                  CAST(:version AS int) IS NULL
                                  OR version <= CAST(:version AS int)
                              )
                            ORDER BY field_class, version DESC
                            """
                        ),
                        {"key": request.key, "version": requested_version},
                    )
                )
                .mappings()
                .all()
            )
            if not rows and requested_version is not None:
                rows = (
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT DISTINCT ON (field_class)
                                       field_class, weighted_sources, version
                                FROM source_profile
                                WHERE pack_key = :key
                                ORDER BY field_class, version DESC
                                """
                            ),
                            {"key": request.key},
                        )
                    )
                    .mappings()
                    .all()
                )
            icp_key = context.attributes.get("icp_key")
            resolved_icp_key = icp_key if isinstance(icp_key, str) else None
            overrides = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT DISTINCT ON (field_class)
                                   field_class, icp_key, weighted_sources, version
                            FROM source_profile_override
                            WHERE pack_key = :key AND workspace_id = :workspace_id
                              AND (
                                  icp_key = CAST(:icp_key AS text)
                                  OR icp_key IS NULL
                              )
                              AND (
                                  CAST(:version AS int) IS NULL
                                  OR version <= CAST(:version AS int)
                              )
                            ORDER BY field_class, (icp_key IS NOT NULL) DESC, version DESC
                            """
                        ),
                        {
                            "key": request.key,
                            "workspace_id": context.workspace_id,
                            "icp_key": resolved_icp_key,
                            "version": requested_version,
                        },
                    )
                )
                .mappings()
                .all()
            )
        if not rows and not overrides:
            return None
        selected_version = max(int(row["version"]) for row in (*rows, *overrides))
        return _observation(
            version=str(selected_version),
            payload={
                "pack_key": request.key,
                "defaults": [dict(row) for row in rows],
                "workspace_overrides": [dict(row) for row in overrides],
            },
        )

    registry.register(CallablePinResolver(kind="source_profile", loader=source_profile))

    async def product_context(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        try:
            UUID(request.key)
        except ValueError:
            return None
        async with conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT to_jsonb(p) AS payload, manifest_hash, compiler_version
                            FROM product_context_version p
                            WHERE id = CAST(:key AS uuid) AND workspace_id = :workspace_id
                            """
                        ),
                        {"key": request.key, "workspace_id": context.workspace_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return _observation(
            version=str(row["compiler_version"]),
            payload=row["payload"],
            digest=str(row["manifest_hash"]),
        )

    registry.register(CallablePinResolver(kind="product_context", loader=product_context))

    async def artifact_input(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        async with conn_factory() as conn:
            artifact = await get_artifact(conn, request.key)
        if artifact is None or artifact.workspace_id != context.workspace_id:
            return None
        status = (
            "erased"
            if artifact.erased_at is not None or artifact.purged_at is not None
            else "active"
        )
        return _observation(
            version="1",
            payload={
                "storage_key": artifact.storage_key,
                "workspace_id": artifact.workspace_id,
                "media_type": artifact.media_type,
                "size_bytes": artifact.size_bytes,
            },
            digest=artifact.content_sha256,
            status=status,
        )

    registry.register(CallablePinResolver(kind="artifact_input", loader=artifact_input))

    async def memory_switch(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        if request.key not in {"default", "workspace", context.workspace_id}:
            return None
        async with conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT enabled, updated_at, updated_by
                            FROM memory_switch WHERE workspace_id = :workspace_id
                            """
                        ),
                        {"workspace_id": context.workspace_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        enabled = True if row is None else bool(row["enabled"])
        payload = {
            "workspace_id": context.workspace_id,
            "enabled": enabled,
            "updated_at": None if row is None else row["updated_at"],
            "updated_by": None if row is None else row["updated_by"],
        }
        return _observation(
            version="live",
            payload=payload,
            status="active" if enabled else "disabled",
            metadata={"enabled": enabled},
        )

    registry.register(CallablePinResolver(kind="memory_switch", loader=memory_switch))

    async def memory_bundle(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        try:
            UUID(request.key)
        except ValueError:
            return None
        async with conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT journal_id, workspace_id, recipe, requested_types, scope_stack,
                                   included, excluded, cross_branch_pairs, bundle_hash, created_at
                            FROM memory_bundle_journal
                            WHERE journal_id = CAST(:key AS uuid)
                              AND workspace_id = :workspace_id
                            """
                        ),
                        {"key": request.key, "workspace_id": context.workspace_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return _observation(
            version="1",
            payload=dict(row),
            digest=str(row["bundle_hash"]),
        )

    registry.register(CallablePinResolver(kind="memory_bundle_journal", loader=memory_bundle))

    skills = discover_skills(
        skill_root or Path(__file__).resolve().parents[2] / "agents" / "skills"
    )
    skill_resources: list[VersionedPinResource] = []
    for skill in skills:
        body_sha256 = hashlib.sha256(skill.path.read_bytes()).hexdigest()
        skill_resources.append(
            VersionedPinResource(
                key=skill.name,
                version=skill.version,
                payload={
                    "name": skill.name,
                    "version": skill.version,
                    "summary": skill.summary,
                    "tool_allowlist": skill.tool_allowlist,
                    "body_sha256": body_sha256,
                },
            )
        )
    for kind in ("skill", "stage0_skill"):
        _register_static_catalog(registry, kind=kind, resources=skill_resources)

    config_version = (
        canonical_payload_digest(
            [item.model_dump(mode="json") for item in config.applied_versions]
        )[:16]
        if config is not None
        else None
    )
    resolved_model_policy_resources = tuple(model_policy_resources)
    if config is not None and not resolved_model_policy_resources:
        resolved_model_policy_resources = (
            VersionedPinResource(
                key="gateway",
                version=config_version or "unversioned",
                payload=config.gateway,
            ),
        )

    _register_static_catalog(registry, kind="prompt", resources=prompt_resources)
    _register_static_catalog(
        registry,
        kind="model_policy",
        resources=resolved_model_policy_resources,
    )
    default_stage0_prompt = VersionedPinResource(
        key="stage0-icp-synthesis",
        version="1",
        payload={
            "implementation": "clue_research.stage0.icp_synthesis",
            "contract_version": 1,
        },
    )
    model_prompt_resources = (*prompt_resources, *resolved_model_policy_resources)
    if not any(item.key == default_stage0_prompt.key for item in model_prompt_resources):
        model_prompt_resources = (*model_prompt_resources, default_stage0_prompt)
    _register_static_catalog(
        registry,
        kind="model_prompt",
        resources=model_prompt_resources,
    )

    readiness = stage0_policy.readiness

    async def readiness_policy(
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        if request.key not in {"default", "workspace", context.workspace_id}:
            return None
        try:
            requested_version = int(request.version) if request.version is not None else None
        except ValueError:
            return None
        async with conn_factory() as conn:
            if requested_version is not None:
                row = (
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT version, policy_json, policy_hash
                                FROM readiness_spec_revision
                                WHERE workspace_id = :workspace_id AND version = :version
                                """
                            ),
                            {
                                "workspace_id": context.workspace_id,
                                "version": requested_version,
                            },
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            else:
                row = None
            if row is None:
                row = (
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT version, policy_json, policy_hash
                                FROM readiness_spec_revision
                                WHERE workspace_id = :workspace_id
                                ORDER BY version DESC LIMIT 1
                                """
                            ),
                            {"workspace_id": context.workspace_id},
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        if row is None:
            return _observation(
                version=str(readiness.version),
                payload=readiness,
                metadata={"source": "code_default"},
            )
        return _observation(
            version=str(row["version"]),
            payload=row["policy_json"],
            digest=str(row["policy_hash"]),
            metadata={"source": "workspace_revision"},
        )

    registry.register(CallablePinResolver(kind="readiness_policy", loader=readiness_policy))
    _register_static_catalog(
        registry,
        kind="stage0_policy",
        resources=(
            VersionedPinResource(
                key="default",
                version=STAGE0_POLICY_VERSION,
                payload=stage0_policy,
            ),
        ),
    )
    _register_static_catalog(
        registry,
        kind="proposal_policy",
        resources=(
            VersionedPinResource(
                key="default",
                version="1",
                payload=DEFAULT_PROPOSAL_POLICY,
            ),
        ),
    )
    _register_static_catalog(
        registry,
        kind="ingestion_policy",
        resources=(
            VersionedPinResource(
                key="default",
                version="1",
                payload=DEFAULT_INGESTION_POLICY,
            ),
        ),
    )
    _register_static_catalog(
        registry,
        kind="coverage_policy",
        resources=(
            VersionedPinResource(
                key="default",
                version="1",
                payload=DEFAULT_RESEARCH_LOOP_POLICY,
            ),
        ),
    )

    if config is not None:
        policy_resources: dict[str, object] = {
            "budget_policy": config.budget_caps,
            "cost_policy": config.budget_caps,
            "deep_policy": config.recursion_policy,
            "scoring_policy": config.scoring_rubric,
            "tier_policy": config.source_plan_policy,
            "verification_policy": config.verification_health_thresholds,
        }
        version = config_version or "unversioned"
        for kind, payload in policy_resources.items():
            _register_static_catalog(
                registry,
                kind=kind,
                resources=(VersionedPinResource(key="default", version=version, payload=payload),),
            )

    for kind, resources in (extra_static_resources or {}).items():
        if registry.get(kind) is not None:
            raise ValueError(f"extra static resource kind {kind!r} duplicates a production adapter")
        _register_static_catalog(registry, kind=kind, resources=resources)

    return registry


def system_recipe_asset_root() -> Path:
    source_root = Path(__file__).resolve().parents[2] / "execution" / "recipes"
    if source_root.is_dir():
        return source_root
    execution_file = clue_execution.__file__
    installed_root = (
        Path(execution_file).resolve().parent / "recipes" if execution_file is not None else Path()
    )
    if installed_root.is_dir():
        return installed_root
    raise FileNotFoundError("system recipe assets are not installed")


def load_system_recipe_definitions(
    *,
    asset_root: Path | None = None,
) -> tuple[RecipeDefinition, ...]:
    root = asset_root or system_recipe_asset_root()
    return tuple(load_recipe_definition(root / filename) for filename in SYSTEM_RECIPE_FILENAMES)


async def seed_system_recipes(
    *,
    repository: DbRecipeRepository,
    lifecycle: RecipeLifecycle,
    definitions: Sequence[RecipeDefinition] | None = None,
) -> tuple[RecipeRevisionView, ...]:
    """Idempotently propose and promote checked-in system revisions.

    A same-version asset mismatch is rejected by :meth:`DbRecipeRepository.propose`; operators
    must add the next version rather than rewrite history.
    """
    seeded: list[RecipeRevisionView] = []
    for definition in definitions or load_system_recipe_definitions():
        if definition.scope_type.value != "system":
            raise ValueError("the system recipe seed accepts system-scoped definitions only")
        revision = await repository.propose(definition)
        effective = await repository.effective_event(recipe_revision_id=revision.recipe_revision_id)
        if effective is not None and effective.event_type is RecipeRevisionEventType.PROPOSED:
            result = await lifecycle.promote(
                revision,
                context=CompatibilityContext(workspace_id="__system__"),
                actor="system",
            )
            if not result.promoted:
                graph_reasons = [
                    f"{issue.location}:{issue.code}" for issue in result.graph_validation.issues
                ]
                pin_reasons = [
                    f"{item.kind}:{item.key}:{item.reason}"
                    for item in result.compatibility.incompatibilities
                ]
                raise ValueError(
                    f"system recipe {definition.recipe_key}@{definition.version} "
                    f"failed promotion: {graph_reasons + pin_reasons}"
                )
        if revision.definition_sha256 != definition.definition_sha256:
            raise RuntimeError("promoted seed digest differs from the checked-in definition")
        seeded.append(revision)
    by_recipe: dict[str, list[RecipeRevisionView]] = {}
    for revision in seeded:
        by_recipe.setdefault(str(revision.recipe_id), []).append(revision)
    for revisions in by_recipe.values():
        latest = max(revisions, key=lambda item: item.version)
        for older in revisions:
            if older.version >= latest.version:
                continue
            effective = await repository.effective_event(
                recipe_revision_id=older.recipe_revision_id
            )
            if effective is not None and effective.event_type is RecipeRevisionEventType.PROMOTED:
                await lifecycle.supersede(
                    recipe_revision_id=older.recipe_revision_id,
                    replacement=latest,
                    actor="system",
                )
    return tuple(seeded)


def build_recipe_lifecycle(
    *,
    tool_registry: ToolRegistry,
    conn_factory: ConnFactory = transaction,
    pin_registry: PinResolverRegistry,
) -> RecipeLifecycle:
    return RecipeLifecycle(
        repository=DbRecipeRepository(conn_factory=conn_factory),
        tool_catalog=tool_registry,
        compatibility_loader=CompatibilityLoader(pin_registry),
    )


__all__ = [
    "HISTORICAL_REPLAY_ONLY_RECIPE_FILENAMES",
    "STAGE0_POLICY_VERSION",
    "SYSTEM_RECIPE_FILENAMES",
    "VersionedPinResource",
    "build_recipe_lifecycle",
    "build_recipe_pin_registry",
    "load_system_recipe_definitions",
    "seed_system_recipes",
    "system_recipe_asset_root",
]
