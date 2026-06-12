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

    for final_path in finals:
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
    }


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
