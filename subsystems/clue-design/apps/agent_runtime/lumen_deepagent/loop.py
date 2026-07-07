from __future__ import annotations

import copy
import json
import re
from typing import Optional, Protocol

from .accommodation import (
    CONFLICT_CLEARANCE_THRESHOLD,
    clearance,
    page_space_box,
    turn_introduced_conflicts,
)
from .schemas import (
    AgentActionMode,
    AgentDirectorDecision,
    AgentIteration,
    AgentRunState,
    AuthoringBlockRequest,
    CompileRepairContext,
    CompileSummary,
    DiagnosticSeverity,
    PreviewTarget,
    PreflightSummary,
    ExportSummary,
    KnowledgeSnippet,
    LayoutClusterTarget,
    RepairClass,
    RepairClassification,
    EditSurfaceRecommendation,
    StopReason,
    VisualCritique,
    VisualIssue,
    VisualTarget,
)
from .prompts import (
    DSL_REF_GRAMMAR_ESCALATION,
    IMAGERY_REPAIR_RECIPE,
    POSTER_RECOMPOSE_RECIPE,
    REPEAT_BLOCK_ESCALATION,
    SEEDED_CONTINUATION_RECIPE,
)
from .tools import LumenDesignTools


# Visual-critique categories that signal a vertical-distribution / dead-band
# problem the poster idiom fixes. When the latest critique carries one of these,
# the loop hands the rebuild the exact poster recipe (P1.5#2a) so the LLM
# recompose converges on the fixed structure instead of re-stranding content.
RECOMPOSE_CATEGORIES = {"visual_balance", "spacing"}

# Visual-critique categories that signal an IMAGERY-quality problem (Step 9). An
# image defect is repaired as an image — regenerate / recrop / scrim / replace /
# remove — NOT as a layout-geometry patch, so the loop routes these to the
# asset-tool surface and hands the rebuild IMAGERY_REPAIR_RECIPE.
IMAGERY_CATEGORIES = {"imagery"}

# Structural layout categories take precedence over an imagery defect: a clipped or
# unbalanced page is fixed by geometry first, then the imagery axis is revisited next
# iteration. (Mirrors the layout-cluster forcing set in classify_visual_critique.)
_STRUCTURAL_LAYOUT_CATEGORIES = {"visual_balance", "alignment", "spacing", "compiler_repair"}

# How much a critic issue counts against a draft when ranking keep-best
# candidates. A raw issue COUNT treats "entirely clipped off-canvas" (blocker)
# the same as a margin nit (warning): run_8e7b9f64 proposed an invisible badge
# over a visible one because both drafts had two issues and the invisible one
# was rejected with higher confidence. Weights are deliberately coarse — one
# blocker outweighs several errors, one error outweighs a pile of warnings.
_ISSUE_SEVERITY_PENALTY = {
    DiagnosticSeverity.info: 0,
    DiagnosticSeverity.warning: 1,
    DiagnosticSeverity.error: 3,
    DiagnosticSeverity.blocker: 10,
}

# Phase 0b: action modes that author from scratch (or wipe the working scene).
# On a SEEDED run the scene is the user's live document — these are coerced to
# targeted_patch so the turn continues the document instead of replacing it.
SEEDED_FORBIDDEN_ACTION_MODES = {
    AgentActionMode.new_artifact,
    AgentActionMode.full_page_rewrite,
    AgentActionMode.replace_artboard_subtree,
}

# The two ways an authoring block re-authors existing content instead of editing
# it: re-declaring an existing node id (LUMD0401) or an existing page (LUMA0200).
# Both halt the compile with the code preserved in `halted_at.code` — the ONE
# place the code survives diagnostic normalization (diagnostics_from stringifies
# session-shaped DSL diagnostics, so `diagnostics[].code` may be null).
REAUTHOR_HALT_CODES = {"LUMD0401", "LUMA0200"}
_REAUTHORED_NODE_RE = re.compile(r"duplicate node id ([A-Za-z0-9_.\-]+)")
_REAUTHORED_PAGE_RE = re.compile(r"recreate existing page ([A-Za-z0-9_.\-]+)")
# LUMD0901 halts whose "missing node" is actually an existing PAGE id: the
# author wrote `#page_a4 ...` (node-ref grammar) where the page-modify grammar
# is `#page:page_a4 ...` — or pointed replace() at a page. Observed live
# (run_8cbeae790f07): the model followed the LUMA0200 corrective hint but used
# the wrong ref form, and burned every remaining iteration on it.
_MISSING_TARGET_RE = re.compile(
    r"(?:target node|replace target) ([A-Za-z0-9_.\-]+) does not exist"
)


def recompose_recipe_for_feedback(feedback: Optional[dict]) -> Optional[str]:
    """Return the poster-idiom recipe when the latest visual critique flags a
    vertical-distribution problem (dead bands / imbalance), else None."""
    if not isinstance(feedback, dict) or feedback.get("kind") != "visual":
        return None
    payload = feedback.get("feedback") or {}
    categories = {
        str(issue.get("category"))
        for issue in (payload.get("issues") or [])
        if isinstance(issue, dict) and issue.get("category")
    }
    if categories & RECOMPOSE_CATEGORIES:
        return POSTER_RECOMPOSE_RECIPE
    return None


def imagery_recipe_for_feedback(feedback: Optional[dict]) -> Optional[str]:
    """Return the imagery-repair recipe when the latest visual critique flags an
    imagery-quality problem (and not a structural layout problem that must be fixed
    first), else None. Mirrors ``recompose_recipe_for_feedback`` (Step 9)."""
    if not isinstance(feedback, dict) or feedback.get("kind") != "visual":
        return None
    payload = feedback.get("feedback") or {}
    categories = {
        str(issue.get("category"))
        for issue in (payload.get("issues") or [])
        if isinstance(issue, dict) and issue.get("category")
    }
    if categories & IMAGERY_CATEGORIES and not (categories & _STRUCTURAL_LAYOUT_CATEGORIES):
        return IMAGERY_REPAIR_RECIPE
    return None


class DslAuthor(Protocol):
    def write_block(self, request: AuthoringBlockRequest) -> str:
        """Return one DSL block for the current authoring or repair step."""


class VisualReviewer(Protocol):
    def review(
        self,
        *,
        user_request: str,
        scene_summary: dict,
        export_summary: dict,
        preview_payload: dict,
        knowledge: list[dict],
        previous_feedback: list[dict],
        full_context: dict,
    ) -> VisualCritique:
        """Review the current preview and return a structured critique."""


class AgentDirector(Protocol):
    def decide(self, *, full_context: dict) -> AgentDirectorDecision:
        """Choose the next authoring/repair strategy from the complete context."""


class HeuristicAgentDirector:
    """Deterministic fallback director used by tests and non-provider callers."""

    def decide(self, *, full_context: dict) -> AgentDirectorDecision:
        latest = full_context.get("latest_feedback")
        if not isinstance(latest, dict):
            return AgentDirectorDecision(
                action_mode=AgentActionMode.new_artifact,
                rationale="No previous feedback exists; author a new artifact.",
                instructions_to_author=(
                    "Create the requested artifact from the user request. "
                    "Ignore unrelated seed editor selections unless the user asks to edit them."
                ),
            )

        repair_class = latest.get("repair_class")
        if repair_class == RepairClass.layout_cluster.value:
            return AgentDirectorDecision(
                action_mode=AgentActionMode.layout_cluster_rewrite,
                rationale="Previous feedback requires a layout-cluster repair.",
                target=VisualTarget.model_validate(latest.get("target") or {})
                if latest.get("target")
                else None,
                allowed_scope=latest.get("cluster") or {},
                instructions_to_author=(
                    "Repair the affected layout cluster as a structural layout problem. "
                    "Prefer a coherent bounded rewrite over many tiny local patches."
                ),
            )

        if latest.get("kind") == "visual":
            feedback = latest.get("feedback") or {}
            issues = feedback.get("issues") or []
            categories = {
                str(issue.get("category"))
                for issue in issues
                if isinstance(issue, dict) and issue.get("category")
            }
            if categories & {"visual_balance", "alignment", "compiler_repair", "spacing"}:
                return AgentDirectorDecision(
                    action_mode=AgentActionMode.replace_artboard_subtree,
                    rationale=(
                        "Visual critique identified composition/layout quality issues "
                        "that need structural repair."
                    ),
                    target=VisualTarget.model_validate(first_issue_target_from_payload(feedback))
                    if first_issue_target_from_payload(feedback)
                    else None,
                    allowed_scope={"visual_issue_categories": sorted(categories)},
                    instructions_to_author=(
                        "Use the full visual critique verbatim. Rebuild the affected artboard "
                        "composition if that is the clearest way to satisfy the critique."
                        + (
                            f"\n\n{POSTER_RECOMPOSE_RECIPE}"
                            if categories & RECOMPOSE_CATEGORIES
                            else ""
                        )
                    ),
                )
            # Step 9: a pure imagery-quality critique is an asset repair, not a layout
            # rewrite — fix the image (regenerate/recrop/scrim/replace/remove).
            if categories & IMAGERY_CATEGORIES:
                imagery_target = first_issue_target_from_payload(feedback)
                return AgentDirectorDecision(
                    action_mode=AgentActionMode.targeted_patch,
                    rationale=(
                        "Visual critique flagged an imagery-quality problem; repair the "
                        "image as an asset, not the layout."
                    ),
                    target=VisualTarget.model_validate(imagery_target)
                    if imagery_target
                    else None,
                    allowed_scope={"visual_issue_categories": sorted(categories)},
                    instructions_to_author=(
                        "Use the full visual critique verbatim. Fix the IMAGE as an image — "
                        "do not patch layout geometry."
                        f"\n\n{IMAGERY_REPAIR_RECIPE}"
                    ),
                )

        target = latest.get("target") if isinstance(latest.get("target"), dict) else {}
        return AgentDirectorDecision(
            action_mode=AgentActionMode.targeted_patch,
            rationale="Latest feedback is narrow enough for a targeted patch.",
            target=VisualTarget.model_validate(target) if target else None,
            instructions_to_author=(
                "Apply the smallest patch that resolves the latest compiler/preflight feedback."
            ),
        )


class LumenQualityLoop:
    """Deterministic Phase A loop used by DeepAgents and tests.

    This class keeps orchestration explicit and testable. LLM-backed
    implementations can wrap the author/reviewer protocols, while deterministic
    tests can use scripted fakes.
    """

    def __init__(
        self,
        tools: LumenDesignTools,
        author: DslAuthor,
        reviewer: VisualReviewer,
        director: AgentDirector | None = None,
    ) -> None:
        self.tools = tools
        self.author = author
        self.reviewer = reviewer
        self.director = director or HeuristicAgentDirector()
        self.previous_feedback: list[dict] = []
        self.director_decisions: list[dict] = []
        self.state = AgentRunState(run_id=tools.run_id, user_request=tools.prompt)
        # Snapshot of the most recent scene that compiled cleanly (and is
        # therefore renderable). A later repair iteration can author a
        # destructive block — e.g. delete-then-recreate — whose compile halts
        # partway, leaving `tools.scene` stripped of the good design. We restore
        # this snapshot when the run fails so the editor always receives the best
        # renderable draft on the canvas instead of a wiped scene.
        #
        # `best_scene` is the BEST draft seen this run, not merely the last one
        # that compiled. We rank candidates by `best_rank` (preflight-clean beats
        # compile-only; among those, accepted beats rejected, then fewer critic
        # issues, then higher critic confidence) so a later, worse iteration can
        # never clobber an earlier, better design. This is what the editor gets
        # back when no iteration is ever `accepted`.
        self.best_scene: Optional[dict] = None
        self.best_rank: Optional[tuple] = None
        self.best_iteration: Optional[int] = None
        # Phase 0b: the node/page ids this run's APPLIED operations touched — the
        # edit scope that edit-scoped acceptance judges critique issues against.
        self.edited_node_ids: set = set()
        self.edited_page_ids: set = set()
        # Agent-improvement follow-up 1 (baseline-diff repair scoping): errors
        # that already existed on the SEEDED scene before this turn touched it,
        # keyed by (code, subject) — see `_diagnostic_key`. Populated once at
        # the start of `run()`. The Phase A preflight gate must block only on
        # errors NOT in this set (i.e. errors this turn introduced); baseline
        # errors are surfaced as advisory context instead of burning repair
        # iterations. Empty for an unseeded (fresh) run — there is no prior
        # state to baseline against.
        self.baseline_diagnostic_keys: set = set()
        self.baseline_diagnostics: list[dict] = []
        # Baseline errors the turn never touched (still present, unaddressed,
        # by the time the run finalizes) — surfaced as advisory in the result.
        self.unaddressed_baseline_diagnostics: list[dict] = []
        # Accommodation edits: the seeded scene AS GEOMETRY, captured before
        # the turn's first edit, so turn-introduced crowding can be measured
        # (baseline_diagnostics above only captures diagnostic keys). None for
        # an unseeded run.
        self.baseline_scene: Optional[dict] = None
        # Latest detection: turn-introduced (edited node × neighbor) conflicts
        # on the CURRENT draft — drives the critic hint, the repair
        # accommodation clause, and edit-scoped-acceptance scope expansion.
        self.accommodation_conflicts: list[dict] = []
        # Every conflict ever detected this run, keyed (edited, neighbor).
        # The final announcement diffs these neighbors' geometry against the
        # baseline: a repair that RESOLVES a conflict empties the latest list,
        # but the nudge that resolved it must still be reported.
        self.accommodation_conflict_log: dict = {}
        # At most ONE forced accommodation repair round per run (see
        # _should_force_accommodation_round).
        self.accommodation_repair_attempted = False
        # Phase 3c: at most ONE loop-executed imagery repair (edit_image /
        # regenerate) per run — mirrors the accommodation forced-round counter so
        # a pure-imagery critique can never wedge the loop on repeated repairs.
        self.imagery_repair_attempted = False
        # K4 sweep finding: logo adoption measured 5/10 while typography and
        # palette held at 0.96/1.00 — the pixel critic accepts logo-less
        # drafts on kits that PROVIDE logo assets. One bounded placement
        # round per run (a missing logo is one operation, unlike the 25-edit
        # rebind that wedged run_bff3433f).
        self.logo_repair_attempted = False
        # Latest imagery verdict from the PNG-render-seam gate (DET, + judge when a
        # key is configured), or None on scenes without generated/edited imagery.
        self.imagery_verdict: Optional[dict] = None

    def run(self, user_request: str) -> dict:
        # Agent-improvement follow-up 1: capture the seeded scene's OWN
        # diagnostics before this turn's first draft/edit ever applies. Must
        # happen before the iteration loop so every gate this run runs sees
        # the same baseline (the loop never re-captures mid-run).
        self.baseline_diagnostics = self.tools.baseline_preflight_diagnostics()
        self.baseline_diagnostic_keys = {
            _diagnostic_key(diag) for diag in self.baseline_diagnostics
        }
        # Accommodation edits: snapshot the seeded scene's geometry at the same
        # pre-first-edit moment, so crowding this turn CREATES is separable
        # from adjacency the design already had (frozen output legitimately
        # contains 0pt gaps — see the calibration in
        # .context/agent-improvement/2026-07-05-accommodation-edits.md).
        if self.tools.seeded_from_initial_scene and isinstance(self.tools.scene, dict):
            self.baseline_scene = copy.deepcopy(self.tools.scene)
        knowledge = json.loads(self.tools.load_knowledge(user_request))
        self.state.loaded_knowledge = [
            KnowledgeSnippet.model_validate(snippet)
            for snippet in knowledge.get("snippets", [])
        ]
        knowledge_snippets = [
            KnowledgeSnippet.model_validate(snippet)
            for snippet in knowledge.get("snippets", [])
        ]
        for _ in range(self.tools.config.max_iterations):
            full_context = self.tools.curated_context(
                user_request=user_request,
                previous_feedback=self.previous_feedback,
                director_decisions=self.director_decisions,
            )
            decision = self.director.decide(full_context=full_context)
            # Phase 0b: a seeded run continues the user's live document. Fresh
            # authoring would discard or collide with it — coerce those modes to
            # a targeted continuation, deterministically, and record it. (The
            # tools-level start_fresh_rewrite_scene refuses seeded scenes too;
            # this keeps the iteration productive instead of merely safe.)
            if (
                self.tools.seeded_from_initial_scene
                and decision.action_mode in SEEDED_FORBIDDEN_ACTION_MODES
            ):
                original_mode = decision.action_mode
                decision = decision.model_copy(
                    update={
                        "action_mode": AgentActionMode.targeted_patch,
                        "instructions_to_author": (
                            f"(The director chose '{original_mode.value}', which is "
                            "unavailable on a seeded document. Perform the intent "
                            "as targeted edits within the existing scene instead.)"
                            f"\n\n{decision.instructions_to_author}"
                        ).strip(),
                    }
                )
                self.tools.record(
                    "director",
                    "seeded_mode_coerced",
                    input_summary=original_mode.value,
                    output_summary=(
                        f"coerced {original_mode.value} -> targeted_patch: a "
                        "seeded scene is continuation-only"
                    ),
                    payload={
                        "from": original_mode.value,
                        "to": AgentActionMode.targeted_patch.value,
                    },
                )
            # P1.5#2a: when the latest critique flags a vertical-distribution
            # problem (dead bands / visual_balance / spacing), deterministically
            # hand the rebuild the exact poster-idiom recipe — regardless of what
            # the LLM director wrote — so the recompose converges on the fixed
            # structure instead of re-stranding content. Skip terminal modes.
            recompose_recipe = recompose_recipe_for_feedback(
                self.previous_feedback[-1] if self.previous_feedback else None
            )
            if recompose_recipe and decision.action_mode not in {
                AgentActionMode.accept,
                AgentActionMode.stop_with_gap,
            } and POSTER_RECOMPOSE_RECIPE not in (decision.instructions_to_author or ""):
                decision = decision.model_copy(
                    update={
                        "instructions_to_author": (
                            f"{decision.instructions_to_author}\n\n{recompose_recipe}"
                            if decision.instructions_to_author
                            else recompose_recipe
                        )
                    }
                )
            # Step 9: when the latest critique flags an IMAGERY axis, deterministically
            # hand the rebuild the imagery-repair recipe so the fix is an asset operation
            # (regenerate / recrop / scrim / replace / remove), not a layout patch.
            imagery_recipe = imagery_recipe_for_feedback(
                self.previous_feedback[-1] if self.previous_feedback else None
            )
            if imagery_recipe and decision.action_mode not in {
                AgentActionMode.accept,
                AgentActionMode.stop_with_gap,
            } and IMAGERY_REPAIR_RECIPE not in (decision.instructions_to_author or ""):
                decision = decision.model_copy(
                    update={
                        "instructions_to_author": (
                            f"{decision.instructions_to_author}\n\n{imagery_recipe}"
                            if decision.instructions_to_author
                            else imagery_recipe
                        )
                    }
                )
            # Phase 0b: every seeded-turn author instruction carries the
            # continuation recipe (modify-line grammar, never re-author existing
            # ids, fresh ids for new content) so grammar discovery does not burn
            # an iteration — 0a's e2e lost its first iteration to exactly that.
            if (
                self.tools.seeded_from_initial_scene
                and decision.action_mode
                not in {AgentActionMode.accept, AgentActionMode.stop_with_gap}
                and SEEDED_CONTINUATION_RECIPE
                not in (decision.instructions_to_author or "")
            ):
                decision = decision.model_copy(
                    update={
                        "instructions_to_author": (
                            f"{decision.instructions_to_author}\n\n{SEEDED_CONTINUATION_RECIPE}"
                            if decision.instructions_to_author
                            else SEEDED_CONTINUATION_RECIPE
                        )
                    }
                )
            decision_payload = decision.model_dump(mode="json")
            self.director_decisions.append(decision_payload)
            # Record ONLY the decision — never the context. Writing `full_context`
            # into the trace and then reading the trace back into the next
            # iteration's context is what made the prompt nest into itself and
            # explode past the token limit. The curated context is rebuilt fresh
            # from canonical state each iteration instead.
            self.tools.record(
                "director",
                "director_decision",
                input_summary=user_request[:500],
                output_summary=f"{decision.action_mode.value}: {decision.rationale[:300]}",
                payload={"decision": decision_payload},
            )
            if decision.action_mode == AgentActionMode.accept:
                self.state.status = "accepted"
                self.state.stop_reason = StopReason.accepted
                return json.loads(
                    self.tools.finalize_run(
                        "accepted",
                        StopReason.accepted.value,
                        decision.rationale,
                        baseline_advisory_json=self._baseline_advisory_payload_json(),
                        accommodation_json=self._accommodation_payload_json(),
                    )
                )
            if decision.action_mode == AgentActionMode.stop_with_gap:
                self.tools.record_gap(
                    "agent_protocol",
                    "director stopped with a gap",
                    decision.rationale,
                    "agentic-director-v0",
                )
                return self._finalize_failed(
                    StopReason.unsupported_capability.value,
                    decision.rationale,
                )

            block_request = AuthoringBlockRequest(
                iteration=self.tools.iteration + 1,
                user_request=user_request,
                preview_target=infer_preview_target(user_request),
                knowledge_paths=[
                    snippet["path"] for snippet in knowledge.get("snippets", [])
                ],
                knowledge_snippets=knowledge_snippets,
                current_scene_summary=json.loads(self.tools.summarize_scene()),
                repair_context=self.previous_feedback[-1] if self.previous_feedback else None,
                full_context=full_context,
                director_decision=decision,
            )
            # Strip the curated context out of the recorded author request for the
            # same reason as the director event: nothing context-shaped goes into
            # the trace, so the trace can never be re-inflated into a later prompt.
            recorded_request = block_request.model_dump(mode="json")
            recorded_request.pop("full_context", None)
            self.tools.record(
                "coordinator",
                "dsl_block_requested",
                input_summary=user_request[:500],
                output_summary=f"iteration {block_request.iteration}",
                payload={"author_request": recorded_request},
            )
            source = self.author.write_block(block_request)
            iteration_record = AgentIteration(
                index=block_request.iteration,
                dsl_source=source,
            )
            self.state.current_iteration = block_request.iteration
            self.state.iterations.append(iteration_record)
            self.tools.record(
                "dsl-author",
                "dsl_block_produced",
                input_summary=json.dumps(block_request.model_dump(mode="json"))[:500],
                output_summary=source[:500],
                payload={"dsl": source},
            )

            # Surgical-repair enforcement. When the previous gate asked for a
            # targeted in-place repair, the author must return modify-only DSL
            # (`#<id> ...` lines). A block that re-declares the page, deletes
            # nodes, or re-authors the scene is REJECTED here — before it ever
            # reaches the compiler — so a destructive repair can never strip the
            # existing design from the scene. The author retries with corrective
            # feedback; `tools.scene` is left untouched.
            repair_context = block_request.repair_context
            director_allows_structural_rewrite = decision.action_mode in {
                AgentActionMode.new_artifact,
                AgentActionMode.full_page_rewrite,
                AgentActionMode.replace_artboard_subtree,
            }
            if (
                repair_context
                and repair_context.get("repair_class") == RepairClass.layout_cluster.value
                and not director_allows_structural_rewrite
            ):
                # NON-ATOMIC cluster repair: keep the valid in-cluster modify lines
                # and drop only the out-of-cluster / unsupported ones, instead of
                # zero-applying the whole patch when a single line strays out of the
                # cluster. The iteration is wasted (fully rejected) only when NOTHING
                # in the block is a valid in-cluster edit — otherwise the valid edits
                # are applied and any still-unresolved diagnostics resurface naturally
                # on the next preflight.
                kept_source, dropped_lines = filter_layout_cluster_dsl(
                    source, repair_context
                )
                if not is_layout_cluster_dsl(kept_source, repair_context):
                    feedback = layout_cluster_violation_feedback(repair_context, source)
                    self.previous_feedback.append(feedback)
                    iteration_record.stop_reason = StopReason.compile_failed
                    self.tools.record(
                        "coordinator",
                        "layout_cluster_repair_rejected",
                        input_summary=json.dumps(repair_context.get("cluster") or {}),
                        output_summary=source[:300],
                        payload={"rejected_source": source[:2000]},
                    )
                    continue
                if dropped_lines:
                    self.tools.record(
                        "coordinator",
                        "layout_cluster_repair_partial",
                        input_summary=json.dumps(repair_context.get("cluster") or {}),
                        output_summary=(
                            "applied in-cluster edits; skipped "
                            f"{len(dropped_lines)} out-of-cluster line(s)"
                        ),
                        payload={
                            "applied_source": kept_source[:2000],
                            "dropped_lines": dropped_lines[:20],
                            "original_source": source[:2000],
                        },
                    )
                    source = kept_source
            if (
                repair_context
                and repair_context.get("repair_class") == RepairClass.slot_fixture.value
                and not director_allows_structural_rewrite
                and not is_surgical_dsl(source)
            ):
                # A slot-fixture repair must be modify-only (`#slot:<key> ...` or
                # `#<node> ...`). is_surgical_dsl permits those and rejects any
                # page/delete/re-author block, so the scene survives — while the
                # `#slot:` fixture edit the layout-cluster gate used to forbid is now
                # allowed through.
                feedback = slot_fixture_violation_feedback(repair_context, source)
                self.previous_feedback.append(feedback)
                iteration_record.stop_reason = StopReason.compile_failed
                self.tools.record(
                    "coordinator",
                    "slot_fixture_repair_rejected",
                    input_summary=json.dumps(repair_context.get("target") or {}),
                    output_summary=source[:300],
                    payload={"rejected_source": source[:2000]},
                )
                continue
            if (
                repair_context
                and repair_context.get("surgical_repair")
                and not director_allows_structural_rewrite
                and not is_surgical_dsl(source)
            ):
                feedback = surgical_violation_feedback(repair_context, source)
                self.previous_feedback.append(feedback)
                iteration_record.stop_reason = StopReason.compile_failed
                self.tools.record(
                    "coordinator",
                    "dsl_repair_not_surgical",
                    input_summary=json.dumps(
                        repair_context.get("surgical_target") or {}
                    ),
                    output_summary=source[:300],
                    payload={"rejected_source": source[:2000]},
                )
                continue

            # Agent-quality: a block IDENTICAL to the previous iteration's
            # cannot change the outcome — the prior attempt either applied (so
            # this is a no-op) or was rejected (so this fails the same way).
            # Observed live (run_d6e08a28): the same 1-op patch three times
            # against the same critique, burning the whole repair budget. Skip
            # the wasted compile/review and escalate the standing feedback so
            # the next attempt must change strictly more. This check sits
            # AFTER the cluster/surgical gates on purpose: their violation
            # feedback is the more specific correction, so it wins on a first
            # offense; the repeat gate catches identical re-emits that would
            # otherwise burn a full compile/review cycle.
            previous_source = (
                self.state.iterations[-2].dsl_source
                if len(self.state.iterations) >= 2
                else None
            )
            if (
                previous_source is not None
                and source.strip() == previous_source.strip()
                and self.previous_feedback
            ):
                standing = self.previous_feedback[-1]
                if standing.get("escalation") != "repeat_block":
                    standing["escalation"] = "repeat_block"
                    standing["authoring_constraints"] = [
                        REPEAT_BLOCK_ESCALATION,
                        *(standing.get("authoring_constraints") or []),
                    ]
                iteration_record.stop_reason = StopReason.compile_failed
                self.tools.record(
                    "coordinator",
                    "repeat_block_escalated",
                    input_summary=source[:300],
                    output_summary=(
                        "identical block re-emitted; compile/review skipped "
                        "and the standing feedback escalated"
                    ),
                    payload={"repeated_source": source[:2000]},
                )
                continue

            rewrite_scene_backup: Optional[dict] = None
            if (
                decision.action_mode
                in {
                    AgentActionMode.full_page_rewrite,
                    AgentActionMode.replace_artboard_subtree,
                }
                and self.tools.scene.get("pages")
            ):
                rewrite_scene_backup = copy.deepcopy(self.tools.scene)
                self.tools.start_fresh_rewrite_scene(decision.rationale)

            compile_result = json.loads(self.tools.compile_dsl_block(source))
            compile_summary = compile_result.get("compile", {})
            if rewrite_scene_backup is not None and tool_has_blocking_failure(
                compile_summary
            ):
                self.tools.scene = rewrite_scene_backup
                self.tools.dsl_session = None
                self.tools.record(
                    "director",
                    "fresh_rewrite_scene_restored",
                    input_summary=decision.rationale[:500],
                    output_summary="restored prior scene after failed rewrite compile",
                    payload={"decision": decision_payload},
                )
            iteration_record.compile_summary = CompileSummary.model_validate(compile_summary)
            if tool_has_blocking_failure(compile_summary):
                target = first_diagnostic_target(compile_summary)
                repair_intent = diagnostic_repair_intent(compile_summary)
                recommendation = json.loads(
                    self.tools.recommend_edit_surface(
                        repair_intent,
                        json.dumps(target),
                    )
                ).get("recommendation", "dsl")
                classification = classify_diagnostics(
                    compile_summary.get("diagnostics", []),
                    target,
                    scene=self.tools.scene,
                    prior_context=block_request.repair_context,
                )
                recommendation = classification.allowed_edit_surface.value
                context = CompileRepairContext(
                    reason="compile_failed",
                    compile_summary=iteration_record.compile_summary,
                    failing_source=source,
                    exact_feedback=json.dumps(compile_summary, indent=2),
                )
                # Keep surgical mode CONTINUOUS: a compile error often carries no
                # node target (its subject is the failing line, not a node), which
                # would otherwise drop us out of surgical enforcement mid-repair.
                # If we were already repairing surgically and the block that just
                # failed was itself modify-only, the fix stays surgical.
                prior_surgical = bool(
                    block_request.repair_context
                    and block_request.repair_context.get("surgical_repair")
                )
                surgical = (
                    classification.repair_class == RepairClass.targeted_node
                    and repair_is_surgical(recommendation, target)
                ) or (
                    prior_surgical and is_surgical_dsl(source)
                )
                if surgical:
                    # A surgical repair is, by definition, a checked in-place edit.
                    recommendation = "structured_ops"
                if surgical and not target.get("node_id"):
                    # Preserve the node we were repairing so enforcement + feedback
                    # keep pointing at it.
                    prior_target = (block_request.repair_context or {}).get(
                        "surgical_target"
                    ) or {}
                    if prior_target.get("node_id"):
                        target = prior_target
                correction = reauthor_correction(compile_summary, self.tools.scene)
                if correction:
                    # Phase 0b guardrail: the block re-authored existing content
                    # (LUMD0401 duplicate id / LUMA0200 page re-declaration) and
                    # was rejected WHOLE. Reroute deterministically as a
                    # corrective, targeted repair — never rely on the model
                    # noticing the pattern on its own. A `duplicate_in_block`
                    # correction stays NON-surgical on purpose: its node does
                    # not exist in the scene, so the fix is a corrected full
                    # re-emit, not modify lines against a phantom target.
                    if correction["kind"] == "node" and correction.get("offending_id"):
                        surgical = True
                        recommendation = "structured_ops"
                        target = {"node_id": correction["offending_id"]}
                    self.tools.record(
                        "coordinator",
                        "reauthor_rerouted",
                        input_summary=correction["code"],
                        output_summary=correction["instruction"][:300],
                        payload={"correction": correction},
                    )
                feedback = {
                    "kind": "compile",
                    "feedback": context.model_dump(mode="json"),
                    "target": target,
                    "recommended_edit_surface": recommendation,
                    "authoring_constraints": authoring_constraints_for(
                        classification,
                        surgical,
                        [
                            "Do not recreate an existing page unless the coordinator explicitly requests a whole-scene replacement.",
                            "Do not re-emit existing node IDs as new elements.",
                            "Repair only the failing line or targeted existing object.",
                        ],
                    ),
                    **repair_class_payload(classification),
                }
                if surgical:
                    feedback["surgical_repair"] = True
                    feedback["surgical_target"] = target
                if correction:
                    feedback["reauthor_correction"] = correction
                    feedback["authoring_constraints"] = [
                        correction["instruction"],
                        *(feedback.get("authoring_constraints") or []),
                    ]
                # Agent-quality: two CONSECUTIVE halts on the same diagnostic
                # code mean the corrective hint alone is not landing
                # (run_8cbeae790f07 burned every iteration on one grammar
                # form). Pin the ref-grammar excerpt into the next author
                # request deterministically — the escalation heuristic from
                # the agent-improvement backlog.
                halt_code = (compile_summary.get("halted_at") or {}).get("code")
                feedback["halt_code"] = halt_code
                prior_feedback = block_request.repair_context or {}
                if halt_code and prior_feedback.get("halt_code") == halt_code:
                    feedback["escalation"] = "repeated_halt"
                    feedback["authoring_constraints"] = [
                        (
                            f"ESCALATION — this is another consecutive {halt_code} "
                            "halt; the previous correction did not land. Follow "
                            "the pinned grammar below EXACTLY and do not repeat "
                            "the failing form."
                        ),
                        DSL_REF_GRAMMAR_ESCALATION,
                        *(feedback.get("authoring_constraints") or []),
                    ]
                    self.tools.record(
                        "coordinator",
                        "repeated_halt_escalated",
                        input_summary=halt_code,
                        output_summary=(
                            "same-code compile halt repeated; ref-grammar "
                            "excerpt pinned into the author request"
                        ),
                        payload={"halt_code": halt_code},
                    )
                repair_request = json.loads(
                    self.tools.create_repair_request(
                        exact_feedback=json.dumps(feedback, indent=2),
                        diagnostics_json=json.dumps(compile_summary.get("diagnostics", [])),
                        target_json=json.dumps(target),
                        allowed_edit_surface=recommendation,
                        forbidden_changes_json=json.dumps(
                            [
                                "do not recreate existing pages",
                                "do not reinsert existing node IDs",
                                "do not remove unrelated existing nodes",
                            ]
                        ),
                        **repair_request_kwargs(classification),
                    )
                )
                feedback["repair_request"] = repair_request.get("repair_request")
                self.previous_feedback.append(feedback)
                iteration_record.stop_reason = StopReason.compile_failed
                continue

            # Compile succeeded: the scene is renderable even if later quality
            # gates (preflight/critic) reject it. Record it as a (weak) keep-best
            # candidate so a subsequent failed repair cannot strip the design from
            # canvas. Preflight-clean / reviewed drafts outrank it below.
            self._track_edited_ids(compile_result.get("operations") or [])
            self._consider_best(stage="compiled", critique=None)

            preflight_result = json.loads(self.tools.preflight_design())
            preflight_summary = preflight_result.get("preflight", {})
            self.state.effective_brand = preflight_result.get("effective_brand")
            iteration_record.preflight_summary = PreflightSummary.model_validate(
                preflight_summary
            )
            # Agent-improvement follow-up 1 (baseline-diff repair scoping): the
            # clean-draft gate blocks ONLY on errors this turn INTRODUCED, never
            # on errors that already existed on the seeded scene before this
            # turn touched it. Without this, a doc with pre-existing legacy
            # errors (e.g. LUMV0810 slot-fixture overflow on frozen/pinned
            # text) wedges every repair iteration re-fixing out-of-scope
            # errors while the user's actual ask never converges
            # (run_4a0feb15048e4fbe993029bd2cab436f).
            all_preflight_diagnostics = preflight_summary.get("diagnostics", [])
            introduced_diagnostics = self._introduced_diagnostics(all_preflight_diagnostics)
            baseline_advisory = self._baseline_advisory(all_preflight_diagnostics)
            self.unaddressed_baseline_diagnostics = baseline_advisory
            introduced_summary = {**preflight_summary, "diagnostics": introduced_diagnostics}
            # K4 NOTE (measured, do not re-add casually): hard-gating the
            # clean-draft check on introduced LUMB08xx findings was tried
            # live and WEDGED the run — 25 raw-token findings, five repair
            # iterations, zero progress (run_bff3433f): the LLM repair path
            # cannot incrementally rebind tokens today. Enforcement needs a
            # DETERMINISTIC retokenization pass (map raw values to the kit
            # tokens they equal) — until that exists, brand debt stays
            # advisory here and is enforced via keep-best ranking, the
            # reviewer's LUMB0805 rejection rule, and the fidelity eval.
            if tool_has_blocking_failure(introduced_summary) or has_blocking_diagnostics(
                introduced_diagnostics
            ):
                debug_preview = json.loads(
                    self.tools.export_preview_bundle(
                        debug_only=True,
                        debug_reason="preflight_failed",
                    )
                )
                debug_export_summary = debug_preview.get("reviewer", {})
                if debug_export_summary:
                    iteration_record.export_summary = ExportSummary.model_validate(
                        debug_export_summary
                    )
                target = first_diagnostic_target(introduced_summary)
                repair_intent = diagnostic_repair_intent(introduced_summary)
                recommendation = json.loads(
                    self.tools.recommend_edit_surface(
                        repair_intent,
                        json.dumps(target),
                    )
                ).get("recommendation", "dsl")
                classification = classify_diagnostics(
                    introduced_diagnostics,
                    target,
                    scene=self.tools.scene,
                    prior_context=block_request.repair_context,
                )
                recommendation = classification.allowed_edit_surface.value
                surgical = (
                    classification.repair_class == RepairClass.targeted_node
                    and repair_is_surgical(recommendation, target)
                )
                feedback = {
                    "kind": "preflight",
                    "feedback": introduced_summary,
                    "debug_preview": debug_export_summary,
                    "target": target,
                    "recommended_edit_surface": recommendation,
                    "authoring_constraints": authoring_constraints_for(
                        classification,
                        surgical,
                        [
                            "Do not recreate an existing page unless full_replace is explicitly requested.",
                            "Do not re-emit existing node IDs as new elements.",
                            "Repair only the targeted node/page/slot when a target is present.",
                            "If structured operations are unavailable in this authoring step, emit the smallest DSL continuation that avoids duplicate IDs.",
                        ],
                    ),
                    **repair_class_payload(classification),
                }
                if baseline_advisory:
                    # The repair prompt must never be told to fix baseline
                    # errors — they are handed to the author only as advisory
                    # context, never as part of what to repair.
                    feedback["baseline_advisory"] = {
                        "count": len(baseline_advisory),
                        "diagnostics": baseline_advisory,
                        "note": (
                            f"{len(baseline_advisory)} pre-existing issue(s) on this "
                            "document were not addressed — they predate this turn "
                            "and are out of scope; do not spend the repair budget "
                            "on them unless the user explicitly asks."
                        ),
                    }
                if surgical:
                    feedback["surgical_repair"] = True
                    feedback["surgical_target"] = target
                repair_request = json.loads(
                    self.tools.create_repair_request(
                        exact_feedback=json.dumps(feedback, indent=2),
                        diagnostics_json=json.dumps(introduced_diagnostics),
                        target_json=json.dumps(target),
                        allowed_edit_surface=recommendation,
                        forbidden_changes_json=json.dumps(
                            [
                                "do not recreate existing pages",
                                "do not reinsert existing node IDs",
                                "do not remove unrelated existing nodes",
                                "do not change page dimensions unless the diagnostic targets the page size",
                            ]
                        ),
                        **repair_request_kwargs(classification),
                    )
                )
                feedback["repair_request"] = repair_request.get("repair_request")
                self.previous_feedback.append(feedback)
                iteration_record.stop_reason = StopReason.preflight_failed
                continue

            # Preflight is CLEAN for gating purposes (no errors this turn
            # introduced), even if pre-existing baseline errors remain. Those
            # ride along as advisory — never re-checked here, never blocking.

            # Preflight passed: this draft is renderable AND valid — a strictly
            # better keep-best candidate than a compile-only draft. Advisory
            # brand-governance findings (LUMB08xx) count as debt so a draft
            # that "cleaned up" by unbinding kit tokens never outranks one
            # that kept them.
            brand_debt = sum(
                1
                for d in all_preflight_diagnostics
                if str(d.get("code") or "").startswith("LUMB08")
            )
            # A draft that never placed the kit's logo outranks nothing: a
            # logo-carrying iteration beats it even against a few advisory
            # token warnings (5 ≈ the largest observed LUMB08 spread).
            if self._scene_lacks_kit_logo():
                brand_debt += 5
            self._consider_best(
                stage="preflight_clean", critique=None, brand_debt=brand_debt
            )

            # Accommodation edits: measure turn-introduced crowding on this
            # laid-out draft BEFORE the critic runs, so the critic judges the
            # conflicts (it missed exactly this at confidence 0.9 in
            # run_e0bb1733) and a subsequent repair may nudge the named
            # neighbors. Detection is geometric; judgment stays with the
            # critic and the author.
            self._detect_accommodation_conflicts()

            # Quality is judged on PIXELS: always render a PNG for the critic so the
            # visual reviewer inspects the rendered image, not SVG geometry, even
            # when the configured preview format is SVG.
            export_result = json.loads(
                self.tools.export_preview_bundle(critic_format="png")
            )
            export_summary = export_result.get("critic", {})
            iteration_record.export_summary = ExportSummary.model_validate(export_summary)
            if tool_has_blocking_failure(export_summary):
                iteration_record.stop_reason = StopReason.preview_invalid
                self.state.status = "failed"
                self.state.stop_reason = StopReason.preview_invalid
                return self._finalize_failed(
                    StopReason.preview_invalid.value,
                    "Preview export failed validation.",
                )
            target_errors = preview_target_errors(
                export_summary,
                block_request.preview_target or PreviewTarget(),
            )
            if target_errors:
                self.tools.record(
                    "coordinator",
                    "preview_invalid",
                    output_summary="; ".join(target_errors),
                    payload={
                        "target_errors": target_errors,
                        "preview_target": (
                            block_request.preview_target.model_dump(mode="json")
                            if block_request.preview_target
                            else {}
                        ),
                        "export": export_summary,
                    },
                )
                self.tools.record_gap(
                    "rendering_export_preview",
                    "Preview dimensions do not match requested artifact constraints",
                    "; ".join(target_errors),
                    "Phase A",
                )
                iteration_record.stop_reason = StopReason.preview_invalid
                self.state.status = "failed"
                self.state.stop_reason = StopReason.preview_invalid
                return self._finalize_failed(
                    StopReason.preview_invalid.value,
                    "Preview dimensions did not match requested artifact constraints.",
                )

            preview_payload = json.loads(self.tools.get_latest_preview_for_critique())
            if preview_payload.get("status") == "error":
                return self._finalize_failed(
                    StopReason.preview_invalid.value,
                    preview_payload.get("message", "Preview payload unavailable."),
                )

            # Phase 3c imagery gate: on a scene with generated/edited imagery, run the
            # verifier at the PNG-render seam (DET always; the judge vision call only
            # when an agent key is configured). Its hard-gate failures ride into the
            # reviewer's context so a baked-text / illegible / mis-fit image the
            # geometry-only critic would wave through is caught, and the loop-executed
            # imagery repair (below) has an explicit signal.
            self.imagery_verdict = None
            if self.tools.scene_has_generated_imagery():
                self.imagery_verdict = json.loads(self.tools.verify_imagery())
                preview_payload["imagery_verdict"] = self.imagery_verdict

            try:
                reviewer_full_context = self.tools.curated_context(
                    user_request=user_request,
                    previous_feedback=self.previous_feedback,
                    director_decisions=self.director_decisions,
                )
                critique = self.reviewer.review(
                    user_request=user_request,
                    scene_summary=json.loads(self.tools.summarize_scene()),
                    export_summary=export_summary,
                    preview_payload=preview_payload,
                    knowledge=knowledge.get("snippets", []),
                    previous_feedback=self.previous_feedback,
                    full_context=reviewer_full_context,
                )
            except Exception as error:
                critique_failure = json.loads(
                    self.tools.submit_visual_critique(
                        json.dumps({"provider_error": str(error)})
                    )
                )
                iteration_record.stop_reason = StopReason.critic_failed
                self.state.status = "failed"
                self.state.stop_reason = StopReason.critic_failed
                return self._finalize_failed(
                    StopReason.critic_failed.value,
                    f"Visual reviewer failed: {error}",
                    critique_json=json.dumps(critique_failure),
                )
            self.tools.submit_visual_critique(critique.model_dump_json())
            iteration_record.critique = critique
            # Rank this fully-reviewed draft. The highest-scoring one is what we
            # hand back if no iteration is ever accepted.
            self._consider_best(
                stage="preflight_clean", critique=critique, brand_debt=brand_debt
            )
            if critique.accepted and self._should_force_accommodation_round():
                # The pixel critic accepted OVER an unresolved turn-introduced
                # conflict. Swap in a synthetic rejection carrying the nudge
                # instruction so the ordinary repair plumbing below runs one
                # bounded accommodation round; keep-best already ranked the
                # accepted draft, so a failed round still returns it.
                critique = self._forced_accommodation_critique(critique)
            elif critique.accepted and self._should_force_logo_round():
                # The critic accepted a logo-less draft on a kit that provides
                # logo assets — the measured 5/10 adoption gap. One bounded
                # placement round; a failed round still returns the accepted
                # draft via keep-best.
                critique = self._forced_logo_critique(critique)
            if critique.accepted:
                iteration_record.stop_reason = StopReason.accepted
                self.state.status = "accepted"
                self.state.stop_reason = StopReason.accepted
                return json.loads(
                    self.tools.finalize_run(
                        "accepted",
                        StopReason.accepted.value,
                        critique.summary,
                        critique_json=critique.model_dump_json(),
                        baseline_advisory_json=self._baseline_advisory_payload_json(),
                        accommodation_json=self._accommodation_payload_json(),
                    )
                )

            # Phase 0b edit-scoped acceptance: on a seeded turn, when the
            # requested edit has compiled and preflighted clean (we are past
            # both gates here) and no BLOCKING critique issue targets content
            # this turn touched, the whole-design rejection must not hold the
            # user's edit hostage. Accept at edit scope; the critique rides
            # along as advisory. Error/blocker issues targeting an edited node
            # (or anything it contains) still block and repair as before —
            # warnings/info are advisory by severity even on edited nodes (the
            # 0b e2e showed a pre-existing "could dominate more" warning on the
            # edited headline forcing a needless extra director round).
            if self.tools.seeded_from_initial_scene and (
                self.edited_node_ids or self.edited_page_ids
            ):
                # Accommodation edits: neighbors this turn newly crowds are
                # in scope too — a blocking critique on the crowded neighbor
                # must be able to block, or the mechanism that protects edits
                # from pre-existing complaints would wave through damage the
                # edit itself caused.
                scope_node_ids = (
                    self._edited_scope_node_ids() | self._accommodation_scope_node_ids()
                )
                in_scope_issues = [
                    issue
                    for issue in critique.issues
                    if issue.severity
                    in {DiagnosticSeverity.blocker, DiagnosticSeverity.error}
                    and issue_in_edit_scope(issue, scope_node_ids, self.edited_page_ids)
                ]
                if not in_scope_issues:
                    iteration_record.stop_reason = StopReason.edit_scoped_acceptance
                    self.state.status = "edit_applied"
                    self.state.stop_reason = StopReason.edit_scoped_acceptance
                    self.tools.record(
                        "director",
                        "edit_scoped_acceptance",
                        output_summary=(
                            "requested edit applied and verified; "
                            f"{len(critique.issues)} whole-design critique "
                            "issue(s) are advisory (no blocking issue targets "
                            "this turn's edits)"
                        ),
                        payload={
                            "edited_node_ids": sorted(self.edited_node_ids),
                            "edited_page_ids": sorted(self.edited_page_ids),
                            "advisory_issue_count": len(critique.issues),
                        },
                    )
                    return json.loads(
                        self.tools.finalize_run(
                            "edit_applied",
                            StopReason.edit_scoped_acceptance.value,
                            "Requested edit applied and verified (compile + "
                            "preflight clean). Remaining whole-design critique "
                            "is advisory and targets content this turn did not "
                            "modify.",
                            critique_json=critique.model_dump_json(),
                            ops_valid_through_iteration=self.state.current_iteration,
                            baseline_advisory_json=self._baseline_advisory_payload_json(),
                            accommodation_json=self._accommodation_payload_json(),
                        )
                    )

            # Phase 3c: a PURE-imagery rejection over a generated/edited image is the
            # loop's to repair — the DSL author has no image tools. Execute one
            # in-place edit (or regenerate) BEFORE the next author round; the repaired
            # scene carries forward and is re-reviewed next iteration. Bounded to one
            # per run (mirrors the accommodation forced round) so it can never wedge.
            imagery_repaired = self._maybe_execute_imagery_repair(critique)

            # K4 logo adoption, rejected path: the accept-intercept alone
            # measured 1/10 ship — most runs exhaust budget without any
            # acceptance, so the placement fact must ride EVERY repair round.
            # Appended LAST: the critic's own top issue keeps driving the
            # target and classification; this rider just makes the same
            # repair round also place the logo (one op — the event-poster
            # gate round proved the model does it reliably when told).
            if self._scene_lacks_kit_logo():
                critique.issues.append(self._logo_missing_issue())
            feedback = {
                "kind": "visual",
                "feedback": critique.model_dump(mode="json"),
            }
            if imagery_repaired:
                feedback["loop_executed_imagery_repair"] = True
            self.previous_feedback.append(feedback)
            target = first_issue_target(critique)
            recommendation = json.loads(
                self.tools.recommend_edit_surface(
                    critique.repair_instruction or critique.summary,
                    json.dumps(target),
                )
            ).get("recommendation", "dsl")
            classification = classify_visual_critique(critique, target, self.tools.scene)
            recommendation = classification.allowed_edit_surface.value
            feedback.update(repair_class_payload(classification))
            repair_request = json.loads(
                self.tools.create_repair_request(
                    exact_feedback=json.dumps(feedback, indent=2),
                    target_json=json.dumps(target),
                    allowed_edit_surface=recommendation,
                    forbidden_changes_json=json.dumps(
                        ["do not remove unrelated existing nodes"]
                    ),
                    **repair_request_kwargs(classification),
                )
            )
            feedback["repair_request"] = repair_request.get("repair_request")
            iteration_record.stop_reason = StopReason.reviewer_rejected

        # Repair budget exhausted. If we captured a preflight-clean draft — a valid
        # design that simply never won an explicit visual acceptance within the
        # budget — hand it back as `completed_with_warnings` rather than a hard
        # failure: the editor should surface the best draft, not an error state.
        # Only a run that never reached a clean draft is a genuine failure. Either
        # way the best renderable scene is restored so the canvas is never wiped.
        self.state.stop_reason = StopReason.max_iterations_reached
        last_feedback = self.previous_feedback[-1] if self.previous_feedback else {}
        best_is_preflight_clean = bool(self.best_rank and self.best_rank[0] == 1)
        if best_is_preflight_clean:
            self._restore_best_scene()
            if self.tools.seeded_from_initial_scene and (
                self.edited_node_ids or self.edited_page_ids
            ):
                # Phase 0b: on a seeded turn the verified, preflight-clean edit
                # must reach the editor even at budget exhaustion — 0a's run 1
                # showed the ops being stripped despite the edit having landed.
                # Ops are valid only through the restored best iteration.
                self.state.status = "edit_applied"
                return json.loads(
                    self.tools.finalize_run(
                        "edit_applied",
                        StopReason.max_iterations_reached.value,
                        "Repair budget reached. The requested edit is applied in "
                        "the best preflight-clean draft; remaining visual "
                        "critique is advisory.",
                        critique_json=json.dumps(
                            self._latest_visual_critique_payload()
                        ),
                        ops_valid_through_iteration=self.best_iteration,
                        baseline_advisory_json=self._baseline_advisory_payload_json(),
                        accommodation_json=self._accommodation_payload_json(),
                    )
                )
            self.state.status = "completed_with_warnings"
            return json.loads(
                self.tools.finalize_run(
                    "completed_with_warnings",
                    StopReason.max_iterations_reached.value,
                    "Repair budget reached. Returned the best preflight-clean draft, "
                    "which was not explicitly accepted by the visual reviewer.",
                    critique_json=json.dumps(last_feedback),
                    ops_valid_through_iteration=self.best_iteration,
                    baseline_advisory_json=self._baseline_advisory_payload_json(),
                    accommodation_json=self._accommodation_payload_json(),
                )
            )
        self.state.status = "failed"
        return self._finalize_failed(
            StopReason.max_iterations_reached.value,
            "Maximum Phase A repair iterations reached without a clean draft.",
            critique_json=json.dumps(last_feedback),
        )

    def _track_edited_ids(self, operations: list) -> None:
        """Accumulate the node/page ids touched by APPLIED operations (Phase 0b).

        This is the edit scope that edit-scoped acceptance judges critique
        issues against. Ids come from the checked core operations, not the DSL
        text, so the scope reflects what actually changed."""
        for op in operations:
            if not isinstance(op, dict):
                continue
            node_id = op.get("node_id")
            if isinstance(node_id, str) and node_id:
                self.edited_node_ids.add(node_id)
            node = op.get("node")
            if isinstance(node, dict) and isinstance(node.get("id"), str):
                self.edited_node_ids.add(node["id"])
            page = op.get("page")
            if isinstance(page, dict) and isinstance(page.get("id"), str):
                self.edited_page_ids.add(page["id"])
            page_id = op.get("page_id")
            if isinstance(page_id, str) and page_id:
                self.edited_page_ids.add(page_id)

    def _edited_scope_node_ids(self) -> set:
        """Edited node ids plus their CURRENT descendants.

        An edit to a container legitimately owns critique on what it contains;
        pre-existing siblings and ancestors stay out of scope (an ancestor
        inclusion would let any pre-existing page-level complaint block every
        targeted edit — the exact failure edit-scoped acceptance removes)."""
        return self._with_descendants(set(self.edited_node_ids))

    def _introduced_diagnostics(self, diagnostics: list[dict]) -> list[dict]:
        """Diagnostics from THIS turn's gate that are NOT in the baseline.

        Agent-improvement follow-up 1: a diagnostic counts as baseline (and is
        dropped here) only when its (code, subject) key was already present on
        the seeded scene BEFORE this turn's first edit. A baseline error that
        MOVED to a new subject (e.g. the same slot-fixture overflow code now
        keyed to a different node) is a different key and so counts as
        introduced — it is not the same error, it is a new occurrence. A
        baseline error that simply disappeared needs no handling here; it is
        just absent from `diagnostics`, which is fine (an improvement)."""
        if not self.baseline_diagnostic_keys:
            return list(diagnostics)
        return [
            diag
            for diag in diagnostics
            if not isinstance(diag, dict)
            or _diagnostic_key(diag) not in self.baseline_diagnostic_keys
        ]

    def _baseline_advisory(self, diagnostics: list[dict]) -> list[dict]:
        """The subset of `diagnostics` that ARE baseline (pre-existing, out of
        this turn's scope) — the complement of `_introduced_diagnostics`, used
        to surface "N pre-existing issues were not addressed" advisories
        instead of silently dropping them."""
        if not self.baseline_diagnostic_keys:
            return []
        return [
            diag
            for diag in diagnostics
            if isinstance(diag, dict) and _diagnostic_key(diag) in self.baseline_diagnostic_keys
        ]

    def _baseline_advisory_payload_json(self) -> str:
        """The turn-result advisory payload for `finalize_run`: pre-existing
        baseline issues that were never addressed this turn (agent-improvement
        follow-up 1). `"null"` when there is nothing to advise — either an
        unseeded run or every baseline issue happened to be resolved anyway."""
        if not self.unaddressed_baseline_diagnostics:
            return "null"
        return json.dumps(
            {
                "count": len(self.unaddressed_baseline_diagnostics),
                "diagnostics": self.unaddressed_baseline_diagnostics,
                "note": (
                    f"{len(self.unaddressed_baseline_diagnostics)} pre-existing "
                    "issue(s) on this document were not addressed — they predate "
                    "this turn."
                ),
            }
        )

    def _detect_accommodation_conflicts(self) -> None:
        """Refresh `accommodation_conflicts` for the current laid-out draft.

        A conflict is TURN-INTRODUCED crowding: an edited node now sits closer
        than the calibrated threshold to a neighbor it cleared at baseline
        (ancestors/descendants excluded, neighbor rolled up to its topmost
        conflicting container — the correct nudge unit). When conflicts exist,
        they are appended to `previous_feedback` so both the visual reviewer
        (this iteration) and any repair author (next iteration) see them with
        the accommodation rule attached."""
        self.accommodation_conflicts = []
        if not (
            self.tools.seeded_from_initial_scene
            and isinstance(self.baseline_scene, dict)
            and self.edited_node_ids
            and isinstance(self.tools.scene, dict)
        ):
            return
        conflicts = turn_introduced_conflicts(
            self.baseline_scene, self.tools.scene, set(self.edited_node_ids)
        )
        self.accommodation_conflicts = conflicts
        for conflict in conflicts:
            key = (conflict.get("edited"), conflict.get("neighbor"))
            self.accommodation_conflict_log.setdefault(key, conflict)
        if not conflicts:
            return
        self.tools.record(
            "coordinator",
            "accommodation_conflicts",
            output_summary=(
                f"{len(conflicts)} turn-introduced crowding conflict(s): "
                + "; ".join(
                    f"{c['edited']}↔{c['neighbor']} ({c['clearance']:.0f}pt)"
                    for c in conflicts
                )
            ),
            payload={"conflicts": conflicts},
        )
        self.previous_feedback.append(
            {
                "kind": "mechanical_crowding",
                "feedback": {
                    "conflicts": conflicts,
                    "note": (
                        "Geometrically measured: this turn's edit newly crowds "
                        "neighbors that were clear before (clearance in pt; "
                        "negative = overlap). ACCOMMODATION RULE — you MAY move "
                        "each named neighbor with a position-only `#<id> p(x,y)` "
                        "nudge: the smallest move that restores at least 16pt "
                        "clearance. Never restyle, resize, delete, or reorder an "
                        "accommodated neighbor, never touch nodes not listed, "
                        "and record each nudge as a `// collateral:` comment line in your block. If the crowding "
                        "is what the user explicitly asked for, leave it and "
                        "say so."
                    ),
                },
            }
        )

    def _should_force_accommodation_round(self) -> bool:
        """Whether an acceptance must yield to ONE accommodation repair round.

        A sub-16pt gap or hairline overlap is a geometric fact the pixel
        critic cannot reliably see: run_7ff4ac79 accepted a -0.31pt
        badge↔organizer overlap at confidence 0.9 with a false "visible
        vertical space" acceptance note — exactly the run_e0bb1733 failure
        this feature exists for. When conflicts stand at acceptance time,
        the geometric signal outranks pixel judgment — once. Bounded by
        design: at most one forced round per run, and only while an
        iteration remains, so a turn can never wedge on it; if the nudge
        round fails, the accepted draft still returns via keep-best (as
        completed_with_warnings, conflict honestly advisory)."""
        return bool(
            self.accommodation_conflicts
            and not self.accommodation_repair_attempted
            and self.state.current_iteration < self.tools.config.max_iterations
        )

    def _accommodation_repair_instruction(self, conflict: dict) -> str:
        """A precise, boxed nudge instruction for one conflict.

        run_e3bbb02e's forced round failed on model precision, not intent: it
        nudged using the LABEL's box instead of the container's and drifted
        +46pt sideways off the artboard. So the instruction now carries the
        neighbor's and edited node's CURRENT page-space boxes, tells the model
        to move along one axis only by the minimal amount, and to keep the
        node fully on the artboard."""
        nodes = (self.tools.scene or {}).get("nodes") or {}
        neighbor_node = nodes.get(conflict["neighbor"])
        edited_node = nodes.get(conflict["edited"])
        neighbor_box = page_space_box(neighbor_node) if neighbor_node else None
        edited_box = page_space_box(edited_node) if edited_node else None
        deficit = max(0.0, CONFLICT_CLEARANCE_THRESHOLD - conflict["clearance"])
        boxes = ""
        if neighbor_box and edited_box:
            boxes = (
                f" {conflict['neighbor']} currently occupies page-space "
                f"({neighbor_box['x']:.0f},{neighbor_box['y']:.0f},"
                f"{neighbor_box['width']:.0f},{neighbor_box['height']:.0f}); "
                f"{conflict['edited']} occupies "
                f"({edited_box['x']:.0f},{edited_box['y']:.0f},"
                f"{edited_box['width']:.0f},{edited_box['height']:.0f})."
            )
        return (
            f"Nudge {conflict['neighbor']} with a position-only "
            f"`#{conflict['neighbor']} p(x,y)` — move it along ONE axis only, "
            f"directly away from {conflict['edited']}, by about "
            f"{deficit + 2.0:.0f}pt (just enough for 16pt clearance)."
            f"{boxes} Use the CONTAINER's own box above (not a child label's), "
            "keep the node fully inside the artboard, and do not restyle, "
            "resize, delete, or reorder it."
        )

    def _kit_logo_asset_ids(self) -> set:
        """Asset ids of the attached kit's logo variants (empty when no kit
        is genuinely attached — the platform default never reaches config)."""
        kit = self.tools.config.brand_kit
        if not isinstance(kit, dict):
            return set()
        ids = set()
        for logo in ((kit.get("assets") or {}).get("logos") or {}).values():
            if not isinstance(logo, dict):
                continue
            for variant in logo.get("variants") or []:
                if isinstance(variant, dict) and variant.get("asset_id"):
                    ids.add(str(variant["asset_id"]))
        return ids

    def _should_force_logo_round(self) -> bool:
        """Whether an acceptance must yield to ONE logo-placement round.

        The K4 sweep measured logo adoption at 5/10 with typography/palette
        near-perfect: the pixel critic reliably accepts a brand-clean design
        that simply never placed the kit's logo. When the kit provides logo
        assets and the scene places none, the inventory fact outranks pixel
        judgment — once. Bounded exactly like the accommodation round: at
        most one forced round per run, only while an iteration remains, and
        a failed round still returns the accepted draft via keep-best."""
        logo_ids = self._kit_logo_asset_ids()
        if not logo_ids or self.logo_repair_attempted:
            return False
        if self.state.current_iteration >= self.tools.config.max_iterations:
            return False
        return self._scene_lacks_kit_logo()

    def _scene_lacks_kit_logo(self) -> bool:
        logo_ids = self._kit_logo_asset_ids()
        if not logo_ids:
            return False
        nodes = (self.tools.scene or {}).get("nodes") or {}
        for node in nodes.values():
            kind = (node or {}).get("kind")
            if (
                isinstance(kind, dict)
                and kind.get("kind") == "image"
                and str(kind.get("asset_id")) in logo_ids
            ):
                return False
        return True

    def _logo_missing_issue(self) -> VisualIssue:
        kit = self.tools.config.brand_kit or {}
        logos = (kit.get("assets") or {}).get("logos") or {}
        suggestion = None
        for slot in ("mark", "primary", "wordmark"):
            for variant in (logos.get(slot) or {}).get("variants") or []:
                if isinstance(variant, dict) and variant.get("asset_id"):
                    suggestion = (slot, str(variant["asset_id"]))
                    break
            if suggestion:
                break
        slot_name, asset_id = suggestion or ("mark", sorted(self._kit_logo_asset_ids())[0])
        return VisualIssue(
            severity=DiagnosticSeverity.error,
            category="brand_fit",
            target=VisualTarget(node_id=None),
            message=(
                "Inventory fact: the attached Brand Kit provides logo assets and "
                "no image node in the scene references any of them."
            ),
            suggested_repair=(
                f"While making the requested repair, ALSO place the kit's {slot_name} "
                f"logo: add an `image asset({asset_id})` element (the compiler "
                "auto-registers kit assets) in the header/top region, sized per the "
                "kit's logo rules (min_size, variant per background)."
            ),
        )

    def _forced_logo_critique(self, accepted: VisualCritique) -> VisualCritique:
        """The synthetic rejection that drives the forced logo round."""
        self.logo_repair_attempted = True
        kit = self.tools.config.brand_kit or {}
        logos = (kit.get("assets") or {}).get("logos") or {}
        # Prefer the mark (smallest safe footprint) then the primary lockup.
        suggestion = None
        for slot in ("mark", "primary", "wordmark"):
            for variant in (logos.get(slot) or {}).get("variants") or []:
                if isinstance(variant, dict) and variant.get("asset_id"):
                    suggestion = (slot, str(variant["asset_id"]))
                    break
            if suggestion:
                break
        slot_name, asset_id = suggestion or ("mark", sorted(self._kit_logo_asset_ids())[0])
        repair = (
            f"Place the Brand Kit's {slot_name} logo: add an `image asset({asset_id})` "
            "element (the compiler auto-registers kit assets) in the header/top "
            "region of the artboard, sized per the kit's logo rules "
            "(min_size, variant appropriate to the background — see "
            "brand-application). Do not restyle or move any other node."
        )
        issue = self._logo_missing_issue()
        issue.suggested_repair = repair
        forced = VisualCritique(
            accepted=False,
            summary=(
                "Visual acceptance withheld for one logo-placement round: the "
                "attached Brand Kit provides logo assets and this design places "
                "none — brand presence is part of the brief."
            ),
            issues=[issue],
            confidence=1.0,
        )
        return forced

    def _forced_accommodation_critique(self, accepted: VisualCritique) -> VisualCritique:
        """The synthetic rejection that drives the forced accommodation round."""
        self.accommodation_repair_attempted = True
        issues = [
            VisualIssue(
                severity=DiagnosticSeverity.error,
                category="spacing",
                target=VisualTarget(node_id=conflict["neighbor"]),
                message=(
                    f"Geometrically measured: this turn's edit to "
                    f"{conflict['edited']} left {conflict['neighbor']} at "
                    f"{conflict['clearance']:.1f}pt clearance "
                    f"({'overlapping' if conflict.get('overlap') else 'under the 16pt minimum'}) "
                    "— crowding that did not exist before this turn."
                ),
                suggested_repair=self._accommodation_repair_instruction(conflict),
            )
            for conflict in self.accommodation_conflicts
        ]
        forced = VisualCritique(
            accepted=False,
            summary=(
                "Visual acceptance withheld for one accommodation round: "
                "turn-introduced crowding is unresolved ("
                + "; ".join(
                    f"{c['edited']}↔{c['neighbor']} {c['clearance']:.1f}pt"
                    for c in self.accommodation_conflicts
                )
                + "). Nudge the named neighbor(s), position-only."
            ),
            issues=issues,
            repair_instruction=issues[0].suggested_repair if issues else None,
            confidence=1.0,
        )
        self.tools.record(
            "coordinator",
            "accommodation_repair_forced",
            output_summary=(
                "critic accepted over unresolved turn-introduced crowding; "
                "forcing one accommodation repair round"
            ),
            payload={
                "conflicts": self.accommodation_conflicts,
                "overridden_acceptance_summary": accepted.summary,
                "overridden_confidence": accepted.confidence,
            },
        )
        return forced

    def _pure_imagery_repair_node(self, critique: VisualCritique) -> Optional[str]:
        """The node id an imagery repair should target, or None when the critique is
        not a PURE-imagery critique over a generated/edited image.

        Pure = every categorized issue is in IMAGERY_CATEGORIES and none is a
        structural-layout category (those are fixed by geometry first). The target
        must be an image node whose asset was generated or edited — a library image or
        a typographic critique is not the loop's to auto-repair."""
        categories = {
            str(issue.category.value if hasattr(issue.category, "value") else issue.category)
            for issue in critique.issues
        }
        if not categories:
            return None
        if not (categories <= IMAGERY_CATEGORIES):
            return None
        scene = self.tools.scene or {}
        assets = scene.get("assets") or {}
        nodes = scene.get("nodes") or {}
        for issue in critique.issues:
            node_id = issue.target.node_id if issue.target else None
            if not node_id:
                continue
            node = nodes.get(node_id) or {}
            asset_id = (node.get("kind") or {}).get("asset_id")
            if not asset_id:
                continue
            source_kind = ((assets.get(asset_id) or {}).get("source") or {}).get("kind")
            if source_kind in ("generated", "edited"):
                return node_id
        return None

    @staticmethod
    def _imagery_repair_is_regenerate(text: str) -> bool:
        """Whether the critique text calls for a full regenerate (wrong subject /
        still a placeholder) rather than an in-place edit (recolor / warmth / bg /
        fix a flawed subject). Defaults to edit_image — the cheaper, composition-
        preserving repair — unless the text signals a wrong/placeholder image."""
        lowered = (text or "").lower()
        regenerate_signals = ("wrong subject", "wrong image", "placeholder", "irrelevant", "off-brief subject")
        return any(signal in lowered for signal in regenerate_signals)

    def _maybe_execute_imagery_repair(self, critique: VisualCritique) -> bool:
        """Phase 3c: when a rejection is a PURE-imagery critique over a generated/
        edited image, the LOOP executes the repair before the next author round — at
        most ONCE per run (the DSL author stays barred from image tools). Returns True
        when a repair was executed. Bounded exactly like the accommodation forced
        round: one attempt, and only while an iteration remains, so it can never wedge."""
        if self.imagery_repair_attempted:
            return False
        if self.state.current_iteration >= self.tools.config.max_iterations:
            return False
        node_id = self._pure_imagery_repair_node(critique)
        if node_id is None:
            return False
        self.imagery_repair_attempted = True
        instruction = critique.repair_instruction or critique.summary or ""
        # Prefer the targeting issue's own repair text when present.
        for issue in critique.issues:
            if issue.target and issue.target.node_id == node_id:
                instruction = issue.suggested_repair or issue.message or instruction
                break
        if self._imagery_repair_is_regenerate(instruction):
            # Wrong subject / placeholder → full regenerate + re-place into the node.
            gen = json.loads(self.tools.generate_image(instruction, target_node_id=node_id))
            action = "regenerate"
            new_asset_id = (gen.get("image") or {}).get("asset_id")
            ok = (gen.get("image") or {}).get("status") == "ok"
            if ok and new_asset_id:
                place = json.loads(self.tools.place_asset_in_node(node_id, new_asset_id))
                ok = (place.get("placement") or {}).get("status") == "ok"
            result = {"generate": gen}
        else:
            # Right-but-flawed → edit in place (preserves the composition).
            remove_bg = "background" in (instruction or "").lower() and (
                "remove" in instruction.lower() or "transparent" in instruction.lower()
            )
            edit = json.loads(
                self.tools.edit_image(node_id, instruction, remove_background=remove_bg)
            )
            action = "edit_image"
            ok = (edit.get("image_edit") or {}).get("status") == "ok"
            result = {"edit": edit}
        self.tools.record(
            "coordinator",
            "imagery_repair_executed",
            output_summary=(
                f"loop-executed imagery repair on {node_id} via {action} "
                f"({'ok' if ok else 'failed'})"
            ),
            payload={"node_id": node_id, "action": action, "ok": bool(ok), **result},
        )
        return bool(ok)

    def _accommodation_scope_node_ids(self) -> set:
        """Crowded neighbors (+ their descendants) count as this turn's scope.

        Edit-scoped acceptance exists so PRE-EXISTING whole-design complaints
        can't hold a targeted edit hostage — but crowding the turn itself
        created is the turn's business, so a blocking critique that targets
        the crowded neighbor must be able to block."""
        seeds = {c["neighbor"] for c in self.accommodation_conflicts}
        return self._with_descendants(seeds)

    def _with_descendants(self, seeds: set) -> set:
        scope = set(seeds)
        nodes = (self.tools.scene or {}).get("nodes") or {}
        stack = list(scope)
        while stack:
            node = nodes.get(stack.pop())
            for child in (node or {}).get("children") or []:
                if child not in scope:
                    scope.add(child)
                    stack.append(child)
        return scope

    def _final_unresolved_conflicts(self) -> list[dict]:
        """The logged conflict pairs re-measured on the FINAL scene.

        `accommodation_conflicts` (the latest detection) can describe a draft
        that is NOT the one being returned: run_e3bbb02e's forced-round draft
        resolved the crowding but was rejected for clipping, keep-best
        restored the earlier accepted draft — and the stale latest list
        reported `unresolved: []` over a scene still carrying the 7.7pt
        conflict. Direct re-measurement of the known pairs on whatever scene
        finalize is actually returning cannot go stale, and sidesteps the
        both-edited pair exclusion (a discarded nudge marks the neighbor
        edited without its edit surviving)."""
        nodes = (self.tools.scene or {}).get("nodes") or {}
        unresolved = []
        for (edited, neighbor), first_seen in self.accommodation_conflict_log.items():
            edited_box = page_space_box(nodes[edited]) if nodes.get(edited) else None
            neighbor_box = page_space_box(nodes[neighbor]) if nodes.get(neighbor) else None
            if not edited_box or not neighbor_box:
                continue
            gap = clearance(edited_box, neighbor_box)
            if gap < CONFLICT_CLEARANCE_THRESHOLD:
                unresolved.append(
                    {**first_seen, "clearance": gap, "overlap": gap < 0}
                )
        return unresolved

    def _accommodation_payload_json(self) -> str:
        """The run-result announcement: conflicts detected + nudges applied.

        Applied nudges diff each ever-conflicting neighbor's geometry against
        the baseline — computed from the LOG, not the latest detection, because
        a successful accommodation repair empties the latest list while being
        exactly the thing worth announcing. `unresolved` re-measures the
        logged pairs on the final scene (see _final_unresolved_conflicts).
        Every finalize path restores/settles the returned scene BEFORE calling
        this, so both diffs read the geometry the editor actually receives."""
        if not self.accommodation_conflict_log:
            return "null"
        nodes_now = (self.tools.scene or {}).get("nodes") or {}
        nodes_then = (self.baseline_scene or {}).get("nodes") or {}
        applied_nudges = []
        for _, neighbor in self.accommodation_conflict_log:
            then = nodes_then.get(neighbor)
            now = nodes_now.get(neighbor)
            box_then = page_space_box(then) if then else None
            box_now = page_space_box(now) if now else None
            if not box_then or not box_now:
                continue
            dx = round(box_now["x"] - box_then["x"], 2)
            dy = round(box_now["y"] - box_then["y"], 2)
            if dx or dy:
                applied_nudges.append({"node": neighbor, "dx": dx, "dy": dy})
        return json.dumps(
            {
                "detected": list(self.accommodation_conflict_log.values()),
                "applied_nudges": applied_nudges,
                "unresolved": self._final_unresolved_conflicts(),
                "note": (
                    "Turn-introduced crowding, measured geometrically. "
                    "applied_nudges are accommodation moves this turn made to "
                    "neighbors of its own edit; unresolved conflicts remain on "
                    "the final draft."
                ),
            }
        )

    def _latest_visual_critique_payload(self) -> dict:
        """The most recent visual critique payload, for advisory surfacing."""
        for entry in reversed(self.previous_feedback):
            if isinstance(entry, dict) and entry.get("kind") == "visual":
                payload = entry.get("feedback")
                if isinstance(payload, dict):
                    return payload
        return {}

    def _consider_best(
        self, *, stage: str, critique: Optional[VisualCritique], brand_debt: int = 0
    ) -> None:
        """Update the keep-best snapshot if the live scene beats the incumbent.

        Ranking (higher wins): preflight-clean drafts dominate compile-only ones;
        among equals, an accepted critique beats a rejected one, then the LOWER
        brand-governance debt (K4: count of advisory LUMB08xx on the draft —
        without this term the loop launders a brand failure into the winning
        draft by STRIPPING tokens until preflight has no errors; run_68496e56
        shipped 0/4 style bindings exactly that way), then the lower
        severity-weighted issue penalty, then confidence — SIGNED by the verdict:
        the critic's confidence is in its own verdict, so among accepted drafts
        higher confidence wins, while among rejected drafts higher confidence
        means "more certainly bad" and ranks LOWER (run_8e7b9f64: the off-canvas
        draft was rejected at 0.90, the visible one at 0.86 — the raw-confidence
        tiebreak proposed the invisible badge). The scene is unchanged across the
        compile/preflight/critique stages of one iteration, so re-ranking the same
        iteration as more signal arrives simply upgrades its tier.
        """
        preflight_clean = stage == "preflight_clean"
        accepted = bool(critique and critique.accepted)
        if critique is None:
            issue_penalty = 999
        else:
            issue_penalty = sum(
                _ISSUE_SEVERITY_PENALTY.get(issue.severity, 3)
                for issue in critique.issues
            )
        confidence = critique.confidence if critique is not None else 0.0
        rank = (
            1 if preflight_clean else 0,
            1 if accepted else 0,
            -brand_debt,
            -issue_penalty,
            confidence if accepted else -confidence,
        )
        if self.best_rank is None or rank > self.best_rank:
            self.best_rank = rank
            self.best_scene = copy.deepcopy(self.tools.scene)
            self.best_iteration = self.state.current_iteration

    def _finalize_failed(self, stop_reason: str, message: str, **kwargs) -> dict:
        """Finalize a failed run, always leaving the editor the best draft.

        Every failed exit routes through here so the canvas shows the
        highest-ranked renderable design we produced — never a half-mutated or
        rejected scene from the last repair attempt.
        """
        self._restore_best_scene()
        kwargs.setdefault("baseline_advisory_json", self._baseline_advisory_payload_json())
        kwargs.setdefault("accommodation_json", self._accommodation_payload_json())
        return json.loads(
            self.tools.finalize_run("failed", stop_reason, message, **kwargs)
        )

    def _restore_best_scene(self) -> None:
        """Replace the live scene with the best clean draft, if we captured one.

        Repairs can author a delete-then-recreate block whose compile halts
        partway and leaves `tools.scene` partially mutated. Restoring keeps the
        last renderable design available to the editor as a failed-run draft.
        """
        if self.best_scene is not None:
            self.tools.scene = copy.deepcopy(self.best_scene)


# Constraints handed to the author for a targeted, modify-only repair. They are
# also enforced mechanically by `is_surgical_dsl` — the prose tells the model
# what to do; the gate guarantees the scene survives if it doesn't.
SURGICAL_AUTHORING_CONSTRAINTS = [
    "This is a TARGETED repair. Emit ONLY `#<node_id> property(...)` modify lines "
    "that edit existing nodes (the failing node or its immediate container).",
    "Do NOT emit any `page` line, any `delete(...)`, `parent(...)`, `clone(...)`, "
    "or `replace(...)` directive, and do NOT re-declare an existing node as a new "
    "element. Re-authoring the scene is forbidden and will be rejected unapplied.",
    "Change the smallest set of properties that clears the diagnostic. For text "
    "overflow: enlarge the box (`#node s(w,h)`), raise `max_lines`, lower the "
    "font size, or make the container taller (`#container s(w,h)`).",
]

LAYOUT_CLUSTER_PERMISSIONS = [
    "modify_position",
    "modify_size",
    "modify_sizing_mode",
    "modify_auto_layout",
    "modify_padding",
    "modify_gap",
    "modify_wrap",
    "modify_clip",
    "modify_page_background",
    "convert_diagnosed_background",
]

LAYOUT_CLUSTER_PROHIBITIONS = [
    "do not delete pages",
    "do not re-declare existing pages",
    "do not delete unrelated nodes",
    "do not edit unrelated slots",
    "do not edit unrelated Brand Kit tokens",
    "do not replace unrelated assets",
    "do not regenerate the whole scene",
    "do not hide overflow with clipping unless the content also fits",
]

LAYOUT_CLUSTER_AUTHORING_CONSTRAINTS = [
    "This is a BOUNDED LAYOUT CLUSTER repair.",
    "Edit only the named page/root/parent/descendant IDs in the cluster.",
    "Use supported modify-line properties only: `#node p(...)`, `#node s(...)`, "
    "`#node g(...)`, `#node pad(...)`, `#node x(...)`, `#node y(...)`, "
    "`#node clip(...)`, and text `wrap_text(...)` / `max_lines(...)`.",
    "Do NOT write `#node al(...)` or `#node wrap(...)`: `al(...)` is creation "
    "syntax and auto-layout `wrap(...)` is not lowered for node modify lines.",
    "If the cluster includes the root artboard frame and you edit its size, use "
    "`#root s(fill,fill)`. Numeric root artboard sizes such as `s(595,842)` are "
    "rejected because they can drift from canonical artboard bounds.",
    "You may convert only the diagnosed background node into page/artboard fill.",
    "Do not emit page declarations, unrelated node declarations, or whole-scene "
    "replacements.",
    "Do not delete pages, unrelated nodes, slots, Brand Kit tokens, or assets.",
]

SLOT_FIXTURE_PERMISSIONS = [
    "set_slot_sample",
    "set_slot_worst_case",
    "set_slot_placeholder",
    "rebind_slot",
]

SLOT_FIXTURE_PROHIBITIONS = [
    "do not re-declare existing pages",
    "do not delete or re-author nodes",
    "do not edit unrelated slots",
    "do not change page dimensions",
]

SLOT_FIXTURE_AUTHORING_CONSTRAINTS = [
    "This is a SLOT-FIXTURE repair. Fix the diagnosed slot in place with "
    "`#slot:<key> ...` modify lines.",
    "For a slot with no fit-validation fixture, add realistic fixtures: "
    '`#slot:<key> sample("…") worst_case("…")` (and `placeholder("…")` if the '
    "slot is required). Use worst-case copy so fit validation tests real-length "
    "data.",
    "For a slot that binds a missing node, `#slot:<key> unbind(<node>)` or rebind "
    "to an existing node.",
    "Emit ONLY `#slot:<key> ...` (or `#<node_id> ...`) modify lines. Do NOT emit "
    "any `page` line, `delete(...)`, or whole-scene re-author — that is rejected "
    "unapplied.",
]

TEXT_FIT_CODES = {"LUMV0902", "LUMV0903", "LUMV0904", "LUMV0810"}
LAYOUT_CLUSTER_CODES = {"LUMV0800", "LUMV0801", "LUMV0803"}
LEGACY_GEOMETRY_CODES = {"LUMV0805"}
# Slot-fixture / slot-binding diagnostics whose fix is a `#slot:` edit (add a
# sample/worst_case/placeholder fixture, or rebind a missing node) — NOT a
# page/parent-bounds geometry repair. Routed to RepairClass.slot_fixture only when
# the diagnostic's SUBJECT is the slot itself; the same codes with a NODE subject
# (e.g. the root artboard exceeding page bounds) stay layout_cluster.
SLOT_REPAIR_CODES = {"LUMV0800", "LUMV0801", "LUMV0509"}
UNSUPPORTED_LAYOUT_CLUSTER_MODIFY_CALL_RE = re.compile(
    r"(?:^|\s)(?:al|autolayout|wrap)\("
)
SIZE_CALL_RE = re.compile(r"(?:^|\s)(?:s|size)\(([^)]*)\)")


def reauthor_correction(compile_summary: dict, scene: Optional[dict] = None) -> Optional[dict]:
    """Detect the re-author failure modes on an existing scene and produce the
    exact corrective feedback for the next authoring attempt (Phase 0b).

    Keys off `halted_at.code` — the one place the LUMD code survives diagnostic
    normalization — and pulls the offending id out of the diagnostic text
    (which may be a stringified session-shaped dict). With the scene available
    it also distinguishes two traps the code alone cannot: a LUMD0901 "missing
    node" whose id is actually an existing PAGE (`#page_a4` written instead of
    `#page:page_a4`, or `replace()` pointed at a page), and a LUMD0401 whose
    duplicate id is NOT in the scene — a within-block collision (the same id
    declared on two pages of one block) that needs rename-and-re-emit, not an
    in-place edit of a node that doesn't exist."""
    halted = compile_summary.get("halted_at") or {}
    code = halted.get("code")
    blob = json.dumps(compile_summary.get("diagnostics") or [])
    if code == "LUMD0901":
        match = _MISSING_TARGET_RE.search(blob)
        offending = match.group(1) if match else None
        pages = (scene or {}).get("pages") or {}
        if not offending or offending not in pages:
            return None
        return {
            "code": code,
            "kind": "page_ref",
            "offending_id": offending,
            "instruction": (
                f"'{offending}' is a PAGE, not a node — `#{offending} ...` is node-ref "
                "grammar, so the block halted (LUMD0901) and NOTHING applied. Page "
                f"modify lines use the page ref form: `#page:{offending} "
                "size(1080,1350,px)`. `replace(...)`/`clone(...)`/`delete(...)` take "
                "NODE ids only, never page ids. To repurpose this page in ONE block: "
                f"`#page:{offending} size(w,h,px)` on the first line, then "
                "`replace(<existing_root_node_id>)` with your new single-root subtree "
                "indented under it."
            ),
        }
    if code not in REAUTHOR_HALT_CODES:
        return None
    if code == "LUMD0401":
        match = _REAUTHORED_NODE_RE.search(blob)
        offending = match.group(1) if match else None
        nodes = (scene or {}).get("nodes") or {}
        if scene is not None and offending and offending not in nodes:
            # The duplicate collides with itself INSIDE the rejected block — the
            # scene has no such node (observed live, run_bdfe575c: the author
            # declared `artboard`/`header` on BOTH variant pages of one block).
            # The existing-node correction would be a misdiagnosis here: "edit
            # it in place with `#<id>` modify lines" targets a node that does
            # not exist (LUMD0901), and the surgical reroute would pin the next
            # iteration to it. The correct move is rename-and-re-emit.
            return {
                "code": code,
                "kind": "duplicate_in_block",
                "offending_id": offending,
                "instruction": (
                    f"Your block declares the node id '{offending}' MORE THAN "
                    "ONCE — the collision is inside the block itself (no node "
                    f"'{offending}' exists in the scene), so the WHOLE block "
                    "was rejected unapplied (LUMD0401). Node ids are "
                    "document-global across ALL pages: give every element a "
                    "unique id — suffix per page/variant, e.g. "
                    f"`{offending}_a` on the first page, `{offending}_b` on "
                    "the second — and re-emit the corrected FULL block. Do "
                    f"NOT switch to `#{offending}` modify lines; that node "
                    "does not exist."
                ),
            }
        return {
            "code": code,
            "kind": "node",
            "offending_id": offending,
            "instruction": (
                f"You re-declared the existing node id '{offending or '<unknown>'}' "
                "as a new element, so the WHOLE block was rejected unapplied "
                f"(LUMD0401). Edit it in place with `#{offending or '<id>'} "
                "property(...)` modify lines (every property is a parenthesized "
                "call), or swap its subtree atomically with `replace("
                f"{offending or '<id>'})` + an indented single-root subtree. "
                "Never re-author existing ids."
            ),
        }
    match = _REAUTHORED_PAGE_RE.search(blob)
    offending = match.group(1) if match else None
    page_ref = f"#page:{offending}" if offending else "#page:<page_id>"
    return {
        "code": code,
        "kind": "page",
        "offending_id": offending,
        "instruction": (
            f"You re-declared the existing page '{offending or '<unknown>'}', so "
            "the block was rejected unapplied (LUMA0200). Never emit a `page` "
            "line for an existing page. To resize or restyle it, use the PAGE "
            f"ref form on a modify line: `{page_ref} size(1080,1350,px)` — "
            f"plain `#{offending or '<page_id>'}` is NODE grammar and will fail "
            "with LUMD0901. To replace its content, keep the page and swap the "
            "existing root node's subtree: `replace(<existing_root_node_id>)` "
            "with your new single-root subtree indented under it (replace takes "
            "node ids only). Brand-new pages go under NEW page ids."
        ),
    }


def issue_in_edit_scope(
    issue: VisualIssue, scope_node_ids: set, edited_page_ids: set
) -> bool:
    """True when a critique issue targets content this turn edited (Phase 0b).

    Node targets are in scope when they name an edited node or one of its
    current descendants. Page targets are in scope only for pages this turn
    added/updated. Untargeted (whole-design) issues and slot-key-only issues
    are advisory on a seeded turn — they describe pre-existing content."""
    target = issue.target
    if target is None:
        return False
    if target.node_id:
        return target.node_id in scope_node_ids
    if target.page_id:
        return target.page_id in edited_page_ids
    return False


def primary_diagnostic(diagnostics: list[dict]) -> dict | None:
    """The diagnostic ``first_diagnostic_target`` keys on: the first error/blocker
    that carries a target, else the first non-error that does. Used to classify a
    repair by the SUBJECT (node vs slot vs page) of the diagnostic actually being
    targeted, so it stays consistent with the ``target`` passed to
    :func:`classify_diagnostics`."""
    ordered = [
        *[d for d in diagnostics if d.get("severity") in {"error", "blocker"}],
        *[d for d in diagnostics if d.get("severity") not in {"error", "blocker"}],
    ]
    for diagnostic in ordered:
        if (
            diagnostic.get("target_page_id")
            or diagnostic.get("target_node_id")
            or diagnostic.get("target_slot_key")
            or diagnostic.get("target_slot_id")
        ):
            return diagnostic
    return None


def classify_diagnostics(
    diagnostics: list[dict],
    target: dict,
    scene: dict | None = None,
    prior_context: dict | None = None,
) -> RepairClassification:
    normalized = [diagnostic_to_dict(diagnostic) for diagnostic in diagnostics]
    codes = {str(diagnostic.get("code") or "") for diagnostic in normalized}
    blocking_codes = {
        str(diagnostic.get("code") or "")
        for diagnostic in normalized
        if diagnostic.get("severity") in {"error", "blocker"}
    }
    priority_codes = blocking_codes or codes
    scene = scene or {}

    if (
        prior_context
        and prior_context.get("repair_class") == RepairClass.layout_cluster.value
        and any(code.startswith("LUMD") or code.startswith("LUMA") for code in priority_codes)
    ):
        cluster = LayoutClusterTarget.model_validate(prior_context.get("cluster") or {})
        return RepairClassification(
            repair_class=RepairClass.layout_cluster,
            target=VisualTarget.model_validate(target) if target else None,
            cluster=cluster,
            allowed_edit_surface=EditSurfaceRecommendation.structured_ops,
            permissions=list(LAYOUT_CLUSTER_PERMISSIONS),
            prohibitions=list(LAYOUT_CLUSTER_PROHIBITIONS),
            reason="preserve_layout_cluster_after_compile_failure",
        )

    # A slot-SUBJECT LUMV0800/LUMV0801 (required slot needs a fixture / slot binds a
    # missing node) or LUMV0509 (no fit-validation fixtures) is NOT page/parent-bounds
    # geometry — its fix is a `#slot:` edit, which the layout-cluster gate forbids.
    # Route it to a slot-fixture repair instead. The SAME codes with a NODE subject
    # (e.g. the root artboard exceeding page bounds) fall through to layout_cluster.
    primary = primary_diagnostic(normalized)
    if (
        primary
        and str(primary.get("code") or "") in SLOT_REPAIR_CODES
        and (primary.get("target_slot_id") or primary.get("target_slot_key"))
        and not primary.get("target_node_id")
    ):
        return RepairClassification(
            repair_class=RepairClass.slot_fixture,
            target=VisualTarget.model_validate(target) if target else None,
            allowed_edit_surface=EditSurfaceRecommendation.structured_ops,
            permissions=list(SLOT_FIXTURE_PERMISSIONS),
            prohibitions=list(SLOT_FIXTURE_PROHIBITIONS),
            reason="slot_fixture_or_binding",
        )

    if priority_codes & LAYOUT_CLUSTER_CODES:
        return layout_cluster_classification(
            normalized,
            target,
            scene,
            reason="page_or_parent_bounds",
        )

    if priority_codes & LEGACY_GEOMETRY_CODES:
        return RepairClassification(
            repair_class=RepairClass.unsupported_gap,
            target=VisualTarget.model_validate(target) if target else None,
            allowed_edit_surface=EditSurfaceRecommendation.external_planner,
            reason="legacy_geometry_requires_migration_decision",
        )

    if text_fit_should_escalate(normalized, scene):
        return layout_cluster_classification(
            normalized,
            target,
            scene,
            reason="multiple_text_fit_diagnostics_share_parent",
        )

    if priority_codes & TEXT_FIT_CODES and target.get("node_id"):
        return RepairClassification(
            repair_class=RepairClass.targeted_node,
            target=VisualTarget.model_validate(target),
            allowed_edit_surface=EditSurfaceRecommendation.structured_ops,
            reason="single_text_fit_target",
        )

    if any(code.startswith("LUMB") for code in priority_codes):
        return RepairClassification(
            repair_class=RepairClass.brand_token,
            target=VisualTarget.model_validate(target) if target else None,
            allowed_edit_surface=EditSurfaceRecommendation.structured_ops,
            reason="brand_governance_diagnostic",
        )

    if any(code.startswith("LUMD") or code.startswith("LUMA") for code in priority_codes):
        return RepairClassification(
            repair_class=RepairClass.syntax_continuation,
            target=VisualTarget.model_validate(target) if target else None,
            allowed_edit_surface=EditSurfaceRecommendation.dsl,
            reason="compile_or_agent_guard_diagnostic",
        )

    if target.get("node_id"):
        return RepairClassification(
            repair_class=RepairClass.targeted_node,
            target=VisualTarget.model_validate(target),
            allowed_edit_surface=EditSurfaceRecommendation.structured_ops,
            reason="named_node_target",
        )

    return RepairClassification(
        repair_class=RepairClass.syntax_continuation,
        target=VisualTarget.model_validate(target) if target else None,
        allowed_edit_surface=EditSurfaceRecommendation.dsl,
        reason="default_repair_class",
    )


def layout_cluster_classification(
    diagnostics: list[dict],
    target: dict,
    scene: dict,
    reason: str,
) -> RepairClassification:
    cluster = resolve_layout_cluster(scene, diagnostics, target)
    return RepairClassification(
        repair_class=RepairClass.layout_cluster,
        target=VisualTarget.model_validate(target) if target else None,
        cluster=cluster,
        allowed_edit_surface=EditSurfaceRecommendation.structured_ops,
        permissions=list(LAYOUT_CLUSTER_PERMISSIONS),
        prohibitions=list(LAYOUT_CLUSTER_PROHIBITIONS),
        reason=reason,
    )


def resolve_layout_cluster(
    scene: dict,
    diagnostics: list[dict],
    target: dict,
) -> LayoutClusterTarget:
    parent_by_node, page_by_node = build_parent_maps(scene)
    target_node_ids = diagnostic_node_ids(
        diagnostics,
        scene=scene,
        include_slot_bound_nodes=True,
    )
    if target.get("node_id"):
        target_node_ids.append(str(target["node_id"]))
    if target.get("slot_key"):
        target_node_ids.extend(slot_bound_node_ids(scene, str(target["slot_key"])))
    target_node_ids = dedupe(target_node_ids)

    page_id = (
        target.get("page_id")
        or first_diagnostic_value(diagnostics, "target_page_id")
        or first_page_for_nodes(target_node_ids, page_by_node)
        or single_page_id(scene)
    )
    if page_id:
        page_target_node_ids = [
            node_id
            for node_id in target_node_ids
            if page_by_node.get(node_id) == page_id
        ]
        if page_target_node_ids:
            target_node_ids = dedupe(page_target_node_ids)
    root_frame_id = find_root_frame_candidate(scene, page_id) if page_id else None
    common_parent_node_id = common_layout_cluster_parent(
        scene,
        target_node_ids,
        parent_by_node,
        root_frame_id,
    )
    non_root_target_count = len(
        [node_id for node_id in target_node_ids if node_id != root_frame_id]
    )
    parent_node_id = common_parent_node_id
    if parent_node_id is None and non_root_target_count <= 1:
        parent_node_id = target.get("parent_node_id")
    background_node_id = find_background_candidate(
        scene,
        page_id,
        target_node_ids,
        diagnostics,
    )

    descendants: list[str] = []
    if parent_node_id:
        descendants.extend(node_children(scene, parent_node_id))
    descendants.extend(target_node_ids)
    descendants.extend(
        affected_ancestor_ids(
            target_node_ids,
            parent_by_node,
            stop_ids={parent_node_id, root_frame_id, background_node_id, None},
        )
    )
    if root_frame_id and not parent_node_id:
        descendants.extend(node_children(scene, root_frame_id))
    descendants = [
        node_id
        for node_id in dedupe(descendants)
        if node_id not in {parent_node_id, root_frame_id, background_node_id, None}
    ]

    return LayoutClusterTarget(
        page_id=page_id,
        root_frame_id=root_frame_id,
        parent_node_id=parent_node_id,
        descendant_node_ids=descendants,
        background_node_id=background_node_id,
        diagnostic_codes=dedupe(
            [
                str(diagnostic.get("code"))
                for diagnostic in diagnostics
                if diagnostic.get("code")
            ]
        ),
    )


def diagnostic_to_dict(diagnostic: dict | object) -> dict:
    if isinstance(diagnostic, dict):
        return diagnostic
    model_dump = getattr(diagnostic, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return {}


def diagnostic_node_ids(
    diagnostics: list[dict],
    scene: dict | None = None,
    include_slot_bound_nodes: bool = False,
) -> list[str]:
    node_ids: list[str] = []
    for diagnostic in diagnostics:
        node_id = diagnostic.get("target_node_id")
        subject = diagnostic.get("subject") or {}
        if not node_id and isinstance(subject, dict) and subject.get("kind") == "node":
            node_id = subject.get("id") or subject.get("value")
        if node_id:
            node_ids.append(str(node_id))
        if (
            include_slot_bound_nodes
            and scene is not None
            and diagnostic.get("code") in TEXT_FIT_CODES
        ):
            slot_identifier = diagnostic.get("target_slot_id") or diagnostic.get(
                "target_slot_key"
            )
            if slot_identifier:
                node_ids.extend(slot_bound_node_ids(scene, str(slot_identifier)))
    return node_ids


def slot_bound_node_ids(scene: dict, slot_identifier: str) -> list[str]:
    """Resolve a diagnostic slot id/key to bound node IDs.

    Runtime classification receives the raw Scene where `slots` is a dict of
    slot records with `bound_nodes` as node IDs. Trace/debug summaries expose
    `slots` as a list and each `bound_nodes` entry is a node brief. Supporting
    both keeps the repair resolver aligned with persisted traces.
    """
    slots = scene.get("slots") or {}
    if isinstance(slots, dict):
        iterable = slots.items()
    elif isinstance(slots, list):
        iterable = ((slot.get("id"), slot) for slot in slots if isinstance(slot, dict))
    else:
        iterable = []

    node_ids: list[str] = []
    for slot_id, slot in iterable:
        if not isinstance(slot, dict):
            continue
        candidates = {
            str(value)
            for value in (slot_id, slot.get("id"), slot.get("key"))
            if value
        }
        if slot_identifier not in candidates:
            continue
        for bound in slot.get("bound_nodes") or []:
            node_id = bound_node_id(bound)
            if node_id:
                node_ids.append(node_id)
    return dedupe(node_ids)


def bound_node_id(bound: object) -> str | None:
    if isinstance(bound, str):
        return bound
    if isinstance(bound, dict) and bound.get("id"):
        return str(bound["id"])
    return None


def first_diagnostic_value(diagnostics: list[dict], key: str) -> str | None:
    for diagnostic in diagnostics:
        value = diagnostic.get(key)
        if value:
            return str(value)
        subject = diagnostic.get("subject") or {}
        if (
            key == "target_page_id"
            and isinstance(subject, dict)
            and subject.get("kind") == "page"
        ):
            return str(subject.get("id") or subject.get("value"))
    return None


def text_fit_should_escalate(diagnostics: list[dict], scene: dict) -> bool:
    text_node_ids = [
        node_id
        for diagnostic in diagnostics
        if diagnostic.get("code") in TEXT_FIT_CODES
        for node_id in diagnostic_node_ids(
            [diagnostic],
            scene=scene,
            include_slot_bound_nodes=True,
        )
    ]
    if len(text_node_ids) < 2:
        return False
    parent_by_node, _ = build_parent_maps(scene)
    parent_ids = {parent_by_node.get(node_id) for node_id in text_node_ids}
    parent_ids.discard(None)
    return len(parent_ids) == 1


def build_parent_maps(scene: dict) -> tuple[dict[str, str], dict[str, str]]:
    parent_by_node: dict[str, str] = {}
    page_by_node: dict[str, str] = {}
    for page_id, page in (scene.get("pages") or {}).items():
        for child_id in page.get("children") or []:
            page_by_node[str(child_id)] = str(page_id)
            collect_node_parent_maps(
                scene,
                str(child_id),
                str(page_id),
                parent_by_node,
                page_by_node,
            )
    return parent_by_node, page_by_node


def collect_node_parent_maps(
    scene: dict,
    node_id: str,
    page_id: str,
    parent_by_node: dict[str, str],
    page_by_node: dict[str, str],
) -> None:
    page_by_node[node_id] = page_id
    for child_id in node_children(scene, node_id):
        parent_by_node[str(child_id)] = node_id
        collect_node_parent_maps(
            scene,
            str(child_id),
            page_id,
            parent_by_node,
            page_by_node,
        )


def first_page_for_nodes(
    node_ids: list[str],
    page_by_node: dict[str, str],
) -> str | None:
    for node_id in node_ids:
        page_id = page_by_node.get(node_id)
        if page_id:
            return page_id
    return None


def common_layout_cluster_parent(
    scene: dict,
    node_ids: list[str],
    parent_by_node: dict[str, str],
    root_frame_id: str | None,
) -> str | None:
    candidate_nodes = [
        node_id for node_id in dedupe(node_ids) if node_id != root_frame_id
    ]
    if not candidate_nodes:
        return None
    ancestor_paths = [
        ancestor_path_including_self(
            scene,
            node_id,
            parent_by_node,
            root_frame_id,
        )
        for node_id in candidate_nodes
    ]
    ancestor_paths = [path for path in ancestor_paths if path]
    if not ancestor_paths:
        return None

    common = set(ancestor_paths[0])
    for path in ancestor_paths[1:]:
        common.intersection_update(path)
    if not common:
        return None

    first_path = ancestor_paths[0]
    for candidate in first_path:
        if candidate in common and candidate != root_frame_id:
            return candidate

    return None


def ancestor_path_including_self(
    scene: dict,
    node_id: str,
    parent_by_node: dict[str, str],
    root_frame_id: str | None,
) -> list[str]:
    path: list[str] = []
    current = (
        node_id if is_container_node(scene, node_id) else parent_by_node.get(node_id)
    )
    while current:
        path.append(current)
        if current == root_frame_id:
            break
        current = parent_by_node.get(current)
    return path


def is_container_node(scene: dict, node_id: str | None) -> bool:
    if not node_id:
        return False
    node = (scene.get("nodes") or {}).get(node_id) or {}
    kind = node.get("kind")
    if isinstance(kind, dict):
        kind_name = kind.get("kind")
    else:
        kind_name = kind
    return str(kind_name or "").lower() in {
        "frame",
        "group",
        "autolayout",
        "auto_layout",
        "auto-layout",
        "al",
    }


def affected_ancestor_ids(
    node_ids: list[str],
    parent_by_node: dict[str, str],
    stop_ids: set[str | None],
) -> list[str]:
    ancestors: list[str] = []
    for node_id in node_ids:
        parent_id = parent_by_node.get(node_id)
        while parent_id and parent_id not in stop_ids:
            ancestors.append(parent_id)
            parent_id = parent_by_node.get(parent_id)
    return dedupe(ancestors)


def single_page_id(scene: dict) -> str | None:
    pages = scene.get("pages") or {}
    if len(pages) == 1:
        return next(iter(pages.keys()))
    return None


def page_children(scene: dict, page_id: str | None) -> list[str]:
    if not page_id:
        return []
    page = (scene.get("pages") or {}).get(page_id) or {}
    return [str(child_id) for child_id in page.get("children") or []]


def node_children(scene: dict, node_id: str | None) -> list[str]:
    if not node_id:
        return []
    node = (scene.get("nodes") or {}).get(node_id) or {}
    return [str(child_id) for child_id in node.get("children") or []]


def find_root_frame_candidate(scene: dict, page_id: str | None) -> str | None:
    direct_children = page_children(scene, page_id)
    if len(direct_children) == 1:
        return direct_children[0]
    for node_id in direct_children:
        if is_root_like_node_id(node_id):
            return node_id
    return None


def find_background_candidate(
    scene: dict,
    page_id: str | None,
    target_node_ids: list[str],
    diagnostics: list[dict],
) -> str | None:
    message = " ".join(
        str(diagnostic.get("message") or "") + " " + str(diagnostic.get("hint") or "")
        for diagnostic in diagnostics
    ).lower()
    direct_children = set(page_children(scene, page_id))
    for node_id in target_node_ids:
        if node_id in direct_children and (
            "background" in message or is_background_like_node_id(node_id)
        ):
            return node_id
    for node_id in direct_children:
        if is_background_like_node_id(node_id) and not has_slot_binding(scene, node_id):
            return node_id
    return None


def is_root_like_node_id(node_id: str) -> bool:
    lowered = node_id.lower()
    return any(
        term in lowered for term in ("root", "artboard", "canvas", "background", "bg")
    )


def is_background_like_node_id(node_id: str) -> bool:
    lowered = node_id.lower()
    return any(term in lowered for term in ("background", "bg", "backdrop", "canvas"))


def has_slot_binding(scene: dict, node_id: str) -> bool:
    slots = scene.get("slots") or {}
    iterable = slots.values() if isinstance(slots, dict) else slots
    for slot in iterable:
        if not isinstance(slot, dict):
            continue
        bound_node_ids = [
            bound_node_id(bound) for bound in slot.get("bound_nodes") or []
        ]
        if node_id in bound_node_ids:
            return True
    return False


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def repair_class_payload(classification: RepairClassification) -> dict:
    return {
        "repair_class": classification.repair_class.value,
        "cluster": (
            classification.cluster.model_dump(mode="json")
            if classification.cluster
            else None
        ),
        "permissions": list(classification.permissions),
        "prohibitions": list(classification.prohibitions),
        "repair_class_reason": classification.reason,
    }


def repair_request_kwargs(classification: RepairClassification) -> dict:
    return {
        "repair_class": classification.repair_class.value,
        "cluster_json": json.dumps(
            classification.cluster.model_dump(mode="json")
            if classification.cluster
            else None
        ),
        "permissions_json": json.dumps(classification.permissions),
        "prohibitions_json": json.dumps(classification.prohibitions),
    }


def authoring_constraints_for(
    classification: RepairClassification,
    surgical: bool,
    fallback: list[str],
) -> list[str]:
    if classification.repair_class == RepairClass.layout_cluster:
        return list(LAYOUT_CLUSTER_AUTHORING_CONSTRAINTS)
    if classification.repair_class == RepairClass.slot_fixture:
        return list(SLOT_FIXTURE_AUTHORING_CONSTRAINTS)
    if surgical:
        return list(SURGICAL_AUTHORING_CONSTRAINTS)
    return fallback


def repair_is_surgical(recommendation: str, target: dict) -> bool:
    """A targeted property/fit repair we enforce as modify-only: a concrete node
    target routed to checked/structured edits."""
    return recommendation == "structured_ops" and bool((target or {}).get("node_id"))


def is_surgical_dsl(source: str) -> bool:
    """True when every meaningful line is a `#<ref> ...` modify line.

    Such a block edits existing objects in place and structurally cannot delete,
    re-declare, or re-`page` the scene. Blank lines and `//` checkpoints are
    ignored; a comment (`# text`, with a space after `#`) is not a modify ref. A
    block with no modify line at all is not surgical.
    """
    saw_modify = False
    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if not line.startswith("#"):
            return False  # page / element / delete / parent line → not surgical
        if len(line) < 2 or line[1].isspace():
            return False  # bare '#' or '# comment' → not a modify ref
        saw_modify = True
    return saw_modify


def is_layout_cluster_dsl(source: str, context: dict) -> bool:
    cluster = context.get("cluster") or {}
    allowed_pages = {cluster.get("page_id")} if cluster.get("page_id") else set()
    allowed_nodes = layout_cluster_allowed_node_ids(cluster)
    root_frame_id = cluster.get("root_frame_id")
    background_node_id = cluster.get("background_node_id")
    permissions = set(context.get("permissions") or [])
    saw_edit = False

    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("#"):
            ref = line[1:].split(None, 1)[0]
            if not layout_cluster_modify_syntax_is_supported(line):
                return False
            if ref == root_frame_id and not root_artboard_size_syntax_is_supported(line):
                return False
            if ref.startswith("page:"):
                page_id = ref.split(":", 1)[1]
                if page_id not in allowed_pages:
                    return False
            elif ref.startswith(("slot:", "asset:", "document")):
                return False
            elif ref not in allowed_nodes:
                return False
            saw_edit = True
            continue
        if line.startswith("delete(") and line.endswith(")"):
            deleted_id = line[len("delete(") : -1].strip()
            if (
                deleted_id == background_node_id
                and "convert_diagnosed_background" in permissions
            ):
                saw_edit = True
                continue
            return False
        return False

    return saw_edit


def filter_layout_cluster_dsl(source: str, context: dict) -> tuple[str, list[dict]]:
    """Split a layout_cluster repair block into the lines safe to apply and the
    out-of-cluster lines to skip.

    Returns ``(kept_source, dropped)`` where ``dropped`` is a list of
    ``{"line", "reason"}``. This is what makes cluster repair NON-ATOMIC: the
    per-line rules are identical to :func:`is_layout_cluster_dsl`, but instead of
    rejecting the whole block on the first stray line, the valid in-cluster
    modifies are kept and only the offending lines are dropped — so a mostly-valid
    patch is applied rather than zero-applied and the iteration is not wasted.
    Blank lines, ``//`` checkpoints, and comments are preserved verbatim.
    """
    cluster = context.get("cluster") or {}
    allowed_pages = {cluster.get("page_id")} if cluster.get("page_id") else set()
    allowed_nodes = layout_cluster_allowed_node_ids(cluster)
    root_frame_id = cluster.get("root_frame_id")
    background_node_id = cluster.get("background_node_id")
    permissions = set(context.get("permissions") or [])
    kept: list[str] = []
    dropped: list[dict] = []

    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            kept.append(raw)
            continue
        if line.startswith("#"):
            ref = line[1:].split(None, 1)[0]
            if not layout_cluster_modify_syntax_is_supported(line):
                dropped.append({
                    "line": line,
                    "reason": "unsupported modify syntax (al()/wrap() are not lowered for node modify lines)",
                })
                continue
            if ref == root_frame_id and not root_artboard_size_syntax_is_supported(line):
                dropped.append({
                    "line": line,
                    "reason": "root artboard frame must use s(fill,fill), not numeric dimensions",
                })
                continue
            if ref.startswith("page:"):
                page_id = ref.split(":", 1)[1]
                if page_id not in allowed_pages:
                    dropped.append({
                        "line": line,
                        "reason": f"page {page_id} is outside the allowed cluster",
                    })
                    continue
            elif ref.startswith(("slot:", "asset:", "document")):
                dropped.append({
                    "line": line,
                    "reason": f"{ref} is not editable in a layout_cluster repair",
                })
                continue
            elif ref not in allowed_nodes:
                dropped.append({
                    "line": line,
                    "reason": f"node {ref} is outside the allowed cluster",
                })
                continue
            kept.append(raw)
            continue
        if line.startswith("delete(") and line.endswith(")"):
            deleted_id = line[len("delete(") : -1].strip()
            if (
                deleted_id == background_node_id
                and "convert_diagnosed_background" in permissions
            ):
                kept.append(raw)
                continue
            dropped.append({
                "line": line,
                "reason": "delete is not permitted in a layout_cluster repair",
            })
            continue
        dropped.append({
            "line": line,
            "reason": "only #modify lines (and an allowed background delete) are permitted in a layout_cluster repair",
        })

    return "\n".join(kept), dropped


def layout_cluster_modify_syntax_is_supported(line: str) -> bool:
    parts = line.split(None, 1)
    if len(parts) == 1:
        return True
    ref = parts[0][1:]
    if ref.startswith(("page:", "slot:", "asset:", "document", "export:")):
        return True
    properties = parts[1]
    return UNSUPPORTED_LAYOUT_CLUSTER_MODIFY_CALL_RE.search(properties) is None


def root_artboard_size_syntax_is_supported(line: str) -> bool:
    for match in SIZE_CALL_RE.finditer(line):
        args = [arg.strip().lower() for arg in match.group(1).split(",")]
        if args != ["fill", "fill"]:
            return False
    return True


def layout_cluster_allowed_node_ids(cluster: dict) -> set[str]:
    allowed = set(cluster.get("descendant_node_ids") or [])
    for key in ("root_frame_id", "parent_node_id", "background_node_id"):
        value = cluster.get(key)
        if value:
            allowed.add(str(value))
    return allowed


def surgical_violation_feedback(prior: dict, rejected_source: str) -> dict:
    """Feedback for a rejected non-surgical repair: tell the author exactly why
    it was dropped and re-issue the modify-only constraints, keeping the repair
    marked surgical so the next attempt is enforced too."""
    target = prior.get("surgical_target") or prior.get("target") or {}
    node_id = (target or {}).get("node_id")
    return {
        "kind": "surgical_violation",
        "feedback": (
            "Your previous repair was REJECTED and NOT applied because it was not "
            "a modify-only edit. A targeted repair must contain ONLY "
            "`#<node_id> property(...)` modify lines that edit existing nodes. You "
            "emitted a page line, a delete/parent/clone/replace directive, or a new "
            f"element declaration. Re-author nothing. Fix node `{node_id}` (or its "
            "immediate container) using the smallest set of `#`-modify lines."
        ),
        "target": target,
        "surgical_repair": True,
        "surgical_target": target,
        "recommended_edit_surface": "structured_ops",
        "authoring_constraints": list(SURGICAL_AUTHORING_CONSTRAINTS),
        "rejected_source": rejected_source[:500],
    }


def layout_cluster_violation_feedback(prior: dict, rejected_source: str) -> dict:
    cluster = prior.get("cluster") or {}
    allowed_pages = [cluster.get("page_id")] if cluster.get("page_id") else []
    allowed_nodes = sorted(layout_cluster_allowed_node_ids(cluster))
    root_frame_id = cluster.get("root_frame_id")
    return {
        "kind": "layout_cluster_violation",
        "feedback": (
            "Your previous layout_cluster repair was REJECTED and NOT applied "
            "because it edited outside the allowed cluster or attempted to "
            "re-author the page. Emit only #modify lines for allowed page/node "
            f"IDs. Allowed pages: {allowed_pages}. Allowed nodes: {allowed_nodes}. "
            f"If editing root artboard frame `{root_frame_id}`, use `s(fill,fill)` "
            "instead of numeric page dimensions."
        ),
        "target": prior.get("target") or {},
        "repair_class": RepairClass.layout_cluster.value,
        "cluster": cluster,
        "permissions": prior.get("permissions") or list(LAYOUT_CLUSTER_PERMISSIONS),
        "prohibitions": prior.get("prohibitions") or list(LAYOUT_CLUSTER_PROHIBITIONS),
        "recommended_edit_surface": EditSurfaceRecommendation.structured_ops.value,
        "authoring_constraints": list(LAYOUT_CLUSTER_AUTHORING_CONSTRAINTS),
        "rejected_source": rejected_source[:500],
    }


def slot_fixture_violation_feedback(prior: dict, rejected_source: str) -> dict:
    """Feedback for a rejected slot-fixture repair: it must be modify-only. Re-issue
    the slot-fixture constraints so the next attempt edits the slot in place rather
    than re-authoring the scene."""
    target = prior.get("target") or {}
    slot_key = (target or {}).get("slot_key")
    return {
        "kind": "slot_fixture_violation",
        "feedback": (
            "Your previous slot-fixture repair was REJECTED and NOT applied because "
            "it was not modify-only. Fix the diagnosed slot in place: add fixtures "
            f'with `#slot:{slot_key or "<key>"} sample("…") worst_case("…")` (and '
            "`placeholder(\"…\")` if required), or rebind a missing node with "
            f"`#slot:{slot_key or '<key>'} unbind(<node>)`. Do NOT emit any `page` "
            "line, `delete(...)`, or new element declaration."
        ),
        "target": target,
        "repair_class": RepairClass.slot_fixture.value,
        "permissions": prior.get("permissions") or list(SLOT_FIXTURE_PERMISSIONS),
        "prohibitions": prior.get("prohibitions") or list(SLOT_FIXTURE_PROHIBITIONS),
        "recommended_edit_surface": EditSurfaceRecommendation.structured_ops.value,
        "authoring_constraints": list(SLOT_FIXTURE_AUTHORING_CONSTRAINTS),
        "rejected_source": rejected_source[:500],
    }


def _diagnostic_key(diagnostic: dict) -> tuple:
    """Stable identity for a diagnostic: (code, subject).

    `subject` is whichever target field is set, preferring the most specific
    (node > slot > page), falling back to None for document-level diagnostics
    (e.g. brand/font asset warnings with no target at all). Two diagnostics
    with the same code but a DIFFERENT subject are different errors — this is
    what makes a baseline error that moves to a new node count as introduced
    rather than pre-existing (agent-improvement follow-up 1)."""
    subject = (
        diagnostic.get("target_node_id")
        or diagnostic.get("target_slot_id")
        or diagnostic.get("target_slot_key")
        or diagnostic.get("target_page_id")
    )
    return (diagnostic.get("code"), subject)


def has_blocking_diagnostics(diagnostics: list) -> bool:
    return any(
        isinstance(diagnostic, dict) and diagnostic.get("severity") in {"error", "blocker"}
        for diagnostic in diagnostics
    )


def tool_has_blocking_failure(summary: dict) -> bool:
    if summary.get("status") == "error":
        return True
    if summary.get("validation_errors"):
        return True
    return has_blocking_diagnostics(summary.get("diagnostics", []))


def infer_preview_target(user_request: str) -> PreviewTarget:
    lowered = user_request.lower()
    if "1:1" in lowered or "square" in lowered:
        return PreviewTarget(requested_aspect_ratio=1.0)
    return PreviewTarget()


def preview_target_errors(export_summary: dict, target: PreviewTarget) -> list[str]:
    errors: list[str] = []
    if target.requested_aspect_ratio is None:
        return errors
    for artifact in export_summary.get("artifacts", []):
        actual = artifact.get("aspect_ratio")
        if actual is None:
            continue
        if abs(float(actual) - target.requested_aspect_ratio) > 0.01:
            errors.append(
                "preview aspect ratio "
                f"{actual:.3f} does not match requested "
                f"{target.requested_aspect_ratio:.3f}"
            )
    return errors


def first_issue_target(critique: VisualCritique) -> dict:
    for issue in critique.issues:
        if issue.target is not None:
            return issue.target.model_dump(mode="json")
    return {}


def first_issue_target_from_payload(feedback: dict) -> dict:
    for issue in feedback.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        target = issue.get("target")
        if isinstance(target, dict) and target:
            return target
    return {}


def classify_visual_critique(
    critique: VisualCritique,
    target: dict,
    scene: dict,
) -> RepairClassification:
    diagnostics: list[dict] = []
    layout_categories = {
        "visual_balance",
        "alignment",
        "spacing",
        "compiler_repair",
        "clipping",
        "overflow",
        "page_dimensions",
    }
    categories: set[str] = set()
    for issue in critique.issues:
        category = str(issue.category.value if hasattr(issue.category, "value") else issue.category)
        categories.add(category)
        if category in layout_categories:
            issue_target = issue.target.model_dump(mode="json") if issue.target else target
            code = "LUMV0800" if issue_target.get("page_id") else "LUMV0801"
            diagnostics.append(
                {
                    "severity": issue.severity.value,
                    "code": code,
                    "message": issue.message,
                    "target_page_id": issue_target.get("page_id"),
                    "target_node_id": issue_target.get("node_id"),
                    "suggested_repair": issue.suggested_repair,
                }
            )
    classification = classify_diagnostics(diagnostics, target, scene=scene)
    if categories & {"visual_balance", "alignment", "spacing", "compiler_repair"}:
        return layout_cluster_classification(
            diagnostics,
            target,
            scene,
            reason="visual_critique_requires_structural_layout_repair",
        )
    # Step 9: an imagery-quality failure is repaired as an IMAGE (regenerate / recrop /
    # scrim / replace / remove) on the asset-tool surface — never a layout-geometry patch.
    # A co-occurring structural layout failure already returned above (fixed first).
    if categories & IMAGERY_CATEGORIES:
        return RepairClassification(
            repair_class=RepairClass.asset_tool,
            target=VisualTarget.model_validate(target) if target else None,
            allowed_edit_surface=EditSurfaceRecommendation.asset_tool,
            permissions=[
                "regenerate_asset",
                "recrop_focal_point",
                "add_or_fix_scrim",
                "replace_asset",
                "remove_asset",
            ],
            prohibitions=[
                "do not patch layout geometry to fix an image problem",
                "do not delete unrelated nodes",
                "do not replace a real image with a placeholder",
            ],
            reason="imagery_quality_requires_asset_repair",
        )
    return classification


def first_diagnostic_target(summary: dict) -> dict:
    diagnostics = summary.get("diagnostics", [])
    ordered = [
        *[
            diagnostic
            for diagnostic in diagnostics
            if diagnostic.get("severity") in {"error", "blocker"}
        ],
        *[
            diagnostic
            for diagnostic in diagnostics
            if diagnostic.get("severity") not in {"error", "blocker"}
        ],
    ]
    for diagnostic in ordered:
        target = {}
        if diagnostic.get("target_page_id"):
            target["page_id"] = diagnostic["target_page_id"]
        if diagnostic.get("target_node_id"):
            target["node_id"] = diagnostic["target_node_id"]
        if diagnostic.get("target_slot_key"):
            target["slot_key"] = diagnostic["target_slot_key"]
        elif diagnostic.get("target_slot_id"):
            target["slot_key"] = diagnostic["target_slot_id"]
        if target:
            return target
    return {}


def diagnostic_repair_intent(summary: dict) -> str:
    diagnostics = summary.get("diagnostics", [])
    if not diagnostics:
        return "repair preflight errors"
    parts = []
    for diagnostic in diagnostics[:5]:
        code = diagnostic.get("code") or "diagnostic"
        target = (
            diagnostic.get("target_node_id")
            or diagnostic.get("target_page_id")
            or diagnostic.get("target_slot_key")
            or diagnostic.get("target_slot_id")
            or "document"
        )
        message = diagnostic.get("message") or ""
        repair = diagnostic.get("suggested_repair") or ""
        parts.append(f"{code} on {target}: {message} {repair}".strip())
    intent = "repair targeted preflight diagnostics: " + " | ".join(parts)
    codes = {str(d.get("code") or "") for d in diagnostics}
    if "LUMB0301" in codes:
        # K4 guardrail: run_68496e56 "repaired" undefined-token errors by
        # stripping EVERY kit binding — errors gone, brand gone. Fixing an
        # undefined token means removing only that token reference.
        intent += (
            " | RULE: fix LUMB0301 by removing ONLY the undefined token "
            "reference (e.g. drop a font_size($type.size.*) the kit does not "
            "define); NEVER remove style($type.*) bindings to silence "
            "diagnostics — unbinding text is a brand regression (LUMB0805)."
        )
    return intent
