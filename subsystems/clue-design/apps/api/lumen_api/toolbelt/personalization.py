"""Governed personalization + batch tools (Part II slice D6 Round C — domain 4).

Scene-mode personalization (binding sets, derived instances, the repair queue) and BOTH batch
families (instance batches over binding sets; web batches over accounts). Seven tools:

| tool | what it governs |
|---|---|
| ``design_upsert_binding_set`` | one client-named binding set |
| ``design_delete_binding_set`` | its removal |
| ``design_derive_instance`` | the instance row + its generated assets + its repair requests |
| ``design_create_instance_batch`` | the batch row |
| ``design_advance_instance_batch`` | ONE chunk of progress |
| ``design_create_web_batch`` | the batch row |
| ``design_advance_web_batch`` | ONE chunk of progress |

**The derive tool is three writes on purpose.** ``_derive_and_persist_instance`` upserts the
instance, registers every asset the engine generated while re-fitting it, and opens a repair
request per slot the engine could not fit. Those are not three operations — they are one
derivation's durable footprint, all keyed off the same deterministic ``inst_<rev>_<bind>``
identity, and a partial application (an instance row whose generated crop was never registered)
is exactly the state nobody can repair. The ENGINE derive stays in the route (R-D6-B4).

**The batch single-flight (the round's personalization correctness fix).** ``_process_batch`` /
``_process_web_batch`` read the cursor, derive a chunk — hundreds of milliseconds to minutes of
engine work, outside any transaction, because the O5 bridge is one transaction per store call —
and then write progress. Two concurrent ``POST …/resume`` calls therefore both derived the same
chunk and both wrote it: the instance side accumulated a duplicate manifest slice and rewound the
cursor to the loser's view; the web side additionally minted a second ``doc_`` per account and
could publish a second slug. Now every chunk write carries the cursor the chunk STARTED from and
the DAL compare-and-sets it under the batch row lock. The loser's write is refused, the tool
reports ``advanced=False`` with the batch's *current* cursor, and the loop stops and returns the
live progress — a resume is never an error, it just discovers the work is already being done.

The residual, stated honestly: the losing resumer still *derives* its chunk before discovering
the cursor moved (the lock cannot be held across the engine round-trip). The loop therefore also
re-reads the cursor at the top of each chunk, which shrinks the window to one chunk, and on the
instance side that wasted work is harmless — ``inst_<rev>_<bind>`` is deterministic and the write
is an upsert. On the web side one chunk of orphan documents is possible; closing that needs a
real per-batch lease, which is fleet work, not toolbelt work.
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

__all__ = [
    "AdvanceInstanceBatchInput",
    "AdvanceInstanceBatchTool",
    "AdvanceWebBatchInput",
    "AdvanceWebBatchTool",
    "BatchProgressRef",
    "BatchRef",
    "BindingSetRef",
    "CreateInstanceBatchInput",
    "CreateInstanceBatchTool",
    "CreateWebBatchInput",
    "CreateWebBatchTool",
    "DeleteBindingSetInput",
    "DeleteBindingSetTool",
    "DeriveInstanceInput",
    "DeriveInstanceTool",
    "InstanceRef",
    "UpsertBindingSetInput",
    "UpsertBindingSetTool",
    "persist_derived_instance",
]

JsonObject = dict[str, Any]


# ---------------------------------------------------------------------------------------------
# typed reference outputs
# ---------------------------------------------------------------------------------------------


class BindingSetRef(ToolOutput):
    binding_set_id: str
    template_revision_id: str
    status: str


class InstanceRef(ToolOutput):
    instance_id: str
    template_revision_id: str
    binding_set_id: str
    batch_id: str | None
    status: str
    fit_status: str
    #: Ids of the assets the derivation generated and registered (a re-fit crop, say).
    generated_asset_ids: list[str]
    #: Ids of the repair requests it opened.
    repair_request_ids: list[str]


class BatchRef(ToolOutput):
    batch_id: str
    status: str
    cursor: int
    total: int


class BatchProgressRef(ToolOutput):
    batch_id: str
    status: str
    cursor: int
    #: ``False`` when the compare-and-set found the cursor had already moved — this invocation
    #: wrote nothing and ``cursor`` is where the batch actually is.
    advanced: bool


# ---------------------------------------------------------------------------------------------
# the derive-persist operation core
# ---------------------------------------------------------------------------------------------


def persist_derived_instance(
    *,
    repository: Any,
    instance: JsonObject,
    generated_records: list[JsonObject],
    repair_requests: list[JsonObject],
) -> InstanceRef:
    """One derivation's whole durable footprint. The ONE instance-persist write path."""
    stored = repository.upsert_instance(instance)
    generated_ids: list[str] = []
    for record in generated_records:
        repository.create_asset_record(record)
        generated_ids.append(str(record["id"]))
    repair_ids: list[str] = []
    for repair in repair_requests:
        repository.upsert_repair_request(repair)
        repair_ids.append(str(repair["repair_id"]))
    return InstanceRef(
        instance_id=stored["instance_id"],
        template_revision_id=stored["template_revision_id"],
        binding_set_id=stored["binding_set_id"],
        batch_id=stored.get("batch_id"),
        status=stored["status"],
        fit_status=stored["fit_status"],
        generated_asset_ids=generated_ids,
        repair_request_ids=repair_ids,
    )


# ---------------------------------------------------------------------------------------------
# binding sets
# ---------------------------------------------------------------------------------------------


class UpsertBindingSetInput(ToolInput):
    #: The validated binding set. Its ``binding_set_id`` is CLIENT-SUPPLIED and mandatory (the
    #: route 422s a payload without one before the invocation), which is what makes the domain
    #: key real here rather than the "route mints a uuid" else-branch Round B had to document.
    binding: JsonObject
    status: str
    diagnostics: list[JsonObject] = []


class UpsertBindingSetTool(DesignTool):
    """Store or re-author one binding set."""

    name = "design_upsert_binding_set"
    version = "1"
    model_description = (
        "Store a validated personalization binding set under its client-supplied id. "
        "Re-authoring replaces the stored payload in place. Returns the binding-set reference."
    )
    input_model: ClassVar[type[ToolInput]] = UpsertBindingSetInput
    output_model: ClassVar[type[ToolOutput]] = BindingSetRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + binding.binding_set_id",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the id is client-supplied and REQUIRED (never minted), and the write is an upsert "
            "of the whole payload, so re-sending the same binding set converges on one row"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("status",)
    )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, UpsertBindingSetInput)
        stored = self.host.repository(ctx.workspace_id).upsert_binding_set(
            inputs.binding, inputs.status, inputs.diagnostics
        )
        return BindingSetRef(
            binding_set_id=stored["binding_set_id"],
            template_revision_id=stored["template_revision_id"],
            status=stored["status"],
        )


class DeleteBindingSetInput(ToolInput):
    binding_set_id: str


class DeleteBindingSetTool(DesignTool):
    """Remove one binding set."""

    name = "design_delete_binding_set"
    version = "1"
    model_description = "Delete a personalization binding set by id."
    input_model: ClassVar[type[ToolInput]] = DeleteBindingSetInput
    output_model: ClassVar[type[ToolOutput]] = BindingSetRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + binding_set_id (absence)",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "convergent by value — deleting an already-absent binding set is a no-op, which is "
            "also the ported route contract (it has never 404'd, so nothing is gated on "
            "existence and there is no destructive swap to protect, unlike "
            "design_delete_web_account, whose response body is built from the row it removes)"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("binding_set_id",)
    )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, DeleteBindingSetInput)
        repository = self.host.repository(ctx.workspace_id)
        stored = None
        from ..database import NotFoundError

        try:
            stored = repository.require_binding_set(inputs.binding_set_id)
        except NotFoundError:
            stored = None
        repository.delete_binding_set(inputs.binding_set_id)
        return BindingSetRef(
            binding_set_id=inputs.binding_set_id,
            template_revision_id=(stored or {}).get("template_revision_id") or "",
            status="deleted",
        )


# ---------------------------------------------------------------------------------------------
# instances
# ---------------------------------------------------------------------------------------------


class DeriveInstanceInput(ToolInput):
    #: The instance row to write, already shaped by the route from the engine's derive output.
    #: Its ``instance_id`` is the deterministic ``inst_<revision>_<binding>``.
    instance: JsonObject
    #: Asset records the derivation generated (already given durable byte custody by the route).
    generated_records: list[JsonObject] = []
    #: Repair-queue rows for the slots the engine asked a human/agent to fix.
    repair_requests: list[JsonObject] = []


class DeriveInstanceTool(DesignTool):
    """Persist one derived personalization instance and everything it produced."""

    name = "design_derive_instance"
    version = "1"
    model_description = (
        "Persist a derived personalization instance together with the assets its derivation "
        "generated and the repair requests it opened. Returns the instance reference, never "
        "the derived scene."
    )
    input_model: ClassVar[type[ToolInput]] = DeriveInstanceInput
    output_model: ClassVar[type[ToolOutput]] = InstanceRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + instance.instance_id (inst_<revision>_<binding set>)",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the instance id is DERIVED from the revision and binding set, and all three writes "
            "are upserts keyed off it (the generated asset ids are content-derived, the repair "
            "ids are rep_<revision>_<slot>_<binding>), so re-deriving the same pair refreshes "
            "one instance instead of accumulating rows"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=()
    )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, DeriveInstanceInput)
        return persist_derived_instance(
            repository=self.host.repository(ctx.workspace_id),
            instance=inputs.instance,
            generated_records=inputs.generated_records,
            repair_requests=inputs.repair_requests,
        )


# ---------------------------------------------------------------------------------------------
# batches
# ---------------------------------------------------------------------------------------------


class CreateInstanceBatchInput(ToolInput):
    #: Minted by the route (``batch_<uuid4hex>``) — a batch is a job, not a content address.
    batch: JsonObject


class CreateInstanceBatchTool(DesignTool):
    """Open one chunked instance-derivation batch."""

    name = "design_create_instance_batch"
    version = "1"
    model_description = (
        "Open a chunked personalization batch over a list of binding sets. Returns the batch "
        "reference; the derivation itself is driven chunk by chunk."
    )
    input_model: ClassVar[type[ToolInput]] = CreateInstanceBatchInput
    output_model: ClassVar[type[ToolOutput]] = BatchRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + batch.batch_id + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the batch id is a fresh uuid per request — a batch is a job with its own cursor and "
            "manifest, so two requests are two jobs and only a same-operation retry replays"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=()
    )
    _total_key: ClassVar[str] = "binding_set_ids"

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, CreateInstanceBatchInput)
        stored = self.host.repository(ctx.workspace_id).create_batch(inputs.batch)
        return BatchRef(
            batch_id=stored["batch_id"],
            status=stored["status"],
            cursor=int(stored["cursor"]),
            total=len(stored[self._total_key]),
        )


class CreateWebBatchInput(CreateInstanceBatchInput):
    """Same shape; a separate model so the two tools' inputs are separately documented."""


class CreateWebBatchTool(CreateInstanceBatchTool):
    """Open one chunked website derive/publish batch."""

    name = "design_create_web_batch"
    version = "1"
    model_description = (
        "Open a chunked website batch that derives (and optionally publishes) one page per "
        "account from a template document. Returns the batch reference."
    )
    input_model: ClassVar[type[ToolInput]] = CreateWebBatchInput
    _total_key: ClassVar[str] = "account_ids"

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, CreateWebBatchInput)
        stored = self.host.repository(ctx.workspace_id).create_web_batch(inputs.batch)
        return BatchRef(
            batch_id=stored["batch_id"],
            status=stored["status"],
            cursor=int(stored["cursor"]),
            total=len(stored[self._total_key]),
        )


class AdvanceInstanceBatchInput(ToolInput):
    batch_id: str
    #: The cursor the chunk STARTED from — the compare-and-set key. A stale value means another
    #: resumer already advanced this batch, and this invocation writes nothing.
    expected_cursor: int
    cursor: int
    status: str
    counts: JsonObject
    manifest: list[JsonObject]
    diagnostics: list[JsonObject] = []


class AdvanceInstanceBatchTool(DesignTool):
    """Persist one chunk of instance-batch progress, under the cursor compare-and-set."""

    name = "design_advance_instance_batch"
    version = "1"
    model_description = (
        "Persist one chunk of personalization batch progress. Refuses to write when another "
        "worker has already advanced the batch past this chunk, reporting where it actually is."
    )
    input_model: ClassVar[type[ToolInput]] = AdvanceInstanceBatchInput
    output_model: ClassVar[type[ToolOutput]] = BatchProgressRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + batch_id + expected_cursor + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "each chunk advances a cursor and appends to a manifest, so a blind retry of a "
            "SUCCEEDED chunk would append it twice; the operation id is what makes a retry a "
            "no-op. The expected_cursor CAS is the concurrency truth beside it — it stops a "
            "second RESUMER (a different operation) from double-writing, which no A9 key can"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("batch_id", "expected_cursor", "cursor", "status")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        # No isinstance narrowing: :class:`AdvanceWebBatchTool` inherits this check with its own
        # input model. Both models carry ``batch_id``; ``_read``/``_write`` are the only two
        # things that differ between the families and both are overridden.
        batch_id = str(getattr(inputs, "batch_id"))
        from ..database import NotFoundError

        try:
            self._read(self.host.repository(ctx.workspace_id), batch_id)
        except NotFoundError:
            return (
                PreconditionFailure(
                    reason_code="design_batch_not_found",
                    message=f"no batch {batch_id!r} in this workspace",
                ),
            )
        return ()

    @staticmethod
    def _read(repository: Any, batch_id: str) -> JsonObject:
        return repository.require_batch(batch_id)

    @staticmethod
    def _write(repository: Any, inputs: Any) -> JsonObject:
        return repository.update_batch_progress(
            inputs.batch_id,
            inputs.cursor,
            inputs.status,
            inputs.counts,
            inputs.manifest,
            inputs.diagnostics,
            expected_cursor=inputs.expected_cursor,
        )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        from ..database import DesignResourceVersionConflict

        repository = self.host.repository(ctx.workspace_id)
        try:
            stored = self._write(repository, inputs)
        except DesignResourceVersionConflict as moved:
            current = self._read(repository, moved.key)
            return BatchProgressRef(
                batch_id=moved.key,
                status=current["status"],
                cursor=int(current["cursor"]),
                advanced=False,
            )
        return BatchProgressRef(
            batch_id=stored["batch_id"],
            status=stored["status"],
            cursor=int(stored["cursor"]),
            advanced=True,
        )


class AdvanceWebBatchInput(ToolInput):
    batch_id: str
    expected_cursor: int
    cursor: int
    status: str
    manifest: list[JsonObject]


class AdvanceWebBatchTool(AdvanceInstanceBatchTool):
    """Persist one chunk of web-batch progress, under the cursor compare-and-set."""

    name = "design_advance_web_batch"
    version = "1"
    model_description = (
        "Persist one chunk of website batch progress. Refuses to write when another worker has "
        "already advanced the batch past this chunk, reporting where it actually is."
    )
    input_model: ClassVar[type[ToolInput]] = AdvanceWebBatchInput

    @staticmethod
    def _read(repository: Any, batch_id: str) -> JsonObject:
        return repository.require_web_batch(batch_id)

    @staticmethod
    def _write(repository: Any, inputs: Any) -> JsonObject:
        return repository.update_web_batch_progress(
            inputs.batch_id,
            inputs.cursor,
            inputs.status,
            inputs.manifest,
            expected_cursor=inputs.expected_cursor,
        )
