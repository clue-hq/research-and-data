"""Run one Exa Agent discovery trial: fill the prompt, create the run, poll it, save everything.

    set -a; source .env; set +a
    uv run python trials/exa-agent-discovery/run_trial.py \
        --context <context.json> --effort high --out <run dir>

Writes request.json (without the key), run.json (the final GET body) and companies.json (the
structured output) into --out. Spends money: one Exa Agent run at the chosen effort.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import httpx

HERE = Path(__file__).parent
BASE = "https://api.exa.ai"
TERMINAL = {"completed", "failed", "cancelled"}


def _gates(context: dict) -> str:
    return "\n".join(
        f"- **{g['key']}**: {g['rule']} (How to check: {g['test']})" for g in context["gates"]
    )


def _exclude(context: dict) -> str:
    return "\n".join(
        f"- {c['name']}: {', '.join(c['domains']) or 'no domain known'}" for c in context["exclude"]
    )


def build_request(context: dict, effort: str, max_cost: float | None) -> dict:
    prompt = (HERE / "system_prompt.md").read_text()
    for key, value in {
        "seller_name": context["seller_name"],
        "seller_offer": context["seller_offer"],
        "icp_summary": context["icp_summary"],
        "gates": _gates(context),
        "exclude": _exclude(context),
        "competitors": context["competitors"],
        "target_count": str(context["target_count"]),
    }.items():
        prompt = prompt.replace("{" + key + "}", value)
    body: dict = {
        "query": (
            f"Find {context['target_count']} target companies for {context['seller_name']} that "
            f"match this profile: {context['query']}"
        ),
        "systemPrompt": prompt,
        "effort": effort,
        "outputSchema": json.loads((HERE / "output_schema.json").read_text()),
        "input": {
            "exclusion": [
                {"domain": domain} for c in context["exclude"] for domain in c["domains"]
            ]
        },
    }
    if max_cost is not None:
        body["budget"] = {"maxCostDollars": max_cost}
    return body


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True, type=Path)
    parser.add_argument("--effort", default="high")
    parser.add_argument("--max-cost", type=float, default=None)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--timeout-s", type=float, default=3600)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    body = build_request(json.loads(args.context.read_text()), args.effort, args.max_cost)
    (args.out / "request.json").write_text(json.dumps(body, indent=2, ensure_ascii=False))
    headers = {"Authorization": f"Bearer {os.environ['CLUE_EXA_API_KEY']}"}

    started = time.monotonic()
    with httpx.Client(base_url=BASE, headers=headers, timeout=60) as client:
        created = client.post("/agent/runs", json=body)
        if created.status_code >= 300:
            raise SystemExit(f"create refused: {created.status_code} {created.text[:2000]}")
        run = created.json()
        print("run", run.get("id"), run.get("status"), flush=True)
        while run.get("status") not in TERMINAL:
            if time.monotonic() - started > args.timeout_s:
                print("timed out; run id", run.get("id"))
                break
            time.sleep(10)
            run = client.get(f"/agent/runs/{run['id']}").json()
            print(f"{time.monotonic() - started:6.0f}s {run.get('status')}", flush=True)

    (args.out / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False))
    structured = (run.get("output") or {}).get("structured")
    (args.out / "companies.json").write_text(json.dumps(structured, indent=2, ensure_ascii=False))
    companies = (structured or {}).get("companies") or []
    print(
        f"status {run.get('status')} in {time.monotonic() - started:.0f}s, "
        f"cost {json.dumps(run.get('costDollars'))}, companies {len(companies)}: "
        + ", ".join(f"{c.get('name')} [{c.get('priority')}]" for c in companies)
    )
    if run.get("error"):
        print("error", run["error"])


if __name__ == "__main__":
    main()
