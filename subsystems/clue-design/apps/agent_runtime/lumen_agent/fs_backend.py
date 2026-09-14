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
4. W1.5: the typed-``reference_fidelity`` invariant on a reference turn. The
   fast-loop author writes ``critique.json`` through the generic ``write_file``
   tool, so THIS backend is the only choke point every self-audit passes through.
   On a reference turn a ``critique.json`` write is normalized by
   ``critique_fidelity.normalize_critique_document`` before it lands, promoting a
   fidelity score the author wrote as prose into the typed field. See that
   module's docstring for the defect and the exact promotion rule.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath
from threading import Lock, RLock

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import EditResult, WriteResult
from py_lumen_obs import get_logger

from .critique_fidelity import CRITIQUE_FILENAME, normalize_critique_document
from .materialize import _LOCK_NAME
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

    def __init__(
        self,
        root_dir: str | Path,
        max_file_size_mb: int = 10,
        custom_components_root: str | Path | None = None,
        reference_turn: bool = False,
        critique_observer: Callable[[Path, str], None] | None = None,
    ) -> None:
        super().__init__(
            root_dir=root_dir, virtual_mode=True, max_file_size_mb=max_file_size_mb
        )
        # W1.5: whether reference assets rode this turn. Only a reference turn
        # owes a typed `reference_fidelity`, so only a reference turn normalizes
        # its self-audit; an ordinary turn's `critique.json` is written verbatim.
        self._reference_turn = bool(reference_turn)
        self._critique_observer = critique_observer
        # One backend is shared by a run's concurrent file tools. Stock edit
        # reads then truncates/writes without a transaction; disjoint edits can
        # both succeed while overwriting each other. Locks belong to validated
        # canonical paths, so aliases serialize and independent files do not.
        self._file_locks: dict[Path, RLock] = {}
        self._file_locks_guard = Lock()
        # Stored from the constructor arg (not ``self.cwd``) so the class also works
        # under the harness's stubbed ``FilesystemBackend``, which does not set cwd.
        self._workspace_root = str(Path(root_dir))
        self._custom_components_root: Path | None = None
        self._custom_components_internal_prefix: str | None = None
        if custom_components_root is not None:
            workspace = Path(root_dir).resolve()
            projection = Path(custom_components_root).resolve()
            try:
                relative = projection.relative_to(workspace)
            except ValueError as error:
                raise ValueError(
                    "custom component projection must live inside the agent workspace"
                ) from error
            self._custom_components_root = projection
            self._custom_components_internal_prefix = "/" + relative.as_posix()

    def _normalize_and_map_key(self, key: str) -> str:
        normalized = normalize_agent_key(key, self._workspace_root)
        prefix = self._custom_components_internal_prefix
        if prefix is None:
            return normalized
        if normalized == "/custom_components":
            return prefix
        if normalized.startswith("/custom_components/"):
            return prefix + normalized[len("/custom_components") :]
        return normalized

    def _is_component_projection_key(self, key: str) -> bool:
        normalized = normalize_agent_key(key, self._workspace_root)
        prefix = self._custom_components_internal_prefix
        return (
            normalized == "/custom_components"
            or normalized.startswith("/custom_components/")
            or (
                prefix is not None
                and (
                    normalized == prefix
                    or normalized.startswith(prefix + "/")
                )
            )
        )

    @staticmethod
    def _projection_write_message() -> str:
        return (
            "/custom_components is a read-only projection of the durable "
            "account registry. Use write_custom_component_source with an "
            "expected source version; ordinary filesystem writes cannot bypass "
            "version, provenance, or endpoint-honesty checks."
        )

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
        normalized = self._normalize_and_map_key(key)
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

    def _to_virtual_path(self, path: Path) -> str:
        projection = self._custom_components_root
        if projection is not None:
            try:
                relative = path.resolve().relative_to(projection)
            except (OSError, ValueError):
                pass
            else:
                suffix = relative.as_posix()
                return (
                    "/custom_components"
                    if suffix == "."
                    else f"/custom_components/{suffix}"
                )
        return super()._to_virtual_path(path)

    def _is_critique_key(self, key: str) -> bool:
        try:
            normalized = self._normalize_and_map_key(key)
        except Exception:  # a key we cannot even normalize is not our business.
            return False
        return PurePosixPath(normalized).name == CRITIQUE_FILENAME

    def _normalize_self_audit(self, file_path: str, content: str) -> str:
        """W1.5 — promote a prose fidelity score into the typed field on write."""
        if not self._reference_turn or not self._is_critique_key(file_path):
            return content
        rewritten = normalize_critique_document(content)
        if rewritten is None:
            return content
        logger.debug("critique_reference_fidelity_stamped", key=file_path)
        return rewritten

    def _materialization_lock_write_error(self, key: str) -> str | None:
        # Middleware permission checks precede our host/legacy alias normalization.
        # Protect the coordination file here too, after resolving those spellings.
        normalized = self._normalize_and_map_key(key)
        if PurePosixPath(normalized).as_posix().lstrip("/") == _LOCK_NAME:
            return "The workspace materialization lock is a read-only runtime file."
        return None

    def _file_mutation_lock(self, key: str) -> RLock:
        # Resolve with the existing normalization/containment checks BEFORE
        # allocating a lock. Stock operations still resolve again inside the
        # transaction; no cached file contents or relaxed replacement checks.
        path = self._resolve_path(key)
        with self._file_locks_guard:
            if path not in self._file_locks:
                self._file_locks[path] = RLock()
            return self._file_locks[path]

    def write(self, file_path: str, content: str) -> WriteResult:
        if error := self._materialization_lock_write_error(file_path):
            return WriteResult(error=error)
        if self._is_component_projection_key(file_path):
            return WriteResult(error=self._projection_write_message())
        try:
            lock = self._file_mutation_lock(file_path)
        except (OSError, RuntimeError) as error:
            return WriteResult(error=f"Error writing file '{file_path}': {error}")
        with lock:
            result = super().write(file_path, self._normalize_self_audit(file_path, content))
            if not result.error:
                self._observe_critique(file_path)
            return result

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        if error := self._materialization_lock_write_error(file_path):
            return EditResult(error=error)
        if self._is_component_projection_key(file_path):
            return EditResult(error=self._projection_write_message())
        try:
            lock = self._file_mutation_lock(file_path)
        except (OSError, RuntimeError) as error:
            return EditResult(error=f"Error editing file '{file_path}': {error}")
        with lock:
            result = super().edit(
                file_path,
                old_string,
                new_string,
                replace_all=replace_all,
            )
            if not result.error:
                self._observe_critique(file_path)
            return result

    def _observe_critique(self, file_path: str) -> None:
        if self._critique_observer is not None and self._is_critique_key(file_path):
            path = self._resolve_path(file_path)
            self._critique_observer(path, path.read_text(encoding="utf-8"))
