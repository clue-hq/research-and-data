"""Imagery-quality eval runner (fixture-set spec, Phase 2/3).

Drives the imagery brief set through scoring and writes a versioned capture per brief:

    evaluation/imagery_fixtures/<brief_id>/<tag>/
        brief.json            # {id, artifact, prompt, expected_decision, role, risks}
        render.png            # the rendered PNG the judge scored
        scores.json           # judge_imagery() output (per-axis finals, accept, tier)
        asset_provenance.json # {asset_id, source_kind, status, dims, rendered, cached}
        run_meta.json         # {run_id, model, status, tag, ...}

Two ways to obtain a run to score:
  • ``--score-map run_map.json`` (offline) — a {brief_id: run_dir} mapping of ALREADY
    captured runs; reads each run's ``final_scene.json`` + PNG and scores it. No model
    calls unless ``--model`` is given (the JUDGE ceiling); without a model only the
    deterministic gates run.
  • ``--run`` (live, costs credits) — invokes ``python -m lumen_deepagent.cli ...
    --mode deepagent`` per brief, then scores the resulting trace dir.

The scoring core (``score_run_dir``) and aggregation (``summarize``) are pure and
unit-tested offline; only ``run_brief_live`` touches the network/subprocess.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Make the package importable when run as a script from anywhere.
_AGENT_ROOT = Path(__file__).resolve().parents[1]
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))
_API_ROOT = _AGENT_ROOT.parent / "api"
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from py_lumen_config import settings  # noqa: E402

from lumen_deepagent.imagery_judge import judge_imagery  # noqa: E402

DEFAULT_BRIEFS = _AGENT_ROOT / "evaluation" / "imagery_fixtures" / "briefs.json"
DEFAULT_PROMPTS = _AGENT_ROOT / "evaluation" / "fixture_prompts.json"
DEFAULT_OUT = _AGENT_ROOT / "evaluation" / "imagery_fixtures"


def merge_briefs(briefs_path: Path, prompts_path: Path) -> List[Dict[str, Any]]:
    """Join the imagery sidecar (expected_decision/role/risks) with the prompt text,
    yielding one self-contained brief record per id. Briefs without a prompt are
    skipped with a warning (they can't be run)."""
    briefs = json.loads(Path(briefs_path).read_text(encoding="utf-8"))
    prompts = {p["id"]: p for p in json.loads(Path(prompts_path).read_text(encoding="utf-8"))}
    merged: List[Dict[str, Any]] = []
    for brief_id, sidecar in briefs.items():
        prompt = prompts.get(brief_id)
        if not prompt:
            print(f"[warn] brief {brief_id!r} has no prompt in {prompts_path}; skipping")
            continue
        merged.append(
            {
                "id": brief_id,
                "artifact": sidecar.get("artifact") or prompt.get("artifact"),
                "prompt": prompt["prompt"],
                "expected_decision": sidecar.get("expected_decision"),
                "role": sidecar.get("role"),
                "risks": sidecar.get("risks") or [],
            }
        )
    return merged


def _latest_png(run_dir: Path, preview_paths: List[str]) -> Optional[Path]:
    """Resolve the rendered PNG to judge: prefer the last PNG in final.json's
    preview_paths, else scan the iteration dirs for a preview.png."""
    for raw in reversed(preview_paths or []):
        candidate = Path(raw)
        if candidate.suffix == ".png" and candidate.exists():
            return candidate
    iterations = run_dir / "iterations"
    if iterations.is_dir():
        pngs = sorted(iterations.glob("*/preview.png"))
        if pngs:
            return pngs[-1]
    return None


def _asset_provenance(scene: Dict[str, Any]) -> Dict[str, Any]:
    """Pull the first placed image asset's provenance for the capture sidecar."""
    assets = scene.get("assets") or {}
    nodes = scene.get("nodes") or {}
    for node in nodes.values():
        kind = node.get("kind")
        if not (isinstance(kind, dict) and kind.get("kind") == "image"):
            continue
        asset = assets.get(kind.get("asset_id")) or {}
        raster = asset.get("raster") or {}
        bounds = (node.get("computed") or {}).get("layout_bounds") or {}
        return {
            "asset_id": kind.get("asset_id"),
            "source_kind": (asset.get("source") or {}).get("kind"),
            "model": (asset.get("source") or {}).get("model"),
            "status": asset.get("status"),
            "asset_kind": asset.get("kind"),
            "pixel_width": raster.get("pixel_width"),
            "pixel_height": raster.get("pixel_height"),
            "rendered_width": bounds.get("width"),
            "rendered_height": bounds.get("height"),
            "fit": (node.get("asset_placement") or {}).get("fit"),
        }
    return {"asset_id": None, "note": "no image node in the final scene"}


def score_run_dir(
    run_dir: Path,
    brief: Dict[str, Any],
    *,
    model: Any = None,
    config: Any = None,
) -> Dict[str, Any]:
    """Score one captured run directory: read its full final scene + rendered PNG and
    run the imagery judge (deterministic gates + optional LLM ceiling). Pure I/O glue
    over ``judge_imagery`` so it is offline-testable with a synthetic dir + fake model."""
    run_dir = Path(run_dir)
    scene = json.loads((run_dir / "final_scene.json").read_text(encoding="utf-8"))
    final = {}
    final_path = run_dir / "final.json"
    if final_path.exists():
        final = json.loads(final_path.read_text(encoding="utf-8"))
    png = _latest_png(run_dir, final.get("preview_paths") or [])
    scores = judge_imagery(scene, png, brief, model=model, config=config)
    scores["run_id"] = final.get("run_id")
    scores["run_status"] = final.get("status")
    scores["png_path"] = str(png) if png else None
    scores["_scene"] = scene  # internal: used by write_capture for provenance; popped on write
    return scores


def write_capture(
    out_root: Path,
    brief: Dict[str, Any],
    scores: Dict[str, Any],
    *,
    tag: str,
    model: Optional[str] = None,
) -> Path:
    """Write the per-brief, per-tag capture (brief/scores/provenance/run_meta + render)."""
    capture_dir = Path(out_root) / brief["id"] / tag
    capture_dir.mkdir(parents=True, exist_ok=True)
    scene = scores.pop("_scene", {})
    png_path = scores.get("png_path")

    (capture_dir / "brief.json").write_text(json.dumps(brief, indent=2), encoding="utf-8")
    (capture_dir / "scores.json").write_text(json.dumps(scores, indent=2), encoding="utf-8")
    (capture_dir / "asset_provenance.json").write_text(
        json.dumps(_asset_provenance(scene), indent=2), encoding="utf-8"
    )
    (capture_dir / "run_meta.json").write_text(
        json.dumps(
            {
                "run_id": scores.get("run_id"),
                "run_status": scores.get("run_status"),
                "model": model,
                "tag": tag,
                "brief_id": brief["id"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if png_path and Path(png_path).exists():
        shutil.copyfile(png_path, capture_dir / "render.png")
    return capture_dir


def parse_cli_payload(stdout: str) -> Optional[Dict[str, Any]]:
    """Parse the CLI's result payload from stdout. The CLI prints it as INDENTED
    multi-line JSON (the old last-line parse only ever saw the closing brace), and
    tool/framework chatter may precede it — so parse the last top-level object."""
    text = stdout.strip()
    start = text.rfind("\n{")
    candidate = text[start + 1 :] if start != -1 else text
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict) and payload.get("run_id"):
        return payload
    return None


def run_brief_live(brief: Dict[str, Any], *, repo_root: Path, trace_root: Path, mode: str = "deepagent") -> Optional[Path]:
    """Invoke the agent CLI for one brief and return its trace dir. COSTS CREDITS and
    requires the model/image-model env to be configured. Returns None on failure."""
    cmd = [
        sys.executable, "-m", "lumen_deepagent.cli", brief["prompt"],
        "--mode", mode, "--repo-root", str(repo_root),
    ]
    env_note = f"[run] {brief['id']} ({brief['expected_decision']}) via --mode {mode}"
    print(env_note)
    proc = subprocess.run(cmd, cwd=str(_AGENT_ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"[error] {brief['id']} CLI failed: {proc.stderr[-500:]}")
        return None
    payload = parse_cli_payload(proc.stdout)
    if payload is None:
        print(f"[error] {brief['id']} could not parse run_id from CLI output")
        return None
    return Path(trace_root) / payload["run_id"]


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate accept rate + tier counts overall and per expected-decision bucket."""
    scored = [r for r in results if r.get("scores")]
    tiers: Dict[str, int] = {"ship": 0, "tweak": 0, "redo": 0}
    by_decision: Dict[str, Dict[str, int]] = {}
    accepted = 0
    for r in scored:
        s = r["scores"]
        tier = s.get("tier", "redo")
        tiers[tier] = tiers.get(tier, 0) + 1
        accepted += 1 if s.get("accept") else 0
        bucket = by_decision.setdefault(
            r["brief"].get("expected_decision") or "unknown",
            {"n": 0, "accept": 0},
        )
        bucket["n"] += 1
        bucket["accept"] += 1 if s.get("accept") else 0
    return {
        "briefs_scored": len(scored),
        "accept_rate": round(accepted / len(scored), 3) if scored else 0.0,
        "tiers": tiers,
        "by_decision": by_decision,
    }


def diff_tags(brief_capture_dir: Path, tag_a: str, tag_b: str) -> Dict[str, Any]:
    """Phase-3 cross-tag regression diff for one brief: per-axis + weighted-mean deltas
    and tier transition between two captures (e.g. baseline-pre-step9 → post-step9)."""
    a = json.loads((Path(brief_capture_dir) / tag_a / "scores.json").read_text(encoding="utf-8"))
    b = json.loads((Path(brief_capture_dir) / tag_b / "scores.json").read_text(encoding="utf-8"))
    axis_delta = {}
    for axis, payload in (b.get("per_axis") or {}).items():
        before = ((a.get("per_axis") or {}).get(axis) or {}).get("final")
        after = payload.get("final")
        if before is not None and after is not None:
            axis_delta[axis] = after - before
    regressed = a.get("tier") == "ship" and b.get("tier") in {"tweak", "redo"}
    return {
        "tier": {"from": a.get("tier"), "to": b.get("tier"), "regressed_from_ship": regressed},
        "weighted_mean": {"from": a.get("weighted_mean"), "to": b.get("weighted_mean")},
        "axis_delta": axis_delta,
    }


def run_imagery_evals(
    *,
    briefs_path: Path = DEFAULT_BRIEFS,
    prompts_path: Path = DEFAULT_PROMPTS,
    out_root: Path = DEFAULT_OUT,
    tag: str = "baseline-pre-step9",
    score_map: Optional[Dict[str, str]] = None,
    live: bool = False,
    repo_root: Optional[Path] = None,
    trace_root: Optional[Path] = None,
    only: Optional[List[str]] = None,
    config: Any = None,
    model: Any = None,
    model_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Score the whole imagery brief set into a versioned capture and return a summary."""
    briefs = merge_briefs(briefs_path, prompts_path)
    if only:
        briefs = [b for b in briefs if b["id"] in set(only)]
    results: List[Dict[str, Any]] = []
    for brief in briefs:
        if live:
            run_dir = run_brief_live(brief, repo_root=repo_root or _AGENT_ROOT.parent.parent, trace_root=trace_root)
        else:
            mapped = (score_map or {}).get(brief["id"])
            run_dir = Path(mapped) if mapped else None
        if not run_dir or not (Path(run_dir) / "final_scene.json").exists():
            print(f"[skip] {brief['id']}: no scored run dir (final_scene.json missing)")
            results.append({"brief": brief, "scores": None})
            continue
        scores = score_run_dir(run_dir, brief, model=model, config=config)
        write_capture(out_root, brief, scores, tag=tag, model=model_name)
        results.append({"brief": brief, "scores": scores})
        print(f"[scored] {brief['id']}: tier={scores['tier']} accept={scores['accept']} mean={scores['weighted_mean']}")
    summary = summarize(results)
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Lumen imagery-quality eval set.")
    parser.add_argument("--briefs", type=Path, default=DEFAULT_BRIEFS)
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--tag", default="baseline-pre-step9", help="Capture tag (regression baseline name).")
    parser.add_argument("--score-map", type=Path, help="JSON {brief_id: run_dir} of already-captured runs (offline).")
    parser.add_argument("--run", action="store_true", help="Drive the agent CLI live per brief (COSTS CREDITS).")
    parser.add_argument("--mode", default="deepagent", choices=["deepagent", "quality-loop"])
    parser.add_argument("--repo-root", type=Path, default=_AGENT_ROOT.parent.parent)
    parser.add_argument("--trace-root", type=Path, help="Trace dir root for live runs (LUMEN_AGENT_TRACE_DIR).")
    parser.add_argument("--model", help="Model id for the LLM JUDGE ceiling (omit to run deterministic gates only).")
    parser.add_argument("--only", nargs="*", help="Score only these brief ids.")
    args = parser.parse_args()

    config = None
    model = None
    if args.model:
        from lumen_deepagent.imagery_judge import ImageryJudgeVerdict
        from lumen_deepagent.providers import init_model, try_structured_model

        # Same routing contract as AgentRuntimeConfig.from_env: when the agent env
        # points at an OpenAI-compatible endpoint (e.g. OpenRouter), the judge must
        # ride it too — a bare init_model() would demand OPENAI_API_KEY instead.
        model = try_structured_model(
            init_model(
                args.model,
                base_url=settings.lumen_agent_base_url,
                api_key=settings.lumen_agent_api_key,
                reasoning=settings.lumen_agent_reasoning,
            ),
            ImageryJudgeVerdict,
        )

    score_map = json.loads(args.score_map.read_text(encoding="utf-8")) if args.score_map else None
    run_imagery_evals(
        briefs_path=args.briefs,
        prompts_path=args.prompts,
        out_root=args.out,
        tag=args.tag,
        score_map=score_map,
        live=args.run,
        repo_root=args.repo_root,
        trace_root=args.trace_root,
        only=args.only,
        config=config,
        model=model,
        model_name=args.model,
    )


if __name__ == "__main__":
    main()
