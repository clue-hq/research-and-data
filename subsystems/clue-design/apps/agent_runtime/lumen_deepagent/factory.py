from __future__ import annotations

from typing import Any

from .config import AgentRuntimeConfig
from .prompts import COORDINATOR_SYSTEM_PROMPT, build_subagents
from .tools import LumenDesignTools


def create_lumen_design_agent(
    prompt: str,
    config: AgentRuntimeConfig | None = None,
    initial_scene: dict | None = None,
) -> tuple[Any, LumenDesignTools]:
    """Create the Phase A DeepAgent and its deterministic Lumen tool state.

    `initial_scene` seeds the agent's working scene from an existing canonical
    scene (Phase 0a) so targeted edits land on existing NodeIds; None starts
    from a fresh scene.

    The import is intentionally lazy so unit tests and deterministic helper
    code do not require model-provider dependencies.
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
    tools = LumenDesignTools(runtime_config, prompt, initial_scene=initial_scene)
    backend = FilesystemBackend(root_dir=str(runtime_config.repo_root))

    # OpenRouter is the sole LLM gateway: always hand deepagents a pre-built model
    # instance bound to the OpenRouter base_url + api_key. init_model enforces the
    # "openai:<id>" contract and errors loudly if the creds are missing — there is
    # no native-provider fallback. The same instance is shared with every subagent
    # below (build_subagents(model)), so subagents route through OpenRouter too.
    from .providers import init_model

    model = init_model(
        runtime_config.model,
        base_url=runtime_config.agent_base_url,
        api_key=runtime_config.agent_api_key,
    )

    agent = create_deep_agent(
        model=model,
        backend=backend,
        skills=["apps/agent_runtime/knowledge_docs/skills"],
        # 17 agent-facing tools. The asset/inspect dispatchers fold what were 10
        # singletons (generate_*/place_*; summarize_*/query_*) into two multiplexers,
        # and persist_trace_event is dropped (record() auto-traces every tool call).
        # The folded methods remain on LumenDesignTools as internal Python API — the
        # deterministic loop and tests call them directly; they are simply no longer
        # in the model's tool surface. See .context/tool-and-docs-audit/Q1-*.md.
        tools=[
            tools.load_knowledge,
            tools.compile_dsl_block,
            tools.apply_operations,
            tools.apply_structured_edit,
            tools.asset,
            tools.validate_binding_set,
            tools.derive_instance_preview,
            tools.preflight_design,
            tools.export_preview,
            tools.export_preview_bundle,
            tools.get_preview_for_review,
            tools.submit_visual_critique,
            tools.recommend_edit_surface,
            tools.create_repair_request,
            tools.record_gap,
            tools.inspect,
            tools.finalize_run,
        ],
        system_prompt=COORDINATOR_SYSTEM_PROMPT,
        subagents=build_subagents(model),
        name="lumen-design-coordinator",
    )
    return agent, tools
