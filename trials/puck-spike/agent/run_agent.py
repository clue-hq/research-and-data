"""Run the Puck page agent on one case: build the workspace, run one or more turns on one session,
write the run record (T3 of the phase-2 spike).

Inputs come from a finished platform run (its brief, account and workspace) and the platform's
real reads (account research, seller files, web search). The lane database is only read. The
page renders on the spike's dev server, which must be running on :3047.

Usage (from the repo root):

    set -a; source .env; set +a
    .venv/bin/python trials/puck-spike/agent/run_agent.py --case A --label a1
    .venv/bin/python trials/puck-spike/agent/run_agent.py --case A --label a1-edits --turns edits.txt
    .venv/bin/python trials/puck-spike/agent/run_agent.py --label a1-edits --from-run a1 --turns edits.txt

--turns adds one turn per line after the build, on the same session. --from-run starts a new
session on a copy of a finished run's workspace and runs only the --turns (no build).
Everything lands in trials/puck-spike/agent-runs/<label>/.
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import socket
import sys
import time
import uuid
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
SPIKE = AGENT_DIR.parent
REPO = SPIKE.parents[1]
RUNS = SPIKE / "agent-runs"
BASE_URL = "http://localhost:3047"

sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(REPO / "trials" / "web-agent"))

from trials_puck_agent import workspace as ws  # noqa: E402
from trials_puck_agent.harness import build_agent, build_model  # noqa: E402
from trials_puck_agent.tools import PageTools  # noqa: E402

BUILD_PROMPT = "Build the landing page for {account} ({domain}) described in /brief.md."


def server_up() -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", 3047)) == 0


def gather_inputs(case: dict) -> dict:
    """The brief, the account and its research, and the seller's files, read from the platform."""
    from clue_db import db_lifespan
    from clue_design.envelopes import DesignTurnEnvelope
    from clue_fleet import install_thread_pool
    from run_trial import PlatformLoop, build_platform_reads, read_source_run

    platform = PlatformLoop()
    install_thread_pool(platform.loop, max_workers=8)
    lifespan = db_lifespan()
    platform.run(lifespan.__aenter__())
    try:
        if case.get("source_run"):
            source = platform.run(read_source_run(case["source_run"]))
        else:  # a workspace with no design run: its project, and a turn whose knowledge pin it reads
            source = {
                "workspace_id": case["workspace_id"],
                "payload": {
                    "project_id": case["project_id"],
                    "config": {"delegation_bundle": {"opened_by_turn_id": case["knowledge_turn_id"]}},
                },
            }
        payload = source["payload"]
        config = payload["config"]
        bundle = config["delegation_bundle"]
        artifact = bundle.get("artifact") or {}
        card = config.get("account_card") or {}
        account_entity_id = case.get("account_entity_id") or next(
            item["account_id"] for item in bundle.get("artifacts") or [] if item.get("account_id")
        )
        account = case.get("account_name") or card.get("name")
        domain = case.get("account_domain") or card.get("domain")
        if case.get("brief_file"):
            brief = (AGENT_DIR / case["brief_file"]).read_text()
        else:
            brief = bundle["brief"] + "\n\nTHIS ARTIFACT: " + json.dumps(artifact)
        envelope = DesignTurnEnvelope(
            work_id=uuid.uuid4(),
            workspace_id=source["workspace_id"],
            config=config,
            kind="web_turn",
            run_id=f"run_{uuid.uuid4().hex}",
            checkpoint_thread_id=f"puck_{uuid.uuid4().hex}",
            project_id=payload.get("project_id"),
            document_id=f"doc_{uuid.uuid4().hex}",
        )
        reads = platform.run(build_platform_reads(platform, envelope=envelope))
        research: dict[str, list] = {}
        research_errors: dict[str, str] = {}
        for section in ("overview", "insights"):
            try:
                research[section] = ws.read_research(reads, account_entity_id, section)
            except Exception as error:  # a page not written yet, or an account outside the project
                research[section], research_errors[section] = [], repr(error)
        knowledge = reads.seller_knowledge()
    except BaseException:
        platform.run(lifespan.__aexit__(None, None, None))
        platform.stop()
        raise
    return {
        "platform": platform, "lifespan": lifespan, "reads": reads, "brief": brief,
        "account": account, "domain": domain, "account_entity_id": account_entity_id,
        "overview": research["overview"], "insights": research["insights"], "knowledge": knowledge,
        "research_errors": research_errors,
    }


def transcript(messages: list) -> list[dict]:
    """The saved history without image data."""
    out = []
    for message in messages:
        content = message.content
        if isinstance(content, list):
            content = [
                {"type": "image", "bytes": len(base64.b64decode(block.get("data", "")))}
                if isinstance(block, dict) and block.get("type") == "image" else block
                for block in content
            ]
        out.append({
            "type": message.type,
            "name": getattr(message, "name", None),
            "content": content,
            "tool_calls": getattr(message, "tool_calls", None) or None,
        })
    return out


def summarize_turn(turn, events: list[dict], messages: list) -> dict:
    tool_counts: dict[str, int] = {}
    for call in turn.calls:
        for name in call["tool_calls"]:
            tool_counts[name] = tool_counts.get(name, 0) + 1
    invalid = [e for e in events if e["kind"] == "invalid"]
    final = next((m for m in reversed(messages) if m.type == "ai" and not getattr(m, "tool_calls", None)), None)
    return {
        "prompt": turn.prompt,
        "status": turn.status,
        "seconds": turn.seconds,
        "model_calls": len(turn.calls),
        "input_tokens": sum(c["input_tokens"] for c in turn.calls),
        "cached_tokens": sum(c["cached_tokens"] for c in turn.calls),
        "output_tokens": sum(c["output_tokens"] for c in turn.calls),
        "cost_usd": round(sum(c["cost_cents"] for c in turn.calls) / 100, 4),
        "tool_counts": tool_counts,
        "render_rounds": sum(1 for e in events if e["kind"] == "render"),
        "validations": {
            "valid": sum(1 for e in events if e["kind"] == "valid"),
            "invalid": len(invalid),
            "errors": [error for e in invalid for error in e["errors"]],
        },
        "loop_guards": [e["errors"] for e in events if e["kind"] == "loop_guard"],
        "restores": [e["version"] for e in events if e["kind"] == "restore"],
        "retries": [e for e in events if e["kind"] == "retry"],
        "finish_reminders": turn.reminders,
        "calls": turn.calls,
        "final_message": final.content if final else None,
    }


def history_count(workspace: Path) -> int:
    path = workspace / "history.md"
    return path.read_text().count("\n## ") if path.exists() else 0


def restore_turn(source: Path, previous: dict, workspace: Path, turn: int) -> None:
    """Put the site back as it was after `turn` of the source run, and write its history."""
    snapshot = source / "turns" / str(turn)
    for name in ("page.json", "shell.json", "plan.md"):
        shutil.copy2(snapshot / name, workspace / name)
    shutil.rmtree(workspace / "pages", ignore_errors=True)
    if (snapshot / "pages").exists():
        shutil.copytree(snapshot / "pages", workspace / "pages")
    for leftover in ("versions", "renders"):
        shutil.rmtree(workspace / leftover, ignore_errors=True)
    for name in ("site.md", "history.md"):
        (workspace / name).unlink(missing_ok=True)
    # Pages fetched after that turn would leak what later turns found.
    ended = time.mktime(time.strptime(previous["started_at"], "%Y-%m-%dT%H:%M:%S")) + sum(
        t["seconds"] for t in previous["turns"][:turn]) + 60
    for fetched in (workspace / "fetched").glob("*.md"):
        if fetched.stat().st_mtime > ended:
            fetched.unlink()
    before: dict = {}
    for number, entry in enumerate(previous["turns"][:turn], 1):
        after = ws._site_pages(source / "turns" / str(number))
        ws.append_history(workspace, number=number, request=entry["prompt"], changes=ws.site_changes(before, after),
                          shell_changed=False, reply=entry.get("final_message"))
        before = after


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--label", required=True)
    parser.add_argument("--case", choices=["A", "B", "C"])
    parser.add_argument("--turns", type=Path, help="More turns on the same session, one per line.")
    parser.add_argument("--from-run", help="Start from a finished run's workspace (edits only).")
    parser.add_argument("--from-turn", type=int, help="With --from-run: start from the site as it was after this turn.")
    parser.add_argument("--fresh-each", action="store_true",
                        help="A new session for every turn; code writes site.md before and history.md after each.")
    parser.add_argument("--no-clear", action="store_true",
                        help="Keep superseded tool results in the model request (clearing is on by default).")
    args = parser.parse_args()
    if not args.case and not args.from_run:
        parser.error("give --case (a build) or --from-run (edits on a finished page)")
    if not server_up():
        print("the spike dev server is not running on :3047", file=sys.stderr)
        return 2
    out = RUNS / args.label
    if out.exists():
        print(f"agent-runs/{args.label} already exists; choose another label", file=sys.stderr)
        return 2

    turns: list[str] = []
    inputs = None
    if args.from_run:
        source = RUNS / args.from_run
        previous = json.loads((source / "run.json").read_text())
        case_name = previous["case"]
        shutil.copytree(source / "workspace", out / "workspace")
        run_file = out / "workspace" / ".run.json"
        run = json.loads(run_file.read_text())
        run["site"] = f"agent-{args.label}"
        run_file.write_text(json.dumps(run))
        workspace = out / "workspace"
        setup = {"from_run": args.from_run, "from_turn": args.from_turn}
        account = previous["account"]
        if args.from_turn:
            restore_turn(source, previous, workspace, args.from_turn)
    else:
        case_name = args.case
        case = json.loads((AGENT_DIR / "cases.json").read_text())[case_name]
        inputs = gather_inputs(case)
        account = inputs["account"]
        workspace = out / "workspace"
        setup = ws.assemble(
            workspace,
            spike_root=SPIKE,
            brand=case["brand"],
            seller=case["seller"],
            site=f"agent-{args.label}",
            brief=inputs["brief"],
            account_name=account,
            overview=inputs["overview"],
            insights=inputs["insights"],
            knowledge=inputs["knowledge"],
        )
        setup["research_errors"] = inputs["research_errors"]
        turns.append(BUILD_PROMPT.format(account=account, domain=inputs["domain"]))
    if args.turns:
        turns += [line.strip() for line in args.turns.read_text().splitlines() if line.strip()]

    page_tools = PageTools(
        workspace=workspace, spike_root=SPIKE, base_url=BASE_URL,
        reads=inputs["reads"] if inputs else None,
    )
    trace_file = (out / "trace.log").open("a")

    def trace(line: str) -> None:
        print(line, flush=True)
        trace_file.write(line + "\n")
        trace_file.flush()

    agent, recorder = build_agent(page_tools, model=build_model(), trace=trace, clear_context=not args.no_clear,
                                  summary_model=build_model())
    new_session = lambda: {"configurable": {"thread_id": f"puck_{uuid.uuid4().hex}"}}  # noqa: E731
    session = new_session()
    record = {
        "label": args.label, "case": case_name, "account": account, "setup": setup,
        "clear_context": not args.no_clear, "fresh_each": args.fresh_each,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "turns": [],
    }
    try:
        for prompt in turns:
            trace(f"=== turn {len(record['turns']) + 1}/{len(turns)}: {prompt[:120]}")
            pages_before = ws._site_pages(workspace)
            shell_before = (workspace / "shell.json").read_text() if (workspace / "shell.json").exists() else ""
            if args.fresh_each:
                session = new_session()
                if pages_before:
                    (workspace / "site.md").write_text(ws.site_summary(workspace, SPIKE))
            recorder.start_turn(prompt)
            events_before = len(page_tools.events)
            started = time.monotonic()
            try:
                state = agent.invoke({"messages": [{"role": "user", "content": prompt}]}, session)
            except Exception as error:  # a crash ends the turn honestly, with what it had done
                recorder.turn.status = f"crashed: {error!r}"[:500]
                state = agent.get_state(session).values
            recorder.turn.seconds = round(time.monotonic() - started, 1)
            if recorder.turn.status == "running":
                recorder.turn.status = "ended"
            summary = summarize_turn(recorder.turn, page_tools.events[events_before:], state.get("messages", []))
            record["turns"].append(summary)
            snapshot = out / "turns" / str(len(record["turns"]))  # the site after this turn, for diffs
            snapshot.mkdir(parents=True, exist_ok=True)
            for name in ("page.json", "shell.json", "plan.md"):
                if (workspace / name).exists():
                    shutil.copy2(workspace / name, snapshot / name)
            if (workspace / "pages").exists():
                shutil.copytree(workspace / "pages", snapshot / "pages", dirs_exist_ok=True)
            if args.fresh_each:
                shell_after = (workspace / "shell.json").read_text() if (workspace / "shell.json").exists() else ""
                ws.append_history(workspace, number=history_count(workspace) + 1, request=prompt,
                                  changes=ws.site_changes(pages_before, ws._site_pages(workspace)),
                                  shell_changed=shell_before != shell_after, reply=summary["final_message"])
            trace(
                f"=== {summary['status']}: {summary['model_calls']} calls, ${summary['cost_usd']}, "
                f"{summary['seconds']}s, renders {summary['render_rounds']}"
            )
            if summary["status"] == "stopped by the safety stop":
                trace("ALERT: safety stop reached")
            if summary["status"].startswith("crashed"):
                break
    finally:
        record["prompt_size"] = recorder.prompt_size
        record["skills_words"] = {
            p.parent.name: len(p.read_text().split()) for p in (workspace / "skills").glob("*/SKILL.md")
        }
        record["total"] = {
            "cost_usd": round(sum(t["cost_usd"] for t in record["turns"]), 4),
            "model_calls": sum(t["model_calls"] for t in record["turns"]),
            "seconds": round(sum(t["seconds"] for t in record["turns"]), 1),
        }
        (out / "run.json").write_text(json.dumps(record, indent=2, default=str))
        try:
            messages = agent.get_state(session).values.get("messages", [])
            (out / "transcript.json").write_text(json.dumps(transcript(messages), indent=2, default=str))
        except Exception as error:
            (out / "transcript-error.txt").write_text(repr(error))
        if inputs:
            inputs["platform"].run(inputs["lifespan"].__aexit__(None, None, None))
            inputs["platform"].stop()
    print(json.dumps({"output": str(out), **record["total"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
