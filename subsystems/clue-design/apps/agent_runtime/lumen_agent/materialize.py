"""Materialize the deepagent's isolated workspace (W-isolation, D2).

The agent reads its skills and knowledge from INSIDE its virtual-mode workspace.
This module derives that read-only content from the repo's authored source tree:

    <repo>/apps/agent_runtime/knowledge_docs/        (source of truth, git-tracked)
        →  <workspace>/knowledge_docs/                (selected knowledge view)
        →  <workspace>/.deepagent/skills/<name>/…     (selected skills, flat)
        →  <workspace>/.deepagent/AGENTS.md           (from knowledge_docs/AGENT.md; legacy view only)

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
The default legacy view preserves original website/scene resources and excludes
the authored views/ definitions. Candidate scene selection is explicit; its
manifest references shared mechanics and applies scoped policy projections.
The scene harness uses a separate candidate root, so interleaved web/legacy
turns cannot replace knowledge under an active candidate backend.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
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
_SCENE_PROJECTION_VERSION = "scene-catalog-v1"


def _iter_source_files(root: Path):
    """Every regular file under ``root``, sorted by relative POSIX path."""
    files = [p for p in root.rglob("*") if p.is_file()]
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def scene_view_manifest(root: Path | None = None) -> dict:
    """The versioned authored catalog, shared by delivery and runtime validation."""
    source = root or _PACKAGE_KNOWLEDGE_DOCS
    manifest = json.loads((source / "views/scene/manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise RuntimeError("Unsupported scene knowledge view manifest")
    for field in ("skills", "playbooks"):
        names = manifest.get(field, [])
        if not isinstance(names, list) or any(
            not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
            for name in names
        ) or len(names) != len(set(names)):
            raise RuntimeError(f"Invalid scene {field} registration")
    if not set(manifest.get("playbooks", [])) <= set(manifest.get("skills", [])):
        raise RuntimeError("Scene playbooks must be registered skills")
    from .models.creative_direction import PlaybookEvidenceRequirements

    requirements = manifest.get("playbook_requirements", {})
    if not isinstance(requirements, dict) or not set(requirements) <= set(manifest["playbooks"]):
        raise RuntimeError("Scene evidence requirements must name registered playbooks")
    try:
        for requirement in requirements.values():
            PlaybookEvidenceRequirements.model_validate(requirement)
    except ValueError as error:
        raise RuntimeError("Invalid scene playbook evidence requirements") from error
    from .native_copy import NativeCopyReviewProfile

    profiles = manifest.get("review_profiles", {})
    if not isinstance(profiles, dict) or any(
        not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
        for name in profiles
    ):
        raise RuntimeError("Invalid scene review profile registration")
    try:
        for profile in profiles.values():
            NativeCopyReviewProfile.model_validate(profile)
    except ValueError as error:
        raise RuntimeError("Invalid scene review profile") from error
    return manifest


def _view_files(root: Path, knowledge_view: str) -> dict[str, Path]:
    if knowledge_view == "legacy":
        return {
            p.relative_to(root).as_posix(): p for p in _iter_source_files(root)
            if p.relative_to(root).parts[0] != "views"
        }
    if knowledge_view != "scene":
        raise RuntimeError(f"Unknown knowledge view: {knowledge_view}")
    manifest = scene_view_manifest(root)
    overlay = root / "views/scene"
    # Harness alignment S1 (founder ruling 2026-10-17): the scene view delivers no operating note;
    # its content lives in the scene system prompt, so no /.deepagent/AGENTS.md is materialised.
    selected = [*manifest["knowledge"], *(
        f"skills/{name}/SKILL.md" for name in manifest["skills"]
    )]
    result = {}
    for relative in selected:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or path.parts[0] == "views":
            raise RuntimeError(f"Invalid knowledge view path: {relative}")
        source = overlay / path if (overlay / path).is_file() else root / path
        if not source.is_file():
            raise RuntimeError(f"Scene knowledge view source missing: {relative}")
        result[relative] = source
    return result


def _content_stamp(root: Path, knowledge_view: str = "legacy") -> str:
    """A sha256 over selected source paths/bytes and the view's manifest.

    Deterministic and order-independent: identical source trees produce an
    identical stamp, so an unchanged repo tree never triggers a re-copy.
    """
    digest = hashlib.sha256()
    if knowledge_view != "legacy":
        digest.update(_SCENE_PROJECTION_VERSION.encode("utf-8") + b"\0")
        digest.update(knowledge_view.encode("utf-8") + b"\0")
        digest.update((root / "views/scene/manifest.json").read_bytes() + b"\0")
    for rel, path in sorted(_view_files(root, knowledge_view).items()):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _project_scene_sections(destination: Path, manifest: dict) -> None:
    """Replace selected policy sections without duplicating shared mechanics.

    Heading anchors must be unique; a changed shared document fails loudly so
    a stale projection cannot quietly restore conflicting policy.
    """
    available = set(manifest["knowledge"])
    for relative, overrides in manifest.get("section_overrides", {}).items():
        if relative not in available:
            raise RuntimeError(f"Section override outside scene view: {relative}")
        target = destination / relative
        content = target.read_text(encoding="utf-8")
        for override in overrides:
            replacement_path = override["replacement"]
            if replacement_path not in available:
                raise RuntimeError(f"Section replacement outside scene view: {replacement_path}")
            start, end = override["start"], override["end"]
            if content.count(start) != 1 or content.count(end) != 1:
                raise RuntimeError(f"Scene section anchors changed: {relative}")
            start_at, end_at = content.index(start), content.index(end)
            if end_at <= start_at:
                raise RuntimeError(f"Scene section anchors reversed: {relative}")
            replacement = (destination / replacement_path).read_text(encoding="utf-8")
            content = content[:start_at] + replacement.rstrip() + "\n\n" + content[end_at:]
        target.write_text(content, encoding="utf-8")


def _write_scene_catalog(destination: Path, manifest: dict) -> None:
    """Derive navigation from the same metadata DeepAgents actually discovers.

    Only selected skill descriptions are included, never playbook bodies. Fail
    before a model call if registration and the real skill scanner disagree.
    """
    from deepagents.backends.filesystem import FilesystemBackend
    from deepagents.middleware.skills import _list_skills

    discovered = {
        skill["name"]: skill
        for skill in _list_skills(
            FilesystemBackend(root_dir=destination, virtual_mode=True), "/skills/"
        )
    }
    if set(discovered) != set(manifest["skills"]):
        raise RuntimeError("Scene registration differs from discoverable skill metadata")
    lines = [
        "# Scene playbook catalog",
        "",
        "Derived from registered skill descriptions; these are communicative choices,",
        "not required layouts. Select by request, inspected sources and available evidence.",
        "Read the relevant skill body and shared guides as needed at any stage, including",
        "authoring, review and later revisions. Re-read after context loss or a changed need.",
        "",
    ]
    for name in manifest["playbooks"]:
        description = " ".join(discovered[name]["description"].split())
        lines.append(f"- [{name}](/.deepagent/skills/{name}/SKILL.md): {description}")
    path = destination / "knowledge/scene/catalog.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def materialize_agent_workspace(
    config, *, source_knowledge_docs: Path | None = None, knowledge_view: str = "legacy"
) -> Path:
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
            stamp = _content_stamp(source, knowledge_view)
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
            if knowledge_view == "legacy":
                shutil.copytree(source, knowledge_dest, ignore=shutil.ignore_patterns("views"))
            else:
                for relative, src in _view_files(source, knowledge_view).items():
                    dest = knowledge_dest / relative
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                _project_scene_sections(knowledge_dest, scene_view_manifest(source))
                _write_scene_catalog(knowledge_dest, scene_view_manifest(source))
                skills_src = knowledge_dest / _SKILLS_SUBDIR
                agent_doc_src = knowledge_dest / _AGENT_DOC
            # Canonical skill copies under /.deepagent/skills (the SkillsMiddleware
            # source), and the agent operating doc as /.deepagent/AGENTS.md.
            if skills_src.is_dir():
                shutil.copytree(skills_src, deepagent_skills)
            if agent_doc_src.is_file():
                shutil.copy2(agent_doc_src, deepagent_dir / "AGENTS.md")

            if knowledge_view == "scene":
                descriptor = {**scene_view_manifest(source), "view": "scene", "stamp": stamp}
                (deepagent_dir / "knowledge-view.json").write_text(
                    json.dumps(descriptor, indent=2), encoding="utf-8"
                )

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
