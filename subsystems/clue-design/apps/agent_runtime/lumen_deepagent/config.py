from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentRuntimeConfig:
    repo_root: Path
    model: str
    max_iterations: int
    preview_format: str
    trace_dir: Path
    asset_store_root: Path | None = None
    # Agent LLM service. When both are set the deep-agent's text model is routed
    # through an OpenAI-compatible endpoint (e.g. OpenRouter) instead of Anthropic;
    # `model` must then be an "openai:<openrouter-model-id>" value. Blank → Anthropic.
    agent_base_url: str | None = None
    agent_api_key: str | None = None
    # Brand Kit application (K0): the full kit JSON this run designs against,
    # passed BY VALUE — the runtime never reads the API database. The API's
    # agent-turn path resolves the document's attached kit; the CLI accepts
    # --brand-kit-file. None → the platform default kit, exactly as before.
    # `brand_kit_source` is the provenance label for the effective-brand trace
    # ("document", "file", …).
    brand_kit: dict | None = None
    brand_kit_source: str | None = None

    @classmethod
    def from_env(cls, repo_root: Path | None = None) -> "AgentRuntimeConfig":
        root = repo_root or Path(__file__).resolve().parents[3]
        return cls(
            repo_root=root,
            model=os.environ.get("LUMEN_AGENT_MODEL", "anthropic:claude-opus-4-6"),
            max_iterations=int(os.environ.get("LUMEN_AGENT_MAX_ITERATIONS", "5")),
            preview_format=os.environ.get("LUMEN_AGENT_PREVIEW_FORMAT", "svg"),
            trace_dir=Path(
                os.environ.get(
                    "LUMEN_AGENT_TRACE_DIR",
                    str(root / ".lumen-runs"),
                )
            ),
            asset_store_root=(
                Path(os.environ["LUMEN_AGENT_ASSET_STORE"])
                if os.environ.get("LUMEN_AGENT_ASSET_STORE")
                else None
            ),
            agent_base_url=(os.environ.get("LUMEN_AGENT_BASE_URL", "").strip() or None),
            agent_api_key=(os.environ.get("LUMEN_AGENT_API_KEY", "").strip() or None),
        )

    @property
    def effective_asset_store_root(self) -> Path:
        return self.asset_store_root or self.trace_dir / "asset-store"

    @property
    def skills_dir(self) -> Path:
        return self.repo_root / "apps" / "agent_runtime" / "skills"
