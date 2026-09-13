"""The brand library: one pinned knowledge version, rendered once for the whole workspace.

A turn's seeds copy every pinned brand document into *that thread's* workspace, once per turn, per
thread. The library does it the other way round: the same documents are written once per knowledge
version, beside the threads, at ``<ws>/library/brand/<brand>/<version>/``, and every thread of
every project of that brand mounts that one frozen tree read-only at ``brand/``. Nothing is copied
into a workspace, and a brand's knowledge is written as many times as it has versions rather than
as many times as it has turns.

Three rules make that safe:

* **Content-addressed.** ``<version>`` is the knowledge pin's ``documents_sha256`` (truncated), and
  the tree records the full digest in its ``index.json``. A materializer that finds the recorded
  digest already in place writes nothing at all, so the bytes a turn mounts can never be a
  different rendering of the same version.
* **Brand-wide, never project-relative.** The tree is shared by every project of the brand, so the
  *newest* version of each path owns the plain name in it and an older version rides beside it
  version-qualified — a project's own ICP pin is not allowed to move a name in a tree its sibling
  projects read. The pin still owns the plain name in that project's own thread seeds, and the
  project's ICP is named by the turn's context card. Nothing per-project lives here.
* **Read-only.** :class:`~clue_agents.library_tree.LibraryTree` installs the generation atomically
  as 0400 files in 0500 directories, and the mount is opened ``read_only``.

Postgres stays the truth. This tree is a *rendering* of the pinned rows: nothing server-side reads
it to decide anything, and deleting it costs only the rewrite.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Sequence
from contextlib import suppress
from typing import Final

from clue_agents import AgentWorkspaceFactory, WorkspaceConflict
from clue_agents.library_tree import LibraryFile, LibraryTree
from clue_api.brand_knowledge_context import (
    BRAND_LIBRARY_PREFIX,
    KnowledgePinRow,
    PinnedDocument,
    compile_brand_knowledge_index_card,
    workspace_paths,
)

__all__ = ["brand_library_files", "brand_library_version", "ensure_brand_library"]

#: The library parent's own segment, below ``<ws>/library/``, and the mount's reserved name.
_BRAND_DIR: Final = "brand"
#: The mount serves the tree at ``brand/``, so a mounted path is the tree-relative path with the
#: mount's name in front of it. One derivation, from the one prefix constant.
_TREE_ROOT: Final = f"{_BRAND_DIR}/"
_INDEX_NAME: Final = "index.json"
#: Enough of the digest to be collision-free in practice, short enough to read in a path.
_VERSION_CHARS: Final = 16
#: One materializer at a time in this process. ``LibraryTree.replace`` reclaims residue by name
#: prefix, so two concurrent replaces of one tree would discard each other's in-flight build.
#: Across processes two workers may still race on a brand version that is being written for the
#: first time; the install is atomic and the generation is content-addressed, so the loser simply
#: writes the identical bytes again. A DB lock would buy nothing a rewrite of the same tree costs.
_MATERIALIZE_LOCK: Final = threading.Lock()


def brand_library_version(pin: KnowledgePinRow) -> str:
    """The directory segment one pinned knowledge version is served under."""

    return pin.documents_sha256[:_VERSION_CHARS]


def brand_library_files(
    *,
    pin: KnowledgePinRow,
    documents: Sequence[PinnedDocument],
) -> tuple[LibraryFile, ...]:
    """The whole generation: every brand document, plus the index that describes them.

    A project-scoped document is skipped for the same reason the seeds skip it — it belongs to one
    project, and this tree belongs to the brand. ``pinned_document_id=None`` is the brand-wide
    naming rule: the newest version of a path answers to the plain name here.

    The index is compiled **unbounded** (``max_bytes=None``). The 8 KiB default is the budget for a
    turn's *opening context* card, where every line is spent whether or not the model reads it;
    this card is a manifest of a tree, read from disk by path, so a dropped line would only make
    the manifest under-list the files sitting beside it. The count is asserted rather than trusted:
    an index that does not list everything it serves is refused, never installed.
    """

    paths = workspace_paths(documents, pinned_document_id=None, prefix=BRAND_LIBRARY_PREFIX)
    card = compile_brand_knowledge_index_card(
        brand_id=pin.brand_id,
        documents=documents,
        # Both are per-project facts. They ride the turn's own context card, never a shared tree.
        confirmed_icp=None,
        product_set=None,
        prefix=BRAND_LIBRARY_PREFIX,
        library_sha256=pin.documents_sha256,
        max_bytes=None,
    )
    if card.omitted_count:
        raise WorkspaceConflict("a brand library index must list every document it serves")
    return (
        LibraryFile(path=_INDEX_NAME, content=card.canonical_bytes()),
        *(
            LibraryFile(
                path=paths[document.ref.document_id].removeprefix(_TREE_ROOT),
                content=document.body,
            )
            for document in documents
            if document.ref.project_id is None
        ),
    )


async def ensure_brand_library(
    workspaces: AgentWorkspaceFactory,
    *,
    pin: KnowledgePinRow,
    documents: Sequence[PinnedDocument],
) -> str:
    """Materialize this pin's brand library if it is absent, and return its version segment.

    The bytes are the caller's already-verified pinned documents, so no storage backend is needed
    here: ``read_pinned_documents`` has read and digest-checked them before this is called.

    The work is blocking filesystem work — it runs in a worker thread so the turn's event loop is
    not held while a tree is written.
    """

    version = brand_library_version(pin)
    files = brand_library_files(pin=pin, documents=documents)
    await asyncio.to_thread(
        _materialize,
        workspaces,
        workspace_id=pin.workspace_id,
        brand_id=pin.brand_id,
        version=version,
        files=files,
        digest=pin.documents_sha256,
    )
    return version


def _materialize(
    workspaces: AgentWorkspaceFactory,
    *,
    workspace_id: str,
    brand_id: str,
    version: str,
    files: Sequence[LibraryFile],
    digest: str,
) -> None:
    """Open ``<ws>/library/brand/<brand>/`` and install the generation under ``<version>``."""

    with _MATERIALIZE_LOCK:
        brand_fd = _brand_parent_fd(workspaces, workspace_id=workspace_id, brand_id=brand_id)
        try:
            tree = LibraryTree(parent_fd=brand_fd, name=version)
            # Content-addressed: this version's bytes are already on disk, so writing them again
            # would only churn the tree every reader of every project is holding.
            if tree.current_digest() == digest:
                return
            tree.replace(files, digest=digest)
        finally:
            os.close(brand_fd)


def _brand_parent_fd(
    workspaces: AgentWorkspaceFactory,
    *,
    workspace_id: str,
    brand_id: str,
) -> int:
    """The anchored descriptor on this brand's library parent. The caller owns and closes it.

    Each level is opened from the level above and closed as soon as its child is open, so no
    descriptor outlives the step that needed it and nothing here is reachable by name.
    """

    parent_fd = workspaces.library_parent_fd(workspace_id)
    for segment in (_BRAND_DIR, brand_id):
        try:
            child_fd = workspaces.ensure_child_directory(parent_fd, segment)
        finally:
            with suppress(OSError):
                os.close(parent_fd)
        parent_fd = child_fd
    return parent_fd
