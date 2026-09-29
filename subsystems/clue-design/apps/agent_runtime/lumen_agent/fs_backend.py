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
0. Scene run scope: ``active_run_id`` limits access to this run and shared
   read-only guidance. Root discovery dispatches to those trees before traversal;
   aliases and symlinks cannot grant a sibling run. Omission preserves the web
   backend's existing workspace contract.
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
from deepagents.backends.protocol import (
    EditResult,
    FileUploadResponse,
    GlobResult,
    GrepResult,
    LsResult,
    WriteResult,
)
from py_lumen_obs import get_logger
from wcmatch import glob as wcglob

from .critique_fidelity import CRITIQUE_FILENAME, normalize_critique_document
from .materialize import _LOCK_NAME
from .paths import normalize_agent_key
from .platform_reads import PROJECT_CONTEXT_DIR, SELLER_DIR

logger = get_logger("lumen_agent.fs_backend")


class AgentWorkspaceBackend(FilesystemBackend):
    """``FilesystemBackend`` rooted at the isolated workspace in ``virtual_mode``.

    The agent's ``/`` is the workspace root. ``_normalize_key`` forgives stale
    host-absolute / legacy paths before stock resolution; stock virtual mode does
    the containment. The lone gap stock leaves — an uncaught containment
    ``ValueError`` in ``read``/``write``/``edit`` — is closed by re-raising it as a
    teaching ``PermissionError``.

    Scene factories pass ``active_run_id`` to fence the shared trace root to one
    run. Knowledge, skills, and custom-component projections remain readable,
    with writes rejected here after alias and symlink resolution.
    """

    def __init__(
        self,
        root_dir: str | Path,
        max_file_size_mb: int = 10,
        custom_components_root: str | Path | None = None,
        reference_turn: bool = False,
        critique_observer: Callable[[Path, str], str | None] | None = None,
        active_run_id: str | None = None,
        history_thread_id: str | None = None,
        readonly_subdirs: tuple[str, ...] = (SELLER_DIR, PROJECT_CONTEXT_DIR),
    ) -> None:
        super().__init__(root_dir=root_dir, virtual_mode=True, max_file_size_mb=max_file_size_mb)
        # W1.5: whether reference assets rode this turn. Only a reference turn
        # owes a typed `reference_fidelity`, so only a reference turn normalizes
        # its self-audit; an ordinary turn's `critique.json` is written verbatim.
        self._reference_turn = bool(reference_turn)
        # The observer returns a registration error, or None on success/ignore.
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
        self._active_run_id = active_run_id
        if active_run_id is not None and not self._is_scope_id(active_run_id):
            raise ValueError(
                "active_run_id must be a run_ directory name or sessions/<session_id>"
            )
        # Design session continuity (2026-09-18): the deepagents summarization
        # middleware compacts THIS thread into `/conversation_history/<id>.md`
        # (media under `/conversation_history/media/`) through this backend. A
        # scoped backend would refuse those paths and break compaction, so the
        # active thread's own history is admitted — and only its own: a sibling
        # session's history file is another tenant's conversation. The id names a
        # file, so it is one segment — and ``PurePosixPath("..").name`` IS
        # ``".."``, so the climb is rejected by name rather than assumed away.
        if history_thread_id is not None and (
            not history_thread_id
            or history_thread_id == ".."
            or PurePosixPath(history_thread_id).name != history_thread_id
            or "\\" in history_thread_id
        ):
            raise ValueError("history_thread_id must be a single file-name segment")
        self._history_thread_id = history_thread_id
        # Design note 2026-09-19: folders inside the agent's own workspace that it may READ and
        # never write. `seller/` is the seller's pinned knowledge, written once per session by
        # the runtime from the platform's reads — an agent that could edit it could rewrite what
        # the brand says about itself and then design against its own words.
        self._readonly_subdirs = tuple(readonly_subdirs)
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
            if active_run_id is not None and not any(
                projection.is_relative_to(allowed)
                for allowed in (workspace / active_run_id, workspace / "custom_components")
            ):
                raise ValueError("custom component projection must belong to the current run")
            self._custom_components_root = projection
            self._custom_components_internal_prefix = "/" + relative.as_posix()

    @staticmethod
    def _is_scope_id(scope: str) -> bool:
        """A scope id is one run folder (``run_<id>``) or one session folder
        (``sessions/<session_id>``) — nothing else, and never a climb.

        Requiring ``scope == "/".join(parts)`` rejects every spelling that is not
        already canonical (a leading ``/``, a trailing ``/``, a ``.`` or ``..``
        segment), so the id can be joined onto the workspace root verbatim.
        """
        parts = PurePosixPath(scope).parts
        if "\\" in scope or scope != "/".join(parts):
            return False
        if len(parts) == 1:
            return parts[0].startswith("run_")
        return len(parts) == 2 and parts[0] == "sessions" and bool(parts[1])

    def _history_roots(self) -> tuple[Path, ...]:
        """This thread's conversation-history file and its media folder, or ()."""
        if self._history_thread_id is None:
            return ()
        root = Path(self._workspace_root).resolve() / "conversation_history"
        return (root / f"{self._history_thread_id}.md", root / "media")

    def _scope_roots(self) -> tuple[Path, ...]:
        assert self._active_run_id is not None
        root = Path(self._workspace_root).resolve()
        return (
            root / self._active_run_id,
            root / "knowledge_docs",
            root / ".deepagent",
            self._custom_components_root or root / "custom_components",
            *self._history_roots(),
        )

    def _check_run_scope(self, path: Path, *, allow_root: bool = False) -> None:
        if self._active_run_id is None:
            return
        root = Path(self._workspace_root).resolve()
        if (allow_root and path == root) or any(
            path.is_relative_to(allowed) for allowed in self._scope_roots()
        ):
            return
        raise PermissionError(
            "Path is outside the current run. Use "
            f"/{self._active_run_id}/ or the shared read-only knowledge and skills."
        )

    def _pinned_subdir(self, *candidates: Path) -> str | None:
        """The pinned read-only subdirectory a write would land in, or None.

        The agent's workspace is `<scope>/workspace/`, so a pinned tree is the segment PAIR
        `workspace/<name>/`. Matching on the pair rather than on a scope-rooted prefix is what
        makes this fence hold in BOTH modes: website mode keeps an unscoped backend (no
        `active_run_id`), and the seller's knowledge is written and read there too.
        """
        for candidate in candidates:
            parts = candidate.parts
            for index in range(len(parts) - 1):
                if parts[index] == "workspace" and parts[index + 1] in self._readonly_subdirs:
                    return parts[index + 1]
        return None

    def _assert_writable(self, key: str) -> None:
        lexical = Path(self._workspace_root).resolve() / self._normalize_and_map_key(key).lstrip(
            "/"
        )
        # The pinned trees are refused before the scope check, because they are refused in both
        # scope modes: they sit INSIDE the agent's own read-write workspace and are carved back
        # out of it, rather than being another shared projection outside it.
        if (pinned := self._pinned_subdir(lexical)) is not None:
            raise PermissionError(
                f"{pinned}/ is read-only: it is the pinned knowledge this turn designs from. "
                "Write files elsewhere in the workspace."
            )
        if self._active_run_id is None:
            return
        resolved = self._resolve_path(key)
        if (pinned := self._pinned_subdir(resolved)) is not None:
            raise PermissionError(
                f"{pinned}/ is read-only: it is the pinned knowledge this turn designs from. "
                f"Write files elsewhere under /{self._active_run_id}/."
            )
        scope = self._scope_roots()
        history = self._history_roots()
        # The run/session folder AND this thread's own history are read-write;
        # the shared projections stay read-only.
        writable = (scope[0], *history)
        readonly = [root for root in scope[1:] if root not in history]
        if not any(resolved.is_relative_to(root) for root in writable) or any(
            candidate.is_relative_to(root) for candidate in (lexical, resolved) for root in readonly
        ):
            raise PermissionError(
                "Shared knowledge, skills, and custom components are read-only. "
                f"Write files under /{self._active_run_id}/ instead."
            )

    def _root_discovery_keys(self, path: str | None) -> list[str] | None:
        """Route root discovery before the SDK can traverse other runs.

        SDK glob bypasses _resolve_path for '/', and grep recursively opens
        files below its base. Output filtering alone cannot isolate those reads.
        """
        if self._active_run_id is None:
            return None
        normalized = self._normalize_and_map_key(path or "/")
        if PurePosixPath("/" + normalized.lstrip("/")).as_posix() != "/":
            return None
        keys = []
        for root in self._scope_roots():
            key = "/" + root.relative_to(Path(self._workspace_root).resolve()).as_posix()
            try:
                resolved = self._resolve_path(key)
                if resolved.is_dir():
                    keys.append(key)
            except (OSError, RuntimeError):
                continue
        return keys

    @staticmethod
    def _root_pattern_matches(path: str, pattern: str, *, recursive: bool) -> bool:
        pattern = pattern.lstrip("/")
        patterns = [pattern, f"**/{pattern}"] if recursive else [pattern]
        return wcglob.globmatch(
            path.lstrip("/"),
            patterns,
            flags=wcglob.GLOBSTAR | wcglob.BRACE | wcglob.DOTGLOB,
        )

    def ls(self, path: str) -> LsResult:
        keys = self._root_discovery_keys(path)
        if keys is None:
            return super().ls(path)
        return LsResult(
            entries=[
                {"path": self._to_virtual_path(self._resolve_path(key)) + "/", "is_dir": True}
                for key in keys
            ]
        )

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        keys = self._root_discovery_keys(path)
        if keys is None:
            return super().glob(pattern, path)
        if ".." in PurePosixPath(pattern).parts:
            return GlobResult(error="Path traversal not allowed in glob pattern", matches=[])
        matches = {}
        errors = []
        for key in keys:
            result = super().glob("**/*", path=key)
            if result.error:
                errors.append(result.error)
            for match in result.matches or []:
                if self._root_pattern_matches(match["path"], pattern, recursive=True):
                    matches[match["path"]] = match
        return GlobResult(
            matches=[matches[key] for key in sorted(matches)], error="\n".join(errors) or None
        )

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None) -> GrepResult:
        keys = self._root_discovery_keys(path)
        if keys is None:
            return super().grep(pattern, path, glob)
        matches = {}
        errors = []
        for key in keys:
            result = super().grep(pattern, path=key)
            if result.error:
                errors.append(result.error)
            for match in result.matches or []:
                if glob is None or self._root_pattern_matches(
                    match["path"], glob, recursive="/" not in glob.lstrip("/")
                ):
                    matches[(match["path"], match["line"])] = match
        return GrepResult(
            matches=[matches[key] for key in sorted(matches)], error="\n".join(errors) or None
        )

    def _ripgrep_search(self, pattern: str, base_full: Path, include_glob: str | None):
        if self._active_run_id is not None:
            # Stock rg inherits RIPGREP_CONFIG_PATH, whose --follow can read a
            # sibling symlink before output filtering. Its Python walker checks
            # _to_virtual_path before opening each file and does not recurse
            # through directory symlinks. Keep that checked walker for scenes;
            # avoid mutating process-wide environment in concurrent runs.
            return None
        return super()._ripgrep_search(pattern, base_full, include_glob)

    def _normalize_and_map_key(self, key: str) -> str:
        normalized = normalize_agent_key(key, self._workspace_root)
        prefix = self._custom_components_internal_prefix
        if prefix is None:
            return normalized
        if self._active_run_id is not None:
            normalized = PurePosixPath("/" + normalized.lstrip("/")).as_posix()
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
                prefix is not None and (normalized == prefix or normalized.startswith(prefix + "/"))
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
            f"(e.g. /{self._active_run_id or 'run_<id>'}/workspace/..., /knowledge_docs/..., "
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
        # Root discovery is routed separately; direct operations share this
        # normalization and canonical containment check. Keep details in run.jsonl.
        try:
            resolved = super()._resolve_path(normalized)
        except ValueError:
            logger.debug("fs_resolve_rejected", key=key, normalized_key=normalized)
            raise PermissionError(self._teaching_message(key)) from None
        lexical = Path(self._workspace_root).resolve() / normalized.lstrip("/")
        allow_root = lexical == Path(self._workspace_root).resolve()
        self._check_run_scope(lexical, allow_root=allow_root)
        self._check_run_scope(resolved, allow_root=allow_root)
        logger.debug(
            "fs_resolve",
            key=key,
            normalized_key=normalized,
            resolved=str(resolved),
        )
        return resolved

    def _to_virtual_path(self, path: Path) -> str:
        try:
            self._check_run_scope(path.resolve())
        except PermissionError as error:
            # SDK walkers skip ValueError results before opening their content.
            raise ValueError(str(error)) from None
        projection = self._custom_components_root
        if projection is not None:
            try:
                relative = path.resolve().relative_to(projection)
            except (OSError, ValueError):
                pass
            else:
                suffix = relative.as_posix()
                return "/custom_components" if suffix == "." else f"/custom_components/{suffix}"
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
        self._assert_writable(key)
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
                result.error = self._observe_critique(file_path)
            return result

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        if self._active_run_id is None:
            return super().upload_files(files)
        responses = []
        for key, content in files:
            try:
                lock = self._file_mutation_lock(key)
            except (OSError, RuntimeError):
                responses.append(FileUploadResponse(path=key, error="permission_denied"))
                continue
            with lock:
                responses.extend(super().upload_files([(key, content)]))
        return responses

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
                result.error = self._observe_critique(file_path)
            return result

    def _observe_critique(self, file_path: str) -> str | None:
        if self._critique_observer is not None and self._is_critique_key(file_path):
            path = self._resolve_path(file_path)
            if error := self._critique_observer(path, path.read_text(encoding="utf-8")):
                return (
                    f"File saved, but visual review was not registered: {error} "
                    "Edit this saved file to resolve the review error."
                )
        return None
