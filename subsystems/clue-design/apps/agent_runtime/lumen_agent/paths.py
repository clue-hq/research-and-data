"""Workspace path helpers (W-isolation, D1 + D5 + D7).

The deepagent runs on an ISOLATED workspace: its filesystem backend is
``virtual_mode=True`` rooted at the workspace directory, so the agent's ``/`` IS
the workspace. Two pure, unit-tested string transforms live here:

- ``normalize_agent_key`` (D1): forgive the path forms a model may still emit
  from stale habit — a host-absolute path under the workspace root, or a legacy
  ``apps/agent_runtime/knowledge_docs/…`` / ``.lumen-runs/…`` reference — mapping
  each to its correct virtual form (``/knowledge_docs/…``, ``/run_<id>/…``).
  Applied BEFORE resolution by ``AgentWorkspaceBackend`` (fs_backend.py).
- ``to_virtual`` (D5): render a HOST path that lives under the workspace root as
  the virtual string the model should see (``/run_<id>/…``). Applied at the tool
  seams where a result string exposes a path to the model (render.py, view.py).

Both are pure string operations. In particular ``normalize_agent_key`` NEVER
collapses ``..`` — a traversal stays a traversal so the backend's own guard (and
the deepagents middleware ``validate_path``) still rejects it. Nothing here can
turn a ``..`` climb into a clean escape.
"""

from __future__ import annotations

from pathlib import Path

# Legacy repo-relative marker the model may still emit for knowledge docs; every
# occurrence maps to the virtual ``/knowledge_docs/`` root regardless of whatever
# prefix (bare, repo-absolute, or ``/``-rooted) preceded it.
_KNOWLEDGE_MARKER = "apps/agent_runtime/knowledge_docs/"
# Legacy run-root segment: the old trace dir was ``<repo>/.lumen-runs`` and runs
# lived at ``.lumen-runs/run_<id>``; the workspace now roots runs at ``/run_<id>``,
# so dropping everything up to and including this segment maps old → new.
_LEGACY_RUN_MARKER = ".lumen-runs/"


def _root_str(workspace_root: str | Path) -> str:
    """The workspace root as a string with no trailing slash."""
    return str(workspace_root).rstrip("/")


def normalize_agent_key(key: str, workspace_root: str | Path) -> str:
    """Map a model-emitted path to its workspace-virtual form (D1).

    Pure string transform; precedence:

    1. Any path containing ``apps/agent_runtime/knowledge_docs/`` → the tail under
       ``/knowledge_docs/`` (handles bare, repo-absolute, and ``/``-rooted forms).
    2. A host-absolute path under the workspace root → the tail under ``/``.
    3. A path containing the legacy ``.lumen-runs/`` segment → the tail under ``/``.
    4. Anything else (already-virtual ``/…`` paths, plain relative paths) →
       returned unchanged (the backend resolves it under the virtual root).

    ``..`` segments are never collapsed here — a pathological climb survives into
    the returned string so the backend's traversal guard rejects it. This helper
    cannot manufacture an escape.
    """
    if _KNOWLEDGE_MARKER in key:
        tail = key.split(_KNOWLEDGE_MARKER, 1)[1].lstrip("/")
        return "/knowledge_docs/" + tail if tail else "/knowledge_docs"
    # The BARE directory form (no trailing slash) — `ls` on the knowledge root is
    # exactly what a model does, and it was the live failure form of 2026-07-10.
    if key.rstrip("/").endswith(_KNOWLEDGE_MARKER.rstrip("/")):
        return "/knowledge_docs"

    root = _root_str(workspace_root)
    if key == root:
        return "/"
    if root and key.startswith(root + "/"):
        return "/" + key[len(root) + 1 :]

    if _LEGACY_RUN_MARKER in key:
        tail = key.split(_LEGACY_RUN_MARKER, 1)[1]
        return "/" + tail.lstrip("/")
    if key.rstrip("/").endswith(_LEGACY_RUN_MARKER.rstrip("/")):
        return "/"

    return key


def host_to_virtual(path: str | Path, workspace_root: str | Path) -> str:
    """Render a HOST path under ``workspace_root`` as its virtual string (D5).

    A path that is NOT under the workspace root is returned as its plain string
    unchanged — the caller is responsible for only handing this workspace-interior
    paths (previews, round dirs); a stray external path is surfaced verbatim rather
    than silently rewritten into a misleading virtual form.
    """
    root = Path(_root_str(workspace_root))
    candidate = Path(path)
    try:
        relative = candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return str(path)
    posix = relative.as_posix()
    return "/" if posix == "." else "/" + posix


def to_virtual(path: str | Path, config) -> str:
    """D5 tool-seam helper: virtualize a host path against the run's workspace root.

    ``config.workspace_root`` is the ``virtual_mode`` backend's root, so a path
    under it renders to the same ``/…`` string the model resolves through its
    filesystem tools.
    """
    return host_to_virtual(path, config.workspace_root)
