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
    # Agent LLM service. OpenRouter is the SOLE gateway for every LLM call — there
    # is no native-provider fallback. `agent_base_url` defaults to the OpenRouter API
    # and `model` must be an "openai:<openrouter-model-id>" value; `agent_api_key`
    # (the OpenRouter key) is required. init_model enforces this and errors if either
    # the creds or the "openai:" prefix is missing.
    agent_base_url: str | None = "https://openrouter.ai/api/v1"
    agent_api_key: str | None = None
    # Brand Kit application (K0): the full kit JSON this run designs against,
    # passed BY VALUE — the runtime never reads the API database. The API's
    # agent-turn path resolves the document's attached kit; the CLI accepts
    # --brand-kit-file. None → the platform default kit, exactly as before.
    # `brand_kit_source` is the provenance label for the effective-brand trace
    # ("document", "file", …).
    brand_kit: dict | None = None
    brand_kit_source: str | None = None
    # K2: the kit-asset MANIFEST — {asset_id: {"record": <engine asset record>,
    # "title"/"description"/"usage": str|None}} for the kit's logo variants and
    # brand images, resolved by the API from its asset library and passed BY
    # VALUE (same rule as brand_kit: the runtime never reads the API database).
    # The records were engine-built at ingestion time; `use_brand_asset`
    # upserts them into the scene verbatim (same id — brand governance matches
    # logo nodes by asset id) with provenance rewritten to brand_guide. None or
    # empty → the kit has no placeable assets (e.g. styles-compiled kits).
    brand_kit_assets: dict | None = None
    # K3: the kit FONT SPEC — {"store_root": str, "digests": [sha256...]} for
    # the kit's font faces, resolved by the API from its asset library and
    # passed BY VALUE. The core helper reads the bytes from the shared store
    # and shapes text in the kit's real faces during preflight measurement
    # and preview export. None → bundled fonts only (Inter fallback).
    brand_fonts: dict | None = None

    @classmethod
    def from_env(cls, repo_root: Path | None = None) -> "AgentRuntimeConfig":
        root = repo_root or Path(__file__).resolve().parents[3]
        return cls(
            repo_root=root,
            model=os.environ.get("LUMEN_AGENT_MODEL", "openai:anthropic/claude-opus-4.8"),
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
            agent_base_url=(
                os.environ.get("LUMEN_AGENT_BASE_URL", "").strip()
                or "https://openrouter.ai/api/v1"
            ),
            agent_api_key=(os.environ.get("LUMEN_AGENT_API_KEY", "").strip() or None),
        )

    @property
    def effective_asset_store_root(self) -> Path:
        return self.asset_store_root or self.trace_dir / "asset-store"

    @property
    def skills_dir(self) -> Path:
        return self.repo_root / "apps" / "agent_runtime" / "skills"
