"""The project context files one production conversation turn opens with.

Spec: docs/superpowers/specs/2026-09-12-project-context-and-icp-authoring-design.md §4.1.

A turn does not learn the project's state by being told about it — it reads files. The compiled
set (``status.md``, ``decisions.md``, and later the project's own documents) is materialized
read-only under ``inputs/project/`` and indexed in the opening context.

This module is the seam between those compiled bytes and one turn, and it applies to project files
exactly the discipline :mod:`clue_api.brand_knowledge_context` applies to brand knowledge
documents:

* :func:`load_or_create_project_files_pin` — the compiled set frozen for one turn. The project
  moves while a turn runs (a discovery run finishes, a decision is recorded), so a turn that
  recompiled "the current files" on every attempt could seed one ``status.md``, crash, and seed a
  different one on the retry: the file the model was told to re-read would have moved underneath
  it. The pin is insert-once and written before composition; every later attempt reads the winner's
  row and never its own discarded compile.
* :func:`read_pinned_project_files` / :func:`project_seed_files` — the pinned bytes, verified
  against the pinned digest, materialized under ``inputs/project/``.
* :func:`compile_project_files_index_card` — a bounded index of those files for the opening
  context. The card is an *index*, not the content: a path, a status and one summary line per file
  so the model knows what to open.

:func:`summary_of` is the one summary rule. The compiler (which builds
:class:`CompiledProjectFile`) and the index card both call it, so the line the card shows can never
disagree with the line the pin recorded.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import WorkspaceSeedFile
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_core import UtcDatetime
from clue_storage import ArtifactIntegrityError, StorageBackend, read_verified_artifact

__all__ = [
    "PROJECT_CONTEXT_FILE_BINDING_KIND",
    "PROJECT_FILES_INDEX_CARD_MEDIA_TYPE",
    "PROJECT_INPUT_PREFIX",
    "CompiledProjectFile",
    "PinnedProjectFile",
    "ProjectFileEntry",
    "ProjectFileRef",
    "ProjectFilesIndexCard",
    "ProjectFilesPinConflict",
    "ProjectFilesPinRow",
    "compile_project_files_index_card",
    "get_project_files_pin",
    "load_or_create_project_files_pin",
    "project_seed_files",
    "read_pinned_project_files",
    "summary_of",
]

#: Every compiled project file is materialized read-only below this workspace prefix.
PROJECT_INPUT_PREFIX = "inputs/project/"
PROJECT_FILES_INDEX_CARD_MEDIA_TYPE = "application/vnd.clue.project-files-index-card+json"
#: The DSAR binding kind these artifacts carry, so an erasure of the project reaches them.
PROJECT_CONTEXT_FILE_BINDING_KIND = "project_context_file"

#: Project files are markdown, in the artifact store and in the workspace.
_FILE_MEDIA_TYPE = "text/markdown"
#: One index line per file: long enough to tell two files apart, short enough to stay an index.
_SUMMARY_MAX_CHARS = 160
_PIN_COLUMNS = "turn_id, workspace_id, project_id, files, files_sha256, pinned_at"
_BARE_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProjectFilesPinConflict(ValueError):
    """This turn's pinned project files cannot be read as the turn pinned them."""


def summary_of(body: bytes) -> str:
    """The one summary rule: the file's first prose line, bounded.

    The leading ``#`` heading is the file's title, not a summary of it, so heading lines are
    skipped — otherwise every line of the index would read ``# Project status``. A file that is
    only a heading (or is not text at all) summarizes to the empty string, which is honest: there
    is nothing to preview, and the model opens the file.
    """

    try:
        decoded = body.decode()
    except UnicodeDecodeError:
        return ""
    for line in decoded.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if len(stripped) > _SUMMARY_MAX_CHARS:
            return stripped[: _SUMMARY_MAX_CHARS - 1] + "…"
        return stripped
    return ""


@dataclass(frozen=True, slots=True)
class CompiledProjectFile:
    """One freshly compiled project file, before it is persisted and pinned."""

    path: str
    kind: str
    body: bytes
    version: int | None
    status: str
    summary: str


class ProjectFileRef(BaseModel):
    """One pinned file, identified precisely enough to re-read exactly these bytes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    kind: str
    version: int | None
    status: str
    summary: str
    artifact_key: str
    artifact_sha256: str

    @field_validator("artifact_sha256")
    @classmethod
    def _bare_hex_digest(cls, value: str) -> str:
        """Bare 64-hex, always.

        ``ArtifactRef.sha256`` is the artifact row's ``content_sha256`` (bare), but a
        ``sha256:``-prefixed card digest reads identically at a call site. The pin's DB CHECK is
        bare hex and :func:`read_verified_artifact` compares the bare column, so the prefix is
        normalized away here rather than at each caller.
        """

        digest = value.removeprefix("sha256:")
        if _BARE_SHA256.match(digest) is None:
            raise ValueError("a pinned artifact digest must be a bare 64-hex sha256")
        return digest


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _ref_payload(ref: ProjectFileRef) -> dict[str, Any]:
    return ref.model_dump(mode="json")


def _files_digest(refs: Sequence[ProjectFileRef]) -> str:
    """A bare 64-hex digest over the pinned set, in path order.

    Two attempts of one turn compare this value to prove they composed the same project context,
    so it is order-independent by construction rather than by the caller's care.
    """

    payload = [_ref_payload(ref) for ref in sorted(refs, key=lambda ref: ref.path)]
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


class ProjectFilesPinRow(BaseModel):
    """One turn's immutable project-files receipt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: UUID
    workspace_id: str
    project_id: str
    files: tuple[ProjectFileRef, ...]
    files_sha256: str
    pinned_at: UtcDatetime


def _pin_row(row: dict[str, Any]) -> ProjectFilesPinRow:
    """Decode the one ``jsonb`` column, which asyncpg may hand back as text or bytes."""

    files = row.get("files")
    if isinstance(files, bytes | bytearray | str):
        row["files"] = json.loads(files)
    return ProjectFilesPinRow.model_validate(row)


async def get_project_files_pin(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_id: UUID,
) -> ProjectFilesPinRow | None:
    """Read a pin inside one workspace; a foreign pin is indistinguishable from absence."""

    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_PIN_COLUMNS} FROM agent_turn_project_files "
                    "WHERE turn_id = :turn_id AND workspace_id = :workspace_id"
                ),
                {"turn_id": turn_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else _pin_row(dict(row))


async def load_or_create_project_files_pin(
    conn: AsyncConnection,
    artifacts: DurableAgentArtifactStore,
    *,
    workspace_id: str,
    turn_id: UUID,
    project_id: str,
    compile: Callable[[], Awaitable[Sequence[CompiledProjectFile]]],
) -> tuple[ProjectFilesPinRow, bool]:
    """Return this turn's pinned files, compiling and persisting them on the first attempt only.

    ``compile`` is called at most once per turn: a pinned turn re-reads its row and never
    recompiles, so a retry seeds byte-identical files even after the project has moved on.
    Concurrent attempts may both compile, but only the winning ``INSERT`` owns the turn; the loser
    reads the winner's row and discards its own observation. Its persisted bytes are harmless —
    the store is content-addressed, so identical content is one artifact.

    Database ``now()`` supplies the receipt time.
    """

    existing = await get_project_files_pin(conn, workspace_id=workspace_id, turn_id=turn_id)
    if existing is not None:
        return existing, False

    compiled = sorted(await compile(), key=lambda file: file.path)
    refs: list[ProjectFileRef] = []
    for file in compiled:
        ref = await artifacts.persist_body(
            workspace_id=workspace_id,
            data=file.body,
            media_type=_FILE_MEDIA_TYPE,
            project_bindings=((project_id, PROJECT_CONTEXT_FILE_BINDING_KIND),),
        )
        refs.append(
            ProjectFileRef(
                path=file.path,
                kind=file.kind,
                version=file.version,
                status=file.status,
                summary=file.summary,
                artifact_key=ref.artifact_key,
                artifact_sha256=ref.sha256,
            )
        )
    inserted = (
        (
            await conn.execute(
                text(
                    "INSERT INTO agent_turn_project_files "
                    "(turn_id, workspace_id, project_id, files, files_sha256) "
                    "VALUES (:turn_id, :workspace_id, :project_id, CAST(:files AS jsonb), "
                    " :digest) "
                    "ON CONFLICT (turn_id) DO NOTHING "
                    f"RETURNING {_PIN_COLUMNS}"
                ),
                {
                    "turn_id": turn_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "files": _canonical_json([_ref_payload(ref) for ref in refs]).decode(),
                    "digest": _files_digest(refs),
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if inserted is not None:
        return _pin_row(dict(inserted)), True

    winner = await get_project_files_pin(conn, workspace_id=workspace_id, turn_id=turn_id)
    if winner is None:
        raise ProjectFilesPinConflict(
            "this turn's project-files pin exists outside the requested workspace"
        )
    return winner, False


@dataclass(frozen=True, slots=True)
class PinnedProjectFile:
    """One pinned file's verified bytes."""

    ref: ProjectFileRef
    body: bytes


async def read_pinned_project_files(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    pin: ProjectFilesPinRow,
) -> tuple[PinnedProjectFile, ...]:
    """Read every pinned file's bytes, refusing any that are not the bytes the turn pinned.

    Both refusals are one species — *this turn cannot be composed as it was pinned* — so both are
    :class:`ProjectFilesPinConflict`: the stored digest having moved since the pin, and the blob
    itself no longer matching its durable row (moved, tampered, erased). Seeding a file whose bytes
    are not the pinned bytes would silently hand the model a different project than the one its
    receipt records.
    """

    files: list[PinnedProjectFile] = []
    for ref in pin.files:
        try:
            record, body = await read_verified_artifact(
                conn,
                storage,
                storage_key=ref.artifact_key,
                workspace_id=pin.workspace_id,
            )
        except ArtifactIntegrityError as exc:
            raise ProjectFilesPinConflict(
                f"the pinned project file {ref.path!r} can no longer be read as it was pinned"
            ) from exc
        if record.content_sha256 != ref.artifact_sha256:
            raise ProjectFilesPinConflict(
                f"the pinned project file {ref.path!r} no longer matches its pinned digest"
            )
        files.append(PinnedProjectFile(ref=ref, body=body))
    return tuple(files)


def _workspace_path(ref: ProjectFileRef) -> str:
    return PROJECT_INPUT_PREFIX + ref.path


def project_seed_files(files: Sequence[PinnedProjectFile]) -> tuple[WorkspaceSeedFile, ...]:
    """The read-only workspace files the model reads by path, one per pinned file."""

    return tuple(
        WorkspaceSeedFile(
            path=_workspace_path(file.ref),
            content=file.body,
            sha256=file.ref.artifact_sha256,
            media_type=_FILE_MEDIA_TYPE,
        )
        for file in files
    )


class ProjectFileEntry(BaseModel):
    """One line of the index: what the file is, where it is, and why it might be worth opening."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    workspace_path: str
    kind: str
    version: int | None
    status: str
    summary: str
    artifact_sha256: str


class ProjectFilesIndexCard(BaseModel):
    """The bounded index of a turn's pinned project files — an index, never the files."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    card_kind: Literal["project_files_index"] = "project_files_index"
    project_id: str
    files: list[ProjectFileEntry]

    def canonical_bytes(self) -> bytes:
        # ``exclude_none=False``: an unversioned (compiled) file's null ``version`` is the typed
        # "this file has no version" state, not an absent field.
        return _canonical_json(self.model_dump(mode="json", exclude_none=False))

    def content_sha256(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"


def compile_project_files_index_card(
    *,
    project_id: str,
    files: Sequence[PinnedProjectFile],
) -> ProjectFilesIndexCard:
    """Compile the opening index over one turn's pinned project files, in path order.

    Every summary is derived from the pinned bytes through :func:`summary_of`, the same rule the
    compiler used, so the card cannot advertise a line the seeded file does not open with.
    """

    return ProjectFilesIndexCard(
        project_id=project_id,
        files=[
            ProjectFileEntry(
                path=file.ref.path,
                workspace_path=_workspace_path(file.ref),
                kind=file.ref.kind,
                version=file.ref.version,
                status=file.ref.status,
                summary=summary_of(file.body),
                artifact_sha256=file.ref.artifact_sha256,
            )
            for file in sorted(files, key=lambda file: file.ref.path)
        ],
    )
