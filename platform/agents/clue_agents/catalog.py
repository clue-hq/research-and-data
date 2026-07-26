"""Strict, provider-neutral agent resource catalogs with a folder-backed V1 adapter."""

from __future__ import annotations

import hashlib
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Protocol, TypeVar, runtime_checkable

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from clue_agents.contracts import (
    AgentResourceRef,
    AgentRole,
    ModelPolicy,
    ResourceKind,
    ToolPin,
    WorkspacePolicy,
)

__all__ = [
    "AgentCatalogError",
    "CatalogResourcePin",
    "FolderProfileCatalog",
    "FolderPromptCatalog",
    "FolderSkillCatalog",
    "ProfileCatalog",
    "ProfileDefinition",
    "ProfileResource",
    "ProfileStatus",
    "PromptCatalog",
    "PromptResource",
    "SkillCatalog",
    "SkillResource",
]

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class AgentCatalogError(RuntimeError):
    """A folder resource or cross-reference is malformed, mutable, or unavailable."""


class CatalogDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProfileStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


class CatalogResourcePin(CatalogDocument):
    name: str = Field(pattern=r"^[a-z0-9-]+$")
    version: str = Field(pattern=r"^v[0-9]+(?:\.[0-9]+){0,2}(?:[-+][a-z0-9.-]+)?$")
    sha256: Sha256


class PromptHeader(CatalogDocument):
    schema_version: Literal["1"]
    kind: Literal["prompt"]
    name: str = Field(pattern=r"^[a-z0-9-]+$")
    version: str = Field(pattern=r"^v[0-9]+(?:\.[0-9]+){0,2}(?:[-+][a-z0-9.-]+)?$")
    role: AgentRole
    summary: str = Field(min_length=1, max_length=512)
    framework: Literal["deepagents"]
    framework_version: Literal[">=0.6,<0.7"]


class SkillHeader(CatalogDocument):
    schema_version: Literal["1"]
    kind: Literal["skill"]
    name: str = Field(pattern=r"^[a-z0-9-]+$")
    version: str = Field(pattern=r"^v[0-9]+(?:\.[0-9]+){0,2}(?:[-+][a-z0-9.-]+)?$")
    summary: str = Field(min_length=1, max_length=512)
    roles: list[AgentRole] = Field(min_length=1)
    readiness_requirements: list[str] = Field(default_factory=list)
    tools: list[ToolPin] = Field(default_factory=list)
    framework: Literal["deepagents"]
    framework_version: Literal[">=0.6,<0.7"]

    @model_validator(mode="after")
    def values_are_unique(self) -> SkillHeader:
        if len(set(self.roles)) != len(self.roles):
            raise ValueError("skill roles must be unique")
        if len(set(self.readiness_requirements)) != len(self.readiness_requirements):
            raise ValueError("skill readiness requirements must be unique")
        if len({tool.address for tool in self.tools}) != len(self.tools):
            raise ValueError("skill tools must be unique")
        if any(
            not item
            or len(item) > 128
            or not all(character.isalnum() or character in "._-" for character in item)
            for item in self.readiness_requirements
        ):
            raise ValueError("skill readiness requirements must be stable reason-like ids")
        return self


class WorkspacePolicyDocument(CatalogDocument):
    virtual_mode: Literal[True]
    max_total_bytes: int = Field(ge=1)
    max_file_bytes: int = Field(ge=1)
    max_file_count: int = Field(ge=1)
    allowed_extensions: list[str]
    readable_prefixes: list[str]
    writable_prefixes: list[str]
    retention_class: str = Field(min_length=1, max_length=255)

    def to_contract(self) -> WorkspacePolicy:
        return WorkspacePolicy(
            virtual_mode=self.virtual_mode,
            max_total_bytes=self.max_total_bytes,
            max_file_bytes=self.max_file_bytes,
            max_file_count=self.max_file_count,
            allowed_extensions=tuple(self.allowed_extensions),
            readable_prefixes=tuple(self.readable_prefixes),
            writable_prefixes=tuple(self.writable_prefixes),
            retention_class=self.retention_class,
        )


class ProfileDefinition(CatalogDocument):
    schema_version: Literal["1"]
    kind: Literal["profile"]
    name: str = Field(pattern=r"^[a-z0-9-]+$")
    version: str = Field(pattern=r"^v[0-9]+(?:\.[0-9]+){0,2}(?:[-+][a-z0-9.-]+)?$")
    status: ProfileStatus
    role: AgentRole
    prompt: CatalogResourcePin
    skills: list[CatalogResourcePin] = Field(default_factory=list)
    tools: list[ToolPin]
    model: ModelPolicy
    memory_policy: Literal["scoped-advisory-v1"]
    workspace: WorkspacePolicyDocument
    delegation_roles: list[AgentRole] = Field(default_factory=list)
    delegation_tool_grants: dict[AgentRole, list[ToolPin]] = Field(default_factory=dict)
    max_delegation_depth: int = Field(ge=0, le=4)
    max_delegations: int = Field(ge=0, le=32)
    max_plan_nodes: int = Field(ge=1, le=256)
    turn_timeout_s: float = Field(default=300.0, gt=0, le=1800)
    max_model_rounds: int = Field(default=24, ge=1, le=128)

    @model_validator(mode="after")
    def profile_references_are_coherent(self) -> ProfileDefinition:
        if len({(item.name, item.version) for item in self.skills}) != len(self.skills):
            raise ValueError("profile skill references must be unique")
        if len({item.address for item in self.tools}) != len(self.tools):
            raise ValueError("profile tool pins must be unique")
        if len(set(self.delegation_roles)) != len(self.delegation_roles):
            raise ValueError("profile delegation roles must be unique")
        if self.role in self.delegation_roles:
            raise ValueError("profile cannot delegate to its own role")
        if set(self.delegation_tool_grants) != set(self.delegation_roles):
            raise ValueError("delegation tool grants must exactly match delegation roles")
        for role, tools in self.delegation_tool_grants.items():
            if len({item.address for item in tools}) != len(tools):
                raise ValueError(f"delegation tool grants for {role.value} must be unique")
        if not self.delegation_roles and (self.max_delegation_depth or self.max_delegations):
            raise ValueError("non-delegating profiles must set delegation limits to zero")
        return self


@dataclass(frozen=True, slots=True)
class PromptResource:
    ref: AgentResourceRef
    role: AgentRole
    summary: str
    content: bytes
    body: str


@dataclass(frozen=True, slots=True)
class SkillResource:
    ref: AgentResourceRef
    summary: str
    roles: tuple[AgentRole, ...]
    readiness_requirements: tuple[str, ...]
    required_tools: tuple[ToolPin, ...]
    content: bytes
    body: str


@dataclass(frozen=True, slots=True)
class ProfileResource:
    ref: AgentResourceRef
    definition: ProfileDefinition
    content: bytes


@runtime_checkable
class PromptCatalog(Protocol):
    def get(
        self,
        name: str,
        version: str,
        *,
        expected_sha256: str | None = None,
    ) -> PromptResource: ...

    def list(self) -> Sequence[PromptResource]: ...


@runtime_checkable
class SkillCatalog(Protocol):
    def get(
        self,
        name: str,
        version: str,
        *,
        expected_sha256: str | None = None,
    ) -> SkillResource: ...

    def list(self) -> Sequence[SkillResource]: ...


@runtime_checkable
class ProfileCatalog(Protocol):
    def get(
        self,
        name: str,
        version: str,
        *,
        expected_sha256: str | None = None,
    ) -> ProfileResource: ...

    def list(self) -> Sequence[ProfileResource]: ...


ResourceT = TypeVar("ResourceT", PromptResource, SkillResource, ProfileResource)


class _FolderCatalog:
    def __init__(self, root: Path, *, expected_filename: str) -> None:
        self._root = self._validate_root(root)
        self._expected_filename = expected_filename

    @staticmethod
    def _validate_root(root: Path) -> Path:
        try:
            metadata = root.lstat()
            canonical = root.resolve(strict=True)
        except OSError as exc:
            raise AgentCatalogError("agent catalog root is unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise AgentCatalogError("agent catalog root must be a real directory")
        if canonical != root:
            raise AgentCatalogError("agent catalog root must be canonical and link-free")
        return canonical

    @staticmethod
    def _real_directory(path: Path, *, label: str) -> None:
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise AgentCatalogError(f"{label} is unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise AgentCatalogError(f"{label} must be a real directory")

    @staticmethod
    def _read_regular_file(path: Path, *, address: str) -> bytes:
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise AgentCatalogError(f"resource {address!r} is unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise AgentCatalogError(f"resource {address!r} must be a regular file")
        if metadata.st_nlink != 1 or metadata.st_mode & 0o111:
            raise AgentCatalogError(f"resource {address!r} must be single-link and non-executable")
        try:
            content = path.read_bytes()
            content.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise AgentCatalogError(f"resource {address!r} must be readable UTF-8") from exc
        return content

    def _resource_files(self) -> tuple[tuple[str, str, Path], ...]:
        discovered: list[tuple[str, str, Path]] = []
        for name_directory in sorted(self._root.iterdir(), key=lambda item: item.name):
            self._real_directory(name_directory, label="resource-name directory")
            name = name_directory.name
            for version_directory in sorted(name_directory.iterdir(), key=lambda item: item.name):
                self._real_directory(version_directory, label=f"resource {name!r} version")
                version = version_directory.name
                # Constructing the ref validates immutable name/version syntax before any file body
                # is trusted. The all-zero digest is only a validation sentinel.
                try:
                    AgentResourceRef(
                        kind=ResourceKind.PROFILE,
                        name=name,
                        version=version,
                        sha256="0" * 64,
                    )
                except ValidationError as exc:
                    raise AgentCatalogError(
                        f"resource address {name}@{version} is not immutable and valid"
                    ) from exc
                entries = tuple(version_directory.iterdir())
                if len(entries) != 1 or entries[0].name != self._expected_filename:
                    raise AgentCatalogError(
                        f"resource {name}@{version} must contain only {self._expected_filename}"
                    )
                discovered.append((name, version, entries[0]))
        return tuple(discovered)

    @staticmethod
    def _lookup(
        index: Mapping[tuple[str, str], ResourceT],
        name: str,
        version: str,
        expected_sha256: str | None,
    ) -> ResourceT:
        try:
            resource = index[(name, version)]
        except KeyError:
            raise AgentCatalogError(f"resource {name}@{version} is unavailable") from None
        if expected_sha256 is not None and resource.ref.sha256 != expected_sha256:
            raise AgentCatalogError(f"resource {name}@{version} content digest changed")
        return resource


def _parse_frontmatter(content: bytes, *, address: str) -> tuple[dict[str, object], str]:
    text = content.decode("utf-8")
    if not text.startswith("---\n"):
        raise AgentCatalogError(f"resource {address!r} has no YAML front matter")
    try:
        header_text, body = text[4:].split("\n---\n", 1)
    except ValueError:
        raise AgentCatalogError(f"resource {address!r} has unterminated front matter") from None
    try:
        loaded = yaml.safe_load(header_text)
    except yaml.YAMLError as exc:
        raise AgentCatalogError(f"resource {address!r} has malformed YAML") from exc
    if not isinstance(loaded, dict) or any(not isinstance(key, str) for key in loaded):
        raise AgentCatalogError(f"resource {address!r} metadata must be a string-keyed mapping")
    if not body.strip():
        raise AgentCatalogError(f"resource {address!r} body must not be empty")
    return loaded, body


class FolderPromptCatalog(_FolderCatalog):
    def __init__(self, root: Path) -> None:
        super().__init__(root, expected_filename="SYSTEM.md")
        index: dict[tuple[str, str], PromptResource] = {}
        for name, version, path in self._resource_files():
            address = f"prompt:{name}@{version}"
            content = self._read_regular_file(path, address=address)
            values, body = _parse_frontmatter(content, address=address)
            try:
                header = PromptHeader.model_validate(values)
            except ValidationError as exc:
                raise AgentCatalogError(f"resource {address!r} metadata is invalid") from exc
            if (header.name, header.version) != (name, version):
                raise AgentCatalogError(f"resource {address!r} metadata differs from its folder")
            digest = hashlib.sha256(content).hexdigest()
            resource = PromptResource(
                ref=AgentResourceRef(
                    kind=ResourceKind.PROMPT,
                    name=name,
                    version=version,
                    sha256=digest,
                ),
                role=header.role,
                summary=header.summary,
                content=content,
                body=body,
            )
            if (name, version) in index:
                raise AgentCatalogError(f"duplicate resource {address!r}")
            index[(name, version)] = resource
        self._index = index

    def get(
        self,
        name: str,
        version: str,
        *,
        expected_sha256: str | None = None,
    ) -> PromptResource:
        return self._lookup(self._index, name, version, expected_sha256)

    def list(self) -> Sequence[PromptResource]:
        return tuple(self._index[key] for key in sorted(self._index))


class FolderSkillCatalog(_FolderCatalog):
    def __init__(self, root: Path) -> None:
        super().__init__(root, expected_filename="SKILL.md")
        index: dict[tuple[str, str], SkillResource] = {}
        for name, version, path in self._resource_files():
            address = f"skill:{name}@{version}"
            content = self._read_regular_file(path, address=address)
            values, body = _parse_frontmatter(content, address=address)
            try:
                header = SkillHeader.model_validate(values)
            except ValidationError as exc:
                raise AgentCatalogError(f"resource {address!r} metadata is invalid") from exc
            if (header.name, header.version) != (name, version):
                raise AgentCatalogError(f"resource {address!r} metadata differs from its folder")
            digest = hashlib.sha256(content).hexdigest()
            resource = SkillResource(
                ref=AgentResourceRef(
                    kind=ResourceKind.SKILL,
                    name=name,
                    version=version,
                    sha256=digest,
                ),
                summary=header.summary,
                roles=tuple(header.roles),
                readiness_requirements=tuple(header.readiness_requirements),
                required_tools=tuple(header.tools),
                content=content,
                body=body,
            )
            if (name, version) in index:
                raise AgentCatalogError(f"duplicate resource {address!r}")
            index[(name, version)] = resource
        self._index = index

    def get(
        self,
        name: str,
        version: str,
        *,
        expected_sha256: str | None = None,
    ) -> SkillResource:
        return self._lookup(self._index, name, version, expected_sha256)

    def list(self) -> Sequence[SkillResource]:
        return tuple(self._index[key] for key in sorted(self._index))


class FolderProfileCatalog(_FolderCatalog):
    def __init__(self, root: Path) -> None:
        super().__init__(root, expected_filename="profile.yaml")
        index: dict[tuple[str, str], ProfileResource] = {}
        for name, version, path in self._resource_files():
            address = f"profile:{name}@{version}"
            content = self._read_regular_file(path, address=address)
            try:
                loaded = yaml.safe_load(content.decode("utf-8"))
            except yaml.YAMLError as exc:
                raise AgentCatalogError(f"resource {address!r} has malformed YAML") from exc
            if not isinstance(loaded, dict):
                raise AgentCatalogError(f"resource {address!r} must be a YAML mapping")
            try:
                definition = ProfileDefinition.model_validate(loaded)
            except ValidationError as exc:
                raise AgentCatalogError(f"resource {address!r} schema is invalid") from exc
            if (definition.name, definition.version) != (name, version):
                raise AgentCatalogError(f"resource {address!r} metadata differs from its folder")
            digest = hashlib.sha256(content).hexdigest()
            resource = ProfileResource(
                ref=AgentResourceRef(
                    kind=ResourceKind.PROFILE,
                    name=name,
                    version=version,
                    sha256=digest,
                ),
                definition=definition,
                content=content,
            )
            if (name, version) in index:
                raise AgentCatalogError(f"duplicate resource {address!r}")
            index[(name, version)] = resource
        self._index = index

    def get(
        self,
        name: str,
        version: str,
        *,
        expected_sha256: str | None = None,
    ) -> ProfileResource:
        return self._lookup(self._index, name, version, expected_sha256)

    def list(self) -> Sequence[ProfileResource]:
        return tuple(self._index[key] for key in sorted(self._index))
