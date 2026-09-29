"""C5.4 durable compatibility adapter for governed Recipe #0 interactions."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import text

from clue_api.agent_turn_scope_pin import get_agent_turn_scope_pin
from clue_api.stage0_project_contracts import TrustedStage0ProjectScopeInput
from clue_api.stage0_project_scope import resolve_stage0_project_scope
from clue_api.turn_action import TurnActionUnresolvable, parse_turn_action_ref
from clue_core import EntityId
from clue_db import ConnFactory
from clue_execution import (
    CompatibilityContext,
    CompatibilityLoader,
    ExecutionConflict,
    PinRequest,
    RecipeExecutor,
)
from clue_research.stage0 import current_kb_version
from clue_toolbelt import ToolContext, ToolRegistry, ToolResult

_STAGE0_SLOT = "stage0_interactions"


class RecipeStep(BaseModel):
    """One explicit C4 step; bodies are snapshotted, while extra pins remain references."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step_id: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    tool_name: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    input_refs: dict[str, JsonValue]
    depends_on: tuple[str, ...] = ()
    pin_requests: tuple[PinRequest, ...] = ()


class RecipeRunner(Protocol):
    async def run_step(self, step: RecipeStep, *, ctx: ToolContext) -> ToolResult: ...


class StepPinProvider(Protocol):
    async def pins_for(
        self,
        step: RecipeStep,
        *,
        ctx: ToolContext,
    ) -> tuple[PinRequest, ...]: ...


class Stage0StepPinProvider:
    """Freeze exact workspace-local Stage-0 refs immediately before child materialization."""

    def __init__(
        self,
        *,
        compatibility: CompatibilityLoader,
        conn_factory: ConnFactory,
        tools: ToolRegistry,
    ) -> None:
        self._compatibility = compatibility
        self._conn_factory = conn_factory
        self._tools = tools

    async def _current(
        self,
        *,
        kind: str,
        key: str,
        ctx: ToolContext,
        required: bool = True,
    ) -> PinRequest:
        observation = await self._compatibility.observe_current(
            kind=kind,
            key=key,
            context=CompatibilityContext(workspace_id=ctx.workspace_id),
        )
        if observation is None:
            if required:
                raise ExecutionConflict(f"cannot pin missing Stage-0 resource {kind}:{key}")
            return PinRequest(kind=kind, key=key, version="missing", required=False)
        return PinRequest(
            kind=kind,
            key=key,
            version=observation.version,
            digest=observation.digest,
            required=required,
        )

    async def _exact(
        self,
        *,
        kind: str,
        key: str,
        version: str,
        ctx: ToolContext,
    ) -> PinRequest:
        request = PinRequest(kind=kind, key=key, version=version)
        report = await self._compatibility.resolve_requirements(
            (request,),
            context=CompatibilityContext(workspace_id=ctx.workspace_id),
        )
        if not report.compatible or len(report.pins) != 1:
            reason = (
                report.incompatibilities[0].reason if report.incompatibilities else "unresolved"
            )
            raise ExecutionConflict(f"cannot pin Stage-0 resource {kind}:{key}@{version}: {reason}")
        pin = report.pins[0]
        return PinRequest(
            kind=kind,
            key=key,
            version=pin.version,
            digest=pin.digest,
        )

    async def _execution_project_pin(self, ctx: ToolContext) -> PinRequest:
        """Resolve a tool's project pin from the execution this step is running under (D9).

        For a tool whose body names no project *and* carries no presenting-turn ref, the execution
        row is the trusted coordinate: the run was started against one project and cannot move. An
        execution with no project is pinned explicitly absent, so the tool's own preconditions
        refuse it rather than the plan failing to validate.

        Used by the ARV2 lane's tools (``launch_arv2_account_research@1`` /
        ``launch_arv2_person_research@1`` / ``read_arv2_account_research_run@1``) — wired in
        Task 5 of the O6 lane, and extended to the person launch when v44 granted it.
        """

        absent = PinRequest(
            kind="project",
            key="__not_supplied__",
            version="missing",
            required=False,
        )
        if ctx.execution_id is None:
            return absent
        async with self._conn_factory() as conn:
            project_id = (
                await conn.execute(
                    text(
                        "SELECT project_id FROM execution "
                        "WHERE id = :execution_id AND workspace_id = :workspace_id"
                    ),
                    {"execution_id": ctx.execution_id, "workspace_id": ctx.workspace_id},
                )
            ).scalar_one_or_none()
        if not isinstance(project_id, str) or not project_id:
            return absent
        return await self._current(kind="project", key=project_id, ctx=ctx)

    async def _presenting_turn_project_pin(
        self,
        body: dict[str, JsonValue],
        *,
        ctx: ToolContext,
    ) -> PinRequest:
        """Resolve a tool's project pin from the presenting-turn ref the engine injected.

        Shared by every tool whose only trusted input is that ref (``open_design_leg``, the
        product-set gate, the artifact-shaped ICP gate): the project is never a body field, so the
        pin is derived from the turn instead. A ref that does not resolve is pinned explicitly
        absent and the tool's own preconditions refuse it, with a reason a model can act on.
        """

        from clue_api.turn_action import (
            TurnActionUnresolvable,
            load_turn_identity,
            parse_turn_action_ref,
        )

        absent = PinRequest(
            kind="project",
            key="__not_supplied__",
            version="missing",
            required=False,
        )
        ref = body.get("source_turn_ref")
        if not isinstance(ref, str):
            return absent
        try:
            turn_id = parse_turn_action_ref(ref)
        except TurnActionUnresolvable:
            return absent
        async with self._conn_factory() as conn:
            turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
        if turn is None:
            return absent
        return await self._current(kind="project", key=turn.project_id, ctx=ctx)

    async def pins_for(
        self,
        step: RecipeStep,
        *,
        ctx: ToolContext,
    ) -> tuple[PinRequest, ...]:
        body = step.input_refs
        requested: list[PinRequest] = list(step.pin_requests)
        nested_scope = body.get("scope")
        declared_context = body.get("declared_context")
        scope_body = nested_scope if isinstance(nested_scope, dict) else {}
        ingestion_context = declared_context if isinstance(declared_context, dict) else {}

        descriptor = self._tools.descriptor(step.tool_name, step.tool_version)
        if issubclass(descriptor.input_model, TrustedStage0ProjectScopeInput):
            async with self._conn_factory() as conn:
                trusted_stage0_scope = await resolve_stage0_project_scope(
                    conn,
                    workspace_id=ctx.workspace_id,
                    execution_id=ctx.execution_id,
                )
            if trusted_stage0_scope is None:
                raise ExecutionConflict(
                    "cannot pin a Stage-0 v2 tool without an execution-bound project"
                )
            required_scope_kinds = set(descriptor.pin_requirements) & {
                "brand",
                "project",
                "product",
                "client_kb",
                "product_kb",
            }
            if "brand" in required_scope_kinds:
                requested.append(
                    await self._current(kind="brand", key=trusted_stage0_scope.brand_id, ctx=ctx)
                )
            if "project" in required_scope_kinds:
                requested.append(
                    await self._current(
                        kind="project", key=trusted_stage0_scope.project_id, ctx=ctx
                    )
                )
            if "product" in required_scope_kinds:
                if trusted_stage0_scope.product_id is None:
                    raise ExecutionConflict(
                        "cannot pin a project-scoped Stage-0 tool before product confirmation"
                    )
                requested.append(
                    await self._current(
                        kind="product", key=trusted_stage0_scope.product_id, ctx=ctx
                    )
                )
            if "client_kb" in required_scope_kinds:
                if (
                    trusted_stage0_scope.client_entity_id is None
                    or trusted_stage0_scope.client_kb_version is None
                ):
                    raise ExecutionConflict(
                        "cannot pin a project-scoped Stage-0 tool without a Client Knowledge Base"
                    )
                requested.append(
                    await self._exact(
                        kind="client_kb",
                        # ``client_kb_version`` is the independently-versioned, account-wide
                        # company snapshot. The selected product is already frozen by the
                        # separate ``product`` pin above; applying the company version to a
                        # product-scoped KB key couples two lineages that legitimately differ.
                        key=f"{trusted_stage0_scope.client_entity_id}|-",
                        version=str(trusted_stage0_scope.client_kb_version),
                        ctx=ctx,
                    )
                )
            if "product_kb" in required_scope_kinds:
                if (
                    trusted_stage0_scope.client_entity_id is None
                    or trusted_stage0_scope.product_id is None
                    or trusted_stage0_scope.product_kb_version is None
                ):
                    raise ExecutionConflict(
                        "cannot pin a project-scoped Stage-0 tool without selected-product "
                        "knowledge"
                    )
                requested.append(
                    await self._exact(
                        kind="product_kb",
                        key=(
                            f"{trusted_stage0_scope.client_entity_id}|"
                            f"{trusted_stage0_scope.product_id}"
                        ),
                        version=str(trusted_stage0_scope.product_kb_version),
                        ctx=ctx,
                    )
                )

        artifact_pairs: set[tuple[str, str]] = set()
        artifact_key = body.get("artifact_key")
        content_sha256 = body.get("content_sha256")
        if isinstance(artifact_key, str) and isinstance(content_sha256, str):
            artifact_pairs.add((artifact_key, content_sha256))
        elif isinstance(artifact_key, str):
            requested.append(
                await self._current(
                    kind="artifact_input",
                    key=artifact_key,
                    ctx=ctx,
                )
            )
        onboarding_ids = body.get("onboarding_input_ids")
        if isinstance(onboarding_ids, list) and onboarding_ids:
            async with self._conn_factory() as conn:
                rows = (
                    await conn.execute(
                        text(
                            """
                                SELECT artifact_key, content_sha256
                                FROM onboarding_input
                                WHERE workspace_id = :workspace_id
                                  AND id = ANY(CAST(:ids AS uuid[]))
                                """
                        ),
                        {"workspace_id": ctx.workspace_id, "ids": onboarding_ids},
                    )
                ).all()
            if len(rows) != len(set(onboarding_ids)):
                raise ExecutionConflict(
                    "one or more onboarding inputs are absent from this workspace"
                )
            artifact_pairs.update((str(row[0]), str(row[1])) for row in rows)
        for key, digest in sorted(artifact_pairs):
            requested.append(PinRequest(kind="artifact_input", key=key, digest=digest))

        # Top level first, then the two nested carriers. Since PC-C8 task 1.4 hoisted
        # `brand_id`/`project_id` out of `scope`/`declared_context` (they are trusted authority, and
        # the strip/inject seam is top-level only), the nested fallback is live for `product_id`
        # alone — kept for the others because the lookup is uniform, not because they nest.
        for field, kind in (
            ("brand_id", "brand"),
            ("product_id", "product"),
            ("project_id", "project"),
        ):
            value = body.get(field, scope_body.get(field, ingestion_context.get(field)))
            if isinstance(value, str):
                requested.append(await self._current(kind=kind, key=value, ctx=ctx))

        # S5-F/S6 production composition: the product-selection gate intentionally exposes no
        # model-authored scope arguments. Its sole trusted input is the captured turn reference,
        # while the exact project and company Client-KB pair live in that turn's immutable scope
        # receipt. Resolve the descriptor's two required pins from that receipt here, at the same
        # execution-authority seam that resolves every other dynamic tool pin. Deriving them from
        # current project state would let background publication or a later project mutation
        # change the authority of an already-running turn.
        if step.tool_name == "open_product_selection_gate":
            source_turn_ref = body.get("source_turn_ref")
            if not isinstance(source_turn_ref, str):
                raise ExecutionConflict(
                    "open_product_selection_gate requires its trusted source turn reference"
                )
            try:
                source_turn_id = parse_turn_action_ref(source_turn_ref)
            except TurnActionUnresolvable as exc:
                raise ExecutionConflict(
                    "open_product_selection_gate has an invalid source turn reference"
                ) from exc
            async with self._conn_factory() as conn:
                turn_pin = await get_agent_turn_scope_pin(
                    conn,
                    workspace_id=ctx.workspace_id,
                    turn_id=source_turn_id,
                )
            if (
                turn_pin is None
                or turn_pin.client_entity_id is None
                or turn_pin.client_kb_version is None
            ):
                raise ExecutionConflict(
                    "open_product_selection_gate requires a durable project and Client-KB scope"
                )
            requested.extend(
                (
                    await self._current(
                        kind="project",
                        key=turn_pin.project_id,
                        ctx=ctx,
                    ),
                    await self._exact(
                        kind="client_kb",
                        key=f"{turn_pin.client_entity_id}|-",
                        version=str(turn_pin.client_kb_version),
                        ctx=ctx,
                    ),
                )
            )

        if step.tool_name == "start_recon":
            requested.extend(
                (
                    await self._current(
                        kind="field_registry",
                        key="__all_active__",
                        ctx=ctx,
                    ),
                    await self._current(
                        kind="source_registry",
                        key="__all_active__",
                        ctx=ctx,
                    ),
                )
            )

        # --- FI Lane D D4: the Option-B kickoff chain ------------------------------------------
        # ``draft`` composes direction against the live registries, so it pins them the way
        # ``start_recon`` does. The gate and the launch pin the two durable objects they act on:
        # the project run that authorizes spend, and the exact directive revision being confirmed
        # (which is what makes a redrafted directive refuse rather than slip through).
        if step.tool_name == "draft_account_research_directive":
            requested.extend(
                (
                    await self._current(
                        kind="field_registry",
                        key="__all_active__",
                        ctx=ctx,
                    ),
                    await self._current(
                        kind="source_registry",
                        key="__all_active__",
                        ctx=ctx,
                    ),
                )
            )
        # --- PD-part3 P3.4: the design delegation entry ----------------------------------------
        # The leg's project is not a body field (every authority value is derived from the
        # presenting turn), so the pin is resolved through the turn ref the engine injected. A
        # ref that does not resolve is pinned explicitly absent (the launch tool's idiom) — the
        # tool's own preconditions are what refuse it, with a reason a model can act on.
        # ARV2 context and authoring: the ICP-authoring pair derives its project the same way and
        # for the same reason — each carries only the trusted `source_turn_ref`, never a
        # model-authored project, so the presenting turn is the coordinate the pin resolves from.
        # The project plan derives its project the same way and for the same reason: the tool
        # carries only the trusted `source_turn_ref` and never a model-authored project.
        # `author_icp_document`, `request_persona_synthesis` and `write_project_document` are
        # ungranted from `head-of-abm@v55` and out of the slot at recipe0-stage0@27, but they stay
        # named here: an execution pinned to an earlier revision still plans them, and it still
        # needs this pin resolved to replay.
        # ``configure_project_targeting@1`` (head-of-abm@v61+) replaced the product-set and ICP
        # gates and carries the same trusted ``source_turn_ref`` only, so it resolves the same way.
        if step.tool_name in {
            "author_icp_document",
            "configure_project_targeting",
            "open_design_leg",
            "open_product_set_selection_gate",
            "request_persona_synthesis",
            "write_project_document",
        }:
            requested.append(await self._presenting_turn_project_pin(body, ctx=ctx))
        # The artifact-shaped ICP gate (``@2``) derives its project the same way. ``@1`` keeps the
        # Stage-0 scope path above, so the version is part of the condition.
        if step.tool_name == "open_icp_confirmation_gate" and step.tool_version == "2":
            requested.append(await self._presenting_turn_project_pin(body, ctx=ctx))
        # --- ARV2 onboarding O6: the new-lane launches and their read --------------------------
        # None of the three carries a presenting-turn ref, so the execution row is the trusted
        # coordinate for their ``project`` pin. The account launch is authorized by its ICP
        # artifact digest and product-selection version and the read names only a run id; the
        # person launch names a project in its body, but a body field is model-authored and the
        # execution's own project is not, so it is pinned from the same trusted coordinate as its
        # siblings. An execution with no project pins explicitly absent and each tool's own
        # preconditions refuse it, rather than the plan failing to validate.
        # ARV2 Track R, R4 adds the discovery launch on exactly the person launch's terms.
        # The three ARV2 reads join them for the same reason: two name a `project_id` in their
        # body and the third names no project at all (it is keyed on an account), and a body field
        # is model-authored, so the execution's own project — which is not — is the coordinate
        # their ``project`` pin resolves from.
        # ``read_claims`` and ``read_artifact`` join them at recipe0-stage0@28 on the same terms:
        # the claims query is keyed on an entity and the gallery read on an artifact id, so
        # neither names a project it could be trusted about. This set is keyed by tool NAME, so
        # the paged ``@2`` of the two reads resolves its ``project`` pin exactly as its ``@1``
        # does, and an execution pinned to an older revision still plans the ``@1``.
        if step.tool_name in {
            "launch_arv2_account_research",
            "launch_arv2_discovery",
            "launch_arv2_person_research",
            "read_account_research",
            "read_artifact",
            "read_arv2_account_research_run",
            "read_claims",
            "read_discovery_run",
            "read_project_accounts",
            # ``run_python`` joins them at recipe0-stage0@29 for the same reason: its body is a
            # script, so it names no project either, and the project it must be bound to — the
            # one whose ``attachments/`` the container can see — is the execution's own.
            "run_python",
            # ``web_search`` joins at recipe0-stage0@31: its body names no project either; the
            # pin is the execution's own.
            "web_search",
        }:
            requested.append(await self._execution_project_pin(ctx))

        if step.tool_name in {
            "open_directive_confirmation_gate",
            "launch_account_research",
            "launch_selected_account_research",
        }:
            project_run_id = body.get("project_run_id")
            if isinstance(project_run_id, str):
                requested.append(
                    await self._current(kind="project_run", key=project_run_id, ctx=ctx)
                )
            directive_id = body.get("research_directive_id")
            if isinstance(directive_id, str):
                requested.append(
                    await self._current(kind="research_directive", key=directive_id, ctx=ctx)
                )
        # --- Slice B browser-gate repair (founder ruling 2026-08-19): the research-view read ---
        # ``get_research_view@1`` has been granted to the conversation slot since FI-2, but no
        # case here ever REQUESTED its three declared pin kinds, so plan validation refused every
        # call (``missing_tool_requirement``) and the grant was dead — the agent could never read
        # run state and needed identifiers spoon-fed in chat.
        if step.tool_name == "get_research_view":
            view_run_id = body.get("project_run_id")
            if isinstance(view_run_id, str):
                requested.append(await self._current(kind="project_run", key=view_run_id, ctx=ctx))
            requested.append(
                await self._current(kind="field_registry", key="__all_active__", ctx=ctx)
            )
            # Verification may be disabled (the integration-pilot posture): the policy resource
            # is then absent from the catalog, and the read must still be possible — the pin is
            # requested not-required, so it resolves when the policy exists and records an
            # explicit absence when verification is off, never failing the plan.
            requested.append(
                await self._current(
                    kind="verification_policy", key="default", ctx=ctx, required=False
                )
            )
        if step.tool_name in {
            "launch_account_research",
            "launch_selected_account_research",
        }:
            # Declared absent, not resolved: the selection this launch pins is the selection the
            # launch *creates* (its id is derived from the request digest inside the launch
            # transaction), so requiring it would make the tool permanently unreachable. This is
            # the same explicit-absence idiom the optional Stage-0 kinds below use.
            requested.append(
                PinRequest(
                    kind="account_research_selection",
                    key="__not_supplied__",
                    version="missing",
                    required=False,
                )
            )

        if step.tool_name == "propose_field":
            requested.extend(
                (
                    await self._current(
                        kind="proposal_policy",
                        key="default",
                        ctx=ctx,
                    ),
                    await self._current(
                        kind="field_registry",
                        key="__all_active__",
                        ctx=ctx,
                    ),
                )
            )
        elif step.tool_name == "propose_source":
            requested.extend(
                (
                    await self._current(
                        kind="proposal_policy",
                        key="default",
                        ctx=ctx,
                    ),
                    await self._current(
                        kind="source_registry",
                        key="__all_active__",
                        ctx=ctx,
                    ),
                )
            )
        elif step.tool_name == "submit_ingestion":
            requested.append(
                await self._current(
                    kind="ingestion_policy",
                    key="default",
                    ctx=ctx,
                )
            )

        if step.tool_name in {"synthesize_icps", "confirm_icp"}:
            requested.append(
                await self._current(
                    kind="field_registry",
                    key="__all_active__",
                    ctx=ctx,
                )
            )
        if step.tool_name == "synthesize_icps":
            requested.append(
                await self._current(
                    kind="model_prompt",
                    key="stage0-icp-synthesis",
                    ctx=ctx,
                )
            )
        if step.tool_name == "confirm_icp":
            proposal = body.get("proposal")
            pack_key = proposal.get("pack_key") if isinstance(proposal, dict) else None
            if not isinstance(pack_key, str):
                raise ExecutionConflict("confirm_icp requires a proposal pack_key pin")
            requested.append(await self._current(kind="source_profile", key=pack_key, ctx=ctx))

        client_entity_id = body.get("client_entity_id")
        client_kb_version = body.get("client_kb_version", body.get("kb_version"))
        product_id = body.get("product_id")
        product_kb_version = body.get("product_kb_version")
        if (
            step.tool_name in {"synthesize_icps", "confirm_icp"}
            and isinstance(client_entity_id, str)
            and not isinstance(client_kb_version, int)
        ):
            try:
                entity_id = EntityId(UUID(client_entity_id))
            except ValueError as exc:
                raise ExecutionConflict("client_entity_id is malformed") from exc
            async with self._conn_factory() as conn:
                client_kb_version = await current_kb_version(
                    conn,
                    entity_id,
                    workspace_id=ctx.workspace_id,
                    product_id=None,
                )
            if client_kb_version is None:
                raise ExecutionConflict("cannot pin a missing Client Knowledge Base")
        if isinstance(client_entity_id, str) and isinstance(client_kb_version, int):
            requested.append(
                await self._exact(
                    kind="client_kb",
                    key=f"{client_entity_id}|-",
                    version=str(client_kb_version),
                    ctx=ctx,
                )
            )

        if (
            isinstance(client_entity_id, str)
            and isinstance(product_id, str)
            and isinstance(product_kb_version, int)
        ):
            requested.append(
                await self._exact(
                    kind="product_kb",
                    key=f"{client_entity_id}|{product_id}",
                    version=str(product_kb_version),
                    ctx=ctx,
                )
            )

        product_context_id = body.get("product_context_version_id")
        if isinstance(product_context_id, str):
            requested.append(
                await self._current(
                    kind="product_context",
                    key=product_context_id,
                    ctx=ctx,
                )
            )

        readiness_decision_id = body.get("readiness_decision_id")
        if isinstance(readiness_decision_id, str):
            requested.append(
                await self._current(
                    kind="readiness_decision",
                    key=readiness_decision_id,
                    ctx=ctx,
                )
            )

        icp_key = body.get("icp_key", scope_body.get("icp_key"))
        icp_version = body.get(
            "icp_version",
            scope_body.get("icp_spec_version"),
        )
        if isinstance(icp_key, str) and isinstance(icp_version, int):
            requested.append(
                await self._exact(
                    kind="icp",
                    key=icp_key,
                    version=str(icp_version),
                    ctx=ctx,
                )
            )

        optional_missing_kinds = {
            "submit_onboarding_input": {
                "product": body.get("product_id"),
                "project": body.get("project_id"),
            },
            "evaluate_stage0_readiness": {
                "product_context": body.get("product_context_version_id"),
                "client_kb": body.get("client_kb_version"),
                "icp": body.get("icp_key"),
            },
        }.get(step.tool_name, {})
        present_kinds = {item.kind for item in requested}
        for kind, value in optional_missing_kinds.items():
            if value is None and kind not in present_kinds:
                requested.append(
                    PinRequest(
                        kind=kind,
                        key="__not_supplied__",
                        version="missing",
                        required=False,
                    )
                )

        deduped: dict[tuple[str, str], PinRequest] = {}
        for item in requested:
            identity = (item.kind, item.key)
            existing = deduped.get(identity)
            if existing is not None and existing != item:
                raise ExecutionConflict(
                    f"conflicting Stage-0 pin requests for {item.kind}:{item.key}"
                )
            deduped[identity] = item
        return tuple(deduped[identity] for identity in sorted(deduped))


class ToolbeltRecipeRunner:
    """Submit one C4 step as a bounded Recipe-#0 child and execute it through C5's journal."""

    def __init__(
        self,
        *,
        executor: RecipeExecutor,
        pin_provider: StepPinProvider,
        slot_key: str = _STAGE0_SLOT,
    ) -> None:
        self._executor = executor
        self._pin_provider = pin_provider
        self._slot_key = slot_key

    async def run_step(self, step: RecipeStep, *, ctx: ToolContext) -> ToolResult:
        if ctx.execution_id is None:
            raise ValueError("durable Recipe #0 steps require ctx.execution_id")
        pins = await self._pin_provider.pins_for(step, ctx=ctx)
        appended = await self._executor.append_interaction_tool(
            execution_id=ctx.execution_id,
            workspace_id=ctx.workspace_id,
            slot_key=self._slot_key,
            node_key=step.step_id,
            tool_name=step.tool_name,
            tool_version=step.tool_version,
            inputs=step.input_refs,
            actor=ctx.actor,
            dependencies=step.depends_on,
            pin_requests=pins,
        )
        return await self._executor.invoke_interaction_tool(
            appended,
            inputs=step.input_refs,
            actor=ctx.actor,
        )


__all__ = [
    "RecipeRunner",
    "RecipeStep",
    "Stage0StepPinProvider",
    "StepPinProvider",
    "ToolbeltRecipeRunner",
]
