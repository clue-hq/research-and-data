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
    failure_attribution: Counter[str] = Counter()
    brand_kits: Counter[str] = Counter()
    brand_modes: Counter[str] = Counter()
    preview_paths: list[str] = []
    brand_contexts: list[dict[str, Any]] = []
    run_attributions: list[dict[str, Any]] = []
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
        attribution = attribute_run_failure(run_dir, final)
        run_attributions.append(attribution)
        failure_attribution[attribution["primary"]] += 1

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
        "failure_attribution": dict(failure_attribution),
        "run_attributions": run_attributions,
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


def attribute_run_failure(run_dir: Path, final: dict[str, Any]) -> dict[str, Any]:
    """Classify the likely blocker using only persisted trace evidence.

    The label is an audit starting point, not a proof. It lets the team separate
    agent protocol failures from deterministic layout/export/reviewer blockers
    before opening individual trace files.
    """
    run_id = str(final.get("run_id") or run_dir.name)
    status = str(final.get("status") or "")
    stop_reason = str(final.get("stop_reason") or "")
    evidence: list[str] = []
    signals = summarize_run_trace(run_dir)
    diagnostic_codes = collect_iteration_diagnostic_codes(run_dir)
    trace_events = collect_trace_events(run_dir)
    gap_areas = [
        str(gap.get("area"))
        for gap in final.get("gaps", [])
        if isinstance(gap, dict) and gap.get("area")
    ]

    if status == "accepted":
        return {
            "run_id": run_id,
            "status": status,
            "stop_reason": stop_reason,
            "primary": "accepted",
            "confidence": "high",
            "evidence": ["final status is accepted"],
            "diagnostic_codes": diagnostic_codes,
            "gap_areas": gap_areas,
        }

    if stop_reason in {"export_failed", "preview_invalid"} or (
        "rendering_export_preview" in gap_areas
    ):
        evidence.append(f"stop_reason={stop_reason}")
        if "rendering_export_preview" in gap_areas:
            evidence.append("gap:rendering_export_preview")
        return attribution_payload(
            run_id,
            status,
            stop_reason,
            "renderer_export_preview",
            "high",
            evidence,
            diagnostic_codes,
            gap_areas,
            trace_events,
        )

    if stop_reason == "critic_failed":
        return attribution_payload(
            run_id,
            status,
            stop_reason,
            "visual_reviewer",
            "high",
            ["visual reviewer/provider failed before a usable critique"],
            diagnostic_codes,
            gap_areas,
            trace_events,
        )

    if stop_reason == "unsupported_capability" or gap_areas:
        evidence.extend(f"gap:{area}" for area in gap_areas)
        return attribution_payload(
            run_id,
            status,
            stop_reason,
            "unsupported_capability",
            "high" if stop_reason == "unsupported_capability" else "medium",
            evidence or [f"stop_reason={stop_reason}"],
            diagnostic_codes,
            gap_areas,
            trace_events,
        )

    if (
        signals["destructive_repair_rejections"]
        or signals["whole_scene_regeneration_attempts"]
        or signals["layout_cluster_rejections"]
        or any(code.startswith(("LUMA", "LUMD")) for code in diagnostic_codes)
    ):
        if signals["destructive_repair_rejections"]:
            evidence.append(
                f"{signals['destructive_repair_rejections']} destructive repair rejection(s)"
            )
        if signals["whole_scene_regeneration_attempts"]:
            evidence.append(
                f"{signals['whole_scene_regeneration_attempts']} whole-scene rewrite attempt(s)"
            )
        if signals["layout_cluster_rejections"]:
            evidence.append(
                f"{signals['layout_cluster_rejections']} layout-cluster guard rejection(s)"
            )
        compile_codes = [
            code for code in diagnostic_codes if code.startswith(("LUMA", "LUMD"))
        ]
        if compile_codes:
            evidence.append(f"compile/authoring diagnostic codes: {', '.join(compile_codes)}")
        return attribution_payload(
            run_id,
            status,
            stop_reason,
            "agent_authoring",
            "high",
            evidence,
            diagnostic_codes,
            gap_areas,
            trace_events,
        )

    if (
        signals["layout_cluster_repairs"]
        or signals["remaining_artboard_overflow"]
        or signals["remaining_parent_overflow"]
        or any(code.startswith(("LUMV08", "LUMV09")) for code in diagnostic_codes)
    ):
        if signals["layout_cluster_repairs"]:
            evidence.append(
                f"{signals['layout_cluster_repairs']} layout-cluster repair request(s)"
            )
        if signals["remaining_artboard_overflow"]:
            evidence.append(
                f"{signals['remaining_artboard_overflow']} artboard overflow diagnostic(s)"
            )
        if signals["remaining_parent_overflow"]:
            evidence.append(
                f"{signals['remaining_parent_overflow']} parent overflow diagnostic(s)"
            )
        geometry_codes = [
            code for code in diagnostic_codes if code.startswith(("LUMV08", "LUMV09"))
        ]
        if geometry_codes:
            evidence.append(f"layout/fit diagnostic codes: {', '.join(geometry_codes)}")
        return attribution_payload(
            run_id,
            status,
            stop_reason,
            "layout_contract",
            "medium",
            evidence,
            diagnostic_codes,
            gap_areas,
            trace_events,
        )

    critique = final.get("critique") or {}
    if stop_reason in {"reviewer_rejected", "max_iterations_reached"} and critique:
        issues = critique.get("issues") if isinstance(critique, dict) else []
        categories = sorted(
            {
                str(issue.get("category"))
                for issue in issues or []
                if isinstance(issue, dict) and issue.get("category")
            }
        )
        if categories:
            evidence.append(f"unresolved reviewer categories: {', '.join(categories)}")
        return attribution_payload(
            run_id,
            status,
            stop_reason,
            "visual_quality",
            "medium",
            evidence or [f"stop_reason={stop_reason}"],
            diagnostic_codes,
            gap_areas,
            trace_events,
        )

    return attribution_payload(
        run_id,
        status,
        stop_reason,
        "unknown",
        "low",
        [f"stop_reason={stop_reason}" if stop_reason else "no stop reason"],
        diagnostic_codes,
        gap_areas,
        trace_events,
    )


def attribution_payload(
    run_id: str,
    status: str,
    stop_reason: str,
    primary: str,
    confidence: str,
    evidence: list[str],
    diagnostic_codes: list[str],
    gap_areas: list[str],
    trace_events: Counter[str],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": status,
        "stop_reason": stop_reason,
        "primary": primary,
        "confidence": confidence,
        "evidence": evidence[:8],
        "diagnostic_codes": diagnostic_codes,
        "gap_areas": gap_areas,
        "notable_events": {
            key: trace_events[key]
            for key in sorted(trace_events)
            if key
            in {
                "dsl_repair_not_surgical",
                "layout_cluster_repair_rejected",
                "preview_invalid",
                "export_failed",
                "critique_failed",
                "gap_recorded",
            }
        },
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


def collect_iteration_diagnostic_codes(run_dir: Path) -> list[str]:
    codes = {
        str(diagnostic.get("code"))
        for diagnostic in iter_iteration_diagnostics(run_dir)
        if diagnostic.get("code")
    }
    return sorted(codes)


def collect_trace_events(run_dir: Path) -> Counter[str]:
    events: Counter[str] = Counter()
    trace_path = run_dir / "trace.jsonl"
    if not trace_path.exists():
        return events
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = event.get("event")
        if name:
            events[str(name)] += 1
    return events


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
