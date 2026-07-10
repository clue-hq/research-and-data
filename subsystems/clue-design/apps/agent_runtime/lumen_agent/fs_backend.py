"""Isolated-workspace filesystem backend for the deepagent (W-isolation, D1).

The deepagent gets ONE dedicated workspace directory and its backend is
``FilesystemBackend(root_dir=<workspace>, virtual_mode=True)``: the agent's ``/``
IS the workspace. This retires the whole "path outside permitted root" failure
class — a ``/``-rooted path is now *correct*, and an absolute path is re-anchored
under the root by stock virtual mode rather than escaping it.

WHAT STOCK ``virtual_mode=True`` ALREADY GUARANTEES (verified against deepagents
0.6.12 ``backends/filesystem.py``):
- ``_resolve_path`` (l.197-209) blocks ``..``/``~`` (ValueError), joins the key
  under ``self.cwd`` (the resolved root), ``.resolve()``s it, and asserts
  ``full.relative_to(self.cwd)`` — a symlink-safe containment check — then probes
  for symlink loops. An absolute ``/etc/passwd`` becomes ``<root>/etc/passwd``
  (contained, simply not-found); a ``..`` climb raises before it can escape.
- The middleware ``validate_path`` (backends/utils.py l.499-504) rejects ``..`` as
  a path COMPONENT before the backend is ever called, returning a clean
  ToolMessage — so a traversal never reaches ``_resolve_path`` through the file
  tools.
- ``ls``/``grep``/``glob`` catch the containment ``ValueError`` gracefully;
  ``upload_files``/``download_files`` classify it via
  ``_map_exception_to_standard_error`` (l.1060) to ``INVALID_PATH``.

WHAT THIS SUBCLASS ADDS (only what stock does NOT provide):
1. ``_normalize_key`` (D1, ``paths.normalize_agent_key``) — forgives host-absolute
   and legacy path forms the model may still emit, mapping them to the correct
   virtual path so they RESOLVE instead of re-anchoring to a dead location. Stock
   has no equivalent; this is the subclass's reason to exist.
2. A crash-free re-raise of the containment failure. Stock's ``read``/``write``/
   ``edit`` catch only ``(OSError, RuntimeError)`` from ``_resolve_path`` (l.428,
   483, 530) — NOT ``ValueError`` — so the one reachable containment ValueError (a
   symlink INSIDE the workspace whose target resolves outside it, opened via
   read/write/edit) would propagate and kill the turn. We convert it to
   ``PermissionError`` (an ``OSError`` subclass caught by read/write/edit AND
   still classified to ``INVALID_PATH`` by upload/download), carrying a message
   that teaches the virtual form. We do NOT recompute containment — stock's check
   stands; we only change the exception TYPE so every method handles it uniformly.
"""

from __future__ import annotations

from pathlib import Path

from deepagents.backends.filesystem import FilesystemBackend
from py_lumen_obs import get_logger

from .paths import normalize_agent_key

logger = get_logger("lumen_agent.fs_backend")


class AgentWorkspaceBackend(FilesystemBackend):
    """``FilesystemBackend`` rooted at the isolated workspace in ``virtual_mode``.

    The agent's ``/`` is the workspace root. ``_normalize_key`` forgives stale
    host-absolute / legacy paths before stock resolution; stock virtual mode does
    the containment. The lone gap stock leaves — an uncaught containment
    ``ValueError`` in ``read``/``write``/``edit`` — is closed by re-raising it as a
    teaching ``PermissionError``.
    """

    def __init__(self, root_dir: str | Path, max_file_size_mb: int = 10) -> None:
        super().__init__(
            root_dir=root_dir, virtual_mode=True, max_file_size_mb=max_file_size_mb
        )
        # Stored from the constructor arg (not ``self.cwd``) so the class also works
        # under the harness's stubbed ``FilesystemBackend``, which does not set cwd.
        self._workspace_root = str(Path(root_dir))

    def _teaching_message(self, key: str) -> str:
        return (
            f"Path '{key}' resolves outside the workspace root and was rejected. "
            "Paths are workspace-rooted: use a '/'-rooted virtual path "
            "(e.g. /run_<id>/workspace/..., /knowledge_docs/..., "
            "/.deepagent/skills/...) or a plain relative path; never a '..' "
            "segment that climbs above the root."
        )

    def _resolve_path(self, key: str) -> Path:
        """Normalize the key (D1) then resolve exactly as stock virtual mode does.

        Stock performs the ``..`` block, the re-anchoring, the symlink-safe
        containment assert, and the symlink-loop probe. We only forgive the key
        first and, if stock's containment/traversal ``ValueError`` fires, re-raise
        it as a ``PermissionError`` so read/write/edit surface it as a clean,
        teaching error string instead of crashing the turn.
        """
        normalized = normalize_agent_key(key, self._workspace_root)
        # Debug detail: `_resolve_path` is the ONE seam every file operation
        # (read/write/edit/ls/grep/glob) funnels through, so logging the raw key,
        # its normalized virtual form, and the resolution outcome here traces the
        # backend's whole path activity without overriding each stock op. These
        # are debug-level: absent from the info console, present in run.jsonl.
        try:
            resolved = super()._resolve_path(normalized)
        except ValueError:
            logger.debug("fs_resolve_rejected", key=key, normalized_key=normalized)
            raise PermissionError(self._teaching_message(key)) from None
        logger.debug(
            "fs_resolve",
            key=key,
            normalized_key=normalized,
            resolved=str(resolved),
        )
        return resolved
