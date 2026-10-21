"""Immutable C6.1 resource snapshot and pre-model workspace materialization."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from clue_agents.contracts import (
    AgentResourceManifest,
    AgentResourceRef,
    AgentRole,
    ResourceKind,
    ToolPin,
    normalize_virtual_path,
)
from clue_agents.workspace import AgentWorkspaceLease
from clue_agents.workspace_policy import (
    WorkspaceConflict,
    WorkspaceError,
    WorkspaceSecurityError,
)

__all__ = [
    "AgentResourceMaterializer",
    "AgentResourceSnapshot",
    "ResourceBody",
    "WorkspaceSeedFile",
    "build_agent_resource_manifest",
    "resource_manifest_sha256",
]


def _canonical_manifest_bytes(manifest: AgentResourceManifest) -> bytes:
    return json.dumps(
        manifest.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def resource_manifest_sha256(manifest: AgentResourceManifest) -> str:
    """Digest the immutable manifest inputs without making the digest self-referential."""

    payload = manifest.model_dump(mode="json", exclude={"aggregate_sha256"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_agent_resource_manifest(
    *,
    role: AgentRole,
    profile: AgentResourceRef,
    prompt: AgentResourceRef,
    skills: tuple[AgentResourceRef, ...],
    tools: tuple[ToolPin, ...],
) -> AgentResourceManifest:
    """Build a schema-v1 manifest with its canonical aggregate digest."""

    provisional = AgentResourceManifest(
        schema_version="1",
        role=role,
        profile=profile,
        prompt=prompt,
        skills=skills,
        tools=tools,
        aggregate_sha256="0" * 64,
    )
    return provisional.model_copy(
        update={"aggregate_sha256": resource_manifest_sha256(provisional)}
    )


@dataclass(frozen=True, slots=True)
class ResourceBody:
    ref: AgentResourceRef
    content: bytes
    media_type: str

    def __post_init__(self) -> None:
        if hashlib.sha256(self.content).hexdigest() != self.ref.sha256:
            raise WorkspaceSecurityError("resource body digest does not match its exact reference")
        try:
            self.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceSecurityError("agent resource bodies must be UTF-8 text") from exc


@dataclass(frozen=True, slots=True)
class WorkspaceSeedFile:
    """Pre-assembled context/input body and its expected immutable digest."""

    path: str
    content: bytes
    sha256: str
    media_type: str

    def __post_init__(self) -> None:
        normalized = normalize_virtual_path(self.path)
        if normalized != self.path:
            raise WorkspaceSecurityError("seed path must already be normalized")
        if not normalized.startswith(("context/", "inputs/")):
            raise WorkspaceSecurityError("seed files must materialize below context/ or inputs/")
        if hashlib.sha256(self.content).hexdigest() != self.sha256:
            raise WorkspaceSecurityError("seed file digest does not match its body")
        try:
            self.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceSecurityError("workspace seed files must be UTF-8 text") from exc


#: The readiness marker, written last and verified first.
_MANIFEST_PATH = ".deepagent/manifest.json"
#: The three folders a turn writes from its pins (``workspace._MATERIALIZED_PREFIXES``).
_TRUSTED_TREES = (".deepagent", "inputs", "context")


def _resource_path(ref: AgentResourceRef) -> str:
    if ref.kind is ResourceKind.PROFILE:
        return f".deepagent/profiles/{ref.name}/{ref.version}/profile.yaml"
    if ref.kind is ResourceKind.PROMPT:
        return f".deepagent/prompts/{ref.name}/{ref.version}/SYSTEM.md"
    if ref.kind is ResourceKind.SKILL:
        return f".deepagent/skills/{ref.name}/{ref.version}/SKILL.md"
    raise WorkspaceSecurityError("unsupported agent resource kind")


_SKILL_PATH = re.compile(r"\{\{\s*skills\.([a-zA-Z0-9_-]+)\.path\s*\}\}")


def render_skill_references(text: str, skills: tuple[AgentResourceRef, ...]) -> str:
    """Resolve only skill-path placeholders, from the effective pinned skill set.

    No catalog scans, general template evaluation or recursive substitution. Unrelated
    placeholders (for example account_name in teaching examples) remain literal.
    """

    if not re.search(r"\{\{\s*skills\b", text):
        return text
    paths: dict[str, str] = {}
    for ref in skills:
        key = ref.name.replace("-", "_")
        if key in paths:
            raise WorkspaceSecurityError(f"ambiguous skill placeholder name: {key}")
        paths[key] = "/" + _resource_path(ref)

    def replace(match: re.Match[str]) -> str:
        key = match[1].replace("-", "_")
        if key not in paths:
            raise WorkspaceSecurityError(f"skill placeholder is not mounted by this profile: {key}")
        return paths[key]

    rendered = _SKILL_PATH.sub(replace, text)
    if re.search(r"\{\{\s*skills\b", rendered):
        raise WorkspaceSecurityError("invalid skill placeholder; expected {{skills.<name>.path}}")
    return rendered


@dataclass(frozen=True, slots=True)
class AgentResourceSnapshot:
    """Validated bodies for the exact immutable refs in one resource manifest."""

    manifest: AgentResourceManifest
    bodies: tuple[ResourceBody, ...]

    def __post_init__(self) -> None:
        if resource_manifest_sha256(self.manifest) != self.manifest.aggregate_sha256:
            raise WorkspaceSecurityError("resource manifest aggregate digest is invalid")
        expected = (
            self.manifest.profile,
            self.manifest.prompt,
            *self.manifest.skills,
        )
        expected_by_address = {ref.address: ref for ref in expected}
        if len(expected_by_address) != len(expected):
            raise WorkspaceSecurityError("resource manifest contains duplicate addresses")
        actual_by_address = {body.ref.address: body for body in self.bodies}
        if len(actual_by_address) != len(self.bodies):
            raise WorkspaceSecurityError("resource snapshot contains duplicate addresses")
        if set(actual_by_address) != set(expected_by_address):
            raise WorkspaceSecurityError("resource snapshot bodies do not match the manifest")
        for address, expected_ref in expected_by_address.items():
            if actual_by_address[address].ref != expected_ref:
                raise WorkspaceSecurityError("resource snapshot ref differs from the manifest")
        # Resolve before any model spend or workspace writes, including references between skills.
        for body in self.bodies:
            self.rendered_content(body)

    def rendered_content(self, body: ResourceBody) -> bytes:
        """Derived model-visible bytes; source bodies and their hashes stay immutable."""

        if body.ref.kind not in (ResourceKind.PROMPT, ResourceKind.SKILL):
            return body.content
        return render_skill_references(body.content.decode("utf-8"), self.manifest.skills).encode(
            "utf-8"
        )

    def materialized_entries(self) -> tuple[tuple[str, bytes], ...]:
        entries = []
        rendered_records = []
        for body in sorted(self.bodies, key=lambda item: _resource_path(item.ref)):
            path = _resource_path(body.ref)
            content = self.rendered_content(body)
            entries.append((path, content))
            if content != body.content:
                rendered_records.append(
                    {
                        "path": path,
                        "source_sha256": body.ref.sha256,
                        "rendered_sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
        if rendered_records:
            entries.append(
                (
                    ".deepagent/rendered-resources.json",
                    json.dumps(
                        {"renderer": "skill-paths-v1", "resources": rendered_records},
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8"),
                )
            )
        return tuple(entries)


class AgentResourceMaterializer:
    """Copy one exact snapshot plus context/input bytes and freeze them before model spend.

    The thread workspace is persistent, so this runs once per *turn*, not once per directory:
    every turn resets the three trusted trees and rewrites its own pinned bytes into them.
    """

    def materialize(
        self,
        *,
        lease: AgentWorkspaceLease,
        snapshot: AgentResourceSnapshot,
        seed_files: tuple[WorkspaceSeedFile, ...] = (),
    ) -> None:
        """Write this turn's pinned resources, inputs and context into the thread workspace."""

        if lease.materialized or lease.materialization_failed:
            raise WorkspaceConflict("this turn already materialized its workspace resources")
        self._validate_paths(snapshot, seed_files)
        try:
            self._write_trees(lease=lease, snapshot=snapshot, seed_files=seed_files)
        except Exception:
            lease.mark_materialization_failed()
            raise

    def verify_materialized(
        self,
        *,
        lease: AgentWorkspaceLease,
        snapshot: AgentResourceSnapshot,
        seed_files: tuple[WorkspaceSeedFile, ...] = (),
    ) -> None:
        """Re-verify every immutable byte before a cold process resumes model execution.

        A crash can land anywhere in the write, so an absent, writable or differing path is
        not fatal here: the trees are reset and rewritten from the same pinned snapshot. Only
        bytes that still differ after that rewrite are a security failure.
        """

        if lease.materialization_failed:
            raise WorkspaceConflict("a failed materialization cannot be resumed")
        expected = self._expected_entries(snapshot, seed_files)
        if self._matches(lease=lease, expected=expected):
            lease.mark_resources_frozen()
            lease.mark_materialized()
            return

        self._validate_paths(snapshot, seed_files)
        self._write_trees(lease=lease, snapshot=snapshot, seed_files=seed_files)
        if not self._matches(lease=lease, expected=expected):
            raise WorkspaceSecurityError(
                "reopened materialization differs from its immutable snapshot"
            )

    @staticmethod
    def _validate_paths(
        snapshot: AgentResourceSnapshot,
        seed_files: tuple[WorkspaceSeedFile, ...],
    ) -> None:
        resource_paths = tuple(path for path, _ in snapshot.materialized_entries())
        seed_paths = tuple(seed.path for seed in seed_files)
        all_paths = (*resource_paths, *seed_paths, _MANIFEST_PATH)
        if len(set(all_paths)) != len(all_paths):
            raise WorkspaceConflict("workspace materialization paths must be unique")

    @staticmethod
    def _expected_entries(
        snapshot: AgentResourceSnapshot,
        seed_files: tuple[WorkspaceSeedFile, ...],
    ) -> tuple[tuple[str, str], ...]:
        """Every path the model must see, with the exact digest it must have."""

        return (
            *(
                (path, hashlib.sha256(content).hexdigest())
                for path, content in snapshot.materialized_entries()
            ),
            *((seed.path, seed.sha256) for seed in seed_files),
            (
                _MANIFEST_PATH,
                hashlib.sha256(_canonical_manifest_bytes(snapshot.manifest)).hexdigest(),
            ),
        )

    @staticmethod
    def _matches(
        *,
        lease: AgentWorkspaceLease,
        expected: tuple[tuple[str, str], ...],
    ) -> bool:
        """Whether the frozen trees on disk already hold exactly these immutable bytes."""

        try:
            if not lease.backend.materialized_trees_frozen():
                return False
            for path, digest in expected:
                entry = lease.backend.stat_entry_sync(path)
                if entry.sha256 != digest or not entry.read_only:
                    return False
        except (WorkspaceError, FileNotFoundError):
            # Absent, unsafe or partially frozen: rebuildable, not yet a security failure.
            return False
        return True

    def _write_trees(
        self,
        *,
        lease: AgentWorkspaceLease,
        snapshot: AgentResourceSnapshot,
        seed_files: tuple[WorkspaceSeedFile, ...],
    ) -> None:
        """Sync the trusted trees to this turn's bytes (only what changed), verify every digest."""

        trees: dict[str, dict[str, bytes]] = {prefix: {} for prefix in _TRUSTED_TREES}
        entries = [
            *snapshot.materialized_entries(),
            *((seed.path, seed.content) for seed in sorted(seed_files, key=lambda s: s.path)),
        ]
        # The manifest is written with the rest; it is still the readiness marker, because the
        # verification below re-reads every referenced byte before the turn may use any of them.
        manifest_bytes = _canonical_manifest_bytes(snapshot.manifest)
        entries.append((_MANIFEST_PATH, manifest_bytes))
        for path, content in entries:
            prefix, _, relative = path.partition("/")
            if prefix not in trees or not relative:
                raise WorkspaceSecurityError(f"{path} is outside the trusted trees")
            trees[prefix][relative] = content
        lease.backend.sync_materialized_trees(trees)

        for path, content in snapshot.materialized_entries():
            entry = lease.backend.stat_entry_sync(path)
            if entry.sha256 != hashlib.sha256(content).hexdigest() or not entry.read_only:
                raise WorkspaceSecurityError("materialized resource verification failed")
        for seed in seed_files:
            entry = lease.backend.stat_entry_sync(seed.path)
            if entry.sha256 != seed.sha256 or not entry.read_only:
                raise WorkspaceSecurityError("materialized seed verification failed")
        manifest_entry = lease.backend.stat_entry_sync(_MANIFEST_PATH)
        if (
            manifest_entry.sha256 != hashlib.sha256(manifest_bytes).hexdigest()
            or not manifest_entry.read_only
        ):
            raise WorkspaceSecurityError("materialized manifest verification failed")
        lease.mark_resources_frozen()
        lease.mark_materialized()
