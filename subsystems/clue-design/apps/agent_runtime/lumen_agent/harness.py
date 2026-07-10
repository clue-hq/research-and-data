"""Deepagent v0 harness - assembly and runner.

The v0 TRUE deepagent for one Lumen design turn: an orchestrator agent plus a
DSL-author subagent and a visual-reviewer subagent, over the LumenDesignTools
substrate. Modular layout (reorg 2026-07-09): models/ (state + schemas),
tools/ (substrate, view, render), workspace.py (scaffolding), prompts.py,
llm.py. This package imports NOTHING from the archived pipeline.

Public API:
- ``create_design_deepagent(prompt, config, initial_scene, event_sink)``
- ``run_deepagent_turn(prompt, config, initial_scene, event_sink)``

See ``docs/deepagent-architecture.md`` for the ratified design.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from langchain.agents.structured_output import ToolStrategy

from .config import AgentRuntimeConfig
from .models.schemas import VisualCritique
from .models.state import CONSTITUTION_FIELDS, LumenTurnState
from .prompts import (
    build_author_prompt,
    build_orchestrator_prompt,
    build_reviewer_prompt,
)
from .tools.render import make_render_preview_tool
from .tools.substrate import LumenDesignTools
from .tools.view import make_view_tool
from .workspace import initial_turn_state, scaffold_workspace, workspace_root


# --- assembly (§5) ----------------------------------------------------------


def _filesystem_permissions():
    """READ-ONLY on the materialized skills + knowledge trees; read-write on the
    run workspace.

    W-isolation (D1): the backend is `virtual_mode=True` rooted at the workspace,
    so the file tools operate on VIRTUAL paths. The knowledge/skills copies live
    at `/knowledge_docs/**` and `/.deepagent/**`; denying `write` there is the
    cleanest expression of "read at will, never mutate". (These are derived copies
    anyway — the repo tree is the source of truth and is never written back — so a
    stray write could at worst dirty a copy the next materialize re-syncs.)
    """
    from deepagents import FilesystemPermission

    return [
        FilesystemPermission(
            operations=["write"],
            paths=["/.deepagent/**", "/knowledge_docs/**"],
            mode="deny",
        ),
    ]


def create_design_deepagent(
    prompt: str,
    config: AgentRuntimeConfig | None = None,
    initial_scene: dict | None = None,
    event_sink=None,
    *,
    clarification_already_requested: bool = False,
) -> tuple[Any, LumenDesignTools]:
    """Build the v0 deepagent + substrate. Mirrors
    factory.create_lumen_design_agent's signature so callers can swap.

    `clarification_already_requested` is the STRUCTURAL one-round-per-turn guard:
    when the PREVIOUS turn ended `clarification_requested`, this turn does NOT get
    the `request_clarification` tool — the orchestrator must design from the
    user's answer, recording any residual assumption via record_gap (never a
    second question round). The API sets it from the turn request's
    `previous_turn_outcome`.
    """
    try:
        from deepagents import create_deep_agent

        from .fs_backend import AgentWorkspaceBackend
        from .materialize import materialize_agent_workspace
    except ImportError as error:
        raise RuntimeError(
            "DeepAgents runtime dependencies are missing. Install apps/api/requirements.txt "
            "or add deepagents and langchain-openai to the active environment."
        ) from error

    runtime_config = config or AgentRuntimeConfig.from_env()

    # W-isolation (D2): sync the repo's skills + knowledge into the isolated
    # workspace BEFORE anything the model can touch. Loud RuntimeError on failure —
    # never a silent half-workspace. Idempotent (content-stamp guarded).
    materialize_agent_workspace(runtime_config)

    tools = LumenDesignTools(
        runtime_config, prompt, initial_scene=initial_scene, event_sink=event_sink
    )

    scaffold_workspace(tools, prompt)
    # W-isolation (D4): every path the model sees is workspace-virtual. The run
    # workspace is `<workspace_root>/run_<id>/workspace` on the host, which the
    # `virtual_mode` backend serves at `/run_<id>/workspace`.
    workspace_str = f"/{tools.run_id}/workspace"

    # W-isolation (D1): virtual-mode backend rooted at the isolated workspace. The
    # agent's `/` IS the workspace; absolute paths re-anchor under the root (no
    # escape), and the subclass forgives stale host-absolute/legacy path forms.
    backend = AgentWorkspaceBackend(root_dir=str(runtime_config.workspace_root))

    from .llm import assert_all_role_models_support_image_input, init_model

    # D10(c): every distinct configured role model must accept image input — the
    # loop is mandatory-multimodal for all three minds. Covering it HERE (not at
    # each callsite) means CLI and API entry paths are both guarded, since both
    # build through this factory. Loud only on a positive text-only finding.
    assert_all_role_models_support_image_input(runtime_config)

    # D10(a)+(c): build EXACTLY three model instances — one per role — bounded by
    # the shared max_tokens.
    #
    # No dedupe: per-role usage attribution is done by appending a role-tagged
    # UsageCaptureHandler to each model's own instance-level `.callbacks` field
    # (see usage_capture.attach_usage_capture). Instance-level callbacks fire on
    # THAT instance only, so a SHARED instance across roles would cross-attribute
    # every call to all three roles. Three separate instances of the same
    # resolved id are therefore mandatory — and they cost nothing (construction
    # is a thin client object; no network until invoke). This also replaces the
    # earlier `.with_config` wrapper approach, which returned a RunnableBinding
    # that deepagents' resolve_model mishandled and crashed construction on
    # (probe-r9 CONSTRUCTION-FAILURE).
    def _fresh_model(model_id: str):
        return init_model(
            model_id,
            base_url=runtime_config.agent_base_url,
            api_key=runtime_config.agent_api_key,
            reasoning=runtime_config.agent_reasoning,
            max_tokens=runtime_config.agent_max_tokens,
        )

    from .usage_capture import attach_usage_capture

    # Capture is best-effort — a wiring or callback failure never blocks assembly
    # or breaks a run (see usage_capture.attach_usage_capture). attach_* mutates
    # the model in place and returns the SAME BaseChatModel object.
    orchestrator_model = attach_usage_capture(
        _fresh_model(runtime_config.orchestrator_model), tools, role="orchestrator"
    )
    author_model = attach_usage_capture(
        _fresh_model(runtime_config.author_model), tools, role="author"
    )
    reviewer_model = attach_usage_capture(
        _fresh_model(runtime_config.reviewer_model), tools, role="reviewer"
    )

    view = make_view_tool(tools)
    render_preview = make_render_preview_tool(tools)

    # W-isolation (D6): the `skills` param is a list of SOURCE dirs the
    # SkillsMiddleware scans via `backend.ls(source)` — and it expects each source
    # to be the PARENT of skill directories (it treats every dir CHILD that holds a
    # SKILL.md as a skill). Verified against deepagents 0.6.12
    # `middleware/skills.py:_list_skills_with_errors` (l.597 `backend.ls(source)`,
    # l.607-620 dir-children-with-SKILL.md): pointing a source AT a single skill
    # dir loads NOTHING (its SKILL.md is a file, not a dir child) — which is what
    # the old per-skill-dir wiring silently did. The materialized tree is flat at
    # `/.deepagent/skills/<name>/`, so the source is that parent; the backend reads
    # the real copies while the model-visible reference stays virtual. All authored
    # skills are progressively disclosed to both subagents (name+description only
    # until invoked); each role's prompt still names the skills primary to it.
    workspace_skills = ["/.deepagent/skills"]

    subagents = [
        {
            "name": "lumen-dsl-author",
            "description": (
                "Writes and edits the Lumen design through the DSL compiler. "
                "Give it a round directory containing direction.md; it authors, "
                "self-verifies, saves artifacts, and reports."
            ),
            "system_prompt": build_author_prompt(workspace_str),
            "model": author_model,
            "tools": [
                view,
                tools.inspect,
                tools.compile_dsl_block,
                tools.asset,
                tools.validate_binding_set,
                tools.preflight_design,
            ],
            "skills": workspace_skills,
        },
        {
            "name": "lumen-visual-reviewer",
            "description": (
                "Judges the rendered design against the request and the brand "
                "kit's real assets. Returns a structured VisualCritique and "
                "writes it to the round directory."
            ),
            "system_prompt": build_reviewer_prompt(workspace_str),
            "model": reviewer_model,
            "tools": [view, tools.inspect],
            "skills": workspace_skills,
            # D11 (docs/deepagent-architecture.md "Post-R6 decisions"): the
            # reviewer's structured output goes through the TOOL strategy, not
            # the provider/native one. Trigger: P1r7 died twice on
            # `StructuredOutputValidationError ... Native structured output
            # expected valid JSON for VisualCritique` — grok-4.5 via OpenRouter
            # emits malformed JSON under native structured output. ToolStrategy
            # extracts VisualCritique via a synthetic tool call, and its default
            # `handle_errors=True` re-asks the model on a validation failure
            # instead of failing the run. deepagents 0.6.12 passes this object
            # straight through to `create_agent(..., response_format=...)`
            # (middleware/subagents.py: create_sub_agent).
            "response_format": ToolStrategy(VisualCritique),
        },
    ]

    orchestrator_tools = [
        view,
        render_preview,
        tools.inspect,
        tools.preflight_design,
        tools.record_gap,
        tools.finalize_run,
    ]
    # Brief clarification (opening-move only): the orchestrator may ask the user
    # up to 4 questions on a genuinely under-specified brief. Two structural
    # suppressors keep it honest and bounded, both decided BEFORE any LLM call:
    #   1. auto_defaults (LUMEN_AGENT_AUTO_DEFAULTS=1) — headless/eval mode: apply
    #      the skill's defaults + record_gap per assumption, never ask.
    #   2. clarification_already_requested — the previous turn already asked;
    #      one round per turn, so the tool is simply absent this turn.
    # Tool-absence (not a prompt "please don't") is the enforcement: the model
    # cannot ask what it cannot call. The clarify-design-brief skill carries the
    # derive-first protocol and zero-question rules.
    if not runtime_config.auto_defaults and not clarification_already_requested:
        # Insert before finalize_run so the honest exits sit together at the tail.
        orchestrator_tools.insert(len(orchestrator_tools) - 1, tools.request_clarification)

    agent = create_deep_agent(
        model=orchestrator_model,
        backend=backend,
        state_schema=LumenTurnState,
        permissions=_filesystem_permissions(),
        tools=orchestrator_tools,
        system_prompt=build_orchestrator_prompt(workspace_str),
        subagents=subagents,
        name="lumen-design-deepagent",
    )
    return agent, tools


# --- runner (§7) ------------------------------------------------------------


def run_deepagent_turn(
    prompt: str,
    config: AgentRuntimeConfig | None = None,
    initial_scene: dict | None = None,
    event_sink=None,
    *,
    clarification_already_requested: bool = False,
) -> tuple[dict, LumenDesignTools]:
    """Create + invoke + guarantee an honest finalize payload.

    Returns (finalize_payload_dict, tools). If the orchestrator finalized (or
    requested clarification), trust its `final.json`. If it never finalized
    (crash, recursion limit, model error), finalize "failed" honestly here —
    never fabricate success.

    `clarification_already_requested` rides through to the harness's structural
    one-round-per-turn guard (see create_design_deepagent).
    """
    agent, tools = create_design_deepagent(
        prompt,
        config=config,
        initial_scene=initial_scene,
        event_sink=event_sink,
        clarification_already_requested=clarification_already_requested,
    )

    tools.record(
        "coordinator",
        "deepagent_turn_started",
        input_summary=prompt[:500],
        output_summary=f"workspace={workspace_root(tools)}",
    )

    initial_state = {"messages": [{"role": "user", "content": prompt}], **initial_turn_state(tools, prompt)}
    invoke_config = {
        "recursion_limit": 200,
        "configurable": {"thread_id": tools.run_id},
    }

    exception_text: Optional[str] = None
    try:
        agent.invoke(initial_state, config=invoke_config)
    except Exception as error:  # noqa: BLE001 - honest failure, recorded verbatim
        exception_text = f"{type(error).__name__}: {error}"
        tools.record(
            "coordinator",
            "deepagent_turn_exception",
            output_summary=exception_text[:500],
            payload={"exception": exception_text},
        )

    final_path = tools.trace_dir / "final.json"
    if final_path.exists():
        payload = json.loads(final_path.read_text(encoding="utf-8"))
        return payload, tools

    # The orchestrator never finalized — HONEST failure, never a fabricated success.
    detail = exception_text or "agent ended without finalize"
    raw = tools.finalize_run(
        "failed",
        "orchestrator_did_not_finalize",
        detail,
    )
    payload = json.loads(raw)
    return payload, tools
