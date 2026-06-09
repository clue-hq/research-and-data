from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import AgentRuntimeConfig
from .factory import create_lumen_design_agent


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Lumen Phase A DeepAgent.")
    parser.add_argument("prompt", help="User design request")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
        help="Repository root",
    )
    args = parser.parse_args()

    load_dotenv_if_available(args.repo_root)
    config = AgentRuntimeConfig.from_env(args.repo_root)
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
