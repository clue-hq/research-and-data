"""The shared processor-chain pieces — built once, here, and nowhere else.

Two layers, matching the stdlib-bridge design:

* **shared pre-chain** (``build_shared_processors``) — runs for BOTH native
  structlog events and foreign stdlib records (uvicorn, alembic,
  ``logging.getLogger``), so the whole process emits one uniform stream:
  ``merge_contextvars → add_trace_ids → add_log_level → add_logger_name → ISO TimeStamper →
  callsite (debug only) → redact``.
* **per-handler tail** (``build_processor_formatter``) — the
  ``ProcessorFormatter`` bolted onto each stdlib handler:
  ``remove_processors_meta → truncate (console only) → format_exc_info →
  renderer``.

Splitting truncation into the per-handler tail is deliberate: the same event is
truncated for the console yet written whole to ``run.jsonl`` (which uses a
formatter built with ``truncate=False``).
"""

from __future__ import annotations

import sys
from typing import Any

import structlog
from structlog.typing import Processor

from clue_obs.config_types import LogFormat, LogMode
from clue_obs.otel.trace_ids import add_trace_ids
from clue_obs.redact import redact_processor
from clue_obs.truncate import make_truncate_processor


def build_shared_processors(mode: LogMode) -> list[Processor]:
    """The pre-render chain shared by structlog + the stdlib bridge."""
    procs: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        add_trace_ids,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if mode is LogMode.DEBUG:
        procs.append(
            structlog.processors.CallsiteParameterAdder(
                {
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.LINENO,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                }
            )
        )
    procs.append(redact_processor)
    return procs


def supports_color(stream: Any = None) -> bool:
    stream = stream if stream is not None else sys.stdout
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def build_renderer(fmt: LogFormat, *, colors: bool | None = None) -> Processor:
    """Console = structlog's ANSI ConsoleRenderer; file/json = one JSON event
    per line."""
    if fmt is LogFormat.CONSOLE:
        use_colors = supports_color() if colors is None else colors
        return structlog.dev.ConsoleRenderer(colors=use_colors)
    return structlog.processors.JSONRenderer(sort_keys=True)


def build_processor_formatter(
    mode: LogMode,
    *,
    truncate: bool,
    renderer: Processor,
) -> structlog.stdlib.ProcessorFormatter:
    """Assemble the per-handler ProcessorFormatter (shared pre-chain wired as
    ``foreign_pre_chain`` so stdlib records get the identical treatment)."""
    tail: list[Processor] = [structlog.stdlib.ProcessorFormatter.remove_processors_meta]
    if truncate:
        tail.append(make_truncate_processor(mode))
    # ConsoleRenderer renders exc_info itself and warns if format_exc_info
    # precedes it; JSON needs the explicit formatting to serialize tracebacks.
    if not isinstance(renderer, structlog.dev.ConsoleRenderer):
        tail.append(structlog.processors.format_exc_info)
    tail.append(renderer)
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=build_shared_processors(mode),
        processors=tail,
    )
