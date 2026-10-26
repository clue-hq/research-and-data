"""The brand library: one pinned knowledge version, rendered into each chat's own folder.

The pinned brand documents are written into the chat's own ``brand/`` folder, beside its ``agent/``
root (F3, spec WS-37; ruling AW-9), and mounted read-only at ``brand/``. No folder is shared with
another chat, so a chat's folder can be deleted whole without touching anyone else's turn; a brand
of about a megabyte is cheap to hold once per chat.

Three rules make that safe:

* **Write only what changed (WS-36).** The folder is synced to exactly the pin's files: a file whose
  bytes already match is left alone, so an unchanged brand costs one hash per file and no writes.
* **Brand-wide, never project-relative.** The rendering is the brand's: the *newest* version of
  each path owns the plain name and an older version rides beside it version-qualified — a
  project's own ICP pin is not allowed to move a name here. The pin still owns the plain name in
  that project's own thread seeds, and the project's ICP is named by the turn's context card.
* **Read-only.** The folder ends frozen (0400 files in 0500 folders) and the mount is opened
  ``read_only``.

Postgres stays the truth. This folder is a *rendering* of the pinned rows: nothing server-side
reads it to decide anything, and deleting it costs only the rewrite.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from typing import Final

from clue_agents import AgentWorkspaceFactory, WorkspaceConflict
from clue_agents.library_tree import LibraryFile
from clue_agents.tree_sync import sync_directory
from clue_agents.worker_area import ChatScope
from clue_api.brand_knowledge_context import (
    BRAND_LIBRARY_PREFIX,
    KnowledgePinRow,
    PinnedDocument,
    compile_brand_knowledge_index_card,
    workspace_paths,
)

__all__ = ["brand_library_files", "brand_library_version", "ensure_brand_library"]

#: The chat folder's own ``brand/`` segment, and the mount's reserved name.
_BRAND_DIR: Final = "brand"
#: The mount serves the tree at ``brand/``, so a mounted path is the tree-relative path with the
#: mount's name in front of it. One derivation, from the one prefix constant.
_TREE_ROOT: Final = f"{_BRAND_DIR}/"
_INDEX_NAME: Final = "index.json"
#: Enough of the digest to be collision-free in practice, short enough to read in a path.
_VERSION_CHARS: Final = 16


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
    chat: ChatScope,
    pin: KnowledgePinRow,
    documents: Sequence[PinnedDocument],
) -> str:
    """Sync this pin's brand library into the chat's own ``brand/`` folder; return its version.

    The bytes are the caller's already-verified pinned documents, so no storage backend is needed
    here: ``read_pinned_documents`` has read and digest-checked them before this is called.

    The work is blocking filesystem work — it runs in a worker thread so the turn's event loop is
    not held while files are written.
    """

    version = brand_library_version(pin)
    files = brand_library_files(pin=pin, documents=documents)
    await asyncio.to_thread(_sync, workspaces, chat=chat, files=files)
    return version


def _sync(
    workspaces: AgentWorkspaceFactory, *, chat: ChatScope, files: Sequence[LibraryFile]
) -> None:
    """Bring ``<chat>/brand`` to exactly these files, writing only what changed (WS-36)."""

    chat_fd = workspaces.chat_dir_fd(chat)
    try:
        sync_directory(
            chat_fd, _BRAND_DIR, {file.path: bytes(file.content) for file in files}, frozen=True
        )
    finally:
        os.close(chat_fd)
