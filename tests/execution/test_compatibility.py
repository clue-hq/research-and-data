"""C5.2 exact-pin compatibility behavior."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from clue_execution import (
    CompatibilityContext,
    CompatibilityLoader,
    CompatibilityManifest,
    PinRequest,
    PinResolverRegistry,
    ResourceObservation,
    canonical_payload_digest,
)


@dataclass
class _MutableResolver:
    kind: str
    observations: dict[str, ResourceObservation | None]

    async def observe(self, request, context):
        del context
        return self.observations.get(request.key)


def _observation(
    *,
    version: str,
    status: str = "active",
    payload: object | None = None,
) -> ResourceObservation:
    value = payload if payload is not None else {"version": version, "status": status}
    return ResourceObservation(
        version=version,
        digest=canonical_payload_digest(value),
        status=status,
    )


def test_loader_returns_every_incompatibility_and_deterministic_pins() -> None:
    async def scenario() -> None:
        resolver = _MutableResolver(
            kind="field_definition",
            observations={
                "active": _observation(version="2"),
                "retired": _observation(version="1", status="retired"),
                "wrong-version": _observation(version="3"),
                "wrong-digest": _observation(version="1", payload={"actual": True}),
            },
        )
        registry = PinResolverRegistry()
        registry.register(resolver)
        loader = CompatibilityLoader(registry)
        report = await loader.load(
            CompatibilityManifest(
                execution=(
                    PinRequest(kind="unsupported", key="x", version="1"),
                    PinRequest(kind="field_definition", key="missing", version="1"),
                    PinRequest(kind="field_definition", key="retired", version="1"),
                    PinRequest(kind="field_definition", key="wrong-version", version="2"),
                    PinRequest(
                        kind="field_definition",
                        key="wrong-digest",
                        digest="0" * 64,
                    ),
                    PinRequest(kind="field_definition", key="active", version="2"),
                )
            ),
            context=CompatibilityContext(workspace_id="ws"),
        )

        assert [pin.key for pin in report.pins] == ["active"]
        assert [(item.key, item.reason) for item in report.incompatibilities] == [
            ("missing", "missing"),
            ("retired", "retired"),
            ("wrong-digest", "digest_mismatch"),
            ("wrong-version", "version_mismatch"),
            ("x", "unsupported_kind"),
        ]
        assert report.compatible is False

    from tests.db.conftest import run_async

    run_async(scenario())


def test_node_recheck_catches_retirement_after_initial_load() -> None:
    async def scenario() -> None:
        resolver = _MutableResolver(
            kind="source_manifest",
            observations={"web": _observation(version="1")},
        )
        registry = PinResolverRegistry()
        registry.register(resolver)
        loader = CompatibilityLoader(registry)
        manifest = CompatibilityManifest(
            nodes={"research": (PinRequest(kind="source_manifest", key="web", version="1"),)}
        )

        initial = await loader.load(
            manifest,
            context=CompatibilityContext(workspace_id="ws"),
        )
        assert initial.compatible

        resolver.observations["web"] = _observation(version="1", status="retired")
        dispatch = await loader.recheck_node(
            manifest,
            node_key="research",
            context=CompatibilityContext(workspace_id="ws"),
        )
        assert dispatch.compatible is False
        assert dispatch.incompatibilities[0].reason == "retired"

    from tests.db.conftest import run_async

    run_async(scenario())


def test_optional_disabled_memory_is_pinned_but_required_memory_fails() -> None:
    async def scenario() -> None:
        registry = PinResolverRegistry()
        registry.register(
            _MutableResolver(
                kind="memory_switch",
                observations={
                    "workspace": _observation(version="live", status="disabled"),
                },
            )
        )
        loader = CompatibilityLoader(registry)
        context = CompatibilityContext(workspace_id="ws")

        optional = await loader.load(
            CompatibilityManifest(
                execution=(
                    PinRequest(
                        kind="memory_switch",
                        key="workspace",
                        version="live",
                        required=False,
                    ),
                )
            ),
            context=context,
        )
        assert optional.compatible
        assert optional.pins[0].status == "disabled"

        required = await loader.load(
            CompatibilityManifest(
                execution=(PinRequest(kind="memory_switch", key="workspace", version="live"),)
            ),
            context=context,
        )
        assert required.incompatibilities[0].reason == "memory_disabled"

    from tests.db.conftest import run_async

    run_async(scenario())


def test_conflicting_duplicate_requirement_is_named() -> None:
    async def scenario() -> None:
        registry = PinResolverRegistry()
        registry.register(
            _MutableResolver(
                kind="tool",
                observations={"echo": _observation(version="2")},
            )
        )
        report = await CompatibilityLoader(registry).load(
            CompatibilityManifest(
                execution=(
                    PinRequest(kind="tool", key="echo", version="1"),
                    PinRequest(kind="tool", key="echo", version="2"),
                )
            ),
            context=CompatibilityContext(workspace_id="ws"),
        )
        assert any(item.reason == "conflicting_requirement" for item in report.incompatibilities)

    from tests.db.conftest import run_async

    run_async(scenario())


@pytest.mark.parametrize("reverse", [False, True])
def test_dynamic_digest_can_strengthen_the_same_static_policy_pin(reverse: bool) -> None:
    """Recipe #0 names policy v1; submit_ingestion adds its exact content hash."""

    async def scenario() -> None:
        observation = _observation(version="1")
        registry = PinResolverRegistry()
        registry.register(
            _MutableResolver(kind="ingestion_policy", observations={"default": observation})
        )
        requests = (
            PinRequest(kind="ingestion_policy", key="default", version="1"),
            PinRequest(
                kind="ingestion_policy", key="default", version="1", digest=observation.digest
            ),
        )
        if reverse:
            requests = tuple(reversed(requests))
        report = await CompatibilityLoader(registry).resolve_requirements(
            requests, context=CompatibilityContext(workspace_id="ws")
        )
        assert report.compatible, report.incompatibilities
        assert len(report.pins) == 1
        assert report.pins[0].digest == observation.digest

    from tests.db.conftest import run_async

    run_async(scenario())


@pytest.mark.parametrize("reverse", [False, True])
def test_combined_requirements_keep_version_digest_and_required_checks(reverse: bool) -> None:
    async def scenario() -> None:
        registry = PinResolverRegistry()
        resolver = _MutableResolver(kind="ingestion_policy", observations={})
        registry.register(resolver)
        loader = CompatibilityLoader(registry)
        expected = _observation(version="1")
        requests = (
            PinRequest(kind="ingestion_policy", key="default", version="1", required=False),
            PinRequest(kind="ingestion_policy", key="default", digest=expected.digest),
        )
        if reverse:
            requests = tuple(reversed(requests))
        for observation, reason in (
            (None, "missing"),
            (_observation(version="2"), "version_mismatch"),
            (_observation(version="1", payload={"changed": True}), "digest_mismatch"),
        ):
            resolver.observations["default"] = observation
            report = await loader.resolve_requirements(
                requests, context=CompatibilityContext(workspace_id="ws")
            )
            assert not report.compatible
            assert [item.reason for item in report.incompatibilities] == [reason]

    from tests.db.conftest import run_async

    run_async(scenario())


def test_conflicting_content_hashes_still_refuse_the_same_version() -> None:
    async def scenario() -> None:
        observation = _observation(version="1")
        registry = PinResolverRegistry()
        registry.register(
            _MutableResolver(kind="ingestion_policy", observations={"default": observation})
        )
        report = await CompatibilityLoader(registry).resolve_requirements(
            (
                PinRequest(kind="ingestion_policy", key="default", version="1"),
                PinRequest(kind="ingestion_policy", key="default", digest=observation.digest),
                PinRequest(kind="ingestion_policy", key="default", digest="0" * 64),
            ),
            context=CompatibilityContext(workspace_id="ws"),
        )
        assert not report.compatible
        assert any(item.reason == "conflicting_requirement" for item in report.incompatibilities)

    from tests.db.conftest import run_async

    run_async(scenario())
