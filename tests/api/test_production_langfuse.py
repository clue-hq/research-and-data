"""Lane 3 slice 3a, Task 3: Langfuse composed at the roots — off by default, loud when enabled
without keys, attached to the process provider when enabled with keys."""

from __future__ import annotations

import pytest
from langfuse._client.resource_manager import LangfuseResourceManager
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from clue_api.production_tracing import install_production_langfuse
from clue_config import Secrets, Settings
from clue_obs.langfuse import langfuse_is_installed, observation, shutdown_langfuse
from clue_obs.otel import install_tracing


def _runtime():  # type: ignore[no-untyped-def]
    return install_tracing(
        process_name="clue-test", endpoint=None, set_global=False, instrument_httpx=False
    )


def test_disabled_installs_nothing() -> None:
    settings = Settings(_env_file=None, langfuse_enabled=False)
    secrets = Secrets(_env_file=None)  # type: ignore[call-arg]
    assert (
        install_production_langfuse(settings, secrets, runtime=_runtime(), service_name="t")
        is False
    )
    assert not langfuse_is_installed()


def test_enabled_without_both_keys_skips_and_boots() -> None:
    """On by default (founder, 2026-09-15): blank keys mean "no project here", never a crash."""
    settings = Settings(_env_file=None, langfuse_enabled=True)
    secrets = Secrets(_env_file=None, langfuse_public_key="pk-only")  # type: ignore[call-arg]
    assert (
        install_production_langfuse(settings, secrets, runtime=_runtime(), service_name="t")
        is False
    )
    assert not langfuse_is_installed()


def test_enabled_with_keys_attaches_to_the_process_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client's processor is added to the runtime's provider: a platform observation is one
    span on that provider, carrying the Langfuse attributes."""
    settings = Settings(
        _env_file=None,
        langfuse_enabled=True,
        langfuse_host="http://127.0.0.1:9",
        langfuse_environment="lane-test",
    )
    secrets = Secrets(  # type: ignore[call-arg]
        _env_file=None, langfuse_public_key="pk-lf-root", langfuse_secret_key="sk-lf-root"
    )
    runtime = _runtime()
    exporter = InMemorySpanExporter()
    runtime.provider.add_span_processor(SimpleSpanProcessor(exporter))
    # Keep the SDK off the network: its own exporter is swapped for an in-memory one. The seam
    # lives in clue_obs.production since lane 3 slice 5 (clue_api.production_tracing re-exports
    # the functions, so patching the shim's globals would no longer reach them).
    from clue_obs import production

    sink = InMemorySpanExporter()
    monkeypatch.setattr(production, "_span_exporter_override", sink)
    try:
        assert install_production_langfuse(settings, secrets, runtime=runtime, service_name="t")
        assert langfuse_is_installed()
        with observation("root.probe", as_type="tool"):
            pass
        spans = exporter.get_finished_spans()
        assert [span.name for span in spans] == ["root.probe"]
        assert spans[0].attributes is not None
        assert spans[0].attributes["langfuse.observation.type"] == "tool"
        assert spans[0].attributes["langfuse.environment"] == "lane-test"
    finally:
        shutdown_langfuse()
        LangfuseResourceManager.reset()
        monkeypatch.setattr(production, "_span_exporter_override", None)
