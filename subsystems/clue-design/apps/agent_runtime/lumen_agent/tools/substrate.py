from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from lumen_api.core import CoreClient, CoreError

try:  # the real Python text-to-image seam, shared with the /assets/generate route
    from lumen_api import image_provider
except Exception:  # pragma: no cover - keeps the runtime importable without the API package
    image_provider = None  # type: ignore[assignment]

try:  # generation cache (request -> asset), so the loop doesn't re-pay per iteration
    from lumen_api import image_cache
except Exception:  # pragma: no cover
    image_cache = None  # type: ignore[assignment]

from ..config import AgentRuntimeConfig
from ..retokenize import build_logo_placement_operations, build_retokenize_operations
from ..brand_card import build_brand_card
from ..knowledge import BRAND_APPLICATION_PATH, DIRECTIVES_PATH, read_task_knowledge
from ..models.schemas import (
    CompileSummary,
    DiagnosticSeverity,
    DiagnosticSummary,
    EditSurfaceRecommendation,
    ExportSummary,
    GapArea,
    GapRecord,
    KnowledgeLoadResult,
    KnowledgeSnippet,
    LayoutClusterTarget,
    LumenRunTraceEvent,
    OperationApplicationSummary,
    PreflightSummary,
    PreviewArtifact,
    RepairClass,
    RepairRequest,
    StopReason,
    ToolStatus,
    VisualCritique,
    VisualTarget,
    new_run_id,
)


JsonObject = Dict[str, Any]

# A progress hook: (event_type, event_data) for each recorded trace event.
# Kept dependency-free so agent_runtime never imports the API/DB layer.
EventSink = Callable[[str, JsonObject], None]


# Hard caps for the curated, windowed per-iteration context (P1). They keep the
# director/author/reviewer prompt bounded no matter how many repair iterations
# run. The context is rebuilt fresh each iteration from canonical in-memory
# state and is NEVER written back into the trace, so it cannot self-nest or grow
# unboundedly across iterations (the failure mode that exploded the old
# `full_activity_context` past the token limit).
CONTEXT_MAX_DIAGNOSTICS = 12
CONTEXT_MAX_SUBTREE_NODES = 24
CONTEXT_MAX_VISIBLE_TEXT = 40
CONTEXT_MAX_ATTEMPTS = 6
CONTEXT_MAX_KNOWLEDGE = 6
CONTEXT_MAX_KNOWLEDGE_EXCERPT = 800
CONTEXT_MAX_CRITIQUE_ISSUES = 12
CONTEXT_MAX_SVG_SNIPPET = 4000
CONTEXT_MAX_TEXT_LEN = 120

# Slice 2 (Loop Vision): the Director receives thumbnails of the kit's assets so it
# chooses imagery/logo placements by LOOKING (subject, contrast, baked text), not by
# metadata alone. The reviewer receives the SOURCE thumbnails of the assets a scene
# actually placed so it can verify each placement against its source. Both are capped
# — only paths + small labels ride the context dicts; base64 is produced per call at
# the model boundary (see providers), never accumulated in a persisted dict.
CONTACT_SHEET_MAX = 6
PLACED_PREVIEWS_MAX = 4
# Raster mime types the vision APIs accept as a direct preview when no derived
# thumbnail exists (an SVG has no raster preview → it is skipped, never a broken path).
_PREVIEWABLE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}

# Diagnostic codes that indicate content does not fit its frame (text overflow)
# or a layout cluster is mis-sized — surfaced as `overflow` in the preview
# summary so the director sees them without the raw scene.
CONTEXT_OVERFLOW_CODES = {
    "LUMV0902",
    "LUMV0903",
    "LUMV0904",
    "LUMV0810",
    "LUMV0800",
    "LUMV0801",
    "LUMV0803",
    "LUMV0805",
}


def _extract_diagnostics(entry: JsonObject) -> list:
    """Pull the diagnostics list out of a feedback entry, whatever its kind."""
    if not isinstance(entry, dict):
        return []
    inner = entry.get("feedback")
    if isinstance(inner, dict):
        diags = inner.get("diagnostics")
        if isinstance(diags, list):
            return diags
        compile_summary = inner.get("compile_summary")
        if isinstance(compile_summary, dict) and isinstance(
            compile_summary.get("diagnostics"), list
        ):
            return compile_summary["diagnostics"]
    repair_request = entry.get("repair_request")
    if isinstance(repair_request, dict) and isinstance(
        repair_request.get("diagnostics"), list
    ):
        return repair_request["diagnostics"]
    return []


def _feedback_one_liner(entry: JsonObject) -> str:
    """One short human line describing what an attempt produced/why it failed."""
    if not isinstance(entry, dict):
        return ""
    if entry.get("kind") == "visual":
        critique = entry.get("feedback") or {}
        return str(critique.get("summary") or "")[:200]
    for diagnostic in _extract_diagnostics(entry):
        if isinstance(diagnostic, dict) and diagnostic.get("message"):
            return str(diagnostic["message"])[:200]
    for key in ("reason", "violation", "message", "summary"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            return value[:200]
    return str(entry.get("recommended_edit_surface") or "")[:200]


def _is_render_export_issue(diagnostics: list, previous_feedback: list) -> bool:
    """True only when the raw vector/export output is the subject of repair."""
    for diagnostic in diagnostics or []:
        if not isinstance(diagnostic, dict):
            continue
        code = diagnostic.get("code") or ""
        message = (diagnostic.get("message") or "").lower()
        if code.startswith("LUME") or "export" in message or "render" in message:
            return True
    return False


class LumenDesignTools:
    def __init__(
        self,
        config: AgentRuntimeConfig,
        prompt: str,
        initial_scene: Optional[JsonObject] = None,
        event_sink: Optional["EventSink"] = None,
    ) -> None:
        self.config = config
        self.core = CoreClient(repo_root=config.repo_root)
        # Optional progress hook: every recorded trace event is also handed to
        # this sink so a caller (the API's async turn) can persist it to a
        # durable store and stream it. None keeps the run purely file-traced.
        self.event_sink = event_sink
        self.run_id = new_run_id()
        self.iteration = 0
        self.trace_dir = config.trace_dir / self.run_id
        self.iterations_dir = self.trace_dir / "iterations"
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.iterations_dir.mkdir(parents=True, exist_ok=True)
        # Phase 0a: a caller (the editor's /agent/turn-preview) can seed the
        # working scene from the live canonical scene so targeted edits land on
        # existing NodeIds. Without a seed the run starts from a fresh scene.
        self.seeded_from_initial_scene = initial_scene is not None
        if initial_scene is not None:
            self.scene = copy.deepcopy(initial_scene)
        else:
            self.scene = self.core.new_scene(self.run_id, "Agent-authored design")
        # Slice 3 phase B: the human contract. On a seeded turn the seed scene's
        # node ids are PROTECTED — a reconcile block that omits one keeps it
        # (LUMD0262) rather than deleting human/seed content. Computed once here
        # so every compile call carries the same frozen set; None on fresh runs
        # yields pure declarative reconcile semantics.
        self.protected_node_ids: Optional[list[str]] = (
            sorted((initial_scene.get("nodes") or {}).keys())
            if initial_scene is not None
            else None
        )
        self.prompt = prompt
        self.preview_paths: list[str] = []
        self.loaded_knowledge: list[JsonObject] = []
        self.gaps: list[JsonObject] = []
        self.scene_update_sources: list[str] = (
            ["initial_scene_seed"] if self.seeded_from_initial_scene else []
        )
        # K2 accept-seam: ordered {iteration, source, operation} entries for
        # every applied scene mutation — the proposal's op source of truth
        # (see _log_scene_operations).
        self.operations_ledger: list[JsonObject] = []
        self.effective_brand_context: Optional[JsonObject] = None
        # K1: compact brand context card, built once from the by-value kit in
        # config (None without a kit). Injected via load_knowledge and
        # curated_context — the full kit JSON never enters model history.
        self.brand_card: Optional[JsonObject] = build_brand_card(
            config.brand_kit, source=config.brand_kit_source
        )
        self.dsl_session: Optional[JsonObject] = None
        self.latest_export_summary: Optional[JsonObject] = None
        self.latest_preview_bundle: Optional[JsonObject] = None
        # Agent-improvement follow-up 1: memoized pre-existing-diagnostics
        # baseline, populated on first access by `baseline_preflight_diagnostics`.
        # None means "not computed yet" (distinct from `[]`, "computed, clean").
        self._baseline_diagnostics: Optional[list[JsonObject]] = None
        self._write_json(
            self.trace_dir / "input.json",
            {
                "run_id": self.run_id,
                "prompt": prompt,
                "seeded_from_initial_scene": self.seeded_from_initial_scene,
                # Agent-improvement follow-up 3: the initial brief carries the
                # same scene summary (freehand/frozen-doc state included) that
                # repair requests already see, so the author is never blind to
                # frozen geometry on the FIRST pass — only during repairs.
                "scene_summary": self._scene_summary(),
            },
        )
        self.record(
            "coordinator",
            "run_started",
            input_summary=prompt[:500],
            output_summary=(
                f"seeded scene from initial_scene "
                f"({len(self.scene.get('nodes', {}))} nodes, "
                f"{len(self.scene.get('pages', {}))} pages)"
                if self.seeded_from_initial_scene
                else f"created scene {self.run_id}"
            ),
            payload={
                "scene_update_policy": "core_response_only",
                "seeded_from_initial_scene": self.seeded_from_initial_scene,
                "seed_node_count": len(self.scene.get("nodes", {})),
                "seed_page_count": len(self.scene.get("pages", {})),
            },
        )

    def load_knowledge(self, query: str) -> str:
        """Load task-specific Lumen knowledge snippets with provenance."""
        snippets = read_task_knowledge(
            self.config.repo_root,
            query,
            # A seeded turn edits an existing document, so the modify/ref
            # grammar (`#page:` form, directives-are-node-only) must always be
            # loaded — the recipe inlines the essentials, but the full table
            # stays one load away (agent-improvement backlog).
            extra_mandatory_paths=(
                ([DIRECTIVES_PATH] if self.seeded_from_initial_scene else [])
                # K1: a run with an attached kit always gets the brand
                # decide table (intensity per archetype, CTA/accent rule,
                # logo-variant rules) — same pattern as images/decide.
                + ([BRAND_APPLICATION_PATH] if self.brand_card else [])
            ),
        )
        result = KnowledgeLoadResult(query=query, snippets=snippets)
        payload = _dump(result)
        if self.brand_card:
            # The card rides the knowledge payload so the coordinator (and the
            # author via task context) reasons from the kit's ACTUAL roles,
            # accent, and inventory — not from guessed token names.
            # Through the KnowledgeSnippet model, not a hand-rolled dict — the
            # quality loop re-validates every snippet (loop.py), so a shape
            # drift here kills the whole turn (found by the K1 live proof).
            payload["snippets"].append(
                KnowledgeSnippet(
                    path=f"brand-kit:{self.brand_card['kit'].get('id')}",
                    title="Brand context card (this document's attached kit)",
                    score=100,
                    excerpt=json.dumps(self.brand_card, indent=1),
                    category="brand",
                    selected_reason="attached_brand_kit",
                ).model_dump(mode="json")
            )
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
                protected_node_ids=self.protected_node_ids,
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
        # K2: `image asset(<kit asset id>)` written straight in DSL registers
        # nothing — reconcile against the kit manifest so the natural form
        # renders instead of dangling (see _register_referenced_brand_assets).
        self._register_referenced_brand_assets("compile_dsl_block")
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
        # Ledger: only a CLEAN compile's ops ride proposals — the same gate
        # the legacy compile.json scrape applied in agent_response_from_trace.
        if summary.status == ToolStatus.ok:
            self._log_scene_operations(
                "compile_dsl_block", compile_output.get("operations", [])
            )
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

        self._replace_scene_from_core_response(response, "apply_operations", operations)
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

        self._replace_scene_from_core_response(
            response, "apply_structured_edit", response.get("operations") or []
        )
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

    def generate_qr(
        self,
        data: str,
        ec_level: Optional[str] = None,
        print_media: bool = False,
        target_width_mm: Optional[float] = None,
        label: Optional[str] = None,
    ) -> str:
        """Generate a deterministic QR code asset (URL/text -> sanitized SVG)
        and register it in the scene. Use print_media=True for physical
        artifacts (error correction H); declare target_width_mm so print
        scannability diagnostics can fire. Place the returned asset with a
        place_asset_in_node/place_asset_in_slot operation."""
        asset_id = f"asset_qr_{self.run_id[:8]}_{len(self.scene.get('assets', {}))}"
        try:
            response = self.core.generate_qr(
                store_root=str(self.config.effective_asset_store_root),
                data=data,
                asset_id=asset_id,
                label=label,
                ec_level=ec_level,
                print_media=print_media,
                target_width_mm=target_width_mm,
            )
        except CoreError as error:
            payload = {
                "qr": {
                    "status": "error",
                    "error_code": error.code,
                    "message": error.message,
                },
                "diagnostics": [
                    diag.model_dump(mode="json")
                    for diag in diagnostics_from(error.diagnostics)
                ],
            }
            self.record(
                "coordinator",
                "qr_generation_failed",
                output_summary=error.message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        asset_payload = response.get("asset") or {}
        record = asset_payload.get("record") or {}
        try:
            apply_response = self.core.apply_operations(
                self.scene, [{"kind": "upsert_asset", "asset": record}]
            )
        except CoreError as error:
            payload = {
                "qr": {
                    "status": "error",
                    "error_code": error.code,
                    "message": error.message,
                    "asset_id": record.get("id"),
                },
                "hint": (
                    "The QR was generated but could not be registered in the scene "
                    "(most often the scene has no page/artboard yet). Author the "
                    "page first, then call generate_qr again — QR generation is "
                    "deterministic, so the retry costs nothing."
                ),
                "diagnostics": [
                    diag.model_dump(mode="json")
                    for diag in diagnostics_from(error.diagnostics)
                ],
            }
            self.record(
                "coordinator",
                "qr_registration_failed",
                input_summary=data[:200],
                output_summary=error.message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)
        self._replace_scene_from_core_response(
            apply_response, "generate_qr", [{"kind": "upsert_asset", "asset": record}]
        )

        diagnostics = diagnostics_from(response.get("diagnostics", []))
        payload = {
            "qr": {
                "status": "ok",
                "asset_id": record.get("id"),
                "digest": (record.get("media") or {}).get("digest"),
                "deduplicated": asset_payload.get("deduplicated", False),
                "ec_level": (asset_payload.get("qr") or {}).get("ec_level"),
                "module_count": (asset_payload.get("qr") or {}).get("module_count"),
                "quiet_zone_modules": (asset_payload.get("qr") or {}).get(
                    "quiet_zone_modules"
                ),
                "provenance": record.get("provenance"),
                "source": record.get("source"),
                "license": (record.get("license") or {}).get("name"),
            },
            "diagnostics": [diag.model_dump(mode="json") for diag in diagnostics],
        }
        self.record(
            "coordinator",
            "qr_generated",
            input_summary=data[:200],
            output_summary=(
                f"generated QR asset {record.get('id')} "
                f"(ec={payload['qr']['ec_level']}, modules={payload['qr']['module_count']})"
            ),
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def generate_image(
        self,
        prompt: str,
        target_node_id: Optional[str] = None,
        target_slot_id: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        brand_notes: Optional[List[str]] = None,
        transparent_background: bool = False,
        label: Optional[str] = None,
    ) -> str:
        """Generate a raster image asset from a text prompt and register it in the
        scene. Pass target_node_id (or target_slot_id) so the aspect ratio is
        derived from that frame's geometry — generated images are cropped to fill,
        never stretched. Uses the configured text-to-image model (image-gen-v1)
        when available, otherwise a deterministic placeholder so the design still
        composes offline. The scene must already contain a page/artboard (author
        the layout first) or registration fails with a retryable error. Returns
        the asset_id; place it with place_asset_in_node / place_asset_in_slot
        (a generated image is not auto-placed)."""
        asset_id = f"asset_img_{self.run_id[:8]}_{len(self.scene.get('assets', {}))}"
        width, height, aspect_ratio = self._image_constraints(
            target_node_id, target_slot_id, width, height, aspect_ratio
        )
        notes = [note for note in (brand_notes or []) if note and note.strip()]
        resolved_label = label or (prompt[:60].strip() or asset_id)

        record, meta, raw_diagnostics, error = self._produce_image_asset(
            asset_id=asset_id,
            prompt=prompt,
            label=resolved_label,
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
            brand_notes=notes,
            transparent_background=transparent_background,
        )
        diagnostics = diagnostics_from(raw_diagnostics)
        if record is None:
            payload = {
                "image": {
                    "status": "error",
                    "error_code": error[0] if error else "image.error",
                    "message": error[1] if error else "image generation failed",
                },
                "diagnostics": [diag.model_dump(mode="json") for diag in diagnostics],
            }
            self.record(
                "coordinator",
                "image_generation_failed",
                input_summary=prompt[:200],
                output_summary=payload["image"]["message"],
                diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        try:
            apply_response = self.core.apply_operations(
                self.scene, [{"kind": "upsert_asset", "asset": record}]
            )
        except CoreError as error:
            payload = {
                "image": {
                    "status": "error",
                    "error_code": error.code,
                    "message": error.message,
                    "asset_id": record.get("id"),
                },
                "hint": (
                    "The image was generated but could not be registered in the "
                    "scene (most often the scene has no page/artboard yet). Author "
                    "the page first, then call generate_image again with the same "
                    "prompt — the generation cache makes the retry free."
                ),
                "diagnostics": [
                    diag.model_dump(mode="json")
                    for diag in diagnostics_from(error.diagnostics)
                ],
            }
            self.record(
                "coordinator",
                "image_registration_failed",
                input_summary=prompt[:200],
                output_summary=error.message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)
        self._replace_scene_from_core_response(
            apply_response, "generate_image", [{"kind": "upsert_asset", "asset": record}]
        )

        payload = {
            "image": {
                "status": "ok",
                "asset_id": record.get("id"),
                "mode": meta.get("mode"),
                "model": meta.get("model"),
                "mime_type": (record.get("media") or {}).get("mime_type"),
                "aspect_ratio": aspect_ratio,
                "width": width,
                "height": height,
                "provenance": record.get("provenance"),
                "source": record.get("source"),
                "license": (record.get("license") or {}).get("name"),
            },
            "diagnostics": [diag.model_dump(mode="json") for diag in diagnostics],
        }
        self.record(
            "coordinator",
            "image_generated",
            input_summary=prompt[:200],
            output_summary=(
                f"generated image asset {record.get('id')} "
                f"(mode={meta.get('mode')}, model={meta.get('model')}, aspect={aspect_ratio})"
            ),
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def _register_referenced_brand_assets(self, origin: str) -> None:
        """K2 root fix: a DSL author naturally writes `image asset(<id>)` with
        an asset_id straight from the brand card — a form the compiler accepts
        but which registers nothing, leaving a dangling reference that renders
        blank (LUME0211; the K2 live verify failed exactly here). Rather than
        prompt-steering against the natural form (a losing fight), any image
        node whose asset_id names a kit-manifest asset that the scene doesn't
        carry yet gets its record auto-registered with brand_guide provenance
        — the same registration use_brand_asset performs. The explicit action
        remains for fit/slot control. Failures never break the calling tool:
        registration is a repair, not a gate."""
        manifest = self.config.brand_kit_assets or {}
        if not manifest:
            return
        scene_assets = self.scene.get("assets") or {}
        referenced: list[str] = []
        for node in (self.scene.get("nodes") or {}).values():
            kind = node.get("kind") or {}
            if kind.get("kind") != "image":
                continue
            asset_id = kind.get("asset_id")
            if asset_id in manifest and asset_id not in scene_assets:
                referenced.append(asset_id)
        for asset_id in dict.fromkeys(referenced):
            entry = manifest.get(asset_id) or {}
            record = copy.deepcopy(entry.get("record") or {})
            if not record.get("id"):
                continue
            label = entry.get("title") or record.get("label") or asset_id
            record["source"] = {
                "kind": "brand_guide",
                "source_asset_id": asset_id,
                "label": label,
            }
            try:
                response = self.core.apply_operations(
                    self.scene, [{"kind": "upsert_asset", "asset": record}]
                )
            except CoreError:
                continue
            self._replace_scene_from_core_response(
                response, origin, [{"kind": "upsert_asset", "asset": record}]
            )
            self.record(
                "coordinator",
                "brand_asset_registered",
                input_summary=asset_id,
                output_summary=(
                    f"auto-registered kit asset {asset_id} referenced by the "
                    f"scene ({origin})"
                ),
                payload={
                    "brand_asset": {"asset_id": asset_id, "label": label, "via": origin}
                },
            )

    def use_brand_asset(
        self,
        asset_id: str,
        node_id: Optional[str] = None,
        slot_id: Optional[str] = None,
        fit: str = "contain",
        focal_x: float = 0.5,
        focal_y: float = 0.5,
        alt: Optional[str] = None,
    ) -> str:
        """K2: register one of the attached Brand Kit's assets (a logo variant
        or brand image, from the kit-asset manifest the API passed by value)
        into the scene and place it into `node_id` or `slot_id`.

        The library record is upserted VERBATIM under its ORIGINAL id — brand
        governance (LUMB0809 min-size / LUMB0810 allowed-backgrounds)
        identifies logo nodes by matching node.asset_id against the kit's
        variant asset ids, so minting a new id would silently disable it —
        with only the scene copy's provenance rewritten to brand_guide
        (source_asset_id chains back to the library asset). Bytes never move:
        the record's content-addressed location already points into the
        shared store. Default fit is `contain` — logos are never cropped."""
        manifest = self.config.brand_kit_assets or {}
        entry = manifest.get(asset_id)
        if entry is None or not isinstance(entry, dict):
            return self._tool_error(
                "asset.unknown_brand_asset",
                f"'{asset_id}' is not in the attached Brand Kit's asset manifest. "
                "Use an asset_id from the brand context card's logo/image inventory.",
                known_asset_ids=sorted(manifest.keys())[:12],
            )
        record = copy.deepcopy(entry.get("record") or {})
        if not record.get("id"):
            return self._tool_error(
                "asset.bad_manifest_record",
                f"the manifest entry for '{asset_id}' carries no usable record.",
            )
        label = entry.get("title") or record.get("label") or asset_id
        record["source"] = {
            "kind": "brand_guide",
            "source_asset_id": asset_id,
            "label": label,
        }

        try:
            apply_response = self.core.apply_operations(
                self.scene, [{"kind": "upsert_asset", "asset": record}]
            )
        except CoreError as error:
            payload = {
                "brand_asset": {
                    "status": "error",
                    "error_code": error.code,
                    "message": error.message,
                    "asset_id": asset_id,
                },
                "hint": (
                    "The kit asset could not be registered in the scene (most "
                    "often the scene has no page/artboard yet). Author the page "
                    "first, then call use_brand_asset again."
                ),
                "diagnostics": [
                    diag.model_dump(mode="json")
                    for diag in diagnostics_from(error.diagnostics)
                ],
            }
            self.record(
                "coordinator",
                "brand_asset_registration_failed",
                input_summary=asset_id,
                output_summary=error.message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)
        self._replace_scene_from_core_response(
            apply_response, "use_brand_asset", [{"kind": "upsert_asset", "asset": record}]
        )
        self.record(
            "coordinator",
            "brand_asset_registered",
            input_summary=asset_id,
            output_summary=(
                f"registered kit asset {record.get('id')} "
                f"({(record.get('media') or {}).get('mime_type')}, provenance brand_guide)"
            ),
            payload={"brand_asset": {"asset_id": record.get("id"), "label": label}},
        )

        if node_id is not None:
            return self.place_asset_in_node(
                node_id, record["id"], fit, focal_x, focal_y, alt, None
            )
        if slot_id is not None:
            return self.place_asset_in_slot(
                slot_id, record["id"], fit, focal_x, focal_y, alt, None
            )
        return self._tool_error(
            "asset.bad_request",
            "action='use_brand_asset' requires `node_id` or `slot_id`.",
        )

    def _produce_image_asset(
        self,
        *,
        asset_id: str,
        prompt: str,
        label: str,
        width: Optional[int],
        height: Optional[int],
        aspect_ratio: Optional[str],
        brand_notes: List[str],
        transparent_background: bool,
    ) -> tuple[Optional[JsonObject], JsonObject, List[JsonObject], Optional[tuple]]:
        """Produce + ingest one image asset record. Prefers the configured T2I
        model; on a missing config or any model/ingest failure it falls back to the
        deterministic stub provider (with a warning) so the design loop never
        dead-ends on imagery. Returns (record, meta, raw_diagnostics, error)."""
        diagnostics: List[JsonObject] = []

        # 1) Real text-to-image model, when configured.
        if image_provider is not None and image_provider.is_configured():
            store_root = str(self.config.effective_asset_store_root)
            # Generation cache: re-use the asset an identical earlier request
            # produced (the loop re-requests the same hero each iteration) instead
            # of re-paying the model. Checked BEFORE the provider call.
            cache_key = None
            model_id = getattr(image_provider, "configured_model_id", None)
            if image_cache is not None and callable(model_id):
                cache_key = image_cache.generation_key(
                    prompt=prompt,
                    model=model_id(),
                    width=width,
                    height=height,
                    brand_notes=brand_notes,
                    aspect_ratio=aspect_ratio,
                    transparent_background=transparent_background or None,
                )
                cached = image_cache.lookup(store_root, cache_key)
                if cached:
                    return (
                        cached,
                        {"mode": "cached", "model": (cached.get("source") or {}).get("model")},
                        diagnostics,
                        None,
                    )
            try:
                result = image_provider.generate(
                    prompt=prompt,
                    width=width,
                    height=height,
                    brand_notes=brand_notes,
                    aspect_ratio=aspect_ratio,
                    transparent_background=transparent_background or None,
                    request_id=asset_id,
                )
                ingest = self.core.ingest_asset(
                    store_root=store_root,
                    bytes_base64=base64.b64encode(result.image_bytes).decode("ascii"),
                    asset_id=asset_id,
                    label=label,
                    declared_mime_type=result.mime_type,
                    kind="raster_image",
                    license=result.license,
                    provenance=result.provenance,
                    source={"kind": "generated", "request_id": asset_id, "model": result.model},
                    raise_on_error=False,
                )
                if ingest.get("ok"):
                    record = (ingest.get("asset") or {}).get("record") or {}
                    diagnostics.extend(_as_diag_list(ingest.get("diagnostics")))
                    if cache_key is not None and image_cache is not None:
                        image_cache.store(store_root, cache_key, record)
                    return record, {"mode": "model", "model": result.model}, diagnostics, None
                detail = (ingest.get("error") or {}).get("message", "unknown error")
                diagnostics.append(
                    _image_warning(
                        "LUMA0710",
                        f"generated image could not be ingested ({detail}); used a placeholder",
                    )
                )
            except Exception as error:  # noqa: BLE001 - degrade to a placeholder, never crash the loop
                code = getattr(error, "code", error.__class__.__name__)
                diagnostics.append(
                    _image_warning(
                        "LUMA0710",
                        f"text-to-image model unavailable ({code}); used a placeholder image",
                    )
                )
        elif image_provider is not None:
            diagnostics.append(
                _image_warning(
                    "LUMA0711",
                    "text-to-image model is not configured (set IMAGE_MODEL_*); used a placeholder image",
                )
            )

        # 2) Deterministic stub fallback through the Rust provider registry.
        request = {
            "request_id": asset_id,
            "prompt": prompt,
            "output_kind": "raster_image",
            "target_node_id": None,
            "target_slot_id": None,
            "constraints": {
                "width": width,
                "height": height,
                "transparent_background": transparent_background or None,
                "brand_notes": brand_notes,
            },
        }
        try:
            response = self.core.generate_asset(
                store_root=str(self.config.effective_asset_store_root),
                provider="stub-image-v0",
                request=request,
                asset_id=asset_id,
                label=label,
            )
        except CoreError as error:
            diagnostics.extend(_as_diag_list(error.diagnostics))
            return None, {}, diagnostics, (error.code, error.message)
        record = (response.get("asset") or {}).get("record") or {}
        diagnostics.extend(_as_diag_list(response.get("diagnostics")))
        return record, {"mode": "placeholder", "model": "stub-image-v0"}, diagnostics, None

    def _image_constraints(
        self,
        target_node_id: Optional[str],
        target_slot_id: Optional[str],
        width: Optional[int],
        height: Optional[int],
        aspect_ratio: Optional[str],
    ) -> tuple[Optional[int], Optional[int], Optional[str]]:
        """Derive aspect_ratio (and a role-appropriate resolution) from the target
        frame's geometry so generated images match the frame they fill."""
        bounds = self._target_bounds(target_node_id, target_slot_id)
        if bounds:
            box_width, box_height = bounds
            if aspect_ratio is None:
                aspect_ratio = _nearest_aspect_label(box_width, box_height)
            if width is None and height is None:
                width, height = _resolution_for_aspect(box_width, box_height)
        return width, height, aspect_ratio

    def _target_bounds(
        self, target_node_id: Optional[str], target_slot_id: Optional[str]
    ) -> Optional[tuple]:
        """Resolve a target node's (width, height) from computed geometry, falling
        back to its declared fixed size. Slots resolve to their first bound node."""
        node_id = target_node_id
        if node_id is None and target_slot_id:
            slot = self.scene.get("slots", {}).get(target_slot_id) or {}
            bound = slot.get("bound_nodes") or []
            node_id = bound[0] if bound else None
        if not node_id:
            return None
        node = self.scene.get("nodes", {}).get(node_id) or {}
        bounds = (node.get("computed") or {}).get("layout_bounds") or {}
        box_width = bounds.get("width")
        box_height = bounds.get("height")
        if not box_width or not box_height:
            size = node.get("size") or {}
            box_width = _fixed_dim(size.get("width"))
            box_height = _fixed_dim(size.get("height"))
        if box_width and box_height and box_width > 0 and box_height > 0:
            return float(box_width), float(box_height)
        return None

    def place_asset_in_node(
        self,
        node_id: str,
        asset_id: str,
        fit: str = "cover",
        focal_x: float = 0.5,
        focal_y: float = 0.5,
        alt: Optional[str] = None,
        preserve_transparency: Optional[bool] = None,
    ) -> str:
        """Place an existing asset (generated or library) into an image node with a
        fit mode (default cover, so the frame fills without stretching), a
        normalized focal point (0..1, default centered) that controls the cover
        crop, and alt text. Reversible — re-place or remove to change it."""
        return self._place_asset(
            "place_asset_in_node", "node_id", node_id, asset_id, fit, focal_x, focal_y, alt, preserve_transparency
        )

    def place_asset_in_slot(
        self,
        slot_id: str,
        asset_id: str,
        fit: str = "cover",
        focal_x: float = 0.5,
        focal_y: float = 0.5,
        alt: Optional[str] = None,
        preserve_transparency: Optional[bool] = None,
    ) -> str:
        """Place an existing asset into an image slot's bound node — same placement
        semantics as place_asset_in_node, preserving the slot binding. Reversible."""
        return self._place_asset(
            "place_asset_in_slot", "slot_id", slot_id, asset_id, fit, focal_x, focal_y, alt, preserve_transparency
        )

    def _place_asset(
        self,
        kind: str,
        target_key: str,
        target_id: str,
        asset_id: str,
        fit: str,
        focal_x: float,
        focal_y: float,
        alt: Optional[str],
        preserve_transparency: Optional[bool],
    ) -> str:
        placement: JsonObject = {
            "fit": fit,
            "focal_point": {"x": float(focal_x), "y": float(focal_y)},
        }
        if alt is not None:
            placement["alt_text"] = alt
        if preserve_transparency is not None:
            placement["preserve_transparency"] = bool(preserve_transparency)
        operation = {"kind": kind, target_key: target_id, "asset_id": asset_id, "placement": placement}
        try:
            apply_response = self.core.apply_operations(self.scene, [operation])
        except CoreError as error:
            payload = {
                "placement": {
                    "status": "error",
                    "error_code": error.code,
                    "message": error.message,
                },
                "diagnostics": [
                    diag.model_dump(mode="json") for diag in diagnostics_from(error.diagnostics)
                ],
            }
            self.record(
                "coordinator",
                "asset_placement_failed",
                input_summary=f"{kind} {target_id} <- {asset_id}",
                output_summary=error.message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        self._replace_scene_from_core_response(apply_response, kind, [operation])
        diagnostics = diagnostics_from(apply_response.get("diagnostics", []))
        payload = {
            "placement": {
                "status": "ok",
                "operation": kind,
                target_key: target_id,
                "asset_id": asset_id,
                "fit": fit,
                "focal_point": {"x": float(focal_x), "y": float(focal_y)},
                "alt": alt,
            },
            "diagnostics": [diag.model_dump(mode="json") for diag in diagnostics],
        }
        self.record(
            "coordinator",
            "asset_placed",
            input_summary=f"{kind} {target_id} <- {asset_id}",
            output_summary=f"placed {asset_id} into {target_id} (fit={fit})",
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def _asset_preview_path(
        self, record: JsonObject
    ) -> Optional[tuple[str, Optional[int], Optional[int]]]:
        """Slice 2: resolve a kit-asset record to an ON-DISK preview the vision APIs
        can read, returning (absolute_path, pixel_width, pixel_height) or None.

        Prefer the derived 256px thumbnail (any source type gets one at ingest); else,
        if the primary media is itself a raster the vision APIs accept, use that. An
        SVG with no thumbnail has no usable raster preview → return None (the caller
        skips it and counts it in `_omitted`). Refs are `sha256/<first2>/<digest>`
        under the SAME asset-store root the tools already use for export/ingest —
        resolved the one way (Path(effective_asset_store_root) / opaque_ref). Only the
        path is returned; no bytes are read here (existence is checked at block-build
        time in providers), so this stays cheap to call every curated context."""
        media = record.get("media") or {}
        store_root = Path(self.config.effective_asset_store_root)
        thumbnail = media.get("thumbnail") or {}
        thumb_ref = (thumbnail.get("location") or {}).get("opaque_ref")
        if thumb_ref:
            return (
                str(store_root / thumb_ref),
                thumbnail.get("pixel_width"),
                thumbnail.get("pixel_height"),
            )
        mime = media.get("mime_type")
        primary_ref = (media.get("location") or {}).get("opaque_ref")
        if mime in _PREVIEWABLE_MIME_TYPES and primary_ref:
            # Pixel dims for a raster/logo asset live in its own metadata block.
            dims = record.get("raster") or record.get("logo") or {}
            return (
                str(store_root / primary_ref),
                dims.get("pixel_width"),
                dims.get("pixel_height"),
            )
        return None

    def _resolve_node_image_source(
        self, node_id: str
    ) -> tuple[Optional[JsonObject], Optional[bytes], Optional[str], Optional[str], Optional[tuple]]:
        """Resolve a node's currently placed image asset into (record, bytes, mime,
        source_digest, error). The bytes come from the content-addressed store the
        same way the /assets/generate edit route reads them: media.digest.value →
        `sha256/<first2>/<digest>` under the asset-store root. Returns an error tuple
        (code, message) when the node has no ready image asset to edit — mirroring the
        LUMV0100 graceful guards so an edit on an un-imaged node never crashes the loop."""
        node = (self.scene.get("nodes") or {}).get(node_id)
        if not node:
            return None, None, None, None, (
                "asset.node_not_found",
                f"node {node_id!r} does not exist in the current scene",
            )
        asset_id = (node.get("kind") or {}).get("asset_id")
        if not asset_id:
            return None, None, None, None, (
                "asset.not_an_image_node",
                f"node {node_id!r} is not an image node (no placed asset to edit)",
            )
        record = (self.scene.get("assets") or {}).get(asset_id)
        if not record:
            return None, None, None, None, (
                "asset.source_not_registered",
                f"node {node_id!r} references asset {asset_id!r}, which is not in the scene",
            )
        if record.get("status") != "ready":
            return None, None, None, None, (
                "asset.source_not_ready",
                f"asset {asset_id!r} on node {node_id!r} is not a ready image (status="
                f"{record.get('status')!r}); generate a ready image before editing it",
            )
        media = record.get("media") or {}
        source_digest = (media.get("digest") or {}).get("value")
        mime = media.get("mime_type") or "image/png"
        if not source_digest:
            return None, None, None, None, (
                "asset.source_bytes_missing",
                f"asset {asset_id!r} has no stored digest; its bytes cannot be resolved to edit",
            )
        store_root = Path(self.config.effective_asset_store_root)
        blob_path = store_root / "sha256" / source_digest[:2] / source_digest
        if not blob_path.is_file():
            return None, None, None, None, (
                "asset.source_bytes_missing",
                f"asset {asset_id!r} has no stored bytes to edit ({blob_path})",
            )
        return record, blob_path.read_bytes(), mime, source_digest, None

    def edit_image(
        self,
        node_id: str,
        prompt: str,
        remove_background: bool = False,
        label: Optional[str] = None,
    ) -> str:
        """Edit the raster image currently placed in `node_id` with a text
        instruction (Phase 3c) — recolor / adjust warmth / remove or replace the
        background / fix a flawed subject — WITHOUT changing the composition. The
        source pixels ride the model call; the edited result re-enters the SAME node
        preserving its current placement (fit / focal point / alt). Prefer this over a
        full regenerate when the placed image is right-but-flawed. `remove_background`
        requests a transparent background. Returns the new (edited) asset_id, its
        provenance chained to the source asset. Gracefully errors (never crashes) when
        the node has no ready image asset to edit."""
        source_record, source_bytes, source_mime, source_digest, error = (
            self._resolve_node_image_source(node_id)
        )
        if error is not None:
            payload = {
                "image_edit": {
                    "status": "error",
                    "error_code": error[0],
                    "message": error[1],
                    "node_id": node_id,
                },
                "hint": (
                    "edit_image edits the image already placed in this node. Generate "
                    "and place a ready image first, then edit it — or use "
                    "action='generate_image' for a fresh image."
                ),
            }
            self.record(
                "coordinator",
                "image_edit_failed",
                input_summary=f"{node_id}: {prompt[:160]}",
                output_summary=error[1],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        source_asset_id = (source_record or {}).get("id")
        transparent = remove_background or None
        asset_id = f"asset_img_{self.run_id[:8]}_edit_{len(self.scene.get('assets', {}))}"
        resolved_label = label or (prompt[:60].strip() or asset_id)

        record: Optional[JsonObject] = None
        meta: JsonObject = {}
        diagnostics: List[JsonObject] = []
        edit_error: Optional[tuple] = None

        if image_provider is not None and image_provider.is_configured():
            store_root = str(self.config.effective_asset_store_root)
            # Per-run generation cache, keyed on the SOURCE digest + prompt (+ bg flag)
            # so the loop re-editing the same image with the same instruction is free,
            # and the same instruction on a different image never collides.
            cache_key = None
            model_id = getattr(image_provider, "configured_model_id", None)
            if image_cache is not None and callable(model_id):
                cache_key = image_cache.generation_key(
                    prompt=prompt,
                    model=model_id(),
                    transparent_background=transparent,
                    source_digest=source_digest,
                )
                cached = image_cache.lookup(store_root, cache_key)
                if cached:
                    record = cached
                    meta = {"mode": "cached", "model": (cached.get("source") or {}).get("model")}
            if record is None:
                try:
                    result = image_provider.edit(
                        prompt=prompt,
                        source_images=[(source_bytes, source_mime)],
                        transparent_background=transparent,
                        request_id=asset_id,
                    )
                    ingest = self.core.ingest_asset(
                        store_root=store_root,
                        bytes_base64=base64.b64encode(result.image_bytes).decode("ascii"),
                        asset_id=asset_id,
                        label=resolved_label,
                        declared_mime_type=result.mime_type,
                        kind="raster_image",
                        license=result.license,
                        provenance=result.provenance,
                        source={
                            "kind": "edited",
                            "request_id": asset_id,
                            "model": result.model,
                            "source_asset_id": source_asset_id,
                        },
                        raise_on_error=False,
                    )
                    if ingest.get("ok"):
                        record = (ingest.get("asset") or {}).get("record") or {}
                        diagnostics.extend(_as_diag_list(ingest.get("diagnostics")))
                        if cache_key is not None and image_cache is not None:
                            image_cache.store(store_root, cache_key, record)
                        meta = {"mode": "model", "model": result.model}
                    else:
                        detail = (ingest.get("error") or {}).get("message", "unknown error")
                        edit_error = ("image_edit.ingest_failed", f"edited image could not be ingested ({detail})")
                except Exception as exc:  # noqa: BLE001 - report, never crash the loop
                    code = getattr(exc, "code", exc.__class__.__name__)
                    edit_error = ("image_edit.model_failed", f"image edit failed ({code})")
        else:
            edit_error = (
                "image_edit.model_unconfigured",
                "text-to-image model is not configured (set IMAGE_MODEL_*); cannot edit the image",
            )

        diags = diagnostics_from(diagnostics)
        if record is None:
            payload = {
                "image_edit": {
                    "status": "error",
                    "error_code": edit_error[0] if edit_error else "image_edit.error",
                    "message": edit_error[1] if edit_error else "image edit failed",
                    "node_id": node_id,
                    "source_asset_id": source_asset_id,
                },
                "diagnostics": [d.model_dump(mode="json") for d in diags],
            }
            self.record(
                "coordinator",
                "image_edit_failed",
                input_summary=f"{node_id}: {prompt[:160]}",
                output_summary=payload["image_edit"]["message"],
                diagnostics=[d.model_dump(mode="json") for d in diags],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        # Register the edited asset through the canonical upsert path (guarded — a
        # scene without a page/artboard fails here, same as generate_image).
        try:
            apply_response = self.core.apply_operations(
                self.scene, [{"kind": "upsert_asset", "asset": record}]
            )
        except CoreError as reg_error:
            payload = {
                "image_edit": {
                    "status": "error",
                    "error_code": reg_error.code,
                    "message": reg_error.message,
                    "asset_id": record.get("id"),
                    "node_id": node_id,
                },
                "diagnostics": [
                    d.model_dump(mode="json") for d in diagnostics_from(reg_error.diagnostics)
                ],
            }
            self.record(
                "coordinator",
                "image_edit_registration_failed",
                input_summary=f"{node_id}: {prompt[:160]}",
                output_summary=reg_error.message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)
        self._replace_scene_from_core_response(
            apply_response, "edit_image", [{"kind": "upsert_asset", "asset": record}]
        )

        # Re-place the edited asset into the SAME node, preserving the current
        # placement (fit / focal point / alt) so the composition is untouched.
        placement = ((self.scene.get("nodes") or {}).get(node_id) or {}).get("asset_placement") or {}
        focal = placement.get("focal_point") or {}
        place_result = json.loads(
            self.place_asset_in_node(
                node_id,
                record.get("id"),
                fit=placement.get("fit") or "cover",
                focal_x=focal.get("x", 0.5),
                focal_y=focal.get("y", 0.5),
                alt=placement.get("alt_text"),
                preserve_transparency=True if transparent else None,
            )
        )

        payload = {
            "image_edit": {
                "status": "ok",
                "asset_id": record.get("id"),
                "source_asset_id": source_asset_id,
                "node_id": node_id,
                "mode": meta.get("mode"),
                "model": meta.get("model"),
                "remove_background": bool(remove_background),
                "provenance": record.get("provenance"),
                "source": record.get("source"),
                "placement": place_result.get("placement"),
            },
            "diagnostics": [d.model_dump(mode="json") for d in diags],
        }
        self.record(
            "coordinator",
            "image_edited",
            input_summary=f"{node_id}: {prompt[:160]}",
            output_summary=(
                f"edited image {source_asset_id} -> {record.get('id')} "
                f"(mode={meta.get('mode')}, model={meta.get('model')}) re-placed into {node_id}"
            ),
            diagnostics=[d.model_dump(mode="json") for d in diags],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def scene_has_generated_imagery(self) -> bool:
        """Whether the current scene places any generated or edited raster asset —
        the gate for whether the imagery verifier / mid-loop vision check is worth
        running (a design that placed only library images or none needs no check)."""
        assets = self.scene.get("assets") or {}
        nodes = self.scene.get("nodes") or {}
        for node in nodes.values():
            asset_id = (node.get("kind") or {}).get("asset_id")
            if not asset_id:
                continue
            source_kind = ((assets.get(asset_id) or {}).get("source") or {}).get("kind")
            if source_kind in ("generated", "edited"):
                return True
        return False

    def verify_imagery(
        self,
        expected_decision: Optional[str] = None,
        role: Optional[str] = None,
        risks: Optional[List[str]] = None,
        png_path: Optional[str] = None,
    ) -> str:
        """Verify the current scene's use of imagery (Phase 3c gate). Always runs the
        DETERMINISTIC imagery checks (`imagery_checks.score_scene`); runs the
        `judge_imagery` VISION call in addition ONLY when an agent API key is
        configured (the judge reads its credentials from config, providers pattern) and
        a rendered PNG is available. Returns a compact verdict: per-axis finals, the
        hard-gate failures, accept/tier, and one line of guidance — small enough to
        append to a coordinator handoff or feed the imagery-repair path."""
        from ..imagery_checks import score_scene
        from ..imagery_judge import HARD_GATE_AXES, judge_imagery

        brief: JsonObject = {
            "id": self.run_id,
            "expected_decision": expected_decision,
            "role": role,
            "risks": risks or [],
        }
        # Resolve the rendered PNG (for the vision call) from the latest preview when
        # not passed explicitly. The judge only looks at it when it runs.
        resolved_png = png_path
        if resolved_png is None:
            latest = self.latest_preview_bundle or self.latest_export_summary or {}
            for artifact in (latest.get("artifacts") or []):
                if artifact.get("format") == "png" and artifact.get("path"):
                    resolved_png = artifact.get("path")
                    break

        has_key = bool(getattr(self.config, "agent_api_key", None))
        if has_key:
            # Full DET + JUDGE (vision) combine — judge_imagery builds the model from
            # config when no model is injected.
            result = judge_imagery(self.scene, resolved_png, brief, config=self.config)
        else:
            # DET-only: no key → never make a paid vision call.
            det = score_scene(self.scene, expected_decision=expected_decision)
            from ..imagery_judge import combine

            result = combine(det, None, brief)
            result["brief_id"] = brief["id"]
            result["expected_decision"] = expected_decision
            result["det"] = det

        per_axis = result.get("per_axis") or {}
        hard_gate_failures = sorted(
            axis
            for axis, info in per_axis.items()
            if axis in HARD_GATE_AXES and info.get("final") is not None and info["final"] <= 1
        )
        guidance = self._imagery_verdict_guidance(result, hard_gate_failures)
        verdict = {
            "status": "ok",
            "judge_ran": bool(result.get("judge_ran")),
            "accept": bool(result.get("accept")),
            "tier": result.get("tier"),
            "weighted_mean": result.get("weighted_mean"),
            "gate_failed": bool(result.get("gate_failed")),
            "hard_gate_failures": hard_gate_failures,
            "per_axis": {axis: info.get("final") for axis, info in per_axis.items()},
            "image_count": result.get("image_count", 0),
            "guidance": guidance,
        }
        self.record(
            "coordinator",
            "imagery_verified",
            output_summary=(
                f"imagery verdict tier={verdict['tier']} accept={verdict['accept']} "
                f"judge_ran={verdict['judge_ran']} hard_gate={hard_gate_failures}"
            ),
            payload=verdict,
        )
        return json.dumps(verdict, indent=2)

    @staticmethod
    def _imagery_verdict_guidance(result: JsonObject, hard_gate_failures: list) -> str:
        """One-line, actionable guidance from an imagery verdict."""
        if hard_gate_failures:
            return (
                "Hard imagery gate failed on "
                + ", ".join(hard_gate_failures)
                + " — repair the image (recolor/edit, re-scrim, or regenerate) before shipping."
            )
        if result.get("accept"):
            return "Imagery clears the gate; ship."
        if result.get("tier") == "tweak":
            return "Imagery ships with a minor tweak — nudge the weakest axis."
        return "Imagery below the ship bar; edit or regenerate the flawed image."

    def _tool_error(self, code: str, message: str, **extra: Any) -> str:
        """Uniform error envelope for the dispatcher tools (asset/inspect)."""
        payload: JsonObject = {"status": "error", "error_code": code, "message": message}
        payload.update(extra)
        return json.dumps(payload, indent=2)

    def asset(
        self,
        action: str,
        prompt: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        brand_notes: Optional[List[str]] = None,
        transparent_background: bool = False,
        target_node_id: Optional[str] = None,
        target_slot_id: Optional[str] = None,
        data: Optional[str] = None,
        ec_level: Optional[str] = None,
        print_media: bool = False,
        target_width_mm: Optional[float] = None,
        node_id: Optional[str] = None,
        slot_id: Optional[str] = None,
        asset_id: Optional[str] = None,
        # None = per-action default: cover for place (imagery fills frames),
        # contain for use_brand_asset (a cropped logo is a brand failure).
        # An explicit value always wins.
        fit: Optional[str] = None,
        focal_x: float = 0.5,
        focal_y: float = 0.5,
        alt: Optional[str] = None,
        preserve_transparency: Optional[bool] = None,
        label: Optional[str] = None,
    ) -> str:
        """Generate or place a design asset. Pick `action`:

        - `action="generate_image"` — generate a raster image from `prompt` and
          register it (returns its asset_id; NOT auto-placed). Pass `target_node_id`
          (or `target_slot_id`) so the aspect is derived from that frame's geometry —
          images are cropped to fill, never stretched. Optional `aspect_ratio` /
          `width` / `height`, `brand_notes`, `transparent_background`, `label`.
        - `action="edit_image"` — edit the image already placed in `node_id` with a
          text `prompt` (recolor / warmth / background / fix a flawed subject) WITHOUT
          changing the composition; the edited result re-enters the same node with its
          current placement preserved. Set `transparent_background=True` to remove the
          background. Prefer this over a full regenerate when the image is right-but-flawed.
        - `action="generate_qr"` — generate a deterministic QR asset from `data`
          (URL/text). For physical artifacts set `print_media=True` and `target_width_mm`
          so print-scannability diagnostics can fire. Optional `ec_level`, `label`.
        - `action="place"` — place an existing asset (`asset_id`, generated or library)
          into either an image node (`node_id`) or a bound image slot (`slot_id`) with a
          `fit` (default cover), normalized focal point (`focal_x`/`focal_y`, 0..1,
          default centered), `alt` text, and optional `preserve_transparency`. Reversible.
        - `action="use_brand_asset"` — register one of the attached Brand Kit's assets
          (a logo variant or brand image; `asset_id` from the brand context card's
          inventory) into the scene with brand_guide provenance and place it into
          `node_id` or `slot_id`. Logos place with fit `contain` (never cropped);
          pick the variant by background (reversed on dark fields). Requires an
          attached kit — without one this action errors.

        Every action mutates the scene only through the canonical core operation path."""
        if action == "generate_image":
            if not prompt:
                return self._tool_error(
                    "asset.bad_request", "action='generate_image' requires `prompt`."
                )
            return self.generate_image(
                prompt,
                target_node_id,
                target_slot_id,
                aspect_ratio,
                width,
                height,
                brand_notes,
                transparent_background,
                label,
            )
        if action == "edit_image":
            if not node_id:
                return self._tool_error(
                    "asset.bad_request", "action='edit_image' requires `node_id`."
                )
            if not prompt:
                return self._tool_error(
                    "asset.bad_request", "action='edit_image' requires `prompt`."
                )
            return self.edit_image(node_id, prompt, transparent_background, label)
        if action == "generate_qr":
            if not data:
                return self._tool_error(
                    "asset.bad_request", "action='generate_qr' requires `data`."
                )
            return self.generate_qr(data, ec_level, print_media, target_width_mm, label)
        if action == "place":
            if not asset_id:
                return self._tool_error(
                    "asset.bad_request", "action='place' requires `asset_id`."
                )
            # Preserve the two distinct core op kinds: node_id -> place_asset_in_node,
            # slot_id -> place_asset_in_slot. The agent-facing tool merges to one; the
            # core operation `kind` must NOT, or the slot-binding path breaks.
            if node_id is not None:
                return self.place_asset_in_node(
                    node_id,
                    asset_id,
                    fit or "cover",
                    focal_x,
                    focal_y,
                    alt,
                    preserve_transparency,
                )
            if slot_id is not None:
                return self.place_asset_in_slot(
                    slot_id,
                    asset_id,
                    fit or "cover",
                    focal_x,
                    focal_y,
                    alt,
                    preserve_transparency,
                )
            return self._tool_error(
                "asset.bad_request",
                "action='place' requires `node_id` or `slot_id`.",
            )
        if action == "use_brand_asset":
            if not asset_id:
                return self._tool_error(
                    "asset.bad_request",
                    "action='use_brand_asset' requires `asset_id` (from the brand "
                    "context card's logo/image inventory).",
                )
            return self.use_brand_asset(
                asset_id,
                node_id,
                slot_id,
                fit or "contain",
                focal_x,
                focal_y,
                alt,
            )
        return self._tool_error(
            "asset.unknown_action",
            f"unknown action '{action}'.",
            valid_actions=[
                "generate_image",
                "edit_image",
                "generate_qr",
                "place",
                "use_brand_asset",
            ],
        )

    def _finalized_snapshot_for(self, binding: JsonObject) -> JsonObject:
        """Instances derive from finalized revisions; for agent previews the
        working scene is treated as a snapshot of the binding's revision."""
        snapshot = copy.deepcopy(self.scene)
        status = (snapshot.get("meta") or {}).get("status") or {}
        if status.get("kind") != "finalized":
            snapshot.setdefault("meta", {})["status"] = {
                "kind": "finalized",
                "template_revision_id": binding.get(
                    "template_revision_id", "tmpl_preview"
                ),
            }
        return snapshot

    def validate_binding_set(self, binding_set_json: str) -> str:
        """Validate a Phase G binding set (per-recipient values, links, and
        generated QR entries) against the current scene's slot contracts:
        keys resolve, kinds match content types, required slots covered,
        cardinality and max_length hold, the frozen conditional grammar
        parses, and generated entries chain links.*.url -> qr -> UrlQr
        slot. Returns precise LUMG diagnostics for every violation."""
        binding = parse_json_object(binding_set_json)
        if binding is None:
            payload = {
                "binding_validation": {
                    "status": "error",
                    "message": "binding_set_json is not a JSON object",
                }
            }
            return json.dumps(payload, indent=2)

        snapshot = self._finalized_snapshot_for(binding)
        try:
            response = self.core.validate_binding_set(snapshot, binding)
        except CoreError as error:
            payload = {
                "binding_validation": {
                    "status": "error",
                    "error_code": error.code,
                    "message": error.message,
                }
            }
            self.record(
                "coordinator",
                "binding_validation_failed",
                output_summary=error.message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        diagnostics = diagnostics_from(response.get("diagnostics", []))
        valid = bool(response.get("ok", False))
        payload = {
            "binding_validation": {
                "status": "valid" if valid else "invalid",
                "binding_set_id": binding.get("binding_set_id"),
                "template_revision_id": binding.get("template_revision_id"),
            },
            "diagnostics": [diag.model_dump(mode="json") for diag in diagnostics],
        }
        self.record(
            "coordinator",
            "binding_set_validated",
            input_summary=binding_set_json[:300],
            output_summary=(
                f"binding set {binding.get('binding_set_id')} is "
                f"{'valid' if valid else 'invalid'}"
            ),
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def derive_instance_preview(
        self, binding_set_json: str, export_format: str = "png"
    ) -> str:
        """Derive a personalized instance from the current scene plus a
        binding set (text/asset application, conditionals, repeater
        expansion, generated QR), render a preview artifact for visual
        critique, and report the instance fit verdicts. The working scene
        is never mutated: instances are derived artifacts."""
        binding = parse_json_object(binding_set_json)
        if binding is None:
            return json.dumps(
                {
                    "instance_preview": {
                        "status": "error",
                        "message": "binding_set_json is not a JSON object",
                    }
                },
                indent=2,
            )

        snapshot = self._finalized_snapshot_for(binding)
        store_root = str(self.config.effective_asset_store_root)
        export_format = export_format if export_format in {"svg", "png", "pdf"} else "png"
        try:
            response = self.core.derive_instance(
                snapshot,
                binding,
                asset_records=[],
                store_root=store_root,
                export_formats=[export_format],
                export_dpi=96,
            )
        except CoreError as error:
            payload = {
                "instance_preview": {
                    "status": "error",
                    "error_code": error.code,
                    "message": error.message,
                }
            }
            self.record(
                "coordinator",
                "instance_preview_failed",
                output_summary=error.message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        diagnostics = diagnostics_from(response.get("diagnostics", []))
        instance = response.get("instance") or {}
        fit_report = instance.get("fit_report") or {}
        preview_paths: list[str] = []
        if response.get("ok", False):
            for artifact in instance.get("artifacts", []):
                relative = artifact.get("relative_path")
                if not relative:
                    continue
                source = Path(store_root) / relative
                if not source.exists():
                    continue
                suffix = artifact.get("format", export_format)
                destination = self.trace_dir / (
                    f"instance_{binding.get('binding_set_id', 'preview')}"
                    f"_{len(preview_paths)}.{suffix}"
                )
                destination.write_bytes(source.read_bytes())
                preview_paths.append(str(destination))
            self.preview_paths.extend(preview_paths)

        payload = {
            "instance_preview": {
                "status": "ok" if response.get("ok", False) else "error",
                "binding_set_id": binding.get("binding_set_id"),
                "has_errors": instance.get("has_errors"),
                "fit_status": fit_report.get("status"),
                "fit_slots": fit_report.get("slots", []),
                "repair_requests": instance.get("repair_requests", []),
                "audit_entries": len(instance.get("audit", [])),
                "preview_paths": preview_paths,
            },
            "diagnostics": [diag.model_dump(mode="json") for diag in diagnostics],
        }
        self.record(
            "critic",
            "instance_preview_derived",
            input_summary=binding_set_json[:300],
            output_summary=(
                f"instance for {binding.get('binding_set_id')}: "
                f"fit={fit_report.get('status')}, "
                f"{len(preview_paths)} preview artifact(s)"
            ),
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def preflight_design(self) -> str:
        """Run canonical brand/token/layout preflight using the effective Brand Kit
        (the kit passed by value in config — the document's attached kit — or the
        platform default)."""
        iteration_dir = self._iteration_dir()
        try:
            # K2 belt: catch kit-asset references that arrived via structured
            # edits / raw operations (compile has its own reconcile pass).
            self._register_referenced_brand_assets("preflight_design")
            source, brand_kit, notice = self._effective_brand_kit()
            brand_context = self._brand_context(source, brand_kit)
            if notice:
                brand_context["notice"] = notice
            # K4 retokenization: on the agent's OWN (unseeded) draft, bind
            # every raw literal that equals a kit token before preflight —
            # deterministic data mapping, applied as real validated ops that
            # ride the ledger through Accept. Seeded scenes are skipped: a
            # human's literals are never rebound (resolution-once). LLM
            # repair measurably cannot do this (run_bff3433f); this pass can.
            if (
                brand_kit is not None
                and source not in (None, "platform_default")
                and not self.seeded_from_initial_scene
            ):
                retokenize_ops = build_retokenize_operations(self.scene, brand_kit)
                if retokenize_ops:
                    try:
                        rt_response = self.core.apply_operations(
                            self.scene, retokenize_ops
                        )
                        self._replace_scene_from_core_response(
                            rt_response, "retokenize_brand", operations=retokenize_ops
                        )
                        self.record(
                            "coordinator",
                            "brand_retokenized",
                            output_summary=(
                                f"{len(retokenize_ops)} node(s) rebound to kit tokens"
                            ),
                            payload={"operation_count": len(retokenize_ops)},
                        )
                    except CoreError:
                        # A rejected rebind never blocks the turn; preflight
                        # proceeds on the unmodified scene.
                        pass
                # Deterministic logo presence (same philosophy as the token
                # rebind): authoring adoption is coin-flip and repair-scope
                # constraints make instructions unactionable — so the loop
                # PLACES the mark once, as a page overlay the agent may then
                # move/restyle and the critic judges. K2 preflight
                # auto-register upserts the record from the manifest.
                placement_ops = build_logo_placement_operations(
                    self.scene, brand_kit
                )
                if placement_ops:
                    try:
                        placed = self.core.apply_operations(
                            self.scene, placement_ops
                        )
                        self._replace_scene_from_core_response(
                            placed, "place_brand_logo", operations=placement_ops
                        )
                        self.record(
                            "coordinator",
                            "brand_logo_placed",
                            output_summary="kit mark auto-placed (page overlay)",
                            payload={"operation_count": len(placement_ops)},
                        )
                    except CoreError:
                        pass
            # K4: brand governance judges the AUTHORED scene — resolution
            # deliberately CONSUMES token bindings (resolution-once: the
            # resolved scene is fully literal, style_token = None), so any
            # post-preflight governance pass reports LUMB0805/0804/0806 no
            # matter how well the draft was authored (that artifact wasted
            # three live proof rounds). Advisory: steers author + reviewer,
            # never fails the turn. Platform-default runs stay ungoverned.
            governance_diagnostics = []
            if brand_kit is not None and source not in (None, "platform_default"):
                try:
                    governance = self.core.validate_scene_brand_governance(
                        self.scene, brand_kit, strictness="advisory", raise_on_error=False
                    )
                    governance_diagnostics = diagnostics_from(
                        governance.get("diagnostics", [])
                    )
                except CoreError:
                    governance_diagnostics = []
            # The authored (pre-resolution) scene is the ONLY state where
            # bindings are observable — snapshot it for the fidelity eval.
            self._write_json(
                iteration_dir / "authored_scene.json", {"scene": self.scene}
            )
            response = self.core.preflight_scene(
                self.scene, brand_kit, brand_fonts=self.config.brand_fonts
            )
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
        if governance_diagnostics:
            diagnostics = diagnostics + governance_diagnostics
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

    def baseline_preflight_diagnostics(self) -> list[JsonObject]:
        """Preflight diagnostics on the scene AS SEEDED, before this turn's own
        edits. (Agent-improvement follow-up 1, the frozen-doc turn wedge.)

        A live turn can seed from a document that already carries legacy
        errors — e.g. LUMV0810 slot-fixture overflow on frozen/pinned text
        that predates this edit entirely. Without a baseline, the Phase A
        repair loop cannot tell "the turn broke this" from "this was already
        broken," and burns its whole iteration budget re-fixing errors that
        were never in scope (run_4a0feb15048e4fbe993029bd2cab436f: two
        pre-existing LUMV0810s ate all 3 iterations while the user's actual
        positional ask never landed).

        Memoized and UNTRACED on purpose: this runs once, before iteration 1,
        against the seeded scene only (a fresh/unseeded scene has nothing to
        baseline against). It must not consume an iteration slot, must not
        bump `self.iteration`, and must not write into `iterations/NNN/` —
        those are reserved for this turn's own authoring attempts. It reuses
        the same core preflight call and `diagnostics_from` normalizer as
        `preflight_design` so the diagnostic shape (and therefore the
        `(code, subject)` keys the loop diffs against) is identical."""
        if self._baseline_diagnostics is not None:
            return self._baseline_diagnostics
        if not self.seeded_from_initial_scene:
            self._baseline_diagnostics = []
            return self._baseline_diagnostics
        try:
            # Same kit precedence as preflight_design — a baseline captured
            # against a different kit than the turn's own preflights would
            # make the (code, subject) diff misattribute brand diagnostics.
            _, brand_kit, _ = self._effective_brand_kit()
            response = self.core.preflight_scene(
                self.scene, brand_kit, brand_fonts=self.config.brand_fonts
            )
        except CoreError:
            # A baseline that cannot be computed is treated as empty — the
            # repair loop falls back to today's un-scoped behavior rather
            # than blocking the turn on a baseline-capture failure.
            self._baseline_diagnostics = []
            return self._baseline_diagnostics
        diagnostics = [
            diag.model_dump(mode="json")
            for diag in diagnostics_from(response.get("diagnostics", []))
        ]
        self._baseline_diagnostics = diagnostics
        self._write_json(
            self.trace_dir / "baseline_preflight.json",
            {"baseline_diagnostics": diagnostics},
        )
        self.record(
            "coordinator",
            "baseline_preflight_captured",
            output_summary=(
                f"{len(diagnostics)} pre-existing diagnostic(s) on the seeded scene"
            ),
            diagnostics=diagnostics,
            payload={"baseline_diagnostics": diagnostics},
        )
        return diagnostics

    def export_preview(self, export_format: Optional[str] = None) -> str:
        """Export and validate an SVG or PNG preview for visual critique."""
        preview_format = (export_format or self.config.preview_format).lower()
        iteration_dir = self._iteration_dir()
        try:
            response = self.core.export_preview(
                self.scene,
                preview_format,
                asset_store_root=str(self.config.effective_asset_store_root),
                brand_fonts=self.config.brand_fonts,
            )
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
        """Return the latest validated preview payload WITH the PNG base64 inlined.

        SVG artifacts are returned as text because the model can inspect geometry
        directly. PNG artifacts are returned as base64 so a vision-capable adapter
        can turn them into a real image message. This is the payload the typed
        quality-loop consumes: it strips the base64 from the *text* prompt
        (`compact_preview_payload`) and re-attaches it exactly once as a vision
        block at the model boundary (`preview_image_blocks`), so it never piles up
        in history. Do NOT register this directly as a DeepAgent coordinator tool —
        the coordinator has no vision-block path, so an inlined base64 would sit in
        its message history as dead weight (a single poster PNG's base64 approaches
        the whole model context window). The coordinator uses `get_preview_for_review`.
        """
        return self._latest_preview_payload(include_base64=True, max_svg_chars=max_svg_chars)

    def get_preview_for_review(self, max_svg_chars: int = 20000) -> str:
        """Coordinator-facing preview handoff for the visual-reviewer subagent.

        Returns the rendered SVG geometry (capped) plus, for PNG artifacts, the
        on-disk path and dimensions — NEVER the base64 bytes. In DeepAgent mode the
        reviewer is a text-only subagent (its `task` interface carries a text
        description, and a base64 string inside a tool result is plain text, never
        vision), so it reviews from the SVG geometry and the coordinator's handoff;
        inlining the PNG base64 would only bloat the coordinator's history — a
        987KB poster PNG base64 tokenizes to nearly a whole 1M context window and
        was the cause of the LUMV/context blowup on poster-sized briefs. The
        rendered PNG stays on disk (`png_path`) for the offline imagery judge and
        any filesystem read.

        When the scene places generated/edited imagery, a compact DETERMINISTIC-only
        imagery verdict (`imagery_checks.score_scene`, NO vision call) is appended so
        the coordinator sees any hard-gate failure without a paid judge request.
        """
        payload_json = self._latest_preview_payload(
            include_base64=False, max_svg_chars=max_svg_chars
        )
        if not self.scene_has_generated_imagery():
            return payload_json
        try:
            payload = json.loads(payload_json)
        except (TypeError, ValueError):
            return payload_json
        if payload.get("status") != ToolStatus.ok.value:
            return payload_json
        from ..imagery_checks import score_scene
        from ..imagery_judge import HARD_GATE_AXES, combine

        det = score_scene(self.scene)
        det_verdict = combine(det, None, {"id": self.run_id})
        per_axis = det_verdict.get("per_axis") or {}
        payload["imagery_verdict"] = {
            "source": "deterministic",
            "gate_failed": bool(det_verdict.get("gate_failed")),
            "tier": det_verdict.get("tier"),
            "hard_gate_failures": sorted(
                axis
                for axis, info in per_axis.items()
                if axis in HARD_GATE_AXES and info.get("final") is not None and info["final"] <= 1
            ),
            "image_count": det.get("image_count", 0),
        }
        return json.dumps(payload, indent=2)

    def _latest_preview_payload(self, *, include_base64: bool, max_svg_chars: int) -> str:
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
                if include_base64:
                    raw = path.read_bytes()
                    item["base64"] = base64.b64encode(raw).decode("ascii")
                    item["encoding"] = "base64"
                else:
                    # Coordinator-facing: keep the on-disk render + dims, drop the
                    # heavy base64 (it is never consumed as vision here and would
                    # dominate the context window). dict(artifact) already carries
                    # path/width/height/byte_len.
                    item["png_path"] = str(path)
                    item["base64_omitted"] = True
                    item["note"] = (
                        "rendered PNG kept on disk; base64 omitted to keep coordinator "
                        "context small — review from svg geometry"
                    )
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
        # Slice 2 D3: attach the SOURCE thumbnails of the kit assets this scene
        # actually placed so the reviewer can verify each placement against its source
        # (right mark/variant, undistorted, legible). Paths only — providers reads the
        # bytes into vision blocks at the boundary. Present only for a kit-attached run
        # whose scene places manifest assets that resolve to real previews.
        placed_previews = self._placed_brand_asset_previews()
        if placed_previews:
            payload["placed_brand_asset_previews"] = placed_previews
        self.record(
            "coordinator",
            "critic_preview_loaded",
            output_summary=f"loaded {len(artifacts)} preview artifact(s) for critique",
            payload={
                "artifact_count": len(artifacts),
                "formats": [artifact.get("format") for artifact in artifacts],
                # D3 observability: how many kit-asset source thumbnails rode
                # along with the reviewer call (0 when the scene placed none).
                # Lets live traces confirm the critic saw source imagery; the
                # payload bytes themselves stay untraced by design.
                "placed_brand_asset_previews": len(placed_previews),
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
        """Recommend a conservative edit surface for an agent repair or creation step.

        Precedence is deliberate: a concrete target (a named node/page/slot) means
        a targeted in-place edit, so it routes to ``structured_ops`` FIRST. Only a
        genuine asset *generation* request — signalled by an explicit verb such as
        "generate image"/"vectorize", never the bare word "asset" — routes to the
        asset tool. This stops an unrelated diagnostic like "font asset brand is
        not marked embeddable" (which merely contains the substring "asset") from
        hijacking a text-fit repair toward the image tool.
        """
        try:
            context = json.loads(context_json)
        except json.JSONDecodeError:
            context = {}
        if not isinstance(context, dict):
            context = {}
        intent_lower = intent.lower()
        target_keys = ("node_id", "page_id", "slot_id", "slot_key", "target")
        has_target = any(context.get(key) for key in target_keys)
        asset_generation = any(
            phrase in intent_lower
            for phrase in (
                "generate image",
                "generate an image",
                "generate a image",
                "image generation",
                "vectorize",
                "vectorise",
                "generate logo",
                "create logo",
                "create a logo",
                "generate qr",
                "qr code",
            )
        )
        if has_target and not asset_generation:
            recommendation = EditSurfaceRecommendation.structured_ops
        elif asset_generation:
            recommendation = EditSurfaceRecommendation.asset_tool
        elif any(
            word in intent_lower
            for word in ("create", "compose", "design", "layout", "draft")
        ):
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
        repair_class: Optional[str] = None,
        cluster_json: str = "null",
        permissions_json: str = "[]",
        prohibitions_json: str = "[]",
    ) -> str:
        """Create and persist a repair request without paraphrasing reviewer feedback."""
        diagnostics = diagnostics_from(json.loads(diagnostics_json))
        target_payload = json.loads(target_json)
        forbidden_changes = json.loads(forbidden_changes_json)
        cluster_payload = json.loads(cluster_json)
        permissions = json.loads(permissions_json)
        prohibitions = json.loads(prohibitions_json)
        request = RepairRequest(
            original_user_request=self.prompt,
            exact_feedback=exact_feedback,
            diagnostics=diagnostics,
            target=VisualTarget.model_validate(target_payload) if target_payload else None,
            repair_class=_coerce_repair_class(repair_class),
            cluster=(
                LayoutClusterTarget.model_validate(cluster_payload)
                if cluster_payload
                else None
            ),
            scene_summary=self._scene_summary(),
            allowed_edit_surface=EditSurfaceRecommendation(allowed_edit_surface),
            permissions=permissions,
            prohibitions=prohibitions,
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
        coerced_area = _coerce_gap_area(area)
        if coerced_area.value != area:
            summary = f"[reported area: {area}] {summary}"
        gap = GapRecord(
            area=coerced_area,
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

    def inspect(self, view: str, target: Optional[str] = None) -> str:
        """Read-only inspection of the in-memory scene. Pick `view`:

        - `view="scene"` — document, pages, counts, slots, effective brand.
        - `view="page"` (target=page_id) — page node tree with geometry + slot bindings.
        - `view="node_tree"` (target=page_id) — the node hierarchy for one page.
        - `view="slots"` — every slot key → bound nodes.
        - `view="geometry"` (target=node_id) — stored computed geometry + declared
          transform/size for one node.
        - `view="slot_bindings"` (target=slot_key) — binding details for a semantic slot.

        Use it to confirm a node/page/slot id before targeting a repair. Never mutates."""
        if view == "scene":
            return self.summarize_scene()
        if view == "slots":
            return self.summarize_slots()
        if view == "page":
            if not target:
                return self._tool_error(
                    "inspect.bad_request", "view='page' requires target=<page_id>."
                )
            return self.summarize_page(target)
        if view == "node_tree":
            if not target:
                return self._tool_error(
                    "inspect.bad_request", "view='node_tree' requires target=<page_id>."
                )
            return self.summarize_node_tree(target)
        if view == "geometry":
            if not target:
                return self._tool_error(
                    "inspect.bad_request", "view='geometry' requires target=<node_id>."
                )
            return self.query_geometry(target)
        if view == "slot_bindings":
            if not target:
                return self._tool_error(
                    "inspect.bad_request", "view='slot_bindings' requires target=<slot_key>."
                )
            return self.query_slot_bindings(target)
        return self._tool_error(
            "inspect.unknown_view",
            f"unknown view '{view}'.",
            valid_views=["scene", "page", "node_tree", "slots", "geometry", "slot_bindings"],
        )

    def curated_context(
        self,
        *,
        user_request: str,
        previous_feedback: list[JsonObject],
        director_decisions: list[JsonObject],
    ) -> JsonObject:
        """Build a small, capped situation report from canonical state.

        This is the P1 replacement for the old `full_activity_context`. It is
        rebuilt fresh every iteration and NEVER embeds the whole scene, raw trace
        events, iteration files, base64 PNGs, or full SVG text. Every field is
        hard-capped, so the director/author/reviewer prompt stays bounded no
        matter how many repair iterations run. The latest preview image is sent
        separately as one image block (see providers), not inlined here.
        """
        diagnostics = self._latest_diagnostics_ranked(previous_feedback)
        target_ids = self._diagnostic_target_ids(diagnostics)
        contact_sheet, contact_sheet_omitted = self._brand_asset_contact_sheet()
        context: JsonObject = {
            "run_id": self.run_id,
            "iteration": self.iteration,
            "user_request": user_request,
            "original_prompt": self.prompt,
            # Phase 0b: a seeded run continues the user's live document — the
            # director must choose continuation modes (targeted_patch /
            # layout_cluster_rewrite), never fresh authoring.
            "seeded_from_initial_scene": self.seeded_from_initial_scene,
            "conversation_context": extract_editor_conversation_context(self.prompt),
            "scene_summary": self._scene_summary(),
            "scene_subtree": self._scene_subtree_for_targets(target_ids),
            "diagnostics": diagnostics,
            "latest_feedback": self._latest_feedback_brief(previous_feedback),
            "latest_critique": self._latest_critique(previous_feedback),
            "attempt_history": self._attempt_history(
                director_decisions, previous_feedback
            ),
            "preview_summary": self._preview_summary(
                diagnostics, previous_feedback
            ),
            "loaded_knowledge": self._capped_knowledge(),
            "effective_brand_context": copy.deepcopy(self.effective_brand_context),
            # K1: the compact kit digest (tone, resolved role colors, accent,
            # type roles, logo/image inventory) — the author styles CTAs from
            # its `accent`, the reviewer critiques brand-fit against it.
            "brand_card": copy.deepcopy(self.brand_card),
            "gaps": copy.deepcopy(self.gaps[-CONTEXT_MAX_ATTEMPTS:]),
        }
        # Slice 2: attach the kit-asset contact sheet (thumbnail PATHS + labels) so
        # the Director can choose imagery/logo placements by LOOKING (providers turns
        # each `preview_path` into a vision block at the boundary). Only present when
        # the document has an attached kit whose assets resolve to real previews.
        if contact_sheet:
            context["brand_asset_contact_sheet"] = contact_sheet
            if contact_sheet_omitted:
                context["brand_asset_contact_sheet_omitted"] = contact_sheet_omitted
            self.record(
                "director",
                "contact_sheet_attached",
                output_summary=f"{len(contact_sheet)} asset previews",
                payload={"asset_ids": [entry["asset_id"] for entry in contact_sheet]},
            )
        return context

    # -- Curated-context helpers (all bounded; no file re-reads, no nesting) --

    def _brand_asset_contact_sheet(self) -> tuple[list[JsonObject], int]:
        """Slice 2 D1: the Director's contact sheet — one entry per kit asset that
        resolves to a real on-disk preview, capped at CONTACT_SHEET_MAX.

        Order: logo assets first, then described images (a `title` means the ingest
        pipeline described it → author-selectable), then the rest. Each entry carries
        only PATHS + small strings — never base64 (bytes ride as vision blocks at the
        model boundary). Assets with no usable raster preview (e.g. an SVG with no
        thumbnail) are skipped and counted in the returned omitted total, so a broken
        path never reaches the model."""
        manifest = self.config.brand_kit_assets or {}
        if not manifest:
            return [], 0

        def rank(item: tuple[str, JsonObject]) -> int:
            _asset_id, entry = item
            record = entry.get("record") or {}
            if record.get("kind") == "logo":
                return 0
            return 1 if entry.get("title") else 2

        ordered = sorted(manifest.items(), key=rank)
        sheet: list[JsonObject] = []
        omitted = 0
        for asset_id, entry in ordered:
            if not isinstance(entry, dict):
                omitted += 1
                continue
            record = entry.get("record") or {}
            resolved = self._asset_preview_path(record)
            if resolved is None:
                omitted += 1
                continue
            if len(sheet) >= CONTACT_SHEET_MAX:
                omitted += 1
                continue
            preview_path, pixel_width, pixel_height = resolved
            label = entry.get("title") or record.get("label") or asset_id
            sheet_entry: JsonObject = {
                "asset_id": asset_id,
                "kind": "logo" if record.get("kind") == "logo" else "image",
                "label": label,
                "preview_path": preview_path,
                "pixel_width": pixel_width,
                "pixel_height": pixel_height,
            }
            usage = entry.get("usage")
            if usage:
                sheet_entry["usage_note"] = str(usage)[:120]
            sheet.append(sheet_entry)
        return sheet, omitted

    def _placed_brand_asset_previews(self) -> list[JsonObject]:
        """Slice 2 D3: the reviewer's source-asset comparison list — the intersection
        of (image nodes in the CURRENT scene and their `asset_id`) with the kit
        manifest, each resolved to its source thumbnail path, capped at
        PLACED_PREVIEWS_MAX. Paths only, no base64. Non-kit imagery (generated heroes)
        is excluded — this list exists to verify KIT placements against their source."""
        manifest = self.config.brand_kit_assets or {}
        if not manifest:
            return []
        previews: list[JsonObject] = []
        seen: set[str] = set()
        for node in (self.scene.get("nodes") or {}).values():
            kind = node.get("kind") or {}
            if kind.get("kind") != "image":
                continue
            asset_id = kind.get("asset_id")
            if not asset_id or asset_id in seen or asset_id not in manifest:
                continue
            entry = manifest.get(asset_id) or {}
            record = entry.get("record") or {}
            resolved = self._asset_preview_path(record)
            if resolved is None:
                continue
            seen.add(asset_id)
            preview_path, _pw, _ph = resolved
            label = entry.get("title") or record.get("label") or asset_id
            previews.append(
                {
                    "asset_id": asset_id,
                    "label": label,
                    "preview_path": preview_path,
                }
            )
            if len(previews) >= PLACED_PREVIEWS_MAX:
                break
        return previews

    def _latest_diagnostics_ranked(
        self, previous_feedback: list[JsonObject]
    ) -> list[JsonObject]:
        """Most-recent compile/preflight diagnostics, errors first, capped."""
        raw: list[JsonObject] = []
        for entry in reversed(previous_feedback or []):
            raw = _extract_diagnostics(entry)
            if raw:
                break
        severity_rank = {"blocker": 0, "error": 1, "warning": 2, "info": 3}
        compact: list[JsonObject] = []
        for diagnostic in raw:
            if not isinstance(diagnostic, dict):
                continue
            compact.append(
                {
                    "severity": diagnostic.get("severity"),
                    "code": diagnostic.get("code"),
                    "message": str(diagnostic.get("message") or "")[:300],
                    "target_node_id": diagnostic.get("target_node_id"),
                    "target_page_id": diagnostic.get("target_page_id"),
                    "target_slot_id": diagnostic.get("target_slot_id"),
                    "target_slot_key": diagnostic.get("target_slot_key"),
                }
            )
        compact.sort(key=lambda d: severity_rank.get(d.get("severity") or "info", 4))
        return compact[:CONTEXT_MAX_DIAGNOSTICS]

    def _diagnostic_target_ids(self, diagnostics: list[JsonObject]) -> list[str]:
        slots = self.scene.get("slots", {})
        ids: list[str] = []
        for diagnostic in diagnostics:
            node_id = diagnostic.get("target_node_id")
            if node_id:
                ids.append(node_id)
            slot_ref = diagnostic.get("target_slot_id") or diagnostic.get(
                "target_slot_key"
            )
            if slot_ref:
                for slot_id, slot in slots.items():
                    if slot_id == slot_ref or slot.get("key") == slot_ref:
                        ids.extend(slot.get("bound_nodes", []))
        seen: set[str] = set()
        ordered: list[str] = []
        for node_id in ids:
            if node_id not in seen:
                seen.add(node_id)
                ordered.append(node_id)
        return ordered

    def _scene_subtree_for_targets(self, target_ids: list[str]) -> list[JsonObject]:
        """Briefs for the diagnosed nodes plus their parent and children only."""
        nodes = self.scene.get("nodes", {})
        if not target_ids or not nodes:
            return []
        parent_of: dict[str, str] = {}
        for parent_id, node in nodes.items():
            for child_id in node.get("children", []) or []:
                parent_of[child_id] = parent_id
        selected: list[JsonObject] = []
        seen: set[str] = set()

        def add(node_id: str) -> None:
            if node_id in seen or node_id not in nodes:
                return
            if len(selected) >= CONTEXT_MAX_SUBTREE_NODES:
                return
            seen.add(node_id)
            selected.append(self._node_brief(node_id))

        for node_id in target_ids:
            parent_id = parent_of.get(node_id)
            if parent_id:
                add(parent_id)
            add(node_id)
            for child_id in nodes.get(node_id, {}).get("children", []) or []:
                add(child_id)
        return selected

    def _latest_feedback_brief(
        self, previous_feedback: list[JsonObject]
    ) -> Optional[JsonObject]:
        """The single most-recent feedback entry, trimmed to its decision-relevant
        structure. Keeps `kind`/`repair_class`/`target`/`cluster` (what the
        deterministic director routes on) and visual issue categories, but drops
        the giant `exact_feedback`/`repair_request` strings so it stays bounded
        and never accumulates across iterations.
        """
        if not previous_feedback:
            return None
        latest = previous_feedback[-1]
        if not isinstance(latest, dict):
            return None
        brief: JsonObject = {
            "kind": latest.get("kind"),
            "repair_class": latest.get("repair_class"),
            "recommended_edit_surface": latest.get("recommended_edit_surface"),
            "target": latest.get("target"),
            "cluster": latest.get("cluster"),
            "surgical_repair": latest.get("surgical_repair"),
        }
        inner = latest.get("feedback")
        if isinstance(inner, dict) and latest.get("kind") == "visual":
            issues = inner.get("issues") or []
            brief["feedback"] = {
                "issues": [
                    {
                        "category": issue.get("category"),
                        "severity": issue.get("severity"),
                        "target": issue.get("target"),
                        "detail": str(issue.get("detail") or "")[:300],
                    }
                    for issue in issues[:CONTEXT_MAX_CRITIQUE_ISSUES]
                    if isinstance(issue, dict)
                ]
            }
        return brief

    def _latest_critique(
        self, previous_feedback: list[JsonObject]
    ) -> Optional[JsonObject]:
        for entry in reversed(previous_feedback or []):
            if isinstance(entry, dict) and entry.get("kind") == "visual":
                critique = entry.get("feedback") or {}
                issues = critique.get("issues") or []
                return {
                    "accepted": critique.get("accepted"),
                    "summary": str(critique.get("summary") or "")[:600],
                    "repair_instruction": str(
                        critique.get("repair_instruction") or ""
                    )[:600]
                    or None,
                    "confidence": critique.get("confidence"),
                    "issues": [
                        {
                            "category": issue.get("category"),
                            "severity": issue.get("severity"),
                            "detail": str(issue.get("detail") or "")[:300],
                            "target": issue.get("target"),
                        }
                        for issue in issues[:CONTEXT_MAX_CRITIQUE_ISSUES]
                        if isinstance(issue, dict)
                    ],
                }
        return None

    def _attempt_history(
        self,
        director_decisions: list[JsonObject],
        previous_feedback: list[JsonObject],
    ) -> JsonObject:
        """Short rolling summary of what was tried and how it was rejected."""
        decisions = [
            {
                "iteration": index + 1,
                "action_mode": decision.get("action_mode"),
                "rationale": str(decision.get("rationale") or "")[:200],
            }
            for index, decision in enumerate(director_decisions or [])
            if isinstance(decision, dict)
        ]
        outcomes = [
            {
                "kind": entry.get("kind"),
                "repair_class": entry.get("repair_class"),
                "recommended_edit_surface": entry.get("recommended_edit_surface"),
                "summary": _feedback_one_liner(entry),
            }
            for entry in (previous_feedback or [])
            if isinstance(entry, dict)
        ]
        return {
            "decisions": decisions[-CONTEXT_MAX_ATTEMPTS:],
            "outcomes": outcomes[-CONTEXT_MAX_ATTEMPTS:],
        }

    def _preview_summary(
        self,
        diagnostics: list[JsonObject],
        previous_feedback: list[JsonObject],
    ) -> JsonObject:
        """Image-pointer + structural digest of the latest preview (no raw SVG)."""
        latest = self.latest_preview_bundle or self.latest_export_summary or {}
        artifacts = latest.get("artifacts", []) if isinstance(latest, dict) else []
        svg = next(
            (a for a in artifacts if isinstance(a, dict) and a.get("format") == "svg"),
            {},
        )
        png = next(
            (a for a in artifacts if isinstance(a, dict) and a.get("format") == "png"),
            {},
        )
        pages = self.scene.get("pages", {})
        first_page = next(iter(pages.values()), {}) if pages else {}
        size = first_page.get("size") or {}
        width, height = size.get("width"), size.get("height")
        visible_text: list[str] = []
        for node in self.scene.get("nodes", {}).values():
            kind = node.get("kind", {})
            if isinstance(kind, dict) and kind.get("kind") == "text":
                content = kind.get("content")
                if content:
                    visible_text.append(str(content)[:CONTEXT_MAX_TEXT_LEN])
        overflow = [
            {
                "code": diagnostic.get("code"),
                "message": diagnostic.get("message"),
                "target_node_id": diagnostic.get("target_node_id"),
            }
            for diagnostic in diagnostics
            if (diagnostic.get("code") or "") in CONTEXT_OVERFLOW_CODES
        ]
        summary: JsonObject = {
            "view_box": f"0 0 {width} {height}" if width and height else None,
            "width": width,
            "height": height,
            "element_count": len(self.scene.get("nodes", {})),
            "visible_text": visible_text[:CONTEXT_MAX_VISIBLE_TEXT],
            "overflow": overflow,
            "png_path": png.get("path") or png.get("critic_input_path"),
            "svg_path": svg.get("path") or svg.get("critic_input_path"),
            "svg_byte_len": svg.get("byte_len"),
        }
        # Inline a capped SVG snippet ONLY for renderer/export problems, where the
        # raw vector output is the actual subject of repair. For everything else
        # the image block + structural digest above is higher-value per token.
        if _is_render_export_issue(diagnostics, previous_feedback):
            svg_path = summary["svg_path"]
            if svg_path and Path(svg_path).exists():
                text = Path(svg_path).read_text(encoding="utf-8", errors="replace")
                summary["svg_snippet"] = text[:CONTEXT_MAX_SVG_SNIPPET]
                summary["svg_snippet_truncated"] = len(text) > CONTEXT_MAX_SVG_SNIPPET
        return summary

    def _capped_knowledge(self) -> list[JsonObject]:
        capped: list[JsonObject] = []
        for snippet in (self.loaded_knowledge or [])[:CONTEXT_MAX_KNOWLEDGE]:
            if not isinstance(snippet, dict):
                continue
            item = dict(snippet)
            if isinstance(item.get("excerpt"), str):
                item["excerpt"] = item["excerpt"][:CONTEXT_MAX_KNOWLEDGE_EXCERPT]
            capped.append(item)
        return capped

    def start_fresh_rewrite_scene(self, reason: str) -> None:
        """Reset the live authoring scene for a director-approved rewrite.

        Phase 0b guarantee: a SEEDED scene is the user's live document and is
        unwipeable — the reset is refused (and recorded) instead of replacing
        the seed with an empty scene. The loop additionally coerces the action
        modes that request this away on seeded runs; this block is the
        belt-and-suspenders enforcement for any other caller.
        """
        if self.seeded_from_initial_scene:
            self.record(
                "director",
                "seeded_scene_wipe_blocked",
                input_summary=reason[:500],
                output_summary=(
                    "refused to reset the live scene: it was seeded from the "
                    "user's document and is unwipeable"
                ),
                payload={"reason": reason},
            )
            return
        self.scene = self.core.new_scene(self.run_id, "Agent-authored design")
        self.dsl_session = None
        self.scene_update_sources.append("director_fresh_rewrite")
        self.record(
            "director",
            "fresh_rewrite_scene_started",
            input_summary=reason[:500],
            output_summary="reset live scene for bounded structural rewrite",
            payload={"reason": reason},
        )

    def query_geometry(self, node_id: str) -> str:
        """Return stored computed geometry and declared transform/size for a node."""
        node = self.scene.get("nodes", {}).get(node_id)
        if node is None:
            return json.dumps({"status": "missing", "node_id": node_id}, indent=2)
        payload: JsonObject = {
            "status": "ok",
            "node_id": node_id,
            "transform": node.get("transform"),
            "size": node.get("size"),
            "computed": node.get("computed"),
        }
        # Phase 1e: a pinned node's geometry is human-owned — the box is
        # authoritative (transform x/y are ignored by the solver while
        # pinned). Surfaced only when set.
        if node.get("position_mode") == "absolute":
            payload["position_mode"] = "absolute"
            payload["absolute_box"] = node.get("absolute_box")
            payload["base_anchor"] = node.get("base_anchor")
        return json.dumps(payload, indent=2)

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

    def finalize_run(
        self,
        status: str,
        stop_reason: str,
        summary: str,
        critique_json: str = "{}",
        ops_valid_through_iteration: Optional[int] = None,
        baseline_advisory_json: str = "null",
        accommodation_json: str = "null",
    ) -> str:
        """Write the final run summary in a later-API-compatible local format.

        `ops_valid_through_iteration` names the last iteration whose applied
        operations are part of the returned draft scene (the keep-best snapshot
        can restore an EARLIER iteration's scene; ops from later iterations must
        then not be replayed by the editor). None means all ok iterations.

        `baseline_advisory_json` (agent-improvement follow-up 1): pre-existing
        diagnostics on the seeded scene that this turn never addressed —
        distinct field from `critique`/`diagnostics` on purpose, so the editor
        can show "N pre-existing issues predate this turn" without implying
        the turn caused or must fix them. `"null"` (default) means either an
        unseeded run or a run with no unaddressed baseline issues.
        """
        critique = json.loads(critique_json) if critique_json.strip() else {}
        baseline_advisory = (
            json.loads(baseline_advisory_json) if baseline_advisory_json.strip() else None
        )
        # Accommodation edits: turn-introduced crowding this run detected,
        # plus any position-only nudges it applied to the crowded neighbors —
        # the run result must ANNOUNCE accommodation moves, never smuggle them.
        accommodation = (
            json.loads(accommodation_json) if accommodation_json.strip() else None
        )
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
            "seeded_from_initial_scene": self.seeded_from_initial_scene,
            "ops_valid_through_iteration": ops_valid_through_iteration,
            "baseline_advisory": baseline_advisory,
            "accommodation": accommodation,
        }
        self._write_json(self.trace_dir / "final.json", payload)
        # Persist the FULL final scene (not just the summary) so offline tooling — the
        # imagery-quality eval runner in particular — can deterministically score the
        # design's use of imagery (node kinds, asset_placement, asset records, page
        # sizes) without re-running the agent or recompiling the DSL.
        if isinstance(self.scene, dict):
            self._write_json(self.trace_dir / "final_scene.json", self.scene)
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
        if self.event_sink is not None:
            # Progress streaming is best-effort: a sink failure must never
            # abort the design run (the file trace above is the source of
            # truth). Keep the payload lightweight — the checklist needs the
            # event name + summaries, not the full per-iteration payload.
            try:
                self.event_sink(
                    event,
                    {
                        "actor": actor,
                        "iteration": self.iteration,
                        "input_summary": input_summary,
                        "output_summary": output_summary,
                        "diagnostic_count": len(diagnostics or []),
                    },
                )
            except Exception:
                pass

    def _replace_scene_from_core_response(
        self,
        response: JsonObject,
        source: str,
        operations: Optional[list[JsonObject]] = None,
    ) -> None:
        scene = response.get("scene")
        if not isinstance(scene, dict):
            raise CoreError("helper.scene_missing", f"{source} did not return a scene")
        self.scene = scene
        self.scene_update_sources.append(source)
        if operations:
            self._log_scene_operations(source, operations)

    def _log_scene_operations(
        self, source: str, operations: list[JsonObject]
    ) -> None:
        """K2 accept-seam fix: THE proposal operation ledger. The editor's
        Accept replays the proposal's operation list onto the document — it
        never sees the runtime's working scene — so any scene mutation that
        is not in that list silently vanishes at accept (live-proven: the
        auto-registered logo record existed in the run's final scene but the
        accepted document had empty scene.assets → LUME0211). Every
        successful mutation logs here, tagged with its iteration so the
        keep-best ops window still applies; agent_response_from_trace reads
        this ledger instead of scraping compile.json. Preflight's resolution
        ops are deliberately NOT logged — token resolution on accept belongs
        to the K1.6(b) accept bake, and double-carrying it would duplicate."""
        self.operations_ledger.extend(
            {"iteration": self.iteration, "source": source, "operation": operation}
            for operation in operations
        )
        self._write_json(
            self.trace_dir / "operations_ledger.json",
            {"entries": self.operations_ledger},
        )

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
        summary: JsonObject = {
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
        freehand = self._freehand_summary()
        if freehand is not None:
            summary["freehand"] = freehand
        return summary

    def _freehand_summary(self) -> Optional[JsonObject]:
        """Phase 1e: the director/author's at-a-glance view of human-owned
        geometry. Present only when the scene has freehand state, so
        pre-freehand summaries stay byte-identical."""
        nodes = self.scene.get("nodes", {})
        pinned = [
            node_id
            for node_id, node in nodes.items()
            if node.get("position_mode") == "absolute"
        ]
        free_containers = [
            node_id
            for node_id, node in nodes.items()
            if isinstance(node.get("layout"), dict)
            and node["layout"].get("layout_mode") == "free"
        ]
        if not pinned and not free_containers:
            return None
        return {
            "pinned_nodes": pinned,
            "free_containers": free_containers,
            "note": (
                "human-owned geometry: pinned nodes keep their absolute_box "
                "across relayouts and must not be re-positioned; free "
                "containers hold hand-placed children"
            ),
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
        brief: JsonObject = {
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
        # Phase 1e freehand visibility: surfaced only when set (pre-freehand
        # briefs stay byte-identical). `position_mode: "absolute"` means a
        # human pinned this node — its absolute_box is human-owned geometry;
        # base_anchor records where the layout had it at detach (the delta is
        # the human's deliberate nudge). `layout_mode: "free"` marks a
        # container whose children are hand-placed.
        if node.get("position_mode") == "absolute":
            brief["position_mode"] = "absolute"
            if node.get("absolute_box") is not None:
                brief["absolute_box"] = node.get("absolute_box")
            if node.get("base_anchor") is not None:
                brief["base_anchor"] = node.get("base_anchor")
        layout = node.get("layout")
        if isinstance(layout, dict) and layout.get("layout_mode") == "free":
            brief["layout_mode"] = "free"
        return brief

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

    def _effective_brand_kit(self) -> tuple[str, JsonObject, Optional[str]]:
        """The Brand Kit this run designs against: (source, kit, notice).

        Precedence: a kit passed by value in config (the API's agent-turn path
        resolves the document's attached kit; the CLI a --brand-kit-file) →
        the platform default. The runtime never reads the API database.

        A document-attached kit is honored regardless of approval_status —
        attaching it was the human gate, and the editor canvas already resolves
        its values, so designing against a different kit would both split the
        document's visual truth and trip LUMB0101 (scene ref ≠ resolver kit,
        a hard error that short-circuits token resolution). An unapproved kit
        instead carries a notice so the trace and coordinator see the caveat.
        """
        kit = self.config.brand_kit
        if isinstance(kit, dict) and kit.get("id"):
            source = self.config.brand_kit_source or "config"
            status = str(kit.get("approval_status") or "").lower()
            notice = None
            if status != "approved":
                notice = (
                    f"brand kit {kit.get('id')} v{kit.get('version')} has "
                    f"approval_status={status or 'unknown'}; it is honored because "
                    "it is attached to this document, but its tokens and assets "
                    "are not yet human-approved"
                )
            return source, kit, notice
        return "platform_default", self.core.platform_default_brand_kit(), None

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
        # Honesty rule (K0): the context reports the kit preflight ACTUALLY ran
        # against; a scene ref never overwrites it. A ref for a different kit is
        # surfaced as a mismatch (preflight will also carry LUMB0101) instead of
        # silently masquerading as the effective kit.
        brand_ref = self.scene.get("meta", {}).get("brand_kit") or {}
        ref_id = brand_ref.get("brand_kit_id") or brand_ref.get("id")
        if ref_id:
            honored = ref_id == context.get("brand_kit_id")
            context = {**context, "scene_ref_honored": honored}
            if not honored:
                context["scene_brand_ref"] = {
                    "brand_kit_id": ref_id,
                    "version": (
                        str(brand_ref.get("version"))
                        if brand_ref.get("version") is not None
                        else None
                    ),
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


def extract_editor_conversation_context(prompt: str) -> JsonObject:
    marker = "Editor context JSON:"
    if marker not in prompt:
        return {"raw_prompt": prompt}
    _, context_text = prompt.split(marker, 1)
    context = parse_json_object(context_text.strip()) or {}
    conversation = context.get("conversation_context")
    if isinstance(conversation, dict):
        return conversation
    if isinstance(conversation, list):
        return {"messages": conversation}
    return {"raw_prompt": prompt}


# Common print/social aspect ratios; a generated image is snapped to the nearest
# one of these so the frame is filled cleanly without an odd model ratio.
_COMMON_ASPECTS: list[tuple[str, float]] = [
    ("1:1", 1.0),
    ("4:5", 4 / 5),
    ("5:4", 5 / 4),
    ("3:4", 3 / 4),
    ("4:3", 4 / 3),
    ("2:3", 2 / 3),
    ("3:2", 3 / 2),
    ("9:16", 9 / 16),
    ("16:9", 16 / 9),
    ("21:9", 21 / 9),
]
# Slice-0 hardcodes a sensible long-edge resolution by frame aspect; the explicit
# image_size tier (1K/2K/4K) lands in Step 7 (G0.2).
_IMAGE_LONG_EDGE = 1536


def _fixed_dim(spec: Any) -> Optional[float]:
    if isinstance(spec, dict) and spec.get("kind") == "fixed":
        value = spec.get("value")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _nearest_aspect_label(box_width: float, box_height: float) -> str:
    target = box_width / box_height
    return min(_COMMON_ASPECTS, key=lambda entry: abs(entry[1] - target))[0]


def _resolution_for_aspect(box_width: float, box_height: float) -> tuple[int, int]:
    if box_width >= box_height:
        width = _IMAGE_LONG_EDGE
        height = max(1, round(_IMAGE_LONG_EDGE * box_height / box_width))
    else:
        height = _IMAGE_LONG_EDGE
        width = max(1, round(_IMAGE_LONG_EDGE * box_width / box_height))
    return int(width), int(height)


def _image_warning(code: str, message: str) -> JsonObject:
    return {"severity": "warning", "phase": "validation", "code": code, "message": message}


def _coerce_gap_area(value: str) -> GapArea:
    """Tolerate a hallucinated gap area from the model (same failure class as
    _coerce_repair_class — a freeform label like 'structured_edit / text
    font_size persistence' crashed a whole run). Unknown values map to the
    closest catch-all rather than raising; the freeform text is preserved in
    the gap's summary/evidence either way."""
    try:
        return GapArea(value)
    except ValueError:
        return GapArea.agent_protocol


def _coerce_repair_class(value: Optional[str]) -> Optional[RepairClass]:
    """Tolerate an unknown/hallucinated repair_class from the model: an invalid
    enum value becomes None (unclassified) rather than raising and crashing the run."""
    if not value:
        return None
    try:
        return RepairClass(value)
    except ValueError:
        return None


def _as_diag_list(raw: Any) -> list[JsonObject]:
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


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
