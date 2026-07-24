"""Canonical parameter snapshots behind an injected governed artifact store."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from clue_toolbelt import (
    ParameterSnapshot,
    ParameterSnapshotter,
    ToolContext,
    ToolDescriptor,
    ToolInput,
)

PARAMETER_MEDIA_TYPE = "application/vnd.clue.tool-parameters+json"


class ParameterArtifactState(StrEnum):
    LIVE = "live"
    ERASED = "erased"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class StoredParameterArtifact:
    state: ParameterArtifactState
    data: bytes | None = None

    def __post_init__(self) -> None:
        if self.state is ParameterArtifactState.LIVE and self.data is None:
            raise ValueError("a live parameter artifact requires data")
        if self.state is not ParameterArtifactState.LIVE and self.data is not None:
            raise ValueError("an erased/missing parameter artifact cannot expose data")


class ParameterArtifactStore(Protocol):
    async def persist(
        self,
        *,
        workspace_id: str,
        artifact_key: str,
        content_sha256: str,
        data: bytes,
        media_type: str,
    ) -> None: ...

    async def resolve(
        self,
        *,
        workspace_id: str,
        artifact_key: str,
    ) -> StoredParameterArtifact: ...


class ParameterBodyView(BaseModel):
    """Authorized parameter resolution; execution/event views never include ``body``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_key: str
    content_sha256: str
    state: ParameterArtifactState
    body: dict[str, object] | None = None


class CanonicalParameterSnapshotter(ParameterSnapshotter):
    def __init__(self, store: ParameterArtifactStore) -> None:
        self._store = store

    async def snapshot(
        self,
        *,
        descriptor: ToolDescriptor,
        inputs: ToolInput,
        context: ToolContext,
    ) -> ParameterSnapshot:
        if not context.workspace_id:
            raise ValueError("parameter snapshots require a non-empty workspace id")
        validated = inputs.model_dump(mode="json")
        data = json.dumps(
            validated,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        digest = hashlib.sha256(data).hexdigest()
        key = f"{context.workspace_id}/{digest}"
        await self._store.persist(
            workspace_id=context.workspace_id,
            artifact_key=key,
            content_sha256=digest,
            data=data,
            media_type=PARAMETER_MEDIA_TYPE,
        )
        display = {
            field: validated[field]
            for field in descriptor.parameter_policy.safe_display_fields
            if field in validated
        }
        return ParameterSnapshot(
            artifact_key=key,
            content_sha256=digest,
            display_params=display,
        )


async def resolve_parameter_body(
    *,
    store: ParameterArtifactStore,
    workspace_id: str,
    artifact_key: str,
    content_sha256: str,
) -> ParameterBodyView:
    """Resolve one governed body or return a metadata-only tombstone."""
    artifact = await store.resolve(workspace_id=workspace_id, artifact_key=artifact_key)
    if artifact.state is not ParameterArtifactState.LIVE:
        return ParameterBodyView(
            artifact_key=artifact_key,
            content_sha256=content_sha256,
            state=artifact.state,
        )
    assert artifact.data is not None
    observed = hashlib.sha256(artifact.data).hexdigest()
    if observed != content_sha256:
        raise ValueError("parameter artifact content hash does not match its journaled digest")
    body = json.loads(artifact.data)
    if not isinstance(body, dict):
        raise ValueError("parameter artifact body is not a JSON object")
    return ParameterBodyView(
        artifact_key=artifact_key,
        content_sha256=content_sha256,
        state=artifact.state,
        body=body,
    )


__all__ = [
    "CanonicalParameterSnapshotter",
    "PARAMETER_MEDIA_TYPE",
    "ParameterArtifactState",
    "ParameterArtifactStore",
    "ParameterBodyView",
    "StoredParameterArtifact",
    "resolve_parameter_body",
]
