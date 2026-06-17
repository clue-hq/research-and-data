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
        )

    @property
    def effective_asset_store_root(self) -> Path:
        return self.asset_store_root or self.trace_dir / "asset-store"

    @property
    def skills_dir(self) -> Path:
        return self.repo_root / "apps" / "agent_runtime" / "skills"
