"""Prepare an isolated account discovery trial; no providers are called by preparation.

Execute with preview_live_account_research.py --prepared OUTPUT --discovery-trial.
Retains an approved, freshly authored Head brief; never imports past target research results.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

from research_preview_support import save

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "platform/agents/catalog/research-quality"
GUIDANCE = (
    ROOT / "docs/superpowers/previews/2026-09-24-account-discovery-trial/discovery-instructions.md"
)
RUNNERS = (
    "scripts/trial_account_discovery.py",
    "scripts/preview_live_account_research.py",
    "scripts/research_preview_support.py",
    "scripts/continue_person_research.py",
    "scripts/person_trial_source_review.py",
    "platform/api/clue_api/arv2/account_exa_brief.py",
    "platform/api/clue_api/arv2/exa_client.py",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside(root, name):
    path = root / name
    if (
        Path(name).is_absolute()
        or ".." in Path(name).parts
        or not path.resolve().is_relative_to(root.resolve())
    ):
        raise ValueError("Reference escapes snapshot")
    return path


def prepare(
    source: Path,
    out: Path,
    *,
    refined: bool = False,
    refinement: str | None = None,
    claim_ready: bool = False,
):
    versions = {
        "source-follow-through-v1": "source-follow-through.md",
        "source-follow-through-v2": "source-follow-through-v2.md",
    }
    if refined and refinement:
        raise ValueError("Choose --refined or --refinement, not both")
    selected_refinement = "source-follow-through-v1" if refined else refinement
    if selected_refinement is not None and selected_refinement not in versions:
        raise ValueError("Unknown refinement")
    if out.exists() and any(out.iterdir()):
        raise ValueError("Use a fresh output directory")
    original = json.loads((source / "manifest.json").read_text())
    selected = {}
    for name, sha in original["input_hashes"].items():
        path = inside(source, name)
        if digest(path) != sha:
            raise ValueError(f"Original input changed: {name}")
        if name in {
            "inputs/delegation-brief.md",
            "inputs/research/context.json",
        } or name.startswith(
            ("inputs/documents/", "inputs/project/", "inputs/research/documents/")
        ):
            selected[name] = sha
    for name in ("inputs/delegation-brief.md", "inputs/research/context.json"):
        if name not in selected:
            raise ValueError(f"Missing original input: {name}")
    context = json.loads((source / "inputs/research/context.json").read_text())
    for ref in [context["icp"], *context["personas"], *context["seller_documents"]]:
        doc = source / "inputs/documents" / Path(ref["path"]).name
        if digest(doc) != ref["sha256"] or str(doc.relative_to(source)) not in selected:
            raise ValueError("Pinned document mismatch")
    for name in selected:
        dest = out / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, dest)
    if claim_ready:
        today = date.today()
        month_index = today.year * 12 + today.month - 1 - 9
        year, month_zero = divmod(month_index, 12)
        start_date = date(
            year, month_zero + 1, min(today.day, calendar.monthrange(year, month_zero + 1)[1])
        )
        context.update(run_date=today.isoformat(), recent_window_start=start_date.isoformat())
        save(out / "inputs/research/context.json", context)

    guidance = GUIDANCE.read_text()
    refinement = (
        (GUIDANCE.parent / versions[selected_refinement]).read_text() if selected_refinement else ""
    )
    if refinement:
        guidance += "\n\n" + refinement
    skill_original = (CATALOG / "skills/account-dossier/v2/SKILL.md").read_text()
    start = skill_original.index("## Prepare without repetitive work")
    end = skill_original.index("## Research priorities and depth", start)
    skill = skill_original[:start] + guidance + "\n\n" + skill_original[end:]
    prompt_original = (CATALOG / "prompts/quality-account-research/v9/SYSTEM.md").read_text()
    prompt = prompt_original.split("---", 2)[2].strip()
    start = prompt.index("Batch independent context reads,")
    end = prompt.index("\n\n", start)
    prompt = prompt[:start] + guidance + prompt[end:]
    prompt += "\n\nSelected account-dossier skill (complete body):\n" + skill
    prompt += (
        "\n\nISOLATED TRIAL: research acquisitions, source reads and /scratch/ notes only. "
        "Use finish_research for the report. No nominations, person-depth, enrichment of people, "
        "specialists, claims, page synthesis or production finalization tools are installed. "
        "Media can be explored through searches and page reads; native transcription is not "
        "installed in this account trial. Record that limitation honestly.\n"
    )
    if claim_ready:
        from live_account_dossier import prepare_format

        prompt = prepare_format(out, prompt)
    (out / "account-system-prompt.md").write_text(prompt)
    skill_path = out / "inputs/.deepagent/skills/account-dossier/v2/SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(skill)
    (out / "instructions").mkdir()
    (out / "instructions/discovery-instructions.md").write_text(guidance)
    if refinement:
        (out / "instructions/source-follow-through.md").write_text(refinement)
    (out / "instructions/account-dossier.original.md").write_text(skill_original)
    (out / "instructions/account-system.original.md").write_text(prompt_original)
    for name in ("exa-system.md", "request-config.json"):
        shutil.copyfile(
            CATALOG / "provider-requests/account-deep/v1" / name, out / "instructions" / name
        )
    (out / "inputs/scratch").mkdir()
    runner_hashes = {}
    runners = (
        (
            *RUNNERS,
            "scripts/live_account_dossier.py",
            "scripts/account_dossier_trial.py",
            "scripts/trial_account_claims.py",
        )
        if claim_ready
        else RUNNERS
    )
    for name in runners:
        dest = out / "runner-snapshot" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
        runner_hashes[name] = digest(dest)
    hashes = {
        str(p.relative_to(out)): digest(p)
        for base in (out / "inputs", out / "instructions")
        for p in base.rglob("*")
        if p.is_file()
    }
    hashes["account-system-prompt.md"] = digest(out / "account-system-prompt.md")
    save(
        out / "trial-manifest.json",
        {
            "strategy": "account-discovery-first",
            "refinement": selected_refinement,
            "claim_ready": claim_ready,
            "source_snapshot": str(source),
            "copied_original_inputs": selected,
            "prepared_hashes": hashes,
            "runner_hashes": runner_hashes,
            "head_brief": "retained approved generation; not regenerated",
            "limitations": [
                "Historical seller/project snapshot; sparse persona body",
                "Not a production fleet job or controlled causal A/B comparison",
                "No native transcription, claims, person jobs or application writes",
            ],
        },
    )


def verify(out: Path):
    manifest = json.loads((out / "trial-manifest.json").read_text())
    for name, sha in manifest["prepared_hashes"].items():
        if digest(inside(out, name)) != sha:
            raise ValueError(f"Prepared input changed: {name}")
    for name, sha in manifest["runner_hashes"].items():
        if digest(ROOT / name) != sha:
            raise ValueError(f"Runner changed: {name}; prepare a fresh trial")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--refined", action="store_true")
    parser.add_argument("--claim-ready", action="store_true")
    parser.add_argument(
        "--refinement", choices=("source-follow-through-v1", "source-follow-through-v2")
    )
    args = parser.parse_args()
    prepare(
        args.context.resolve(),
        args.output.resolve(),
        refined=args.refined,
        refinement=args.refinement,
        claim_ready=args.claim_ready,
    )
    print("Prepared account discovery trial; no external calls.")
