from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from py_lumen_config import settings


@dataclass(frozen=True)
class AgentRuntimeConfig:
    repo_root: Path
    model: str
    max_iterations: int
    preview_format: str
    trace_dir: Path
    asset_store_root: Path | None = None
    # Design session continuity (2026-09-18): when set, the substrate lands this turn inside the
    # persistent session folder ``<trace_dir>/sessions/<session_id>/turns/<run_id>`` and the
    # agent's workspace ``<trace_dir>/sessions/<session_id>/workspace`` survives across turns.
    # None keeps the per-run folder ``<trace_dir>/<run_id>`` (editor preview, CLI, fixtures).
    session_id: str | None = None
    # Design session continuity (2026-09-18): a leg turn passes the PLATFORM's design run id here
    # so a retried run reuses its own ``turns/<run_id>`` folder and stamps the same
    # ``lumen_run_id`` on its human message — which is what lets `checkpoint.invoke_turn_graph`
    # recognise the retry and resume the thread instead of re-prompting it. None mints a fresh
    # runtime id per construction, exactly as before (editor preview, CLI, fixtures).
    run_id: str | None = None
    # Design note 2026-09-19: the platform's reads for a LEG turn — the target account's
    # research through the governed tools, and the seller's pinned knowledge — injected by
    # value as one object the design side calls from its worker thread. None (editor preview,
    # CLI, fixtures, direct turns) means no such tools and no seller files.
    platform_reads: Any | None = None
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
    # R-A2: what the human WROTE about those targets, passed BY VALUE beside the ids
    # (same rule again — the runtime never reads the API database). One mapping per
    # submitted reference in submission order: {"target": node id, "path": the optional
    # `:nth-child` chain naming an element inside a cloned band, "note": their words}.
    # The order is part of the message — a marketer numbers their own annotations. The
    # prompt block that renders these is the runtime's; the API renders the same facts
    # into the brief's ANNOTATION lines. None/empty → a selection-only scoped turn.
    turn_target_notes: list[dict] | None = None
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
    # Brand Ad Assets W4: the workspace's ad-DNA card PAYLOAD — {"schema_version": 2,
    # "prose": str, "style_groups": [{"name", "creative_ids"}]} — resolved by the API from
    # the ad-assets lane and passed BY VALUE (same rule as brand_kit: the runtime never reads
    # the API database). It is ADVISORY context: a description of the ads this brand already
    # published, rendered into the composed frame payload next to the brand card. It is not a
    # gate, it carries no required structure, and nothing refuses a turn over it (ruling D5).
    # Already bounded at distillation. None → the lane is off, empty, or undistilled, and the
    # turn composes byte-identically to a pre-W4 one.
    ad_dna_card: dict | None = None
    # W5/R2-D: the pre-generated grounds the ad lane holds for the ACTIVE card, as a bounded
    # list of {"asset_id", "style_group", "shape"} — resolved by the API from the same lane
    # read that produced `ad_dna_card` and passed BY VALUE for the same reason.
    #
    # This exists because the lane's third artifact kind was invisible. The ids were placeable
    # and viewable the whole time; they were simply never NAMED anywhere the agent reads, so
    # the W5 Ramp turn generated its own ground while twelve pre-generated ones sat unused.
    # Naming them is the entire fix — the list is advisory, nothing requires their use, and
    # None (no lane, no card, no imagery) composes byte-identically to a pre-W4 turn.
    ad_pregenerated_assets: list | None = None
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
    # Non-OpenAI agent models over chat-completions (see py_lumen_config for the ruling).
    agent_chat_completions: bool = True
    # P3.2: fallback model id for the governed gateway (None → no fallback).
    agent_fallback_model: str | None = None
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
    # P6 grounding: the non-archived workspace asset library, resolved by the
    # API and passed BY VALUE so the runtime can search real records without
    # reading the API database or calling the API back over HTTP. Shape:
    # {asset_id: {"record": <engine AssetRecord>, "title"?: str,
    # "description"?: str, "usage"?: str, "tags"?: [str, ...]}}.
    # The runtime only returns/places records from this manifest; None means the
    # library is unavailable for this turn, never that an asset may be invented.
    asset_library: dict | None = None
    # API-owned lazy byte reader; accepts only an id from the frozen manifest.
    asset_materializer: Any | None = None
    # P6.4: an account-bound durable custom-component capability supplied by
    # the API worker. The runtime receives methods, not database/store paths;
    # source is projected by value into the run's virtual filesystem while all
    # mutations go through CAS/compile-gated typed tools.
    # The absolute base URL the agent's OWN in-loop preview render resolves
    # `<img data-asset=…>` against — `{api origin}/asset-store`, so Playwright
    # (which renders via `set_content`, with no asset server of its own) can
    # actually fetch the pixels. Resolved from `settings.asset_base_url`
    # (LUMEN_API_ORIGIN) in `from_env`.
    #
    # THIS FIELD DID NOT EXIST until 2026-08-20, and its absence was the root
    # cause of "generated web pages never contain imagery": the substrate did
    # `getattr(config, "asset_base_url", None) or "http://127.0.0.1:8000/…"`,
    # which — with no such field — ALWAYS took the hardcoded fallback, and
    # nothing has listened on 8000 since the design API moved to 8010. The agent
    # placed images, saw them broken in its own screenshots, and stripped them.
    # None → the substrate's last-resort fallback (see `_FALLBACK_ASSET_BASE_URL`).
    asset_base_url: str | None = None
    custom_component_registry: Any | None = None
    custom_component_account_id: str | None = None
    custom_component_document_id: str | None = None
    # F1.3: the cloned-section artifacts this turn's document pins, resolved by the API at
    # composition and carried BY VALUE — the same rule `asset_library` follows, and for the same
    # reason: the runtime is fleet work that never reads the API database. Shape is
    # `lumen_api.fragments.render`'s package: {schema_version, fragments{id:{html,css}}, missing[]}.
    # None means nothing was resolved for this turn; every fragment node then renders the
    # engine's placeholder, which is honest rather than empty.
    fragment_render_package: dict | None = None
    # F2.3: the WORKSPACE's released cloned sections, as a capability rather than a value.
    # Discovery and the insert action reach the registry through it —
    # `lumen_api.agent_cloned_sections.DurableAgentClonedSectionRegistry`, supplied by the API
    # worker exactly as `custom_component_registry` is. A capability rather than a manifest
    # because the insert's permission question ("has a human released this section?") must be
    # answered by the document write's OWN gate, not by a copy of its rules taken at composition
    # time. None means this turn cannot see the library at all; the tools say so and refuse,
    # never invent.
    cloned_section_registry: Any | None = None
    # F4.3 (ruling R25-1): the G1+G2 bridge, as a capability for the same reason the two above
    # are — the runtime holds no database handle and must never be given one.
    # `lumen_api.agent_account_logos.DurableAgentAccountLogoBinder`, supplied by the API worker.
    # It is what carries a `fetch_logo` result out of the working DOCUMENT and onto the ACCOUNT
    # (the `design_asset` registry row + `design_account.logo_asset_id`), so the batch derive can
    # personalize every page with the target's real mark. None means this turn cannot bind; the
    # tool says so and refuses, and an empty account logo stays CORRECT.
    account_logo_binder: Any | None = None
    # The durable target-logo family cache (founder decision #4, 2026-08-31):
    # `lumen_api.agent_logo_family_cache.DurableLogoFamilyCache`, supplied by the
    # API worker at turn composition like `account_logo_binder`. None -> fetch_logo
    # simply runs the two rungs every call (correct, just slower/costlier).
    logo_family_cache: Any | None = None
    # The PUBLIC Brandfetch Logo-API client id, for the web lane's hotlink prompt
    # guidance (decorative third-party logos). None/blank -> guidance omitted.
    brandfetch_client_id: str | None = None
    # Brief-clarification headless/eval mode (LUMEN_AGENT_AUTO_DEFAULTS=1). When
    # true, the harness does NOT register `request_clarification` on the
    # orchestrator: it applies the skill's defaults and ledgers each assumption
    # via record_gap. Probes/sweeps run with this ON so results stay comparable;
    # live editor runs leave it OFF so the agent can ask a vague brief.
    auto_defaults: bool = False
    # --- Fast loop v1 (docs/deepagent-fast-loop-v1-spec.md §5) ----------------
    # ONE flag selects the whole §5 loop for SCENE turns. False (the default and
    # every offline/CLI/fixture path that does not opt in) keeps the turn
    # byte-identical to the pre-fast-loop behaviour, which is the contract the
    # flag-off tests pin. Web turns never consult it (§3 non-goal).
    fast_loop: bool = False
    # Scene-only knowledge rollout. Web harnesses always materialize legacy.
    scene_skill_bundle: Literal["legacy", "candidate"] = "legacy"
    # Caller-selected viewing condition for candidate acceptance. Empty disables
    # numeric sizing policy; the model cannot select it through its direction.
    scene_review_profile: str = ""
    # Candidate-only one-agent scene experiment. The scene factory requires the
    # candidate bundle and fast loop; website factories ignore this selector.
    scene_solo: bool = False
    # R3 kill-switch: re-enable the `lumen-visual-reviewer` subagent on scene
    # turns WITHOUT leaving the fast loop. Read through
    # `scene_reviewer_enabled`, never directly — that property is the single
    # place R3 is expressed.
    scene_reviewer: bool = False
    # --- the WEB lane's own fast loop (clone-fidelity F3.3, founder rulings D-F7 / P-6) ------
    # `fast_loop` above is scene-turn-only (§3 non-goal), so these two mirror its shape for web
    # turns. Read `web_reviewer_enabled`, never these directly — that property is the single
    # place the web quarantine rule is expressed, exactly as `scene_reviewer_enabled` is for
    # scenes. Default OFF, and the default is a decision (see py_lumen_config for why).
    web_fast_loop: bool = False
    web_reviewer: bool = False
    # SOLO MODE (founder ruling 2026-09-04): one web deepagent — director, designer, and
    # reviewer in a single loop. Quarantines BOTH web subagents (the D-F7 pattern, widened)
    # and swaps in the merged solo prompt; the two flags above are moot while this is on.
    web_solo: bool = False
    # Context clearing (founder decisions 2026-10-06): see lumen_agent/context_clearing.py.
    web_context_clearing: bool = True
    # R4 budgets, re-shaped by ruling D1 (2026-08-26). Only consulted under
    # `fast_loop`. Two pairs, two jobs:
    #   * `fast_loop_target_*` — GUIDANCE. Communicated to the orchestrator in
    #     plain language (prompt + the round-boundary BUDGET LEFT line). Nothing
    #     stops a run at the target; crossing it is recorded, not enforced.
    #   * `fast_loop_max_llm_calls` / `fast_loop_wall_clock_s` — the BACKSTOP,
    #     ~2x the target. The only hard stop, and only for a hung/runaway run;
    #     it still finalizes checkpointed work gracefully. The agent's prompt
    #     never names it.
    fast_loop_target_llm_calls: int = 45
    fast_loop_target_wall_clock_s: float = 900.0
    fast_loop_max_llm_calls: int = 90
    fast_loop_wall_clock_s: float = 1800.0
    fast_loop_inner_iterations: int = 4
    # §5.1 pin-list override (comma-separated knowledge_docs-relative paths).
    # None → `lumen_agent.frame.DEFAULT_PINNED_KNOWLEDGE`.
    fast_loop_pinned_knowledge: str | None = None
    # §5.4: planning-pass ceiling for the deterministic autofix loop. Only read
    # when `fast_loop` is true; 0 disables autofix on its own.
    autofix_max_passes: int = 2

    @property
    def autofix_passes(self) -> int:
        """How many autofix passes THIS run may take — 0 whenever the flag is
        down, so no caller has to remember to check both."""
        return self.autofix_max_passes if self.fast_loop else 0

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
            asset_base_url=settings.asset_base_url,
            agent_base_url=settings.lumen_agent_base_url or "https://openrouter.ai/api/v1",
            agent_api_key=settings.lumen_agent_api_key,
            agent_reasoning=settings.lumen_agent_reasoning,
            agent_max_tokens=settings.lumen_agent_max_tokens,
            agent_provider_sort=settings.lumen_agent_provider_sort,
            agent_chat_completions=settings.lumen_agent_openrouter_chat_completions,
            agent_fallback_model=settings.lumen_agent_fallback_model,
            agent_llm_timeout_s=settings.lumen_agent_llm_timeout_s,
            agent_model_orchestrator=settings.lumen_agent_model_orchestrator,
            agent_model_author=settings.lumen_agent_model_author,
            agent_model_reviewer=settings.lumen_agent_model_reviewer,
            brandfetch_client_id=(settings.brandfetch_client_id.strip() or None),
            auto_defaults=settings.lumen_agent_auto_defaults,
            fast_loop=settings.lumen_agent_fast_loop,
            scene_skill_bundle=settings.lumen_agent_scene_skill_bundle,
            scene_review_profile=settings.lumen_agent_scene_review_profile.strip(),
            scene_solo=settings.lumen_agent_scene_solo,
            scene_reviewer=settings.lumen_agent_scene_reviewer,
            web_fast_loop=settings.lumen_agent_web_fast_loop,
            web_reviewer=settings.lumen_agent_web_reviewer,
            web_solo=settings.lumen_agent_web_solo,
            web_context_clearing=settings.lumen_agent_web_context_clearing,
            fast_loop_target_llm_calls=settings.lumen_agent_fast_loop_target_llm_calls,
            fast_loop_target_wall_clock_s=settings.lumen_agent_fast_loop_target_wall_clock_s,
            fast_loop_max_llm_calls=settings.lumen_agent_fast_loop_max_llm_calls,
            fast_loop_wall_clock_s=settings.lumen_agent_fast_loop_wall_clock_s,
            fast_loop_inner_iterations=settings.lumen_agent_fast_loop_inner_iterations,
            fast_loop_pinned_knowledge=settings.lumen_agent_fast_loop_pinned_knowledge,
            autofix_max_passes=settings.lumen_agent_autofix_max_passes,
        )

    @property
    def scene_reviewer_enabled(self) -> bool:
        """Whether a SCENE turn dispatches the `lumen-visual-reviewer` subagent.

        Ruling R3 in one expression. Off the fast loop the reviewer is always
        dispatched (nothing changes). On the fast loop it is quarantined — its
        prompt, model, schema and web-turn wiring all stay built and reachable,
        it is simply absent from the scene orchestrator's subagent list, which
        is tool-absence enforcement exactly as `request_clarification` does it.
        `LUMEN_AGENT_SCENE_REVIEWER=1` puts it back.
        Scene solo overrides that switch because no subagent is constructed.
        """
        return not self.scene_solo and ((not self.fast_loop) or self.scene_reviewer)

    @property
    def web_reviewer_enabled(self) -> bool:
        """Whether a WEB turn dispatches the `lumen-web-reviewer` subagent (F3.3, D-F7).

        The scene property's twin, one line for one rule. Off the web fast loop the reviewer is
        always dispatched. On it the reviewer is QUARANTINED — its prompt builder, its model, its
        `ToolStrategy(VisualCritique)` and its whole subagent dict are still constructed on every
        turn; it is simply absent from the orchestrator's subagent list, which is tool-absence
        enforcement rather than a prompt asking nicely.

        What does NOT change with the flag is the rubric: quarantined or not, the review is made
        against the same shared artifact, because D-F7 says the flag changes who checks and never
        what is checked. `LUMEN_AGENT_WEB_REVIEWER=1` puts the reviewer back.
        """
        return (not self.web_fast_loop) or self.web_reviewer

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

    def session_dir(self) -> Path | None:
        """The persistent folder this document's design session owns, or None.

        None means there is no session (editor preview, CLI, fixtures) and the
        substrate keeps today's per-run folder.
        """
        return None if self.session_id is None else self.trace_dir / "sessions" / self.session_id

    @property
    def effective_asset_store_root(self) -> Path:
        return self.asset_store_root or self.trace_dir / "asset-store"
