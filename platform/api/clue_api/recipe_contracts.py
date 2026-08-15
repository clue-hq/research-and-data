"""Standing Recipe #0/#1 tool inventory and replay-safety audit."""

from __future__ import annotations

from dataclasses import dataclass

from clue_toolbelt import (
    ExternalReplayBoundary,
    ReplayPolicy,
    ToolEffectClass,
    ToolRegistry,
)

RECIPE_0_TOOL_ADDRESSES: tuple[str, ...] = (
    "submit_onboarding_input@1",
    "start_recon@1",
    "record_interview_answer@1",
    "confirm_project_product@1",
    "evaluate_stage0_readiness@2",
    "synthesize_icps@2",
    "open_icp_confirmation_gate@1",
    "confirm_icp@1",
    "override_stage0_readiness@1",
    "open_discovery_configuration_gate@1",
    "start_confirmed_project_run@3",
    "propose_field@2",
    "propose_source@1",
    "submit_ingestion@1",
    # PC-C8 §7 (retained in recipe0-stage0@5): the two bounded read-only history tools. A tool the
    # card's
    # omission cursors resolve through has to be runnable in the Stage-0 interaction slot, and
    # anything in that slot is certified here first.
    "inspect_statement_history@1",
    "inspect_readiness_history@1",
    # FI production context S4-D (recipe0-stage0@8): strict artifact-bound reads behind the
    # bounded Client-KB index. Both are effect-free and pin only the exact Client-KB checkpoint;
    # project/workspace/client authority is injected from the production constitution.
    "list_client_knowledge@2",
    "inspect_client_claim@2",
    # S5-D (recipe0-stage0@9): selected-product knowledge stays a separate exact Product-KB
    # surface. Scope is injected from the paired turn pin; both reads are effect-free.
    "list_product_knowledge@1",
    "inspect_product_claim@1",
    # S5-F: this model-callable action presents the exact pinned catalog to the human but cannot
    # confirm a product. Its deterministic gate identity makes retries domain-idempotent.
    "open_product_selection_gate@1",
    # FI Lane D D4 (added in recipe0-stage0@6): the Option-B kickoff chain. Anything runnable in
    # the Stage-0 interaction slot is replay-certified here first, and these three are the whole
    # point of the widened conversation surface — draft the direction, present its confirmation
    # gate, and launch what the human's confirming turn approved.
    "draft_account_research_directive@2",
    "open_directive_confirmation_gate@1",
    "launch_account_research@1",
    # FI-2 exact current-message Account launch, retained in integration recipe0-stage0@11.
    "launch_selected_account_research@1",
)

RECIPE_1_TOOL_ADDRESSES: tuple[str, ...] = (
    "reverse_profile@1",
    "synthesize_icps@1",
    "confirm_icp@1",
    "import_accounts@1",
    "discover_accounts@1",
    "score_accounts@1",
    "submit_tier_checkpoint@1",
    "submit_project_checkpoint@1",
    "advance_project_phase@1",
    "run_deep_account@1",
    "resolve_committee@1",
    "profile_contact@1",
    "run_verification@1",
    "compose_handoff@1",
    "estimate_project@1",
    "start_project_run@1",
    "pause_run@1",
    "resume_run@1",
    "adjust_budget@1",
)

ACCOUNT_RESEARCH_TOOL_ADDRESSES: tuple[str, ...] = ("research_account_gaps@2",)


def _split_address(address: str) -> tuple[str, str]:
    name, separator, version = address.rpartition("@")
    if not separator or not name or not version:
        raise ValueError(f"invalid exact tool address {address!r}")
    return name, version


@dataclass(frozen=True, slots=True)
class ReplayAuditEntry:
    address: str
    recipes: tuple[str, ...]
    replay_policy: ReplayPolicy
    durable_identity: str
    operation_id_required: bool
    external_boundary: ExternalReplayBoundary
    effect_class: ToolEffectClass
    input_schema_sha256: str
    output_schema_sha256: str
    pin_requirements: tuple[str, ...]


def standing_recipe_addresses() -> tuple[str, ...]:
    return tuple(
        sorted(
            set(RECIPE_0_TOOL_ADDRESSES)
            | set(RECIPE_1_TOOL_ADDRESSES)
            | set(ACCOUNT_RESEARCH_TOOL_ADDRESSES)
        )
    )


def build_replay_safety_audit(registry: ToolRegistry) -> tuple[ReplayAuditEntry, ...]:
    """Resolve every standing tool exactly and return the machine-readable replay audit."""
    entries: list[ReplayAuditEntry] = []
    failures: list[str] = []
    for address in standing_recipe_addresses():
        name, version = _split_address(address)
        descriptor = registry.descriptor(name, version)
        if not descriptor.has_typed_output:
            failures.append(f"{address}: output is untyped")
        if descriptor.replay.policy is ReplayPolicy.UNCERTIFIED:
            failures.append(f"{address}: replay policy is uncertified")
        if not descriptor.pin_requirements:
            failures.append(f"{address}: pin requirements are empty")
        if (
            descriptor.effect_class is ToolEffectClass.STEERING
            and not descriptor.has_steering_snapshot
        ):
            failures.append(f"{address}: steering snapshot is absent")
        recipes = tuple(
            recipe
            for recipe, addresses in (
                ("recipe0@1", RECIPE_0_TOOL_ADDRESSES),
                ("recipe1@1", RECIPE_1_TOOL_ADDRESSES),
                ("account-research-unit@1", ACCOUNT_RESEARCH_TOOL_ADDRESSES),
            )
            if address in addresses
        )
        entries.append(
            ReplayAuditEntry(
                address=address,
                recipes=recipes,
                replay_policy=descriptor.replay.policy,
                durable_identity=descriptor.replay.durable_identity,
                operation_id_required=descriptor.replay.operation_id_required,
                external_boundary=descriptor.replay.external_boundary,
                effect_class=descriptor.effect_class,
                input_schema_sha256=descriptor.input_schema_sha256,
                output_schema_sha256=descriptor.output_schema_sha256,
                pin_requirements=descriptor.pin_requirements,
            )
        )
    if failures:
        raise ValueError("standing recipe contract audit failed:\n" + "\n".join(failures))
    return tuple(entries)


__all__ = [
    "RECIPE_0_TOOL_ADDRESSES",
    "RECIPE_1_TOOL_ADDRESSES",
    "ACCOUNT_RESEARCH_TOOL_ADDRESSES",
    "ReplayAuditEntry",
    "build_replay_safety_audit",
    "standing_recipe_addresses",
]
