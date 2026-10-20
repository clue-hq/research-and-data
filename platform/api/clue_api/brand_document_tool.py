"""``write_brand_document@1``: the Head of ABM publishes a Brand-context document.

Spec: docs/superpowers/specs/crm-integration/2026-10-20-crm-integration-first-release-design.md
§6. The CRM sales analysis lands as ``company/sales-motion.md``, and recent closed-won customers
are merged into ``proof/customers.md``; both are ordinary brand-level documents the person can read
and edit in Brand context. The tool writes only under ``company/`` and ``proof/``, only to the
brand of the conversation's project, and always as a new version: older versions are superseded,
never changed, and a project's confirmed pin is never touched.

The body comes inline or from a file the agent wrote in the code sandbox's ``outputs/`` folder (a
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
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.manual import tool_manual_link
from clue_api.brand_knowledge_writes import (
    SERVABLE_STATUSES,
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
_PATH = re.compile(r"^(company|proof)/[a-z0-9][a-z0-9-]*\.md$")
_FROM_FILE = re.compile(r"^outputs/(?:[A-Za-z0-9_][A-Za-z0-9._-]*/)*[A-Za-z0-9_][A-Za-z0-9._-]*$")
_KIND = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_MAX_BODY_CHARS = 1_000_000
_MAX_FILE_BYTES = 2_000_000


class WriteBrandDocumentInput(ToolInput):
    #: ``company/<name>.md`` or ``proof/<name>.md``, lower-case letters, digits and hyphens.
    path: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    #: What the document is, e.g. ``sales-motion``. Needed only for a new document; an existing
    #: document keeps its kind.
    kind: str | None = None
    #: The Markdown body, without front matter. Give this or ``from_file``, not both.
    body: str | None = Field(default=None, max_length=_MAX_BODY_CHARS)
    #: A Markdown file you wrote in the sandbox, e.g. ``outputs/sales-motion.md``.
    from_file: str | None = None
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


@dataclass(frozen=True)
class _Current:
    document_id: UUID
    kind: str
    version: int
    sha256: str | None


def _check_input(inputs: WriteBrandDocumentInput) -> None:
    if not _PATH.fullmatch(inputs.path):
        raise _Refused(
            "path_not_allowed",
            "Only company/<name>.md and proof/<name>.md can be written, with a name of lower-case "
            "letters, digits and hyphens (e.g. company/sales-motion.md).",
        )
    if (inputs.body is None) == (inputs.from_file is None):
        raise _Refused("body_or_file_required", "Give exactly one of body or from_file.")
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
        raise _Refused("body_empty", "The document body is empty.")
    if body.startswith("---\n"):
        raise _Refused(
            "front_matter_not_allowed",
            "Write the body only, without a front-matter block; the platform keeps that.",
        )
    return body


class WriteBrandDocumentTool(Tool):
    name = "write_brand_document"
    version = "1"
    model_description = (
        "Publish a Brand-context document under company/ or proof/ (for example "
        "company/sales-motion.md, or an updated proof/customers.md). It becomes the brand's "
        "current version of that document, which the person can read and edit in Brand context; "
        "the previous version is kept in its history. Write the whole document, not a change: "
        "to update one, read the current version from brand/ and write it back with your "
        "changes. Give the Markdown body inline, or from_file for a file you wrote under "
        "outputs/ with run_python. " + tool_manual_link("write_brand_document")
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
    parameter_policy = JournalParameterPolicy(safe_display_fields=("path", "kind", "from_file"))
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
        current = await _current(conn, workspace_id, scope.brand_id, inputs.path)
        front: dict[str, Any] = {}
        if current is not None:
            if inputs.kind is not None and inputs.kind != current.kind:
                raise _Refused(
                    "kind_mismatch",
                    f"{inputs.path} is a {current.kind} document; leave kind out to keep it.",
                )
            kind = current.kind
            read = await read_brand_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=scope.brand_id,
                document_id=current.document_id,
            )
            front = dict(read[0]) if read is not None else {}
        elif inputs.kind is None:
            raise _Refused("kind_required", f"{inputs.path} is new: say what it is with kind.")
        else:
            kind = inputs.kind
        front.setdefault("kind", kind)
        front["written_by"] = {"user_id": scope.user_id, "turn_id": str(scope.turn_id)}
        data = render_brand_document(path=inputs.path, kind=kind, front=front, body=body)
        if current is not None and current.sha256 == content_address(data):
            return WriteBrandDocumentOutput(
                document_id=str(current.document_id),
                path=inputs.path,
                version=current.version,
                unchanged=True,
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
        if inputs.body is not None:
            return _check_body(inputs.body)
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
                "This turn has no sandbox outputs/ folder; give the document as body instead.",
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


async def _current(
    conn: AsyncConnection, workspace_id: str, brand_id: str, path: str
) -> _Current | None:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT document_id, kind, version, artifact_sha256 "
                    "FROM brand_knowledge_document WHERE workspace_id = :ws AND brand_id = :brand "
                    "AND path = :path AND project_id IS NULL AND status IN :servable "
                    "ORDER BY version DESC LIMIT 1"
                ).bindparams(bindparam("servable", expanding=True)),
                {
                    "ws": workspace_id,
                    "brand": brand_id,
                    "path": path,
                    "servable": list(SERVABLE_STATUSES),
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return _Current(
        document_id=row["document_id"],
        kind=str(row["kind"]),
        version=int(row["version"]),
        sha256=row["artifact_sha256"],
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
