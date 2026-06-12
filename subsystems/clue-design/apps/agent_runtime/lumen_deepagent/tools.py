from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from lumen_api.core import CoreClient, CoreError

from .config import AgentRuntimeConfig
from .knowledge import read_task_knowledge
from .schemas import (
    CompileSummary,
    DiagnosticSeverity,
    DiagnosticSummary,
    EditSurfaceRecommendation,
    ExportSummary,
    GapArea,
    GapRecord,
    KnowledgeLoadResult,
    LumenRunTraceEvent,
    OperationApplicationSummary,
    PreflightSummary,
    PreviewArtifact,
    RepairRequest,
    StopReason,
    ToolStatus,
    VisualCritique,
    VisualTarget,
    new_run_id,
)


JsonObject = Dict[str, Any]


class LumenDesignTools:
    def __init__(self, config: AgentRuntimeConfig, prompt: str) -> None:
        self.config = config
        self.core = CoreClient(repo_root=config.repo_root)
        self.run_id = new_run_id()
        self.iteration = 0
        self.trace_dir = config.trace_dir / self.run_id
        self.iterations_dir = self.trace_dir / "iterations"
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.iterations_dir.mkdir(parents=True, exist_ok=True)
        self.scene = self.core.new_scene(self.run_id, "Agent-authored design")
        self.prompt = prompt
        self.preview_paths: list[str] = []
        self.loaded_knowledge: list[JsonObject] = []
        self.gaps: list[JsonObject] = []
        self.scene_update_sources: list[str] = []
        self.effective_brand_context: Optional[JsonObject] = None
        self.dsl_session: Optional[JsonObject] = None
        self.latest_export_summary: Optional[JsonObject] = None
        self.latest_preview_bundle: Optional[JsonObject] = None
        self._write_json(
            self.trace_dir / "input.json",
            {"run_id": self.run_id, "prompt": prompt},
        )
        self.record(
            "coordinator",
            "run_started",
            input_summary=prompt[:500],
            output_summary=f"created scene {self.run_id}",
            payload={"scene_update_policy": "core_response_only"},
        )

    def load_knowledge(self, query: str) -> str:
        """Load task-specific Lumen knowledge snippets with provenance."""
        snippets = read_task_knowledge(self.config.repo_root, query)
        result = KnowledgeLoadResult(query=query, snippets=snippets)
        payload = _dump(result)
        self.loaded_knowledge = payload["snippets"]
        self._write_json(self.trace_dir / "knowledge.json", payload)
        self.record(
            "coordinator",
            "knowledge_loaded",
            input_summary=query,
            output_summary=f"loaded {len(snippets)} snippets",
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def compile_dsl_block(self, source: str) -> str:
        """Compile a Lumen DSL block and update the scene only from core output."""
        self.iteration += 1
        iteration_dir = self._iteration_dir()
        (iteration_dir / "dsl.lumen").write_text(source, encoding="utf-8")

        duplicate_page = first_existing_page_declaration(source, self.scene)
        if duplicate_page:
            summary = CompileSummary(
                status=ToolStatus.error,
                diagnostics=[
                    DiagnosticSummary(
                        severity=DiagnosticSeverity.error,
                        code="LUMA0200",
                        message=(
                            "repair block tries to recreate existing page "
                            f"{duplicate_page['page_id']}"
                        ),
                        line=duplicate_page["line"],
                        target_page_id=duplicate_page["page_id"],
                        suggested_repair=(
                            "Do not emit an existing page line during repair. "
                            "Use checked structured operations for targeted changes, "
                            "or emit only a non-duplicating DSL continuation."
                        ),
                    )
                ],
                halted_at={"code": "LUMA0200", "line": duplicate_page["line"]},
            )
            payload = {"compile": _dump(summary)}
            self._write_json(iteration_dir / "compile.json", payload)
            self.record(
                "dsl-author",
                "dsl_compile_rejected",
                input_summary=source[:500],
                output_summary=summary.diagnostics[0].message,
                diagnostics=[diag.model_dump(mode="json") for diag in summary.diagnostics],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        try:
            response = self.core.compile_dsl_into_scene(
                self.scene,
                source,
                dsl_session=self.dsl_session,
            )
        except CoreError as error:
            summary = CompileSummary(
                status=ToolStatus.error,
                diagnostics=diagnostics_from(error.diagnostics),
                operation_error={"code": error.code, "message": error.message},
            )
            payload = {"compile": _dump(summary)}
            self._write_json(iteration_dir / "compile.json", payload)
            self.record(
                "dsl-author",
                "dsl_compile_failed",
                input_summary=source[:500],
                output_summary=error.message,
                diagnostics=[diag.model_dump(mode="json") for diag in summary.diagnostics],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        self._replace_scene_from_core_response(response, "compile_dsl_block")
        dsl = response.get("dsl", {})
        self.dsl_session = dsl.get("session_snapshot")
        compile_output = dsl.get("compile_output", {})
        diagnostics = diagnostics_from(compile_output.get("diagnostics", []))
        halted_at = normalize_halt_location(compile_output.get("halted_at"))
        has_blocking_diagnostics = any(
            diagnostic.severity in {DiagnosticSeverity.error, DiagnosticSeverity.blocker}
            for diagnostic in diagnostics
        )
        summary = CompileSummary(
            applied_operations=response.get("applied_operations") or 0,
            operation_count=len(compile_output.get("operations", [])),
            diagnostics=diagnostics,
            halted_at=halted_at,
            operation_error=dsl.get("operation_error"),
            status=(
                ToolStatus.error
                if dsl.get("operation_error") or halted_at or has_blocking_diagnostics
                else ToolStatus.ok
            ),
        )
        payload = {
            "compile": _dump(summary),
            "operations": compile_output.get("operations", []),
            "dsl_session": self.dsl_session,
            "checkpoint_label": compile_output.get("checkpoint_label"),
        }
        self._write_json(iteration_dir / "compile.json", payload)
        self.record(
            "dsl-author",
            "dsl_compiled",
            input_summary=source[:500],
            output_summary=(
                f"{summary.operation_count} operations; "
                f"{len(diagnostics)} DSL diagnostics"
            ),
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def apply_operations(self, operations_json: str) -> str:
        """Apply checked core operations. The input must be a JSON operation list."""
        try:
            operations = json.loads(operations_json)
            if not isinstance(operations, list):
                raise ValueError("operations_json must decode to a list")
            response = self.core.apply_operations(self.scene, operations)
        except (CoreError, ValueError, json.JSONDecodeError) as error:
            diagnostics = []
            if isinstance(error, CoreError):
                diagnostics = diagnostics_from(error.diagnostics)
                message = error.message
                code = error.code
            else:
                message = str(error)
                code = "operations.invalid_input"
            summary = OperationApplicationSummary(
                status=ToolStatus.error,
                diagnostics=diagnostics,
                operation_error={"code": code, "message": message},
            )
            payload = {"operations": _dump(summary)}
            self.record(
                "coordinator",
                "operations_failed",
                input_summary=operations_json[:500],
                output_summary=message,
                diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        self._replace_scene_from_core_response(response, "apply_operations")
        self.dsl_session = None
        diagnostics = diagnostics_from(response.get("diagnostics", []))
        summary = OperationApplicationSummary(
            applied_operations=response.get("applied_operations") or len(operations),
            diagnostics=diagnostics,
        )
        payload = {"operations": _dump(summary)}
        self.record(
            "coordinator",
            "operations_applied",
            input_summary=operations_json[:500],
            output_summary=f"applied {summary.applied_operations} operation(s)",
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def apply_structured_edit(self, edit_json: str) -> str:
        """Apply a typed targeted edit through the Rust edit builder.

        The input must be a JSON object matching the `apply_structured_edit`
        helper contract, for example:

        {
          "kind": "modify",
          "target": {"kind": "node", "id": "headline"},
          "patch": {"kind": "node", "value": {"text": {"content": {"kind": "set", "value": "New copy"}}}}
        }

        Repairs for a concrete critic issue must declare their scope so the
        engine can reject out-of-scope mutations before they happen:

        {
          "kind": "modify",
          "target": {"kind": "node", "id": "headline"},
          "patch": {...},
          "scope": {"mode": "strict", "allowed": [{"kind": "node", "id": "headline"}]}
        }
        """
        scope = None
        try:
            edit = json.loads(edit_json)
            if not isinstance(edit, dict):
                raise ValueError("edit_json must decode to an object")
            scope = edit.pop("scope", None)
            response = self.core.apply_structured_edit(self.scene, edit, scope=scope)
        except (CoreError, ValueError, json.JSONDecodeError) as error:
            diagnostics = []
            if isinstance(error, CoreError):
                diagnostics = diagnostics_from(error.diagnostics)
                message = error.message
                code = error.code
            else:
                message = str(error)
                code = "structured_edit.invalid_input"
            scope_rejected = code == "edit.scope_violation"
            summary = OperationApplicationSummary(
                status=ToolStatus.error,
                diagnostics=diagnostics,
                operation_error={"code": code, "message": message},
            )
            payload = {"structured_edit": _dump(summary)}
            if scope is not None:
                payload["scope"] = scope
                payload["scope_verdict"] = (
                    "rejected" if scope_rejected else "not_evaluated"
                )
            self.record(
                "coordinator",
                "structured_edit_scope_rejected"
                if scope_rejected
                else "structured_edit_failed",
                input_summary=edit_json[:500],
                output_summary=message,
                diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        self._replace_scene_from_core_response(response, "apply_structured_edit")
        if edit.get("kind") in {
            "delete",
            "move_before",
            "move_after",
            "move_to_parent",
            "replace_node",
        }:
            self.dsl_session = None
        diagnostics = diagnostics_from(response.get("diagnostics", []))
        operations = response.get("operations") or []
        summary = OperationApplicationSummary(
            applied_operations=response.get("applied_operations") or len(operations),
            operation_count=len(operations),
            diagnostics=diagnostics,
        )
        payload = {
            "structured_edit": _dump(summary),
            "edit": response.get("edit") or edit,
            "operations": operations,
        }
        if scope is not None:
            payload["scope"] = scope
            payload["scope_verdict"] = "in_scope"
        self.record(
            "coordinator",
            "structured_edit_applied",
            input_summary=edit_json[:500],
            output_summary=f"applied {summary.applied_operations} operation(s)",
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def preflight_design(self) -> str:
        """Run canonical brand/token/layout preflight using the platform default Brand Kit."""
        iteration_dir = self._iteration_dir()
        try:
            brand_kit = self.core.platform_default_brand_kit()
            brand_context = self._brand_context("platform_default", brand_kit)
            response = self.core.preflight_scene(self.scene, brand_kit)
        except CoreError as error:
            summary = PreflightSummary(
                status=ToolStatus.error,
                has_errors=True,
                diagnostics=diagnostics_from(error.diagnostics),
            )
            payload = {"preflight": _dump(summary)}
            self._write_json(iteration_dir / "preflight.json", payload)
            self.record(
                "coordinator",
                "preflight_failed",
                output_summary=error.message,
                diagnostics=[diag.model_dump(mode="json") for diag in summary.diagnostics],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        self._replace_scene_from_core_response(response, "preflight_design")
        diagnostics = diagnostics_from(response.get("diagnostics", []))
        preflight = response.get("preflight", {})
        brand_context = self._brand_context_from_scene_ref(brand_context)
        self.effective_brand_context = brand_context
        summary = PreflightSummary(
            status=ToolStatus.ok,
            has_errors=bool(preflight.get("has_errors")),
            diagnostics=diagnostics,
            brand_source=brand_context.get("source"),
            brand_kit_id=brand_context.get("brand_kit_id"),
            brand_kit_version=brand_context.get("brand_kit_version"),
            brand_mode=brand_context.get("mode"),
        )
        payload = {
            "preflight": _dump(summary),
            "raw_preflight": preflight,
            "effective_brand": brand_context,
        }
        self._write_json(iteration_dir / "preflight.json", payload)
        self.record(
            "coordinator",
            "preflight_completed",
            output_summary=(
                f"has_errors={summary.has_errors}; "
                f"{len(diagnostics)} diagnostics"
            ),
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def export_preview(self, export_format: Optional[str] = None) -> str:
        """Export and validate an SVG or PNG preview for visual critique."""
        preview_format = (export_format or self.config.preview_format).lower()
        iteration_dir = self._iteration_dir()
        try:
            response = self.core.export_preview(self.scene, preview_format)
        except CoreError as error:
            self.latest_export_summary = None
            self.latest_preview_bundle = None
            summary = ExportSummary(
                status=ToolStatus.error,
                requested_format=preview_format,
                diagnostics=diagnostics_from(error.diagnostics),
                validation_errors=[error.message],
            )
            payload = {"export": _dump(summary)}
            self._write_json(iteration_dir / "export.json", payload)
            self.record(
                "coordinator",
                "export_failed",
                output_summary=error.message,
                diagnostics=[diag.model_dump(mode="json") for diag in summary.diagnostics],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        diagnostics = diagnostics_from(response.get("diagnostics", []))
        artifacts = self._write_and_validate_preview_artifacts(
            response.get("export", {}).get("artifacts", []),
            preview_format,
            iteration_dir,
        )
        validation_errors = [
            error for artifact in artifacts for error in artifact.validation_errors
        ]
        status = ToolStatus.error if validation_errors else ToolStatus.ok
        event = "preview_invalid" if validation_errors else "preview_exported"
        summary = ExportSummary(
            status=status,
            requested_format=preview_format,
            diagnostics=diagnostics,
            artifacts=artifacts,
            validation_errors=validation_errors,
        )
        payload = {"export": _dump(summary)}
        if status == ToolStatus.ok:
            self.latest_export_summary = payload["export"]
            self.latest_preview_bundle = None
        else:
            self.latest_export_summary = None
            self.latest_preview_bundle = None
        self._write_json(iteration_dir / "export.json", payload)
        self.record(
            "coordinator",
            event,
            output_summary=(
                f"exported {len(artifacts)} {preview_format} artifact(s); "
                f"{len(validation_errors)} validation error(s)"
            ),
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def export_preview_bundle(
        self,
        critic_format: Optional[str] = None,
        *,
        debug_only: bool = False,
        debug_reason: Optional[str] = None,
    ) -> str:
        """Export canonical SVG plus the configured critic preview artifact.

        SVG remains the canonical preview contract. When the critic format is
        PNG, this stores a raster preview beside the SVG so the reviewer or
        provider adapter can inspect rendered pixels as well as vector source.

        When `debug_only` is true, artifacts are still written to disk, but the
        bundle is intentionally not exposed as a valid critic/final preview.
        Use this after preflight errors so humans and agents can inspect the
        broken visual without weakening the acceptance gate.
        """
        canonical = json.loads(self.export_preview("svg"))
        desired_critic_format = (critic_format or self.config.preview_format).lower()
        critic = canonical
        if desired_critic_format != "svg":
            critic = json.loads(self.export_preview(desired_critic_format))
        canonical_summary = canonical.get("export", canonical)
        critic_summary = critic.get("export", critic)
        bundle_artifacts = combined_preview_artifacts(
            canonical_summary,
            critic_summary,
            desired_critic_format,
        )
        validation_errors = bundle_validation_errors(
            canonical_summary,
            critic_summary,
        )
        if debug_only:
            validation_errors.append(
                debug_reason
                or "debug preview exported from a non-accepted intermediate scene"
            )

        payload = {
            "debug_only": debug_only,
            "debug_reason": debug_reason,
            "canonical": canonical_summary,
            "critic": critic_summary,
            "reviewer": {
                "status": (
                    ToolStatus.error.value
                    if validation_errors
                    else ToolStatus.ok.value
                ),
                "requested_format": desired_critic_format,
                "artifacts": bundle_artifacts,
                "validation_errors": validation_errors,
                "diagnostics": (
                    canonical_summary.get("diagnostics", [])
                    + critic_summary.get("diagnostics", [])
                    if critic_summary is not canonical_summary
                    else canonical_summary.get("diagnostics", [])
                ),
            },
        }
        if not debug_only and payload["reviewer"]["status"] == ToolStatus.ok.value:
            self.latest_preview_bundle = payload["reviewer"]
            self.latest_export_summary = payload["reviewer"]
        else:
            self.latest_preview_bundle = None
            self.latest_export_summary = None
        self._write_json(self._iteration_dir() / "preview_bundle.json", payload)
        self.record(
            "coordinator",
            "debug_preview_exported" if debug_only else "preview_bundle_exported",
            output_summary=(
                (
                    f"exported debug preview after {debug_reason}"
                    if debug_only
                    else (
                        "exported canonical svg"
                        if desired_critic_format == "svg"
                        else f"exported canonical svg and {desired_critic_format} critic preview"
                    )
                )
            ),
            payload={
                "critic_format": desired_critic_format,
                "debug_only": debug_only,
                "debug_reason": debug_reason,
                "canonical_status": payload["canonical"].get("status"),
                "critic_status": payload["critic"].get("status"),
                "reviewer_status": payload["reviewer"].get("status"),
                "reviewer_artifact_formats": [
                    artifact.get("format")
                    for artifact in payload["reviewer"].get("artifacts", [])
                ],
            },
        )
        return json.dumps(payload, indent=2)

    def get_latest_preview_for_critique(self, max_svg_chars: int = 40000) -> str:
        """Return the latest validated preview payload for visual review.

        SVG artifacts are returned as text because the model can inspect
        geometry directly. PNG artifacts are returned as base64 so a
        vision-capable provider adapter can turn them into an image message.
        """
        latest_preview = self.latest_preview_bundle or self.latest_export_summary
        if not latest_preview:
            payload = {
                "status": ToolStatus.error.value,
                "message": "no preview is available; latest preview is invalid or no valid preview has been exported for this run",
            }
            self.record(
                "coordinator",
                "critic_preview_missing",
                output_summary=payload["message"],
                payload=payload,
            )
            return json.dumps(payload, indent=2)
        if latest_preview.get("status") != ToolStatus.ok.value:
            payload = {
                "status": ToolStatus.error.value,
                "message": "latest preview is invalid and cannot be sent to the critic",
                "preview": latest_preview,
            }
            self.record(
                "coordinator",
                "critic_preview_invalid",
                output_summary=payload["message"],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        artifacts = []
        content_errors: list[str] = []
        for artifact in latest_preview.get("artifacts", []):
            if artifact.get("valid") is False or artifact.get("validation_errors"):
                content_errors.extend(
                    artifact.get("validation_errors")
                    or [f"artifact {artifact.get('format')} is marked invalid"]
                )
                continue
            path_value = artifact.get("path")
            if not path_value:
                content_errors.append(
                    f"artifact {artifact.get('format')} does not include a path"
                )
                continue
            path = Path(path_value)
            if not path.exists():
                content_errors.append(f"artifact path {path} does not exist")
                continue
            item = dict(artifact)
            if artifact.get("format") == "svg":
                text = path.read_text(encoding="utf-8", errors="replace")
                item["svg_text"] = text[:max_svg_chars]
                item["truncated"] = len(text) > max_svg_chars
            elif artifact.get("format") == "png":
                raw = path.read_bytes()
                item["base64"] = base64.b64encode(raw).decode("ascii")
                item["encoding"] = "base64"
            else:
                content_errors.append(
                    f"unsupported critic payload format {artifact.get('format')}"
                )
                continue
            artifacts.append(item)

        if content_errors or not artifacts:
            message = (
                "latest preview is invalid and cannot be sent to the critic"
                if content_errors
                else "latest preview has no critic-readable artifacts"
            )
            payload = {
                "status": ToolStatus.error.value,
                "message": message,
                "content_errors": content_errors,
                "preview": latest_preview,
            }
            self.record(
                "coordinator",
                "critic_preview_invalid",
                output_summary=message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        payload = {
            "status": ToolStatus.ok.value,
            "run_id": self.run_id,
            "iteration": self.iteration,
            "artifacts": artifacts,
        }
        self.record(
            "coordinator",
            "critic_preview_loaded",
            output_summary=f"loaded {len(artifacts)} preview artifact(s) for critique",
            payload={
                "artifact_count": len(artifacts),
                "formats": [artifact.get("format") for artifact in artifacts],
            },
        )
        return json.dumps(payload, indent=2)

    def submit_visual_critique(self, critique_json: str) -> str:
        """Persist structured reviewer output and fail closed on malformed critique JSON."""
        iteration_dir = self._iteration_dir()
        try:
            critique = VisualCritique.model_validate_json(critique_json)
        except Exception as error:  # pydantic raises provider/version-specific errors.
            raw_payload = parse_json_object(critique_json)
            message = (
                str(raw_payload.get("provider_error"))
                if isinstance(raw_payload, dict) and raw_payload.get("provider_error")
                else str(error)
            )
            payload = {
                "status": ToolStatus.error.value,
                "stop_reason": StopReason.critic_failed.value,
                "message": message,
                "validation_error": str(error),
                "raw": critique_json,
            }
            self._write_json(iteration_dir / "critique.json", payload)
            self.record(
                "visual-reviewer",
                "critique_failed",
                input_summary=critique_json[:500],
                output_summary=str(error),
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        payload = {"status": ToolStatus.ok.value, "critique": critique.model_dump(mode="json")}
        self._write_json(iteration_dir / "critique.json", payload)
        self.record(
            "visual-reviewer",
            "critique_result",
            input_summary=critique_json[:500],
            output_summary=(
                "accepted" if critique.accepted else "rejected: " + critique.summary[:300]
            ),
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def recommend_edit_surface(self, intent: str, context_json: str = "{}") -> str:
        """Recommend a conservative edit surface for an agent repair or creation step."""
        try:
            context = json.loads(context_json)
        except json.JSONDecodeError:
            context = {}
        lower = f"{intent} {json.dumps(context, sort_keys=True)}".lower()
        target_keys = ("node_id", "page_id", "slot_id", "slot_key", "target")
        if any(word in lower for word in ("generate image", "asset", "logo", "vectorize")):
            recommendation = EditSurfaceRecommendation.asset_tool
        elif any(key in context for key in target_keys) or any(key in lower for key in target_keys):
            recommendation = EditSurfaceRecommendation.structured_ops
        elif any(word in lower for word in ("create", "compose", "design", "layout", "draft")):
            recommendation = EditSurfaceRecommendation.dsl
        else:
            recommendation = EditSurfaceRecommendation.external_planner
        payload = {
            "recommendation": recommendation.value,
            "reason": "conservative_phase_a_rule",
        }
        self.record(
            "coordinator",
            "edit_surface_recommended",
            input_summary=intent[:500],
            output_summary=recommendation.value,
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def create_repair_request(
        self,
        exact_feedback: str,
        diagnostics_json: str = "[]",
        target_json: str = "{}",
        allowed_edit_surface: str = "dsl",
        forbidden_changes_json: str = "[]",
    ) -> str:
        """Create and persist a repair request without paraphrasing reviewer feedback."""
        diagnostics = diagnostics_from(json.loads(diagnostics_json))
        target_payload = json.loads(target_json)
        forbidden_changes = json.loads(forbidden_changes_json)
        request = RepairRequest(
            original_user_request=self.prompt,
            exact_feedback=exact_feedback,
            diagnostics=diagnostics,
            target=VisualTarget.model_validate(target_payload) if target_payload else None,
            scene_summary=self._scene_summary(),
            allowed_edit_surface=EditSurfaceRecommendation(allowed_edit_surface),
            forbidden_changes=forbidden_changes,
        )
        payload = {"repair_request": request.model_dump(mode="json")}
        self._write_json(self._iteration_dir() / "repair_request.json", payload)
        self.record(
            "coordinator",
            "repair_requested",
            input_summary=exact_feedback[:500],
            output_summary=f"repair via {allowed_edit_surface}",
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def record_gap(
        self,
        area: str,
        summary: str,
        evidence: str,
        suggested_phase: Optional[str] = None,
    ) -> str:
        """Record a product gap instead of hiding unsupported semantics in prompts."""
        gap = GapRecord(
            area=GapArea(area),
            summary=summary,
            evidence=evidence,
            suggested_phase=suggested_phase,
        )
        payload = gap.model_dump(mode="json")
        self.gaps.append(payload)
        self._write_json(self.trace_dir / "gaps.json", {"gaps": self.gaps})
        self.record(
            "coordinator",
            "gap_recorded",
            input_summary=evidence[:500],
            output_summary=f"{area}: {summary}",
            payload=payload,
        )
        return json.dumps({"gap": payload}, indent=2)

    def summarize_scene(self) -> str:
        """Return a compact document scene summary for planning or repair targeting."""
        return json.dumps(self._scene_summary(), indent=2)

    def summarize_page(self, page_id: str) -> str:
        """Return a page-specific node and geometry summary."""
        pages = self.scene.get("pages", {})
        page = pages.get(page_id)
        if page is None:
            return json.dumps({"status": "missing", "page_id": page_id}, indent=2)
        return json.dumps(
            {
                "status": "ok",
                "page": self._page_summary(page_id, page),
                "node_tree": self._node_tree(page.get("children", [])),
            },
            indent=2,
        )

    def summarize_slots(self) -> str:
        """Return slot-to-node binding summaries."""
        return json.dumps({"slots": self._slot_summaries()}, indent=2)

    def summarize_node_tree(self, page_id: str) -> str:
        """Return the node hierarchy for one page."""
        page = self.scene.get("pages", {}).get(page_id)
        if page is None:
            return json.dumps({"status": "missing", "page_id": page_id}, indent=2)
        return json.dumps(
            {"status": "ok", "page_id": page_id, "node_tree": self._node_tree(page.get("children", []))},
            indent=2,
        )

    def query_geometry(self, node_id: str) -> str:
        """Return stored computed geometry and declared transform/size for a node."""
        node = self.scene.get("nodes", {}).get(node_id)
        if node is None:
            return json.dumps({"status": "missing", "node_id": node_id}, indent=2)
        return json.dumps(
            {
                "status": "ok",
                "node_id": node_id,
                "transform": node.get("transform"),
                "size": node.get("size"),
                "computed": node.get("computed"),
            },
            indent=2,
        )

    def query_slot_bindings(self, slot_key: str) -> str:
        """Return binding details for a semantic slot key."""
        matches = [
            (slot_id, slot)
            for slot_id, slot in self.scene.get("slots", {}).items()
            if slot.get("key") == slot_key or slot_id == slot_key
        ]
        return json.dumps(
            {
                "status": "ok" if matches else "missing",
                "query": slot_key,
                "slots": [
                    {
                        "id": slot_id,
                        "key": slot.get("key"),
                        "content_type": slot.get("content_type"),
                        "bound_nodes": [
                            self._node_brief(node_id)
                            for node_id in slot.get("bound_nodes", [])
                        ],
                    }
                    for slot_id, slot in matches
                ],
            },
            indent=2,
        )

    def persist_trace_event(
        self,
        actor: str,
        event: str,
        output_summary: str,
        payload_json: str = "{}",
    ) -> str:
        """Persist an explicit trace event supplied by the coordinator or a subagent."""
        payload = json.loads(payload_json)
        self.record(actor, event, output_summary=output_summary, payload=payload)
        return json.dumps({"status": "persisted", "run_id": self.run_id}, indent=2)

    def finalize_run(
        self,
        status: str,
        stop_reason: str,
        summary: str,
        critique_json: str = "{}",
    ) -> str:
        """Write the final run summary in a later-API-compatible local format."""
        critique = json.loads(critique_json) if critique_json.strip() else {}
        payload = {
            "run_id": self.run_id,
            "status": status,
            "stop_reason": stop_reason,
            "summary": summary,
            "final_scene_summary": self._scene_summary(),
            "effective_brand": self.effective_brand_context,
            "preview_paths": self.preview_paths,
            "critique": critique,
            "gaps": self.gaps,
            "scene_update_sources": self.scene_update_sources,
        }
        self._write_json(self.trace_dir / "final.json", payload)
        self.record(
            "coordinator",
            "run_finalized",
            output_summary=f"{status}: {stop_reason}",
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def record(
        self,
        actor: str,
        event: str,
        input_summary: Optional[str] = None,
        output_summary: Optional[str] = None,
        diagnostics: Optional[List[JsonObject]] = None,
        payload: Optional[JsonObject] = None,
    ) -> None:
        trace = LumenRunTraceEvent(
            run_id=self.run_id,
            iteration=self.iteration,
            actor=actor,
            event=event,
            input_summary=input_summary,
            output_summary=output_summary,
            diagnostics=diagnostics or [],
            payload=payload or {},
        )
        path = self.trace_dir / "trace.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(trace.model_dump_json() + "\n")

    def _replace_scene_from_core_response(self, response: JsonObject, source: str) -> None:
        scene = response.get("scene")
        if not isinstance(scene, dict):
            raise CoreError("helper.scene_missing", f"{source} did not return a scene")
        self.scene = scene
        self.scene_update_sources.append(source)

    def _write_and_validate_preview_artifacts(
        self,
        raw_artifacts: list[JsonObject],
        requested_format: str,
        iteration_dir: Path,
    ) -> list[PreviewArtifact]:
        if not raw_artifacts:
            return [
                PreviewArtifact(
                    format=requested_format,
                    mime_type="",
                    byte_len=0,
                    valid=False,
                    validation_errors=["export returned no artifacts"],
                )
            ]

        artifacts: list[PreviewArtifact] = []
        for index, artifact in enumerate(raw_artifacts, start=1):
            raw_bytes = bytes(artifact.get("bytes", []))
            artifact_format = str(artifact.get("format") or requested_format).lower()
            page_id = artifact.get("page_id")
            suffix = "svg" if artifact_format == "svg" else artifact_format
            path = iteration_dir / f"preview.{suffix}" if len(raw_artifacts) == 1 else iteration_dir / f"preview_{index}.{suffix}"
            path.write_bytes(raw_bytes)
            self.preview_paths.append(str(path))
            width, height = self._page_dimensions(page_id)
            validation_errors = validate_preview_bytes(
                raw_bytes,
                artifact_format,
                requested_format,
            )
            artifacts.append(
                PreviewArtifact(
                    format=artifact_format,
                    mime_type=artifact.get("mime_type") or "",
                    page_id=page_id,
                    byte_len=len(raw_bytes),
                    path=str(path),
                    width=width,
                    height=height,
                    aspect_ratio=width / height if width and height else None,
                    critic_input_path=str(path),
                    valid=not validation_errors,
                    validation_errors=validation_errors,
                )
            )
        return artifacts

    def _iteration_dir(self) -> Path:
        index = max(self.iteration, 1)
        path = self.iterations_dir / f"{index:03d}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _scene_summary(self) -> JsonObject:
        pages = self.scene.get("pages", {})
        nodes = self.scene.get("nodes", {})
        slots = self.scene.get("slots", {})
        return {
            "document_id": self.scene.get("meta", {}).get("id"),
            "title": self.scene.get("meta", {}).get("title"),
            "status": self.scene.get("meta", {}).get("status"),
            "brand_kit": self.scene.get("meta", {}).get("brand_kit"),
            "effective_brand": self.effective_brand_context,
            "page_count": len(pages),
            "node_count": len(nodes),
            "slot_count": len(slots),
            "asset_count": len(self.scene.get("assets", {})),
            "pages": [
                self._page_summary(page_id, page) for page_id, page in pages.items()
            ],
            "slots": self._slot_summaries(),
        }

    def _page_summary(self, page_id: str, page: JsonObject) -> JsonObject:
        width, height = self._page_dimensions(page_id)
        return {
            "id": page_id,
            "name": page.get("name"),
            "size": page.get("size"),
            "width": width,
            "height": height,
            "aspect_ratio": width / height if width and height else None,
            "children": page.get("children", []),
            "child_count": len(page.get("children", [])),
        }

    def _slot_summaries(self) -> list[JsonObject]:
        return [
            {
                "id": slot_id,
                "key": slot.get("key"),
                "content_type": slot.get("content_type"),
                "scope": slot.get("scope"),
                "bound_nodes": [
                    self._node_brief(node_id) for node_id in slot.get("bound_nodes", [])
                ],
            }
            for slot_id, slot in self.scene.get("slots", {}).items()
        ]

    def _node_tree(self, node_ids: list[str]) -> list[JsonObject]:
        return [self._node_with_children(node_id) for node_id in node_ids]

    def _node_with_children(self, node_id: str) -> JsonObject:
        node = self.scene.get("nodes", {}).get(node_id)
        if node is None:
            return {"id": node_id, "missing": True}
        brief = self._node_brief(node_id)
        brief["children"] = self._node_tree(node.get("children", []))
        return brief

    def _node_brief(self, node_id: str) -> JsonObject:
        node = self.scene.get("nodes", {}).get(node_id)
        if node is None:
            return {"id": node_id, "missing": True}
        kind = node.get("kind", {})
        kind_name = kind.get("kind") if isinstance(kind, dict) else kind
        slots = [
            slot.get("key")
            for slot in self.scene.get("slots", {}).values()
            if node_id in slot.get("bound_nodes", [])
        ]
        return {
            "id": node_id,
            "name": node.get("name"),
            "kind": kind_name,
            "text": kind.get("content") if isinstance(kind, dict) else None,
            "transform": node.get("transform"),
            "size": node.get("size"),
            "computed": node.get("computed"),
            "slots": slots,
            "source_asset_id": node.get("source_asset_id"),
        }

    def _page_dimensions(self, page_id: Optional[str]) -> tuple[Optional[float], Optional[float]]:
        if not page_id:
            return None, None
        page = self.scene.get("pages", {}).get(page_id)
        if not page:
            return None, None
        size = page.get("size") or {}
        width = size.get("width")
        height = size.get("height")
        return _as_float(width), _as_float(height)

    def _brand_context(self, source: str, brand_kit: JsonObject) -> JsonObject:
        mode = brand_mode_from_kit(brand_kit)
        scene_medium = scene_medium_token(self.scene)
        if scene_medium:
            mode["medium"] = scene_medium
        return {
            "source": source,
            "brand_kit_id": brand_kit.get("id"),
            "brand_kit_version": (
                str(brand_kit.get("version"))
                if brand_kit.get("version") is not None
                else None
            ),
            "brand_kit_name": brand_kit.get("name"),
            "mode": mode,
        }

    def _brand_context_from_scene_ref(self, context: JsonObject) -> JsonObject:
        brand_ref = self.scene.get("meta", {}).get("brand_kit") or {}
        if brand_ref.get("brand_kit_id") or brand_ref.get("id"):
            context = {
                **context,
                "brand_kit_id": brand_ref.get("brand_kit_id") or brand_ref.get("id"),
            }
        if brand_ref.get("version") is not None:
            context = {
                **context,
                "brand_kit_version": str(brand_ref.get("version")),
            }
        scene_medium = scene_medium_token(self.scene)
        if scene_medium:
            context = {
                **context,
                "mode": {
                    **(context.get("mode") or {}),
                    "medium": scene_medium,
                },
            }
        return context

    def _write_json(self, path: Path, payload: JsonObject) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def validate_preview_bytes(
    raw_bytes: bytes,
    artifact_format: str,
    requested_format: str,
) -> list[str]:
    errors: list[str] = []
    if artifact_format != requested_format:
        errors.append(
            f"artifact format {artifact_format} does not match requested {requested_format}"
        )
    if not raw_bytes:
        errors.append("artifact bytes are empty")
        return errors
    if artifact_format == "svg":
        text = raw_bytes.decode("utf-8", errors="ignore").lstrip()
        if "<svg" not in text[:300]:
            errors.append("SVG preview does not contain an <svg root near the start")
    elif artifact_format == "png":
        if not raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            errors.append("PNG preview has an invalid PNG signature")
    else:
        errors.append(f"unsupported visual preview format {artifact_format}")
    return errors


def combined_preview_artifacts(
    canonical_summary: JsonObject,
    critic_summary: JsonObject,
    critic_format: str,
) -> list[JsonObject]:
    canonical_artifacts = list(canonical_summary.get("artifacts", []))
    if critic_format == "svg":
        return canonical_artifacts
    return canonical_artifacts + list(critic_summary.get("artifacts", []))


def bundle_validation_errors(
    canonical_summary: JsonObject,
    critic_summary: JsonObject,
) -> list[str]:
    errors: list[str] = []
    for label, summary in (("canonical", canonical_summary), ("critic", critic_summary)):
        if summary.get("status") != ToolStatus.ok.value:
            errors.append(f"{label} preview status is {summary.get('status')}")
        errors.extend(
            f"{label}: {error}"
            for error in summary.get("validation_errors", [])
        )
        for artifact in summary.get("artifacts", []):
            errors.extend(
                f"{label} {artifact.get('format')}: {error}"
                for error in artifact.get("validation_errors", [])
            )
    return errors


def reviewer_bundle_status(
    canonical_summary: JsonObject,
    critic_summary: JsonObject,
) -> str:
    return (
        ToolStatus.error.value
        if bundle_validation_errors(canonical_summary, critic_summary)
        else ToolStatus.ok.value
    )


def brand_mode_from_kit(brand_kit: JsonObject) -> JsonObject:
    modes = brand_kit.get("modes")
    defaults = modes.get("defaults") if isinstance(modes, dict) else None
    if isinstance(defaults, dict):
        return {str(axis): str(value) for axis, value in defaults.items()}

    default_mode = brand_kit.get("default_mode")
    values = default_mode.get("values") if isinstance(default_mode, dict) else None
    if isinstance(values, dict):
        return {str(axis): str(value) for axis, value in values.items()}
    return {}


def scene_medium_token(scene: JsonObject) -> Optional[str]:
    medium = scene.get("meta", {}).get("medium")
    if medium in {"print", "direct_mail"}:
        return "print"
    if medium in {"digital", "email", "ad"}:
        return "digital"
    return None


def normalize_halt_location(raw_halt: Any) -> Optional[JsonObject]:
    if raw_halt is None:
        return None
    if isinstance(raw_halt, dict):
        normalized: JsonObject = {}
        for key in ("code", "line", "column", "message"):
            if key in raw_halt and raw_halt[key] is not None:
                normalized[key] = raw_halt[key]
        return normalized or {"value": raw_halt}
    if isinstance(raw_halt, int):
        return {"line": raw_halt}
    return {"value": str(raw_halt)}


def parse_json_object(source: str) -> Optional[JsonObject]:
    try:
        parsed = json.loads(source)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def diagnostics_from(raw_diagnostics: Any) -> list[DiagnosticSummary]:
    diagnostics: list[DiagnosticSummary] = []
    if not isinstance(raw_diagnostics, list):
        return diagnostics
    for raw in raw_diagnostics:
        if not isinstance(raw, dict):
            continue
        span = raw.get("span") or {}
        subject = raw.get("subject") or {}
        target_page_id = None
        target_node_id = None
        target_slot_id = None
        if isinstance(subject, dict):
            kind = subject.get("kind")
            value = subject.get("id") or subject.get("value")
            if kind == "page":
                target_page_id = value
            elif kind == "node":
                target_node_id = value
            elif kind == "slot":
                target_slot_id = value
        target_page_id = target_page_id or raw.get("target_page_id")
        target_node_id = target_node_id or raw.get("target_node_id")
        target_slot_id = target_slot_id or raw.get("target_slot_id")
        severity = str(raw.get("severity") or "info").lower()
        if severity not in {item.value for item in DiagnosticSeverity}:
            severity = "info"
        diagnostics.append(
            DiagnosticSummary(
                severity=DiagnosticSeverity(severity),
                code=raw.get("code"),
                message=str(raw.get("message") or raw.get("detail") or raw),
                line=span.get("line") or raw.get("line"),
                column=span.get("column") or raw.get("column"),
                target_page_id=target_page_id,
                target_node_id=target_node_id,
                target_slot_id=target_slot_id,
                target_slot_key=raw.get("slot_key"),
                suggested_repair=raw.get("hint") or raw.get("suggested_repair"),
            )
        )
    return diagnostics


def first_existing_page_declaration(source: str, scene: JsonObject) -> Optional[JsonObject]:
    existing_pages = set((scene.get("pages") or {}).keys())
    if not existing_pages:
        return None
    for line_number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        page_id = declared_page_id(stripped)
        if page_id and page_id in existing_pages:
            return {"page_id": page_id, "line": line_number}
    return None


def declared_page_id(stripped_line: str) -> Optional[str]:
    if stripped_line.startswith("page("):
        close = stripped_line.find(")")
        if close == -1:
            return None
        return stripped_line[len("page(") : close].strip() or None
    if stripped_line == "page" or not stripped_line.startswith("page "):
        return None
    parts = stripped_line.split()
    return parts[1] if len(parts) > 1 else None


def _dump(model: Any) -> JsonObject:
    return model.model_dump(mode="json")


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None
