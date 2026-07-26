"""Immutable C6.1 resource snapshot and pre-model workspace materialization."""

from __future__ import annotations

import hashlib
import json
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
from clue_agents.workspace_policy import WorkspaceConflict, WorkspaceSecurityError

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


def _resource_path(ref: AgentResourceRef) -> str:
    if ref.kind is ResourceKind.PROFILE:
        return f".deepagent/profiles/{ref.name}/{ref.version}/profile.yaml"
    if ref.kind is ResourceKind.PROMPT:
        return f".deepagent/prompts/{ref.name}/{ref.version}/SYSTEM.md"
    if ref.kind is ResourceKind.SKILL:
        return f".deepagent/skills/{ref.name}/{ref.version}/SKILL.md"
    raise WorkspaceSecurityError("unsupported agent resource kind")


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


class AgentResourceMaterializer:
    """Copy one exact snapshot plus context/input bytes and freeze them before model spend."""

    def materialize(
        self,
        *,
        lease: AgentWorkspaceLease,
        snapshot: AgentResourceSnapshot,
        seed_files: tuple[WorkspaceSeedFile, ...] = (),
    ) -> None:
        if lease.resources_frozen or lease.materialization_failed:
            raise WorkspaceConflict("workspace materialization is one-shot")

        resource_paths = tuple(_resource_path(body.ref) for body in snapshot.bodies)
        seed_paths = tuple(seed.path for seed in seed_files)
        all_paths = (*resource_paths, *seed_paths, ".deepagent/manifest.json")
        if len(set(all_paths)) != len(all_paths):
            raise WorkspaceConflict("workspace materialization paths must be unique")

        try:
            for body in sorted(snapshot.bodies, key=lambda item: _resource_path(item.ref)):
                lease.backend.materialize_bytes(_resource_path(body.ref), body.content)
            for seed in sorted(seed_files, key=lambda item: item.path):
                lease.backend.materialize_bytes(seed.path, seed.content)

            # Manifest-last is the readiness marker: its presence means every referenced byte was
            # copied successfully. It includes digests and addresses, never prompt/context bodies.
            manifest_bytes = _canonical_manifest_bytes(snapshot.manifest)
            lease.backend.materialize_bytes(".deepagent/manifest.json", manifest_bytes)
            lease.backend.freeze_materialized_trees()

            for body in snapshot.bodies:
                entry = lease.backend.stat_entry_sync(_resource_path(body.ref))
                if entry.sha256 != body.ref.sha256 or not entry.read_only:
                    raise WorkspaceSecurityError("materialized resource verification failed")
            for seed in seed_files:
                entry = lease.backend.stat_entry_sync(seed.path)
                if entry.sha256 != seed.sha256 or not entry.read_only:
                    raise WorkspaceSecurityError("materialized seed verification failed")
            manifest_entry = lease.backend.stat_entry_sync(".deepagent/manifest.json")
            if (
                manifest_entry.sha256 != hashlib.sha256(manifest_bytes).hexdigest()
                or not manifest_entry.read_only
            ):
                raise WorkspaceSecurityError("materialized manifest verification failed")
            lease.mark_resources_frozen()
        except Exception:
            lease.mark_materialization_failed()
            raise
