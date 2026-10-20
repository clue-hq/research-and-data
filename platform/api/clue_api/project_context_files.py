"""The project context files one production conversation turn opens with.

Spec: docs/superpowers/specs/archive/2026-09-12-project-context-and-icp-authoring-design.md §4.1.

A turn does not learn the project's state by being told about it — it reads files. The compiled
set (``status.md``, ``decisions.md``, the project's own documents and the artifact index) is served
read-only under ``project/`` and indexed in the opening context.

This module is the seam between those compiled bytes and one turn, and it applies to project files
exactly the discipline :mod:`clue_api.brand_knowledge_context` applies to brand knowledge
documents:

* :func:`load_or_create_project_files_pin` — the compiled set frozen for one turn. The project
  moves while a turn runs (a discovery run finishes, a decision is recorded), so a turn that
  recompiled "the current files" on every attempt could seed one ``status.md``, crash, and seed a
  different one on the retry: the file the model was told to re-read would have moved underneath
  it. The pin is insert-once and written before composition; every later attempt reads the winner's
  row and never its own discarded compile.
* :func:`read_pinned_project_files` — the pinned bytes, verified against the pinned digest. A
  turn reads them at ``project/``, where :mod:`clue_api.project_library` compiles them once beside
  the threads and every thread of the project mounts them read-only; a turn whose library has
  moved since it pinned materializes the pinned set as its own tree for the length of that turn.
  :func:`project_seed_files` copied the same bytes into one thread instead; no production surface
  composes it since 2026-09-14.
* :func:`compile_project_files_index_card` / :func:`compile_project_library_index_card` — a
  bounded index of those files for the opening context. The card is an *index*, not the content:
  a path, a status and one summary line per file so the model knows what to open.

The index card never derives a summary of its own: it renders ``ProjectFileRef.summary``, the line
the pin recorded, so the card cannot advertise a line the pinned file does not carry. A *compiled*
file (``status.md``, ``decisions.md``) gets a literal summary from its compiler — the file is
section-structured, and its first prose line is one section's content, not a description of the
file. :func:`summary_of` remains the summary rule for *prose* documents, whose first line really is
their subject.
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
from clue_agents.contracts import normalize_virtual_path
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_core import UtcDatetime
from clue_storage import ArtifactIntegrityError, StorageBackend, read_verified_artifact

__all__ = [
    "PROJECT_CONTEXT_FILE_BINDING_KIND",
    "PROJECT_FILES_INDEX_CARD_MEDIA_TYPE",
    "PROJECT_INPUT_PREFIX",
    "PROJECT_LIBRARY_INDEX_CARD_MEDIA_TYPE",
    "PROJECT_LIBRARY_PREFIX",
    "SEED_PREFIX",
    "CompiledProjectFile",
    "PinnedProjectFile",
    "ProjectFileEntry",
    "ProjectFileRef",
    "ProjectFilesIndexCard",
    "ProjectFilesPinConflict",
    "ProjectFilesPinRow",
    "ProjectLibraryIndexCard",
    "canonical_json",
    "compile_project_files_index_card",
    "compile_project_library_index_card",
    "get_project_files_pin",
    "load_or_create_project_files_pin",
    "project_seed_files",
    "project_workspace_path",
    "read_pinned_project_files",
    "summary_of",
]

#: Where a turn reads this project's files. Since 2026-09-14 that is the **mounted** project
#: library — the same state compiled once beside the threads (``<ws>/projects/<project>/library/``)
#: and mounted read-only at ``project/`` — so the two constants below are one path, kept as two
#: names because they are two *surfaces*: the per-turn seed surface (:func:`project_seed_files`,
#: which no production turn composes any more) and the library mount. One constant per surface,
#: so a path is never spelled by hand at a call site; the brand's two are named the same way
#: (``brand_knowledge_context.INPUT_PREFIX`` / ``BRAND_LIBRARY_PREFIX``).
PROJECT_INPUT_PREFIX = "project/"
PROJECT_LIBRARY_PREFIX = "project/"
PROJECT_FILES_INDEX_CARD_MEDIA_TYPE = "application/vnd.clue.project-files-index-card+json"
#: The media type of the card a turn actually opens on: the *library's* own manifest, pinned for
#: that turn. One media type per card kind, so an artifact row says which card it holds.
PROJECT_LIBRARY_INDEX_CARD_MEDIA_TYPE = "application/vnd.clue.project-library-index-card+json"
#: Where the *seed* surface puts these files. Deliberately NOT :data:`PROJECT_INPUT_PREFIX`, which
#: now names the mount: a ``WorkspaceSeedFile`` may only materialize below ``context/`` or
#: ``inputs/`` (``clue_agents.resources``), so a seed built at the mount's prefix is refused at
#: construction.
SEED_PREFIX = "inputs/project/"
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


def project_workspace_path(row_path: str, *, prefix: str = PROJECT_INPUT_PREFIX) -> str:
    """The one rule for where a project document is materialized (ruling F).

    A project document's stored path is folder-qualified — ``project/plan.md`` for the plan,
    ``audience/icp-gi.md`` for an audience document — while every project file is served below
    :data:`PROJECT_LIBRARY_PREFIX`. One leading ``project/`` segment is therefore the *folder
    name*, not a directory under the prefix: without stripping it the plan would be advertised at
    ``project/project/plan.md``, a path nothing serves. Everything else is kept verbatim, so a
    document's folder survives into the workspace.

    ``prefix`` is the one thing that could differ between the two surfaces that serve these files
    — the thread's own seeds (:data:`PROJECT_INPUT_PREFIX`) and the mounted project library
    (:data:`PROJECT_LIBRARY_PREFIX`) — and since 2026-09-14 the two agree on one path. The naming
    rule above is identical for both, which is the point: a document is at the same relative path
    whichever surface a turn reads it from.

    This is the only place that rule is written down: ``status.md``'s renderer, the compiled files'
    seed paths and the index card all call it, so two surfaces cannot name one document differently.
    """

    return prefix + row_path.removeprefix("project/")


def _after_front_matter(decoded: str) -> str:
    """A document's text with its leading YAML front matter dropped.

    Every authored project document (an ICP variant, its personas, the plan) is markdown *with*
    front matter, whose first line is the ``---`` fence and whose next lines are ``kind:``,
    ``status:`` and friends — metadata about the document, never its subject. Without this every
    index line for an authored document would read ``---``.

    A fence that is never closed is not front matter (it is a horizontal rule on the first line),
    so the text is returned untouched rather than swallowed to the end of the file.
    """

    lines = decoded.splitlines()
    if not lines or lines[0].strip() != "---":
        return decoded
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1 :])
    return decoded


def summary_of(body: bytes) -> str:
    """The summary rule for a *prose* document: its first prose line, bounded.

    The leading ``#`` heading is the file's title, not a summary of it, so heading lines are
    skipped — otherwise every line of the index would read ``# Project status``. A leading YAML
    front-matter block is skipped for the same reason (see :func:`_after_front_matter`). A file
    that is only a heading (or is not text at all) summarizes to the empty string, which is
    honest: there is nothing to preview, and the model opens the file.

    This rule is wrong for a *section-structured compiled* file, whose first prose line is one
    section's content (``status.md`` would summarize as "Not confirmed."). Such a file carries a
    literal summary written by its compiler instead.
    """

    try:
        decoded = body.decode()
    except UnicodeDecodeError:
        return ""
    for line in _after_front_matter(decoded).splitlines():
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
    """One pinned file, identified precisely enough to re-read exactly these bytes.

    ``extra="ignore"``: the pin is read back by whichever worker retries the turn, which during a
    rollout may be running *older* code than the worker that wrote it. An unknown key added by a
    newer compiler must degrade to "a field I do not use", never fail the turn — the pin is
    append-only, so a refusal here would fail every attempt of that turn forever.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    path: str
    kind: str
    version: int | None
    status: str
    summary: str
    artifact_key: str
    artifact_sha256: str

    @field_validator("path")
    @classmethod
    def _materializable_path(cls, value: str) -> str:
        """A path the workspace can actually seed, refused where it can still be refused.

        A pinned path is materialized verbatim under :data:`PROJECT_INPUT_PREFIX`, and
        ``WorkspaceSeedFile`` rejects an absolute, dot-relative or backslash path with a
        ``WorkspaceSecurityError`` — but by then the pin is written, and the pin is read before
        the compiler runs, so *every* retry of that turn would fail identically. The same rule is
        therefore enforced at the one boundary that can still say no.
        """

        return normalize_virtual_path(value)

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


def canonical_json(value: object) -> bytes:
    """One byte-stable JSON encoding, shared by every digest and card compiled over these files.

    Public because the project library hashes and writes JSON of its own (its index card, its
    artifact index, its refresh digest) and two encoders would eventually disagree about key order
    or separators — which, for a content-addressed tree, reads as "the project changed".
    """

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _ref_payload(ref: ProjectFileRef) -> dict[str, Any]:
    return ref.model_dump(mode="json")


def _files_digest(payloads: Sequence[dict[str, Any]]) -> str:
    """A bare 64-hex digest over the pinned set, exactly as it is stored.

    Two attempts of one turn compare this value to prove they composed the same project context.
    It hashes the *same* payload list the ``files`` column is written from — one explicitly
    path-sorted list built once by the caller — so the column and the digest cannot disagree about
    order.
    """

    return hashlib.sha256(canonical_json(list(payloads))).hexdigest()


class ProjectFilesPinRow(BaseModel):
    """One turn's immutable project-files receipt.

    ``extra="ignore"`` for the same mixed-version reason as :class:`ProjectFileRef`: a retry may be
    read back by an older worker than the one that wrote the row.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

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
    paths = [file.path for file in compiled]
    if len(set(paths)) != len(paths):
        # Refused before anything is persisted: a pin is insert-once and is read before the
        # compiler runs, so a set that cannot be materialized (two files claiming one path) would
        # otherwise fail every later attempt of this turn identically, forever.
        raise ProjectFilesPinConflict(
            "a compiled project-file set cannot name one path twice: "
            + ", ".join(sorted({path for path in paths if paths.count(path) > 1}))
        )
    refs: list[ProjectFileRef] = []
    for file in compiled:
        try:
            ref = await artifacts.persist_body(
                workspace_id=workspace_id,
                data=file.body,
                media_type=_FILE_MEDIA_TYPE,
                project_bindings=((project_id, PROJECT_CONTEXT_FILE_BINDING_KIND),),
            )
        except ValueError as exc:
            # The artifact store refuses to resurrect erased bytes. A compiled file is
            # content-addressed, so an *identical* file compiled for an erased project can land on
            # a tombstoned key: say which file, in this module's own vocabulary, instead of
            # letting an untyped store error escape the turn.
            if "cannot be resurrected" not in str(exc):
                raise
            raise ProjectFilesPinConflict(
                f"the compiled project file {file.path!r} was erased in this workspace and "
                "cannot be re-pinned"
            ) from exc
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
    # One explicitly path-sorted list: the stored column and the digest are built from it, so the
    # invariant "the pin is in path order" is local to these two lines.
    payloads = [_ref_payload(ref) for ref in sorted(refs, key=lambda ref: ref.path)]
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
                    "files": canonical_json(payloads).decode(),
                    "digest": _files_digest(payloads),
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


def project_seed_files(
    files: Sequence[PinnedProjectFile],
    *,
    prefix: str = SEED_PREFIX,
) -> tuple[WorkspaceSeedFile, ...]:
    """The read-only workspace files the model reads by path, one per pinned file.

    **No production surface composes this since 2026-09-14**: a turn reads these files at the
    mounted project library instead, so these bytes are never copied into a thread. It is kept for
    the reason ``brand_knowledge_context.knowledge_seed_files`` is kept — it is where the seed
    surface's naming rule is spelled, and that rule is the library's too.
    """

    return tuple(
        WorkspaceSeedFile(
            path=project_workspace_path(file.ref.path, prefix=prefix),
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
        return canonical_json(self.model_dump(mode="json", exclude_none=False))

    def content_sha256(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"


def compile_project_files_index_card(
    *,
    project_id: str,
    files: Sequence[PinnedProjectFile],
    prefix: str = SEED_PREFIX,
) -> ProjectFilesIndexCard:
    """Compile the opening index over one turn's *seeded* project files, in path order.

    Every line is read off the pinned :class:`ProjectFileRef` — including the summary, which the
    compiler wrote and the pin recorded. The card derives nothing of its own, so it cannot
    describe a file differently from the receipt the turn is composed against.

    ``prefix`` defaults to :data:`SEED_PREFIX` for the same reason :func:`project_seed_files` does:
    this card describes the seed surface, and it must name files where that surface puts them. The
    card a production turn opens on is the *library's* manifest
    (:func:`compile_project_library_index_card`), not this one — no production surface has
    composed this since 2026-09-14.
    """

    return ProjectFilesIndexCard(
        project_id=project_id,
        files=[
            ProjectFileEntry(
                path=file.ref.path,
                workspace_path=project_workspace_path(file.ref.path, prefix=prefix),
                kind=file.ref.kind,
                version=file.ref.version,
                status=file.ref.status,
                summary=file.ref.summary,
                artifact_sha256=file.ref.artifact_sha256,
            )
            for file in sorted(files, key=lambda file: file.ref.path)
        ],
    )


class ProjectLibraryIndexCard(BaseModel):
    """The manifest of one *project library* generation — the whole tree, never the files.

    The sibling of :class:`ProjectFilesIndexCard` on the other surface. The pinned card describes
    one turn's frozen set, so every line is read off a ``ProjectFileRef``; this one describes a
    tree on disk, so every line is read off the compiled bytes that were installed in it. Two more
    facts ride along, because they are what the tree is *for*:

    * ``library_sha256`` — the digest over the rows this generation was compiled from.
      :class:`~clue_agents.library_tree.LibraryTree` reads it back out of this very card to decide
      whether anything has to be rewritten, so the card is the tree's own record of its freshness.
    * ``artifacts`` — how many design artifacts ``artifacts/index.json`` names. The index is by
      reference (W4), so the count is the one number a reader gets without opening it.

    It is compiled **unbounded**: the 8 KiB budget belongs to a turn's *opening* card, where every
    line is spent whether or not the model reads it, while this manifest is read from disk by path
    and an omitted line would only make it under-list the files sitting beside it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    card_kind: Literal["project_library_index"] = "project_library_index"
    project_id: str
    files: list[ProjectFileEntry]
    library_sha256: str
    artifacts: int

    def canonical_bytes(self) -> bytes:
        # ``exclude_none=False``: a compiled file's null ``version`` is the typed "this file has
        # no version" state, not an absent field.
        return canonical_json(self.model_dump(mode="json", exclude_none=False))

    def content_sha256(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"


def compile_project_library_index_card(
    *,
    project_id: str,
    files: Sequence[CompiledProjectFile],
    library_sha256: str,
    artifacts: int,
) -> ProjectLibraryIndexCard:
    """Compile the manifest of one library generation over the files it installs, in path order.

    ``path`` is the file's path *inside the tree*, which for a document is its row path with the
    ``project/`` folder segment already folded away (:func:`project_workspace_path`) — inside the
    library the tree path is the name. ``workspace_path`` is where the mount serves it, so it is
    that same path under :data:`PROJECT_LIBRARY_PREFIX` and nothing else: the manifest describes
    the tree it ships in, so it cannot name a file at a path the mount does not serve.

    ``artifact_sha256`` is the digest of the bytes installed at that path. For a document that is
    exactly its artifact row's ``artifact_sha256`` (the store is content-addressed); for a
    compiled file it is the only digest there is. One rule, so a reader can compare what it read
    against what the manifest says it should have read.
    """

    return ProjectLibraryIndexCard(
        project_id=project_id,
        library_sha256=library_sha256,
        artifacts=artifacts,
        files=[
            ProjectFileEntry(
                path=file.path,
                workspace_path=PROJECT_LIBRARY_PREFIX + file.path,
                kind=file.kind,
                version=file.version,
                status=file.status,
                summary=file.summary,
                artifact_sha256=hashlib.sha256(file.body).hexdigest(),
            )
            for file in sorted(files, key=lambda file: file.path)
        ],
    )
