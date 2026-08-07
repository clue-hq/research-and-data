"""Human-readable CLI trace viewer for a run's ``logs/run.jsonl`` (L3).

    python -m lumen_agent.trace <run_id | path/to/run.jsonl> \
        [--follow] [--full] [--role R] [--tools-only|--messages-only]

Renders the message-level trace emitted by ``trace_callbacks.TraceCallbackHandler``
(see that module's docstring for the event schema). A bare run_id resolves under
the workspace root; a path is used directly. Colours by role (orchestrator cyan,
author green, reviewer magenta, tools dim) via ``rich`` when importable, with a
plain-ANSI fallback so the viewer never hard-fails without rich.

The rendering core (``render_report`` / ``format_event``) is colourless and
deterministic — that is the plain-ANSI path and what the tests assert against.
Colour is a thin presentation wrapper applied only on the live/console path.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

# Role → colour name (rich style / ANSI). Tools + unknown fall back to dim.
_ROLE_COLOR = {
    "orchestrator": "cyan",
    "author": "green",
    "reviewer": "magenta",
}
_ANSI = {
    "cyan": "\033[36m",
    "green": "\033[32m",
    "magenta": "\033[35m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "reset": "\033[0m",
}

_LLM_EVENTS = {"llm_call_started", "llm_call_completed", "llm_call_failed"}
_TOOL_EVENTS = {
    "tool_started",
    "tool_completed",
    "tool_failed",
    "subagent_started",
    "subagent_completed",
}

_TRUNC_LIMIT = 500


# --------------------------------------------------------------------------- #
# run_id / path resolution
# --------------------------------------------------------------------------- #
def resolve_run_log(target: str, workspace_root: Path) -> Path:
    """Resolve a CLI target to a ``run.jsonl`` path.

    - A target that names an existing file, or looks like a path (contains a
      separator or ends in ``.jsonl``), is used directly.
    - Otherwise it is a bare run_id, resolved under the workspace root as
      ``<workspace_root>/<run_id>/logs/run.jsonl``. Because substrate writes run
      directories as ``run_<id>``, a ``run_``-prefixed sibling is accepted as a
      fallback. When neither exists the primary candidate is returned anyway (so
      ``--follow`` can wait for a run that has not started writing yet).
    """
    p = Path(target)
    if p.is_file():
        return p
    if target.endswith(".jsonl") or ("/" in target) or ("\\" in target):
        return p
    primary = workspace_root / target / "logs" / "run.jsonl"
    if primary.exists():
        return primary
    prefixed = workspace_root / f"run_{target}" / "logs" / "run.jsonl"
    if prefixed.exists():
        return prefixed
    return primary


# --------------------------------------------------------------------------- #
# formatting helpers
# --------------------------------------------------------------------------- #
def _hhmmss(ts: Any) -> str:
    if not isinstance(ts, str):
        return "--:--:--"
    # ISO like 2026-07-10T20:59:38.445188Z → HH:MM:SS
    t = ts
    if "T" in t:
        t = t.split("T", 1)[1]
    return t[:8] if len(t) >= 8 else t


def _ktok(n: Any) -> str:
    if not isinstance(n, (int, float)):
        return "?"
    n = int(n)
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _dur(ms: Any) -> str:
    if not isinstance(ms, (int, float)):
        return "?"
    ms = int(ms)
    if ms >= 60000:
        return f"{ms / 60000:.1f}m"
    if ms >= 1000:
        return f"{ms / 1000:.1f}s"
    return f"{ms}ms"


def _truncate(text: str, full: bool, limit: int = _TRUNC_LIMIT) -> str:
    if full or len(text) <= limit:
        return text
    return text[:limit] + f"… (+{len(text) - limit} chars)"


def _label(role: Any, is_tool: bool) -> str:
    if is_tool:
        return "tools"
    return str(role or "?").upper()


def _pretty_tool_call(call: dict) -> str:
    name = call.get("name", "tool")
    args = call.get("args")
    if isinstance(args, dict):
        parts = []
        for k, v in args.items():
            sv = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            if isinstance(sv, str) and len(sv) > 40:
                nlines = sv.count("\n") + 1
                sv = f"… {nlines} lines" if "\n" in sv else f"…{len(sv)} chars"
            parts.append(f"{k}={sv}")
        return f"{name}({', '.join(parts)})"
    return f"{name}()"


def _render_message(msg: dict, full: bool) -> str:
    role = msg.get("role", "?")
    content = msg.get("content", "")
    if isinstance(content, list):
        chunks = []
        for block in content:
            if not isinstance(block, dict):
                chunks.append(str(block))
            elif block.get("type") == "text":
                chunks.append(block.get("text", ""))
            elif block.get("type") == "image":
                chunks.append(block.get("placeholder", "<image>"))
            else:
                chunks.append(json.dumps(block, ensure_ascii=False))
        content = " ".join(c for c in chunks if c)
    text = _truncate(str(content).replace("\n", " ").strip(), full)
    return f"      [{role}] {text}"


def format_event(ev: dict, *, full: bool = False) -> list[str]:
    """Render one event to a list of colourless text lines."""
    name = ev.get("event", "")
    role = ev.get("role")
    ts = _hhmmss(ev.get("timestamp"))
    is_tool = name in _TOOL_EVENTS
    label = _label(role, is_tool)
    lines: list[str] = []

    if name == "llm_call_started":
        model = ev.get("model", "unknown")
        n = ev.get("message_count", "?")
        lines.append(f"{ts} {label} ▸ llm start · {model} · {n} msgs")
        for msg in ev.get("messages", []) or []:
            if isinstance(msg, dict):
                lines.append(_render_message(msg, full))

    elif name == "llm_call_completed":
        toks = (
            f"in {_ktok(ev.get('input_tokens'))} / "
            f"out {_ktok(ev.get('output_tokens'))}"
        )
        fr = ev.get("finish_reason")
        frs = f" finish={fr}" if fr else ""
        lines.append(
            f"{ts} {label} ▸ llm done ({toks}, {_dur(ev.get('duration_ms'))}){frs}"
        )
        completion = (ev.get("completion") or "").strip()
        if completion:
            lines.append(f"      {_truncate(completion.replace(chr(10), ' '), full)}")
        for call in ev.get("tool_calls") or []:
            if isinstance(call, dict):
                lines.append(f"      → {_pretty_tool_call(call)}")

    elif name == "llm_call_failed":
        lines.append(f"{ts} {label} ▸ llm FAILED: {ev.get('error', '')}")

    elif name == "tool_started":
        args = ev.get("args")
        rendered = _pretty_tool_call({"name": ev.get("name"), "args": args})
        lines.append(f"{ts} {label} ▸ tool start · {rendered}")

    elif name == "tool_completed":
        result = _truncate(str(ev.get("result", "")).replace("\n", " "), full)
        lines.append(
            f"{ts} {label} ▸ tool done · {ev.get('name')} ({_dur(ev.get('duration_ms'))})"
        )
        if result:
            lines.append(f"      → {result}")

    elif name == "tool_failed":
        lines.append(
            f"{ts} {label} ▸ tool FAILED · {ev.get('name')}: {ev.get('error', '')}"
        )

    elif name == "subagent_started":
        lines.append(f"{ts} {label} ▸ subagent start · {ev.get('subagent')}")

    elif name == "subagent_completed":
        suffix = f" ({_dur(ev.get('duration_ms'))})"
        err = ev.get("error")
        errs = f" FAILED: {err}" if err else ""
        lines.append(
            f"{ts} {label} ▸ subagent done · {ev.get('subagent')}{suffix}{errs}"
        )

    elif name == "trace_callback_warning":
        lines.append(f"{ts} {label} ▸ trace warning: {ev.get('error', '')}")

    else:  # unknown / foreign event — show it plainly so nothing is lost
        lines.append(f"{ts} {label} ▸ {name}")

    return lines


# --------------------------------------------------------------------------- #
# filtering + totals
# --------------------------------------------------------------------------- #
def event_passes(ev: dict, *, role: Optional[str], tools_only: bool, messages_only: bool) -> bool:
    name = ev.get("event", "")
    if role is not None and ev.get("role") != role:
        return False
    if tools_only and name not in _TOOL_EVENTS:
        return False
    if messages_only and name not in _LLM_EVENTS:
        return False
    # Only ever render events this viewer understands (trace events); ignore
    # unrelated structured log lines that happen to share run.jsonl.
    return name in _LLM_EVENTS or name in _TOOL_EVENTS or name == "trace_callback_warning"


def build_footer(events: Iterable[dict]) -> list[str]:
    per_role: dict[str, dict[str, int]] = {}
    tool_counts: dict[str, int] = {}
    rounds: set = set()
    for ev in events:
        name = ev.get("event", "")
        role = ev.get("role") or "?"
        if ev.get("round") is not None:
            rounds.add(ev.get("round"))
        if name == "llm_call_completed":
            r = per_role.setdefault(role, {"calls": 0, "tokens": 0, "duration_ms": 0})
            r["calls"] += 1
            r["tokens"] += int(ev.get("total_tokens") or 0)
            r["duration_ms"] += int(ev.get("duration_ms") or 0)
        elif name in ("tool_completed", "tool_failed"):
            tool_counts[ev.get("name") or "tool"] = (
                tool_counts.get(ev.get("name") or "tool", 0) + 1
            )
    lines = ["", "── totals ──────────────────────────────────"]
    for role in sorted(per_role):
        r = per_role[role]
        lines.append(
            f"  {role:<13} {r['calls']} calls · {_ktok(r['tokens'])} tokens · "
            f"{_dur(r['duration_ms'])}"
        )
    if tool_counts:
        tools = ", ".join(f"{k}×{v}" for k, v in sorted(tool_counts.items()))
        lines.append(f"  tools         {tools}")
    if rounds:
        lines.append(f"  rounds        {len(rounds)}")
    return lines


# --------------------------------------------------------------------------- #
# top-level rendering
# --------------------------------------------------------------------------- #
def _parse_lines(lines: Iterable[str]) -> Iterator[dict]:
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except Exception:
            continue


def render_report(
    events: Iterable[dict],
    *,
    role: Optional[str] = None,
    tools_only: bool = False,
    messages_only: bool = False,
    full: bool = False,
) -> str:
    """The colourless, deterministic render used by tests and the plain-ANSI
    fallback: a filtered timeline plus a totals footer."""
    selected = [
        ev
        for ev in events
        if event_passes(ev, role=role, tools_only=tools_only, messages_only=messages_only)
    ]
    out: list[str] = []
    for ev in selected:
        out.extend(format_event(ev, full=full))
    out.extend(build_footer(selected))
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# colourised presentation (rich if available, else ANSI)
# --------------------------------------------------------------------------- #
def _color_for(line: str) -> Optional[str]:
    upper = line.split("▸", 1)[0]
    for role, color in _ROLE_COLOR.items():
        if role.upper() in upper:
            return color
    if "TOOLS" in upper:
        return "dim"
    if "FAILED" in line:
        return "red"
    return None


def _emit_lines(lines: list[str]) -> None:
    try:
        from rich.console import Console  # noqa: F401
        from rich.text import Text

        console = _rich_console()
        for line in lines:
            color = _color_for(line)
            if color and line.strip():
                console.print(Text(line, style=color))
            else:
                console.print(line, highlight=False)
        return
    except Exception:
        pass
    use_ansi = sys.stdout.isatty()
    for line in lines:
        color = _color_for(line) if use_ansi else None
        if color:
            print(f"{_ANSI[color]}{line}{_ANSI['reset']}")
        else:
            print(line)


def _rich_console():
    from rich.console import Console

    return Console(highlight=False, soft_wrap=True)


# --------------------------------------------------------------------------- #
# follow (tail -f)
# --------------------------------------------------------------------------- #
def _follow(path: Path, opts: argparse.Namespace) -> None:
    # Wait for the file to appear (a run may not have started writing yet).
    while not path.exists():
        print(f"(waiting for {path} …)", file=sys.stderr)
        time.sleep(0.5)
    with path.open("r", encoding="utf-8") as fh:
        while True:
            line = fh.readline()
            if not line:
                time.sleep(0.3)
                continue
            for ev in _parse_lines([line]):
                if not event_passes(
                    ev,
                    role=opts.role,
                    tools_only=opts.tools_only,
                    messages_only=opts.messages_only,
                ):
                    continue
                _emit_lines(format_event(ev, full=opts.full))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m lumen_agent.trace",
        description="Render a deepagent run's message-level trace (logs/run.jsonl).",
    )
    p.add_argument("target", help="run_id or path to run.jsonl")
    p.add_argument("--follow", action="store_true", help="tail the file live")
    p.add_argument("--full", action="store_true", help="disable truncation")
    p.add_argument("--role", choices=["orchestrator", "author", "reviewer"], default=None)
    mx = p.add_mutually_exclusive_group()
    mx.add_argument("--tools-only", action="store_true", dest="tools_only")
    mx.add_argument("--messages-only", action="store_true", dest="messages_only")
    return p


def _workspace_root() -> Path:
    try:
        from lumen_agent.config import AgentRuntimeConfig

        return AgentRuntimeConfig.from_env().workspace_root
    except Exception:
        return Path.cwd()


def main(argv: Optional[list[str]] = None) -> int:
    opts = _build_parser().parse_args(argv)
    path = resolve_run_log(opts.target, _workspace_root())

    if opts.follow:
        try:
            _follow(path, opts)
        except KeyboardInterrupt:
            pass
        return 0

    if not path.exists():
        print(f"No trace found at {path}", file=sys.stderr)
        return 1

    with path.open("r", encoding="utf-8") as fh:
        events = list(_parse_lines(fh))
    report = render_report(
        events,
        role=opts.role,
        tools_only=opts.tools_only,
        messages_only=opts.messages_only,
        full=opts.full,
    )
    _emit_lines(report.split("\n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
