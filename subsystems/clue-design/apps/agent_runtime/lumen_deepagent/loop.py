from __future__ import annotations

import copy
import json
from typing import Optional, Protocol

from .schemas import (
    AgentIteration,
    AgentRunState,
    AuthoringBlockRequest,
    CompileRepairContext,
    CompileSummary,
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
    VisualTarget,
)
from .tools import LumenDesignTools


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
        knowledge: list[dict],
        previous_feedback: list[dict],
    ) -> VisualCritique:
        """Review the current preview and return a structured critique."""


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
    ) -> None:
        self.tools = tools
        self.author = author
        self.reviewer = reviewer
        self.previous_feedback: list[dict] = []
        self.state = AgentRunState(run_id=tools.run_id, user_request=tools.prompt)
        # Snapshot of the most recent scene that compiled cleanly (and is
        # therefore renderable). A later repair iteration can author a
        # destructive block — e.g. delete-then-recreate — whose compile halts
        # partway, leaving `tools.scene` stripped of the good design. We restore
        # this snapshot when the run fails so the editor always receives the best
        # renderable draft on the canvas instead of a wiped scene.
        self.best_scene: Optional[dict] = None

    def run(self, user_request: str) -> dict:
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
            )
            self.tools.record(
                "coordinator",
                "dsl_block_requested",
                input_summary=user_request[:500],
                output_summary=f"iteration {block_request.iteration}",
                payload={"author_request": block_request.model_dump(mode="json")},
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
            if (
                repair_context
                and repair_context.get("repair_class") == RepairClass.layout_cluster.value
                and not is_layout_cluster_dsl(source, repair_context)
            ):
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
            if (
                repair_context
                and repair_context.get("surgical_repair")
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

            compile_result = json.loads(self.tools.compile_dsl_block(source))
            compile_summary = compile_result.get("compile", {})
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
            # gates (preflight/critic) reject it. Remember it as the best draft
            # so a subsequent failed repair cannot strip the design from canvas.
            self.best_scene = copy.deepcopy(self.tools.scene)

            preflight_result = json.loads(self.tools.preflight_design())
            preflight_summary = preflight_result.get("preflight", {})
            self.state.effective_brand = preflight_result.get("effective_brand")
            iteration_record.preflight_summary = PreflightSummary.model_validate(
                preflight_summary
            )
            if tool_has_blocking_failure(preflight_summary) or preflight_summary.get("has_errors"):
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
                target = first_diagnostic_target(preflight_summary)
                repair_intent = diagnostic_repair_intent(preflight_summary)
                recommendation = json.loads(
                    self.tools.recommend_edit_surface(
                        repair_intent,
                        json.dumps(target),
                    )
                ).get("recommendation", "dsl")
                classification = classify_diagnostics(
                    preflight_summary.get("diagnostics", []),
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
                    "feedback": preflight_summary,
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
                if surgical:
                    feedback["surgical_repair"] = True
                    feedback["surgical_target"] = target
                repair_request = json.loads(
                    self.tools.create_repair_request(
                        exact_feedback=json.dumps(feedback, indent=2),
                        diagnostics_json=json.dumps(preflight_summary.get("diagnostics", [])),
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

            export_result = json.loads(self.tools.export_preview_bundle())
            export_summary = export_result.get("critic", {})
            iteration_record.export_summary = ExportSummary.model_validate(export_summary)
            if tool_has_blocking_failure(export_summary):
                iteration_record.stop_reason = StopReason.preview_invalid
                self.state.status = "failed"
                self.state.stop_reason = StopReason.preview_invalid
                final = json.loads(
                    self.tools.finalize_run(
                        "failed",
                        StopReason.preview_invalid.value,
                        "Preview export failed validation.",
                    )
                )
                return final
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
                return json.loads(
                    self.tools.finalize_run(
                        "failed",
                        StopReason.preview_invalid.value,
                        "Preview dimensions did not match requested artifact constraints.",
                    )
                )

            preview_payload = json.loads(self.tools.get_latest_preview_for_critique())
            if preview_payload.get("status") == "error":
                return json.loads(
                    self.tools.finalize_run(
                        "failed",
                        StopReason.preview_invalid.value,
                        preview_payload.get("message", "Preview payload unavailable."),
                    )
                )

            try:
                critique = self.reviewer.review(
                    user_request=user_request,
                    scene_summary=json.loads(self.tools.summarize_scene()),
                    export_summary=export_summary,
                    preview_payload=preview_payload,
                    knowledge=knowledge.get("snippets", []),
                    previous_feedback=self.previous_feedback,
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
                return json.loads(
                    self.tools.finalize_run(
                        "failed",
                        StopReason.critic_failed.value,
                        f"Visual reviewer failed: {error}",
                        critique_json=json.dumps(critique_failure),
                    )
                )
            self.tools.submit_visual_critique(critique.model_dump_json())
            iteration_record.critique = critique
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
                    )
                )

            feedback = {
                "kind": "visual",
                "feedback": critique.model_dump(mode="json"),
            }
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
            self.tools.create_repair_request(
                exact_feedback=json.dumps(feedback, indent=2),
                target_json=json.dumps(target),
                allowed_edit_surface=recommendation,
                forbidden_changes_json=json.dumps(["do not remove unrelated existing nodes"]),
                **repair_request_kwargs(classification),
            )
            iteration_record.stop_reason = StopReason.reviewer_rejected

        self.state.status = "failed"
        self.state.stop_reason = StopReason.max_iterations_reached
        # A destructive final repair may have left `tools.scene` stripped. Restore
        # the best scene that compiled this run so the editor renders that draft
        # on the canvas for inspection instead of an empty scene.
        self._restore_best_scene()
        return json.loads(
            self.tools.finalize_run(
                "failed",
                StopReason.max_iterations_reached.value,
                "Maximum Phase A repair iterations reached.",
                critique_json=json.dumps(
                    self.previous_feedback[-1] if self.previous_feedback else {}
                ),
            )
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
    "Allowed changes: p/s, fill/hug/fixed sizing, auto-layout, padding, gap, "
    "wrap, clip, and page background when permitted.",
    "You may convert only the diagnosed background node into page/artboard fill.",
    "Do not emit page declarations, unrelated node declarations, or whole-scene "
    "replacements.",
    "Do not delete pages, unrelated nodes, slots, Brand Kit tokens, or assets.",
]

TEXT_FIT_CODES = {"LUMV0902", "LUMV0903", "LUMV0904", "LUMV0810"}
LAYOUT_CLUSTER_CODES = {"LUMV0800", "LUMV0801", "LUMV0803"}
LEGACY_GEOMETRY_CODES = {"LUMV0805"}


def classify_diagnostics(
    diagnostics: list[dict],
    target: dict,
    scene: dict | None = None,
    prior_context: dict | None = None,
) -> RepairClassification:
    normalized = [diagnostic_to_dict(diagnostic) for diagnostic in diagnostics]
    codes = {str(diagnostic.get("code") or "") for diagnostic in normalized}
    scene = scene or {}

    if (
        prior_context
        and prior_context.get("repair_class") == RepairClass.layout_cluster.value
        and any(code.startswith("LUMD") or code.startswith("LUMA") for code in codes)
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

    if codes & LAYOUT_CLUSTER_CODES:
        return layout_cluster_classification(
            normalized,
            target,
            scene,
            reason="page_or_parent_bounds",
        )

    if codes & LEGACY_GEOMETRY_CODES:
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

    if any(code.startswith("LUMB") for code in codes):
        return RepairClassification(
            repair_class=RepairClass.brand_token,
            target=VisualTarget.model_validate(target) if target else None,
            allowed_edit_surface=EditSurfaceRecommendation.structured_ops,
            reason="brand_governance_diagnostic",
        )

    if codes & TEXT_FIT_CODES and target.get("node_id"):
        return RepairClassification(
            repair_class=RepairClass.targeted_node,
            target=VisualTarget.model_validate(target),
            allowed_edit_surface=EditSurfaceRecommendation.structured_ops,
            reason="single_text_fit_target",
        )

    if any(code.startswith("LUMD") or code.startswith("LUMA") for code in codes):
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
    target_node_ids = diagnostic_node_ids(diagnostics)
    if target.get("node_id"):
        target_node_ids.append(str(target["node_id"]))
    target_node_ids = dedupe(target_node_ids)

    page_id = (
        target.get("page_id")
        or first_diagnostic_value(diagnostics, "target_page_id")
        or first_page_for_nodes(target_node_ids, page_by_node)
        or single_page_id(scene)
    )
    target_node_id = target_node_ids[0] if target_node_ids else None
    parent_node_id = target.get("parent_node_id") or (
        parent_by_node.get(target_node_id) if target_node_id else None
    )
    root_frame_id = find_root_frame_candidate(scene, page_id) if page_id else None
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


def diagnostic_node_ids(diagnostics: list[dict]) -> list[str]:
    node_ids: list[str] = []
    for diagnostic in diagnostics:
        node_id = diagnostic.get("target_node_id")
        subject = diagnostic.get("subject") or {}
        if not node_id and isinstance(subject, dict) and subject.get("kind") == "node":
            node_id = subject.get("id") or subject.get("value")
        if node_id:
            node_ids.append(str(node_id))
    return node_ids


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
        for node_id in diagnostic_node_ids([diagnostic])
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
    for slot in (scene.get("slots") or {}).values():
        if node_id in (slot.get("bound_nodes") or []):
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
    background_node_id = cluster.get("background_node_id")
    permissions = set(context.get("permissions") or [])
    saw_edit = False

    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("#"):
            ref = line[1:].split(None, 1)[0]
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
    return {
        "kind": "layout_cluster_violation",
        "feedback": (
            "Your previous layout_cluster repair was REJECTED and NOT applied "
            "because it edited outside the allowed cluster or attempted to "
            "re-author the page. Emit only #modify lines for allowed page/node "
            f"IDs. Allowed pages: {allowed_pages}. Allowed nodes: {allowed_nodes}."
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


def tool_has_blocking_failure(summary: dict) -> bool:
    if summary.get("status") == "error":
        return True
    if summary.get("validation_errors"):
        return True
    for diagnostic in summary.get("diagnostics", []):
        if diagnostic.get("severity") in {"error", "blocker"}:
            return True
    return False


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


def classify_visual_critique(
    critique: VisualCritique,
    target: dict,
    scene: dict,
) -> RepairClassification:
    diagnostics: list[dict] = []
    for issue in critique.issues:
        category = str(issue.category.value if hasattr(issue.category, "value") else issue.category)
        if category in {"clipping", "overflow", "page_dimensions"}:
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
    return classify_diagnostics(diagnostics, target, scene=scene)


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
    return "repair targeted preflight diagnostics: " + " | ".join(parts)
