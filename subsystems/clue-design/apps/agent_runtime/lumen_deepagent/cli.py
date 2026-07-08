from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from .config import AgentRuntimeConfig
from .factory import create_lumen_design_agent
from .providers import (
    assert_model_supports_image_input,
    create_provider_quality_loop,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Lumen Phase A DeepAgent.")
    parser.add_argument("prompt", help="User design request")
    parser.add_argument(
        "--mode",
        choices=["deepagent", "quality-loop"],
        default="deepagent",
        help=(
            "deepagent runs the DeepAgents coordinator. quality-loop runs the "
            "typed Phase A loop with model-backed author/reviewer adapters."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
        help="Repository root",
    )
    parser.add_argument(
        "--brand-kit-file",
        type=Path,
        default=None,
        help=(
            "Path to a full Brand Kit JSON file; the run designs against it "
            "instead of the platform default kit (K0 kit application)."
        ),
    )
    args = parser.parse_args()

    load_dotenv_if_available(args.repo_root)
    config = AgentRuntimeConfig.from_env(args.repo_root)
    if args.brand_kit_file is not None:
        config = replace(
            config,
            brand_kit=json.loads(args.brand_kit_file.read_text(encoding="utf-8")),
            brand_kit_source="file",
        )
    # Slice 2 D4: before a live run starts, fail loudly if the configured model is
    # text-only — the loop is mandatory-multimodal (Director + reviewer attach images
    # every turn), so a text-only model dies mid-turn at the reviewer after burning
    # the authoring call. Unknown model / network error never raises.
    assert_model_supports_image_input(
        config.model,
        base_url=config.agent_base_url,
        api_key=config.agent_api_key,
    )
    if args.mode == "quality-loop":
        loop, tools = create_provider_quality_loop(args.prompt, config)
        result = loop.run(args.prompt)
    else:
        agent, tools = create_lumen_design_agent(args.prompt, config)
        result = agent.invoke(
            {"messages": [{"role": "user", "content": args.prompt}]},
            config={"configurable": {"thread_id": tools.run_id}},
        )
    print(json.dumps({"run_id": tools.run_id, "result": stringify(result)}, indent=2))


def load_dotenv_if_available(repo_root: Path) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(repo_root / ".env")


def stringify(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


if __name__ == "__main__":
    main()
