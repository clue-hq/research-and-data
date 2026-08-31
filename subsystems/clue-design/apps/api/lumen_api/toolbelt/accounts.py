"""Governed personalization-account tools (Part II slice D6 Round A — reference domain 2).

Three writes over ``design_account``: create, partial update, delete.

Replay honesty (R-D6-3):

* **create** is ``DOMAIN_IDEMPOTENT`` on the caller-supplied ``account_id``. The tool input makes
  the id **required** — the HTTP route keeps minting ``acc_<uuid4hex>`` when the client omits
  one, exactly as before, but it does so *before* the invocation, so the durable identity a tool
  writes is always one its caller named. That is what turns "create" from an unkeyed write into a
  content-addressed one, and it is why this tool needs no ``operation_id``.
* **update** is ``DOMAIN_IDEMPOTENT``: a partial *assignment*, not an increment, so re-sending the
  same patch converges. (It carries no CAS, so two concurrent partial patches still last-writer-
  win; that is pre-existing and recorded, not introduced here.)
* **delete** is ``OPERATION_IDEMPOTENT``: the second execution of a *new* operation refuses
  ``design_account_not_found`` rather than succeeding, so only a same-operation retry is a no-op.
"""

from __future__ import annotations

from typing import ClassVar

from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolOutput,
)

from .base import DesignTool

__all__ = [
    "CreateWebAccountInput",
    "CreateWebAccountTool",
    "DeleteWebAccountInput",
    "DeleteWebAccountTool",
    "UpdateWebAccountInput",
    "UpdateWebAccountTool",
    "WebAccountDeletionRef",
    "WebAccountRef",
]

_ACCOUNT_PATCH_FIELDS = ("name", "domain", "logo_asset_id", "data", "notes")


class WebAccountRef(ToolOutput):
    account_id: str
    #: The O1 account-spine join, when the account resolved to a platform account entity.
    account_entity_id: str | None


class WebAccountDeletionRef(ToolOutput):
    account_id: str
    deleted: bool


def _logo_failure(repository: object, logo_asset_id: str | None) -> tuple[PreconditionFailure, ...]:
    """The ported ``_require_logo_resolves`` check: a named logo must be a known library asset."""
    from ..database import NotFoundError

    if not logo_asset_id:
        return ()
    try:
        repository.require_asset_record(logo_asset_id)  # type: ignore[attr-defined]
    except NotFoundError:
        return (
            PreconditionFailure(
                reason_code="design_account_logo_unresolved",
                message=f"logo_asset_id {logo_asset_id!r} does not resolve to a known asset",
            ),
        )
    return ()


class CreateWebAccountInput(ToolInput):
    #: Required: the durable identity this write claims. The HTTP route mints one when the
    #: client omits it, so the tool never invents an identity of its own.
    account_id: str
    name: str
    domain: str | None = None
    logo_asset_id: str | None = None
    data: dict[str, str] = {}
    notes: str | None = None


class CreateWebAccountTool(DesignTool):
    """Create one personalization account under a caller-named id."""

    name = "design_create_web_account"
    version = "1"
    model_description = (
        "Create a design personalization account (the per-account variable set a website-mode "
        "template derives against). The account id is the durable identity of the write."
    )
    input_model: ClassVar[type[ToolInput]] = CreateWebAccountInput
    output_model: ClassVar[type[ToolOutput]] = WebAccountRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + caller-supplied account_id",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the id is required, so a re-run under any operation id addresses the same row and "
            "refuses design_account_exists rather than creating a second account"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("account_id", "name", "domain")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, CreateWebAccountInput)
        repository = self.host.repository(ctx.workspace_id)
        if repository.get_web_account(inputs.account_id) is not None:
            return (
                PreconditionFailure(
                    reason_code="design_account_exists",
                    message=f"account {inputs.account_id!r} already exists",
                ),
            )
        return _logo_failure(repository, inputs.logo_asset_id)

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, CreateWebAccountInput)
        repository = self.host.repository(ctx.workspace_id)
        account = repository.create_web_account(
            inputs.account_id,
            inputs.name,
            inputs.domain,
            inputs.logo_asset_id,
            dict(inputs.data),
            inputs.notes,
        )
        return WebAccountRef(
            account_id=account["account_id"],
            account_entity_id=account.get("account_entity_id"),
        )


class UpdateWebAccountInput(ToolInput):
    account_id: str
    #: The already-``exclude_unset``-narrowed patch: only the keys the client actually sent.
    #: A closed key set (``_ACCOUNT_PATCH_FIELDS``) is enforced as a precondition, so a typo'd
    #: key is a loud refusal rather than a silently ignored field.
    patch: dict[str, object]


class UpdateWebAccountTool(DesignTool):
    """Apply one partial update to a personalization account."""

    name = "design_update_web_account"
    version = "1"
    model_description = (
        "Partially update a design personalization account. Only the supplied keys are written."
    )
    input_model: ClassVar[type[ToolInput]] = UpdateWebAccountInput
    output_model: ClassVar[type[ToolOutput]] = WebAccountRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + account_id (a value assignment, not an increment)",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "effect-free by value: re-applying the same patch converges; there is no CAS, so "
            "two concurrent partial patches still last-writer-win (pre-existing)"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("account_id",)
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, UpdateWebAccountInput)
        repository = self.host.repository(ctx.workspace_id)
        if repository.get_web_account(inputs.account_id) is None:
            return (
                PreconditionFailure(
                    reason_code="design_account_not_found",
                    message=f"no account {inputs.account_id!r} in this workspace",
                ),
            )
        unknown = sorted(set(inputs.patch) - set(_ACCOUNT_PATCH_FIELDS))
        if unknown:
            return (
                PreconditionFailure(
                    reason_code="design_account_patch_invalid",
                    message=f"unknown account fields {unknown}",
                ),
            )
        if "logo_asset_id" in inputs.patch:
            logo = inputs.patch["logo_asset_id"]
            return _logo_failure(repository, logo if isinstance(logo, str) else None)
        return ()

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, UpdateWebAccountInput)
        repository = self.host.repository(ctx.workspace_id)
        account = repository.update_web_account(inputs.account_id, dict(inputs.patch))
        return WebAccountRef(
            account_id=account["account_id"],
            account_entity_id=account.get("account_entity_id"),
        )


class DeleteWebAccountInput(ToolInput):
    account_id: str


class DeleteWebAccountTool(DesignTool):
    """Delete one personalization account (its component families cascade with it)."""

    name = "design_delete_web_account"
    version = "1"
    model_description = (
        "Delete a design personalization account. Its custom-component families, source "
        "revisions, artifacts and compilations cascade with it."
    )
    input_model: ClassVar[type[ToolInput]] = DeleteWebAccountInput
    output_model: ClassVar[type[ToolOutput]] = WebAccountDeletionRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + account_id + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "a second execution under a NEW operation refuses design_account_not_found rather "
            "than succeeding, so only a same-operation retry replays"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("account_id",)
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, DeleteWebAccountInput)
        repository = self.host.repository(ctx.workspace_id)
        if repository.get_web_account(inputs.account_id) is None:
            return (
                PreconditionFailure(
                    reason_code="design_account_not_found",
                    message=f"no account {inputs.account_id!r} in this workspace",
                ),
            )
        return ()

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, DeleteWebAccountInput)
        repository = self.host.repository(ctx.workspace_id)
        repository.delete_web_account(inputs.account_id)
        return WebAccountDeletionRef(account_id=inputs.account_id, deleted=True)
