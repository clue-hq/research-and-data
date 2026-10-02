"""Sectioned record parser and mechanical importer for the isolated dossier trial.

No model calls or research acquisition. All mutations reuse the trial's shared
claim-store writer. Original record bytes and per-line failures remain inspectable.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from trial_account_claims import save

from clue_api.arv2.dossier_json import Entry, EntryReview  # noqa: F401

DRAFT = (
    Path(__file__).resolve().parents[1] / "docs/superpowers/drafts/2026-09-26-claim-ready-dossier"
)
DOSSIER = "outputs/account-dossier.entries.md"


def parse_dossier(body, sources):
    records, errors = [], []
    section = None
    for line, raw in enumerate(body.splitlines(), 1):
        if not raw.strip():
            continue
        if raw.startswith("# "):
            section = None
            continue
        if raw.startswith("## "):
            section = raw[3:].strip()
            continue
        try:
            if not section:
                raise ValueError("Place the finding under a ## section heading")
            entry = Entry.model_validate_json(raw)
            unknown = set(entry.source_paths) - set(sources)
            if unknown:
                raise ValueError(f"Unknown source paths: {sorted(unknown)}")
            records.append({"line": line, "section": section, "entry": entry, "raw": raw})
        except ValueError as exc:
            errors.append({"line": line, "error": str(exc)})
    counts = Counter(r["entry"].id for r in records)
    entries = {r["entry"].id: r["entry"] for r in records}
    valid = []
    for record in records:
        entry = record["entry"]
        reason = None
        if counts[entry.id] > 1:
            reason = "Duplicate finding identifier; neither occurrence is silently selected"
        elif entry.id in entry.dependencies():
            reason = "A finding cannot reference itself"
        elif entry.dependencies() - entries.keys():
            reason = f"Missing finding references: {sorted(entry.dependencies() - entries.keys())}"
        elif (
            entry.review.duplicate_of
            and entries[entry.review.duplicate_of].review.status == "duplicate"
        ):
            reason = "duplicate_of must point to a canonical nonduplicate finding"
        if reason:
            errors.append({"line": record["line"], "id": entry.id, "error": reason})
        else:
            valid.append(record)
    return valid, errors


def ordered_records(records):
    pending = list(records)
    available, ordered = set(), []
    while pending:
        ready = [r for r in pending if r["entry"].dependencies() <= available]
        if not ready:
            break
        for record in ready:
            ordered.append(record)
            available.add(record["entry"].id)
            pending.remove(record)
    errors = [
        {
            "line": r["line"],
            "id": r["entry"].id,
            "error": "Unresolved dependency or cyclic reference; retain and repair explicitly",
        }
        for r in pending
    ]
    return ordered, errors


def inspect_dossier(body, sources):
    records, errors = parse_dossier(body, sources)
    ordered, dependency_errors = ordered_records(records)
    return ordered, errors + dependency_errors


def render_dossier(records, sources, *, subject_label="Account"):
    lines = [
        f"# {subject_label} dossier — readable record view",
        "",
        "Rendered mechanically from the agent's entries; no second model or summary.",
        "",
    ]
    last = None
    for record in sorted(records, key=lambda r: r["line"]):
        e = record["entry"]
        if record["section"] != last:
            last = record["section"]
            lines.extend([f"## {last}", ""])
        lines.extend(
            [
                f"### {e.id} · {e.topic}",
                "",
                f"{e.claim_type} · **{e.review.status}**",
                "",
                e.finding
                if isinstance(e.finding, str)
                else json.dumps(e.finding, indent=2, ensure_ascii=False),
                "",
                f"Attribution: {e.attribution}",
                f"Time: {e.time_context}",
                f"Review: {e.review.reason}",
                f"Qualifications: {json.dumps(e.qualifications, ensure_ascii=False)}",
            ]
        )
        if e.review.duplicate_of:
            lines.append(f"Duplicate of: {e.review.duplicate_of}")
        if e.review.conflicts_with:
            lines.append(f"Potential conflict with: {', '.join(e.review.conflicts_with)}")
        if e.review.expected_entity:
            lines.append(
                f"Expected entity: {json.dumps(e.review.expected_entity, ensure_ascii=False)}"
            )
        if e.agent_interpretation:
            lines.append(f"Agent interpretation (not evidence): {e.agent_interpretation}")
        for path in e.source_paths:
            url = sources[path].get("url")
            lines.append(f"- [{path}]({url})" if url else f"- `{path}` (retained material)")
        lines.append("")
    return "\n".join(lines)


async def import_dossier(writer, out):
    """Import each parseable independent entry, preserving errors and exact text."""
    frozen = out / "dossier.entries.md"
    body = frozen.read_text()
    digest = hashlib.sha256(frozen.read_bytes()).hexdigest()
    completion = out / "agent-completion.json"
    if completion.exists() and json.loads(completion.read_text()).get("dossier_sha256") != digest:
        raise ValueError(
            "Frozen dossier differs from the generation receipt; refuse silent mutation"
        )
    records, errors = inspect_dossier(body, writer.sources)
    receipt = {"dossier_sha256": digest, "entries": [], "errors": errors}
    mapping = {}
    async with writer.lock:
        async with writer.engine.begin() as conn:
            prior = {
                r["value_json"]["dossier_entry"]["id"]: r
                for r in await writer.rows(conn)
                if "dossier_entry" in r["value_json"]
            }
        for record in records:
            e = record["entry"]
            origin = {
                "id": e.id,
                "section": record["section"],
                "dossier_sha256": digest,
                "entry_sha256": hashlib.sha256(record["raw"].encode()).hexdigest(),
            }
            try:
                args = e.as_finding(mapping)
                if e.id in prior and prior[e.id]["value_json"]["dossier_entry"] != origin:
                    raise ValueError(
                        "Finding already imported from different content; no implicit correction"
                    )
                async with writer.engine.begin() as conn:
                    result = await writer.write(conn, args, dossier_entry=origin)
                mapping[e.id] = str(result["claim_id"])
                receipt["entries"].append(
                    {"id": e.id, "line": record["line"], "section": record["section"], **result}
                )
            except Exception as exc:
                receipt["errors"].append({"id": e.id, "line": record["line"], "error": str(exc)})
            save(out / "import-receipt.json", receipt)
        save(out / "import-receipt.json", receipt)
        rows = await writer.export()
    by_id = {str(r["id"]): r for r in rows}
    checks = []
    for record in records:
        e = record["entry"]
        if e.id not in mapping:
            continue
        value = by_id[mapping[e.id]]["value_json"]
        expected = e.as_finding(mapping).model_dump(mode="json", exclude={"source_paths"})
        checks.append(
            {
                "id": e.id,
                "claim_id": mapping[e.id],
                "content_and_metadata_equal": all(value[k] == v for k, v in expected.items()),
                "source_ids_equal": {s["source_id"] for s in value["sources"]}
                == {writer.sources[p]["source_id"] for p in e.source_paths},
                "section_equal": value["dossier_entry"]["section"] == record["section"],
            }
        )
    receipt["stored"] = len(mapping)
    receipt["roundtrip_checks"] = checks
    save(out / "import-receipt.json", receipt)
    (out / "dossier.readable.md").write_text(render_dossier(records, writer.sources))
    return receipt


def prepare_instructions(out):
    workspace = out / "workspace"
    old_skill = workspace / "skills/account-claim-writing-trial"
    if old_skill.exists():
        for path in old_skill.iterdir():
            path.unlink()
        old_skill.rmdir()
    target = workspace / "skills/claim-ready-account-dossier/SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((DRAFT / "SKILL.md").read_bytes())
    for src, dest in [("SYSTEM.md", "system-prompt.md"), ("TASK.md", "task-prompt.md")]:
        (out / dest).write_bytes((DRAFT / src).read_bytes())
    path = workspace / "trial-manifest.json"
    manifest = json.loads(path.read_text())
    manifest.update(
        dossier_output="/" + DOSSIER,
        mode="claim-ready-dossier",
        correction_limit="Edit the dossier before finishing; historical claims are unchanged.",
    )
    save(path, manifest)
    save(
        workspace / "capabilities.json",
        {
            "validate_dossier": (
                "Inspect /outputs/account-dossier.entries.md for syntax and reference errors; "
                "no writes or semantic judge."
            ),
            "finish_dossier": (
                "Freeze the final dossier, summary and gaps. "
                "Programmatic claim import runs after the agent finishes."
            ),
            "native_workspace": (
                "Read saved inputs; write and edit /work/ and /outputs/ only. "
                "No shell, new research or direct claim-writing tools."
            ),
        },
    )
