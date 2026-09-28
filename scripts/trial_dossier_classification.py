"""Isolated classified-dossier replay. No production schema or claim-store writes."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from account_dossier_trial import render_dossier
from live_account_dossier import dossier_workspace_path, prepare_replay, source_aliases
from pydantic import BaseModel, ConfigDict, JsonValue
from research_preview_support import save
from trial_account_discovery import ROOT, digest

from clue_api.arv2.dossier_json import Entry, parse_json_dossier, replace_section
from clue_research.claimstore.registry import validate_value_against_schema

DRAFT = ROOT / "docs/superpowers/drafts/2026-09-26-dossier-classification"
CATEGORIES = {
    "identity": "Company identity, legal form, domain and identifiers.",
    "geography": "Locations and geographic operations.",
    "offering": "Products, services, capabilities and product positioning.",
    "business_model": "How the target earns money, packaging and routes to market.",
    "scale": "Size, employee counts and organizational footprint.",
    "funding": "Financing rounds, investors and cumulative funding.",
    "financial_performance": "Reported revenue, growth and operating performance; not funding.",
    "hiring": "Recruitment, open roles and candidate requirements.",
    "organization": "Named teams, leaders, structure and explicit reporting relationships.",
    "responsibilities": "Explicit remit and ownership; not inferred from title alone.",
    "workflows": "Described processes, actors, sequence and handoffs.",
    "technology": "Named systems/tools with usage, requirement or mention scope preserved.",
    "operational_needs": "Source-stated needs, constraints or problems; not seller hypotheses.",
    "strategic_priorities": "Expressed direction, objectives and priorities.",
    "initiatives": "Concrete programs, launches or actions.",
    "public_statements": (
        "Substantive attributed words or views, not routine public profile metadata."
    ),
    "events_media": "Conferences, appearances, interviews, podcasts and authored media.",
    "culture": "Stated working values, employee experience or culture.",
    "risks": "Source-reported adverse developments and risks; no inferred purchase verdict.",
    "customer_proof": "Attributed customer outcomes, cases or references; not target operations.",
    "partnerships": "Announced collaborations, alliances and ecosystem relationships.",
    "career": "Person employment and career history.",
    "education": "Person education and credentials.",
    "personal_projects": "Individual projects distinct from employer initiatives.",
    "interests_contributions": "Self-disclosed interests, recommendations and contributions.",
}


class Projection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: JsonValue


class Classification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_key: str
    field_version: int | None
    projection: Projection | None
    categories: list[str]
    reason: str | None = None


class ClassifiedEntry(Entry):
    classification: Classification


def base_document(document):
    result = copy.deepcopy(document)
    for s in result["sections"]:
        for f in s["findings"]:
            f.pop("classification", None)
    return result


def check_classification(finding, catalog, subject="accounts"):
    entry = ClassifiedEntry.model_validate(finding)
    c = entry.classification
    unknown = set(c.categories) - CATEGORIES.keys()
    if unknown:
        raise ValueError(f"{entry.id}: unknown categories {sorted(unknown)}")
    if len(c.categories) != len(set(c.categories)):
        raise ValueError(f"{entry.id}: repeated category")
    fallback = "contact.research_finding" if subject == "contacts" else "account.research_finding"
    if c.field_key == fallback:
        if c.field_version is not None or c.projection is not None:
            raise ValueError(
                "Generic fallback uses null field_version and projection; full finding is retained."
            )
        return entry
    match = next(
        (
            r
            for r in catalog
            if r["entity"] == subject
            and r["field_key"] == c.field_key
            and r["version"] == c.field_version
        ),
        None,
    )
    if match is None:
        raise ValueError(f"{entry.id}: field/version not in supplied subject catalog")
    if c.projection is None:
        raise ValueError(
            f"{entry.id}: specific field requires projection.value; use fallback if unsupported"
        )
    validate_value_against_schema(c.projection.value, match["value_schema"])
    return entry


def catalog_for(out):
    return json.loads((out / "inputs/research/field-catalog.json").read_text())["fields"]


def save_section(out, rows, section, findings):
    if (out / "agent-completion.json").exists():
        return {"saved": False, "error": "Dossier frozen"}
    try:
        catalog = catalog_for(out)
        for f in findings:
            check_classification(f, catalog)
        path = out / "inputs" / dossier_workspace_path(out).lstrip("/")
        document = json.loads(path.read_text()) if path.exists() else {"sections": []}
        # Shared base contract validates references/IDs without discarding classification.
        replace_section(
            base_document(document),
            section,
            [{k: v for k, v in f.items() if k != "classification"} for f in findings],
            set(source_aliases(out / "inputs", rows)),
        )
        replacement = {"section": section, "findings": findings}
        exists = any(s["section"] == section for s in document["sections"])
        document["sections"] = [
            replacement if s["section"] == section else s for s in document["sections"]
        ]
        if not exists:
            document["sections"].append(replacement)
        save(path, document)
        return {
            "saved": True,
            "path": dossier_workspace_path(out),
            "section": section,
            "entries": len(findings),
        }
    except (ValueError, KeyError, TypeError) as exc:
        return {"saved": False, "error": str(exc)}


def inspect_live(out, rows):
    path = out / "inputs" / dossier_workspace_path(out).lstrip("/")
    if not path.exists():
        return [], [{"error": "Use save_dossier_section first"}]
    document = json.loads(path.read_text())
    parsed = parse_json_dossier(json.dumps(base_document(document)).encode())
    originals = {f["id"]: f for s in document["sections"] for f in s["findings"]}
    errors = list(parsed.errors)
    catalog = catalog_for(out)
    aliases = source_aliases(out / "inputs", rows)
    records = []
    for i, r in enumerate(parsed.records):
        try:
            original = originals[r.entry.id]
            check_classification(original, catalog)
            unknown = set(r.entry.source_paths) - aliases.keys()
            if unknown:
                raise ValueError(f"Unknown source paths: {sorted(unknown)}")
            records.append(
                {
                    "line": i + 1,
                    "section": r.section,
                    "entry": r.entry,
                    "raw": json.dumps(original, ensure_ascii=False),
                }
            )
        except ValueError as exc:
            errors.append({"id": r.entry.id, "error": str(exc)})
    return records, errors


def finish_live(out, rows, summary, gaps):
    if (out / "agent-completion.json").exists():
        return {"finished": True, "instruction": "Already frozen; return final summary."}
    records, errors = inspect_live(out, rows)
    if errors or not records:
        return {"finished": False, "errors": errors or [{"error": "No entries"}]}
    path = out / "inputs" / dossier_workspace_path(out).lstrip("/")
    body = path.read_bytes()
    (out / "dossier.json").write_bytes(body)
    rendered = render_dossier(
        records, source_aliases(out / "inputs", rows), subject_label="Account"
    )
    (out / "dossier.readable.md").write_text(rendered)
    (out / "findings.md").write_text(rendered)
    entries = [json.loads(r["raw"]) for r in records]
    save(
        out / "classification-summary.json",
        {
            "entries": len(entries),
            "fields": dict(Counter(f["classification"]["field_key"] for f in entries)),
            "categories": dict(
                Counter(c for f in entries for c in f["classification"]["categories"])
            ),
        },
    )
    lines = [
        "# Classification review",
        "",
        "Full findings and source links remain in dossier.readable.md.",
        "",
    ]
    for f in entries:
        c = f["classification"]
        lines += [
            f"## {f['id']} — {f['topic']}",
            "",
            f"Field: `{c['field_key']}` (version {c['field_version']})",
            f"Categories: {', '.join(c['categories'])}",
            "",
            "Typed projection: " + json.dumps(c["projection"], ensure_ascii=False),
            "",
            "Finding: "
            + (
                f["finding"]
                if isinstance(f["finding"], str)
                else json.dumps(f["finding"], ensure_ascii=False)
            ),
            "",
            "Classification reason: " + str(c.get("reason")),
            "",
        ]
    (out / "classification-review.md").write_text("\n".join(lines))
    save(
        out / "agent-completion.json",
        {
            "summary": summary,
            "gaps": gaps,
            "entries": len(records),
            "finished_at": datetime.now(UTC).isoformat(),
            "structured_dossier_sha256": hashlib.sha256(body).hexdigest(),
            "claims_written_by_agent": 0,
        },
    )
    return {"finished": True, "entries": len(records), "instruction": "Return final summary."}


def prepare(source, catalog_source, out):
    prepare_replay(source, out)
    context = json.loads(catalog_source.read_text())
    save(
        out / "inputs/research/field-catalog.json",
        {
            "source": str(catalog_source),
            "source_sha256": digest(catalog_source),
            "kind": "field_definitions_not_evidence",
            "fields": [r for r in context["field_catalog"] if r["entity"] == "accounts"],
            "fallback": {
                "field_key": "account.research_finding",
                "field_version": None,
                "meaning": (
                    "Existing generic finding destination, absent from this retained "
                    "registry snapshot. No typed projection."
                ),
            },
        },
    )
    save(out / "inputs/research/categories.json", {"version": "trial-v1", "categories": CATEGORIES})
    dest = out / "inputs/.deepagent/skills/dossier-field-classification/SKILL.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DRAFT / "SKILL.md", dest)
    save(out / "inputs/research/classified-entry-schema.json", ClassifiedEntry.model_json_schema())
    addition = """

CLASSIFIED DOSSIER TRIAL
Read the COMPLETE /.deepagent/skills/claim-ready-account-dossier/SKILL.md and
/.deepagent/skills/dossier-field-classification/SKILL.md. This supplement adds field
classification to the full dossier, not a separate or abbreviated report. Read
/research/field-catalog.json and /research/categories.json. These are definitions,
not evidence. The catalog is a retained workspace snapshot, not a new global registry.

Every finding must retain all its existing fields and add this classification object:
{"field_key":"core.employee_count","field_version":1,"projection":{"value":167},
 "categories":["scale"],"reason":null}
That is a fictional format example, never target evidence. Supply matching typed values
without changing finding text or duplicating it. Use field meaning and value_schema.
For generic findings use {"field_key":"account.research_finding","field_version":null,
"projection":null,"categories":[...],"reason":"brief reason no narrower field fits"}.
The generic field is the current production fallback but absent in the retained catalog;
no registry version is fabricated here. Null projection means no typed projection;
{"value":null} is instead an explicit null value and must satisfy a field's schema.
Full transport schema: /research/classified-entry-schema.json. Category lists may be
empty if none fits: retain the finding and explain the gap in notes. Do not force tags.

This is an ACCOUNT dossier. Preserve relevant attributed professional statements about
the company under account fields, not contact fields; do not repurpose titles as buying
roles. Derived scoring, fit, committee assessments, narratives and research-process
fields in the catalog are not factual destinations for your interpretations or gaps.
Keep those in their already specified places. Narrow fields do not justify suppressing
rich wording. Classify from the source assertion, not a field-name keyword match.
Review the actual saved dossier against BOTH skills and correct meaningful defects.
The trial tools check syntax, field/version, typed value shape and references, not
semantic truth. finish_dossier saves local JSON and review artifacts only, no import.
No registry changes, providers, fleet, person jobs, database writes or page synthesis.
"""
    with (out / "account-system-prompt.md").open("a") as f:
        f.write(addition)
    with (out / "task-prompt.md").open("a") as f:
        f.write(
            "\nApply the classified dossier trial contract to every entry. "
            "Read the classification supplement and field/category definitions before saving. "
            "Produce the full account dossier, retaining source detail.\n"
        )
    manifest = json.loads((out / "trial-manifest.json").read_text())
    manifest["classification_trial"] = True
    manifest["classification_catalog_source"] = str(catalog_source)
    name = "scripts/trial_dossier_classification.py"
    target = out / "runner-snapshot" / name
    shutil.copyfile(ROOT / name, target)
    manifest["runner_hashes"][name] = digest(ROOT / name)
    # Refresh hashes only during explicit preparation, never at execution.
    for base in (out / "inputs", out / "source-bodies"):
        for p in base.rglob("*"):
            if p.is_file():
                manifest["prepared_hashes"][str(p.relative_to(out))] = digest(p)
    for name in ("account-system-prompt.md", "task-prompt.md"):
        manifest["prepared_hashes"][name] = digest(out / name)
    save(out / "trial-manifest.json", manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--catalog-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.source.resolve(), args.catalog_source.resolve(), args.output.resolve())
    print("Prepared classification replay; no paid calls or database writes.")
