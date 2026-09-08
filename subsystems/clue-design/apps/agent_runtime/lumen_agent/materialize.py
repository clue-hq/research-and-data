"""Materialize the deepagent's isolated workspace (W-isolation, D2).

The agent reads its skills and knowledge from INSIDE its virtual-mode workspace.
This module derives that read-only content from the repo's authored source tree:

    <repo>/apps/agent_runtime/knowledge_docs/        (source of truth, git-tracked)
        →  <workspace>/knowledge_docs/                (full tree copy)
        →  <workspace>/.deepagent/skills/<name>/…     (every skill dir, flat)
        →  <workspace>/.deepagent/AGENTS.md           (from knowledge_docs/AGENT.md)

The repo tree is the SINGLE source of truth; the workspace copy is derived and is
never written back. Sync is content-hash guarded (``.deepagent/.sync-stamp``, the
same philosophy as the engine stamp): identical sources ⇒ no copy; changed sources
⇒ a full loud re-sync. A missing source tree or a copy failure is a loud
``RuntimeError`` raised BEFORE any model call — never a silent half-workspace.

Same-host callers serialize the entire check-and-sync with a per-workspace
POSIX file lock. The lock file stays outside the rebuilt trees and must never
be unlinked: waiters must keep sharing the same inode. Closing the descriptor
(including process exit) releases the lock, so interrupted syncs are retryable.
Authored sources must remain fixed while turns using this shared root are live;
this initialization lock does not pin different source versions for active runs.
"""

from __future__ import annotations

import fcntl
import hashlib
import shutil
from pathlib import Path

from py_lumen_obs import get_logger

logger = get_logger("lumen_agent.materialize")

# The authored knowledge tree lives beside the package (``apps/agent_runtime/
# knowledge_docs``), resolved relative to THIS file so it is found regardless of
# ``config.repo_root`` (which may be a bare temp root in tests). This is the same
# physical tree the repo tracks — the single source of truth.
_PACKAGE_KNOWLEDGE_DOCS = Path(__file__).resolve().parent.parent / "knowledge_docs"

_SKILLS_SUBDIR = "skills"
_AGENT_DOC = "AGENT.md"
_STAMP_NAME = ".sync-stamp"
_LOCK_NAME = ".materialize.lock"


def _iter_source_files(root: Path):
    """Every regular file under ``root``, sorted by relative POSIX path."""
    files = [p for p in root.rglob("*") if p.is_file()]
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def _content_stamp(root: Path) -> str:
    """A sha256 over (relative path, bytes) of every file under ``root``.

    Deterministic and order-independent: identical source trees produce an
    identical stamp, so an unchanged repo tree never triggers a re-copy.
    """
    digest = hashlib.sha256()
    for path in _iter_source_files(root):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def materialize_agent_workspace(config, *, source_knowledge_docs: Path | None = None) -> Path:
    """Sync the repo knowledge tree into the workspace; return the workspace root.

    Called before agent construction (harness path — which both the API and CLI
    go through). Idempotent: on a matching ``.sync-stamp`` it returns immediately
    without copying. On any mismatch it re-syncs the whole derived tree and logs
    the sync loudly. Raises ``RuntimeError`` on a missing source or a copy failure.
    """
    source = (source_knowledge_docs or _PACKAGE_KNOWLEDGE_DOCS).resolve()
    if not source.is_dir():
        raise RuntimeError(
            f"Cannot materialize agent workspace: knowledge source tree missing at "
            f"{source}. The repo's apps/agent_runtime/knowledge_docs/ is the single "
            f"source of truth and must exist before an agent turn."
        )

    workspace_root = Path(config.workspace_root)
    deepagent_dir = workspace_root / ".deepagent"
    knowledge_dest = workspace_root / "knowledge_docs"
    stamp_path = deepagent_dir / _STAMP_NAME

    try:
        workspace_root.mkdir(parents=True, exist_ok=True)
        with (workspace_root / _LOCK_NAME).open("a") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            stamp = _content_stamp(source)
            if stamp_path.exists() and stamp_path.read_text(encoding="utf-8") == stamp:
                # Decision (debug detail): announce the no-op sync decision so a run
                # trace shows the materializer was consulted and found the workspace
                # already current (distinct from a re-sync, which stays loud below).
                logger.debug(
                    "materialize_stamp_hit",
                    stamp=stamp[:12],
                    workspace_root=str(workspace_root),
                )
                return workspace_root

            # Stale or absent stamp: rebuild the derived trees from scratch so a removed
            # source file can never linger in the workspace copy.
            # Invalidate first, even if deletion fails partway through. A later
            # source rollback must not accept a stamp over incomplete resources.
            stamp_path.unlink(missing_ok=True)
            if deepagent_dir.exists():
                shutil.rmtree(deepagent_dir)
            if knowledge_dest.exists():
                shutil.rmtree(knowledge_dest)

            skills_src = source / _SKILLS_SUBDIR
            agent_doc_src = source / _AGENT_DOC
            deepagent_skills = deepagent_dir / _SKILLS_SUBDIR

            deepagent_dir.mkdir(parents=True, exist_ok=True)
            # Full knowledge tree (its skills/ subtree included, so intra-doc relative
            # references keep resolving).
            shutil.copytree(source, knowledge_dest)
            # Canonical skill copies under /.deepagent/skills (the SkillsMiddleware
            # source), and the agent operating doc as /.deepagent/AGENTS.md.
            if skills_src.is_dir():
                shutil.copytree(skills_src, deepagent_skills)
            if agent_doc_src.is_file():
                shutil.copy2(agent_doc_src, deepagent_dir / "AGENTS.md")

            stamp_path.write_text(stamp, encoding="utf-8")
            skill_count = (
                sum(1 for child in (deepagent_dir / _SKILLS_SUBDIR).iterdir() if child.is_dir())
                if (deepagent_dir / _SKILLS_SUBDIR).is_dir()
                else 0
            )
            # The sync stays LOUD (warning) per this module's contract — a re-sync is a
            # real event worth seeing. Structured fields replace the old %-format args
            # (the shared obs chain renders event + fields, not printf-style templates).
            logger.warning(
                "materialized agent workspace",
                skill_count=skill_count,
                source=str(source),
                workspace_root=str(workspace_root),
                stamp=stamp[:12],
            )
            return workspace_root
    except OSError as error:
        raise RuntimeError(
            f"Failed to materialize agent workspace at {workspace_root} from {source}: {error}"
        ) from error
