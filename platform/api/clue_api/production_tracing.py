"""Re-export shim: the production installers live in ``clue_obs.production`` (lane 3 slice 5).

They moved so the design API root can install the same OTel/Sentry/Langfuse composition without
importing ``clue_api`` (the seam: nothing under ``subsystems/clue-design`` may). The platform
roots keep importing them from here, unchanged.

The ``_span_exporter_override`` test seam moved with them: patch ``clue_obs.production``.
"""

from clue_obs.production import (  # noqa: F401
    install_production_langfuse,
    install_production_sentry,
    install_production_tracing,
    production_tracing_lifespan,
)

__all__ = [
    "install_production_langfuse",
    "install_production_sentry",
    "install_production_tracing",
    "production_tracing_lifespan",
]
