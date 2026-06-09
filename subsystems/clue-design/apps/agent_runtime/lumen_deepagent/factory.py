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

    agent = create_deep_agent(
        model=runtime_config.model,
        backend=backend,
        skills=["apps/agent_runtime/skills"],
        tools=[
            tools.load_knowledge,
            tools.compile_dsl_block,
            tools.preflight_design,
            tools.export_preview,
            tools.summarize_scene,
            tools.persist_trace_event,
        ],
        system_prompt=COORDINATOR_SYSTEM_PROMPT,
        subagents=build_subagents(runtime_config.model),
        name="lumen-design-coordinator",
    )
    return agent, tools
