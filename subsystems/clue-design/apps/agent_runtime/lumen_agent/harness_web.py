"""Website-mode deepagent — assembly and runner.

The website twin of harness.py: an orchestrator agent plus a web-author subagent
and a visual-reviewer subagent, over the LumenWebTools substrate. Same three-role
shape, same per-role model construction (_instrument/_fresh_model, imported from
harness), same materialized skills + read-only filesystem perms + recursion limit
+ honest-finalize guarantee. The artifact is a WebDoc, not a Rust scene, so the
tools and prompts differ but the machinery does not.

Public API:
- ``create_web_deepagent(prompt, config, initial_web_doc, event_sink)``
- ``run_deepagent_web_turn(prompt, config, initial_web_doc, event_sink)``
"""

from __future__ import annotations

import json
from typing import Any, Optional

from langchain.agents.structured_output import ToolStrategy
from py_lumen_obs import configure, get_logger

from .config import AgentRuntimeConfig
from .harness import _filesystem_permissions, _instrument
from .materialize import materialize_agent_workspace
from .models.schemas import VisualCritique
from .prompts_web import (
    build_web_author_prompt,
    build_web_orchestrator_prompt,
    build_web_reviewer_prompt,
)
from .tools.web_substrate import (
    HOME_PAGE_ID,
    LumenWebTools,
    make_web_view_tool,
    web_theme_token_names,
)

logger = get_logger("lumen_agent.harness_web")


def _has_existing_content(web_doc: dict, page_id: str) -> bool:
    """True when the home page already carries authored content (any node
    beyond the empty root)."""
    for page in web_doc.get("pages") or []:
        if isinstance(page, dict) and page.get("id") == page_id:
            return len(page.get("nodes") or {}) > 1
    return False


def _scaffold_web_workspace(tools: LumenWebTools, prompt: str) -> str:
    """Create the run workspace and seed its read-write files. Returns the
    virtual workspace path the file tools operate under."""
    workspace = tools.trace_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "brief.md").write_text(
        f"# Website turn brief — run {tools.run_id}\n\n{prompt}", encoding="utf-8"
    )
    (workspace / "brand_card.json").write_text(
        json.dumps(tools.brand_card, indent=2), encoding="utf-8"
    )
    logger.debug("web_workspace_scaffolded", run_id=tools.run_id, workspace=str(workspace))
    return f"/{tools.run_id}/workspace"


def create_web_deepagent(
    prompt: str,
    config: AgentRuntimeConfig | None,
    initial_web_doc: dict,
    event_sink=None,
) -> tuple[Any, LumenWebTools]:
    """Build the website-mode deepagent + substrate. Mirrors
    create_design_deepagent's shape."""
    try:
        from deepagents import create_deep_agent

        from .fs_backend import AgentWorkspaceBackend
    except ImportError as error:
        raise RuntimeError(
            "DeepAgents runtime dependencies are missing. Install "
            "apps/api/requirements.txt or add deepagents and langchain-openai to "
            "the active environment."
        ) from error

    runtime_config = config or AgentRuntimeConfig.from_env()

    # W-isolation: sync skills + knowledge into the isolated workspace BEFORE any
    # model can touch them (idempotent, content-stamp guarded).
    materialize_agent_workspace(runtime_config)

    tools = LumenWebTools(
        runtime_config, prompt, initial_web_doc=initial_web_doc, event_sink=event_sink
    )
    workspace_str = _scaffold_web_workspace(tools, prompt)

    backend = AgentWorkspaceBackend(root_dir=str(runtime_config.workspace_root))

    from .llm import assert_all_role_models_support_image_input

    # The loop is mandatory-multimodal (reviewer attaches screenshots) — fail
    # loud here if any configured role model is text-only.
    assert_all_role_models_support_image_input(runtime_config)

    # THREE role instances (never deduped) through the shared constructor.
    orchestrator_model = _instrument(
        runtime_config, tools, runtime_config.orchestrator_model, "orchestrator"
    )
    author_model = _instrument(runtime_config, tools, runtime_config.author_model, "author")
    reviewer_model = _instrument(runtime_config, tools, runtime_config.reviewer_model, "reviewer")

    # Two view variants over the same substrate state: identical except the
    # stale/no-preview refusal text. The subagent variant never instructs a
    # role to call render_web_preview — that tool is orchestrator-only, and a
    # refusal naming an uncallable tool sent the author into a blind edit
    # churn on a live run (2026-07-29).
    view = make_web_view_tool(tools, can_render=True)
    subagent_view = make_web_view_tool(tools, can_render=False)

    # The materialized skills tree (SkillsMiddleware source is the PARENT of the
    # skill dirs) — same wiring as the scene harness so create-website /
    # review-website are progressively disclosed to both subagents.
    workspace_skills = ["/.deepagent/skills"]

    theme_token_names = web_theme_token_names(runtime_config.brand_kit)

    subagents = [
        {
            "name": "lumen-web-author",
            "description": (
                "Writes the page in the constrained-HTML wire format and submits "
                "it with author_web_page. Owns markup, copy, and imagery; give it "
                "the section plan and copy angles."
            ),
            "system_prompt": build_web_author_prompt(
                brand_card=tools.brand_card_text,
                theme_token_names=theme_token_names,
                account_card=tools.account_card_text,
            ),
            "model": author_model,
            "tools": [
                subagent_view,
                tools.web_ops,
                tools.author_web_page,
                tools.author_web_subtree,
                tools.patch_web_page,
                tools.asset,
            ],
            "skills": workspace_skills,
        },
        {
            "name": "lumen-web-reviewer",
            "description": (
                "Judges the rendered page against the review-website checklist at "
                "all three widths and returns a structured VisualCritique."
            ),
            "system_prompt": build_web_reviewer_prompt(
                has_account=bool(tools.account_card)
            ),
            "model": reviewer_model,
            "tools": [subagent_view],
            "skills": workspace_skills,
            # Same rationale as the scene reviewer: extract VisualCritique via the
            # TOOL strategy (native structured output emits malformed JSON on some
            # OpenRouter providers); its default handle_errors re-asks on a
            # validation failure instead of killing the run.
            "response_format": ToolStrategy(VisualCritique),
        },
    ]

    orchestrator_tools = [view, tools.render_web_preview, tools.finalize_web_run]

    doc_title = initial_web_doc.get("title") or "Untitled site"
    agent = create_deep_agent(
        model=orchestrator_model,
        backend=backend,
        permissions=_filesystem_permissions(),
        tools=orchestrator_tools,
        system_prompt=build_web_orchestrator_prompt(
            doc_title=doc_title,
            has_existing_content=_has_existing_content(initial_web_doc, HOME_PAGE_ID),
            brand_card=tools.brand_card_text,
            account_card=tools.account_card_text,
        ),
        subagents=subagents,
        name="lumen-web-deepagent",
    )
    return agent, tools


def run_deepagent_web_turn(
    prompt: str,
    config: AgentRuntimeConfig | None = None,
    initial_web_doc: dict | None = None,
    event_sink=None,
) -> dict:
    """Create + invoke + guarantee an honest finalize.

    Returns {status: "applied"|"failed", summary, web_doc (final),
    preview_paths, outcome}. `applied` iff the orchestrator finalized
    accepted/completed_with_warnings; a crash/recursion-limit/no-finalize turn
    is finalized "failed" here — never a fabricated success."""
    agent, tools = create_web_deepagent(
        prompt, config=config, initial_web_doc=initial_web_doc or {}, event_sink=event_sink
    )

    run_log_path = tools.trace_dir / "logs" / "run.jsonl"
    configure(run_log_path=run_log_path, mode=None)
    logger.debug("web_run_log_attached", run_id=tools.run_id, run_log_path=str(run_log_path))

    tools.record(
        "coordinator",
        "web_turn_started",
        input_summary=prompt[:500],
        output_summary=f"workspace=/{tools.run_id}/workspace",
    )

    initial_state = {"messages": [{"role": "user", "content": prompt}]}
    invoke_config = {"recursion_limit": 200, "configurable": {"thread_id": tools.run_id}}

    exception_text: Optional[str] = None
    try:
        agent.invoke(initial_state, config=invoke_config)
    except Exception as error:  # noqa: BLE001 - honest failure, recorded verbatim
        exception_text = f"{type(error).__name__}: {error}"
        tools.record(
            "coordinator",
            "web_turn_exception",
            output_summary=exception_text[:500],
            payload={"exception": exception_text},
        )

    final_path = tools.trace_dir / "final.json"
    if not final_path.exists():
        # The orchestrator never finalized — HONEST failure, never fabricated.
        tools.finalize_web_run(
            "failed", exception_text or "orchestrator ended without finalize"
        )
    final = json.loads(final_path.read_text(encoding="utf-8"))
    outcome = final.get("outcome", "failed")
    summary = final.get("summary", "")

    final_doc_path = tools.trace_dir / "final_web_doc.json"
    web_doc = (
        json.loads(final_doc_path.read_text(encoding="utf-8"))
        if final_doc_path.exists()
        else tools.web_doc
    )

    status = "applied" if outcome in ("accepted", "completed_with_warnings") else "failed"
    return {
        "status": status,
        "summary": summary,
        "web_doc": web_doc,
        "preview_paths": list(tools.preview_paths),
        "outcome": outcome,
    }
