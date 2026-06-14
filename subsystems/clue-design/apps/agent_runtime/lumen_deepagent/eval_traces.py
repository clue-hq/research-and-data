from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def summarize_trace_dir(trace_root: Path) -> dict[str, Any]:
    finals = sorted(trace_root.glob("*/final.json"))
    accepted = 0
    failed = 0
    stop_reasons: Counter[str] = Counter()
    issue_categories: Counter[str] = Counter()
    brand_kits: Counter[str] = Counter()
    brand_modes: Counter[str] = Counter()
    preview_paths: list[str] = []
    brand_contexts: list[dict[str, Any]] = []
    trace_metrics: Counter[str] = Counter()

    for final_path in finals:
        run_dir = final_path.parent
        final = json.loads(final_path.read_text(encoding="utf-8"))
        if final.get("status") == "accepted":
            accepted += 1
        else:
            failed += 1
        if final.get("stop_reason"):
            stop_reasons[str(final["stop_reason"])] += 1
        brand_context = final.get("effective_brand") or {}
        if isinstance(brand_context, dict):
            brand_contexts.append(
                {
                    "run_id": final.get("run_id") or final_path.parent.name,
                    "source": brand_context.get("source"),
                    "brand_kit_id": brand_context.get("brand_kit_id"),
                    "brand_kit_version": brand_context.get("brand_kit_version"),
                    "mode": brand_context.get("mode") or {},
                }
            )
            brand_key = brand_context_key(brand_context)
            if brand_key:
                brand_kits[brand_key] += 1
            mode_key = mode_context_key(brand_context.get("mode"))
            if mode_key:
                brand_modes[mode_key] += 1
        preview_paths.extend(final.get("preview_paths", []))
        critique = final.get("critique") or {}
        for issue in critique.get("issues", []):
            category = issue.get("category")
            if category:
                issue_categories[str(category)] += 1
        for gap in final.get("gaps", []):
            area = gap.get("area")
            if area:
                issue_categories[f"gap:{area}"] += 1
        trace_metrics.update(summarize_run_trace(run_dir))

    return {
        "trace_root": str(trace_root),
        "run_count": len(finals),
        "accepted": accepted,
        "failed": failed,
        "stop_reasons": dict(stop_reasons),
        "brand_kits": dict(brand_kits),
        "brand_modes": dict(brand_modes),
        "brand_contexts": brand_contexts,
        "unresolved_issue_categories": dict(issue_categories),
        "preview_paths": preview_paths,
        "layout_cluster_repairs": trace_metrics["layout_cluster_repairs"],
        "layout_cluster_rejections": trace_metrics["layout_cluster_rejections"],
        "destructive_repair_rejections": trace_metrics[
            "destructive_repair_rejections"
        ],
        "whole_scene_regeneration_attempts": trace_metrics[
            "whole_scene_regeneration_attempts"
        ],
        "oversized_background_rects": trace_metrics["oversized_background_rects"],
        "remaining_artboard_overflow": trace_metrics["remaining_artboard_overflow"],
        "remaining_parent_overflow": trace_metrics["remaining_parent_overflow"],
        "final_lumv080x_count": trace_metrics["final_lumv080x_count"],
        "final_lumv090x_count": trace_metrics["final_lumv090x_count"],
    }


def summarize_run_trace(run_dir: Path) -> Counter[str]:
    metrics: Counter[str] = Counter()
    for repair_path in sorted(run_dir.glob("iterations/*/repair_request.json")):
        payload = read_json_file(repair_path)
        request = payload.get("repair_request") or {}
        if request.get("repair_class") == "layout_cluster":
            metrics["layout_cluster_repairs"] += 1

    for diagnostic in iter_iteration_diagnostics(run_dir):
        count_geometry_diagnostic(metrics, diagnostic)

    trace_path = run_dir / "trace.jsonl"
    if trace_path.exists():
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_name = event.get("event")
            if event_name == "layout_cluster_repair_rejected":
                metrics["layout_cluster_rejections"] += 1
                if looks_like_whole_scene_rewrite(event):
                    metrics["whole_scene_regeneration_attempts"] += 1
            elif event_name == "dsl_repair_not_surgical":
                metrics["destructive_repair_rejections"] += 1
                if looks_like_whole_scene_rewrite(event):
                    metrics["whole_scene_regeneration_attempts"] += 1
    return metrics


def iter_iteration_diagnostics(run_dir: Path) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for path in sorted(run_dir.glob("iterations/*/*.json")):
        if path.name not in {"compile.json", "preflight.json"}:
            continue
        payload = read_json_file(path)
        for key in ("compile", "preflight"):
            summary = payload.get(key) or {}
            if isinstance(summary, dict):
                diagnostics.extend(
                    item
                    for item in summary.get("diagnostics", [])
                    if isinstance(item, dict)
                )
    return diagnostics


def count_geometry_diagnostic(metrics: Counter[str], diagnostic: dict[str, Any]) -> None:
    code = str(diagnostic.get("code") or "")
    if code.startswith("LUMV080"):
        metrics["final_lumv080x_count"] += 1
    if code.startswith("LUMV090"):
        metrics["final_lumv090x_count"] += 1
    if code == "LUMV0800":
        metrics["remaining_artboard_overflow"] += 1
        if diagnostic_mentions_background(diagnostic):
            metrics["oversized_background_rects"] += 1
    elif code == "LUMV0801":
        metrics["remaining_parent_overflow"] += 1


def diagnostic_mentions_background(diagnostic: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(diagnostic.get(key) or "")
        for key in (
            "message",
            "suggested_repair",
            "target_node_id",
            "target_page_id",
            "detail",
        )
    ).lower()
    return any(term in haystack for term in ("background", "bg", "backdrop"))


def looks_like_whole_scene_rewrite(event: dict[str, Any]) -> bool:
    payload = event.get("payload") or {}
    source = str(payload.get("rejected_source") or event.get("output_summary") or "")
    lowered = source.lower()
    return "page " in lowered or "delete(" in lowered


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def brand_context_key(brand_context: dict[str, Any]) -> str | None:
    brand_kit_id = brand_context.get("brand_kit_id")
    if not brand_kit_id:
        return None
    version = brand_context.get("brand_kit_version")
    return f"{brand_kit_id}@{version}" if version is not None else str(brand_kit_id)


def mode_context_key(mode: Any) -> str | None:
    if not isinstance(mode, dict) or not mode:
        return None
    return ",".join(f"{key}={mode[key]}" for key in sorted(mode))


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize Lumen Phase A run traces.")
    parser.add_argument(
        "--trace-root",
        type=Path,
        default=Path(".lumen-runs"),
        help="Directory containing per-run trace folders.",
    )
    args = parser.parse_args()
    print(json.dumps(summarize_trace_dir(args.trace_root), indent=2))


if __name__ == "__main__":
    main()
