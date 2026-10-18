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
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from py_lumen_obs import get_logger
from py_lumen_obs.config import run_log
from pydantic import BaseModel, ConfigDict

from .budget import BudgetExhausted, RunBudget, attach_budget_callback
from .cancellation import (
    CANCELLED_EVENT,
    CANCELLED_STOP_REASON,
    TurnCancelled,
    attach_cancellation_callback,
)
from .checkpoint import RUN_ID_KEY, invoke_turn_graph
from .config import AgentRuntimeConfig
from .frame import build_frame_payload
from .models.schemas import ClarificationRequest, SceneVisualCritique, VisualCritique
from .models.state import CONSTITUTION_FIELDS, LumenTurnState
from .platform_reads import make_platform_read_tools
from .prompts import (
    SCENE_LOGO_SELECTION_GUIDANCE,
    SCENE_LS_DESCRIPTION,
    SCENE_READ_FILE_DESCRIPTION,
    SCENE_SKILLS_SECTION,
    build_author_prompt,
    build_orchestrator_prompt,
    build_reviewer_prompt,
)
from .run_metrics import emit_run_metrics
from .scoped_preferences import PreferenceResolver, ScopedPreferencesMiddleware
from .tools.render import make_render_preview_tool
from .tools.substrate import LumenDesignTools
from .tools.view import make_view_tool
from .workspace import initial_turn_state, scaffold_workspace, workspace_root

if TYPE_CHECKING:  # the collector pulls in the platform gateway/obs libs; keep it lazy
    from .usage_collector import TurnCallbacks

logger = get_logger("lumen_agent.harness")


def _make_candidate_fetch_logo_tool(tools: LumenDesignTools) -> StructuredTool:
    """Replace only legacy selection advice; use the original callable/schema."""
    description = tools.fetch_logo.__doc__
    start = description.index("        In an account-personalized")
    end = description.index("\n\n", start)
    description = description[:start] + SCENE_LOGO_SELECTION_GUIDANCE + description[end:]
    return StructuredTool.from_function(tools.fetch_logo, description=description)


def _make_request_clarification_tool(tools: LumenDesignTools) -> StructuredTool:
    """The clarification tool with a typed parameter schema (harness alignment I6, 2026-10-17).

    The method's own signature is a loose `List[Dict]`, which reaches the model as "a list of any
    objects"; the fields and the 1-6 limit then lived only in prose. Binding `ClarificationRequest`
    as the args schema hands the model every field, its description and the limit before it calls.
    The method still validates (and answers a bad payload with a readable error) as the backstop.
    """
    return StructuredTool.from_function(tools.request_clarification, args_schema=ClarificationRequest)


class _CandidateFinalizeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    stop_reason: str
    summary: str
    ops_valid_through_iteration: int | None = None
    baseline_advisory_json: str = "null"
    accommodation_json: str = "null"


def _make_candidate_finalize_tool(tools: LumenDesignTools) -> StructuredTool:
    def finalize_run(
        status: str,
        stop_reason: str,
        summary: str,
        ops_valid_through_iteration: int | None = None,
        baseline_advisory_json: str = "null",
        accommodation_json: str = "null",
    ) -> str:
        """Finalize with this run's latest registered visual review.

        Missing, stale or rejected evidence still prevents acceptance. Write
        the current review to the active round's critique.json before accepting.
        A targeted edit finishes with status='edit_applied' and no critique; its
        summary states what was asked, what changed, what else moved and
        anything not done. Accepted is for a new ad or a revamp.
        ops_valid_through_iteration limits draft operation replay (None means
        all ok iterations). baseline_advisory_json records pre-existing issues;
        accommodation_json records accommodation moves. Both default to null.
        """
        return tools.finalize_run(
            status=status,
            stop_reason=stop_reason,
            summary=summary,
            ops_valid_through_iteration=ops_valid_through_iteration,
            baseline_advisory_json=baseline_advisory_json,
            accommodation_json=accommodation_json,
        )

    return StructuredTool.from_function(finalize_run, args_schema=_CandidateFinalizeInput)


# --- fast loop v1 §5.7: the skill index the orchestrator selects from --------


def _materialized_skill_index(config: AgentRuntimeConfig) -> list[tuple[str, str]]:
    """`[(name, description)]` for every materialized skill, sorted by name.

    Composed from the workspace's `.deepagent/skills/<name>/SKILL.md`
    frontmatter, so the flag-on orchestrator can match a brief to a FORMAT skill
    without an `ls` — the same push-don't-fetch move §5.1 makes for the author,
    and the reason §5.7's required-decisions list can say "read the skill's
    `## Defaults & required decisions` section" and have that be one read_file.

    THE FORMAT-SKILL INTERFACE (§6.1, so a skill written by its own owner plugs
    in with no code change here):
      * `name:` and `description:` in the SKILL.md frontmatter are what this
        index shows; the description is what the orchestrator matches against,
        so it must name the trigger phrases.
      * `required_decisions:` — an OPTIONAL frontmatter list of
        `{id, question, default}` mappings, the machine-readable twin of the
        prose section. Not consumed here (the orchestrator reads the prose);
        declared so the two can be checked against each other.
      * `## Defaults & required decisions` — the named section the flag-on
        orchestrator prompt reads for the §5.7 gate.
      * `## Self-audit checklist` — the named section the flag-on AUTHOR prompt
        scores its §5.3 `critique.json` against.
      * `pinned_knowledge:` — an OPTIONAL frontmatter list of
        knowledge_docs-relative paths this skill's work needs inlined. Feeds
        `frame.pinned_knowledge_paths` once pre-dispatch skill selection exists;
        until then `LUMEN_AGENT_FAST_LOOP_PINNED_KNOWLEDGE` is that seam.

    Never raises: a malformed or unreadable SKILL.md is skipped, because a
    broken skill file must degrade the index, not fail the turn.
    """
    skills_dir = Path(config.workspace_root) / ".deepagent" / "skills"
    index: list[tuple[str, str]] = []
    try:
        children = sorted(child for child in skills_dir.iterdir() if child.is_dir())
    except OSError:
        return index
    for child in children:
        try:
            text = (child / "SKILL.md").read_text(encoding="utf-8")
        except OSError:
            continue
        index.append((child.name, _skill_description(text) or "(no description)"))
    return index


def _skill_description(text: str) -> Optional[str]:
    """The `description:` value from a SKILL.md's YAML frontmatter, flattened.

    A hand-rolled two-key read rather than a YAML dependency: the frontmatter
    shape is fixed by the skill contract above, descriptions are routinely
    wrapped across continuation lines, and pulling PyYAML into the runtime for
    one field would be the larger change.
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    lines = text[3:end].splitlines()
    collected: list[str] = []
    capturing = False
    for line in lines:
        stripped = line.strip()
        if capturing:
            # A continuation line is indented and is not the next `key:` pair.
            if line[:1].isspace() and stripped:
                collected.append(stripped)
                continue
            break
        if stripped.startswith("description:"):
            capturing = True
            first = stripped[len("description:") :].strip()
            if first:
                collected.append(first)
    return " ".join(collected) or None


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
        chat_completions=runtime_config.agent_chat_completions,
    )


def _instrument(
    runtime_config: AgentRuntimeConfig,
    tools,
    model_id: str,
    role: str,
    budget: Any = None,
    *,
    cancel_probe: Any = None,
):
    """A role model, role-labelled at the gateway, with trace capture attached.

    P3.2 (PD-part3 delta 6): per-role USAGE capture moved into the governed
    gateway — the role rides ``provider.build(role=...)`` onto the instance, and
    the gateway's ``model_call_usage`` record (role-tagged, with cost and the
    cached-prefill share) is the ONE usage authority. The design-local usage
    capture handler is RETIRED (its module is gone) — attaching both would double
    count. Trace capture (non-usage reasoning/tool telemetry) stays design-local.
    Three instances = three roles; never deduped — the gateway's attribution is
    per-instance too. Lane 3 slice 5's ``ModelCallCollector`` is a THIRD thing
    again: it rides the turn's invoke config, not a model instance, and only
    COPIES the gateway's stamps onto a receipt.
    `tools` only needs a `record(...)` method, so both LumenDesignTools and
    LumenWebTools work here.

    Fast-loop v1 §7: when `tools` carries a `metrics` accumulator
    (`run_metrics.RunMetrics`), the trace handler folds this role's calls into
    it. `getattr` rather than an attribute access on purpose — the web tools do
    not carry one yet, and a substrate without it must keep working unchanged.

    Fast-loop v1 §5.6: `budget` is the run's shared `RunBudget` (None off the
    flag, and None for every web-mode caller). It attaches a SECOND handler that
    refuses a model call once the run is out of calls or wall clock. Kept
    separate from the trace handler on purpose: the tracer's whole contract is
    that it never affects the run, and the budget's whole contract is that it
    does.

    A3 (defect R3-D): `cancel_probe` is the run's "has a human asked this to
    stop?" callable, and it attaches a THIRD handler on the same seam and for
    the same reason the budget's is a handler at all — the model call is the
    only place a running graph can be refused. Deliberately independent of
    `budget`: a cancel must work whether or not the fast loop (and so the
    budget) is on, because a human's stop is not a tuning knob. None — every
    CLI / fixture / offline / synchronous-preview caller — leaves the callback
    list byte-identical to before.

    KEYWORD-ONLY, and the caller omits it entirely when there is no probe. That
    is not style: `_instrument` is a monkeypatch seam that shipped suites spy on
    with a five-parameter signature, so a sixth POSITIONAL argument would break
    them — and a suite breaking on a parameter its subject never uses is a false
    alarm about a real seam. A no-probe build therefore calls this with exactly
    the pre-A3 argument list.
    """
    from .trace_callbacks import attach_trace_callback

    model = _fresh_model(runtime_config, model_id, role=f"design_{role}")
    attach_trace_callback(model, role=role, metrics=getattr(tools, "metrics", None))
    if budget is not None:
        attach_budget_callback(model, budget, role)
    if cancel_probe is not None:
        attach_cancellation_callback(model, cancel_probe, role)
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
                "/.materialize.lock",
                "/.deepagent/**",
                "/knowledge_docs/**",
                "/custom_components",
                "/custom_components/**",
            ],
            mode="deny",
        ),
    ]


def _create_scene_solo_graph(
    *, model, backend, tools, system_prompt, skills, checkpointer, context_middleware=(),
):
    """Compose DeepAgents 0.6.12 middleware without a delegation capability.

    Its create_deep_agent(subagents=[]) still creates general-purpose + task.
    Disabling that default is only exposed through the process-global model
    profile registry, which would also change concurrent web/control turns.
    This small scene-only adapter uses the same real middleware and permissions
    with LangChain's factory; no profile/model identifiers are changed. Recheck
    this composition when the pinned DeepAgents version changes. The filesystem
    middleware's `_permissions` argument is the same enforcement seam used by
    the upstream factory; our rules are deny-only, requiring no HITL layer.
    """
    from deepagents import __version__
    from deepagents.graph import BASE_AGENT_PROMPT
    from deepagents.middleware.filesystem import FilesystemMiddleware
    from deepagents.middleware.memory import MemoryMiddleware
    from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
    from deepagents.middleware.skills import SkillsMiddleware
    from deepagents.middleware.summarization import create_summarization_middleware
    from langchain.agents import create_agent
    from langchain.agents.middleware import TodoListMiddleware
    from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware

    from .guidance_reads import SceneGuidanceReadMiddleware

    middleware = [
        TodoListMiddleware(),
        # Harness alignment I7: our wording for the skills section and the ls/read_file
        # descriptions, through the library's own options (scene agent only).
        SkillsMiddleware(backend=backend, sources=skills, system_prompt=SCENE_SKILLS_SECTION),
        FilesystemMiddleware(
            backend=backend,
            _permissions=_filesystem_permissions(),
            custom_tool_descriptions={
                "ls": SCENE_LS_DESCRIPTION,
                "read_file": SCENE_READ_FILE_DESCRIPTION,
            },
        ),
        SceneGuidanceReadMiddleware(backend),
        create_summarization_middleware(model, backend),
        PatchToolCallsMiddleware(),
        AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
        MemoryMiddleware(
            backend=backend, sources=["/.deepagent/AGENTS.md"], add_cache_control=True,
        ),
        *context_middleware,
    ]
    return create_agent(
        model,
        tools=tools,
        system_prompt=system_prompt + "\n\n" + BASE_AGENT_PROMPT,
        middleware=middleware,
        state_schema=LumenTurnState,
        checkpointer=checkpointer,
        name="lumen-design-deepagent",
    ).with_config({
        "recursion_limit": 9_999,
        "metadata": {
            "ls_integration": "deepagents",
            "lc_versions": {"deepagents": __version__},
            "lc_agent_name": "lumen-design-deepagent",
        },
    })


def effective_runtime_config(config: AgentRuntimeConfig) -> AgentRuntimeConfig:
    """The config the SCENE harness actually runs with — the candidate bundle's rebound root.

    Shared hosts may assemble web/legacy and candidate turns concurrently, so a candidate turn's
    derived knowledge and backend roots are kept disjoint for the whole run (not merely while the
    materializer's initialization lock is held) by rooting it at ``<trace_dir>/scene-candidate``.

    It is a FUNCTION, and public, because the rebase decides where the session folder and the
    conversation history live (design session continuity, 2026-09-18), and the turn-end sync at
    the API seam has to look in the same place the harness wrote. Inline, the two would disagree
    the moment the candidate bundle was on, and a candidate session would sync an empty folder.
    Pure, and a non-candidate config comes back UNCHANGED (the same object), so every other path
    is byte-identical to before. NOT idempotent — it appends a segment — so apply it once per
    config: a caller passes the ORIGINAL config on to the harness, which rebases it itself.
    """
    if config.scene_skill_bundle != "candidate":
        return config
    return replace(config, trace_dir=config.trace_dir / "scene-candidate")


def create_design_deepagent(
    prompt: str,
    config: AgentRuntimeConfig | None = None,
    initial_scene: dict | None = None,
    event_sink=None,
    *,
    clarification_already_requested: bool = False,
    checkpointer: Any = None,
    scene_checkpoint=None,
    cancel_requested=None,
    scoped_preferences: PreferenceResolver | None = None,
) -> tuple[Any, LumenDesignTools]:
    """Build the v0 deepagent + substrate. Mirrors
    factory.create_lumen_design_agent's signature so callers can swap.

    `cancel_requested` (A3, defect R3-D) is the run's cancellation probe: a
    zero-argument callable answering "has a human asked this run to stop?". It
    is consulted immediately before every model call, on all three roles, and a
    True answer raises `TurnCancelled` out of the graph. `None` — every CLI /
    fixture / offline path, and the synchronous preview route — keeps the turn
    uncancellable and byte-identical to before. See `cancellation.py` for why
    the model call is the only boundary available, and what "cancelled" is
    therefore allowed to mean.

    `scene_checkpoint` (P0.4) is the checkpoint-commit sink: each verified
    authoring round hands it the operation ledger so the caller can make the
    round durable mid-run. `None` — every CLI/fixture/offline path — keeps the
    run save-on-finalize-only. See `LumenDesignTools.checkpoint_scene`.

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
    scene_candidate = runtime_config.scene_skill_bundle == "candidate"
    scene_solo = runtime_config.scene_solo
    if scene_solo and (not scene_candidate or not runtime_config.fast_loop):
        raise ValueError(
            "Scene solo requires the candidate skill bundle and fast_loop=True. "
            "Set LUMEN_AGENT_SCENE_SKILL_BUNDLE=candidate and LUMEN_AGENT_FAST_LOOP=1."
        )
    runtime_config = effective_runtime_config(runtime_config)

    # W-isolation (D2): sync the repo's skills + knowledge into the isolated
    # workspace BEFORE anything the model can touch. Loud RuntimeError on failure —
    # never a silent half-workspace. Idempotent (content-stamp guarded).
    materialize_agent_workspace(
        runtime_config, knowledge_view="scene" if scene_candidate else "legacy"
    )

    tools = LumenDesignTools(
        runtime_config,
        prompt,
        initial_scene=initial_scene,
        event_sink=event_sink,
        scene_checkpoint=scene_checkpoint,
    )

    scaffold_workspace(tools, prompt)
    # W-isolation (D4): every path the model sees is workspace-virtual. The run
    # workspace is `<workspace_root>/run_<id>/workspace` on the host, which the
    # `virtual_mode` backend serves at `/run_<id>/workspace`. On a session turn
    # (design session continuity, 2026-09-18) the scope id is
    # `sessions/<session_id>` instead, so a continued thread's prompt names the
    # persistent session workspace rather than a per-turn folder that no longer
    # exists.
    workspace_str = f"/{tools.workspace_scope_id}/workspace"

    # W-isolation (D1): virtual-mode backend rooted at the isolated workspace. The
    # agent's `/` IS the workspace; absolute paths re-anchor under the root (no
    # escape), and the subclass forgives stale host-absolute/legacy path forms.
    # `reference_turn` (W1.5): on a reference turn the backend normalizes any
    # `critique.json` the author writes so the typed `reference_fidelity` is
    # always stamped — the fast loop has no typed critique writer, only
    # `write_file`, so this backend is the invariant's only choke point.
    backend = AgentWorkspaceBackend(
        root_dir=str(runtime_config.workspace_root),
        active_run_id=tools.workspace_scope_id,
        # The summarization middleware compacts this thread into
        # `/conversation_history/<thread_id>.md`; the thread IS the session, so
        # the scoped backend admits that one file (and its media) or compaction
        # would be refused mid-turn.
        history_thread_id=runtime_config.session_id,
        reference_turn=bool(runtime_config.reference_assets),
        critique_observer=tools.observe_written_critique,
    )
    guidance_middleware = []
    if scene_candidate:
        from .guidance_reads import SceneGuidanceReadMiddleware

        guidance_middleware = [SceneGuidanceReadMiddleware(backend)]

    def preference_middleware(role):
        if scoped_preferences is None:
            return []
        return [ScopedPreferencesMiddleware(
            scoped_preferences,
            lambda payload: tools.record(role, "scoped_preferences_resolved", payload=payload),
        )]

    def model_middleware(role):
        return [*guidance_middleware, *preference_middleware(role)]

    from .llm import assert_all_role_models_support_image_input, assert_model_supports_image_input

    # D10(c): every distinct configured role model must accept image input — the
    # loop is mandatory-multimodal for all three minds. Covering it HERE (not at
    # each callsite) means CLI and API entry paths are both guarded, since both
    # build through this factory. Loud only on a positive text-only finding.
    if scene_solo:
        assert_model_supports_image_input(
            runtime_config.orchestrator_model,
            base_url=runtime_config.agent_base_url,
            api_key=runtime_config.agent_api_key,
        )
    else:
        assert_all_role_models_support_image_input(runtime_config)

    # D10(a)+(c): build EXACTLY three model instances — one per role — bounded by
    # the shared max_tokens.
    #
    # No dedupe: per-role attribution is done at the gateway, which stamps the
    # role the instance was BUILT for onto every answer (`_instrument` passes
    # `role=design_<role>` into init_model), and by the instance-level trace
    # handler, which fires on THAT instance only. A SHARED instance across roles
    # would cross-attribute every call to all three roles. Three separate
    # instances of the same
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
    #
    # Fast loop §5.6: ONE budget shared by all three roles — the ceiling is on
    # the RUN, so the orchestrator cannot buy itself more calls by delegating.
    # None off the flag, which is what keeps every model instance's callback
    # list byte-identical to a pre-fast-loop turn.
    fast_loop = bool(runtime_config.fast_loop)
    budget = None
    if fast_loop:
        budget = RunBudget(
            # D1: the guidance the agent steers by...
            target_llm_calls=runtime_config.fast_loop_target_llm_calls,
            target_wall_clock_s=runtime_config.fast_loop_target_wall_clock_s,
            # ...and the distant circuit breaker that is the only hard stop.
            max_llm_calls=runtime_config.fast_loop_max_llm_calls,
            wall_clock_s=runtime_config.fast_loop_wall_clock_s,
            metrics=tools.metrics,
        )
        tools.metrics.attach_budget(budget)
        tools.fast_loop_budget = budget

    # A3: passed only when there IS one, so a turn with no probe calls `_instrument` with the
    # exact pre-A3 argument list — see that function's docstring for why that matters.
    cancel_kwargs = {} if cancel_requested is None else {"cancel_probe": cancel_requested}

    orchestrator_model = _instrument(
        runtime_config,
        tools,
        runtime_config.orchestrator_model,
        "orchestrator",
        budget,
        **cancel_kwargs,
    )
    if not scene_solo:
        author_model = _instrument(
            runtime_config, tools, runtime_config.author_model, "author", budget, **cancel_kwargs
        )
        # Preserve control-mode construction even when R3 quarantines review.
        reviewer_model = _instrument(
            runtime_config,
            tools,
            runtime_config.reviewer_model,
            "reviewer",
            budget,
            **cancel_kwargs,
        )

    view = make_view_tool(tools)
    # `budget` is None off the flag, so the orchestrator's render summary stays
    # byte-identical to a pre-fast-loop turn. Under the flag it appends the
    # round-boundary headroom line — this render IS the round boundary.
    render_preview = make_render_preview_tool(tools, budget=budget)
    # §5.2: the author's own render. Same substrate, same round-directory
    # custody — but it does NOT checkpoint. See the trigger site in
    # tools/render.py for the full reasoning; the short version is that a
    # checkpoint must keep meaning "a round was accepted", and the author renders
    # mid-round precisely to find what is still wrong.
    author_render_preview = (
        make_render_preview_tool(tools, checkpoint=False) if fast_loop and not scene_solo else None
    )

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

    # §5.1: the composed frame payload rides the author's SYSTEM prompt, which is
    # assembled once per turn and never mutated — inside the cache-stable prefix
    # the L1 invariant above protects, so it is paid for once, not per call.
    frame_payload = build_frame_payload(tools) if fast_loop else None
    fetch_logo = _make_candidate_fetch_logo_tool(tools) if scene_candidate else tools.fetch_logo

    # Design note 2026-09-19: on a LEG turn the platform hands the runtime its reads
    # (`config.platform_reads`, duck-typed — the design side imports nothing from the platform),
    # and the target account's research becomes three tools. Off a leg turn there is no such
    # object and the three tools simply do not exist: the same tool-absence enforcement the
    # reviewer and `request_clarification` use, decided before any model call.
    platform_read_tools = (
        make_platform_read_tools(tools, runtime_config.platform_reads)
        if runtime_config.platform_reads is not None
        else []
    )
    if platform_read_tools:
        tools.record(
            "orchestrator",
            "platform_reads_attached",
            payload={"tools": [read.name for read in platform_read_tools]},
        )

    author_tools = [
        view,
        tools.inspect,
        tools.search_assets,
        tools.compile_dsl_block,
        tools.asset,
        fetch_logo,
        tools.validate_binding_set,
        tools.preflight_design,
    ]
    if author_render_preview is not None:
        author_tools.append(author_render_preview)
    if scene_candidate:
        author_tools.append(tools.validate_creative_direction)
    if not scene_solo:
        # The author writes the copy, so the author reads the account: a headline about this
        # company is written from what research found, not from the director's paraphrase.
        author_tools.extend(platform_read_tools)

    subagents = [] if scene_solo else [
        {
            "name": "lumen-dsl-author",
            "description": (
                "Writes and edits the Lumen design through the DSL compiler. "
                "Give it a round directory containing direction.md; it authors, "
                "self-verifies, saves artifacts, and reports."
            ),
            "system_prompt": build_author_prompt(
                workspace_str,
                has_references=has_references,
                fast_loop=fast_loop,
                frame_payload=frame_payload,
                inner_iterations=runtime_config.fast_loop_inner_iterations,
                scene_skill_bundle=runtime_config.scene_skill_bundle,
            ),
            "model": author_model,
            "tools": author_tools,
            "skills": workspace_skills,
            **({"middleware": model_middleware("author")} if scene_candidate or scoped_preferences else {}),
        },
        {
            "name": "lumen-visual-reviewer",
            "description": (
                "Judges the rendered design against the request and the brand "
                "kit's real assets. Returns a structured VisualCritique and "
                "writes it to the round directory."
            ),
            "system_prompt": build_reviewer_prompt(
                workspace_str, has_references=has_references,
                scene_skill_bundle=runtime_config.scene_skill_bundle,
            ),
            "model": reviewer_model,
            "tools": [view, tools.inspect],
            "skills": workspace_skills,
            **({"middleware": model_middleware("reviewer")} if scene_candidate or scoped_preferences else {}),
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
            "response_format": ToolStrategy(SceneVisualCritique if scene_candidate else VisualCritique),
        },
    ]

    # --- fast loop §5.3 / ruling R3: reviewer QUARANTINED, not deleted -------
    # On a scene turn under the fast loop the `lumen-visual-reviewer` subagent is
    # not registered, so the orchestrator cannot dispatch it — the same
    # tool-absence enforcement `request_clarification` uses, and the same
    # quarantine pattern as M8D-R1: the code path stays whole. Its prompt builder,
    # its model instance, its ToolStrategy(VisualCritique) response format and its
    # entire dict above are still constructed on every turn and are one config
    # flag from being live again; the WEB harness (harness_web) never consults
    # this flag and keeps its reviewer unconditionally (§3 non-goal).
    #
    # Why quarantine at all: the reviewer's measured catches were mechanical
    # (cropped text, contrast, dead nodes) — now covered by preflight plus an
    # author that sees its own render — while taste is beyond both roles and
    # belongs to the human in the chat leg. Each round-trip cost ~25 model calls,
    # two or three times per run, which is most of the gap to the §1 budget.
    #
    # `LUMEN_AGENT_SCENE_REVIEWER=1` is the kill-switch: it puts the reviewer back
    # WITHOUT leaving the fast loop, which is both §7's kill-switch check and the
    # rollback if self-audit scores diverge from human acceptance on a defect class.
    if not scene_solo and not runtime_config.scene_reviewer_enabled:
        quarantined = [sa for sa in subagents if sa["name"] == "lumen-visual-reviewer"]
        subagents = [sa for sa in subagents if sa["name"] != "lumen-visual-reviewer"]
        logger.info(
            "scene_reviewer_quarantined",
            run_id=tools.run_id,
            quarantined=[sa["name"] for sa in quarantined],
            reason="fast_loop_v1_r3",
        )

    orchestrator_tools = [
        view,
        render_preview,
        tools.inspect,
        tools.search_assets,
        tools.preflight_design,
        tools.record_gap,
        _make_candidate_finalize_tool(tools) if scene_candidate else tools.finalize_run,
    ]
    if scene_candidate:
        orchestrator_tools.insert(-1, tools.validate_creative_direction)
    # Brief clarification (opening-move only): the agent may ask the person
    # up to 6 questions on a genuinely under-specified brief. Two structural
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
        orchestrator_tools.insert(len(orchestrator_tools) - 1, _make_request_clarification_tool(tools))

    # Both paths: the reads sit before finalize_run, the way request_clarification does, so the
    # tail of the list stays the honest exits.
    for read_tool in platform_read_tools:
        orchestrator_tools.insert(len(orchestrator_tools) - 1, read_tool)

    if scene_solo:
        from .prompts import build_scene_solo_prompt

        orchestrator_tools.extend([
            tools.compile_dsl_block, tools.asset, tools.search_assets, fetch_logo, tools.validate_binding_set,
            # A follow-up's targeted edit (text, style, size, position, image placement, delete,
            # move) goes straight through the engine's typed edit builder instead of a compile.
            tools.apply_structured_edit,
        ])
        tools.record(
            "orchestrator", "scene_agent_topology",
            payload={"mode": "solo", "active_model_roles": ["orchestrator"], "subagents": []},
        )
        agent = _create_scene_solo_graph(
            model=orchestrator_model,
            backend=backend,
            tools=orchestrator_tools,
            system_prompt=build_scene_solo_prompt(
                workspace_str,
                has_references=has_references,
                has_ad_assets=(workspace_root(tools) / "ad-assets.md").is_file(),
                frame_payload=frame_payload,
                target_llm_calls=runtime_config.fast_loop_target_llm_calls,
                target_wall_clock_s=runtime_config.fast_loop_target_wall_clock_s,
                inner_iterations=runtime_config.fast_loop_inner_iterations,
            ),
            skills=workspace_skills,
            checkpointer=checkpointer,
            # Solo already installs guidance-read middleware above.
            context_middleware=preference_middleware("orchestrator"),
        )
        return agent, tools

    agent = create_deep_agent(
        model=orchestrator_model,
        backend=backend,
        state_schema=LumenTurnState,
        permissions=_filesystem_permissions(),
        tools=orchestrator_tools,
        system_prompt=build_orchestrator_prompt(
            workspace_str,
            has_references=has_references,
            has_ad_assets=(workspace_root(tools) / "ad-assets.md").is_file(),
            fast_loop=fast_loop,
            scene_reviewer=runtime_config.scene_reviewer_enabled,
            # §5.7: composed at assembly time so selecting a format skill costs
            # no `ls` — see _materialized_skill_index for the skill interface.
            skills=(
                _materialized_skill_index(runtime_config) if fast_loop or scene_candidate else None
            ),
            # D1: the prompt is handed the TARGET, never the backstop.
            target_llm_calls=runtime_config.fast_loop_target_llm_calls,
            target_wall_clock_s=runtime_config.fast_loop_target_wall_clock_s,
            inner_iterations=runtime_config.fast_loop_inner_iterations,
            scene_skill_bundle=runtime_config.scene_skill_bundle,
        ),
        subagents=subagents,
        **({"middleware": model_middleware("orchestrator")} if scene_candidate or scoped_preferences else {}),
        name="lumen-design-deepagent",
        checkpointer=checkpointer,
        **(
            {"skills": workspace_skills, "memory": ["/.deepagent/AGENTS.md"]}
            if scene_candidate else {}
        ),
    )
    return agent, tools


# --- runner (§7) ------------------------------------------------------------


def _finalize_interrupted_run(
    tools: LumenDesignTools,
    *,
    gap_summary: str,
    gap_detail: str,
    stop_reason: str,
    headline: str,
) -> dict:
    """THE graceful stop. One body, shared by every reason a turn is halted early.

    Extracted at A3 (defect R3-D) from `_finalize_on_budget_exhausted`, which was
    the only caller when the budget backstop was the only thing that could stop a
    run. Cancellation is now the second, and it must land the *same* guarantees
    rather than a look-alike of them — so the two callers below differ only in
    what they SAY, never in what they do.

    Three things the fast loop §5.6 spec demands of this path, in order:

    1. NEVER DISCARD WORK. The 20m42s baseline died on a quota 403 at finalize
       and threw away a fully valid scene, because the only write was
       save-on-finalize. P0.4 changed that: every accepted round is already a
       document version, so what survives an early stop survives without this
       function doing anything clever. What this function must not do is
       overwrite that with a `failed` verdict when a real draft stands.
    2. NEVER FABRICATE. A run that never authored anything gets `failed`. A run
       whose scene has nodes gets `completed_with_warnings` and says exactly
       what was cut short. Neither is ever `accepted` — nothing accepted this.
    3. RECORD THE GAP. One `record_gap` naming what stopped the run and what
       remained, so the honest incompleteness is in the ledger the editor reads
       and not only in a log line.
    """
    try:
        tools.record_gap(
            # `agent_protocol` is the GapArea for "the loop itself stopped the
            # work" — the enum has no budget or cancellation member and inventing
            # a label would only earn a "[reported area: …]" prefix from
            # `_coerce_gap_area`.
            "agent_protocol",
            gap_summary,
            gap_detail,
        )
    except Exception as error:  # noqa: BLE001 - the gap must not block the finalize
        logger.warning(
            "interrupted_gap_record_failed",
            stop_reason=stop_reason,
            error=f"{type(error).__name__}: {error}",
        )

    has_content = bool((tools.scene or {}).get("nodes"))
    status = "completed_with_warnings" if has_content else "failed"
    summary = headline + (
        "A draft stands and every accepted round was already saved to the "
        "document; what remains is recorded as a gap."
        if has_content
        else "Nothing had been authored yet, so there is no draft to keep."
    )
    raw = tools.finalize_run(status, stop_reason, summary)
    return json.loads(raw)


def _finalize_on_budget_exhausted(tools: LumenDesignTools, breach: BudgetExhausted) -> dict:
    """Fast loop §5.6: the BACKSTOP's honest stop. Wording only — see the shared body above."""
    return _finalize_interrupted_run(
        tools,
        gap_summary=(
            f"run stopped by the {breach.kind} budget before the design was accepted"
        ),
        gap_detail=(
            f"{breach.kind} budget: limit {breach.limit}, observed "
            f"{breach.observed}. Fast loop §5.6 stops the run at the ceiling "
            "rather than grinding past it. Any round already accepted was "
            "checkpointed to the document and stands; the round in flight did "
            "not complete."
        ),
        stop_reason=f"budget_exhausted_{breach.kind}",
        headline=(
            f"Stopped at the {breach.kind} budget ({breach.limit:g} allowed, "
            f"{breach.observed:g} observed) before the design was accepted. "
        ),
    )


def _finalize_on_cancelled(tools: LumenDesignTools, cancelled: TurnCancelled) -> dict:
    """A3 (defect R3-D): a human asked, so the run stopped. Wording only — shared body above.

    The founder-visible truth is `stop_reason = "cancelled_by_request"`, and it is deliberately
    the ONE thing this path says differently from the budget's. A cancelled run is not a failed
    run and is not a runaway run; conflating any two of those in the durable record is exactly
    the dishonesty the whole result envelope exists to prevent.
    """
    requested = f" (requested at {cancelled.requested_at})" if cancelled.requested_at else ""
    return _finalize_interrupted_run(
        tools,
        gap_summary="run cancelled by request before the design was accepted",
        gap_detail=(
            f"A human asked this turn to stop{requested}, and it stopped at the next "
            "model-call boundary rather than running to completion. Any round already "
            "accepted was checkpointed to the document and stands; the round in flight did "
            "not complete. Nothing here says the design was wrong — only that it was not "
            "finished."
        ),
        stop_reason=CANCELLED_STOP_REASON,
        headline=f"Cancelled by request{requested} before the design was accepted. ",
    )



def run_deepagent_turn(
    prompt: str,
    config: AgentRuntimeConfig | None = None,
    initial_scene: dict | None = None,
    event_sink=None,
    *,
    clarification_already_requested: bool = False,
    checkpointer: Any = None,
    thread_id: str | None = None,
    scene_checkpoint=None,
    cancel_requested=None,
    scoped_preferences: PreferenceResolver | None = None,
    runtime_workspace_guard=None,
    callbacks: "TurnCallbacks | None" = None,
) -> tuple[dict, LumenDesignTools]:
    """Create + invoke + guarantee an honest finalize payload.

    Returns (finalize_payload_dict, tools). If the orchestrator finalized (or
    requested clarification), read its `final.json`; accepted results must still
    match the live scene and reviewed preview at return. If it never finalized
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

    `scene_checkpoint` (P0.4) rides through to the substrate's checkpoint-commit
    seam — see `create_design_deepagent`.

    `cancel_requested` (A3, defect R3-D) is the run's cancellation probe. Supplied
    by the fleet path, where it reads the run row's durable cancel request; `None`
    everywhere else. A cancelled turn finalizes through the SAME graceful path the
    budget backstop uses, with `stop_reason = "cancelled_by_request"`.

    `callbacks` (lane 3 slice 5) is what the PLATFORM injects into this turn: opaque LangChain
    handlers (its Langfuse handler) plus the run-id registry that handler fills, and — when the
    caller means to read the receipts back — its own `ModelCallCollector`. They ride the INVOKE
    CONFIG, which is what lets one handler see every model, tool and sub-agent event in the graph
    instead of one model instance's `on_llm_*`. None (the CLI, fixtures, the synchronous preview
    route) still collects: the turn always opens a collector, and publishes what it collected on
    `tools.model_calls`.
    """
    agent, tools = create_design_deepagent(
        prompt,
        config=config,
        initial_scene=initial_scene,
        event_sink=event_sink,
        clarification_already_requested=clarification_already_requested,
        checkpointer=checkpointer,
        scene_checkpoint=scene_checkpoint,
        cancel_requested=cancel_requested,
        **({"scoped_preferences": scoped_preferences} if scoped_preferences is not None else {}),
    )

    # Attach only this run's attributed events through finalization and metrics.
    # The shared console keeps its env/default configuration; overlapping runs
    # retain independent file handlers, which close on every exit path.
    run_log_path = tools.turn_dir / "logs" / "run.jsonl"
    guard = (
        runtime_workspace_guard(tools.run_id, tools.turn_dir)
        if runtime_workspace_guard is not None else nullcontext()
    )
    with guard, run_log(
        tools.run_id, run_log_path, private_payloads=scoped_preferences is not None,
    ):
        logger.debug("run_log_attached", run_id=tools.run_id, run_log_path=str(run_log_path))

        tools.record(
            "coordinator",
            "deepagent_turn_started",
            input_summary=prompt[:500],
            output_summary=f"workspace={workspace_root(tools)}",
        )

        # Design session continuity: the human message carries the RUN ID that produced it, so a
        # thread the same run retries is recognisable (resume) and a thread a NEW run lands on is
        # continued. It survives the checkpoint round trip on `additional_kwargs`; a plain dict
        # message would not.
        initial_state = {
            "messages": [HumanMessage(content=prompt, additional_kwargs={RUN_ID_KEY: tools.run_id})],
            **initial_turn_state(tools, prompt),
        }
        # D5: the durable thread is the DESIGN RUN, not the runtime's private run id. When no
        # thread_id is supplied the runtime id keeps its old double duty (thread + trace-dir name);
        # when one is, the runtime id degrades to trace-dir naming only.
        # Lane 3 slice 5: the turn's per-call receipts, and anything the platform injected,
        # attach HERE rather than on the model instances. Config-level callbacks see every
        # model, tool and sub-agent event in the graph (instance-level ones see only
        # `on_llm_*`), so one collector covers the orchestrator, the author, the reviewer and
        # everything they delegate to — and the platform's Langfuse handler rides along so the
        # whole design run nests under the design-leg observation with settled cost.
        from .usage_collector import turn_collector

        collector, turn_handlers = turn_collector(callbacks)
        invoke_config = {
            "recursion_limit": 200,
            "configurable": {"thread_id": thread_id or tools.run_id},
            "callbacks": turn_handlers,
        }

        exception_text: Optional[str] = None
        budget_breach: Optional[BudgetExhausted] = None
        cancellation: Optional[TurnCancelled] = None
        try:
            # A3: the boundary BEFORE the first model call. A run cancelled while it sat queued (or
            # between a lease takeover and its redrive) must not pay for a single call to discover
            # that; the callback seam can only refuse a call that is already being made, so the graph
            # is never entered at all in that case. `cancel_requested` is None off the fleet path, so
            # this is a no-op for every CLI / fixture / preview caller.
            if cancel_requested is not None and cancel_requested():
                raise TurnCancelled()
            invoke_turn_graph(
                agent,
                initial_state,
                invoke_config=invoke_config,
                checkpointer=checkpointer,
                thread_id=thread_id,
                run_id=tools.run_id,
            )
        except TurnCancelled as error:
            # A3 (defect R3-D). NOT a failure and NOT a runaway — a human asked. Caught above the
            # generic handler for the same reason BudgetExhausted is: the finalize below has to be
            # able to say WHY the run ended, and "orchestrator_did_not_finalize" would be a lie
            # about a run that did exactly what it was told.
            cancellation = error
            exception_text = f"{type(error).__name__}: {error}"
            # `record` is BOTH the file trace and the run's live event stream (see
            # `LumenDesignTools.record`), so this one call is what an SSE consumer sees the
            # moment the cancel is honoured — well before the graceful finalize below lands the
            # terminal `done` frame. `sink_extra` is the only channel that rides the push, which
            # is why the stop reason is stated there and not only in the trace payload.
            tools.record(
                "coordinator",
                CANCELLED_EVENT,
                output_summary=str(error)[:500],
                payload={"stop_reason": CANCELLED_STOP_REASON},
                sink_extra={"stop_reason": CANCELLED_STOP_REASON},
            )
        except BudgetExhausted as error:
            # Fast loop §5.6. NOT a failure — a deliberate, harness-enforced stop.
            # It is caught before the generic handler so the finalize below can be
            # honest about WHY the run ended and about what survives: every accepted
            # round is already committed to the document (P0.4), so the cost of
            # stopping here is the round in flight, not the run.
            budget_breach = error
            exception_text = f"{type(error).__name__}: {error}"
            tools.record(
                "coordinator",
                "deepagent_turn_budget_exhausted",
                output_summary=str(error)[:500],
                payload=error.as_dict(),
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
            final_path = tools.turn_dir / "final.json"
            if final_path.exists():
                # The API receives tools.scene, not the older final_scene.json.
                # A later tool in the same graph batch can change that live draft
                # after finalize returned. Recheck evidence at the handoff boundary
                # without banning subsequent edits or discarding their operations.
                with tools._scene_mutation_lock:
                    payload = json.loads(final_path.read_text(encoding="utf-8"))
                    if payload.get("status") == "accepted":
                        reason = tools._acceptance_error(payload.get("critique") or {})
                        if (
                            reason is None
                            and payload.get("acceptance_receipt") != tools._review_receipt
                        ):
                            reason = (
                                "The finalized acceptance receipt differs from the current review."
                            )
                        if reason is not None:
                            tools.record(
                                "coordinator", "deepagent_turn_acceptance_stale",
                                output_summary=reason,
                                payload={
                                    "reason": reason,
                                    "acceptance_receipt": payload.get("acceptance_receipt"),
                                },
                            )
                            payload = json.loads(
                                tools.finalize_run(
                                    "completed_with_warnings",
                                    "acceptance_stale_at_return",
                                    "Final acceptance is stale; the current draft is "
                                    f"retained for review. {reason}",
                                    critique_json=json.dumps(payload.get("critique") or {}),
                                    baseline_advisory_json=json.dumps(
                                        payload.get("baseline_advisory")
                                    ),
                                    accommodation_json=json.dumps(payload.get("accommodation")),
                                )
                            )
                    elif payload.get("status") == "completed_with_warnings":
                        # A warning is still bound to the draft actually returned.
                        # Later graph-batch edits or replaced preview bytes must
                        # not leave its old review looking current at the API seam.
                        verification = tools.draft_verification()
                        if payload.get("draft_verification") != verification:
                            same_scene = (
                                (payload.get("draft_verification") or {}).get("scene_stamp")
                                == verification["scene_stamp"]
                            )
                            payload = json.loads(tools.finalize_run(
                                "completed_with_warnings",
                                payload.get("stop_reason") or "draft_changed_at_return",
                                payload.get("summary") or "Draft retained for review.",
                                critique_json=json.dumps(payload.get("critique") or {}),
                                ops_valid_through_iteration=(
                                    payload.get("ops_valid_through_iteration") if same_scene else None
                                ),
                                baseline_advisory_json=json.dumps(payload.get("baseline_advisory")),
                                accommodation_json=json.dumps(payload.get("accommodation")),
                            ))
                    return payload, tools

            # A3: before the budget, because a human's stop outranks a machine's — though the two
            # are mutually exclusive in practice (the first raise out of the graph wins) and the
            # `final.json` check above still outranks BOTH: a turn the orchestrator already
            # finalized is finished, and a cancel that arrived after that is simply too late. It is
            # honest to say so rather than to rewrite a real result as a cancellation.
            if cancellation is not None:
                payload = _finalize_on_cancelled(tools, cancellation)
                return payload, tools

            if budget_breach is not None:
                payload = _finalize_on_budget_exhausted(tools, budget_breach)
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
            # Lane 3 slice 5: publish what the turn actually spent on EVERY exit path — a turn
            # that died on a quota 403 is exactly the one whose receipts matter most. The
            # finalize paths above make no model calls, so this list is complete wherever it is
            # read from.
            tools.model_calls = list(collector.calls)
            final = payload or {}
            emit_run_metrics(
                tools,
                outcome=final.get("outcome") or final.get("status") or "failed",
                status=final.get("status") or "failed",
                stop_reason=final.get("stop_reason")
                or (exception_text or "no final payload"),
                rounds_dir=workspace_root(tools) / "rounds",
            )
