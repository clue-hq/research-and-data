"""The design API root carries the platform's OTel, Sentry and Langfuse installers (lane 3 slice 5).

`uvicorn lumen_api.main:app` is the design API process's root, so importing the module installs the
process's tracer provider (plus Sentry and Langfuse, both no-ops without their keys) under
``clue-design-api``, and hangs the runtime on the app the server serves.

No ``importlib.reload`` here, deliberately: the install is guarded on "this process has no root
provider yet" (see the guard's comment in ``main``), so a reload — a SECOND execution of the module
in a process that already has one — correctly installs nothing. The plain import is the real
production path.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from opentelemetry import trace

_DESIGN_ROOT = Path(__file__).resolve().parents[3]


def test_design_api_installs_tracing_under_its_own_service_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CLUE_OTEL_TRACES_ENDPOINT", raising=False)
    monkeypatch.setenv("CLUE_SENTRY_ENABLED", "false")
    monkeypatch.delenv("CLUE_LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("CLUE_LANGFUSE_SECRET_KEY", raising=False)
    import lumen_api.main as main

    provider = trace.get_tracer_provider()
    resource = getattr(provider, "resource", None)
    assert resource is not None and resource.attributes.get("service.name") == "clue-design-api"
    assert main.app.state.tracing_runtime is not None


def test_importing_main_inside_a_process_that_already_has_a_root_installs_nothing() -> None:
    """The platform fleet worker lazily imports ``lumen_api.main`` to run a design job. It has
    already installed its own provider/Sentry/Langfuse under ``clue-worker-fleet``; importing the
    design module there must not re-point any of it. Run out of process, because the install is
    process-global and this suite's own process is a design-API root."""
    script = """
import sys
from opentelemetry import trace
from clue_obs.otel import install_tracing

install_tracing(process_name="clue-worker-fleet", endpoint=None, instrument_httpx=False)
import lumen_api.main as main

resource = trace.get_tracer_provider().resource
assert resource.attributes["service.name"] == "clue-worker-fleet", resource.attributes
assert getattr(main.app.state, "tracing_runtime", None) is None
print("GUARD OK")
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(_DESIGN_ROOT),
            str(_DESIGN_ROOT / "apps/api"),
            str(_DESIGN_ROOT / "apps/agent_runtime"),
            env.get("PYTHONPATH", ""),
        ]
    )
    env["CLUE_SENTRY_ENABLED"] = "false"
    env.pop("CLUE_LANGFUSE_PUBLIC_KEY", None)
    env.pop("CLUE_LANGFUSE_SECRET_KEY", None)
    done = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=600
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "GUARD OK" in done.stdout
