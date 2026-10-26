"""``write_brand_document@1``: the Head of ABM publishes a Brand-context document.

Spec: docs/superpowers/specs/crm-integration/2026-10-20-crm-integration-first-release-design.md
§6; founder ruling R-3.15. The agent may edit any Brand-context document (``company/``,
``product/``, ``audience/``, ``proof/``) except the generated product catalog, which only
``manage_products`` changes - and only when the person asks or a skill says to. It writes only to
the brand of the conversation's project, and always as a new version: older versions are
superseded, never changed, and a project's confirmed pin is never touched.

Two writers never silently overwrite each other: the call names the version it read
(``based_on_version``, from ``brand/index.json``), and a document that has moved on since is
refused ``document_changed`` - the rule a person's save in Brand context already follows. Nothing
is locked. The brand row lock serializes the write itself.

The Markdown comes inline (``markdown``) or from a file the agent wrote in the code sandbox's
``outputs/`` folder (a
long document is easier to build there). An existing document keeps its front matter, as the
Brand-context editor does; ``written_by`` records the person and turn. Writing bytes identical to
the current version publishes nothing and returns that version, so a replayed call is harmless.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, ClassVar
from uuid import UUID

from pydantic import Field, StringConstraints
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.manual import tool_manual_link
from clue_api.brand_knowledge_writes import (
    current_brand_version,
    lock_brand,
    render_brand_document,
    write_brand_document_version,
)
from clue_api.product_management import read_brand_document
from clue_api.sandbox.workspaces import SandboxWorkspaces
from clue_api.turn_action import TurnActionUnresolvable, load_turn_identity, parse_turn_action_ref
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_db import ConnFactory, transaction
from clue_spine import get_project
from clue_storage import StorageBackend, content_address
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailed,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolEstimate,
    ToolInput,
    ToolOutput,
    ToolResult,
)

__all__ = [
    "SOURCE_KEY",
    "WriteBrandDocumentInput",
    "WriteBrandDocumentOutput",
    "WriteBrandDocumentTool",
    "build_brand_document_tools",
]

SOURCE_KEY = "brand_document_agent_write"
_PATH = re.compile(r"^(company|product|audience|proof)/[a-z0-9][a-z0-9-]*\.md$")
#: Generated from the brand's product list; ``manage_products`` is its only writer.
_CATALOG_PATH = "product/catalog.md"
_FROM_FILE = re.compile(r"^outputs/(?:[A-Za-z0-9_][A-Za-z0-9._-]*/)*[A-Za-z0-9_][A-Za-z0-9._-]*$")
_KIND = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_MAX_BODY_CHARS = 1_000_000
_MAX_FILE_BYTES = 2_000_000


class WriteBrandDocumentInput(ToolInput):
    #: ``<company|product|audience|proof>/<name>.md``, lower-case letters, digits and hyphens.
    path: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    #: What the document is, e.g. ``sales-motion``. Needed only for a new document; an existing
    #: document keeps its kind.
    kind: str | None = None
    #: The document's Markdown, without front matter. Give this or ``from_file``, not both.
    #: Never name an input ``body``/``content``/``text``…: the agent's plan validator refuses any
    #: binding with one of those names (``clue_execution.graph._RAW_BODY_KEYS``), trial 1 F4.
    markdown: str | None = Field(default=None, max_length=_MAX_BODY_CHARS)
    #: A Markdown file you wrote in the sandbox, e.g. ``outputs/sales-motion.md``.
    from_file: str | None = None
    #: The version you read, from ``brand/index.json``. Leave it out only for a new document.
    based_on_version: int | None = Field(default=None, ge=1)
    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})


class WriteBrandDocumentOutput(ToolOutput):
    document_id: str
    path: str
    version: int
    #: ``True`` when the bytes matched the current version, so nothing new was published.
    unchanged: bool


class _Refused(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class _Scope:
    brand_id: str
    user_id: str
    turn_id: UUID


def _check_input(inputs: WriteBrandDocumentInput) -> None:
    if not _PATH.fullmatch(inputs.path):
        raise _Refused(
            "path_not_allowed",
            "Only company/, product/, audience/ and proof/ documents can be written, named "
            "<folder>/<name>.md with lower-case letters, digits and hyphens "
            "(e.g. company/sales-motion.md).",
        )
    if inputs.path == _CATALOG_PATH:
        raise _Refused(
            "document_generated",
            "The product catalog is generated from the product list; change the products with "
            "manage_products instead.",
        )
    if (inputs.markdown is None) == (inputs.from_file is None):
        raise _Refused("markdown_or_file_required", "Give exactly one of markdown or from_file.")
    if inputs.kind is not None and not _KIND.fullmatch(inputs.kind):
        raise _Refused("kind_invalid", "kind is lower-case letters, digits and hyphens.")
    if inputs.from_file is not None and (
        not _FROM_FILE.fullmatch(inputs.from_file) or ".." in inputs.from_file.split("/")
    ):
        raise _Refused(
            "file_not_allowed", "from_file must be a file under outputs/, e.g. outputs/notes.md."
        )


def _check_body(body: str) -> str:
    if not body.strip():
        raise _Refused("markdown_empty", "The document is empty.")
    if body.startswith("---\n"):
        raise _Refused(
            "front_matter_not_allowed",
            "Write the Markdown only, without a front-matter block; the platform keeps that.",
        )
    return body


class WriteBrandDocumentTool(Tool):
    name = "write_brand_document"
    version = "1"
    model_description = (
        "Publish a new version of a Brand-context document under company/, product/, audience/ "
        "or proof/ (for example company/sales-motion.md, or an updated proof/customers.md). Use "
        "it only when the person asks you to change a brand document, or a skill tells you to; "
        "never on your own initiative. The previous version is kept in its history, and the "
        "person can read and edit the document in Brand context. Write the whole document, not a "
        "change: read the current version from brand/, pass the version you read as "
        "based_on_version (from brand/index.json; leave it out only for a new document), and "
        "write it back with your changes. The product catalog cannot be written here. Give the "
        "document as markdown, or from_file for a file you wrote under outputs/ with run_python. "
        + tool_manual_link("write_brand_document")
    )
    input_model: ClassVar[type[ToolInput]] = WriteBrandDocumentInput
    output_model: ClassVar[type[ToolOutput]] = WriteBrandDocumentOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity=(
            "the path's current brand-level version: identical bytes return it unchanged"
        ),
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("path", "kind", "from_file", "based_on_version")
    )
    pin_requirements = ("project",)

    def __init__(
        self,
        *,
        storage: StorageBackend | None,
        sandbox_workspaces: SandboxWorkspaces | None,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._storage = storage
        self._sandbox = sandbox_workspaces
        self._conn_factory = conn_factory

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate.free()

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, WriteBrandDocumentInput)
        try:
            _check_input(inputs)
            self._require_storage()
            self._read_body(inputs, ctx)
            async with self._conn_factory() as conn:
                await self._scope(conn, inputs, ctx)
        except _Refused as exc:
            return (PreconditionFailure(reason_code=exc.reason_code, message=str(exc)),)
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, WriteBrandDocumentInput)
        try:
            _check_input(inputs)
            storage = self._require_storage()
            body = self._read_body(inputs, ctx)
            async with self._conn_factory() as conn:
                output = await self._write(conn, storage, inputs, ctx, body)
        except _Refused as exc:
            raise PreconditionFailed([PreconditionFailure(exc.reason_code, str(exc))]) from exc
        return ToolResult(
            tool=self.name, version=self.version, references=output.model_dump(mode="json")
        )

    async def _write(
        self,
        conn: AsyncConnection,
        storage: StorageBackend,
        inputs: WriteBrandDocumentInput,
        ctx: ToolContext,
        body: str,
    ) -> WriteBrandDocumentOutput:
        scope = await self._scope(conn, inputs, ctx)
        workspace_id = ctx.workspace_id
        if not await lock_brand(conn, workspace_id=workspace_id, brand_id=scope.brand_id):
            raise _Refused("brand_unavailable", "The project's brand is unavailable.")
        current = await current_brand_version(
            conn, workspace_id=workspace_id, brand_id=scope.brand_id, path=inputs.path
        )
        front: dict[str, Any] = {}
        if current is not None:
            read = await read_brand_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=scope.brand_id,
                document_id=current.document_id,
            )
            front = dict(read[0]) if read is not None else {}
            if front.get("generated") is True:
                raise _Refused(
                    "document_generated",
                    f"{inputs.path} is generated by the platform and cannot be edited.",
                )
            if inputs.kind is not None and inputs.kind != current.kind:
                raise _Refused(
                    "kind_mismatch",
                    f"{inputs.path} is a {current.kind} document; leave kind out to keep it.",
                )
            kind = current.kind
        elif inputs.kind is None:
            raise _Refused("kind_required", f"{inputs.path} is new: say what it is with kind.")
        else:
            kind = inputs.kind
        front.setdefault("kind", kind)
        front["written_by"] = {"user_id": scope.user_id, "turn_id": str(scope.turn_id)}
        data = render_brand_document(path=inputs.path, kind=kind, front=front, body=body)
        if current is not None and current.artifact_sha256 == content_address(data):
            return WriteBrandDocumentOutput(
                document_id=str(current.document_id),
                path=inputs.path,
                version=current.version,
                unchanged=True,
            )
        current_version = current.version if current is not None else None
        if inputs.based_on_version != current_version:
            raise _Refused(
                "document_changed",
                f"{inputs.path} "
                + (
                    f"is now at version {current_version}"
                    if current_version is not None
                    else "has no current version"
                )
                + (
                    f", not the version {inputs.based_on_version} you read"
                    if inputs.based_on_version is not None
                    else " and you did not say which version you read"
                )
                + ". Someone saved it after this turn began; your brand/ files show it from the "
                "next turn. Nothing was written.",
            )
        document_id = await write_brand_document_version(
            conn,
            storage,
            workspace_id=workspace_id,
            brand_id=scope.brand_id,
            path=inputs.path,
            kind=kind,
            front=front,
            body=body,
            source_key=SOURCE_KEY,
        )
        version = await conn.scalar(
            text("SELECT version FROM brand_knowledge_document WHERE document_id = :id"),
            {"id": document_id},
        )
        return WriteBrandDocumentOutput(
            document_id=str(document_id), path=inputs.path, version=int(version), unchanged=False
        )

    def _require_storage(self) -> StorageBackend:
        if self._storage is None:
            raise _Refused(
                "storage_unavailable", "Document storage is not composed on this deployment."
            )
        return self._storage

    def _read_body(self, inputs: WriteBrandDocumentInput, ctx: ToolContext) -> str:
        if inputs.markdown is not None:
            return _check_body(inputs.markdown)
        assert inputs.from_file is not None
        mounts = (
            None
            if self._sandbox is None or ctx.execution_id is None
            else self._sandbox.mounts_for(ctx.execution_id)
        )
        outputs = None if mounts is None else mounts.read_write.get("outputs")
        if outputs is None:
            raise _Refused(
                "sandbox_unavailable",
                "This turn has no sandbox outputs/ folder; give the document as markdown instead.",
            )
        root = Path(outputs).resolve()
        target = (root / inputs.from_file.removeprefix("outputs/")).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise _Refused("file_not_found", f"{inputs.from_file} does not exist.")
        if target.stat().st_size > _MAX_FILE_BYTES:
            raise _Refused("file_too_large", f"{inputs.from_file} is larger than 2 MB.")
        try:
            return _check_body(target.read_text(encoding="utf-8"))
        except UnicodeDecodeError as exc:
            raise _Refused("file_not_text", f"{inputs.from_file} is not UTF-8 text.") from exc

    async def _scope(
        self, conn: AsyncConnection, inputs: WriteBrandDocumentInput, ctx: ToolContext
    ) -> _Scope:
        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
        except TurnActionUnresolvable as exc:
            raise _Refused("turn_unavailable", "The current turn is unavailable.") from exc
        turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
        if turn is None or not turn.submitted_by_user_id:
            raise _Refused("turn_unavailable", "The current turn is unavailable.")
        project = await get_project(conn, turn.project_id)
        if project is None or project.workspace_id != ctx.workspace_id:
            raise _Refused("turn_unavailable", "The current turn's project is unavailable.")
        return _Scope(
            brand_id=str(project.brand_id), user_id=turn.submitted_by_user_id, turn_id=turn_id
        )


def build_brand_document_tools(
    *,
    storage: StorageBackend | None,
    sandbox_workspaces: SandboxWorkspaces | None,
    conn_factory: ConnFactory = transaction,
) -> tuple[Tool, ...]:
    """Registered on every deployment; refuses by name without storage (or, for from_file,
    without the turn's sandbox outputs/ folder)."""
    return (
        WriteBrandDocumentTool(
            storage=storage, sandbox_workspaces=sandbox_workspaces, conn_factory=conn_factory
        ),
    )
