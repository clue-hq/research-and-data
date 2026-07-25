"""Canonical, workspace-local C5.1 parameter snapshots and tombstone reads."""

from __future__ import annotations

from dataclasses import replace

import pytest

from clue_core import new_operation_id
from clue_execution import (
    CanonicalParameterSnapshotter,
    ParameterArtifactState,
    StoredParameterArtifact,
    resolve_parameter_body,
)
from clue_toolbelt import (
    JournalParameterPolicy,
    ToolContext,
    ToolDescriptor,
)
from tests.db.conftest import run_async
from tests.toolbelt.conftest import EchoInput, EchoTool, human_ctx


class _ArtifactStore:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], StoredParameterArtifact] = {}
        self.persist_calls = 0

    async def persist(
        self,
        *,
        workspace_id: str,
        artifact_key: str,
        content_sha256: str,
        data: bytes,
        media_type: str,
    ) -> None:
        assert artifact_key == f"{workspace_id}/{content_sha256}"
        assert media_type == "application/vnd.clue.tool-parameters+json"
        self.rows[(workspace_id, artifact_key)] = StoredParameterArtifact(
            state=ParameterArtifactState.LIVE,
            data=data,
        )
        self.persist_calls += 1

    async def resolve(self, *, workspace_id: str, artifact_key: str) -> StoredParameterArtifact:
        return self.rows.get(
            (workspace_id, artifact_key),
            StoredParameterArtifact(state=ParameterArtifactState.MISSING),
        )


def _descriptor(*safe_fields: str) -> ToolDescriptor:
    base = EchoTool().descriptor
    return replace(
        base,
        parameter_policy=JournalParameterPolicy(safe_display_fields=safe_fields),
    )


def test_snapshot_is_canonical_content_addressed_and_display_safe() -> None:
    async def scenario() -> None:
        store = _ArtifactStore()
        snapshotter = CanonicalParameterSnapshotter(store)
        ctx = human_ctx("ws-parameters")

        first = await snapshotter.snapshot(
            descriptor=_descriptor("value"),
            inputs=EchoInput(value=7, note="private detail"),
            context=ctx,
        )
        second = await snapshotter.snapshot(
            descriptor=_descriptor("value"),
            inputs=EchoInput.model_validate({"note": "private detail", "value": 7}),
            context=ctx,
        )

        assert first == second
        assert first.artifact_key == f"ws-parameters/{first.content_sha256}"
        assert first.display_params == {"value": 7}
        assert (
            await store.resolve(
                workspace_id=ctx.workspace_id,
                artifact_key=first.artifact_key,
            )
        ).data == b'{"note":"private detail","value":7}'

    run_async(scenario())


def test_parameter_resolution_is_workspace_scoped_and_erasure_is_a_tombstone() -> None:
    async def scenario() -> None:
        store = _ArtifactStore()
        snapshotter = CanonicalParameterSnapshotter(store)
        ctx = ToolContext(
            workspace_id="ws-a",
            actor="human",
            conn_factory=human_ctx().conn_factory,
            operation_id=new_operation_id(),
        )
        snapshot = await snapshotter.snapshot(
            descriptor=_descriptor(),
            inputs=EchoInput(value=1, note="personal-secret"),
            context=ctx,
        )

        cross_workspace = await resolve_parameter_body(
            store=store,
            workspace_id="ws-b",
            artifact_key=snapshot.artifact_key,
            content_sha256=snapshot.content_sha256,
        )
        assert cross_workspace.state is ParameterArtifactState.MISSING
        assert cross_workspace.body is None

        store.rows[(ctx.workspace_id, snapshot.artifact_key)] = StoredParameterArtifact(
            state=ParameterArtifactState.ERASED
        )
        erased = await resolve_parameter_body(
            store=store,
            workspace_id=ctx.workspace_id,
            artifact_key=snapshot.artifact_key,
            content_sha256=snapshot.content_sha256,
        )
        assert erased.state is ParameterArtifactState.ERASED
        assert erased.body is None
        assert "personal-secret" not in erased.model_dump_json()

    run_async(scenario())


def test_hash_mismatch_fails_closed() -> None:
    async def scenario() -> None:
        store = _ArtifactStore()
        key = "ws-a/" + "a" * 64
        store.rows[("ws-a", key)] = StoredParameterArtifact(
            state=ParameterArtifactState.LIVE,
            data=b'{"value":1}',
        )
        with pytest.raises(ValueError, match="content hash"):
            await resolve_parameter_body(
                store=store,
                workspace_id="ws-a",
                artifact_key=key,
                content_sha256="a" * 64,
            )

    run_async(scenario())
