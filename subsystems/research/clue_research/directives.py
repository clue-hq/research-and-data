"""Durable account-research directive compiler and repository (M8B A2).

This is the single domain write/read surface behind the A2 tools.  Directive content and account
overrides are immutable; only the lifecycle moves draft -> confirmed -> superseded, with an
append-only event for each transition.  Memory is submitted through its shared seam and remains
advisory.  No provider or claim writer is reachable from this module.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast
from uuid import UUID, uuid5

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    USER_RESEARCH_INSTRUCTION_MAX_BYTES,
    EffectiveAccountResearchDirective,
    EntityId,
    EntityScope,
    MemoryAccepted,
    MemoryDisabled,
    MemoryPreconditionFailed,
    MemoryProvenanceClass,
    MemoryRejected,
    MemoryScopeType,
    MemorySubmission,
    MemoryType,
    MemoryWriteSeam,
    OperationId,
    PassKind,
    ResearchAccountScope,
    ResearchDirective,
    ResearchDirectiveAccountOverride,
    ResearchDirectiveAccountOverrideBody,
    ResearchDirectiveBody,
    ResearchDirectiveId,
    ResearchDirectiveOverrideId,
    ResearchDirectivePin,
    ResearchDirectiveStatus,
    ResearchSealedSelectionRef,
    ScopeRef,
    SubmissionOutcome,
    compose_account_research_directive,
    research_directive_digest,
    research_directive_override_digest,
)
from clue_core.research_profile import COMPREHENSIVE_ACCOUNT_FIELDS
from clue_research.claimstore.registry import get_field
from clue_research.durable.scheduler import AccountSpec
from clue_research.durable.spend_posture import record_policy_refusal_skipped
from clue_research.icp import get_icp_version
from clue_research.identity import get_account
from clue_research.membership import ensure_project_account
from clue_research.sources.authority import load_effective_source_plan
from clue_research.sources.registry import get_source, sources_for
from clue_research.sources.source_profile import resolve_allowed_set
from clue_spine import get_project

#: Attribution for the record-only policy posture (:mod:`clue_research.durable.spend_posture`).
_SITE_DIRECTIVE_MEMORY_SEAM = "research_directive_memory_seam"

_OVERRIDE_NAMESPACE = UUID("466ca70e-f500-51b9-abf8-891353fcfc0c")
_EVENT_NAMESPACE = UUID("742bbb9b-564f-572f-891a-0849122c3031")


class ResearchDirectiveError(RuntimeError):
    """Base error for a well-typed directive the durable compiler cannot admit."""


class ResearchDirectiveNotFound(ResearchDirectiveError):
    pass


class ResearchDirectiveConflict(ResearchDirectiveError):
    pass


class ResearchDirectiveInvalid(ResearchDirectiveError):
    pass


@dataclass(frozen=True, slots=True)
class DraftedResearchDirective:
    directive: ResearchDirective
    overrides: tuple[ResearchDirectiveAccountOverride, ...]
    account_ids: tuple[EntityId, ...]
    memory_outcome: str


def _event_id(operation_id: OperationId, directive_id: ResearchDirectiveId, event: str) -> UUID:
    return uuid5(_EVENT_NAMESPACE, f"{operation_id}:{directive_id}:{event}")


def _override_id(
    directive_id: ResearchDirectiveId, account_id: EntityId
) -> ResearchDirectiveOverrideId:
    return ResearchDirectiveOverrideId(uuid5(_OVERRIDE_NAMESPACE, f"{directive_id}:{account_id}"))


#: Contract §3.1 — the fixed 21-field comprehensive account profile. Directive-valid as a
#: platform contract independent of per-field pass_kind and of the pinned ICP's authored list.
_COMPREHENSIVE_PROFILE_FIELDS = frozenset(COMPREHENSIVE_ACCOUNT_FIELDS)


async def validate_research_directive_draft(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    product_id: str,
    icp_key: str,
    icp_version: int,
    body: ResearchDirectiveBody,
    overrides: dict[EntityId, ResearchDirectiveAccountOverrideBody],
) -> tuple[EntityId, ...]:
    project = await get_project(conn, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise ResearchDirectiveInvalid("research directive project is absent or cross-workspace")
    if project.product_id != product_id:
        raise ResearchDirectiveInvalid("research directive product is not selected by the project")
    icp = await get_icp_version(conn, workspace_id, icp_key, icp_version)
    if icp is None or icp.product_id != product_id:
        raise ResearchDirectiveInvalid("research directive ICP/product lineage is absent")

    field_keys = set(body.field_keys)
    field_keys.update(
        question.target_field_key
        for question in body.questions
        if question.target_field_key is not None
    )
    for override in overrides.values():
        field_keys.update(override.include_field_keys)
        field_keys.update(override.exclude_field_keys)
        field_keys.update(
            question.target_field_key
            for question in override.additional_questions
            if question.target_field_key is not None
        )
    active_icp_fields = set(icp.field_keys)
    for field_key in sorted(field_keys):
        field = await get_field(conn, field_key)
        # The fixed comprehensive account profile (contract §3.1, COMPREHENSIVE_ACCOUNT_FIELDS) is a
        # platform contract, not an ICP choice: its rows are directive-valid regardless of
        # pass_kind (ten are core.* firmographics born in the scoring era) and regardless of the
        # pinned ICP's authored field list (§3.3 row 1 — a full-profile command compiles to all
        # 21 unless the user explicitly narrows). Every field OUTSIDE the fixed profile keeps the
        # strict deep-registration and ICP-activation gates unchanged.
        comprehensive = field_key in _COMPREHENSIVE_PROFILE_FIELDS
        if field is None or (not comprehensive and field.pass_kind is not PassKind.DEEP):
            raise ResearchDirectiveInvalid(
                f"research directive field {field_key!r} is not a registered deep field"
            )
        if not comprehensive and field_key not in active_icp_fields:
            raise ResearchDirectiveInvalid(
                f"research directive field {field_key!r} is not active in the pinned ICP"
            )

    canonical_field_sources: set[str] = set()
    for field_key in sorted(field_keys):
        frozen = await load_effective_source_plan(
            conn,
            workspace_id=workspace_id,
            icp_key=icp_key,
            icp_version=icp_version,
            field_key=field_key,
        )
        if frozen is not None:
            canonical_field_sources.update(item.source_key for item in frozen.sources)
        else:
            profiled = await resolve_allowed_set(
                conn,
                icp,
                field_key,
                entity_scope=EntityScope.ACCOUNT,
            )
            if profiled:
                canonical_field_sources.update(item.source_key for item in profiled)
            else:
                # A pinned ICP may deliberately carry no source-profile override. That is not a
                # ban on research: admit only active registry sources whose declared capability
                # covers the exact deep field. An existing frozen/profiled plan remains strict.
                canonical_field_sources.update(
                    await sources_for(
                        conn,
                        field_key,
                        entity_scope=EntityScope.ACCOUNT,
                        active=True,
                    )
                )

    source_keys = set(body.source_policy.allowed_source_keys)
    for override in overrides.values():
        if override.source_policy is not None:
            if not set(override.source_policy.allowed_source_keys) <= set(
                body.source_policy.allowed_source_keys
            ):
                raise ResearchDirectiveInvalid(
                    "account source-policy override may only narrow project sources"
                )
            source_keys.update(override.source_policy.allowed_source_keys)
    for source_key in sorted(source_keys):
        source = await get_source(conn, source_key)
        if source is None or not source.active:
            raise ResearchDirectiveInvalid(
                f"research directive source {source_key!r} is not active in the registry"
            )
        field_authorized = source_key in canonical_field_sources
        committee_authorized = (
            body.privacy_policy.committee_discovery_allowed and "contact" in source.manifest.yields
        )
        if not (field_authorized or committee_authorized):
            raise ResearchDirectiveInvalid(
                f"research directive source {source_key!r} is outside the pinned ICP field plans "
                "and is not a registered committee-enumeration source"
            )

    scoped_ids = set(
        await resolve_research_directive_accounts(
            conn,
            workspace_id=workspace_id,
            project_id=project_id,
            icp_key=icp_key,
            icp_version=icp_version,
            scope=body.account_scope,
        )
    )
    project_question_ids = {item.question_id for item in body.questions}
    for override in overrides.values():
        unknown_question_ids = set(override.exclude_question_ids) - project_question_ids
        if unknown_question_ids:
            raise ResearchDirectiveInvalid(
                "account override excludes unknown project question ids: "
                + ", ".join(sorted(unknown_question_ids))
            )
    for account_id in (*scoped_ids, *overrides):
        account = await get_account(conn, account_id)
        if account is None or account.workspace_id != workspace_id:
            raise ResearchDirectiveInvalid(
                f"research directive account {account_id} is absent or cross-workspace"
            )
        if account_id not in scoped_ids:
            raise ResearchDirectiveInvalid(
                "account override lies outside the resolved account scope"
            )
    return tuple(sorted(scoped_ids, key=str))


async def resolve_research_directive_accounts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    icp_key: str,
    icp_version: int,
    scope: ResearchAccountScope,
) -> tuple[EntityId, ...]:
    """Resolve an explicit scope or one exact immutable discovery seal to canonical accounts."""

    typed_scope = ResearchAccountScope.model_validate(scope)
    if typed_scope.explicit_account_ids:
        return typed_scope.explicit_account_ids
    assert typed_scope.sealed_selection_ref is not None
    sealed = ResearchSealedSelectionRef.parse(typed_scope.sealed_selection_ref)
    row = (
        (
            await conn.execute(
                text(
                    "SELECT manifest.account_ids FROM discovery_batch_seal seal "
                    "JOIN discovery_batch_manifest manifest "
                    "ON manifest.batch_id=seal.batch_id "
                    "AND manifest.workspace_id=seal.workspace_id "
                    "WHERE seal.workspace_id=:workspace_id AND seal.batch_id=:batch_id "
                    "AND seal.seal_sha256=:seal_sha256 AND manifest.project_id=:project_id "
                    "AND manifest.icp_key=:icp_key AND manifest.icp_version=:icp_version"
                ),
                {
                    "workspace_id": workspace_id,
                    "batch_id": sealed.discovery_batch_id,
                    "seal_sha256": sealed.discovery_seal_sha256,
                    "project_id": project_id,
                    "icp_key": icp_key,
                    "icp_version": icp_version,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ResearchDirectiveInvalid(
            "sealed research selection is absent or has different project/ICP lineage"
        )
    account_ids = tuple(EntityId(UUID(str(value))) for value in row["account_ids"])
    if not account_ids:
        raise ResearchDirectiveInvalid("sealed research selection contains no accounts")
    if len(account_ids) != len(set(account_ids)):
        raise ResearchDirectiveInvalid("sealed research selection contains duplicate accounts")
    return account_ids


def research_directive_draft_request_sha256(
    *,
    workspace_id: str,
    project_id: str,
    product_id: str,
    icp_key: str,
    icp_version: int,
    body: ResearchDirectiveBody,
    account_overrides: dict[EntityId, ResearchDirectiveAccountOverrideBody],
    user_instruction: str,
    source_turn_ref: str,
    created_by: str,
    actor_type: Literal["human", "agent"],
    predecessor_id: ResearchDirectiveId | None,
) -> str:
    """Hash every caller-controlled draft input for durable replay conflict detection."""

    payload = {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "product_id": product_id,
        "icp_key": icp_key,
        "icp_version": icp_version,
        "body": body.model_dump(mode="json"),
        "account_overrides": [
            {
                "account_id": str(account_id),
                "body": override.model_dump(mode="json"),
            }
            for account_id, override in sorted(
                account_overrides.items(), key=lambda item: str(item[0])
            )
        ],
        "user_instruction": user_instruction,
        "source_turn_ref": source_turn_ref,
        "created_by": created_by,
        "actor_type": actor_type,
        "predecessor_id": str(predecessor_id) if predecessor_id is not None else None,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _row_to_directive(
    row: dict[str, object],
) -> ResearchDirective:
    try:
        return ResearchDirective(
            directive_id=ResearchDirectiveId(row["directive_id"]),  # type: ignore[arg-type]
            workspace_id=str(row["workspace_id"]),
            project_id=str(row["project_id"]),
            product_id=str(row["product_id"]),
            icp_key=str(row["icp_key"]),
            icp_version=cast(int, row["icp_version"]),
            version=cast(int, row["version"]),
            status=ResearchDirectiveStatus(str(row["status"])),
            body=ResearchDirectiveBody.model_validate(row["content_json"]),
            memory_refs=tuple(row["memory_refs"]),  # type: ignore[arg-type]
            created_by=str(row["created_by"]),
            source_turn_ref=str(row["source_turn_ref"]),
            predecessor_id=(
                ResearchDirectiveId(row["predecessor_id"])  # type: ignore[arg-type]
                if row["predecessor_id"] is not None
                else None
            ),
            canonical_json_sha256=str(row["canonical_json_sha256"]),
            created_at=cast(datetime, row["created_at"]),
            confirmed_by=(str(row["confirmed_by"]) if row["confirmed_by"] is not None else None),
            confirming_turn_ref=(
                str(row["confirming_turn_ref"]) if row["confirming_turn_ref"] is not None else None
            ),
            confirmed_at=cast(datetime | None, row["confirmed_at"]),
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise ResearchDirectiveInvalid(f"invalid stored research directive: {exc}") from exc


def _row_to_override(row: dict[str, object]) -> ResearchDirectiveAccountOverride:
    return ResearchDirectiveAccountOverride(
        override_id=ResearchDirectiveOverrideId(row["override_id"]),  # type: ignore[arg-type]
        directive_id=ResearchDirectiveId(row["directive_id"]),  # type: ignore[arg-type]
        workspace_id=str(row["workspace_id"]),
        account_id=EntityId(row["account_id"]),  # type: ignore[arg-type]
        body=ResearchDirectiveAccountOverrideBody.model_validate(row["content_json"]),
        created_by=str(row["created_by"]),
        source_turn_ref=str(row["source_turn_ref"]),
        canonical_json_sha256=str(row["canonical_json_sha256"]),
        created_at=row["created_at"],  # type: ignore[arg-type]
    )


_DIRECTIVE_COLUMNS = (
    "directive_id, workspace_id, project_id, product_id, icp_key, icp_version, version, "
    "status::text, predecessor_id, content_json, memory_refs, created_by, source_turn_ref, "
    "canonical_json_sha256, created_at, confirmed_by, confirming_turn_ref, confirmed_at"
)


async def get_research_directive(
    conn: AsyncConnection,
    directive_id: ResearchDirectiveId,
    *,
    workspace_id: str,
) -> ResearchDirective | None:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_DIRECTIVE_COLUMNS} FROM account_research_directive "
                    "WHERE directive_id=:directive_id AND workspace_id=:workspace_id"
                ),
                {"directive_id": directive_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return await _row_to_directive(dict(row)) if row is not None else None


async def get_latest_research_directive(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    product_id: str,
    icp_key: str,
    icp_version: int,
) -> ResearchDirective | None:
    """Return the newest immutable directive version for one exact project/ICP lineage.

    This is a read-side convenience for conversational context assembly. It deliberately returns
    a draft when that is the newest version: the Head-of-ABM must be able to describe an awaiting
    confirmation draft honestly rather than silently falling back to an older confirmed version.
    A launched operation still reads its separately pinned directive from the launch receipt.
    """

    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_DIRECTIVE_COLUMNS} FROM account_research_directive "
                    "WHERE workspace_id=:workspace_id AND project_id=:project_id "
                    "AND product_id=:product_id AND icp_key=:icp_key "
                    "AND icp_version=:icp_version ORDER BY version DESC LIMIT 1"
                ),
                {
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "product_id": product_id,
                    "icp_key": icp_key,
                    "icp_version": icp_version,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    return await _row_to_directive(dict(row)) if row is not None else None


async def research_directive_account_ids(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    directive_id: ResearchDirectiveId,
) -> tuple[EntityId, ...]:
    """Read the exact membership frozen when a directive draft was admitted."""

    values = (
        await conn.execute(
            text(
                "SELECT account_id FROM account_research_directive_account "
                "WHERE directive_id=:directive_id AND workspace_id=:workspace_id "
                "ORDER BY account_id"
            ),
            {"directive_id": directive_id, "workspace_id": workspace_id},
        )
    ).scalars()
    return tuple(EntityId(value) for value in values)


async def get_research_directive_by_operation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: OperationId,
) -> ResearchDirective | None:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_DIRECTIVE_COLUMNS} FROM account_research_directive "
                    "WHERE workspace_id=:workspace_id AND draft_operation_id=:operation_id"
                ),
                {"workspace_id": workspace_id, "operation_id": operation_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return await _row_to_directive(dict(row)) if row is not None else None


async def research_directive_draft_replay_matches(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: OperationId,
    expected_request_sha256: str,
) -> bool | None:
    """Return ``None`` for a new operation, otherwise whether its frozen request is exact."""

    stored = (
        await conn.execute(
            text(
                "SELECT draft_request_sha256 FROM account_research_directive "
                "WHERE workspace_id=:workspace_id AND draft_operation_id=:operation_id"
            ),
            {"workspace_id": workspace_id, "operation_id": operation_id},
        )
    ).scalar_one_or_none()
    if stored is None:
        return None
    return str(stored) == expected_request_sha256


async def research_directive_confirmation_replay_matches(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    directive_id: ResearchDirectiveId,
    operation_id: OperationId,
    confirmed_by: str,
    confirming_turn_ref: str,
) -> bool:
    """Prove a confirmed directive carries this exact human confirmation receipt."""

    row = (
        (
            await conn.execute(
                text(
                    "SELECT confirmation_operation_id, confirmed_by, confirming_turn_ref "
                    "FROM account_research_directive WHERE workspace_id=:workspace_id "
                    "AND directive_id=:directive_id"
                ),
                {"workspace_id": workspace_id, "directive_id": directive_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return bool(
        row is not None
        and row["confirmation_operation_id"] == operation_id
        and row["confirmed_by"] == confirmed_by
        and row["confirming_turn_ref"] == confirming_turn_ref
    )


async def list_research_directive_overrides(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    directive_id: ResearchDirectiveId,
) -> tuple[ResearchDirectiveAccountOverride, ...]:
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT override_id, directive_id, workspace_id, account_id, content_json, "
                    "created_by, source_turn_ref, canonical_json_sha256, created_at "
                    "FROM account_research_directive_override "
                    "WHERE workspace_id=:workspace_id AND directive_id=:directive_id "
                    "ORDER BY account_id"
                ),
                {"workspace_id": workspace_id, "directive_id": directive_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(_row_to_override(dict(row)) for row in rows)


async def get_research_directive_override(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    directive_id: ResearchDirectiveId,
    account_id: EntityId,
) -> ResearchDirectiveAccountOverride | None:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT override_id, directive_id, workspace_id, account_id, content_json, "
                    "created_by, source_turn_ref, canonical_json_sha256, created_at "
                    "FROM account_research_directive_override "
                    "WHERE workspace_id=:workspace_id AND directive_id=:directive_id "
                    "AND account_id=:account_id"
                ),
                {
                    "workspace_id": workspace_id,
                    "directive_id": directive_id,
                    "account_id": account_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    return _row_to_override(dict(row)) if row is not None else None


async def _load_exact_draft_replay(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    operation_id: OperationId,
    request_sha256: str,
) -> DraftedResearchDirective | None:
    existing = await get_research_directive_by_operation(
        conn, workspace_id=workspace_id, operation_id=operation_id
    )
    if existing is None:
        return None
    replay_matches = await research_directive_draft_replay_matches(
        conn,
        workspace_id=workspace_id,
        operation_id=operation_id,
        expected_request_sha256=request_sha256,
    )
    if replay_matches is not True:
        raise ResearchDirectiveConflict(
            "draft operation id was already used with different research direction"
        )
    return DraftedResearchDirective(
        directive=existing,
        overrides=await list_research_directive_overrides(
            conn, workspace_id=workspace_id, directive_id=existing.directive_id
        ),
        account_ids=tuple(
            EntityId(value)
            for value in (
                await conn.execute(
                    text(
                        "SELECT account_id FROM account_research_directive_account "
                        "WHERE directive_id=:directive_id AND workspace_id=:workspace_id "
                        "ORDER BY account_id"
                    ),
                    {"directive_id": existing.directive_id, "workspace_id": workspace_id},
                )
            ).scalars()
        ),
        memory_outcome=("persisted" if existing.memory_refs else "memory_disabled"),
    )


async def draft_research_directive(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    product_id: str,
    icp_key: str,
    icp_version: int,
    body: ResearchDirectiveBody,
    account_overrides: dict[EntityId, ResearchDirectiveAccountOverrideBody],
    user_instruction: str,
    source_turn_ref: str,
    created_by: str,
    actor_type: Literal["human", "agent"],
    operation_id: OperationId,
    memory_write: MemoryWriteSeam,
    predecessor_id: ResearchDirectiveId | None = None,
) -> DraftedResearchDirective:
    instruction_size = len(user_instruction.encode("utf-8"))
    if not user_instruction.strip() or instruction_size > USER_RESEARCH_INSTRUCTION_MAX_BYTES:
        raise ResearchDirectiveInvalid(
            "user research instruction must contain 1 to "
            f"{USER_RESEARCH_INSTRUCTION_MAX_BYTES} UTF-8 bytes"
        )
    request_sha256 = research_directive_draft_request_sha256(
        workspace_id=workspace_id,
        project_id=project_id,
        product_id=product_id,
        icp_key=icp_key,
        icp_version=icp_version,
        body=body,
        account_overrides=account_overrides,
        user_instruction=user_instruction,
        source_turn_ref=source_turn_ref,
        created_by=created_by,
        actor_type=actor_type,
        predecessor_id=predecessor_id,
    )
    replay = await _load_exact_draft_replay(
        conn,
        workspace_id=workspace_id,
        operation_id=operation_id,
        request_sha256=request_sha256,
    )
    if replay is not None:
        return replay
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
        {"scope": f"research-directive:{workspace_id}:{project_id}:{product_id}:{icp_key}"},
    )
    # The first lookup is the fast replay path. Recheck under the lineage lock so two concurrent
    # deliveries of the same durable operation converge instead of the loser trying to append
    # behind the winner's still-draft version.
    replay = await _load_exact_draft_replay(
        conn,
        workspace_id=workspace_id,
        operation_id=operation_id,
        request_sha256=request_sha256,
    )
    if replay is not None:
        return replay
    resolved_account_ids = await validate_research_directive_draft(
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
        product_id=product_id,
        icp_key=icp_key,
        icp_version=icp_version,
        body=body,
        overrides=account_overrides,
    )

    latest_row = (
        (
            await conn.execute(
                text(
                    "SELECT directive_id, version, status::text, predecessor_id "
                    "FROM account_research_directive "
                    "WHERE workspace_id=:workspace_id AND project_id=:project_id "
                    "AND product_id=:product_id AND icp_key=:icp_key AND icp_version=:icp_version "
                    "ORDER BY version DESC LIMIT 1"
                ),
                {
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "product_id": product_id,
                    "icp_key": icp_key,
                    "icp_version": icp_version,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if latest_row is None:
        if predecessor_id is not None:
            raise ResearchDirectiveConflict("initial directive cannot name a predecessor")
        version = 1
        superseded_draft_id: ResearchDirectiveId | None = None
    else:
        latest_id = ResearchDirectiveId(latest_row["directive_id"])
        latest_status = str(latest_row["status"])
        if latest_status == "draft":
            # A draft is a proposal, not an authority: a fresh draft replaces it instead of
            # deadlocking the lineage. Found live at the Slice B browser gate: a draft whose
            # effort tier could never price its confirmation gate blocked every successor
            # forever, because confirmation is the only lifecycle exit and no reject path
            # exists. Confirmed history stays immutable — only the unconfirmed latest is
            # superseded, with its own append-only event naming the replacing directive.
            if predecessor_id is not None and predecessor_id != latest_id:
                raise ResearchDirectiveConflict("successor must name the latest directive version")
            superseded_draft_id = latest_id
            # The fresh draft takes over the superseded draft's position in the lineage: its
            # predecessor is the lineage's currently-confirmed directive (unique by the
            # one-confirmed-per-lineage index), or NULL when nothing is confirmed yet. Pointing
            # at the superseded draft instead would break confirmation twice over — the
            # confirmed-predecessor check would refuse it, and the one-confirmed index would
            # refuse a confirm that never superseded the lineage's current confirmed authority
            # (found live at the Slice B browser gate).
            confirmed_row = (
                (
                    await conn.execute(
                        text(
                            "SELECT directive_id FROM account_research_directive "
                            "WHERE workspace_id=:workspace_id AND project_id=:project_id "
                            "AND product_id=:product_id AND icp_key=:icp_key "
                            "AND icp_version=:icp_version AND status='confirmed'"
                        ),
                        {
                            "workspace_id": workspace_id,
                            "project_id": project_id,
                            "product_id": product_id,
                            "icp_key": icp_key,
                            "icp_version": icp_version,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            predecessor_id = (
                ResearchDirectiveId(confirmed_row["directive_id"])
                if confirmed_row is not None
                else None
            )
        else:
            if predecessor_id != latest_id:
                raise ResearchDirectiveConflict("successor must name the latest directive version")
            if latest_status != "confirmed":
                raise ResearchDirectiveConflict("cannot append behind an unconfirmed directive")
            superseded_draft_id = None
        version = int(latest_row["version"]) + 1

    memory_outcome: SubmissionOutcome | None
    try:
        memory_outcome = await memory_write.submit(
            MemorySubmission(
                workspace_id=workspace_id,
                scope=ScopeRef(scope_type=MemoryScopeType.PROJECT, scope_id=project_id),
                type=MemoryType.PREFERENCE,
                trigger=f"account-research-directive:{project_id}",
                body=user_instruction,
                provenance_class=MemoryProvenanceClass.USER_STATED,
                creating_quote=user_instruction,
            )
        )
    except MemoryPreconditionFailed as exc:
        # The seam's own deterministic person-adjacency guard: an instruction that happens to
        # carry an email address or a phone-shaped number ("...and cc me at me@acme.com") is a
        # malformed *memory submission* — the writer has no resolved contact to stamp, and this
        # call site never has one by construction. That is a fact about the memory record, not
        # about the directive, so it degrades like the rejection below rather than raising
        # through a fully validated draft. (Scope shape, the guard's only other cause, is built
        # by this function and cannot be wrong.)
        record_policy_refusal_skipped(
            site=_SITE_DIRECTIVE_MEMORY_SEAM,
            reason="person_adjacent_precondition",
            detail=str(exc),
        )
        memory_outcome = None
    # The memory side-write is advisory and it stays that way: a rejection is recorded, never
    # fatal (live blocker, 2026-08-20 16:26/16:29 IST — the memory seam's LLM reconciliation judge
    # answered ``body_ok=false`` on an instruction that legitimately named committee personas, and
    # the directive died). Doc M §2 is binding here — "memory is advisory; config is binding …
    # nothing authoritative lives in memory" — and the seam already models the degradation:
    # ``MemoryDisabled`` lands the directive with no refs and a truthful outcome. A rejection now
    # degrades identically. Store hygiene is untouched (the seam still wrote nothing); only the
    # veto over the primary flow dies. Deliberately unconditional, not pilot-gated: an advisory
    # subsystem's hygiene opinion may not stop a directive in *any* posture.
    if isinstance(memory_outcome, MemoryRejected):
        record_policy_refusal_skipped(
            site=_SITE_DIRECTIVE_MEMORY_SEAM,
            reason=memory_outcome.reason.value,
            detail=memory_outcome.detail,
        )
    memory_refs = (memory_outcome.memory_id,) if isinstance(memory_outcome, MemoryAccepted) else ()
    memory_outcome_name = (
        "persisted"
        if isinstance(memory_outcome, MemoryAccepted)
        else "memory_disabled"
        if isinstance(memory_outcome, MemoryDisabled)
        else f"memory_rejected:{memory_outcome.reason.value}"
        if isinstance(memory_outcome, MemoryRejected)
        else "memory_rejected:person_adjacent_precondition"
        if memory_outcome is None
        else "unknown"
    )

    directive_id = ResearchDirectiveId(UUID(str(operation_id)))
    digest = research_directive_digest(
        directive_id=directive_id,
        workspace_id=workspace_id,
        project_id=project_id,
        product_id=product_id,
        icp_key=icp_key,
        icp_version=icp_version,
        version=version,
        body=body,
        memory_refs=memory_refs,
        source_turn_ref=source_turn_ref,
        predecessor_id=predecessor_id,
    )
    created_at = (
        await conn.execute(
            text(
                "INSERT INTO account_research_directive (directive_id, workspace_id, project_id, "
                "product_id, icp_key, icp_version, version, predecessor_id, content_json, "
                "memory_refs, created_by, source_turn_ref, draft_operation_id, "
                "draft_request_sha256, canonical_json_sha256) VALUES (:directive_id, "
                ":workspace_id, :project_id, "
                ":product_id, :icp_key, :icp_version, :version, :predecessor_id, "
                "CAST(:content_json AS jsonb), CAST(:memory_refs AS jsonb), :created_by, "
                ":source_turn_ref, :operation_id, :request_sha256, :digest) RETURNING created_at"
            ),
            {
                "directive_id": directive_id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "product_id": product_id,
                "icp_key": icp_key,
                "icp_version": icp_version,
                "version": version,
                "predecessor_id": predecessor_id,
                "content_json": body.model_dump_json(),
                "memory_refs": json.dumps(list(memory_refs)),
                "created_by": created_by,
                "source_turn_ref": source_turn_ref,
                "operation_id": operation_id,
                "request_sha256": request_sha256,
                "digest": digest,
            },
        )
    ).scalar_one()
    scope_kind = "explicit" if body.account_scope.explicit_account_ids else "discovery_seal"
    for account_id in resolved_account_ids:
        await conn.execute(
            text(
                "INSERT INTO account_research_directive_account "
                "(directive_id, workspace_id, account_id, scope_kind, selection_ref) "
                "VALUES (:directive_id, :workspace_id, :account_id, :scope_kind, :selection_ref)"
            ),
            {
                "directive_id": directive_id,
                "workspace_id": workspace_id,
                "account_id": account_id,
                "scope_kind": scope_kind,
                "selection_ref": body.account_scope.sealed_selection_ref,
            },
        )
        # FI-2 P1 (spec §2): scoping an account into a directive is a project claiming it as a
        # target, so the membership lands in the directive's own transaction. Idempotent and
        # first-add-wins: an account discovered for this project earlier keeps ``added_via
        # ='discovered'``, and a successor directive re-scoping the same account is a no-op.
        await ensure_project_account(
            conn,
            workspace_id=workspace_id,
            project_id=project_id,
            account_entity_id=account_id,
            added_via="directive",
        )
    if superseded_draft_id is not None:
        await conn.execute(
            text(
                "UPDATE account_research_directive SET status='superseded' "
                "WHERE directive_id=:directive_id AND status='draft'"
            ),
            {"directive_id": superseded_draft_id},
        )
        await conn.execute(
            text(
                "INSERT INTO account_research_directive_event "
                "(event_id, directive_id, workspace_id, event_type, actor_type, actor_ref, "
                "turn_ref, successor_id, operation_id) VALUES (:event_id, :directive_id, "
                ":workspace_id, 'superseded', :actor_type, :actor_ref, :turn_ref, "
                ":successor_id, :operation_id)"
            ),
            {
                "event_id": _event_id(operation_id, superseded_draft_id, "superseded"),
                "directive_id": superseded_draft_id,
                "workspace_id": workspace_id,
                "actor_type": actor_type,
                "actor_ref": created_by,
                "turn_ref": source_turn_ref,
                "successor_id": directive_id,
                "operation_id": operation_id,
            },
        )
    await conn.execute(
        text(
            "INSERT INTO account_research_directive_event "
            "(event_id, directive_id, workspace_id, event_type, actor_type, actor_ref, turn_ref, "
            "operation_id) VALUES (:event_id, :directive_id, :workspace_id, 'drafted', "
            ":actor_type, :actor_ref, :turn_ref, :operation_id)"
        ),
        {
            "event_id": _event_id(operation_id, directive_id, "drafted"),
            "directive_id": directive_id,
            "workspace_id": workspace_id,
            "actor_type": actor_type,
            "actor_ref": created_by,
            "turn_ref": source_turn_ref,
            "operation_id": operation_id,
        },
    )

    overrides: list[ResearchDirectiveAccountOverride] = []
    for account_id, override_body in sorted(
        account_overrides.items(), key=lambda item: str(item[0])
    ):
        override_id = _override_id(directive_id, account_id)
        override_digest = research_directive_override_digest(
            override_id=override_id,
            directive_id=directive_id,
            workspace_id=workspace_id,
            account_id=account_id,
            body=override_body,
            source_turn_ref=source_turn_ref,
        )
        override_created_at = (
            await conn.execute(
                text(
                    "INSERT INTO account_research_directive_override "
                    "(override_id, directive_id, workspace_id, account_id, content_json, "
                    "created_by, source_turn_ref, canonical_json_sha256) VALUES "
                    "(:override_id, :directive_id, :workspace_id, :account_id, "
                    "CAST(:content_json AS jsonb), :created_by, :source_turn_ref, :digest) "
                    "RETURNING created_at"
                ),
                {
                    "override_id": override_id,
                    "directive_id": directive_id,
                    "workspace_id": workspace_id,
                    "account_id": account_id,
                    "content_json": override_body.model_dump_json(),
                    "created_by": created_by,
                    "source_turn_ref": source_turn_ref,
                    "digest": override_digest,
                },
            )
        ).scalar_one()
        overrides.append(
            ResearchDirectiveAccountOverride(
                override_id=override_id,
                directive_id=directive_id,
                workspace_id=workspace_id,
                account_id=account_id,
                body=override_body,
                created_by=created_by,
                source_turn_ref=source_turn_ref,
                canonical_json_sha256=override_digest,
                created_at=override_created_at,
            )
        )

    directive = ResearchDirective(
        directive_id=directive_id,
        workspace_id=workspace_id,
        project_id=project_id,
        product_id=product_id,
        icp_key=icp_key,
        icp_version=icp_version,
        version=version,
        status=ResearchDirectiveStatus.DRAFT,
        body=body,
        memory_refs=memory_refs,
        created_by=created_by,
        source_turn_ref=source_turn_ref,
        predecessor_id=predecessor_id,
        canonical_json_sha256=digest,
        created_at=created_at,
    )
    return DraftedResearchDirective(
        directive=directive,
        overrides=tuple(overrides),
        account_ids=resolved_account_ids,
        memory_outcome=memory_outcome_name,
    )


async def confirm_research_directive(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    directive_id: ResearchDirectiveId,
    expected_sha256: str,
    confirmed_by: str,
    confirming_turn_ref: str,
    operation_id: OperationId,
) -> ResearchDirective:
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
        {"scope": f"research-directive-confirm:{workspace_id}:{directive_id}"},
    )
    directive = await get_research_directive(conn, directive_id, workspace_id=workspace_id)
    if directive is None:
        raise ResearchDirectiveNotFound(str(directive_id))
    if directive.canonical_json_sha256 != expected_sha256:
        raise ResearchDirectiveConflict("confirmation digest differs from the reviewed directive")
    op_row = (
        await conn.execute(
            text(
                "SELECT confirmation_operation_id FROM account_research_directive "
                "WHERE directive_id=:directive_id"
            ),
            {"directive_id": directive_id},
        )
    ).scalar_one()
    if directive.status is ResearchDirectiveStatus.CONFIRMED:
        if op_row == operation_id and await research_directive_confirmation_replay_matches(
            conn,
            workspace_id=workspace_id,
            directive_id=directive_id,
            operation_id=operation_id,
            confirmed_by=confirmed_by,
            confirming_turn_ref=confirming_turn_ref,
        ):
            return directive
        raise ResearchDirectiveConflict(
            "directive was already confirmed by another or different confirmation request"
        )
    if directive.status is not ResearchDirectiveStatus.DRAFT:
        raise ResearchDirectiveConflict("superseded directive cannot be confirmed")

    if directive.predecessor_id is not None:
        predecessor = await get_research_directive(
            conn, directive.predecessor_id, workspace_id=workspace_id
        )
        if predecessor is None or predecessor.status is not ResearchDirectiveStatus.CONFIRMED:
            raise ResearchDirectiveConflict(
                "successor confirmation requires its confirmed predecessor"
            )
        await conn.execute(
            text(
                "UPDATE account_research_directive SET status='superseded' "
                "WHERE directive_id=:directive_id"
            ),
            {"directive_id": predecessor.directive_id},
        )
        await conn.execute(
            text(
                "INSERT INTO account_research_directive_event "
                "(event_id, directive_id, workspace_id, event_type, actor_type, actor_ref, "
                "turn_ref, successor_id, operation_id) VALUES (:event_id, :directive_id, "
                ":workspace_id, 'superseded', 'human', :actor_ref, :turn_ref, :successor_id, "
                ":operation_id)"
            ),
            {
                "event_id": _event_id(operation_id, predecessor.directive_id, "superseded"),
                "directive_id": predecessor.directive_id,
                "workspace_id": workspace_id,
                "actor_ref": confirmed_by,
                "turn_ref": confirming_turn_ref,
                "successor_id": directive_id,
                "operation_id": operation_id,
            },
        )

    confirmed_at = (
        await conn.execute(
            text(
                "UPDATE account_research_directive SET status='confirmed', "
                "confirmation_operation_id=:operation_id, confirmed_by=:confirmed_by, "
                "confirming_turn_ref=:turn_ref, confirmed_at=now() "
                "WHERE directive_id=:directive_id RETURNING confirmed_at"
            ),
            {
                "operation_id": operation_id,
                "confirmed_by": confirmed_by,
                "turn_ref": confirming_turn_ref,
                "directive_id": directive_id,
            },
        )
    ).scalar_one()
    await conn.execute(
        text(
            "INSERT INTO account_research_directive_event "
            "(event_id, directive_id, workspace_id, event_type, actor_type, actor_ref, turn_ref, "
            "operation_id) VALUES (:event_id, :directive_id, :workspace_id, 'confirmed', "
            "'human', :actor_ref, :turn_ref, :operation_id)"
        ),
        {
            "event_id": _event_id(operation_id, directive_id, "confirmed"),
            "directive_id": directive_id,
            "workspace_id": workspace_id,
            "actor_ref": confirmed_by,
            "turn_ref": confirming_turn_ref,
            "operation_id": operation_id,
        },
    )
    return directive.model_copy(
        update={
            "status": ResearchDirectiveStatus.CONFIRMED,
            "confirmed_by": confirmed_by,
            "confirming_turn_ref": confirming_turn_ref,
            "confirmed_at": confirmed_at,
        }
    )


async def effective_account_research_directive(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    directive_id: ResearchDirectiveId,
    account_id: EntityId,
    expected_pin: ResearchDirectivePin | None = None,
    allow_draft: bool = False,
) -> EffectiveAccountResearchDirective:
    """Compose one account's effective direction.

    ``allow_draft`` is FI Lane D D4's pricing relaxation (see
    :func:`clue_core.compose_account_research_directive`): the confirmation gate prices the draft it
    presents with this same composition, so the gate's number and the launcher's verified number
    cannot drift. Every execution path leaves it ``False``.
    """

    directive = await get_research_directive(conn, directive_id, workspace_id=workspace_id)
    if directive is None:
        raise ResearchDirectiveNotFound(str(directive_id))
    member = (
        await conn.execute(
            text(
                "SELECT 1 FROM account_research_directive_account "
                "WHERE directive_id=:directive_id AND workspace_id=:workspace_id "
                "AND account_id=:account_id"
            ),
            {
                "directive_id": directive_id,
                "workspace_id": workspace_id,
                "account_id": account_id,
            },
        )
    ).first()
    if member is None:
        raise ResearchDirectiveInvalid("account is outside the directive's resolved scope")
    override = await get_research_directive_override(
        conn,
        workspace_id=workspace_id,
        directive_id=directive_id,
        account_id=account_id,
    )
    effective = compose_account_research_directive(
        directive,
        account_id=account_id,
        override=override,
        allow_superseded=expected_pin is not None,
        allow_draft=allow_draft,
    )
    if expected_pin is not None and effective.pin != expected_pin:
        raise ResearchDirectiveConflict("stored directive content differs from the execution pin")
    return effective


async def confirmed_directive_account_specs(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    directive_id: ResearchDirectiveId,
) -> tuple[AccountSpec, ...]:
    """Compile one confirmed explicit selection into exact, separately pinned account inputs."""

    directive = await get_research_directive(conn, directive_id, workspace_id=workspace_id)
    if directive is None:
        raise ResearchDirectiveNotFound(str(directive_id))
    if directive.status is not ResearchDirectiveStatus.CONFIRMED:
        raise ResearchDirectiveConflict("only the current confirmed directive can start new work")
    account_ids = tuple(
        EntityId(value)
        for value in (
            await conn.execute(
                text(
                    "SELECT account_id FROM account_research_directive_account "
                    "WHERE directive_id=:directive_id AND workspace_id=:workspace_id "
                    "ORDER BY account_id"
                ),
                {"directive_id": directive_id, "workspace_id": workspace_id},
            )
        ).scalars()
    )
    if not account_ids:
        raise ResearchDirectiveInvalid("confirmed directive has no resolved account membership")
    specs: list[AccountSpec] = []
    for account_id in account_ids:
        effective = await effective_account_research_directive(
            conn,
            workspace_id=workspace_id,
            directive_id=directive_id,
            account_id=account_id,
        )
        specs.append(
            AccountSpec(
                entity_id=account_id,
                tier=effective.effort_policy.tier,
                workspace_id=workspace_id,
                field_keys=effective.field_keys,
                research_directive=effective.pin,
                budget_cap_cents=effective.effort_policy.budget_cap_cents,
            )
        )
    return tuple(specs)


__all__ = [
    "DraftedResearchDirective",
    "ResearchDirectiveConflict",
    "ResearchDirectiveError",
    "ResearchDirectiveInvalid",
    "ResearchDirectiveNotFound",
    "confirm_research_directive",
    "confirmed_directive_account_specs",
    "draft_research_directive",
    "effective_account_research_directive",
    "get_research_directive",
    "get_research_directive_by_operation",
    "get_latest_research_directive",
    "get_research_directive_override",
    "list_research_directive_overrides",
    "research_directive_account_ids",
    "research_directive_confirmation_replay_matches",
    "research_directive_draft_replay_matches",
    "research_directive_draft_request_sha256",
    "resolve_research_directive_accounts",
    "validate_research_directive_draft",
]
