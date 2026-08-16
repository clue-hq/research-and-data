"""Governed custom-component tools (Part II slice D6 Round A — reference domain 3).

Two writes: replace a component's source tree (under the existing optimistic CAS), and compile
one exact durable source version into an immutable artifact.

These are the two design writes with **two callers each** — the HTTP route and the deep agent's
``DurableAgentCustomComponentRegistry``. D6 governs the *orchestration functions*
(``custom_components.persist_custom_component_source_revision`` /
``custom_component_compiler.compile_and_persist_custom_component``), which is what lets both
callers become tool-governed without either of them learning about the other (R-D6-5).

Replay honesty (R-D6-3):

* **write source** is ``DOMAIN_IDEMPOTENT``. The revision id is content-derived
  (``ccsrc_<sha256(account, slug, next_version, snapshot_digest)>``) and the write is guarded by a
  DB-enforced ``expected_version`` compare-and-swap, so a re-run at the same expected version
  either lands the same row or refuses with a version conflict — it can never append a duplicate.
* **compile** is ``OPERATION_IDEMPOTENT``. The *artifact* it may produce is content-addressed
  (``ccart_<sha256(identity)>``, insert-or-no-op, immutable by trigger), but every attempt also
  appends a fresh ``cccmp_<uuid4>`` compilation record — deliberately, because that table is the
  attempt log. So a NEW operation genuinely re-executes; only a same-operation retry replays.
  (The brief suggested DOMAIN_IDEMPOTENT on the ``ccart`` id; that would be a true statement about
  the artifact and a false one about the compilation record, so the weaker, honest policy wins.)
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
    "CompileCustomComponentInput",
    "CompileCustomComponentTool",
    "CustomComponentCompilationRef",
    "CustomComponentSourceRef",
    "WriteCustomComponentSourceInput",
    "WriteCustomComponentSourceTool",
]


class ComponentActor(ToolInput):
    """Who authored this component write (the ported ``ActorEnvelope``)."""

    kind: str = "api"
    id: str | None = None


class CustomComponentSourceRef(ToolOutput):
    account_id: str
    slug: str
    revision_id: str
    source_version: int
    snapshot_digest: str


class CustomComponentCompilationRef(ToolOutput):
    account_id: str
    slug: str
    compilation_id: str
    #: ``success`` | ``failed`` | ``transient_error`` — the route's 200/422/503 selector.
    compile_status: str
    artifact_id: str | None
    source_revision_id: str
    source_version: int


def _account_missing(
    repository: Any, account_id: str
) -> tuple[PreconditionFailure, ...]:
    if repository.get_web_account(account_id) is None:
        return (
            PreconditionFailure(
                reason_code="design_account_not_found",
                message=f"no account {account_id!r} in this workspace",
            ),
        )
    return ()


class WriteCustomComponentSourceInput(ToolInput):
    account_id: str
    slug: str
    expected_version: int
    files: dict[str, str]
    #: The provenance object stamped verbatim on the immutable revision row. The HTTP route
    #: sends ``{"kind": "custom_component_source_write", "actor": …}``; the agent registry sends
    #: its run id, ladder gap, endpoint claims and prompt digest. Kept a caller-supplied input
    #: (rather than derived here) so the recorded provenance stays byte-identical to both
    #: callers' pre-D6 shape.
    provenance: dict[str, object]


class WriteCustomComponentSourceTool(DesignTool):
    """Replace one component's source tree under its optimistic version CAS."""

    name = "design_write_component_source"
    version = "1"
    model_description = (
        "Replace the source tree of one account-local custom component, guarded by an optimistic "
        "expected_version compare-and-swap. Returns the new revision's references, not its files."
    )
    input_model: ClassVar[type[ToolInput]] = WriteCustomComponentSourceInput
    output_model: ClassVar[type[ToolOutput]] = CustomComponentSourceRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity=(
            "workspace + ccsrc_<sha256(account, slug, expected_version+1, snapshot digest)> "
            "under the design_custom_component.source_version CAS"
        ),
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the CAS makes a duplicate append unrepresentable: a re-run at the same expected "
            "version either writes the same content-derived revision id or refuses with a source "
            "version conflict"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("account_id", "slug", "expected_version")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, WriteCustomComponentSourceInput)
        from ..custom_components import canonical_custom_component_source_snapshot

        repository = self.host.repository(ctx.workspace_id)
        if failure := _account_missing(repository, inputs.account_id):
            return failure
        if inputs.expected_version < 0:
            return (
                PreconditionFailure(
                    reason_code="design_component_source_invalid",
                    message="expected_version must be >= 0",
                ),
            )
        try:
            canonical_custom_component_source_snapshot(
                slug=inputs.slug, files=dict(inputs.files)
            )
        except ValueError as error:
            # The exact message the route's 422 body has always carried.
            return (
                PreconditionFailure(
                    reason_code="design_component_source_invalid",
                    message=str(error),
                ),
            )
        return ()

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, WriteCustomComponentSourceInput)
        from ..custom_components import persist_custom_component_source_revision

        revision = persist_custom_component_source_revision(
            self.host.repository(ctx.workspace_id),
            self.host.blobs(ctx.workspace_id),
            account_id=inputs.account_id,
            slug=inputs.slug,
            expected_version=inputs.expected_version,
            files=dict(inputs.files),
            provenance=dict(inputs.provenance),
        )
        return CustomComponentSourceRef(
            account_id=inputs.account_id,
            slug=inputs.slug,
            revision_id=revision["revision_id"],
            source_version=revision["source_version"],
            snapshot_digest=revision["snapshot"]["value"],
        )


class CompileCustomComponentInput(ToolInput):
    account_id: str
    slug: str
    source_version: int
    actor: ComponentActor = ComponentActor()


class CompileCustomComponentTool(DesignTool):
    """Compile one exact durable source revision inside the constrained node worker."""

    name = "design_compile_component"
    version = "1"
    model_description = (
        "Compile one exact durable source version of an account-local custom component. Records "
        "every outcome; only a protocol-valid success creates an immutable artifact."
    )
    input_model: ClassVar[type[ToolInput]] = CompileCustomComponentInput
    output_model: ClassVar[type[ToolOutput]] = CustomComponentCompilationRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity=(
            "workspace + ToolContext.operation_id; the artifact it may produce is the "
            "content-derived ccart_<sha256(identity)>"
        ),
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the artifact is content-addressed and re-registering it is a no-op, but every "
            "attempt appends a fresh cccmp_ compilation record (the attempt log), so a NEW "
            "operation re-executes; the compiler is a local node subprocess, not a provider"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("account_id", "slug", "source_version")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, CompileCustomComponentInput)
        repository = self.host.repository(ctx.workspace_id)
        # NOT an account-existence check: `get_custom_component` is already account-scoped, and
        # the pre-D6 route reported an unknown account as `custom_component.not_found` (it never
        # probed the account separately). Checking the account here would silently change that
        # 404's code, which the editor reads.
        if repository.get_custom_component(inputs.account_id, inputs.slug) is None:
            return (
                PreconditionFailure(
                    reason_code="design_component_not_found",
                    message=f"no custom component {inputs.slug!r} for this account",
                ),
            )
        return ()

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, CompileCustomComponentInput)
        from ..custom_component_compiler import compile_and_persist_custom_component

        # NOTE: the source-version compare-and-swap (before AND after the out-of-transaction
        # compile) stays inside the orchestration core and still raises
        # ``CustomComponentSourceVersionConflict``. It is deliberately NOT lifted into a
        # precondition: the conflict body carries expected/current versions that a
        # ``PreconditionFailure`` cannot express, and the post-compile re-check has no
        # pre-invocation moment to run in.
        response = compile_and_persist_custom_component(
            repository=self.host.repository(ctx.workspace_id),
            blobs=self.host.blobs(ctx.workspace_id),
            node_binary=self.host.need("compiler_node_bin"),
            worker_path=self.host.need("compiler_worker_path"),
            timeout_seconds=self.host.need("compiler_timeout_seconds"),
            account_id=inputs.account_id,
            slug=inputs.slug,
            source_version=inputs.source_version,
            actor=inputs.actor.model_dump(),
            compile_fn=self.host.need("compile_fn"),
        )
        compilation = response["compilation"]
        artifact = response["artifact"]
        return CustomComponentCompilationRef(
            account_id=inputs.account_id,
            slug=inputs.slug,
            compilation_id=compilation["compilation_id"],
            compile_status=response["compile_status"],
            artifact_id=artifact["artifact_id"] if artifact else None,
            source_revision_id=compilation["source_revision_id"],
            source_version=compilation["source_version"],
        )
