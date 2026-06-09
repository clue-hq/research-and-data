from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from lumen_api.core import CoreClient

from .config import AgentRuntimeConfig
from .knowledge import read_knowledge
from .schemas import LumenRunTraceEvent, new_run_id


JsonObject = Dict[str, Any]


class LumenDesignTools:
    def __init__(self, config: AgentRuntimeConfig, prompt: str) -> None:
        self.config = config
        self.core = CoreClient(repo_root=config.repo_root)
        self.run_id = new_run_id()
        self.iteration = 0
        self.trace_dir = config.trace_dir / self.run_id
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.scene = self.core.new_scene(self.run_id, "Agent-authored design")
        self.prompt = prompt
        self.preview_paths: list[str] = []
        self.record(
            "coordinator",
            "run_started",
            input_summary=prompt[:500],
            output_summary=f"created scene {self.run_id}",
        )

    def load_knowledge(self, query: str) -> str:
        """Load relevant Lumen design-engine knowledge snippets for a design task."""
        snippets = read_knowledge(self.config.repo_root, query)
        payload = {"snippets": [snippet.model_dump() for snippet in snippets]}
        self.record(
            "coordinator",
            "knowledge_loaded",
            input_summary=query,
            output_summary=f"loaded {len(snippets)} snippets",
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def compile_dsl_block(self, source: str) -> str:
        """Compile a Lumen DSL block into checked scene operations and update the scene."""
        self.iteration += 1
        response = self.core.compile_dsl_into_scene(self.scene, source)
        self.scene = response["scene"]
        dsl = response.get("dsl", {})
        compile_output = dsl.get("compile_output", {})
        diagnostics = compile_output.get("diagnostics", [])
        self.record(
            "dsl-author",
            "dsl_compiled",
            input_summary=source[:500],
            output_summary=(
                f"{len(compile_output.get('operations', []))} operations; "
                f"{len(diagnostics)} DSL diagnostics"
            ),
            diagnostics=diagnostics,
            payload={"dsl": dsl},
        )
        return json.dumps(
            {
                "applied_operations": response.get("applied_operations") or 0,
                "compile_output": compile_output,
                "operation_error": dsl.get("operation_error"),
            },
            indent=2,
        )

    def preflight_design(self) -> str:
        """Run canonical brand/token/layout preflight using the platform default Brand Kit."""
        brand_kit = self.core.platform_default_brand_kit()
        response = self.core.preflight_scene(self.scene, brand_kit)
        self.scene = response["scene"]
        diagnostics = response.get("diagnostics", [])
        preflight = response.get("preflight", {})
        self.record(
            "coordinator",
            "preflight_completed",
            output_summary=(
                f"has_errors={preflight.get('has_errors')}; "
                f"{len(diagnostics)} diagnostics"
            ),
            diagnostics=diagnostics,
            payload={"preflight": preflight},
        )
        return json.dumps(
            {
                "diagnostics": diagnostics,
                "preflight": preflight,
            },
            indent=2,
        )

    def export_preview(self, export_format: Optional[str] = None) -> str:
        """Export an SVG or PNG preview for visual critique and return local artifact paths."""
        preview_format = export_format or self.config.preview_format
        response = self.core.export_preview(self.scene, preview_format)
        export = response["export"]
        artifacts = []
        for index, artifact in enumerate(export.get("artifacts", []), start=1):
            raw_bytes = bytes(artifact.get("bytes", []))
            suffix = artifact.get("format", preview_format)
            path = self.trace_dir / f"preview_{self.iteration}_{index}.{suffix}"
            path.write_bytes(raw_bytes)
            self.preview_paths.append(str(path))
            artifacts.append(
                {
                    "format": artifact.get("format"),
                    "mime_type": artifact.get("mime_type"),
                    "page_id": artifact.get("page_id"),
                    "byte_len": len(raw_bytes),
                    "path": str(path),
                }
            )
        self.record(
            "coordinator",
            "preview_exported",
            output_summary=f"exported {len(artifacts)} {preview_format} artifact(s)",
            diagnostics=response.get("diagnostics", []),
            payload={"artifacts": artifacts},
        )
        return json.dumps(
            {
                "diagnostics": response.get("diagnostics", []),
                "artifacts": artifacts,
            },
            indent=2,
        )

    def summarize_scene(self) -> str:
        """Return a compact scene summary for planning or repair targeting."""
        pages = self.scene.get("pages", {})
        nodes = self.scene.get("nodes", {})
        slots = self.scene.get("slots", {})
        summary = {
            "document_id": self.scene.get("meta", {}).get("id"),
            "title": self.scene.get("meta", {}).get("title"),
            "page_count": len(pages),
            "node_count": len(nodes),
            "slot_count": len(slots),
            "pages": [
                {
                    "id": page_id,
                    "name": page.get("name"),
                    "size": page.get("size"),
                    "children": page.get("children", []),
                }
                for page_id, page in pages.items()
            ],
            "slots": [
                {
                    "id": slot_id,
                    "key": slot.get("key"),
                    "bound_nodes": slot.get("bound_nodes", []),
                }
                for slot_id, slot in slots.items()
            ],
        }
        return json.dumps(summary, indent=2)

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
