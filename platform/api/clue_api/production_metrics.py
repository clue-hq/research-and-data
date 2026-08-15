"""Process lifecycle for privacy-safe OpenTelemetry metrics export."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

from clue_config import Settings
from clue_obs import get_logger
from clue_obs.otel import MetricRuntime, configure_metric_exporter

__all__ = ["production_metrics_lifespan"]

log = get_logger("clue_api.metrics")


@asynccontextmanager
async def production_metrics_lifespan(
    settings: Settings,
    *,
    service_name: str,
) -> AsyncIterator[None]:
    """Install OTLP export for one production process and flush it on graceful shutdown."""

    runtime: MetricRuntime | None = None
    if settings.metrics_exporter == "otlp":
        endpoint = settings.metrics_otlp_endpoint
        if not endpoint:
            # Settings rejects this too; retaining the local guard keeps direct/fake Settings-like
            # composition fail-closed rather than handing ``None`` to environment-driven SDK code.
            raise RuntimeError("OTLP metrics export requires a collector endpoint")
        runtime = configure_metric_exporter(
            OTLPMetricExporter(endpoint=endpoint),
            service_name=service_name,
            export_interval_millis=settings.metrics_export_interval_ms,
        )
        log.info(
            "metrics.exporter.started",
            exporter="otlp",
            service_name=service_name,
            export_interval_ms=settings.metrics_export_interval_ms,
        )
    else:
        log.info("metrics.exporter.started", exporter="memory", service_name=service_name)
    try:
        yield
    finally:
        if runtime is not None:
            runtime.shutdown()
            log.info("metrics.exporter.stopped", exporter="otlp", service_name=service_name)
