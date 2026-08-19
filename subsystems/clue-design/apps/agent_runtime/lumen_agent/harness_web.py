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
from typing import Any, Callable, Optional

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command
from py_lumen_obs import configure, get_logger

from .checkpoint import invoke_turn_graph
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

#: G4 (founder ruling, 2026-08-19): at most this many `lumen-web-reviewer` delegations
#: per web turn. A live chat-driven generation spent ~13 minutes on a simple landing page
#: because the review loop kept going, so the budget is MECHANICAL — the prompt asks for
#: the fewest rounds, this number is what actually stops the seventh.
WEB_REVIEW_DELEGATION_CAP = 6

_REVIEWER_SUBAGENT = "lumen-web-reviewer"

_REVIEW_BUDGET_EXHAUSTED = (
    "Review budget exhausted: this turn has already used all {cap} `lumen-web-reviewer` "
    "delegations, which is the hard per-turn cap. No further review will run. Finish now "
    "from the critique you already hold: send any outstanding blocking fix to the author "
    "and judge the re-render with your own `view` calls, then call `finalize_web_run` — "
    "`accepted` if the page meets the ship bar, `completed_with_warnings` if advisory "
    "issues remain, naming them in the summary."
)


class WebReviewDelegationCap(AgentMiddleware):
    """Enforce the per-turn reviewer budget at the `task` tool.

    One instance is built per :func:`create_web_deepagent` call, so the counter is
    turn-scoped by construction rather than by a framework — the whole mechanism is an
    integer and one branch. Only `lumen-web-reviewer` delegations count: author rounds and
    ordinary tools pass straight through.

    Exceeding the cap is a tool-level REFUSAL, never an exception: an exhausted budget must
    leave the orchestrator able to finalize honestly with its standing critique, and killing
    the turn would throw away a page that is very likely already shippable.

    Sync only, deliberately: the web turn is invoked through `agent.invoke`
    (`checkpoint.invoke_turn_graph`). An async invocation would raise LangChain's own
    "synchronous implementation only" error rather than silently skipping the cap.
    """

    def __init__(
        self,
        *,
        cap: int = WEB_REVIEW_DELEGATION_CAP,
        record: Optional[Callable[..., None]] = None,
    ) -> None:
        super().__init__()
        self._cap = cap
        self._record = record
        self.delegations = 0

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        call = request.tool_call
        args = call.get("args") or {}
        if call.get("name") != "task" or args.get("subagent_type") != _REVIEWER_SUBAGENT:
            return handler(request)
        if self.delegations >= self._cap:
            logger.warning("web_review_cap_reached", cap=self._cap)
            if self._record is not None:
                self._record(
                    "coordinator",
                    "web_review_cap_reached",
                    output_summary=f"reviewer delegation refused after {self._cap} rounds",
                    payload={"cap": self._cap},
                )
            return ToolMessage(
                content=_REVIEW_BUDGET_EXHAUSTED.format(cap=self._cap),
                tool_call_id=call["id"],
                name="task",
            )
        self.delegations += 1
        return handler(request)


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
    *,
    checkpointer: Any = None,
) -> tuple[Any, LumenWebTools]:
    """Build the website-mode deepagent + substrate. Mirrors
    create_design_deepagent's shape, `checkpointer` included (D5 Round B)."""
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

    backend = AgentWorkspaceBackend(
        root_dir=str(runtime_config.workspace_root),
        custom_components_root=tools.custom_component_projection_root,
    )

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
                tools.fetch_page,
                tools.search_assets,
                tools.provenance,
                tools.asset,
                tools.list_custom_components,
                tools.inspect_custom_component,
                tools.write_custom_component_source,
                tools.compile_custom_component,
                tools.place_custom_component,
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
            "tools": [subagent_view, tools.provenance],
            "skills": workspace_skills,
            # Same rationale as the scene reviewer: extract VisualCritique via the
            # TOOL strategy (native structured output emits malformed JSON on some
            # OpenRouter providers); its default handle_errors re-asks on a
            # validation failure instead of killing the run.
            "response_format": ToolStrategy(VisualCritique),
        },
    ]

    orchestrator_tools = [
        view,
        tools.fetch_page,
        tools.search_assets,
        tools.provenance,
        tools.list_custom_components,
        tools.inspect_custom_component,
        tools.render_web_preview,
        tools.finalize_web_run,
    ]

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
            review_cap=WEB_REVIEW_DELEGATION_CAP,
            account_card=tools.account_card_text,
        ),
        subagents=subagents,
        # G4: the review budget rides as ordinary tool-call middleware on the ORCHESTRATOR,
        # which is where `task` executes. Fresh per turn, so its counter cannot leak.
        middleware=[WebReviewDelegationCap(record=tools.record)],
        name="lumen-web-deepagent",
        checkpointer=checkpointer,
    )
    return agent, tools


def run_deepagent_web_turn(
    prompt: str,
    config: AgentRuntimeConfig | None = None,
    initial_web_doc: dict | None = None,
    event_sink=None,
    *,
    checkpointer: Any = None,
    thread_id: str | None = None,
) -> dict:
    """Create + invoke + guarantee an honest finalize.

    Returns {status: "applied"|"failed", summary, web_doc (final), operations,
    grounding, preview_paths, outcome}. `applied` iff the orchestrator finalized
    accepted/completed_with_warnings; a crash/recursion-limit/no-finalize turn
    is finalized "failed" here — never a fabricated success.

    `checkpointer` / `thread_id` (D5 Round B): the durable-execution seam, supplied together by
    the fleet handler. `thread_id` is the DESIGN RUN ID (the D5 ruling); absent it, the turn
    threads on `tools.run_id` exactly as before. See checkpoint.py for the honest resume
    semantics that shipped (resume-as-restart, and why)."""
    agent, tools = create_web_deepagent(
        prompt,
        config=config,
        initial_web_doc=initial_web_doc or {},
        event_sink=event_sink,
        checkpointer=checkpointer,
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
    invoke_config = {
        "recursion_limit": 200,
        "configurable": {"thread_id": thread_id or tools.run_id},
    }

    exception_text: Optional[str] = None
    try:
        invoke_turn_graph(
            agent,
            initial_state,
            invoke_config=invoke_config,
            checkpointer=checkpointer,
            thread_id=thread_id,
        )
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
        "operations": list(tools.operations_ledger),
        "grounding": tools.grounding_report(),
        "preview_paths": list(tools.preview_paths),
        "outcome": outcome,
    }
