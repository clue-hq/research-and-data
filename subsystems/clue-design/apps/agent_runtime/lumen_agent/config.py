from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from py_lumen_config import settings


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
    # Slice 2.5: the node ids the human explicitly chipped as this turn's edit
    # targets, passed BY VALUE from the editor payload (same rule as brand_kit:
    # the runtime never reads the API database). Edit-scoped acceptance treats
    # blocking critique on these nodes as always in scope, and refuses the
    # edit-scoped shortcut when the applied ops touched none of them — the
    # measured P1r2/P5r2 failure was the agent editing an unrelated node while
    # the reviewer's blocker on the requested target was "out of scope" by
    # construction. None/empty → no declared targets, behavior unchanged.
    turn_target_node_ids: list[str] | None = None
    # RC (reference-conditioned design): the user-attached reference images for
    # THIS turn, resolved by the API from its asset library and passed BY VALUE
    # (same rule as brand_kit_assets: the runtime never reads the API database).
    # Shape — THE contract both sides build against:
    #   {asset_id: {
    #     "record": <engine asset record, verbatim from the library>,
    #     "preview_digest": str,   # sha256 of a RASTER (png/jpg/webp) in the
    #                              # shared store — SVG references are
    #                              # pre-rasterized by the API at resolve time,
    #                              # so the runtime only ever handles rasters
    #     "mime_type": str,
    #     "width": int | None, "height": int | None,
    #     "dominant_colors": [str, ...],   # <=6 hex, API-computed
    #     "title": str | None, "description": str | None,  # advisory describe
    #                              # text when present — NEVER load-bearing
    #     "order": int,            # 0-based user attachment order
    #   }}
    # References are per-turn context (transient intent), not document state.
    # None/empty -> no references; every RC step is a no-op and the turn is
    # byte-identical to today.
    reference_assets: dict | None = None
    # OpenRouter unified reasoning effort ("low" | "medium" | "high") applied to
    # every deep-agent LLM call via the one gateway constructor (init_model).
    # None → the request carries no reasoning field (provider default, i.e.
    # no extended thinking). One mechanism for all models — never a per-vendor
    # special case.
    agent_reasoning: str | None = None
    # D10(a): OPTIONAL output-token bound threaded into the single init_model
    # gateway for every deep-agent LLM call. None → no max_tokens kwarg (today's
    # behavior, byte-identical). Validated positive at config parse.
    agent_max_tokens: int | None = None
    # L1 (cache locality): OpenRouter provider `sort` preference threaded into
    # init_model for every deep-agent LLM call — `sort` pins one provider replica
    # (disables load-balancing) so the append-only ReAct prefix stays cache-warm.
    # None → no `provider` field on the request (byte-identical to pre-L1).
    agent_provider_sort: str | None = "latency"
    # L3 (straggler watchdog): per-request timeout in SECONDS threaded into
    # init_model for every deep-agent LLM call (installs `timeout` + `max_retries=2`
    # on the ChatOpenAI client). None → no timeout/retry kwargs (today's behavior).
    agent_llm_timeout_s: float | None = 60.0
    # D10(c): OPTIONAL per-role model overrides. Each None → fall back to `model`
    # (LUMEN_AGENT_MODEL). Read via the resolved accessors below so the harness
    # never open-codes the fallback. Same "openai:<id>" contract, enforced by
    # init_model when the harness builds each instance.
    agent_model_orchestrator: str | None = None
    agent_model_author: str | None = None
    agent_model_reviewer: str | None = None
    # P5 (D6): the TARGET ACCOUNT this website turn personalizes for, passed BY
    # VALUE (same rule as brand_kit: the runtime never reads the API database).
    # `account_card` is the compact human-facing card {name, domain,
    # logo_asset_id, data, notes} the orchestrator/author/reviewer prompts and
    # view("account") render; `account_assets` is the parallel logo manifest
    # {asset_id: {"record": <engine asset record>, "title"?: str}} `use_account_asset`
    # upserts into the WebDoc — exactly mirroring brand_kit / brand_kit_assets.
    # None → an un-personalized turn (every account path is a no-op).
    account_card: dict | None = None
    account_assets: dict | None = None
    # Brief-clarification headless/eval mode (LUMEN_AGENT_AUTO_DEFAULTS=1). When
    # true, the harness does NOT register `request_clarification` on the
    # orchestrator: it applies the skill's defaults and ledgers each assumption
    # via record_gap. Probes/sweeps run with this ON so results stay comparable;
    # live editor runs leave it OFF so the agent can ask a vague brief.
    auto_defaults: bool = False

    @classmethod
    def from_env(cls, repo_root: Path | None = None) -> "AgentRuntimeConfig":
        root = repo_root or Path(__file__).resolve().parents[3]
        return cls(
            repo_root=root,
            model=settings.lumen_agent_model,
            max_iterations=settings.lumen_agent_max_iterations,
            preview_format=settings.lumen_agent_preview_format,
            # W-isolation (D3): the run root now lives INSIDE the deepagent's
            # isolated workspace. `trace_dir` IS the workspace root — substrate
            # lands each run at `<workspace>/run_<id>`. Precedence: an explicit
            # `lumen_agent_trace_dir` override wins (back-compat), else the new
            # `lumen_agent_workspace_root` setting, else `<repo>/.deepagent-workspace`.
            trace_dir=(
                settings.lumen_agent_trace_dir
                or settings.lumen_agent_workspace_root
                or (root / ".deepagent-workspace")
            ),
            asset_store_root=settings.lumen_agent_asset_store,
            agent_base_url=settings.lumen_agent_base_url or "https://openrouter.ai/api/v1",
            agent_api_key=settings.lumen_agent_api_key,
            agent_reasoning=settings.lumen_agent_reasoning,
            agent_max_tokens=settings.lumen_agent_max_tokens,
            agent_provider_sort=settings.lumen_agent_provider_sort,
            agent_llm_timeout_s=settings.lumen_agent_llm_timeout_s,
            agent_model_orchestrator=settings.lumen_agent_model_orchestrator,
            agent_model_author=settings.lumen_agent_model_author,
            agent_model_reviewer=settings.lumen_agent_model_reviewer,
            auto_defaults=settings.lumen_agent_auto_defaults,
        )

    @property
    def orchestrator_model(self) -> str:
        """The orchestrator's model id, defaulting to LUMEN_AGENT_MODEL."""
        return self.agent_model_orchestrator or self.model

    @property
    def author_model(self) -> str:
        """The DSL-author subagent's model id, defaulting to LUMEN_AGENT_MODEL."""
        return self.agent_model_author or self.model

    @property
    def reviewer_model(self) -> str:
        """The visual-reviewer subagent's model id, defaulting to LUMEN_AGENT_MODEL."""
        return self.agent_model_reviewer or self.model

    @property
    def workspace_root(self) -> Path:
        """The deepagent's isolated workspace root (W-isolation, D3).

        This IS `trace_dir`: the `virtual_mode` backend roots here, the
        materializer syncs skills/knowledge here, and substrate lands each run at
        `<workspace_root>/run_<id>`.
        """
        return self.trace_dir

    @property
    def effective_asset_store_root(self) -> Path:
        return self.asset_store_root or self.trace_dir / "asset-store"
