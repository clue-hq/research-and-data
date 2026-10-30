"""Website-mode deepagent — assembly and runner.

The website twin of harness.py: an orchestrator agent plus a web-author subagent
and a visual-reviewer subagent, over the LumenWebTools substrate. Same three-role
shape, same per-role model construction (_instrument/_fresh_model, imported from
harness), same materialized skills + read-only filesystem perms + recursion limit
+ honest-finalize guarantee. The artifact is a WebDoc, not a Rust scene, so the
tools and prompts differ but the machinery does not.

Public API:
- ``create_web_deepagent(prompt, config, initial_web_doc, event_sink)``
- ``run_deepagent_web_turn(prompt, config, initial_web_doc, event_sink)``
"""

from __future__ import annotations

import functools
import json
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Optional

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command
from py_lumen_obs import get_logger
from py_lumen_obs.config import run_log

from .cancellation import CANCELLED_EVENT, CANCELLED_STOP_REASON, TurnCancelled
from .checkpoint import RUN_ID_KEY, invoke_turn_graph
from .config import AgentRuntimeConfig
from .harness import _filesystem_permissions, _instrument
from .materialize import materialize_agent_workspace
from .models.schemas import VisualCritique
from .sandbox_tool import design_run_python
from .platform_reads import (
    PROJECT_CONTEXT_DIR,
    make_platform_read_tools,
    read_thread_attachments,
    with_attachments_note,
    write_project_design_context,
    write_seller_knowledge,
    write_thread_attachments,
)
from .prompts_web import (
    build_web_author_prompt,
    build_web_orchestrator_prompt,
    build_web_reviewer_prompt,
    build_web_solo_prompt,
)
from .tools.web_substrate import (
    LumenWebTools,
    has_existing_content,
    make_web_view_tool,
    web_theme_token_names,
)

if TYPE_CHECKING:  # the collector pulls in the platform gateway/obs libs; keep it lazy
    from .usage_collector import TurnCallbacks

logger = get_logger("lumen_agent.harness_web")

#: G4 (founder ruling, 2026-08-19): at most this many `lumen-web-reviewer` delegations
#: per web turn. A live chat-driven generation spent ~13 minutes on a simple landing page
#: because the review loop kept going, so the budget is MECHANICAL — the prompt asks for
#: the fewest rounds, this number is what actually stops the seventh.
WEB_REVIEW_DELEGATION_CAP = 6

#: G6 lever 1 (founder ruling, 2026-08-19): at most this many `lumen-web-author`
#: delegations per web turn. The G6 benchmark ran the same ordinary brief twice — 3.25 and
#: 10.0 minutes — and the spread was agent-CHOSEN SCOPE, not model speed: 2 author
#: delegations versus 5, with an IDENTICAL 6.2s mean author-call latency. The fast run's
#: shape is the target (one brief, one pass); four leaves room for two genuine repair
#: rounds and still stops the churn.
WEB_AUTHOR_DELEGATION_CAP = 4

_AUTHOR_SUBAGENT = "lumen-web-author"
_REVIEWER_SUBAGENT = "lumen-web-reviewer"

_REVIEW_BUDGET_EXHAUSTED = (
    "Review budget exhausted: this turn has already used all {cap} `lumen-web-reviewer` "
    "delegations, which is the hard per-turn cap. No further review will run. Finish now "
    "from the critique you already hold: send any outstanding blocking fix to the author "
    "and judge the re-render with your own `view` calls, then call `finalize_web_run` — "
    "`accepted` if the page meets the ship bar, `completed_with_warnings` if advisory "
    "issues remain, naming them in the summary."
)

_AUTHOR_BUDGET_EXHAUSTED = (
    "Author budget exhausted: this turn has already used all {cap} `lumen-web-author` "
    "delegations, which is the hard per-turn cap. No further authoring will run, so the "
    "page as it stands is the page that ships. Finish now: call `render_web_preview` if "
    "your last change is not on screen yet, judge the three widths with your own `view` "
    "calls, then call `finalize_web_run` — `accepted` if it meets the ship bar, "
    "`completed_with_warnings` naming every fix you could not make, so the user knows "
    "exactly what to ask for next."
)


@dataclass(frozen=True)
class DelegationBudget:
    """One subagent's per-turn delegation budget: how many, and what the refusal says."""

    subagent: str
    role: str
    cap: int
    refusal: str


#: The shipped per-turn budgets (G4 reviewer, G6 author). Immutable, so it is safe as the
#: middleware's default — only the middleware instance's counters move.
WEB_DELEGATION_BUDGETS: tuple[DelegationBudget, ...] = (
    DelegationBudget(
        subagent=_AUTHOR_SUBAGENT,
        role="author",
        cap=WEB_AUTHOR_DELEGATION_CAP,
        refusal=_AUTHOR_BUDGET_EXHAUSTED,
    ),
    DelegationBudget(
        subagent=_REVIEWER_SUBAGENT,
        role="reviewer",
        cap=WEB_REVIEW_DELEGATION_CAP,
        refusal=_REVIEW_BUDGET_EXHAUSTED,
    ),
)


class WebDelegationCap(AgentMiddleware):
    """Enforce the per-turn subagent delegation budgets at the `task` tool.

    ONE instance is built per :func:`create_web_deepagent` call and holds every budget, so
    the counters are turn-scoped by construction rather than by a framework — the whole
    mechanism is a dict of integers and one branch. Author and reviewer budgets are
    independent; any other subagent and every ordinary tool pass straight through.

    Exceeding a cap is a tool-level REFUSAL, never an exception: an exhausted budget must
    leave the orchestrator able to finalize honestly with what it already holds, and killing
    the turn would throw away a page that is very likely already shippable. Each refusal
    names only tools the ORCHESTRATOR itself can call — naming an uncallable tool is what
    sent a role into blind churn on a live run (2026-07-29).

    Sync only, deliberately: the web turn is invoked through `agent.invoke`
    (`checkpoint.invoke_turn_graph`). An async invocation would raise LangChain's own
    "synchronous implementation only" error rather than silently skipping the caps.
    """

    def __init__(
        self,
        *,
        budgets: tuple[DelegationBudget, ...] = WEB_DELEGATION_BUDGETS,
        record: Optional[Callable[..., None]] = None,
    ) -> None:
        super().__init__()
        self._budgets = {budget.subagent: budget for budget in budgets}
        self._record = record
        self.delegations = {subagent: 0 for subagent in self._budgets}

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        call = request.tool_call
        args = call.get("args") or {}
        if call.get("name") != "task":
            return handler(request)
        budget = self._budgets.get(args.get("subagent_type"))
        if budget is None:
            return handler(request)
        if self.delegations[budget.subagent] >= budget.cap:
            event = f"web_{budget.role}_cap_reached"
            logger.warning(event, cap=budget.cap)
            if self._record is not None:
                self._record(
                    "coordinator",
                    event,
                    output_summary=(
                        f"{budget.role} delegation refused after {budget.cap} rounds"
                    ),
                    payload={"cap": budget.cap, "subagent": budget.subagent},
                )
            return ToolMessage(
                content=budget.refusal.format(cap=budget.cap),
                tool_call_id=call["id"],
                name="task",
            )
        self.delegations[budget.subagent] += 1
        return handler(request)


def serialize_tool_calls(tool_list: list, lock: "threading.RLock") -> list:
    """Wrap every plain-callable tool so its execution holds ``lock``.

    langgraph executes one response's tool calls in parallel threads; the substrate's
    document is a read-modify-write shared state, so two batched writers race (live
    2026-09-04: two `asset` registrations erased an `assemble_cloned_sections` result
    that landed 27ms earlier). Holding one re-entrant lock per call turns a batched
    response into an in-order sequence. `functools.wraps` keeps the name, docstring,
    annotations and `__wrapped__`, which is what the tool-schema conversion reads, so the
    model sees byte-identical tools. Ready-made ``BaseTool`` objects (the `view` tool) are
    passed through untouched — they are reads of an atomically-assigned dict.
    """

    def wrap(tool):
        if not callable(tool) or hasattr(tool, "invoke"):
            return tool

        @functools.wraps(tool)
        def serialized(*args, **kwargs):
            with lock:
                return tool(*args, **kwargs)

        return serialized

    return [wrap(tool) for tool in tool_list]


def _scaffold_web_workspace(tools: LumenWebTools, prompt: str) -> str:
    """Create the run workspace and seed its read-write files. Returns the
    virtual workspace path the file tools operate under."""
    workspace = tools.trace_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "brief.md").write_text(
        f"# Website turn brief — run {tools.run_id}\n\n{prompt}", encoding="utf-8"
    )
    (workspace / "brand_card.json").write_text(
        json.dumps(tools.brand_card, indent=2), encoding="utf-8"
    )
    # Design note 2026-09-19: the seller's pinned knowledge, on the same terms as the scene
    # workspace — ordinary files next to the brand card, written once per pin, read-only to the
    # agent (fs_backend's readonly_subdirs).
    if tools.config.platform_reads is not None:
        write_seller_knowledge(workspace, tools.config.platform_reads, record=tools.record)
    if tools.config.platform_reads is not None or (workspace / PROJECT_CONTEXT_DIR).exists():
        write_project_design_context(workspace, tools.config.platform_reads, record=tools.record)
    # Spec 2026-10-30 §3.3: the chat's files, rebuilt every turn, read-only to the agent.
    tools.attachments_note = write_thread_attachments(
        workspace, read_thread_attachments(tools.config.platform_reads, record=tools.record)
    )
    logger.debug("web_workspace_scaffolded", run_id=tools.run_id, workspace=str(workspace))
    return f"/{tools.workspace_scope_id}/workspace"


def create_web_deepagent(
    prompt: str,
    config: AgentRuntimeConfig | None,
    initial_web_doc: dict,
    event_sink=None,
    *,
    checkpointer: Any = None,
    cancel_requested=None,
) -> tuple[Any, LumenWebTools]:
    """Build the website-mode deepagent + substrate. Mirrors
    create_design_deepagent's shape, `checkpointer` included (D5 Round B).

    `cancel_requested` (A3, defect R3-D) is the run's cancellation probe, wired
    on the same seam and to all three roles for the same reasons the scene
    harness wires it — see `cancellation.py`. What it CANNOT mirror is the scene
    path's "keep the accepted rounds": website mode has no mid-run checkpointing
    (a web turn authors the page and persists once, at the end), so a cancelled
    web turn has no partial work to keep and honestly ends `failed` with nothing
    applied. `None` keeps every existing caller byte-identical."""
    try:
        from deepagents import create_deep_agent

        from .fs_backend import AgentWorkspaceBackend
    except ImportError as error:
        raise RuntimeError(
            "DeepAgents runtime dependencies are missing. Install "
            "apps/api/requirements.txt or add deepagents and langchain-openai to "
            "the active environment."
        ) from error

    runtime_config = config or AgentRuntimeConfig.from_env()

    # W-isolation: sync skills + knowledge into the isolated workspace BEFORE any
    # model can touch them (idempotent, content-stamp guarded).
    materialize_agent_workspace(runtime_config)

    tools = LumenWebTools(
        runtime_config, prompt, initial_web_doc=initial_web_doc, event_sink=event_sink
    )
    workspace_str = _scaffold_web_workspace(tools, prompt)

    backend = AgentWorkspaceBackend(
        root_dir=str(runtime_config.workspace_root),
        custom_components_root=tools.custom_component_projection_root,
        # Website mode keeps its unscoped workspace contract (no `active_run_id`),
        # so this is inert today; it is passed so the thread's history stays the
        # admitted one the moment the web backend is scoped.
        history_thread_id=runtime_config.session_id,
    )

    from .llm import assert_all_role_models_support_image_input

    # The loop is mandatory-multimodal (reviewer attaches screenshots) — fail
    # loud here if any configured role model is text-only.
    assert_all_role_models_support_image_input(runtime_config)

    # THREE role instances (never deduped) through the shared constructor.
    # A3: the probe is passed only when there IS one, so an uncancellable web turn calls
    # `_instrument` with the exact pre-A3 argument list (that seam is monkeypatched by shipped
    # suites — see the scene harness's note).
    cancel_kwargs = {} if cancel_requested is None else {"cancel_probe": cancel_requested}
    orchestrator_model = _instrument(
        runtime_config, tools, runtime_config.orchestrator_model, "orchestrator", **cancel_kwargs
    )
    # SOLO MODE (founder ruling 2026-09-04) builds neither subagent model: there is nobody
    # to hand them to, and an instrumented model that can never be called is a lie in the
    # attribution stream.
    if not runtime_config.web_solo:
        author_model = _instrument(
            runtime_config, tools, runtime_config.author_model, "author", **cancel_kwargs
        )
        reviewer_model = _instrument(
            runtime_config, tools, runtime_config.reviewer_model, "reviewer", **cancel_kwargs
        )

    # Two view variants over the same substrate state: identical except the
    # stale/no-preview refusal text. The subagent variant never instructs a
    # role to call render_web_preview — that tool is orchestrator-only, and a
    # refusal naming an uncallable tool sent the author into a blind edit
    # churn on a live run (2026-07-29).
    view = make_web_view_tool(tools, can_render=True)
    subagent_view = make_web_view_tool(tools, can_render=False)

    # The materialized skills tree (SkillsMiddleware source is the PARENT of the
    # skill dirs) — same wiring as the scene harness so create-website /
    # review-website are progressively disclosed to both subagents.
    workspace_skills = ["/.deepagent/skills"]

    theme_token_names = web_theme_token_names(runtime_config.brand_kit)

    # The platform injects governed reads only on LEG turns. Share those tools with the
    # copy author as well as the director; neither role invents its own research path.
    platform_read_tools = (
        make_platform_read_tools(tools, runtime_config.platform_reads)
        if runtime_config.platform_reads is not None
        else []
    )

    # SOLO MODE: the ternary short-circuits, so neither subagent dict (nor the models they
    # would close over) is ever constructed — the same tool-absence enforcement as D-F7,
    # widened to both roles. The trio path below is byte-identical to before the ruling.
    subagents = (
        []
        if runtime_config.web_solo
        else [
        {
            "name": "lumen-web-author",
            "description": (
                "Writes the page in the constrained-HTML wire format and submits "
                "it with author_web_page. Owns markup, copy, and imagery; give it "
                "the section plan and copy angles."
            ),
            "system_prompt": build_web_author_prompt(
                brand_card=tools.brand_card_text,
                theme_token_names=theme_token_names,
                account_card=tools.account_card_text,
                brandfetch_client_id=runtime_config.brandfetch_client_id,
            ),
            "model": author_model,
            "tools": [
                subagent_view,
                tools.web_ops,
                tools.author_web_page,
                tools.author_web_subtree,
                tools.patch_web_page,
                tools.fetch_page,
                tools.fetch_logo,
                # F4.3 (ruling R25-1): the other half of the ladder. `fetch_logo` puts a target's
                # real mark on THIS page; this saves it onto the ACCOUNT, so `{{account.logo}}`
                # resolves for them on every page derived from any campaign template. Without it
                # a fetched logo dies with the turn and a fifty-account batch publishes fifty
                # empty logo slots. It is a named, per-account act on purpose — never a sweep.
                tools.bind_account_logo,
                tools.search_assets,
                # F2.3: the reuse ladder's bottom rung. The AUTHOR gets both halves — chrome and
                # proof bands are reused where a released clone serves the job, and composing one
                # from scratch is what happens when none does.
                tools.search_cloned_sections,
                tools.inspect_cloned_section,
                tools.insert_cloned_section,
                # F3.1: the two halves of the recreate walk. `recreate_cloned_page` is the
                # whole-page assembly (all of them, source order, nothing added);
                # `repair_cloned_section` is D-F6's ladder for the ones that came back broken.
                # Both write to the document, so both belong to the author and to no one else.
                tools.recreate_cloned_page,
                # The paved verb for the one-step campaign flow (2026-08-30): pin a CHOSEN,
                # ordered subset of released clones onto an empty page atomically, slots
                # rebindable in the same call — the middle ground between the whole-page
                # recreate and pin-by-pin choreography.
                tools.assemble_cloned_sections,
                tools.repair_cloned_section,
                # Founder ruling 2026-08-30: the raw-CSS authoring lane. A NEW band that must
                # match the source site's fidelity is composed as real HTML+CSS through the
                # same sanitize-once pipeline every captured byte passes, minted released, and
                # pinned like any clone. The author's, because it writes library content the
                # author then places.
                tools.compose_web_section,
                tools.set_web_typography_reference,
                # F4.4 (FOUNDER RULING R-X9): a repair is released ONE AT A TIME, by a human who
                # was shown it and asked. The brand-kit approval no longer sweeps repairs along
                # with the harvested sections, so this is the only door — and it is the author's
                # because the author is who composed the repair and who can explain it. It
                # enacts an answer; it never decides one (see the prompt's release law).
                tools.release_repair,
                # F4.1: the ABM page's own chrome. A library operation, not a document write —
                # it mints the two shells and touches no page — but it belongs to the author for
                # the same reason the other two do: the author is the role that decides what a
                # page wears, and the shells exist to be worn INSTEAD of the cloned nav.
                tools.mint_campaign_shells,
                # F4.2: the assembly. `mint_campaign_shells` makes the chrome; this is what puts
                # it on — header first, footer last, hero between, everything bound to the
                # account MARKERS rather than to one account's values. It writes to the document,
                # so it is the author's, and it refuses rather than falling back to the cloned
                # nav, which is the campaign-shell rule made structural instead of prompted.
                tools.assemble_abm_page,
                tools.provenance,
                tools.asset,
                tools.list_custom_components,
                tools.inspect_custom_component,
                tools.write_custom_component_source,
                tools.compile_custom_component,
                tools.place_custom_component,
                # F5 task 8: a READ, and only the read. The author writes the page the
                # director switched to, so it needs to know which page that is (and what
                # routes its sibling pages answer on, to link between them) — but creating,
                # dropping and switching pages is the director's plan, not the author's.
                tools.list_pages,
                *platform_read_tools,
            ],
            "skills": workspace_skills,
        },
        {
            "name": "lumen-web-reviewer",
            "description": (
                "Judges the rendered page against the review-website checklist at "
                "all three widths and returns a structured VisualCritique."
            ),
            "system_prompt": build_web_reviewer_prompt(
                has_account=bool(tools.account_card),
                brief=tools.reviewer_brief_text,
            ),
            "model": reviewer_model,
            "tools": [subagent_view, tools.provenance],
            "skills": workspace_skills,
            # Same rationale as the scene reviewer: extract VisualCritique via the
            # TOOL strategy (native structured output emits malformed JSON on some
            # OpenRouter providers); its default handle_errors re-asks on a
            # validation failure instead of killing the run.
            "response_format": ToolStrategy(VisualCritique),
        },
        ]
    )

    # --- the web lane's fast loop / ruling D-F7: reviewer QUARANTINED, not deleted -------------
    # The scene lane's R3 quarantine, mirrored for web turns (F3.3). Under the web fast loop the
    # `lumen-web-reviewer` subagent is not registered, so the orchestrator cannot dispatch it —
    # tool-absence enforcement, not a prompt asking nicely — and it self-reviews against the SAME
    # shared rubric artifact instead (the prompt builder interpolates it; see prompts_web).
    #
    # Everything about the reviewer stays BUILT above: its prompt (rubric included), its own
    # model instance, its ToolStrategy(VisualCritique), its whole dict. It is one config flag
    # from being live again, and `LUMEN_AGENT_WEB_REVIEWER=1` is that flag.
    if not runtime_config.web_solo and not runtime_config.web_reviewer_enabled:
        subagents = [sa for sa in subagents if sa["name"] != _REVIEWER_SUBAGENT]
        logger.info(
            "web_reviewer_quarantined",
            run_id=tools.run_id,
            quarantined=[_REVIEWER_SUBAGENT],
            reason="web_fast_loop_d_f7",
        )

    orchestrator_tools = [
        view,
        tools.fetch_page,
        tools.search_assets,
        # Discovery only, deliberately: the director DECIDES the reuse ladder (which bands are
        # reused and which are composed) and names the sections in the author's brief; the author
        # is the only role that writes to the document.
        tools.search_cloned_sections,
        tools.provenance,
        # F4 wave item 4 (the CP2 walk's F-4): the logo ladder lived only on the author role,
        # so a director's "bind logos, change nothing" delegation to a generic subagent bound
        # NOTHING and reported success. Neither tool writes the document — fetch_logo ingests
        # assets and bind_account_logo stamps the ACCOUNT row — so the author-owns-the-document
        # law survives their presence here.
        tools.fetch_logo,
        tools.bind_account_logo,
        tools.list_custom_components,
        tools.inspect_custom_component,
        tools.render_web_preview,
        tools.set_web_typography_reference,
        # F3.3: the behavioural review gate. The ORCHESTRATOR's, in both flag states — it is the
        # role that renders and the role that decides, and its findings are advice a director
        # weighs rather than markup an author edits. The reviewer subagent, when it exists, reads
        # the gate's captures through the director's brief exactly as it reads the previews.
        tools.review_cloned_page,
        # F5 task 8: the site's page shape is the DIRECTOR's plan. It creates every page the
        # plan names before the first delegation and switches to each one in turn, because
        # the author always writes the ACTIVE page and one author brief covers exactly one
        # page. None of these four write page content.
        tools.list_pages,
        tools.add_page,
        tools.remove_page,
        tools.switch_page,
        tools.finalize_web_run,
    ]
    # Design note 2026-09-19: on a LEG turn the platform's reads become three tools here too —
    # a landing page for a named company is written from what research found about it. Off a leg
    # turn `platform_reads` is None and the tools do not exist. Inserted before finalize_web_run
    # so the honest exit stays last.
    if runtime_config.platform_reads is not None:
        for read_tool in platform_read_tools:
            orchestrator_tools.insert(len(orchestrator_tools) - 1, read_tool)
        # Spec 2026-10-30 §3.5: Python over the chat's files.
        run_python = design_run_python(
            tools, tools.trace_dir / "workspace", runtime_config.platform_reads
        )
        if run_python is not None:
            orchestrator_tools.insert(len(orchestrator_tools) - 1, run_python)
        tools.record(
            "orchestrator",
            "platform_reads_attached",
            payload={"tools": [read.name for read in platform_read_tools]},
        )

    if runtime_config.web_solo:
        # SOLO MODE (founder ruling 2026-09-04): the one agent is director, designer, and
        # judge, so it carries the author's whole write surface on top of the director's
        # read/render/judge surface above. The author-owns-the-document law is not
        # weakened — there is exactly one document-writing role either way; it simply has
        # the director's eyes now.
        orchestrator_tools += [
            tools.web_ops,
            tools.author_web_page,
            tools.author_web_subtree,
            tools.patch_web_page,
            tools.insert_cloned_section,
            # 2026-09-04: the raw lane's missing read — a clone's real HTML+CSS, so a variant
            # or raw composition remixes bytes instead of imagining them.
            tools.inspect_cloned_section,
            tools.recreate_cloned_page,
            tools.assemble_cloned_sections,
            tools.repair_cloned_section,
            tools.compose_web_section,
            tools.release_repair,
            tools.mint_campaign_shells,
            tools.assemble_abm_page,
            tools.asset,
            tools.write_custom_component_source,
            tools.compile_custom_component,
            tools.place_custom_component,
        ]
        logger.info(
            "web_subagents_quarantined",
            run_id=tools.run_id,
            quarantined=[_AUTHOR_SUBAGENT, _REVIEWER_SUBAGENT],
            reason="web_solo_2026_09_04",
        )

    doc_title = initial_web_doc.get("title") or "Untitled site"
    page_routes = [
        page["route"]
        for page in initial_web_doc.get("pages") or []
        if isinstance(page, dict) and page.get("route")
    ]
    if runtime_config.web_solo:
        system_prompt = build_web_solo_prompt(
            doc_title=doc_title,
            has_existing_content=has_existing_content(initial_web_doc),
            brand_card=tools.brand_card_text,
            theme_token_names=theme_token_names,
            account_card=tools.account_card_text,
            brandfetch_client_id=runtime_config.brandfetch_client_id,
            page_routes=page_routes,
            # The RUN-SCOPED workspace (founder correction 2026-09-04): plan.md lives
            # beside this run's brief.md, never at the shared backend root — a bare
            # relative "workspace/" resolved there and leaked one brief's plan into the
            # next run (the Ramp run inherited the billing campaign's 380-line plan).
            workspace_dir=workspace_str,
            # The marketer's numbered annotations (R-A1..R-A3, 2026-09-04): when they ride
            # the turn, the prompt carries the law for honouring them; when they do not,
            # the block is absent.
            annotations=runtime_config.turn_target_notes,
        )
    else:
        system_prompt = build_web_orchestrator_prompt(
            doc_title=doc_title,
            # F5 task 8: ANY page having content makes this a continuation, not a fresh
            # site — a second page authored last turn is standing work the director must
            # not treat as an empty document.
            has_existing_content=has_existing_content(initial_web_doc),
            brand_card=tools.brand_card_text,
            review_cap=WEB_REVIEW_DELEGATION_CAP,
            author_cap=WEB_AUTHOR_DELEGATION_CAP,
            account_card=tools.account_card_text,
            # D-F7: the same rubric either way; only who applies it moves.
            web_reviewer=runtime_config.web_reviewer_enabled,
            page_routes=page_routes,
        )
    agent = create_deep_agent(
        model=orchestrator_model,
        backend=backend,
        permissions=_filesystem_permissions(),
        # One response's tool calls run in parallel threads by default; the substrate's
        # document is shared read-modify-write state, so they are serialized (see
        # `serialize_tool_calls`).
        tools=serialize_tool_calls(orchestrator_tools, tools.tool_lock),
        system_prompt=system_prompt,
        # SOLO carries the skills tree itself (it is the reader now); the trio path keeps
        # skills on the subagents exactly as before (None = the library default).
        skills=(workspace_skills if runtime_config.web_solo else None),
        subagents=subagents,
        # G4/G6: the delegation budgets ride as ordinary tool-call middleware on the
        # ORCHESTRATOR, which is where `task` executes. Fresh per turn, so the counters
        # cannot leak.
        middleware=[
            WebDelegationCap(record=tools.record),
            *_context_clearing_middleware(runtime_config),
        ],
        name="lumen-web-deepagent",
        checkpointer=checkpointer,
    )
    return agent, tools


def _context_clearing_middleware(runtime_config: AgentRuntimeConfig) -> list:
    """Founder decisions 2026-10-06: superseded screenshots and finished planning results leave
    the model request (never the saved history). Off restores the previous composition."""
    if not runtime_config.web_context_clearing:
        return []
    from langchain.agents.middleware import ContextEditingMiddleware

    from .context_clearing import SupersededToolResultsEdit

    return [ContextEditingMiddleware(edits=[SupersededToolResultsEdit()])]


def run_deepagent_web_turn(
    prompt: str,
    config: AgentRuntimeConfig | None = None,
    initial_web_doc: dict | None = None,
    event_sink=None,
    *,
    checkpointer: Any = None,
    thread_id: str | None = None,
    cancel_requested=None,
    callbacks: "TurnCallbacks | None" = None,
) -> dict:
    """Create + invoke + guarantee an honest finalize.

    Returns {status: "applied"|"failed", summary, web_doc (final), operations,
    grounding, preview_paths, outcome}. `applied` iff the orchestrator finalized
    accepted/completed_with_warnings; a crash/recursion-limit/no-finalize turn
    is finalized "failed" here — never a fabricated success.

    `checkpointer` / `thread_id` (D5 Round B): the durable-execution seam, supplied together by
    the fleet handler. `thread_id` is the DESIGN RUN ID (the D5 ruling); absent it, the turn
    threads on `tools.run_id` exactly as before. See checkpoint.py for the honest resume
    semantics that shipped (resume-as-restart, and why).

    `cancel_requested` (A3, defect R3-D): the run's cancellation probe. A cancelled web turn ends
    `failed` with nothing applied and a summary that says a human stopped it — which is the whole
    truth here, because website mode persists once at the end and so a stopped turn has nothing
    partial to keep. See `create_web_deepagent`.

    `callbacks` (lane 3 slice 5): the platform's injected LangChain handlers and run-id registry,
    attached at the invoke config exactly as the scene harness attaches them — see
    `harness.run_deepagent_turn`. The turn's per-call receipts ride back on the returned dict's
    `model_calls` key, on every terminal path."""
    agent, tools = create_web_deepagent(
        prompt,
        config=config,
        initial_web_doc=initial_web_doc or {},
        event_sink=event_sink,
        checkpointer=checkpointer,
        cancel_requested=cancel_requested,
    )

    run_log_path = tools.turn_dir / "logs" / "run.jsonl"
    with run_log(tools.run_id, run_log_path):
        logger.debug("web_run_log_attached", run_id=tools.run_id, run_log_path=str(run_log_path))

        tools.record(
            "coordinator",
            "web_turn_started",
            input_summary=prompt[:500],
            output_summary=f"workspace=/{tools.workspace_scope_id}/workspace",
        )

        # Design session continuity: the run id rides the human message so a retry of the SAME
        # run resumes its thread and a new run continues it — see `harness.run_deepagent_turn`.
        initial_state = {
            "messages": [
                HumanMessage(
                    content=with_attachments_note(prompt, tools.attachments_note),
                    additional_kwargs={RUN_ID_KEY: tools.run_id},
                )
            ]
        }
        # Lane 3 slice 5: the turn's receipts and the platform's injected handlers ride the
        # INVOKE CONFIG — see `harness.run_deepagent_turn` for why config-level, not
        # instance-level.
        from .usage_collector import turn_collector

        collector, turn_handlers = turn_collector(callbacks)
        invoke_config = {
            "recursion_limit": 200,
            "configurable": {"thread_id": thread_id or tools.run_id},
            "callbacks": turn_handlers,
        }

        exception_text: Optional[str] = None
        try:
            # A3: the boundary BEFORE the first model call, so a turn cancelled while it sat queued
            # pays for nothing. No-op when no probe was supplied.
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
            # A3 (defect R3-D). Caught above the generic handler purely so the finalize below says
            # "a human stopped this" instead of the generic "orchestrator ended without finalize" —
            # the honest-failure PATH is unchanged and deliberately reused, only its reason is
            # truthful. There is no `completed_with_warnings` branch here and there should not be:
            # website mode persists once at the end, so a cancelled turn applied nothing, and
            # claiming partial success would be the fabrication this whole envelope guards against.
            exception_text = str(error)
            tools.record(
                "coordinator",
                CANCELLED_EVENT,
                output_summary=exception_text[:500],
                payload={"stop_reason": CANCELLED_STOP_REASON},
                sink_extra={"stop_reason": CANCELLED_STOP_REASON},
            )
        except Exception as error:  # noqa: BLE001 - honest failure, recorded verbatim
            exception_text = f"{type(error).__name__}: {error}"
            tools.record(
                "coordinator",
                "web_turn_exception",
                output_summary=exception_text[:500],
                payload={"exception": exception_text},
            )

        final_path = tools.turn_dir / "final.json"
        if not final_path.exists():
            # The orchestrator never finalized — HONEST failure, never fabricated.
            tools.finalize_web_run(
                "failed", exception_text or "orchestrator ended without finalize"
            )
        final = json.loads(final_path.read_text(encoding="utf-8"))
        outcome = final.get("outcome", "failed")
        summary = final.get("summary", "")

        final_doc_path = tools.turn_dir / "final_web_doc.json"
        web_doc = (
            json.loads(final_doc_path.read_text(encoding="utf-8"))
            if final_doc_path.exists()
            else tools.web_doc
        )

        status = "applied" if outcome in ("accepted", "completed_with_warnings") else "failed"
        return {
            "status": status,
            "summary": summary,
            "web_doc": web_doc,
            "operations": list(tools.operations_ledger),
            "grounding": tools.grounding_report(),
            "preview_paths": list(tools.preview_paths),
            "outcome": outcome,
            # Lane 3 slice 5: what this turn actually spent, on the ONE terminal return this
            # harness has (an honest failure comes back through here too).
            "model_calls": [call.as_json() for call in collector.calls],
        }
