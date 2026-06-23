from __future__ import annotations

from typing import Any

from .config import AgentRuntimeConfig
from .prompts import COORDINATOR_SYSTEM_PROMPT, build_subagents
from .tools import LumenDesignTools


def create_lumen_design_agent(
    prompt: str,
    config: AgentRuntimeConfig | None = None,
) -> tuple[Any, LumenDesignTools]:
    """Create the Phase A DeepAgent and its deterministic Lumen tool state.

    The import is intentionally lazy so unit tests and deterministic helper
    code do not require model-provider dependencies.
    """

    try:
        from deepagents import create_deep_agent
        from deepagents.backends.filesystem import FilesystemBackend
    except ImportError as error:
        raise RuntimeError(
            "DeepAgents runtime dependencies are missing. Install apps/api/requirements.txt "
            "or add deepagents and langchain-anthropic to the active environment."
        ) from error

    runtime_config = config or AgentRuntimeConfig.from_env()
    tools = LumenDesignTools(runtime_config, prompt)
    backend = FilesystemBackend(root_dir=str(runtime_config.repo_root))

    # Anthropic stays a bare "provider:model" string (deepagents builds it via
    # init_chat_model). For an OpenAI-compatible service (OpenRouter) we must hand
    # deepagents a pre-built model instance so the base_url + api_key are applied.
    if runtime_config.agent_base_url and runtime_config.agent_api_key:
        from .providers import init_model

        model = init_model(
            runtime_config.model,
            base_url=runtime_config.agent_base_url,
            api_key=runtime_config.agent_api_key,
        )
    else:
        model = runtime_config.model

    agent = create_deep_agent(
        model=model,
        backend=backend,
        skills=["apps/agent_runtime/knowledge_docs/skills"],
        tools=[
            tools.load_knowledge,
            tools.compile_dsl_block,
            tools.apply_operations,
            tools.apply_structured_edit,
            tools.generate_qr,
            tools.generate_image,
            tools.place_asset_in_node,
            tools.place_asset_in_slot,
            tools.validate_binding_set,
            tools.derive_instance_preview,
            tools.preflight_design,
            tools.export_preview,
            tools.export_preview_bundle,
            tools.get_latest_preview_for_critique,
            tools.submit_visual_critique,
            tools.recommend_edit_surface,
            tools.create_repair_request,
            tools.record_gap,
            tools.summarize_scene,
            tools.summarize_page,
            tools.summarize_slots,
            tools.summarize_node_tree,
            tools.query_geometry,
            tools.query_slot_bindings,
            tools.persist_trace_event,
            tools.finalize_run,
        ],
        system_prompt=COORDINATOR_SYSTEM_PROMPT,
        subagents=build_subagents(model),
        name="lumen-design-coordinator",
    )
    return agent, tools
