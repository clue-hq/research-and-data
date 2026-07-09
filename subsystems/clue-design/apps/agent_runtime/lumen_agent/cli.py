"""Minimal CLI for the live v0 deepagent.

Runs one design turn through ``run_deepagent_turn`` — the same path the API
takes — and prints the finalize payload JSON. There is no --mode flag: the
deepagent is the only live mode (D7-AMENDED). The frozen quality-loop CLI lives
in ``lumen_pipeline_archive.cli`` and stays as the offline eval baseline.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from .config import AgentRuntimeConfig
from .harness import run_deepagent_turn
from .llm import assert_model_supports_image_input


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Lumen v0 deepagent for one turn.")
    parser.add_argument("prompt", help="User design request")
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
    # The deepagent is mandatory-multimodal (all minds view pixels via `view`):
    # fail loudly here if the configured model is text-only, before the run
    # burns a paid authoring call. Unknown model / network error never raises.
    assert_model_supports_image_input(
        config.model,
        base_url=config.agent_base_url,
        api_key=config.agent_api_key,
    )
    payload, _tools = run_deepagent_turn(args.prompt, config)
    print(json.dumps(payload, indent=2))


def load_dotenv_if_available(repo_root: Path) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(repo_root / ".env")


if __name__ == "__main__":
    main()
