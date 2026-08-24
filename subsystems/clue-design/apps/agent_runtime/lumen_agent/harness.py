"""Deepagent v0 harness - assembly and runner.

The v0 TRUE deepagent for one Lumen design turn: an orchestrator agent plus a
DSL-author subagent and a visual-reviewer subagent, over the LumenDesignTools
substrate. Modular layout (reorg 2026-07-09): models/ (state + schemas),
tools/ (substrate, view, render), workspace.py (scaffolding), prompts.py,
llm.py. This package imports NOTHING from the archived pipeline.

Public API:
- ``create_design_deepagent(prompt, config, initial_scene, event_sink)``
- ``run_deepagent_turn(prompt, config, initial_scene, event_sink)``

See ``docs/deepagent-architecture.md`` for the ratified design.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from langchain.agents.structured_output import ToolStrategy
from py_lumen_obs import configure, get_logger

from .checkpoint import invoke_turn_graph
from .config import AgentRuntimeConfig
from .models.schemas import VisualCritique
from .models.state import CONSTITUTION_FIELDS, LumenTurnState
from .prompts import (
    build_author_prompt,
    build_orchestrator_prompt,
    build_reviewer_prompt,
)
from .run_metrics import emit_run_metrics
from .tools.render import make_render_preview_tool
from .tools.substrate import LumenDesignTools
from .tools.view import make_view_tool
from .workspace import initial_turn_state, scaffold_workspace, workspace_root

logger = get_logger("lumen_agent.harness")


# --- assembly (§5) ----------------------------------------------------------


def _fresh_model(runtime_config: AgentRuntimeConfig, model_id: str, role: str | None = None):
    """Build ONE role model instance through the platform's governed gateway.

    Extracted to module scope (was a closure in create_design_deepagent) so the
    website-mode harness (harness_web) builds its three role minds through the
    exact same constructor. The `from .llm import init_model` stays LAZY so the
    per-role-models test's monkeypatch of `lumen_agent.llm.init_model` is
    honored (it patches the module attribute this local import re-reads).
    ``role`` (P3.2) labels the governed instance for per-role attribution.
    """
    from .llm import init_model

    return init_model(
        model_id,
        base_url=runtime_config.agent_base_url,
        api_key=runtime_config.agent_api_key,
        reasoning=runtime_config.agent_reasoning,
        max_tokens=runtime_config.agent_max_tokens,
        provider_sort=runtime_config.agent_provider_sort,
        timeout_s=runtime_config.agent_llm_timeout_s,
        role=role,
        fallback_model=runtime_config.agent_fallback_model,
    )


def _instrument(runtime_config: AgentRuntimeConfig, tools, model_id: str, role: str):
    """A role model, role-labelled at the gateway, with trace capture attached.

    P3.2 (PD-part3 delta 6): per-role USAGE capture moved into the governed
    gateway — the role rides ``provider.build(role=...)`` onto the instance, and
    the gateway's ``model_call_usage`` record (role-tagged, with cost and the
    cached-prefill share) is the ONE usage authority. The design-local
    ``attach_usage_capture`` is deliberately NOT attached anymore — attaching
    both would double count. Trace capture (non-usage reasoning/tool telemetry)
    stays design-local. Three instances = three roles; never deduped — the
    gateway's attribution is per-instance too.
    `tools` only needs a `record(...)` method, so both LumenDesignTools and
    LumenWebTools work here.

    Fast-loop v1 §7: when `tools` carries a `metrics` accumulator
    (`run_metrics.RunMetrics`), the trace handler folds this role's calls into
    it. `getattr` rather than an attribute access on purpose — the web tools do
    not carry one yet, and a substrate without it must keep working unchanged.
    """
    from .trace_callbacks import attach_trace_callback

    model = _fresh_model(runtime_config, model_id, role=f"design_{role}")
    attach_trace_callback(model, role=role, metrics=getattr(tools, "metrics", None))
    return model


def _filesystem_permissions():
    """READ-ONLY on the materialized skills + knowledge trees; read-write on the
    run workspace.

    W-isolation (D1): the backend is `virtual_mode=True` rooted at the workspace,
    so the file tools operate on VIRTUAL paths. The knowledge/skills copies live
    at `/knowledge_docs/**` and `/.deepagent/**`; denying `write` there is the
    cleanest expression of "read at will, never mutate". (These are derived copies
    anyway — the repo tree is the source of truth and is never written back — so a
    stray write could at worst dirty a copy the next materialize re-syncs.)
    """
    from deepagents import FilesystemPermission

    return [
        FilesystemPermission(
            operations=["write"],
            paths=[
                "/.deepagent/**",
                "/knowledge_docs/**",
                "/custom_components",
                "/custom_components/**",
            ],
            mode="deny",
        ),
    ]


def create_design_deepagent(
    prompt: str,
    config: AgentRuntimeConfig | None = None,
    initial_scene: dict | None = None,
    event_sink=None,
    *,
    clarification_already_requested: bool = False,
    checkpointer: Any = None,
) -> tuple[Any, LumenDesignTools]:
    """Build the v0 deepagent + substrate. Mirrors
    factory.create_lumen_design_agent's signature so callers can swap.

    `clarification_already_requested` is the STRUCTURAL one-round-per-turn guard:
    when the PREVIOUS turn ended `clarification_requested`, this turn does NOT get
    the `request_clarification` tool — the orchestrator must design from the
    user's answer, recording any residual assumption via record_gap (never a
    second question round). The API sets it from the turn request's
    `previous_turn_outcome`.

    `checkpointer` (D5 Round B) is an optional LangGraph `BaseCheckpointSaver`.
    When present the graph compiles durably, so a turn's message history and
    graph position survive the process that ran it. It is `None` for the CLI /
    fixtures / offline paths, which keeps their behaviour byte-identical. See
    `checkpoint.py` for what durability does and does NOT buy the design
    harness (short answer: resume-as-restart, honestly).
    """
    try:
        from deepagents import create_deep_agent

        from .fs_backend import AgentWorkspaceBackend
        from .materialize import materialize_agent_workspace
    except ImportError as error:
        raise RuntimeError(
            "DeepAgents runtime dependencies are missing. Install apps/api/requirements.txt "
            "or add deepagents and langchain-openai to the active environment."
        ) from error

    runtime_config = config or AgentRuntimeConfig.from_env()

    # W-isolation (D2): sync the repo's skills + knowledge into the isolated
    # workspace BEFORE anything the model can touch. Loud RuntimeError on failure —
    # never a silent half-workspace. Idempotent (content-stamp guarded).
    materialize_agent_workspace(runtime_config)

    tools = LumenDesignTools(
        runtime_config, prompt, initial_scene=initial_scene, event_sink=event_sink
    )

    scaffold_workspace(tools, prompt)
    # W-isolation (D4): every path the model sees is workspace-virtual. The run
    # workspace is `<workspace_root>/run_<id>/workspace` on the host, which the
    # `virtual_mode` backend serves at `/run_<id>/workspace`.
    workspace_str = f"/{tools.run_id}/workspace"

    # W-isolation (D1): virtual-mode backend rooted at the isolated workspace. The
    # agent's `/` IS the workspace; absolute paths re-anchor under the root (no
    # escape), and the subclass forgives stale host-absolute/legacy path forms.
    backend = AgentWorkspaceBackend(root_dir=str(runtime_config.workspace_root))

    from .llm import assert_all_role_models_support_image_input

    # D10(c): every distinct configured role model must accept image input — the
    # loop is mandatory-multimodal for all three minds. Covering it HERE (not at
    # each callsite) means CLI and API entry paths are both guarded, since both
    # build through this factory. Loud only on a positive text-only finding.
    assert_all_role_models_support_image_input(runtime_config)

    # D10(a)+(c): build EXACTLY three model instances — one per role — bounded by
    # the shared max_tokens.
    #
    # No dedupe: per-role usage attribution is done by appending a role-tagged
    # UsageCaptureHandler to each model's own instance-level `.callbacks` field
    # (see usage_capture.attach_usage_capture). Instance-level callbacks fire on
    # THAT instance only, so a SHARED instance across roles would cross-attribute
    # every call to all three roles. Three separate instances of the same
    # resolved id are therefore mandatory — and they cost nothing (construction
    # is a thin client object; no network until invoke). This also replaces the
    # earlier `.with_config` wrapper approach, which returned a RunnableBinding
    # that deepagents' resolve_model mishandled and crashed construction on
    # (probe-r9 CONSTRUCTION-FAILURE).
    # CACHE-STABILITY INVARIANT (L1 — future work MUST respect this):
    # OpenRouter/xAI prefix caching gives the append-only ReAct history a
    # ~95% cached prefill from the 2nd call on, BUT only because the message
    # prefix stays byte-stable within a turn. The system prompt is assembled
    # ONCE here (static per turn) and every subsequent step only APPENDS to the
    # message list. Any in-place edit or re-ordering of an earlier message
    # (e.g. rewriting resolved compile diagnostics, or interleaving a new image
    # into the author's cached text prefix) invalidates the cache from the edit
    # point onward and forfeits that ~95% saving (probe-proven 2026-07-12).
    # When pruning history (L5) or batching reviewer image views (L2) land,
    # prune by APPENDING a summary — never by mutating history already sent.
    # `provider_sort` pins one replica so this cache is actually reused. The
    # per-role constructor/instrumentation now lives at module scope
    # (_fresh_model/_instrument) so the website-mode harness shares it verbatim.
    orchestrator_model = _instrument(
        runtime_config, tools, runtime_config.orchestrator_model, "orchestrator"
    )
    author_model = _instrument(runtime_config, tools, runtime_config.author_model, "author")
    reviewer_model = _instrument(runtime_config, tools, runtime_config.reviewer_model, "reviewer")

    view = make_view_tool(tools)
    render_preview = make_render_preview_tool(tools)

    # RC (D4/D5): references rode this turn → the orchestrator/author/reviewer
    # prompts gain their reference blocks. No references → every build_* call is a
    # no-op and the three prompts are byte-identical to a pre-RC turn.
    has_references = bool(runtime_config.reference_assets)

    # W-isolation (D6): the `skills` param is a list of SOURCE dirs the
    # SkillsMiddleware scans via `backend.ls(source)` — and it expects each source
    # to be the PARENT of skill directories (it treats every dir CHILD that holds a
    # SKILL.md as a skill). Verified against deepagents 0.6.12
    # `middleware/skills.py:_list_skills_with_errors` (l.597 `backend.ls(source)`,
    # l.607-620 dir-children-with-SKILL.md): pointing a source AT a single skill
    # dir loads NOTHING (its SKILL.md is a file, not a dir child) — which is what
    # the old per-skill-dir wiring silently did. The materialized tree is flat at
    # `/.deepagent/skills/<name>/`, so the source is that parent; the backend reads
    # the real copies while the model-visible reference stays virtual. All authored
    # skills are progressively disclosed to both subagents (name+description only
    # until invoked); each role's prompt still names the skills primary to it.
    workspace_skills = ["/.deepagent/skills"]

    subagents = [
        {
            "name": "lumen-dsl-author",
            "description": (
                "Writes and edits the Lumen design through the DSL compiler. "
                "Give it a round directory containing direction.md; it authors, "
                "self-verifies, saves artifacts, and reports."
            ),
            "system_prompt": build_author_prompt(workspace_str, has_references=has_references),
            "model": author_model,
            "tools": [
                view,
                tools.inspect,
                tools.compile_dsl_block,
                tools.asset,
                tools.validate_binding_set,
                tools.preflight_design,
            ],
            "skills": workspace_skills,
        },
        {
            "name": "lumen-visual-reviewer",
            "description": (
                "Judges the rendered design against the request and the brand "
                "kit's real assets. Returns a structured VisualCritique and "
                "writes it to the round directory."
            ),
            "system_prompt": build_reviewer_prompt(workspace_str, has_references=has_references),
            "model": reviewer_model,
            "tools": [view, tools.inspect],
            "skills": workspace_skills,
            # D11 (docs/deepagent-architecture.md "Post-R6 decisions"): the
            # reviewer's structured output goes through the TOOL strategy, not
            # the provider/native one. Trigger: P1r7 died twice on
            # `StructuredOutputValidationError ... Native structured output
            # expected valid JSON for VisualCritique` — grok-4.5 via OpenRouter
            # emits malformed JSON under native structured output. ToolStrategy
            # extracts VisualCritique via a synthetic tool call, and its default
            # `handle_errors=True` re-asks the model on a validation failure
            # instead of failing the run. deepagents 0.6.12 passes this object
            # straight through to `create_agent(..., response_format=...)`
            # (middleware/subagents.py: create_sub_agent).
            "response_format": ToolStrategy(VisualCritique),
        },
    ]

    orchestrator_tools = [
        view,
        render_preview,
        tools.inspect,
        tools.preflight_design,
        tools.record_gap,
        tools.finalize_run,
    ]
    # Brief clarification (opening-move only): the orchestrator may ask the user
    # up to 4 questions on a genuinely under-specified brief. Two structural
    # suppressors keep it honest and bounded, both decided BEFORE any LLM call:
    #   1. auto_defaults (LUMEN_AGENT_AUTO_DEFAULTS=1) — headless/eval mode: apply
    #      the skill's defaults + record_gap per assumption, never ask.
    #   2. clarification_already_requested — the previous turn already asked;
    #      one round per turn, so the tool is simply absent this turn.
    # Tool-absence (not a prompt "please don't") is the enforcement: the model
    # cannot ask what it cannot call. The clarify-design-brief skill carries the
    # derive-first protocol and zero-question rules.
    if not runtime_config.auto_defaults and not clarification_already_requested:
        # Insert before finalize_run so the honest exits sit together at the tail.
        orchestrator_tools.insert(len(orchestrator_tools) - 1, tools.request_clarification)

    agent = create_deep_agent(
        model=orchestrator_model,
        backend=backend,
        state_schema=LumenTurnState,
        permissions=_filesystem_permissions(),
        tools=orchestrator_tools,
        system_prompt=build_orchestrator_prompt(workspace_str, has_references=has_references),
        subagents=subagents,
        name="lumen-design-deepagent",
        checkpointer=checkpointer,
    )
    return agent, tools


# --- runner (§7) ------------------------------------------------------------


def run_deepagent_turn(
    prompt: str,
    config: AgentRuntimeConfig | None = None,
    initial_scene: dict | None = None,
    event_sink=None,
    *,
    clarification_already_requested: bool = False,
    checkpointer: Any = None,
    thread_id: str | None = None,
) -> tuple[dict, LumenDesignTools]:
    """Create + invoke + guarantee an honest finalize payload.

    Returns (finalize_payload_dict, tools). If the orchestrator finalized (or
    requested clarification), trust its `final.json`. If it never finalized
    (crash, recursion limit, model error), finalize "failed" honestly here —
    never fabricate success.

    `clarification_already_requested` rides through to the harness's structural
    one-round-per-turn guard (see create_design_deepagent).

    `checkpointer` / `thread_id` (D5 Round B) are the durable-execution seam.
    Supplied together by the fleet handler: the graph compiles on the given
    checkpointer and runs on `thread_id` — the DESIGN RUN ID, per the D5 ruling,
    so graph state, run row, event stream and fleet work id all key on one
    identifier. Without them the turn threads on `tools.run_id` exactly as it
    did before, which is what every CLI/fixture/offline caller still wants.
    """
    agent, tools = create_design_deepagent(
        prompt,
        config=config,
        initial_scene=initial_scene,
        event_sink=event_sink,
        clarification_already_requested=clarification_already_requested,
        checkpointer=checkpointer,
    )

    # Per-run trace substrate (deliverables 2+3): attach THIS run's full-detail
    # JSONL file handler. This is the single seam serving BOTH entry paths —
    # the CLI (which already set the console mode) and API-triggered runs — so
    # neither double-configures. `mode=None` keeps console verbosity env/default
    # driven (CLI defaults debug via its setdefault; the server stays info); the
    # run file is always untruncated JSON regardless of mode. The run id (and so
    # its log path) only exists after the substrate built its run dir above, and
    # run_id was already bound onto the ambient context there — every event from
    # here on carries it. Kept forever, workspace-local (ratified decision 3).
    run_log_path = tools.trace_dir / "logs" / "run.jsonl"
    configure(run_log_path=run_log_path, mode=None)
    logger.debug("run_log_attached", run_id=tools.run_id, run_log_path=str(run_log_path))

    tools.record(
        "coordinator",
        "deepagent_turn_started",
        input_summary=prompt[:500],
        output_summary=f"workspace={workspace_root(tools)}",
    )

    initial_state = {"messages": [{"role": "user", "content": prompt}], **initial_turn_state(tools, prompt)}
    # D5: the durable thread is the DESIGN RUN, not the runtime's private run id. When no
    # thread_id is supplied the runtime id keeps its old double duty (thread + trace-dir name);
    # when one is, the runtime id degrades to trace-dir naming only.
    invoke_config = {
        "recursion_limit": 200,
        "configurable": {"thread_id": thread_id or tools.run_id},
    }

    exception_text: Optional[str] = None
    try:
        invoke_turn_graph(
            agent,
            initial_state,
            invoke_config=invoke_config,
            checkpointer=checkpointer,
            thread_id=thread_id,
        )
    except Exception as error:  # noqa: BLE001 - honest failure, recorded verbatim
        exception_text = f"{type(error).__name__}: {error}"
        tools.record(
            "coordinator",
            "deepagent_turn_exception",
            output_summary=exception_text[:500],
            payload={"exception": exception_text},
        )

    # Fast-loop v1 §7: ONE run_metrics summary on EVERY terminal outcome. The
    # `finally` is the whole point — a run that died on a quota 403 mid-finalize
    # (the 20m42s baseline) is precisely the run whose 43-minutes-went-where
    # numbers matter most, and a metrics emission that only fired on the happy
    # path would miss it. `emit_run_metrics` itself never raises.
    payload: Optional[dict] = None
    try:
        final_path = tools.trace_dir / "final.json"
        if final_path.exists():
            payload = json.loads(final_path.read_text(encoding="utf-8"))
            return payload, tools

        # The orchestrator never finalized — HONEST failure, never a fabricated success.
        detail = exception_text or "agent ended without finalize"
        raw = tools.finalize_run(
            "failed",
            "orchestrator_did_not_finalize",
            detail,
        )
        payload = json.loads(raw)
        return payload, tools
    finally:
        final = payload or {}
        emit_run_metrics(
            tools,
            outcome=final.get("outcome") or final.get("status") or "failed",
            status=final.get("status") or "failed",
            stop_reason=final.get("stop_reason")
            or (exception_text or "no final payload"),
            rounds_dir=workspace_root(tools) / "rounds",
        )
