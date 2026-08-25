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

from .budget import BudgetExhausted, RunBudget, attach_budget_callback
from .checkpoint import invoke_turn_graph
from .config import AgentRuntimeConfig
from .frame import build_frame_payload
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
    )


def _instrument(
    runtime_config: AgentRuntimeConfig,
    tools,
    model_id: str,
    role: str,
    budget: Any = None,
):
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

    Fast-loop v1 §5.6: `budget` is the run's shared `RunBudget` (None off the
    flag, and None for every web-mode caller). It attaches a SECOND handler that
    refuses a model call once the run is out of calls or wall clock. Kept
    separate from the trace handler on purpose: the tracer's whole contract is
    that it never affects the run, and the budget's whole contract is that it
    does.
    """
    from .trace_callbacks import attach_trace_callback

    model = _fresh_model(runtime_config, model_id, role=f"design_{role}")
    attach_trace_callback(model, role=role, metrics=getattr(tools, "metrics", None))
    if budget is not None:
        attach_budget_callback(model, budget, role)
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
    scene_checkpoint=None,
) -> tuple[Any, LumenDesignTools]:
    """Build the v0 deepagent + substrate. Mirrors
    factory.create_lumen_design_agent's signature so callers can swap.

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

    # W-isolation (D2): sync the repo's skills + knowledge into the isolated
    # workspace BEFORE anything the model can touch. Loud RuntimeError on failure —
    # never a silent half-workspace. Idempotent (content-stamp guarded).
    materialize_agent_workspace(runtime_config)

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
    # `virtual_mode` backend serves at `/run_<id>/workspace`.
    workspace_str = f"/{tools.run_id}/workspace"

    # W-isolation (D1): virtual-mode backend rooted at the isolated workspace. The
    # agent's `/` IS the workspace; absolute paths re-anchor under the root (no
    # escape), and the subclass forgives stale host-absolute/legacy path forms.
    # `reference_turn` (W1.5): on a reference turn the backend normalizes any
    # `critique.json` the author writes so the typed `reference_fidelity` is
    # always stamped — the fast loop has no typed critique writer, only
    # `write_file`, so this backend is the invariant's only choke point.
    backend = AgentWorkspaceBackend(
        root_dir=str(runtime_config.workspace_root),
        reference_turn=bool(runtime_config.reference_assets),
    )

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

    orchestrator_model = _instrument(
        runtime_config, tools, runtime_config.orchestrator_model, "orchestrator", budget
    )
    author_model = _instrument(
        runtime_config, tools, runtime_config.author_model, "author", budget
    )
    # The reviewer's model is built even when R3 quarantines the subagent below:
    # construction costs nothing (a thin client object, no network), the web
    # harness shares this constructor, and building it keeps the reviewer role
    # REGISTERED with run_metrics — so a quarantined run reports the reviewer at
    # zero calls rather than omitting it, which is the fact worth seeing.
    reviewer_model = _instrument(
        runtime_config, tools, runtime_config.reviewer_model, "reviewer", budget
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
        make_render_preview_tool(tools, checkpoint=False) if fast_loop else None
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

    author_tools = [
        view,
        tools.inspect,
        tools.compile_dsl_block,
        tools.asset,
        tools.validate_binding_set,
        tools.preflight_design,
    ]
    if author_render_preview is not None:
        author_tools.append(author_render_preview)

    subagents = [
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
            ),
            "model": author_model,
            "tools": author_tools,
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
    if not runtime_config.scene_reviewer_enabled:
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
        system_prompt=build_orchestrator_prompt(
            workspace_str,
            has_references=has_references,
            fast_loop=fast_loop,
            scene_reviewer=runtime_config.scene_reviewer_enabled,
            # §5.7: composed at assembly time so selecting a format skill costs
            # no `ls` — see _materialized_skill_index for the skill interface.
            skills=_materialized_skill_index(runtime_config) if fast_loop else None,
            # D1: the prompt is handed the TARGET, never the backstop.
            target_llm_calls=runtime_config.fast_loop_target_llm_calls,
            target_wall_clock_s=runtime_config.fast_loop_target_wall_clock_s,
            inner_iterations=runtime_config.fast_loop_inner_iterations,
        ),
        subagents=subagents,
        name="lumen-design-deepagent",
        checkpointer=checkpointer,
    )
    return agent, tools


# --- runner (§7) ------------------------------------------------------------


def _finalize_on_budget_exhausted(tools: LumenDesignTools, breach: BudgetExhausted) -> dict:
    """Fast loop §5.6: stop cleanly and finalize the best state HONESTLY.

    Three things the spec demands of this path, in order:

    1. NEVER DISCARD WORK. The 20m42s baseline died on a quota 403 at finalize
       and threw away a fully valid scene, because the only write was
       save-on-finalize. P0.4 changed that: every accepted round is already a
       document version, so what survives a budget stop survives without this
       function doing anything clever. What this function must not do is
       overwrite that with a `failed` verdict when a real draft stands.
    2. NEVER FABRICATE. A run that never authored anything gets `failed`. A run
       whose scene has nodes gets `completed_with_warnings` and says exactly
       what was cut short. Neither is ever `accepted` — nothing accepted this.
    3. RECORD THE GAP. One `record_gap` naming the ceiling that was hit and what
       remained, so the honest incompleteness is in the ledger the editor reads
       and not only in a log line.
    """
    try:
        tools.record_gap(
            # `agent_protocol` is the GapArea for "the loop itself stopped the
            # work" — the enum has no budget member and inventing a label would
            # only earn a "[reported area: …]" prefix from `_coerce_gap_area`.
            "agent_protocol",
            f"run stopped by the {breach.kind} budget before the design was accepted",
            (
                f"{breach.kind} budget: limit {breach.limit}, observed "
                f"{breach.observed}. Fast loop §5.6 stops the run at the ceiling "
                "rather than grinding past it. Any round already accepted was "
                "checkpointed to the document and stands; the round in flight did "
                "not complete."
            ),
        )
    except Exception as error:  # noqa: BLE001 - the gap must not block the finalize
        logger.warning(
            "budget_gap_record_failed", error=f"{type(error).__name__}: {error}"
        )

    has_content = bool((tools.scene or {}).get("nodes"))
    status = "completed_with_warnings" if has_content else "failed"
    summary = (
        f"Stopped at the {breach.kind} budget ({breach.limit:g} allowed, "
        f"{breach.observed:g} observed) before the design was accepted. "
        + (
            "A draft stands and every accepted round was already saved to the "
            "document; what remains is recorded as a gap."
            if has_content
            else "Nothing had been authored yet, so there is no draft to keep."
        )
    )
    raw = tools.finalize_run(status, f"budget_exhausted_{breach.kind}", summary)
    return json.loads(raw)



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

    `scene_checkpoint` (P0.4) rides through to the substrate's checkpoint-commit
    seam — see `create_design_deepagent`.
    """
    agent, tools = create_design_deepagent(
        prompt,
        config=config,
        initial_scene=initial_scene,
        event_sink=event_sink,
        clarification_already_requested=clarification_already_requested,
        checkpointer=checkpointer,
        scene_checkpoint=scene_checkpoint,
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
    budget_breach: Optional[BudgetExhausted] = None
    try:
        invoke_turn_graph(
            agent,
            initial_state,
            invoke_config=invoke_config,
            checkpointer=checkpointer,
            thread_id=thread_id,
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
        final_path = tools.trace_dir / "final.json"
        if final_path.exists():
            payload = json.loads(final_path.read_text(encoding="utf-8"))
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
        final = payload or {}
        emit_run_metrics(
            tools,
            outcome=final.get("outcome") or final.get("status") or "failed",
            status=final.get("status") or "failed",
            stop_reason=final.get("stop_reason")
            or (exception_text or "no final payload"),
            rounds_dir=workspace_root(tools) / "rounds",
        )
