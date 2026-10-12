"""Governed Puck site writes (Wave 2 Lane A, Contract 2).

Three tools over one store write (``HybridRepository.update_site_document``):

* ``design_write_site`` — a whole-site save. A manual save (route, ``actor="human"``,
  ``actor_kind="editor"``) and an agent turn's persist (Lane B5, ``actor="agent"``,
  ``actor_kind="agent"``) both go through it, so one save and one turn are each ONE undo step.
  It checks the site's contracts first (shape, custody, the site-kit validator) and refuses with
  ``SiteDocumentInvalid``; nothing is written then. A restore passes ``restore_of``, and the tool
  lets it reinstate exactly that snapshot's agent sections.
* ``design_undo_site`` / ``design_redo_site`` — one stack move. History is whole-site snapshots:
  a batch's ``operations`` carry the site it installed and its ``inverse_operations`` the site it
  replaced, so an undo reinstalls the inverse and a redo the forward snapshot, with no replay.

The CAS is ``expected_base_version``, checked under the row lock inside the write.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

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
from .documents import DocumentStateRef, document_failures

__all__ = [
    "REPLACE_SITE",
    "RedoSiteTool",
    "SiteHistoryEmpty",
    "SiteHistoryInput",
    "SiteHistoryRef",
    "UndoSiteTool",
    "WriteSiteInput",
    "WriteSiteTool",
    "replace_site_payload",
    "step_site_history",
    "write_site_document",
]

JsonObject = dict[str, Any]
REPLACE_SITE = "replace_site"


def replace_site_payload(operations: Any) -> JsonObject | None:
    """The site a ``[{"kind": "replace_site", "site": …}]`` batch carries, else None."""
    if (
        isinstance(operations, list)
        and len(operations) == 1
        and isinstance(operations[0], dict)
        and operations[0].get("kind") == REPLACE_SITE
        and isinstance(operations[0].get("site"), dict)
    ):
        return operations[0]["site"]
    return None


class SiteHistoryEmpty(Exception):
    """Nothing to undo (or redo) on this site."""

    def __init__(self, direction: str) -> None:
        super().__init__(f"no {'undoable' if direction == 'undo' else 'redoable'} batches in document history")
        self.direction = direction


class SiteHistoryRef(ToolOutput):
    document_id: str
    current_version: int
    status: str
    #: The batch this step moved between the undo and redo stacks.
    batch_id: str


def write_site_document(
    *,
    repository: Any,
    blobs: Any,
    node_bin: str,
    brand_loader: Any,
    section_loader: Any,
    document_id: str,
    site: Any,
    intent: str | None,
    checkpoint_label: str | None,
    actor_kind: str,
    source: str,
    expected_base_version: int,
    restore_of: str | None = None,
) -> DocumentStateRef:
    """THE site save: check the contracts, then write one whole-site snapshot."""
    from ..site_doc_inputs import load_section_modules
    from ..site_doc_validate import SiteDocumentInvalid, check_site_document, prepare_site_for_write
    from ..site_render import SECTION_MODULE_MISSING, SiteRenderError

    document = repository.require_document(document_id)
    restoring = False
    if restore_of is not None:
        snapshot = replace_site_payload(repository.require_envelope(document_id, restore_of)["operations"])
        if snapshot is None or snapshot != site:
            raise SiteDocumentInvalid([f"restore_of: batch {restore_of} does not hold this site"])
        restoring = True
    prepared, errors = prepare_site_for_write(document, site, allow_new_sections=actor_kind == "agent" or restoring)
    if errors:
        raise SiteDocumentInvalid(errors)
    try:
        sections = load_section_modules(section_loader, repository, blobs, prepared)
    except SiteRenderError as error:
        if error.code == SECTION_MODULE_MISSING:
            raise SiteDocumentInvalid([f"agent_sections: {error.message}"]) from error
        raise
    errors = check_site_document(
        prepared,
        document_id=document_id,
        brand=brand_loader(repository, blobs, document),
        sections=sections,
        blobs=blobs,
        node_bin=node_bin,
    )
    if errors:
        raise SiteDocumentInvalid(errors)
    updated = repository.update_site_document(
        document_id,
        prepared,
        intent=intent,
        checkpoint_label=checkpoint_label,
        operations=[{"kind": REPLACE_SITE, "site": prepared}],
        inverse_operations=[{"kind": REPLACE_SITE, "site": document["scene"]}],
        actor_kind=actor_kind,
        source=source,
        expected_base_version=expected_base_version,
    )
    return DocumentStateRef(
        document_id=updated["id"], current_version=updated["current_version"], status=updated["status"]
    )


def step_site_history(
    *, repository: Any, document_id: str, direction: Literal["undo", "redo"], expected_base_version: int
) -> SiteHistoryRef:
    """One undo or redo: reinstall the snapshot the stack's top batch names."""
    document = repository.require_document(document_id)
    stack = list(document.get("undo_stack" if direction == "undo" else "redo_stack") or [])
    if not stack:
        raise SiteHistoryEmpty(direction)
    target = repository.require_envelope(document_id, stack[-1])
    restored = replace_site_payload(target["inverse_operations"] if direction == "undo" else target["operations"])
    if restored is None:
        raise SiteHistoryEmpty(direction)
    moves = {"reverts_batch_id": target["batch_id"]} if direction == "undo" else {"reapplies_batch_id": target["batch_id"]}
    updated = repository.update_site_document(
        document_id,
        restored,
        intent=f"{direction}:{target['intent'] or target['batch_id']}",
        checkpoint_label="Undo" if direction == "undo" else "Redo",
        operations=[{"kind": REPLACE_SITE, "site": restored}],
        inverse_operations=[{"kind": REPLACE_SITE, "site": document["scene"]}],
        actor_kind="system",
        source="system",
        expected_base_version=expected_base_version,
        **moves,
    )
    return SiteHistoryRef(
        document_id=updated["id"], current_version=updated["current_version"], status=updated["status"], batch_id=target["batch_id"]
    )


class WriteSiteInput(ToolInput):
    document_id: str
    #: The whole site document (Contract 1). The stored theme always wins over the one sent.
    site: JsonObject
    intent: str | None = None
    checkpoint_label: str | None = None
    #: ``editor`` for a manual save, ``agent`` for a site turn's persist (Lane B5).
    actor_kind: str = "editor"
    source: str = "editor"
    #: Set by the restore route: the batch whose snapshot this write reinstalls. The tool re-reads that snapshot itself and allows its agent sections only when ``site`` is exactly it.
    restore_of: str | None = None
    #: The version the save was made from. Required: a turn taking minutes must never clobber a save.
    expected_base_version: int


class SiteHistoryInput(ToolInput):
    document_id: str
    expected_base_version: int


_REPLAY = ReplaySafety(
    policy=ReplayPolicy.OPERATION_IDEMPOTENT,
    durable_identity="workspace + document_id + ToolContext.operation_id",
    operation_id_required=True,
    external_boundary=ExternalReplayBoundary.NONE,
    notes=(
        "each execution bumps current_version and appends an envelope, so a blind retry is a "
        "second write; expected_base_version is checked under the row lock inside the write "
        "transaction, so a stale retry raises the typed version conflict instead"
    ),
)


class WriteSiteTool(DesignTool):
    """Save a whole Puck site document as one undoable step."""

    name = "design_write_site"
    version = "1"
    model_description = (
        "Save a whole Puck site document under its base version after its contract checks, "
        "appending one undoable history step."
    )
    input_model: ClassVar[type[ToolInput]] = WriteSiteInput
    output_model: ClassVar[type[ToolOutput]] = DocumentStateRef
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    replay: ClassVar[ReplaySafety] = _REPLAY
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "actor_kind", "source", "expected_base_version")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, WriteSiteInput)
        return document_failures(
            self.host.repository(ctx.workspace_id), inputs.document_id, kind="site", draft=True, action="save the site"
        )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, WriteSiteInput)
        return write_site_document(
            repository=self.host.repository(ctx.workspace_id),
            blobs=self.host.blobs(ctx.workspace_id),
            node_bin=self.host.need("web_export_node_bin"),
            brand_loader=self.host.need("site_brand_loader"),
            section_loader=self.host.need("site_section_loader"),
            document_id=inputs.document_id,
            site=inputs.site,
            intent=inputs.intent,
            checkpoint_label=inputs.checkpoint_label,
            actor_kind=inputs.actor_kind,
            source=inputs.source,
            expected_base_version=inputs.expected_base_version,
            restore_of=inputs.restore_of,
        )


class UndoSiteTool(DesignTool):
    """Undo the most recent step on a Puck site document."""

    name = "design_undo_site"
    version = "1"
    model_description = "Undo the most recent step on a Puck site document, reinstalling the site it replaced."
    input_model: ClassVar[type[ToolInput]] = SiteHistoryInput
    output_model: ClassVar[type[ToolOutput]] = SiteHistoryRef
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    replay: ClassVar[ReplaySafety] = _REPLAY
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("document_id", "expected_base_version")
    )
    _direction: ClassVar[Literal["undo", "redo"]] = "undo"

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, SiteHistoryInput)
        repository = self.host.repository(ctx.workspace_id)
        failures = document_failures(repository, inputs.document_id, kind="site", draft=True, action=self._direction)
        if failures:
            return failures
        document = repository.require_document(inputs.document_id)
        if not (document.get("undo_stack" if self._direction == "undo" else "redo_stack") or []):
            return (
                PreconditionFailure(
                    reason_code=f"site_{self._direction}_empty",
                    message=str(SiteHistoryEmpty(self._direction)),
                ),
            )
        return ()

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, SiteHistoryInput)
        return step_site_history(
            repository=self.host.repository(ctx.workspace_id),
            document_id=inputs.document_id,
            direction=self._direction,
            expected_base_version=inputs.expected_base_version,
        )


class RedoSiteTool(UndoSiteTool):
    """Redo the most recently undone step on a Puck site document."""

    name = "design_redo_site"
    version = "1"
    model_description = "Redo the most recently undone step on a Puck site document, reinstalling the site it had installed."
    _direction: ClassVar[Literal["undo", "redo"]] = "redo"
