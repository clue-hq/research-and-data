"""The shared processor-chain pieces — built once, here, and nowhere else.

Two layers, matching the stdlib-bridge design:

* **shared pre-chain** (`build_shared_processors`) — runs for BOTH native
  structlog events and foreign stdlib records (uvicorn, `logging.getLogger`),
  so the whole process emits one uniform stream:
  ``merge_contextvars → add_log_level → add_logger_name → ISO TimeStamper →
  callsite (debug only) → redact``.
* **per-handler tail** (`build_processor_formatter`) — the `ProcessorFormatter`
  bolted onto each stdlib handler:
  ``remove_processors_meta → truncate (console only) → format_exc_info →
  renderer``.

Splitting truncation into the per-handler tail is deliberate: the same event is
truncated for the console yet written whole to ``run.jsonl`` (which uses a
formatter built with ``truncate=False``).
"""
from __future__ import annotations

import sys
from typing import Any, Callable

import structlog
from opentelemetry import trace
from opentelemetry.trace import format_span_id, format_trace_id

from .config_types import LogFormat, LogMode
from .redact import redact_processor
from .truncate import make_truncate_processor

Processor = Callable[[Any, str, dict], Any]


#: The attribute the platform's fleet worker stamps an escaping exception's ``(trace_id,
#: span_id)`` under (``clue_obs.otel.trace_ids.EXCEPTION_TRACE_ATTR``). Duplicated, not imported:
#: the two obs packages share no imports; keep the two literals in step.
_EXCEPTION_TRACE_ATTR = "__clue_trace_ids__"


def _logged_exception(event_dict: Any) -> BaseException | None:
    exc_info = event_dict.get("exc_info")
    if isinstance(exc_info, BaseException):
        return exc_info
    if isinstance(exc_info, tuple) and len(exc_info) == 3:
        return exc_info[1] if isinstance(exc_info[1], BaseException) else None
    if exc_info is True:
        return sys.exc_info()[1]
    return None


def add_trace_ids(logger: Any, method_name: str, event_dict: Any) -> Any:
    """Stamp ``trace_id``/``span_id`` (32/16 lowercase hex, the ids Langfuse shows) from the
    current OpenTelemetry span, else from the logged exception's platform stamp — the twin of
    ``clue_obs.otel.trace_ids.add_trace_ids`` (2026-10-03 agent-scoped tracing spec, R4)."""
    del logger, method_name
    context = trace.get_current_span().get_span_context()
    ids: Any = None
    if context.is_valid:
        ids = (format_trace_id(context.trace_id), format_span_id(context.span_id))
    else:
        logged = _logged_exception(event_dict)
        ids = getattr(logged, _EXCEPTION_TRACE_ATTR, None) if logged is not None else None
    if isinstance(ids, tuple) and len(ids) == 2:
        event_dict.setdefault("trace_id", ids[0])
        event_dict.setdefault("span_id", ids[1])
    return event_dict


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
    """Console = structlog's ANSI ConsoleRenderer (no `rich` needed — plain
    ANSI is built in); file/json = one JSON event per line."""
    if fmt is LogFormat.CONSOLE:
        use_colors = supports_color() if colors is None else colors
        return structlog.dev.ConsoleRenderer(colors=use_colors)
    return structlog.processors.JSONRenderer(sort_keys=True)


def build_processor_formatter(
    mode: LogMode,
    *,
    truncate: bool,
    renderer: Processor,
) -> "structlog.stdlib.ProcessorFormatter":
    """Assemble the per-handler ProcessorFormatter (shared pre-chain wired as
    ``foreign_pre_chain`` so stdlib records get the identical treatment)."""
    tail: list[Processor] = [structlog.stdlib.ProcessorFormatter.remove_processors_meta]
    if truncate:
        tail.append(make_truncate_processor(mode))
    # ConsoleRenderer renders exc_info itself (rich tracebacks when available)
    # and warns if format_exc_info precedes it; JSON needs the explicit
    # formatting to serialize the traceback as a string field.
    if not isinstance(renderer, structlog.dev.ConsoleRenderer):
        tail.append(structlog.processors.format_exc_info)
    tail.append(renderer)
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=build_shared_processors(mode),
        processors=tail,
    )
