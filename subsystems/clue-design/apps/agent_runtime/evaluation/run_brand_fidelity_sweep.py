"""K4 exit-gate sweep: N live kit-attached agent turns scored on brand fidelity.

Runs each brief through POST /agent/turn-preview with the target Brand Kit
attached, then scores the run's AUTHORED scene (resolution consumes bindings;
never judge the resolved scene) with ``evaluation.brand_fidelity``. Output: a
per-brief table + aggregate, written to ``.context/kit-application/k4-sweep/``.

Usage:
    python -m evaluation.run_brand_fidelity_sweep \
        --kit-id brand_kit_ing_96fdfc5b3c134b36af96118bfc3b8a16 --kit-version 2
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

from evaluation.brand_fidelity import score_brand_fidelity

API = "http://127.0.0.1:8002"

#: Ten briefs spanning artifact archetypes (FULL marketing surfaces through
#: QUIET data surfaces) so the baseline measures the retokenizer and decide
#: step across scene shapes, not one lucky layout.
BRIEFS = [
    ("launch-announcement", "Design a launch announcement for our new AI phone agent. Bold headline, short subtitle, one call-to-action button. Use our logo and brand it properly."),
    ("event-poster", "Design a poster for our annual healthcare innovation summit: event name, date, venue, one keynote highlight, registration call-to-action. Brand it with our kit."),
    ("social-square", "Design a square social post celebrating a customer milestone: 50 clinics onboarded. Punchy stat, one supporting line, our logo."),
    ("pricing-promo", "Design a promo card for our starter plan: plan name, monthly price, three short feature bullets, a signup call-to-action. On-brand."),
    ("deck-title", "Design a presentation title slide: company name, deck title 'Front Office, Automated', presenter name and date. Brand it quietly and professionally."),
    ("stat-card", "Design a compact stat card for a report: one hero metric (99.5% extraction accuracy), a caption explaining it, small logo mark."),
    ("newsletter-header", "Design a newsletter header banner: publication name 'The Front Desk', issue tagline, month. Use brand colors and type."),
    ("job-posting", "Design a hiring announcement: role title 'Founding Designer', two-line pitch about the mission, apply call-to-action, our logo."),
    ("webinar-invite", "Design a webinar invitation: topic 'Cutting no-shows with AI', date and time, speaker name, register button. Brand-true."),
    ("thank-you-card", "Design a simple thank-you card for customers: warm short headline, one sentence of gratitude, sign-off from the team, logo mark."),
]


def _post(path: str, payload: dict, timeout: int = 560) -> dict:
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def _get(path: str) -> dict:
    with urllib.request.urlopen(API + path, timeout=60) as response:
        return json.loads(response.read())


def _seed_scene(kit_id: str, kit_version: int) -> dict:
    scene = json.load(open("/tmp/k4-seed.json"))
    scene["meta"]["brand_kit"] = {"id": kit_id, "version": kit_version}
    return scene


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit-id", required=True)
    parser.add_argument("--kit-version", type=int, required=True)
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument("--out", type=Path, default=Path(".context/kit-application/k4-sweep"))
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    kit = _get(f"/brand-kits/{args.kit_id}")["brand_kit_json"]
    (args.out / "kit.json").write_text(json.dumps(kit))

    results = []
    for index, (name, prompt) in enumerate(BRIEFS, 1):
        started = time.time()
        row = {"brief": name}
        try:
            turn = _post(
                "/agent/turn-preview",
                {
                    "prompt": prompt,
                    "scene": _seed_scene(args.kit_id, args.kit_version),
                    "max_iterations": args.max_iterations,
                },
            )
            row["status"] = turn.get("status")
            row["run_id"] = turn.get("run_id")
            trace_dir = turn.get("trace_dir")
            if trace_dir:
                run_dir = Path(trace_dir)
                authored = sorted(run_dir.glob("iterations/*/authored_scene.json"))
                source = authored[-1] if authored else run_dir / "final_scene.json"
                scene = json.loads(source.read_text())
                scene = scene.get("scene", scene)
                report = score_brand_fidelity(scene, kit)
                row["verdict"] = report["verdict"]
                row["scores"] = report["scores"]
                row["reasons"] = report["reasons"]
            else:
                row["verdict"] = "no-trace"
        except Exception as error:  # a failed brief never stops the sweep
            row["status"] = "sweep-error"
            row["error"] = str(error)[:300]
            row["verdict"] = "error"
        row["seconds"] = round(time.time() - started, 1)
        results.append(row)
        (args.out / "results.json").write_text(json.dumps(results, indent=1))
        print(f"[{index}/{len(BRIEFS)}] {name}: {row.get('verdict')} "
              f"({row.get('status')}, {row['seconds']}s)", flush=True)

    verdicts = [r.get("verdict") for r in results]
    summary = {v: verdicts.count(v) for v in sorted(set(verdicts))}
    bindings = [
        (r.get("scores") or {}).get("typography_binding")
        for r in results
        if isinstance(r.get("scores"), dict)
    ]
    bound = [b for b in bindings if isinstance(b, (int, float))]
    print("\nSWEEP SUMMARY:", json.dumps(summary))
    if bound:
        print(f"mean typography_binding: {sum(bound)/len(bound):.2f} over {len(bound)} scored runs")
    (args.out / "results.json").write_text(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
