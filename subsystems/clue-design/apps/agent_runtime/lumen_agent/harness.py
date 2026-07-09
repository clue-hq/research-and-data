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
    """READ-ONLY on knowledge_docs/**, read-write everywhere else (workspace).

    The backend roots at repo_root (non-virtual mode), so the file tools operate
    on host-absolute paths normalized to a leading slash — the permission pattern
    matches that absolute form. A single `deny write` on the knowledge subtree is
    the cleanest expression of "read at will, never mutate".
    """
    from deepagents import FilesystemPermission

    return [
        FilesystemPermission(
            operations=["write"],
            paths=["/**/apps/agent_runtime/knowledge_docs/**"],
            mode="deny",
        ),
    ]


def create_design_deepagent(
    prompt: str,
    config: AgentRuntimeConfig | None = None,
    initial_scene: dict | None = None,
    event_sink=None,
) -> tuple[Any, LumenDesignTools]:
    """Build the v0 deepagent + substrate. Mirrors
    factory.create_lumen_design_agent's signature so callers can swap.
    """
    try:
        from deepagents import create_deep_agent
        from deepagents.backends.filesystem import FilesystemBackend
    except ImportError as error:
        raise RuntimeError(
            "DeepAgents runtime dependencies are missing. Install apps/api/requirements.txt "
            "or add deepagents and langchain-openai to the active environment."
        ) from error

    runtime_config = config or AgentRuntimeConfig.from_env()
    tools = LumenDesignTools(
        runtime_config, prompt, initial_scene=initial_scene, event_sink=event_sink
    )

    workspace = scaffold_workspace(tools, prompt)
    workspace_str = str(workspace)

    backend = FilesystemBackend(root_dir=str(runtime_config.repo_root))

    from .llm import assert_all_role_models_support_image_input, init_model

    # D10(c): every distinct configured role model must accept image input — the
    # loop is mandatory-multimodal for all three minds. Covering it HERE (not at
    # each callsite) means CLI and API entry paths are both guarded, since both
    # build through this factory. Loud only on a positive text-only finding.
    assert_all_role_models_support_image_input(runtime_config)

    # D10(a)+(c): build up to three model instances — one per role — bounded by
    # the shared max_tokens. Identical resolved ids share a single instance
    # (dedupe) so the common all-same-model config still builds exactly one.
    _model_cache: dict[str, Any] = {}

    def _model_for(model_id: str):
        cached = _model_cache.get(model_id)
        if cached is None:
            cached = init_model(
                model_id,
                base_url=runtime_config.agent_base_url,
                api_key=runtime_config.agent_api_key,
                reasoning=runtime_config.agent_reasoning,
                max_tokens=runtime_config.agent_max_tokens,
            )
            _model_cache[model_id] = cached
        return cached

    orchestrator_model = _model_for(runtime_config.orchestrator_model)
    author_model = _model_for(runtime_config.author_model)
    reviewer_model = _model_for(runtime_config.reviewer_model)

    view = make_view_tool(tools)
    render_preview = make_render_preview_tool(tools)

    author_skills = [
        "apps/agent_runtime/knowledge_docs/skills/create-design",
        "apps/agent_runtime/knowledge_docs/skills/repair-design",
        "apps/agent_runtime/knowledge_docs/skills/brand-and-tokens",
        "apps/agent_runtime/knowledge_docs/skills/effects",
    ]
    reviewer_skills = ["apps/agent_runtime/knowledge_docs/skills/visual-review"]

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
            "skills": author_skills,
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
            "skills": reviewer_skills,
            "response_format": VisualCritique,
        },
    ]

    agent = create_deep_agent(
        model=orchestrator_model,
        backend=backend,
        state_schema=LumenTurnState,
        permissions=_filesystem_permissions(),
        tools=[
            view,
            render_preview,
            tools.inspect,
            tools.preflight_design,
            tools.record_gap,
            tools.finalize_run,
        ],
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
) -> tuple[dict, LumenDesignTools]:
    """Create + invoke + guarantee an honest finalize payload.

    Returns (finalize_payload_dict, tools). If the orchestrator finalized,
    trust its `final.json`. If it never finalized (crash, recursion limit,
    model error), finalize "failed" honestly here — never fabricate success.
    """
    agent, tools = create_design_deepagent(
        prompt, config=config, initial_scene=initial_scene, event_sink=event_sink
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
