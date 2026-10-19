"""Run one website-deepagent turn in a trial setting, outside the platform's chat flow.

The real design runtime and the platform's real research reads run unchanged, in this process.
Only two things differ from production, and only in this process:

- the skill set: a copy of the platform's knowledge_docs with this folder's overlay/ applied
  and the paths in removed.txt deleted;
- the prompt lines in prompt_overrides.py.

The input is replayed from a finished platform run: the same brief, account card, brand-kit pin
and asset snapshot (read from that run's design_agent_run row), so a trial differs from the
original run only in the skills. Nothing is written to the platform's documents: the trial
mints its own empty web document in memory and keeps the result under runs/<label>/.

Usage (from the repo root):

    set -a; source .env; set +a
    .venv/bin/python trials/web-agent/run_trial.py --label syracuse-skill-only

The agent's own workspace (plan.md, previews, logs) lands in trials/web-agent/workspace/, never
in the platform's .deepagent-workspace/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

TRIAL = Path(__file__).resolve().parent
REPO = TRIAL.parents[1]
PLATFORM_KNOWLEDGE = REPO / "subsystems/clue-design/apps/agent_runtime/knowledge_docs"
EXAMPLE = "skills/account-page-copy/references/worked-example-syracuse.md"
EXAMPLE_LINK = "\nFor a finished example of the plan and the page, read\n"
DEFAULT_SOURCE_RUN = "run_d71298e8df7c54c79631623b9f460ce4"  # Syracuse, Run 3 (2026-10-06)

#: Staged mode, build stage: tools a build from a finished copy plan never needs. Dropping them
#: also drops their definitions from every model call.
STAGED_BUILD_DROPPED_TOOLS = frozenset(
    {
        "fetch_page",
        "search_assets",
        "list_custom_components",
        "inspect_custom_component",
        "list_pages",
        "add_page",
        "remove_page",
        "switch_page",
        "read_project_accounts",
        "read_account_research",
        "read_claims",
        "web_search",
        "author_web_page",
        "author_web_subtree",
        "recreate_cloned_page",
        "release_repair",
        "asset",
        "write_custom_component_source",
        "compile_custom_component",
        "place_custom_component",
    }
)

STAGED_BUILD_INSTRUCTION = """

BUILD STAGE — the copy stage has already finished. plan.md in your workspace is final: it names
every section's clone, the slot values, the text edits and the buttons, and the shell's
prepared-for line and header button. Do not re-plan, do not read the account research or the copy
skills, and do not look for other clones. This instruction overrides any planning or
review-coverage step in the skills.

1. Read plan.md once.
2. Build the page: the campaign header and footer and the listed clones in the listed order,
   with the slot values given in the same call that pins them. Apply each text edit and button
   change with repair_cloned_section. Inspect a clone's text only when an edit does not match.
3. Render once with render_web_preview. Look at the 1440 and 375 previews only, not every tile.
4. Fix only blocking defects: a missing or broken section, wrong words, a wrong button label or
   link, overflowing text. At most one more render after fixes.
5. Call finalize_web_run with what was built and what remains open.
"""


def drop_build_tools(dropped: list[str]) -> None:
    """Filter the build stage's tools at the one place the harness hands them to deepagents."""
    import deepagents

    original = deepagents.create_deep_agent

    def create_deep_agent(*args: Any, **kwargs: Any) -> Any:
        kept = []
        for item in kwargs.get("tools") or []:
            if getattr(item, "name", None) in STAGED_BUILD_DROPPED_TOOLS:
                dropped.append(item.name)
            else:
                kept.append(item)
        kwargs["tools"] = kept
        return original(*args, **kwargs)

    deepagents.create_deep_agent = create_deep_agent


def build_skill_set(dest: Path, *, with_example: bool) -> list[str]:
    """Platform knowledge_docs + overlay - removed.txt. Returns the changed paths."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(PLATFORM_KNOWLEDGE, dest)
    changed: list[str] = []
    overlay = TRIAL / "overlay"
    for source in sorted(overlay.rglob("*")):
        if source.is_file():
            relative = source.relative_to(overlay)
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            changed.append(f"overlay {relative}")
    for line in (TRIAL / "removed.txt").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            (dest / line).unlink()
            changed.append(f"removed {line}")
    if not with_example:
        (dest / EXAMPLE).unlink()
        skill = dest / "skills/account-page-copy/SKILL.md"
        skill.write_text(skill.read_text().split(EXAMPLE_LINK)[0].rstrip() + "\n")
        changed.append(f"removed {EXAMPLE} (and its link)")
    return changed


class PlatformLoop:
    """The event loop the platform's async reads run on, in a thread of its own."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coroutine: Any, timeout: float = 300.0) -> Any:
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)


async def read_source_run(run_id: str) -> dict[str, Any]:
    from clue_db import transaction
    from sqlalchemy import text

    async with transaction() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "select workspace_id, payload, asset_context_snapshot "
                        "from design_agent_run where run_id = :run_id"
                    ),
                    {"run_id": run_id},
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


async def build_platform_reads(platform: PlatformLoop, *, envelope: Any) -> Any:
    """The same governed reads a design leg turn gets, composed as fleet_main composes them."""
    from clue_api.arv2.read_tools import DbArv2ReadService
    from clue_api.design_loop_bridge import PlatformLoopBridge
    from clue_api.design_platform_reads import DesignPlatformReadError, DesignPlatformReads
    from clue_api.execution_wiring import build_tool_invoker
    from clue_api.storage_wiring import build_storage_backend
    from clue_api.toolbelt_wiring import build_toolbelt
    from clue_config import Secrets, load_settings
    from clue_db import transaction
    from clue_toolbelt import DbIdempotencyStore

    settings = load_settings()
    storage = build_storage_backend(settings)
    registry = build_toolbelt(
        storage=storage,
        settings=settings,
        secrets=Secrets(),
        arv2_reads=DbArv2ReadService(settings=settings),
    )
    invoker = build_tool_invoker(
        registry=registry,
        idempotency_store=DbIdempotencyStore(),
        storage=storage,
        settings=settings,
    )
    return DesignPlatformReads(
        envelope=envelope,
        invoker=invoker,
        storage=storage,
        conn_factory=transaction,
        bridge=PlatformLoopBridge(
            loop=platform.loop, timeout_s=90.0, error=DesignPlatformReadError
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--label", required=True, help="Name of this trial run (folder name).")
    parser.add_argument("--source-run", default=DEFAULT_SOURCE_RUN)
    parser.add_argument(
        "--brief-file",
        type=Path,
        default=None,
        help="Replace the source run's brief (the 'For the page' / 'Notes' text) with this file.",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Copy stage in text first, then a narrowed build stage that applies its plan.",
    )
    parser.add_argument(
        "--with-example",
        action="store_true",
        help="Include the Syracuse worked example. Leave it out when the trial is Syracuse itself.",
    )
    args = parser.parse_args()

    out = TRIAL / "runs" / args.label
    if out.exists():
        print(f"runs/{args.label} already exists; choose another label", file=sys.stderr)
        return 2
    out.mkdir(parents=True)

    # Isolation: the trial's agent workspace, never the platform's. Set before any lumen import
    # reads settings.
    workspace = TRIAL / "workspace"
    os.environ["LUMEN_AGENT_WORKSPACE_ROOT"] = str(workspace)
    os.environ["LUMEN_AGENT_TRACE_DIR"] = str(workspace)

    skill_set = TRIAL / "skill-set"
    changed = build_skill_set(skill_set, with_example=args.with_example)

    import lumen_agent.materialize as materialize

    materialize._PACKAGE_KNOWLEDGE_DOCS = skill_set
    sys.path.insert(0, str(TRIAL))
    import prompt_overrides

    prompt_overrides.apply()

    from clue_db import db_lifespan
    from clue_design.envelopes import DesignTurnEnvelope
    from clue_design.leg_context import render_leg_turn_prompt
    from clue_api.design_tools import mint_empty_web_document
    from clue_fleet import install_thread_pool
    from lumen_api.main import repo_root, run_web_agent_turn

    platform = PlatformLoop()
    install_thread_pool(platform.loop, max_workers=8)
    lifespan = db_lifespan()
    platform.run(lifespan.__aenter__())
    try:
        source = platform.run(read_source_run(args.source_run))
        payload = source["payload"]
        config = payload["config"]
        workspace_id = source["workspace_id"]

        run_id = f"run_{uuid.uuid4().hex}"
        session_id = f"dsess_{uuid.uuid4().hex}"
        document_id = f"doc_{uuid.uuid4().hex}"

        bundle = json.loads(json.dumps(config["delegation_bundle"]))
        if args.brief_file is not None:
            bundle["brief"] = args.brief_file.read_text()
        bundle["target_document"] = {"document_id": document_id, "version_guard": 0}
        for item in bundle.get("artifacts") or []:
            item["document_id"] = document_id
        artifact = bundle.get("artifact")
        prompt = render_leg_turn_prompt(
            bundle=bundle,
            history=None,
            prompt=config["request"]["prompt"],
            drift_note=None,
            artifact=artifact,
        )

        kit = bundle["brand_kit"]
        web_doc = mint_empty_web_document(
            document_id=document_id,
            title=(artifact or {}).get("title") or "Trial page",
            brand_kit_ref={"id": kit["brand_kit_id"], "version": kit["version"]},
        )
        document = {
            "document_id": document_id,
            "doc_kind": "web",
            "scene": web_doc,
            "current_version": 0,
            "account_id": None,
        }

        envelope = DesignTurnEnvelope(
            work_id=uuid.uuid4(),
            workspace_id=workspace_id,
            config=config,
            kind="web_turn",
            run_id=run_id,
            checkpoint_thread_id=run_id,
            project_id=payload.get("project_id"),
            document_id=document_id,
        )
        reads = platform.run(build_platform_reads(platform, envelope=envelope))

        dropped: list[str] = []
        if args.staged:
            from copy_stage import run_copy_stage
            from lumen_agent.config import AgentRuntimeConfig
            from lumen_api.agent_cloned_sections import DurableAgentClonedSectionRegistry
            from lumen_api.main import api_blob_store, api_engine_cache_root

            registry = DurableAgentClonedSectionRegistry(
                blobs=api_blob_store(workspace_id),
                cache_dir=api_engine_cache_root(workspace_id),
            )
            account_entity_id = next(
                item["account_id"] for item in bundle["artifacts"] if item.get("account_id")
            )
            print("copy stage: started", flush=True)
            plan = run_copy_stage(
                config=AgentRuntimeConfig.from_env(repo_root()),
                reads=reads,
                registry=registry,
                brief=bundle["brief"] + "\n\nTHIS ARTIFACT: " + json.dumps(artifact or {}),
                account_entity_id=account_entity_id,
                kit_version=kit["version"],
                skill_text=(skill_set / "skills/account-page-copy/SKILL.md").read_text(),
                out=out,
            )
            print("copy stage: done", flush=True)
            plan_path = workspace / "sessions" / session_id / "workspace" / "plan.md"
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(plan)
            prompt = prompt + STAGED_BUILD_INSTRUCTION
            drop_build_tools(dropped)

        (out / "prompt.md").write_text(prompt)
        (out / "skill-set-changes.txt").write_text("\n".join(changed) + "\n")
        (out / "trial.json").write_text(
            json.dumps(
                {
                    "label": args.label,
                    "source_run": args.source_run,
                    "run_id": run_id,
                    "session_id": session_id,
                    "document_id": document_id,
                    "workspace_id": workspace_id,
                    "brief_file": str(args.brief_file) if args.brief_file else None,
                    "with_example": args.with_example,
                    "staged": args.staged,
                },
                indent=2,
            )
        )
        print(f"trial {args.label}: run {run_id}, session {session_id}", flush=True)
        print(f"agent workspace: {workspace / 'sessions' / session_id}", flush=True)

        started = time.monotonic()
        response = run_web_agent_turn(
            document,
            prompt,
            None,
            repo_root(),
            account_card=config.get("account_card"),
            asset_library=source.get("asset_context_snapshot"),
            workspace_id=workspace_id,
            session_id=session_id,
            run_id=run_id,
            platform_reads=reads,
        )
        elapsed = time.monotonic() - started
    finally:
        platform.run(lifespan.__aexit__(None, None, None))
        platform.stop()

    (out / "response.json").write_text(json.dumps(response, indent=2, default=str))
    if dropped:
        (out / "build-stage-dropped-tools.txt").write_text("\n".join(sorted(set(dropped))) + "\n")
    session_dir = workspace / "sessions" / session_id
    plan = session_dir / "workspace" / "plan.md"
    if plan.exists():
        shutil.copy2(plan, out / "plan.md")
    turn_dir = session_dir / "turns" / run_id
    for preview in sorted(turn_dir.glob("iter_*/preview_*.png")):
        target = out / "previews" / preview.parent.name / preview.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(preview, target)
    print(
        json.dumps(
            {
                "status": response.get("status"),
                "summary": (response.get("summary") or "")[:400],
                "minutes": round(elapsed / 60, 1),
                "output": str(out),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
