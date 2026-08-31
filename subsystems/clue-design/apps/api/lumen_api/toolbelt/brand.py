"""Governed brand-kit tools (Part II slice D6 Round C — domain 1).

Seven routes, four tools. The seven brand-kit write surfaces are ``POST /brand-kits``,
``POST /brand-kits/generate`` (persist half), ``POST /brand-kits/compile-styles`` (persist half),
``POST /brand-kits/compatibility`` (``persist_report``), ``POST /brand-kits/{id}/approval``,
``POST /brand-kits/{id}/logo`` and ``POST /brand-kits/{id}/describe-assets`` — plus the ingestion
worker, which publishes the kit a capture produced. They collapse to four durable operations,
the same "one tool per operation *family*, never per caller" reading Round B applied to
``design_record_diagnostics``:

* :class:`CreateBrandKitTool` — publish a kit version whose number the CALLER already owns
  (a fresh kit, a generated kit, a compiled-styles kit, an ingested kit). Four callers, one
  write, ``DOMAIN_IDEMPOTENT`` on ``(workspace, kit id, version)``.
* :class:`PublishBrandKitVersionTool` — publish the NEXT version of an existing kit, with the
  number allocated inside the write transaction. Two callers (logo curation, describe-assets
  backfill) and the round's brand-domain correctness fix.
* :class:`SetBrandKitApprovalTool` — the approval flip.
* :class:`CreateBrandCompatibilityReportTool` — the optional stored compatibility report.

**Everything the engine does stays in the route** (R-D6-B4): ``validate_brand_kit`` /
``summarize_brand_kit`` / ``generate_brand_kit`` / ``compile_styles_brand_kit`` /
``compare_brand_kit_compatibility`` are Rust round-trips producing the *candidate* kit, and the
tool governs the durable write with that output as its input.

**The version-race fix.** ``/logo`` and ``/describe-assets`` are read-modify-write: read the
latest version, mutate the kit JSON, set ``version + 1``, insert. Both halves were unprotected —
two concurrent curations computed the same next number and the loser died on the composite
primary key (an ``IntegrityError`` surfacing as a duplicate-kit 409 that named the wrong cause),
and had they *not* collided the later publish would silently have discarded the earlier one's
edits. :class:`PublishBrandKitVersionTool` allocates under a lock on the lineage's anchor row and
compare-and-sets on the base version the caller read, so a lost race is a typed 409 and never a
stray primary-key error. See ``clue_design.brand.publish_next_brand_kit_version`` for why the
lock must be on the *lowest*-version row.

**``on_conflict`` (the ingestion re-offer hole).** ``lumen_ingestion.pipeline`` publishes its kit
from the fleet worker, and the D5 Round C reaper re-offers a job whose worker died between
creating the kit and terminalizing the job row. The kit id is already per-job deterministic
(``brand_kit_ing_<job suffix>``, version 1), so a re-offered job's insert collided and the job
failed with a database error instead of completing. ``on_conflict="adopt"`` makes the create a
no-op that returns the existing row's pointer — safe precisely because the id is derived from the
job id, so the slot a job adopts can only have been filled by an earlier attempt of that same
job. Every HTTP caller keeps the default ``"refuse"``, so a client-supplied duplicate is still
the 409 it always was.
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

__all__ = [
    "BrandCompatibilityReportRef",
    "BrandKitRef",
    "CreateBrandCompatibilityReportInput",
    "CreateBrandCompatibilityReportTool",
    "CreateBrandKitInput",
    "CreateBrandKitTool",
    "PublishBrandKitVersionInput",
    "PublishBrandKitVersionTool",
    "SetBrandKitApprovalInput",
    "SetBrandKitApprovalTool",
]

JsonObject = dict[str, Any]


# ---------------------------------------------------------------------------------------------
# typed reference outputs
# ---------------------------------------------------------------------------------------------


class BrandKitRef(ToolOutput):
    """One published kit version, by reference. Never the kit JSON — the caller already holds it
    (it is the tool's own input) and the routes re-read the stored row for their DTOs."""

    brand_kit_id: str
    version: int
    name: str
    approval_status: str
    product_ready: bool
    source: str
    #: ``False`` when ``on_conflict="adopt"`` found the version already published — the write was
    #: a no-op and this reference names the row that was already there.
    created: bool


class BrandCompatibilityReportRef(ToolOutput):
    report_id: str
    from_brand_kit_id: str
    from_version: int
    to_brand_kit_id: str
    to_version: int


def _kit_ref(record: JsonObject, *, created: bool) -> BrandKitRef:
    return BrandKitRef(
        brand_kit_id=record["brand_kit_id"],
        version=int(record["version"]),
        name=record["name"],
        approval_status=record["approval_status"],
        product_ready=bool(record["product_ready"]),
        source=record["source"],
        created=created,
    )


def _existing_kit(repository: Any, brand_kit_id: str, version: int) -> JsonObject | None:
    from ..database import NotFoundError

    try:
        return repository.require_brand_kit(brand_kit_id, version)
    except NotFoundError:
        return None


# ---------------------------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------------------------


class CreateBrandKitInput(ToolInput):
    #: The validated kit payload. Carries its own ``id`` and ``version`` — this tool never
    #: invents a durable identity (the engine's validate/generate/compile pass produced both).
    brand_kit: JsonObject
    brand_summary: JsonObject
    diagnostics: list[JsonObject] = []
    #: The ``design_brand_kit_source`` enum label: manual / generated / styles / website / pdf /
    #: asset_upload. Not restated as a Literal here — the enum lives in the database and a
    #: rejected label is already a loud constraint error (the ingestion suite pins that).
    source: str
    #: ``refuse`` (default, every HTTP caller) → the taken version is a typed refusal that writes
    #: nothing. ``adopt`` (the ingestion worker only) → a taken version is a no-op that returns
    #: the existing row. See the module docstring.
    on_conflict: Literal["refuse", "adopt"] = "refuse"


class CreateBrandKitTool(DesignTool):
    """Publish one brand-kit version whose id and version the caller already owns."""

    name = "design_create_brand_kit"
    version = "1"
    model_description = (
        "Publish a brand kit version from an already-validated kit payload. Returns the kit "
        "reference (id, version, approval state), never the kit JSON."
    )
    input_model: ClassVar[type[ToolInput]] = CreateBrandKitInput
    output_model: ClassVar[type[ToolOutput]] = BrandKitRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + brand_kit.id + brand_kit.version",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "kit versions are immutable rows: a re-run against a taken (id, version) either "
            "refuses without writing or, under on_conflict='adopt', returns the existing row. "
            "Neither branch can produce a second version of the same content"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("source", "on_conflict")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, CreateBrandKitInput)
        if inputs.on_conflict == "adopt":
            return ()
        repository = self.host.repository(ctx.workspace_id)
        brand_kit_id = str(inputs.brand_kit["id"])
        version = int(inputs.brand_kit["version"])
        if _existing_kit(repository, brand_kit_id, version) is None:
            return ()
        return (
            PreconditionFailure(
                reason_code="design_brand_kit_exists",
                message=f"brand kit {brand_kit_id} version {version} already exists",
            ),
        )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, CreateBrandKitInput)
        repository = self.host.repository(ctx.workspace_id)
        brand_kit_id = str(inputs.brand_kit["id"])
        version = int(inputs.brand_kit["version"])
        if inputs.on_conflict == "adopt":
            adopted = _existing_kit(repository, brand_kit_id, version)
            if adopted is not None:
                return _kit_ref(adopted, created=False)
        record = repository.create_brand_kit(
            inputs.brand_kit,
            inputs.brand_summary,
            inputs.diagnostics,
            inputs.source,
        )
        return _kit_ref(record, created=True)


class PublishBrandKitVersionInput(ToolInput):
    #: The mutated kit payload. Its ``version`` field is IGNORED and overwritten by the number
    #: allocated inside the write transaction — the caller cannot own an identity it computed
    #: before the lock existed.
    brand_kit: JsonObject
    brand_summary: JsonObject
    diagnostics: list[JsonObject] = []
    source: str
    #: The version the caller read the kit at. A mismatch means another curation landed while
    #: this one was in the engine, so publishing on top would discard it.
    expected_base_version: int


class PublishBrandKitVersionTool(DesignTool):
    """Publish the next version of an existing kit, allocated under the lineage lock."""

    name = "design_publish_brand_kit_version"
    version = "1"
    model_description = (
        "Publish the next version of an existing brand kit from a mutated kit payload. The "
        "version number is allocated inside the write, so concurrent curations serialize "
        "instead of colliding; a stale base version is refused."
    )
    input_model: ClassVar[type[ToolInput]] = PublishBrandKitVersionInput
    output_model: ClassVar[type[ToolOutput]] = BrandKitRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + brand_kit.id + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the version is ALLOCATED by the write, so a blind retry publishes a second version "
            "of the same content; only a same-operation retry (journal + A9) is a true no-op. "
            "The expected_base_version CAS is the concurrency truth beside it — it refuses a "
            "stale writer, it does not make a fresh operation idempotent"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("source", "expected_base_version")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, PublishBrandKitVersionInput)
        from ..database import NotFoundError

        repository = self.host.repository(ctx.workspace_id)
        brand_kit_id = str(inputs.brand_kit["id"])
        try:
            repository.require_brand_kit(brand_kit_id)
        except NotFoundError:
            return (
                PreconditionFailure(
                    reason_code="design_brand_kit_not_found",
                    message=f"no brand kit {brand_kit_id!r} in this workspace",
                ),
            )
        return ()

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, PublishBrandKitVersionInput)
        record = self.host.repository(ctx.workspace_id).publish_next_brand_kit_version(
            inputs.brand_kit,
            inputs.brand_summary,
            inputs.diagnostics,
            inputs.source,
            expected_base_version=inputs.expected_base_version,
        )
        return _kit_ref(record, created=True)


class SetBrandKitApprovalInput(ToolInput):
    brand_kit_id: str
    approval_status: str


class SetBrandKitApprovalTool(DesignTool):
    """Flip the approval state on a kit's latest version."""

    name = "design_set_brand_kit_approval"
    version = "1"
    model_description = (
        "Approve a brand kit's latest version or revert it to draft. Returns the kit reference."
    )
    input_model: ClassVar[type[ToolInput]] = SetBrandKitApprovalInput
    output_model: ClassVar[type[ToolOutput]] = BrandKitRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + brand_kit_id (latest version's approval_status)",
        external_boundary=ExternalReplayBoundary.NONE,
        notes="effect-free by value: assigning the same approval state twice converges",
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("brand_kit_id", "approval_status")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, SetBrandKitApprovalInput)
        from ..database import NotFoundError

        try:
            self.host.repository(ctx.workspace_id).require_brand_kit(inputs.brand_kit_id)
        except NotFoundError:
            return (
                PreconditionFailure(
                    reason_code="design_brand_kit_not_found",
                    message=f"no brand kit {inputs.brand_kit_id!r} in this workspace",
                ),
            )
        return ()

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, SetBrandKitApprovalInput)
        record = self.host.repository(ctx.workspace_id).update_brand_kit_approval(
            inputs.brand_kit_id, inputs.approval_status
        )
        return _kit_ref(record, created=False)


class CreateBrandCompatibilityReportInput(ToolInput):
    #: Minted by the route (``brand_report_<uuid4hex>``): the report is a snapshot of one
    #: comparison at one instant, so it has no content address to key on.
    report_id: str
    from_brand_kit: JsonObject
    to_brand_kit: JsonObject
    report: JsonObject
    diagnostics: list[JsonObject] = []


class CreateBrandCompatibilityReportTool(DesignTool):
    """Store one brand-compatibility comparison."""

    name = "design_create_brand_compatibility_report"
    version = "1"
    model_description = (
        "Store the result of comparing two brand kits for compatibility. Returns the report "
        "reference, never the report body."
    )
    input_model: ClassVar[type[ToolInput]] = CreateBrandCompatibilityReportInput
    output_model: ClassVar[type[ToolOutput]] = BrandCompatibilityReportRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + report_id + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the report id is a fresh uuid per request (a stored comparison is a dated snapshot, "
            "not a content address), so each execution is a new row and only a same-operation "
            "retry replays"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("report_id",)
    )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, CreateBrandCompatibilityReportInput)
        stored = self.host.repository(ctx.workspace_id).create_brand_compatibility_report(
            inputs.report_id,
            inputs.from_brand_kit,
            inputs.to_brand_kit,
            inputs.report,
            inputs.diagnostics,
        )
        return BrandCompatibilityReportRef(
            report_id=stored["report_id"],
            from_brand_kit_id=stored["from_ref"]["id"],
            from_version=int(stored["from_ref"]["version"]),
            to_brand_kit_id=stored["to_ref"]["id"],
            to_version=int(stored["to_ref"]["version"]),
        )
