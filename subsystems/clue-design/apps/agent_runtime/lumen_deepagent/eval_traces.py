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
    preview_paths: list[str] = []

    for final_path in finals:
        final = json.loads(final_path.read_text(encoding="utf-8"))
        if final.get("status") == "accepted":
            accepted += 1
        else:
            failed += 1
        if final.get("stop_reason"):
            stop_reasons[str(final["stop_reason"])] += 1
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
        "unresolved_issue_categories": dict(issue_categories),
        "preview_paths": preview_paths,
    }


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

