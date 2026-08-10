"""Governed website-mode document tools (Part II slice D6 Round B).

The web plane's durable mutations. Same R-D6-B4 shape as the scene plane: the caller runs the
engine (``web_apply_ops`` / ``web_derive`` — reads that produce a candidate ``WebDoc``) and the
tool governs the write with that output as input.

Web writes already had the CAS the scene writes were missing: ``update_web_document`` has
forwarded ``expected_base_version`` into the DAL since D2.2, which is why the three web routes
already catch ``WebDocumentVersionConflict`` and 409 on it. D6 keeps every one of those bodies
byte-identical — the conflict is raised from inside the tool now, and propagates untouched.

Two callers share ``design_apply_web_operations``: POST /documents/{id}/web/operations (a human
edit, ``actor="human"`` on the invocation, ``actor_kind="editor"`` on the envelope) and the
website-turn worker's persist (``actor="agent"``, ``actor_kind="agent"``). That is REQ-20 parity
— the same governed write, journaled the same way, differing only in who is recorded as having
done it. The worker's operation-replay verification stays in the worker: it is a precondition on
*trusting the agent's own history*, needs the engine, and must stay loud.
"""

from __future__ import annotations

from typing import Any, ClassVar

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
from .documents import DocumentRef, DocumentStateRef, _absent_document, document_failures

__all__ = [
    "ApplyWebOperationsInput",
    "ApplyWebOperationsTool",
    "CreateWebTemplateInput",
    "CreateWebTemplateTool",
    "DeriveWebDocumentInput",
    "DeriveWebDocumentTool",
    "RedoWebDocumentTool",
    "UndoWebDocumentTool",
    "WebHistoryStepInput",
    "apply_web_operations",
]

JsonObject = dict[str, Any]


# ---------------------------------------------------------------------------------------------
# the operation core (one implementation, three tools, four callers)
# ---------------------------------------------------------------------------------------------


def apply_web_operations(
    *,
    repository: Any,
    document_id: str,
    web_doc: JsonObject,
    intent: str | None,
    checkpoint_label: str | None,
    operations: list[JsonObject],
    inverse_operations: list[JsonObject] | None,
    actor_kind: str,
    source: str,
    reverts_batch_id: str | None = None,
    reapplies_batch_id: str | None = None,
    expected_base_version: int | None = None,
) -> DocumentStateRef:
    """The ONE website-document state write."""
    updated = repository.update_web_document(
        document_id,
        web_doc,
        intent=intent,
        checkpoint_label=checkpoint_label,
        operations=operations,
        inverse_operations=inverse_operations,
        actor_kind=actor_kind,
        source=source,
        reverts_batch_id=reverts_batch_id,
        reapplies_batch_id=reapplies_batch_id,
        expected_base_version=expected_base_version,
    )
    return DocumentStateRef(
        document_id=updated["id"],
        current_version=updated["current_version"],
        status=updated["status"],
    )


class _WebAdvanceTool(DesignTool):
    """Shared gate for the web-state advances."""

    _action: ClassVar[str] = "mutate"
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    output_model: ClassVar[type[ToolOutput]] = DocumentStateRef

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        return document_failures(
            self.host.repository(ctx.workspace_id),
            getattr(inputs, "document_id"),
            kind="web",
            draft=True,
            action=self._action,
        )


class ApplyWebOperationsInput(ToolInput):
    document_id: str
    #: The engine's post-apply ``WebDoc``. The ``web_apply_ops`` round-trip is the caller's.
    web_doc: JsonObject
    operations: list[JsonObject]
    inverse_operations: list[JsonObject] | None = None
    intent: str | None = None
    checkpoint_label: str | None = None
    #: ``editor`` for a manual edit, ``agent`` for the website-turn worker's persist.
    actor_kind: str = "editor"
    source: str = "editor"
    #: The turn/edit's base revision. ALWAYS supplied on this path — the whole point of the web
    #: write is that a turn taking minutes cannot clobber a human edit made while it ran.
    expected_base_version: int | None = None


class ApplyWebOperationsTool(_WebAdvanceTool):
    """Commit one engine-applied operation batch onto a website-mode document."""

    name = "design_apply_web_operations"
    version = "1"
    model_description = (
        "Commit an engine-applied website operation batch onto a design website-mode document "
        "under its base revision, appending an undoable history envelope."
    )
    input_model: ClassVar[type[ToolInput]] = ApplyWebOperationsInput
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + document_id + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "each execution bumps current_version and appends an envelope, so a blind retry is "
            "a second edit; expected_base_version is checked under the row lock inside the "
            "write transaction, so a stale retry raises the typed version conflict instead"
        ),
    )
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "actor_kind", "source", "expected_base_version")
    )
    _action: ClassVar[str] = "apply operations"

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, ApplyWebOperationsInput)
        return apply_web_operations(
            repository=self.host.repository(ctx.workspace_id),
            document_id=inputs.document_id,
            web_doc=inputs.web_doc,
            intent=inputs.intent,
            checkpoint_label=inputs.checkpoint_label,
            operations=inputs.operations,
            inverse_operations=inputs.inverse_operations,
            actor_kind=inputs.actor_kind,
            source=inputs.source,
            expected_base_version=inputs.expected_base_version,
        )


class WebHistoryStepInput(ToolInput):
    document_id: str
    web_doc: JsonObject
    operations: list[JsonObject]
    inverse_operations: list[JsonObject] | None = None
    intent: str | None = None
    #: The batch this step moves between the undo and redo stacks.
    batch_id: str
    expected_base_version: int | None = None


class UndoWebDocumentTool(_WebAdvanceTool):
    """Undo the most recent undoable batch on a website-mode document."""

    name = "design_undo_web_document"
    version = "1"
    model_description = (
        "Undo the most recent undoable batch on a design website-mode document, committing the "
        "engine-replayed inverse as a new history envelope."
    )
    input_model: ClassVar[type[ToolInput]] = WebHistoryStepInput
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + document_id + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "undo is a STACK MOVE: a blind retry undoes the next batch too. "
            "expected_base_version (the version the route just read) turns a concurrent "
            "interleaving into a typed conflict rather than a silent double-undo"
        ),
    )
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "batch_id", "expected_base_version")
    )
    _action: ClassVar[str] = "undo"
    _checkpoint_label: ClassVar[str] = "Undo"
    _direction: ClassVar[str] = "reverts"

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, WebHistoryStepInput)
        moves = {f"{self._direction}_batch_id": inputs.batch_id}
        return apply_web_operations(
            repository=self.host.repository(ctx.workspace_id),
            document_id=inputs.document_id,
            web_doc=inputs.web_doc,
            intent=inputs.intent,
            checkpoint_label=self._checkpoint_label,
            operations=inputs.operations,
            inverse_operations=inputs.inverse_operations,
            actor_kind="system",
            source="system",
            expected_base_version=inputs.expected_base_version,
            **moves,
        )


class RedoWebDocumentTool(UndoWebDocumentTool):
    """Re-apply the most recently undone batch on a website-mode document."""

    name = "design_redo_web_document"
    version = "1"
    model_description = (
        "Redo the most recently undone batch on a design website-mode document, re-committing "
        "its forward operations as a new history envelope."
    )
    _action: ClassVar[str] = "redo"
    _checkpoint_label: ClassVar[str] = "Redo"
    _direction: ClassVar[str] = "reapplies"


# ---------------------------------------------------------------------------------------------
# creates
# ---------------------------------------------------------------------------------------------


class CreateWebTemplateInput(ToolInput):
    #: Required: the NEW template document's durable identity (the route mints it and stamps it
    #: into ``web_doc["id"]`` before invoking).
    document_id: str
    web_doc: JsonObject
    account_id: str | None = None


class CreateWebTemplateTool(DesignTool):
    """Clone one website-mode document into a fresh template row."""

    name = "design_create_web_template"
    version = "1"
    model_description = (
        "Save a website-mode design document as a reusable template: a new document row with "
        "empty history, version 0 and the same theme and brand reference."
    )
    input_model: ClassVar[type[ToolInput]] = CreateWebTemplateInput
    output_model: ClassVar[type[ToolOutput]] = DocumentRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + caller-supplied document_id",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "a re-run under any operation id addresses the same row and refuses "
            "design_document_exists; when the HTTP route mints a random id, two requests are "
            "two templates and only a same-operation retry replays"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "account_id")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, CreateWebTemplateInput)
        return _absent_document(self.host.repository(ctx.workspace_id), inputs.document_id)

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, CreateWebTemplateInput)
        template = self.host.repository(ctx.workspace_id).create_web_template(
            inputs.web_doc, inputs.account_id
        )
        return DocumentRef(
            document_id=template["id"],
            title=template["title"],
            current_version=template["current_version"],
            doc_kind=template.get("doc_kind", "web"),
        )


class DeriveWebDocumentInput(ToolInput):
    #: The NEW derived document's id (minted by the caller and already stamped into ``web_doc``
    #: by the engine's ``web_derive``).
    document_id: str
    #: The engine's derived ``WebDoc``. The ``web_derive`` round-trip is the caller's.
    web_doc: JsonObject
    template_document_id: str
    template_doc_version: int
    account_id: str | None = None


class DeriveWebDocumentTool(DesignTool):
    """Persist one personalized derivation of a website-mode template."""

    name = "design_derive_web_document"
    version = "1"
    model_description = (
        "Persist an engine-derived, account-personalized copy of a website-mode design document, "
        "carrying its template lineage and account binding."
    )
    input_model: ClassVar[type[ToolInput]] = DeriveWebDocumentInput
    output_model: ClassVar[type[ToolOutput]] = DocumentRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + caller-supplied document_id",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "a re-run under any operation id addresses the same derived row and refuses "
            "design_document_exists; the batch-derive loop mints a fresh id per account, so "
            "there each account's derivation is its own identity"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=(
            "document_id",
            "template_document_id",
            "template_doc_version",
            "account_id",
        )
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, DeriveWebDocumentInput)
        return _absent_document(self.host.repository(ctx.workspace_id), inputs.document_id)

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, DeriveWebDocumentInput)
        derived = self.host.repository(ctx.workspace_id).create_document(
            inputs.web_doc,
            doc_kind="web",
            template_document_id=inputs.template_document_id,
            template_doc_version=inputs.template_doc_version,
            account_id=inputs.account_id,
        )
        return DocumentRef(
            document_id=derived["id"],
            title=derived["title"],
            current_version=derived["current_version"],
            doc_kind=derived.get("doc_kind", "web"),
        )
