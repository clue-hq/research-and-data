"""Governed scene-document, history and diagnostics tools (Part II slice D6 Round B).

The scene plane's durable mutations, one tool per operation family. Every one of them follows
the **R-D6-B4 shape**: the ROUTE performs the Rust-engine round-trip (``apply_operations`` /
``apply_structured_edit`` / ``preflight_scene`` / ``finalize_template`` — all *reads* that
produce a candidate scene), and the tool governs the durable write with that engine output as
its input. No tool in this module shells out to the engine, so a governed design write is
always exactly one bounded store sequence.

**The CAS (R-D6-B1).** ``HybridRepository.update_document_state`` now forwards
``expected_base_version`` into ``clue_design.documents.update_document_state``, which checks it
under the row lock inside the write transaction. That is what closes the TOCTOU the routes'
handler-level ``require_base_version`` cannot: the pre-check reads the version, the engine
round-trip then runs for hundreds of milliseconds, and only then does the write land. Before D6
a writer that landed inside that window was silently lost; now it is a typed
``DesignVersionConflictError`` → ``WebDocumentVersionConflict`` → the route's existing
``edits.base_version_mismatch`` 409. Tools whose route contract carries no base version pass
``None`` and keep their (documented) last-writer-wins window — D6 does not invent a request
field to close a gap the wire contract cannot express.

Replay honesty (R-D6-B3):

* **state advances** (replace-scene, operations, edits, undo, redo, preflight persist, brand-kit
  attach, diagnostics append) are ``OPERATION_IDEMPOTENT`` with ``operation_id_required``. Each
  one bumps ``current_version`` and appends an envelope, so a blind retry is a second edit; the
  journal's terminal-node replay plus the A9 record are what make a retry safe, and the CAS is
  the *concurrency* truth beside it.
* **creates** (document, snapshot, template revision via finalize) are ``DOMAIN_IDEMPOTENT``
  keyed on the caller-supplied id. The id is REQUIRED on the tool input: the HTTP routes keep
  minting one when the client omits it, but they mint it *before* the invocation, so a tool
  never invents a durable identity. Honest else-branch: when the route mints a random id, two
  requests are two identities and only a same-operation retry (journal + A9) replays — the
  domain key protects a caller who supplies its own id, which is the only caller that can
  meaningfully retry.
"""

from __future__ import annotations

from typing import Any, ClassVar

from clue_obs.otel import get_metric_sink
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
    "ApplyOperationsInput",
    "ApplyOperationsTool",
    "ApplyStructuredEditTool",
    "AttachBrandKitInput",
    "AttachBrandKitTool",
    "CreateDocumentInput",
    "CreateDocumentTool",
    "CreateSnapshotInput",
    "CreateSnapshotTool",
    "DocumentRef",
    "DocumentStateRef",
    "FinalizeDocumentInput",
    "FinalizeDocumentTool",
    "PersistPreflightInput",
    "PersistPreflightTool",
    "RecordDiagnosticsInput",
    "RecordDiagnosticsTool",
    "RedoDocumentTool",
    "RenameDocumentInput",
    "RenameDocumentTool",
    "ReplaceSceneInput",
    "ReplaceSceneTool",
    "SetAgentInstructionsInput",
    "SetAgentInstructionsTool",
    "SetDocumentArchivedInput",
    "SetDocumentArchivedTool",
    "SetLayoutManagedEditingInput",
    "SetLayoutManagedEditingTool",
    "SetWebNoindexInput",
    "SetWebNoindexTool",
    "SnapshotRef",
    "TemplateRevisionRef",
    "ToggleRef",
    "UndoDocumentTool",
    "UndoRedoInput",
    "document_failures",
    "is_finalized_document",
]

JsonObject = dict[str, Any]


# ---------------------------------------------------------------------------------------------
# shared preconditions
# ---------------------------------------------------------------------------------------------
#
# These restate ``main``'s ``require_scene_document`` / ``require_web_document`` /
# ``require_draft_document`` predicates rather than importing them: ``main`` imports the toolbelt,
# never the other way round. ``tests/test_write_path_governance.py`` pins the two statements of
# each predicate equal, exactly as it does for the publish slug pattern.


def scene_status_kind(scene: JsonObject) -> str:
    status = scene.get("meta", {}).get("status", {})
    if isinstance(status, dict):
        return str(status.get("kind", "draft"))
    return str(status)


def is_finalized_document(document: JsonObject) -> bool:
    return document.get("status") == "finalized" or scene_status_kind(
        document.get("scene", {})
    ) == "finalized"


def document_failures(
    repository: Any,
    document_id: str,
    *,
    kind: str | None = None,
    draft: bool = False,
    action: str = "mutate",
) -> tuple[PreconditionFailure, ...]:
    """The one document gate: exists → right kind → still a draft.

    Returns the FIRST failure only, so a caller's refusal maps to exactly one reason code (the
    routes' legacy bodies are one HTTPException each).
    """
    from ..database import NotFoundError

    try:
        document = repository.require_document(document_id)
    except NotFoundError:
        return (
            PreconditionFailure(
                reason_code="design_document_not_found",
                message=f"no design document {document_id!r} in this workspace",
            ),
        )
    actual = document.get("doc_kind", "scene")
    if kind is not None and actual != kind:
        return (
            PreconditionFailure(
                reason_code={
                    "scene": "design_document_not_scene",
                    "web": "design_document_not_web",
                    "site": "design_document_not_site",
                }[kind],
                message=(
                    f"document {document_id} is a {actual!r} document; this "
                    f"endpoint operates only on {kind} documents"
                ),
            ),
        )
    if draft and is_finalized_document(document):
        return (
            PreconditionFailure(
                reason_code="design_document_finalized",
                message=(
                    f"cannot {action} because document {document_id} is finalized; "
                    "create a new draft revision before mutating it"
                ),
            ),
        )
    return ()


def _absent_document(repository: Any, document_id: str) -> tuple[PreconditionFailure, ...]:
    """Refuse a create whose caller-named id is already taken (the DOMAIN key's guard)."""
    from ..database import NotFoundError

    try:
        repository.require_document(document_id)
    except NotFoundError:
        return ()
    return (
        PreconditionFailure(
            reason_code="design_document_exists",
            message=f"document {document_id!r} already exists in this workspace",
        ),
    )


# ---------------------------------------------------------------------------------------------
# typed reference outputs
# ---------------------------------------------------------------------------------------------


class DocumentRef(ToolOutput):
    """A created document row, by reference."""

    document_id: str
    title: str
    current_version: int
    doc_kind: str


class DocumentStateRef(ToolOutput):
    """A document after one state advance. Never the scene — the route re-reads what it needs."""

    document_id: str
    current_version: int
    status: str


class SnapshotRef(ToolOutput):
    snapshot_id: str
    document_id: str
    version: int


class TemplateRevisionRef(ToolOutput):
    template_revision_id: str
    document_id: str
    current_version: int


class ToggleRef(ToolOutput):
    """A per-document flag/text assignment (agent instructions, layout-managed editing)."""

    document_id: str
    field: str
    value: str | bool | None


class DiagnosticsRef(ToolOutput):
    document_id: str
    kind: str
    diagnostic_count: int


# ---------------------------------------------------------------------------------------------
# the operation cores (one implementation per durable shape)
# ---------------------------------------------------------------------------------------------


def _advance_scene_state(
    *,
    repository: Any,
    document_id: str,
    scene: JsonObject,
    diagnostics: list[JsonObject],
    operations: list[JsonObject],
    source: str,
    actor_kind: str,
    actor_id: str | None,
    diagnostic_kind: str,
    effective_brand: tuple[str, JsonObject | None, JsonObject | None] | None,
    envelope: JsonObject | None,
    expected_base_version: int | None,
) -> DocumentStateRef:
    """The ONE scene-state write. Every scene-plane tool below funnels through here."""
    updated = repository.update_document_state(
        document_id,
        scene,
        diagnostics,
        operations,
        source,
        actor_kind,
        actor_id,
        diagnostic_kind,
        effective_brand=effective_brand,
        envelope=envelope,
        expected_base_version=expected_base_version,
    )
    return DocumentStateRef(
        document_id=updated["id"],
        current_version=updated["current_version"],
        status=updated["status"],
    )


def _effective_brand_tuple(
    effective_brand: JsonObject | None,
) -> tuple[str, JsonObject | None, JsonObject | None] | None:
    """The store's positional ``(source, brand_kit, mode)`` from the tool's named object."""
    if effective_brand is None:
        return None
    return (
        str(effective_brand["source"]),
        effective_brand.get("brand_kit"),
        effective_brand.get("mode"),
    )


# ---------------------------------------------------------------------------------------------
# creates
# ---------------------------------------------------------------------------------------------


class CreateDocumentInput(ToolInput):
    #: Required: the durable identity this write claims. The HTTP route mints ``doc_<uuid4hex>``
    #: when the client omits one (and re-derives it from ``scene.meta.id`` for a scene the client
    #: supplied), so the tool never invents an identity of its own.
    document_id: str
    #: The engine's output (``new_scene`` / a validated client scene / ``web_new_doc``).
    scene: JsonObject
    doc_kind: str = "scene"
    brand_kit: JsonObject | None = None
    effective_brand_source: str | None = None


class CreateDocumentTool(DesignTool):
    """Create one design document under a caller-named id."""

    name = "design_create_document"
    version = "1"
    model_description = (
        "Create a design document (scene or website mode) from an engine-produced scene. The "
        "document id is the durable identity of the write; the tool returns references only."
    )
    input_model: ClassVar[type[ToolInput]] = CreateDocumentInput
    output_model: ClassVar[type[ToolOutput]] = DocumentRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + caller-supplied document_id",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the id is required, so a re-run under any operation id addresses the same row and "
            "refuses design_document_exists rather than creating a second document; when the "
            "HTTP route mints a random id, two requests are two identities and only a "
            "same-operation retry replays"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "doc_kind")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, CreateDocumentInput)
        if inputs.doc_kind not in ("scene", "web"):
            return (
                PreconditionFailure(
                    reason_code="design_document_kind_unsupported",
                    message=(
                        f"unsupported doc_kind {inputs.doc_kind!r}; expected 'scene' or 'web'"
                    ),
                ),
            )
        return _absent_document(self.host.repository(ctx.workspace_id), inputs.document_id)

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, CreateDocumentInput)
        repository = self.host.repository(ctx.workspace_id)
        document = repository.create_document(
            inputs.scene,
            brand_kit=inputs.brand_kit,
            effective_brand_source=inputs.effective_brand_source,
            doc_kind=inputs.doc_kind,
        )
        return DocumentRef(
            document_id=document["id"],
            title=document["title"],
            current_version=document["current_version"],
            doc_kind=document.get("doc_kind", inputs.doc_kind),
        )


class CreateSnapshotInput(ToolInput):
    document_id: str
    #: Required for the same reason ``CreateDocumentInput.document_id`` is (the route mints
    #: ``snap_<uuid4hex>`` when the client omits one).
    snapshot_id: str
    reason: str


class CreateSnapshotTool(DesignTool):
    """Snapshot a document's current scene under a caller-named snapshot id."""

    name = "design_create_snapshot"
    version = "1"
    model_description = (
        "Take an explicit full-scene snapshot of a design document. The snapshot id is the "
        "durable identity of the write."
    )
    input_model: ClassVar[type[ToolInput]] = CreateSnapshotInput
    output_model: ClassVar[type[ToolOutput]] = SnapshotRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + caller-supplied snapshot_id",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "a re-run under any operation id addresses the same snapshot row and refuses "
            "design_snapshot_exists rather than appending a second copy of the same scene"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "snapshot_id", "reason")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, CreateSnapshotInput)
        from ..database import NotFoundError

        repository = self.host.repository(ctx.workspace_id)
        if failures := document_failures(repository, inputs.document_id, kind="scene"):
            return failures
        try:
            repository.require_snapshot(inputs.document_id, inputs.snapshot_id)
        except NotFoundError:
            return ()
        return (
            PreconditionFailure(
                reason_code="design_snapshot_exists",
                message=f"snapshot {inputs.snapshot_id!r} already exists on this document",
            ),
        )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, CreateSnapshotInput)
        repository = self.host.repository(ctx.workspace_id)
        snapshot = repository.create_snapshot(
            inputs.document_id, inputs.snapshot_id, inputs.reason
        )
        return SnapshotRef(
            snapshot_id=snapshot["snapshot_id"],
            document_id=snapshot["document_id"],
            version=snapshot["version"],
        )


# ---------------------------------------------------------------------------------------------
# per-document assignments
# ---------------------------------------------------------------------------------------------


class SetAgentInstructionsInput(ToolInput):
    document_id: str
    #: Already normalized by the route (blank ⇒ ``None`` clears them).
    instructions: str | None = None


class SetAgentInstructionsTool(DesignTool):
    """Set (or clear) a document's standing agent instructions."""

    name = "design_set_agent_instructions"
    version = "1"
    model_description = (
        "Set or clear the per-document standing instructions the design agent receives with "
        "every turn."
    )
    input_model: ClassVar[type[ToolInput]] = SetAgentInstructionsInput
    output_model: ClassVar[type[ToolOutput]] = ToggleRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + document_id (design_document.agent_instructions)",
        external_boundary=ExternalReplayBoundary.NONE,
        notes="effect-free by value: assigning the same instructions twice converges",
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id",)
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, SetAgentInstructionsInput)
        return document_failures(
            self.host.repository(ctx.workspace_id), inputs.document_id, kind="scene"
        )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, SetAgentInstructionsInput)
        document = self.host.repository(ctx.workspace_id).set_agent_instructions(
            inputs.document_id, inputs.instructions
        )
        return ToggleRef(
            document_id=inputs.document_id,
            field="agent_instructions",
            value=document["agent_instructions"],
        )


class SetLayoutManagedEditingInput(ToolInput):
    document_id: str
    enabled: bool


class SetLayoutManagedEditingTool(DesignTool):
    """Toggle a document's advanced opt-out from handoff-absolute layout freezing."""

    name = "design_set_layout_managed_editing"
    version = "1"
    model_description = (
        "Enable or disable layout-managed editing on a design document (the advanced opt-out "
        "from the editor's two layout-freeze seams)."
    )
    input_model: ClassVar[type[ToolInput]] = SetLayoutManagedEditingInput
    output_model: ClassVar[type[ToolOutput]] = ToggleRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + document_id (design_document.layout_managed_editing)",
        external_boundary=ExternalReplayBoundary.NONE,
        notes="effect-free by value: assigning the same flag twice converges",
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "enabled")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, SetLayoutManagedEditingInput)
        return document_failures(
            self.host.repository(ctx.workspace_id), inputs.document_id, kind="scene"
        )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, SetLayoutManagedEditingInput)
        document = self.host.repository(ctx.workspace_id).set_layout_managed_editing(
            inputs.document_id, inputs.enabled
        )
        return ToggleRef(
            document_id=inputs.document_id,
            field="layout_managed_editing",
            value=document["layout_managed_editing"],
        )


class SetWebNoindexInput(ToolInput):
    document_id: str
    #: REQUIRED, with no default, and that is the whole of ruling R-F1's "removing it requires an
    #: explicit action": a caller who does not name a value cannot reach this tool at all.
    enabled: bool


class SetWebNoindexTool(DesignTool):
    """Stamp or explicitly clear one web document's durable ``noindex`` (ruling R-F1)."""

    name = "design_set_web_noindex"
    version = "1"
    model_description = (
        "Stamp or clear the durable noindex flag on a website-mode design document. A stamped "
        "page emits <meta name=\"robots\" content=\"noindex\"> on EVERY publish, whichever route "
        "publishes it; clearing it is this call and nothing else."
    )
    input_model: ClassVar[type[ToolInput]] = SetWebNoindexInput
    output_model: ClassVar[type[ToolOutput]] = ToggleRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + document_id (design_document.web_noindex)",
        external_boundary=ExternalReplayBoundary.NONE,
        notes="effect-free by value: assigning the same flag twice converges",
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "enabled")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, SetWebNoindexInput)
        # `kind="web"`, unlike its two scene-side neighbours: a scene document has no publish
        # surface, so the flag stored on one would be a fact about nothing.
        return document_failures(
            self.host.repository(ctx.workspace_id), inputs.document_id, kind="web"
        )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, SetWebNoindexInput)
        document = self.host.repository(ctx.workspace_id).set_web_noindex(
            inputs.document_id, inputs.enabled
        )
        return ToggleRef(
            document_id=inputs.document_id,
            field="web_noindex",
            value=document["web_noindex"],
        )


class RenameDocumentInput(ToolInput):
    document_id: str
    title: str


class RenameDocumentTool(DesignTool):
    """Rename one document — row title and document JSON title together, version bumped."""

    name = "design_rename_document"
    version = "1"
    model_description = (
        "Rename a design document. Writes the title on the row AND inside the document JSON so "
        "the next save cannot revert it, and advances the document version."
    )
    input_model: ClassVar[type[ToolInput]] = RenameDocumentInput
    output_model: ClassVar[type[ToolOutput]] = ToggleRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + document_id (design_document.title)",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "assigning the same title twice converges on the title; the version advances each time"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "title")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, RenameDocumentInput)
        if not inputs.title.strip():
            return (
                PreconditionFailure(
                    reason_code="design_document_title_blank",
                    message="a document title must not be blank",
                ),
            )
        # Both kinds rename; a finalized document is frozen against every mutation.
        return document_failures(
            self.host.repository(ctx.workspace_id), inputs.document_id, draft=True, action="rename"
        )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, RenameDocumentInput)
        document = self.host.repository(ctx.workspace_id).rename_document(
            inputs.document_id, inputs.title
        )
        get_metric_sink().add(
            "design.document.renamed", 1, {"doc_kind": str(document.get("doc_kind", "scene"))}
        )
        return ToggleRef(document_id=inputs.document_id, field="title", value=document["title"])


class SetDocumentArchivedInput(ToolInput):
    document_id: str
    #: REQUIRED, no default: a caller who names no value cannot reach the tool (the noindex rule).
    enabled: bool


class SetDocumentArchivedTool(DesignTool):
    """Archive or restore one document — a library/gallery state, independent of publish."""

    name = "design_set_document_archived"
    version = "1"
    model_description = (
        "Archive or restore a design document. An archived document leaves the project gallery "
        "and the artifacts library's default view; publishing is unaffected."
    )
    input_model: ClassVar[type[ToolInput]] = SetDocumentArchivedInput
    output_model: ClassVar[type[ToolOutput]] = ToggleRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + document_id (design_document.archived_at)",
        external_boundary=ExternalReplayBoundary.NONE,
        notes="effect-free by value: archiving twice keeps the first timestamp",
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "enabled")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, SetDocumentArchivedInput)
        return document_failures(self.host.repository(ctx.workspace_id), inputs.document_id)

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, SetDocumentArchivedInput)
        document = self.host.repository(ctx.workspace_id).set_document_archived(
            inputs.document_id, inputs.enabled
        )
        get_metric_sink().add(
            "design.document.archived", 1, {"enabled": "true" if inputs.enabled else "false"}
        )
        return ToggleRef(
            document_id=inputs.document_id, field="archived_at", value=document["archived_at"]
        )


# ---------------------------------------------------------------------------------------------
# scene state advances
# ---------------------------------------------------------------------------------------------


class ReplaceSceneInput(ToolInput):
    document_id: str
    #: The engine-VALIDATED scene (``core.validate_scene``'s output), never the raw payload.
    scene: JsonObject
    diagnostics: list[JsonObject] = []
    #: PUT /documents/{id}/scene's request contract carries no base version, so its route passes
    #: ``None`` and keeps its last-writer-wins window (documented at the route). A non-HTTP
    #: caller that holds a version gets the in-transaction CAS.
    expected_base_version: int | None = None


class ReplaceSceneTool(DesignTool):
    """Replace a scene document's whole scene (version + 1)."""

    name = "design_replace_scene"
    version = "1"
    model_description = (
        "Replace a design document's entire scene with an engine-validated one. Version-bumping "
        "and not idempotent by value — supply an operation id."
    )
    input_model: ClassVar[type[ToolInput]] = ReplaceSceneInput
    output_model: ClassVar[type[ToolOutput]] = DocumentStateRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + document_id + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "each execution bumps current_version, so a blind retry is a second replace; "
            "expected_base_version (when the caller has one) is the concurrency truth"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "expected_base_version")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, ReplaceSceneInput)
        return document_failures(
            self.host.repository(ctx.workspace_id),
            inputs.document_id,
            kind="scene",
            draft=True,
            action="replace the current scene",
        )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, ReplaceSceneInput)
        updated = self.host.repository(ctx.workspace_id).replace_scene(
            inputs.document_id,
            inputs.scene,
            inputs.diagnostics,
            expected_base_version=inputs.expected_base_version,
        )
        return DocumentStateRef(
            document_id=updated["id"],
            current_version=updated["current_version"],
            status=updated["status"],
        )


class ApplyOperationsInput(ToolInput):
    document_id: str
    #: The engine's post-apply scene. The engine round-trip is the ROUTE's (R-D6-B4).
    scene: JsonObject
    diagnostics: list[JsonObject] = []
    operations: list[JsonObject]
    source: str
    actor_kind: str
    actor_id: str | None = None
    envelope: JsonObject | None = None
    expected_base_version: int | None = None


class _SceneAdvanceTool(DesignTool):
    """Shared body for the scene-state advances that differ only in name and envelope."""

    _diagnostic_kind: ClassVar[str] = "structural"
    _action: ClassVar[str] = "mutate"
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        document_id = getattr(inputs, "document_id")
        return document_failures(
            self.host.repository(ctx.workspace_id),
            document_id,
            kind="scene",
            draft=True,
            action=self._action,
        )


class ApplyOperationsTool(_SceneAdvanceTool):
    """Commit one engine-applied operation batch onto a scene document."""

    name = "design_apply_operations"
    version = "1"
    model_description = (
        "Commit an engine-applied operation batch onto a design scene document, appending its "
        "undoable history envelope. Returns the new version, never the scene."
    )
    input_model: ClassVar[type[ToolInput]] = ApplyOperationsInput
    output_model: ClassVar[type[ToolOutput]] = DocumentStateRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + document_id + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "each execution advances current_version by len(operations) and appends an "
            "envelope, so a blind retry double-applies; expected_base_version is checked "
            "inside the write transaction and is the concurrency truth"
        ),
    )
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "source", "actor_kind", "expected_base_version")
    )
    _action: ClassVar[str] = "apply operations"

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, ApplyOperationsInput)
        return _advance_scene_state(
            repository=self.host.repository(ctx.workspace_id),
            document_id=inputs.document_id,
            scene=inputs.scene,
            diagnostics=inputs.diagnostics,
            operations=inputs.operations,
            source=inputs.source,
            actor_kind=inputs.actor_kind,
            actor_id=inputs.actor_id,
            diagnostic_kind=self._diagnostic_kind,
            effective_brand=None,
            envelope=inputs.envelope,
            expected_base_version=inputs.expected_base_version,
        )


class ApplyStructuredEditTool(ApplyOperationsTool):
    """Commit one engine-lowered structured edit onto a scene document.

    Distinct from ``design_apply_operations`` in the journal (a structured edit is a different
    authoring gesture — it carries its own ``edit`` lineage and the editor surfaces it as one),
    identical in durable shape, so it shares the body verbatim.
    """

    name = "design_apply_edits"
    version = "1"
    model_description = (
        "Commit the canonical operations an engine-lowered structured edit produced onto a "
        "design scene document."
    )
    _action: ClassVar[str] = "apply structured edit"


class UndoRedoInput(ToolInput):
    document_id: str
    #: The engine's post-replay scene (the inverse batch for undo, the forward batch for redo).
    scene: JsonObject
    diagnostics: list[JsonObject] = []
    operations: list[JsonObject]
    #: Carries ``intent`` + ``reverts_batch_id`` / ``reapplies_batch_id`` + the swapped
    #: ``inverse_operations``; the DAL reads those to move the batch between the undo and redo
    #: stacks.
    envelope: JsonObject
    expected_base_version: int | None = None


class UndoDocumentTool(_SceneAdvanceTool):
    """Apply one document-level undo as a new appended envelope."""

    name = "design_undo_document"
    version = "1"
    model_description = (
        "Undo the most recent undoable batch on a design scene document by committing its "
        "engine-replayed inverse as a new history envelope."
    )
    input_model: ClassVar[type[ToolInput]] = UndoRedoInput
    output_model: ClassVar[type[ToolOutput]] = DocumentStateRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + document_id + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "undo is a STACK MOVE: a blind retry undoes the next batch too. The route reverts "
            "to a checkpoint by invoking this tool once per pending batch, each with its own "
            "operation id and its own base version"
        ),
    )
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "expected_base_version")
    )
    _diagnostic_kind: ClassVar[str] = "structural"
    _action: ClassVar[str] = "undo"

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, UndoRedoInput)
        return _advance_scene_state(
            repository=self.host.repository(ctx.workspace_id),
            document_id=inputs.document_id,
            scene=inputs.scene,
            diagnostics=inputs.diagnostics,
            operations=inputs.operations,
            source="system",
            actor_kind="system",
            actor_id="history",
            diagnostic_kind=self._diagnostic_kind,
            effective_brand=None,
            envelope=inputs.envelope,
            expected_base_version=inputs.expected_base_version,
        )


class RedoDocumentTool(UndoDocumentTool):
    """Re-apply the most recently undone batch (the mirror of ``design_undo_document``)."""

    name = "design_redo_document"
    version = "1"
    model_description = (
        "Redo the most recently undone batch on a design scene document by re-committing its "
        "forward operations as a new history envelope."
    )
    _action: ClassVar[str] = "redo"


class PersistPreflightInput(ToolInput):
    document_id: str
    #: The preflight-resolved scene.
    scene: JsonObject
    diagnostics: list[JsonObject] = []
    #: The brand-ref + token + layout operations preflight produced (possibly empty, in which
    #: case the DAL leaves ``current_version`` alone and only the diagnostics land).
    operations: list[JsonObject] = []
    #: ``"preflight"`` (POST /preflight) or ``"export_preflight"`` (POST /export's persist half).
    #: This is the envelope's ``actor_id`` — the system sub-actor that resolved the scene — and
    #: it is the ONE difference between the two routes' writes (both write ``source="system"``,
    #: ``actor_kind="system"``, ``diagnostic_kind="preflight"``).
    actor_id: str = "preflight"
    #: ``{"source": ..., "brand_kit": ..., "mode": ...}`` when the caller asked to persist the
    #: effective brand, else absent.
    effective_brand: JsonObject | None = None
    expected_base_version: int | None = None


class PersistPreflightTool(_SceneAdvanceTool):
    """Persist one preflight resolution onto a scene document (POST /preflight and /export)."""

    name = "design_persist_preflight"
    version = "1"
    model_description = (
        "Persist an engine preflight's resolved scene, operations, diagnostics and effective "
        "brand onto a design scene document."
    )
    input_model: ClassVar[type[ToolInput]] = PersistPreflightInput
    output_model: ClassVar[type[ToolOutput]] = DocumentStateRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + document_id + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "a preflight that produced operations advances current_version, so a blind retry "
            "re-applies them; one that produced none only appends diagnostics"
        ),
    )
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "actor_id", "expected_base_version")
    )
    _diagnostic_kind: ClassVar[str] = "preflight"
    _action: ClassVar[str] = "preflight the current scene"

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, PersistPreflightInput)
        if inputs.actor_id not in ("preflight", "export_preflight"):
            return (
                PreconditionFailure(
                    reason_code="design_preflight_actor_invalid",
                    message=(
                        f"unsupported preflight actor {inputs.actor_id!r}; expected "
                        "'preflight' or 'export_preflight'"
                    ),
                ),
            )
        return super().check(inputs, ctx)

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, PersistPreflightInput)
        return _advance_scene_state(
            repository=self.host.repository(ctx.workspace_id),
            document_id=inputs.document_id,
            scene=inputs.scene,
            diagnostics=inputs.diagnostics,
            operations=inputs.operations,
            source="system",
            actor_kind="system",
            actor_id=inputs.actor_id,
            diagnostic_kind=self._diagnostic_kind,
            effective_brand=_effective_brand_tuple(inputs.effective_brand),
            envelope=None,
            expected_base_version=inputs.expected_base_version,
        )


class AttachBrandKitInput(ToolInput):
    document_id: str
    scene: JsonObject
    diagnostics: list[JsonObject] = []
    operations: list[JsonObject]
    actor_kind: str
    actor_id: str | None = None
    #: Always ``{"source": "brand_kit_library", "brand_kit": ..., "mode": ...}`` on this path.
    effective_brand: JsonObject
    expected_base_version: int | None = None


class AttachBrandKitTool(_SceneAdvanceTool):
    """Attach a library Brand Kit to a scene document as its effective brand."""

    name = "design_attach_brand_kit"
    version = "1"
    model_description = (
        "Attach a Brand Kit library revision to a design scene document, committing the engine's "
        "brand-update operation and recording the kit as the document's effective brand."
    )
    input_model: ClassVar[type[ToolInput]] = AttachBrandKitInput
    output_model: ClassVar[type[ToolOutput]] = DocumentStateRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + document_id + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the effective-brand columns converge by value, but the write also commits an "
            "operation batch and appends an envelope, so a blind retry is a second edit"
        ),
    )
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "actor_kind", "expected_base_version")
    )
    _action: ClassVar[str] = "attach a Brand Kit"

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, AttachBrandKitInput)
        return _advance_scene_state(
            repository=self.host.repository(ctx.workspace_id),
            document_id=inputs.document_id,
            scene=inputs.scene,
            diagnostics=inputs.diagnostics,
            operations=inputs.operations,
            source="api",
            actor_kind=inputs.actor_kind,
            actor_id=inputs.actor_id,
            diagnostic_kind=self._diagnostic_kind,
            effective_brand=_effective_brand_tuple(inputs.effective_brand),
            envelope=None,
            expected_base_version=inputs.expected_base_version,
        )


# ---------------------------------------------------------------------------------------------
# finalize (two writes, one inseparable operation)
# ---------------------------------------------------------------------------------------------


class FinalizeDocumentInput(ToolInput):
    document_id: str
    #: Required: the durable identity. The route mints ``tmpl_<uuid4hex>`` when the client omits
    #: one, and the engine has already stamped it into ``scene``, so the tool cannot re-derive it.
    template_revision_id: str
    source_snapshot_id: str | None = None
    #: The engine's finalized scene and the slot summary read off it.
    scene: JsonObject
    slot_summary: list[JsonObject] = []
    diagnostics: list[JsonObject] = []
    actor_kind: str
    actor_id: str | None = None
    expected_base_version: int | None = None


class FinalizeDocumentTool(DesignTool):
    """Freeze one scene document into an immutable template revision."""

    name = "design_finalize_document"
    version = "1"
    model_description = (
        "Finalize a design scene document: write the immutable template revision the "
        "personalization plane derives against and move the document to the finalized state."
    )
    input_model: ClassVar[type[ToolInput]] = FinalizeDocumentInput
    output_model: ClassVar[type[ToolOutput]] = TemplateRevisionRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + caller-supplied template_revision_id",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "two writes, one operation: the revision row and the document's finalize state "
            "advance. The revision id is the domain key, so a re-run under a NEW operation id "
            "refuses design_template_revision_exists rather than bumping the version twice; "
            "when the route mints a random id, only a same-operation retry replays"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "template_revision_id", "source_snapshot_id")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, FinalizeDocumentInput)
        from ..database import NotFoundError

        repository = self.host.repository(ctx.workspace_id)
        if failures := document_failures(
            repository,
            inputs.document_id,
            kind="scene",
            draft=True,
            action="finalize the document",
        ):
            return failures
        try:
            repository.require_template_revision(inputs.template_revision_id)
        except NotFoundError:
            return ()
        return (
            PreconditionFailure(
                reason_code="design_template_revision_exists",
                message=(
                    f"template revision {inputs.template_revision_id!r} already exists in "
                    "this workspace"
                ),
            ),
        )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, FinalizeDocumentInput)
        repository = self.host.repository(ctx.workspace_id)
        repository.create_template_revision(
            inputs.document_id,
            inputs.template_revision_id,
            inputs.source_snapshot_id,
            inputs.scene,
            inputs.slot_summary,
        )
        state = _advance_scene_state(
            repository=repository,
            document_id=inputs.document_id,
            scene=inputs.scene,
            diagnostics=inputs.diagnostics,
            operations=[
                {
                    "kind": "finalize_template",
                    "template_revision_id": inputs.template_revision_id,
                }
            ],
            source="system",
            actor_kind=inputs.actor_kind,
            actor_id=inputs.actor_id,
            diagnostic_kind="finalize",
            effective_brand=None,
            envelope=None,
            expected_base_version=inputs.expected_base_version,
        )
        return TemplateRevisionRef(
            template_revision_id=inputs.template_revision_id,
            document_id=inputs.document_id,
            current_version=state.current_version,
        )


# ---------------------------------------------------------------------------------------------
# diagnostics
# ---------------------------------------------------------------------------------------------


class RecordDiagnosticsInput(ToolInput):
    document_id: str
    #: ``structural`` | ``preflight`` | ``export`` | ``brand_governance`` | ``finalize`` —
    #: the append's report kind, closed by a precondition so a typo is a loud refusal.
    kind: str
    diagnostics: list[JsonObject] = []


class RecordDiagnosticsTool(DesignTool):
    """Append one diagnostics report to a document's append-only diagnostics log.

    **Deviation from the suggested inventory, argued.** R-D6-B2 suggested
    ``design_record_brand_governance``. Brand governance is one *caller* of this write, not its
    family: ``store_diagnostics`` is a single append-only mutation that six call sites share
    (structural-validation failure on PUT /scene, the preflight error branch, both export
    branches, brand governance, and finalize's core-error branch). Naming the tool after one
    caller would have left the other five either ungoverned — the D6 gate is "EVERY design
    mutation behind a tool" — or governed by a tool whose name lies about what it writes. One
    kind-parameterized tool is the honest one-tool-per-operation-family reading.
    """

    name = "design_record_diagnostics"
    version = "1"
    model_description = (
        "Append a diagnostics report (structural, preflight, export, brand-governance or "
        "finalize) to a design document's append-only diagnostics log."
    )
    input_model: ClassVar[type[ToolInput]] = RecordDiagnosticsInput
    output_model: ClassVar[type[ToolOutput]] = DiagnosticsRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + document_id + kind + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "design_document_diagnostic is APPEND-ONLY (reads take the latest row per kind), so "
            "a blind retry appends a second identical report; the latest-per-kind read makes "
            "that harmless but it is not a no-op, so the honest policy is operation-keyed"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "kind")
    )

    #: The closed set of report kinds the design tree writes.
    KINDS: ClassVar[tuple[str, ...]] = (
        "structural",
        "preflight",
        "export",
        "brand_governance",
        "finalize",
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, RecordDiagnosticsInput)
        if inputs.kind not in self.KINDS:
            return (
                PreconditionFailure(
                    reason_code="design_diagnostics_kind_invalid",
                    message=(
                        f"unknown diagnostics kind {inputs.kind!r}; expected one of "
                        f"{list(self.KINDS)}"
                    ),
                ),
            )
        return document_failures(self.host.repository(ctx.workspace_id), inputs.document_id)

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, RecordDiagnosticsInput)
        self.host.repository(ctx.workspace_id).store_diagnostics(
            inputs.document_id, inputs.kind, inputs.diagnostics
        )
        return DiagnosticsRef(
            document_id=inputs.document_id,
            kind=inputs.kind,
            diagnostic_count=len(inputs.diagnostics),
        )
