"""Prepare a saved-person JSON formation replay; no providers or DB writes in prepare.

Reuse the established Deep Agent replay runner and section tools. Source pages are
reassembled from their exact saved text segments, with continuity checks, never
summarized into replacement evidence. Historical comparison reports are excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from live_account_dossier import DRAFT, prepare_skill
from research_preview_support import save

from clue_api.arv2.evidence_paths import source_path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reconstruct_source(inputs, source_id):
    pages = sorted((inputs / "evidence" / source_id).glob("*.json"), key=lambda p: int(p.stem))
    if not pages:
        raise ValueError(f"Missing retained source: {source_id}")
    chunks, offset, total = [], 0, None
    for page in pages:
        item = json.loads(page.read_text())
        if item["start"] != offset or total not in (None, item["total_chars"]):
            raise ValueError(f"Discontinuous source pages: {source_id}")
        total = item["total_chars"]
        for segment in item["text_segments"]:
            if segment["start"] != offset:
                raise ValueError(f"Discontinuous source segments: {source_id}")
            chunks.append(segment["text"])
            offset += len(segment["text"])
    if offset != total:
        raise ValueError(f"Incomplete retained source: {source_id}")
    return "".join(chunks)


def prepare(source, out):
    if out.exists():
        raise ValueError("Choose a fresh person dossier replay folder")
    inputs = out / "inputs"
    original = source / "inputs"
    for name in ("research", "documents", "project", "products"):
        if (original / name).exists():
            shutil.copytree(original / name, inputs / name)
    for name in ("person-brief.md", "account-findings.md", "delegation-brief.md"):
        dest = inputs / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original / name, dest)
    shutil.copyfile(source / "findings.md", inputs / "research/prior-person-dossier.md")
    (inputs / "scratch").mkdir()
    save(inputs / "research/capabilities/0.json", {"operations": {}})
    # Historical claims and acquisition directives are not formation inputs.
    for name in ("claims", "acquisition.json"):
        path = inputs / "research" / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    rows = []
    originals = [
        r
        for page in sorted((original / "evidence/index").glob("*.json"), key=lambda p: int(p.stem))
        for r in json.loads(page.read_text())["sources"]
    ]
    if len({r["source_id"] for r in originals}) != len(originals):
        raise ValueError("Duplicate saved source IDs; inspect inventory before preparing")
    ctx = json.loads((inputs / "research/context.json").read_text())
    for revision, source_row in enumerate(originals, 1):
        row = dict(source_row)
        body = reconstruct_source(original, row["source_id"])
        row.update(
            revision=revision,
            body_sha256=hashlib.sha256(body.encode()).hexdigest(),
            observed_at=ctx["run_date"] + "T00:00:00+00:00",
        )
        row["path"] = source_path(row)
        body_path = out / "source-bodies" / (row["source_id"] + ".txt")
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_text(body)
        readable = inputs / row["path"].lstrip("/")
        readable.parent.mkdir(parents=True, exist_ok=True)
        readable.write_text(f"Source URL: {row.get('source_url')}\nKind: {row['kind']}\n\n{body}")
        rows.append(row)
    save(inputs / "evidence/index.json", {"sources": rows})
    save(out / "source-manifest.json", rows)
    save(out / "trial-manifest.json", {"subject_kind": "person"})
    prepare_skill(out)
    skill_path = inputs / ".deepagent/skills/claim-ready-account-dossier/SKILL.md"
    skill = skill_path.read_text().replace(
        "claim-ready-account-dossier", "claim-ready-person-dossier"
    )
    skill = skill.replace("sectioned account dossier", "sectioned person dossier")
    skill = skill.replace("meaningful account observation", "meaningful person observation")
    skill = skill.replace("/scratch/account-dossier.json", "/scratch/person-dossier.json")
    skill = skill.replace(
        "A person's statement about the target's operations belongs here with attribution.\n"
        "Unrelated personal biography belongs in coverage notes for this account-only task.",
        "Preserve the selected person's public professional and personal biography with "
        "attribution. Do not exclude outside-work findings simply for lacking seller relevance.",
    )
    guide = (DRAFT / "PERSON.md").read_text()
    start, end = (
        skill.index("## Section-wise formation guide"),
        skill.index("## Finish with a reviewable handoff"),
    )
    skill = (
        skill[:start]
        + guide[guide.index("## Person-specific section guide") :]
        + "\n\n"
        + skill[end:]
    )
    dest = inputs / ".deepagent/skills/claim-ready-person-dossier/SKILL.md"
    dest.parent.mkdir(parents=True)
    dest.write_text(skill)
    skill_path.unlink()
    skill_path.parent.rmdir()
    system = guide[: guide.index("## Person-specific section guide")]
    system += "\nRead /.deepagent/skills/claim-ready-person-dossier/SKILL.md in full.\n"
    (out / "account-system-prompt.md").write_text(system)
    (out / "person-system-prompt.md").write_text(system)
    person = ctx["person_assignment"]
    task = (
        f"Prepare the saved person investigation for {person['name']} "
        f"({person['linkedin_url']}) as claim-ready JSON. Read /person-brief.md, "
        "/research/context.json and its referenced documents. Read "
        "/research/prior-person-dossier.md alongside /evidence/index.json and originals. "
        "Use /account-findings.md as context, not as proof of personal responsibilities. "
        "Cover the saved research's meaningful findings, including public voice, career "
        "and outside-work material. Read the full person formation skill, write sections "
        "incrementally, review and correct them against its rules, then finish_dossier. "
        "No acquisition, enrichment, publication, database tools or delegation are installed."
    )
    (out / "task-prompt.md").write_text(task)
    runners = [
        "scripts/trial_person_dossier.py",
        "scripts/live_account_dossier.py",
        "scripts/preview_live_account_research.py",
        "scripts/research_preview_support.py",
        "scripts/continue_person_research.py",
        "scripts/account_dossier_trial.py",
        "platform/api/clue_api/arv2/dossier_json.py",
        "platform/api/clue_api/arv2/dossier_findings.py",
    ]
    for name in runners:
        target = out / "runner-snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    files = [p for base in (inputs, out / "source-bodies") for p in base.rglob("*") if p.is_file()]
    files += [
        out / name
        for name in ("account-system-prompt.md", "task-prompt.md", "source-manifest.json")
    ]
    save(
        out / "trial-manifest.json",
        {
            "claim_ready": True,
            "replay_saved_research": True,
            "subject_kind": "person",
            "source_snapshot": str(source),
            "source_dossier_sha256": digest(source / "findings.md"),
            "prepared_hashes": {str(p.relative_to(out)): digest(p) for p in files},
            "runner_hashes": {name: digest(ROOT / name) for name in runners},
            "source_count": len(rows),
            "acquisition_enabled": False,
            "limitations": [
                "Saved-research formation, not original researcher conversation",
                "Retained person trial includes account context sources",
                "No new research or transcription; existing media gaps remain",
            ],
        },
    )
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.source.resolve(), args.out.resolve()))
