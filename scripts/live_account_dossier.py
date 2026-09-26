"""File-format adapter for fresh account discovery, plus isolated source admission.

The live researcher owns acquisition and dossier formation in one execution.
No previous target research is supplied. Claim persistence remains a separate
mechanical invocation after the dossier is frozen.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from account_dossier_trial import DRAFT, Entry, import_dossier, inspect_dossier, render_dossier
from research_preview_support import save


def prepare_skill(out):
    """Share the JSON formation contract between fresh acquisition and saved replay."""
    guide = (
        (DRAFT / "SKILL.md")
        .read_text()
        .replace("/outputs/", "/scratch/")
        .replace("/work/", "/scratch/")
    )
    guide = guide.replace("/skills/", "/.deepagent/skills/")
    start_format = guide.index("## Format:")
    end_format = guide.index("## Meaningful units:")
    fields = guide[guide.index("```json", start_format) : end_format]
    guide = (
        guide[:start_format]
        + """## Format: structured sections and findings

Call save_dossier_section(section, findings) with a section heading and a list of
finding objects. The tool saves /scratch/account-dossier.json. It replaces the
complete named section on revision and preserves other sections. Write sections
incrementally. Read the saved JSON before revising a section so you retain its
existing findings. Do not manually serialize or edit that file.

The canonical shape is {"sections":[{"section":"Heading","findings":[...]}]}.
The tool accepts the following finding fields. Markdown and import records are
rendered mechanically from these objects; no second authored report is needed.

"""
        + fields
        + guide[end_format:]
    )
    guide = guide.replace("The containing heading becomes", "The containing section becomes")
    guide = guide.replace(
        "issues in the same file.", "issues by resubmitting the complete affected section."
    )
    path = out / "inputs/.deepagent/skills/claim-ready-account-dossier/SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(guide)


def prepare_format(out, prompt):
    # Remove unavailable production responsibilities rather than append contradictory guidance.
    start = prompt.index("Select committee candidates through either web research")
    end = prompt.index("Selected account-dossier skill (complete body):", start)
    prompt = prompt[:start] + prompt[end:]
    prompt = prompt.split("ISOLATED TRIAL:")[0]
    prepare_skill(out)
    addition = """

FRESH RESEARCH AND CLAIM-READY DOSSIER
Conduct the fresh investigation yourself: preliminary multi-angle searches, original
page/job reads, an informed Exa deep assignment, review of its dossier AND returned
sources, then targeted follow-ups. No previous target dossier or research results
are supplied. Keep the broad company investigation and relevant public voices.

You also own formation of the final dossier. There is no later model selecting or
rewriting its entries before storage. Missing findings, altered statements and
bundled independent facts will carry directly into downstream claims. Read
/.deepagent/skills/claim-ready-account-dossier/SKILL.md and apply its granularity,
public-statement fidelity, section-wise coverage and separation of interpretation.
Its formation rules apply to the material YOU acquire during this investigation.

Apply the skill's selection rules before saving: identify the subject and actual
source assertion; keep your inferred consequences, fit and buying roles in optional
interpretation, and unanswered research questions in notes. Qualifying a hypothesis
does not turn it into a fact. Preserve partial evidence with its uncertainty. Write
each finding once, adding complementary sources rather than duplicate fit summaries.
Separate independent events and speakers. Ambiguous role text does not establish a
conflict; compare subject, attribute, scope and time. Read actual entries before
linking their IDs. Review sources for omitted substance and entries for unsupported
additions. Repair validation errors without weakening a judgment simply to pass;
only source evidence justifies reassessment. Document unresolved limitations.

Apply the skill's worked examples: your coverage assessments and open questions go
in notes, sourced assertions in findings, and your inferences in interpretation.
Calling something a note inside a finding does not prevent storage as a claim.
Preserve each speaker's meaningful wording, context, negation and qualifications.
Check the actual saved destinations before finishing, not just your self-review.

Use save_dossier_section to save structured JSON sections containing individual
findings, using that skill's fields and stable F-identifiers. Keep relevant
public wording, attribution, dates and source references. Use paths actually returned
by the acquisition tools. Do not instruct Exa to generate this storage format;
Exa remains an evidence researcher and you form the final dossier yourself.
Write coverage and unresolved interpretation notes separately under /scratch/.
Use validate_dossier for format/reference feedback and finish_dossier to freeze
the file. These replace finish_research in this trial. Do not rewrite meaning or
change a factual judgment simply to repair syntax or reference ordering.

Only acquisition, reading and /scratch/ writes are installed. No person research,
contact enrichment, claim specialist, narrative specialist, direct claim writes,
fleet jobs or publication. Native media transcription is not installed; discover
and read accessible media text and record unresolved recordings honestly.
"""
    (out / "dossier-formation.live.md").write_text(addition)
    return prompt + addition


def prepare_replay(source, out):
    """Replay formation only, retaining original evidence and excluding prior review/notes."""
    from trial_account_discovery import ROOT, RUNNERS, digest

    if out.exists():
        raise ValueError("Use a fresh replay directory")
    rows = json.loads((source / "source-manifest.json").read_text())
    for row in rows:
        body = source / "source-bodies" / (row["source_id"] + ".txt")
        if digest(body) != row["body_sha256"]:
            raise ValueError("Saved source body changed")
    for name in ("evidence", "research", "documents", "project"):
        if (source / "inputs" / name).exists():
            shutil.copytree(source / "inputs" / name, out / "inputs" / name)
    shutil.copyfile(source / "inputs/delegation-brief.md", out / "inputs/delegation-brief.md")
    shutil.copytree(source / "source-bodies", out / "source-bodies")
    shutil.copyfile(source / "source-manifest.json", out / "source-manifest.json")
    shutil.copyfile(source / "dossier.json", out / "inputs/research/prior-dossier.json")
    save(out / "inputs/research/capabilities/0.json", {"operations": {}})
    (out / "inputs/scratch").mkdir()
    prepare_skill(out)
    system = (DRAFT / "SYSTEM.md").read_text()
    start = system.index("Retain the dossier's meaningful section headings.")
    end = system.index("Public statements deserve deliberate attention.", start)
    system = (
        system[:start]
        + (
            "Use save_dossier_section(section, findings) for structured JSON following the skill. "
            "One finding is an independently assessable observation or reported statement. "
            "Separate independent events and speakers; preserve coherent workflows and quotes.\n\n"
        )
        + system[end:]
    )
    system = system.replace("/skills/", "/.deepagent/skills/").replace("/work/", "/scratch/")
    system = system.replace(
        "Write the dossier incrementally at /outputs/account-dossier.entries.md.",
        "Write incrementally with save_dossier_section; it saves /scratch/account-dossier.json.",
    )
    system += (
        "\nThe saved draft dossier is a coverage aid, not independent evidence. Reassess "
        "its entries against original sources; do not inherit its classifications or IDs "
        "without review. No acquisition tools are installed.\n"
    )
    (out / "account-system-prompt.md").write_text(system)
    task = (
        "Use /delegation-brief.md, /research/context.json and its pinned documents for "
        "context. Read /research/prior-dossier.json alongside /evidence/index.json and "
        "its continuations. Re-author the account findings from this saved investigation "
        "using the revised claim-ready-account-dossier skill. Inspect original sources "
        "for omissions and correct unsupported additions; preserve useful wording and "
        "uncertainty. Do not target a record count. Use save_dossier_section, "
        "validate_dossier and finish_dossier. Keep coverage/review notes in /scratch/. "
        "This is saved-evidence formation, not a fresh investigation or the original "
        "agent conversation. No purchases, person jobs, publication or new research."
    )
    (out / "task-prompt.md").write_text(task)
    save(
        out / "inputs/trial-manifest.json",
        {
            "dossier": "/research/prior-dossier.json",
            "sources": "/evidence/index.json",
            "context": "/research/context.json",
            "source_count": len(rows),
            "dossier_output": "/scratch/account-dossier.json",
            "acquisition_enabled": False,
        },
    )
    runners = (
        *RUNNERS,
        "scripts/live_account_dossier.py",
        "scripts/account_dossier_trial.py",
        "scripts/trial_account_claims.py",
    )
    for name in runners:
        dest = out / "runner-snapshot" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    files = [
        p
        for base in (out / "inputs", out / "source-bodies")
        for p in base.rglob("*")
        if p.is_file()
    ]
    files.extend(
        out / name
        for name in ("account-system-prompt.md", "task-prompt.md", "source-manifest.json")
    )
    save(
        out / "trial-manifest.json",
        {
            "claim_ready": True,
            "replay_saved_research": True,
            "source_snapshot": str(source),
            "prepared_hashes": {str(p.relative_to(out)): digest(p) for p in files},
            "runner_hashes": {name: digest(ROOT / name) for name in runners},
        },
    )


def source_aliases(inputs, rows):
    return {
        "/" + str(path.relative_to(inputs)): {
            "source_id": row["source_id"],
            "url": row.get("source_url"),
            "kind": row["kind"],
            "locator": row["origin_locator"],
        }
        for row in rows
        for path in [
            inputs / row["path"].lstrip("/"),
            *(inputs / "evidence" / row["source_id"]).glob("*.json"),
        ]
    }


def inspect_live(out, rows):
    path = out / "inputs/scratch/account-dossier.json"
    if not path.exists():
        return [], [{"error": "Use save_dossier_section first"}]
    return inspect_dossier(
        record_lines(json.loads(path.read_text())), source_aliases(out / "inputs", rows)
    )


def record_lines(document):
    """Lossless derived representation for the existing importer, never authored twice."""
    parts = ["# Account dossier"]
    for section in document["sections"]:
        parts.append("## " + section["section"])
        parts.extend(json.dumps(f, ensure_ascii=False) for f in section["findings"])
    return "\n".join(parts) + "\n"


def save_section(out, rows, section, findings):
    if (out / "agent-completion.json").exists():
        return {"saved": False, "error": "Dossier frozen"}
    try:
        if not section.strip() or "\n" in section or "\r" in section:
            raise ValueError("Use a nonempty single-line section heading")
        sources = source_aliases(out / "inputs", rows)
        entries = [Entry.model_validate(f) for f in findings]
        for entry in entries:
            unknown = set(entry.source_paths) - sources.keys()
            if unknown:
                raise ValueError(f"Unknown source paths: {sorted(unknown)}")
        path = out / "inputs/scratch/account-dossier.json"
        document = json.loads(path.read_text()) if path.exists() else {"sections": []}
        others = [s for s in document["sections"] if s["section"] != section]
        ids = [f["id"] for s in others for f in s["findings"]] + [e.id for e in entries]
        if len(ids) != len(set(ids)):
            raise ValueError("Finding identifiers must be unique across sections")
        replacement = {"section": section, "findings": findings}
        document["sections"] = [
            replacement if s["section"] == section else s for s in document["sections"]
        ]
        if len(others) == len(document["sections"]):
            document["sections"].append(replacement)
        save(path, document)
        return {
            "saved": True,
            "path": "/scratch/account-dossier.json",
            "section": section,
            "entries": len(findings),
        }
    except ValueError as exc:
        return {"saved": False, "error": str(exc)}


def finish_live(out, rows, summary, gaps):
    if (out / "agent-completion.json").exists():
        return {"finished": True, "instruction": "Already frozen; return final summary."}
    records, errors = inspect_live(out, rows)
    if errors or not records:
        return {"finished": False, "errors": errors or [{"error": "No finding entries"}]}
    structured = (out / "inputs/scratch/account-dossier.json").read_bytes()
    body = record_lines(json.loads(structured)).encode()
    (out / "dossier.json").write_bytes(structured)
    (out / "dossier.entries.md").write_bytes(body)
    rendered = render_dossier(records, source_aliases(out / "inputs", rows))
    (out / "dossier.readable.md").write_text(rendered)
    (out / "findings.md").write_text(rendered)
    save(out / "source-manifest.json", rows)
    save(
        out / "agent-completion.json",
        {
            "summary": summary,
            "gaps": gaps,
            "entries": len(records),
            "finished_at": datetime.now(UTC).isoformat(),
            "dossier_sha256": hashlib.sha256(body).hexdigest(),
            "structured_dossier_sha256": hashlib.sha256(structured).hexdigest(),
            "claims_written_by_agent": 0,
        },
    )
    return {"finished": True, "entries": len(records), "instruction": "Return your final summary."}


async def admit_and_import(live, run_number):
    """Reuse a fresh isolated clone solely as a persistence fixture, after live research."""
    import trial_account_claims as trial
    from sqlalchemy.ext.asyncio import create_async_engine

    from clue_api.arv2.quality_evidence import grant_manifest, persist_source
    from clue_api.arv2.research_operations import OperationScope
    from clue_storage.fs import FsStorage

    trial.OUT, trial.DB = trial.run_paths(run_number)
    if not (live / "agent-completion.json").exists():
        raise ValueError("Live researcher has not frozen a dossier")
    if not trial.OUT.exists():
        await trial.prepare(dossier_mode=True)
    manifest_path = trial.OUT / "manifest.json"
    m = json.loads(manifest_path.read_text())
    if m["database"] != trial.DB or trial.DB == trial.SOURCE_DB:
        raise ValueError("Not an isolated trial database")
    if (trial.OUT / "started.json").exists():
        raise ValueError("Do not reuse a model-generation trial for fresh-source import")
    if m.get("live_source") and m["live_source"] != str(live):
        raise ValueError("Another live investigation already bound to this import")
    _, url = trial.db_config()
    engine, storage = create_async_engine(url), FsStorage(trial.OUT / "blobs")
    try:
        rows = json.loads((live / "source-manifest.json").read_text())
        scope = trial.scope_from(m)
        target = json.loads((live / "inputs/research/context.json").read_text())["target"]
        if target["domain"] != scope.account_domain:
            raise ValueError("Live target differs from the isolated persistence fixture")
        op = OperationScope(scope.workspace_id, scope.run_id, scope.job_id, scope.account_id)
        sources = []
        async with engine.begin() as conn:
            for row in rows:
                body = (live / "source-bodies" / (row["source_id"] + ".txt")).read_text()
                if hashlib.sha256(body.encode()).hexdigest() != row["body_sha256"]:
                    raise ValueError("Fresh source body changed")
                ref = await persist_source(
                    conn,
                    storage,
                    op,
                    kind=row["kind"],
                    body=body,
                    original_key=None,
                    source_url=row.get("source_url"),
                    origin_locator=f"live-trial:{live.name}:{row['source_id']}:{row['origin_locator']}",
                    observed_at=datetime.fromisoformat(row["observed_at"]),
                    metadata=row.get("metadata", {}),
                )
                for path in [
                    live / "inputs" / row["path"].lstrip("/"),
                    *(live / "inputs/evidence" / row["source_id"]).glob("*.json"),
                ]:
                    sources.append(
                        {
                            "path": "/" + str(path.relative_to(live / "inputs")),
                            "source_id": str(ref.source_id),
                            "url": row.get("source_url"),
                            "kind": row["kind"],
                            "locator": row["origin_locator"],
                        }
                    )
            grant = await grant_manifest(conn, op, consumer_id=UUID(m["trial_id"]))
        m.update(
            sources=sources,
            grant_id=str(grant.grant_id),
            live_source=str(live),
            trial_mode="claim-ready-dossier",
            model_generation_used_old_sources=False,
        )
        save(manifest_path, m)
        for name in ["dossier.entries.md", "agent-completion.json"]:
            (trial.OUT / name).write_bytes((live / name).read_bytes())
        writer = trial.Writer(m, engine, storage)
        result = await import_dossier(writer, trial.OUT)
        save(
            live / "claim-import-location.json",
            {
                "folder": str(trial.OUT),
                "database": trial.DB,
                "stored": result["stored"],
                "errors": result["errors"],
            },
        )
        print(
            json.dumps(
                {"stored": result["stored"], "errors": result["errors"], "out": str(trial.OUT)}
            )
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", type=Path, required=True)
    parser.add_argument("--import-run", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(admit_and_import(args.live.resolve(), args.import_run))
