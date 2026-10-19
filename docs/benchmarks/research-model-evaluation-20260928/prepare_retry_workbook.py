"""Prepare verified local run measurements and bounded spreadsheet updates."""

import json
from pathlib import Path
from datetime import datetime
from decimal import Decimal

OUT = Path(__file__).resolve().parent
BASE = OUT.parents[1]
ROOT = BASE / ".artifacts/zafran-muse-xhigh-glm-retry-20260928"
read = lambda p: json.loads(p.read_text())
dt = lambda s: datetime.fromisoformat(s)
day = lambda s: None if s is None else s / 86400
elapsed = lambda a, b: (dt(b) - dt(a)).total_seconds()
trace = "https://us.cloud.langfuse.com/project/cmu2j8vra0137ad0clp5vylx2/traces/"
rows = {
    s: []
    for s in ["Runs", "Costs", "Jobs", "Quality", "Failures", "Outputs", "Trace metrics", "Method"]
}
links = []
normalized = []
checks = []
quality = OUT / "MUSE-XHIGH-QUALITY.md"


def link(sheet, row, col, target):
    if not str(target).startswith("https://"):
        assert Path(target).exists(), target
    links.append(
        {
            "sheet": sheet,
            "added_row": row,
            "column": col,
            "target": str(target)
            if str(target).startswith("https://")
            else "file://" + str(target),
        }
    )


def output(rid, entity, label, p, note=""):
    if not str(p).startswith("https://") and not Path(p).exists():
        return
    rows["Outputs"].append([rid, entity, label, "Open " + label, note, str(p)])
    link("Outputs", len(rows["Outputs"]) - 1, "D", p)


for rid, folder in [("Z7", "muse-xhigh"), ("Z8", "glm53-medium")]:
    r = ROOT / folder
    timing = read(r / "timing.json")
    jobs = read(r / "review/arv2_research_job.json")
    people = {p["id"]: p["full_name"] for p in read(r / "review/contact_entity.json")}
    calls = read(r / "review/agent_model_call.json")
    costs = read(r / "execution-costs.json")
    activity = read(r / "activity-latest.json")["jobs"]
    ledger = [x for x in read(r / "review/provider_call_ledger.json") if x["phase"] == "result"]
    rec = read(r / "review/arv2_narrative_reconciliation.json")
    manifest = read(r / "manifest.json")
    amount = lambda pred: float(
        sum((Decimal(x["cost_usd"] or "0") for x in ledger if pred(x)), Decimal(0))
    )
    parts = [
        sum(float(x["usd"]) for x in costs),
        amount(lambda x: x["provider"] == "exa"),
        amount(lambda x: x["provider"] == "deepgram"),
        amount(lambda x: "embed" in x["label"]),
        amount(lambda x: x["label"] == "account-reconciliation-v1"),
        0,
        0,
        float(read(r / "model-preflight.json")["response_metadata"]["token_usage"]["cost"]),
        0,
    ]
    credits = float(sum((Decimal(x["credits"] or "0") for x in ledger), Decimal(0)))
    start = min(j["started_at"] for j in jobs)
    end = max(j["finished_at"] for j in jobs)
    settle = max([end] + [x["completed_at"] for x in rec])
    wall = elapsed(start, end)
    totalwall = elapsed(start, settle)
    counts = {
        j["job_id"]: sum(
            len(s["findings"])
            for s in read(r / "review" / j["job_id"] / "dossier.json")["sections"]
        )
        for j in jobs
    }
    report = quality if rid == "Z7" else r / "FINAL-STATUS.md"
    if rid == "Z8":
        report.write_text(f"""# GLM 5.3 medium retry: final status

The untouched retry has settled **needs_review**. All three dossiers, imports and four narrative pages survive; the account finalization and both common-Muse reconciliation attempts failed. It selected **Tom Anthony and Sanaz Yashar**, not the requested Nick/Vari. Its person research therefore is not a controlled comparison with that baseline.

| Stage | Outcome | Duration | Authored findings |
|---|---|---:|---:|
| Account | needs_review | 11m17s | 49 |
| Tom | completed | 9m13s | 33 |
| Sanaz | completed | 29m30s | 55 |

Research wall: {wall / 60:.2f} minutes. Through final failed reconciliation: {totalwall / 60:.2f} minutes. Recorded total **${sum(parts):.8f} + {credits:g} AI Ark credits**; researcher ${parts[0]:.6f}, Exa ${parts[1]:.6f}, Deepgram ${parts[2]:.6f}, embeddings ${parts[3]:.6f}, common reconciliation ${parts[4]:.6f}, preflight ${parts[7]:.8f}.

- Account completion first rejected invalid unprocessed-source references, then nine unresolved failed execution nodes. Saved outputs were not erased.
- Tom repaired an unsupported subject_id in completion notes and completed.
- Sanaz spent approximately 15m27s from formation start to import. This was authoring, not an Exa wait.
- Reconciliation revisions 203 and 204 both failed: `Each update needs page and section only`. This call uses the common Muse reconciler, not GLM research; its failure must not be attributed to GLM prose.
- This addition records lifecycle, cost, timing and artifact links. It is **not** a new full semantic quality audit of Tom or Sanaz. The latest detailed 20-probe comparison covers Muse xhigh versus Grok4.6 on the same Nick/Vari subjects.
- No restart, cancellation, code change or paid call was made during this reporting task. Monitoring paused once both retries settled.

See [timing]({r / "timing.json"}), [public action summary]({r / "activity-latest.json"}), [provider sources]({r / "all-raw/manifest.json"}), [trace verification]({r / "trace-verification.json"}), and workbook Outputs for all dossiers/pages.
""")
    summary = (
        "All 3 jobs completed; reconciliation recovered. Strong Nick voice; narrower account coverage and Vari wrong-employer attribution."
        if rid == "Z7"
        else "All dossiers/pages saved; account and reconciliation need review. Wrong people: Tom/Sanaz instead of Nick/Vari. Semantic quality not fully audited."
    )
    rows["Runs"].append(
        [
            rid,
            "Clue → Zafran",
            "muse-spark-1.3" if rid == "Z7" else "glm-5.3",
            "xhigh" if rid == "Z7" else "medium",
            day(wall),
            day(totalwall),
            None,
            credits,
            counts[jobs[0]["job_id"]],
            "\n".join(
                f"{people.get(j['subject_entity_id'], '?')}: {counts[j['job_id']]} + page"
                for j in jobs
                if j["subject_type"] == "person"
            ),
            summary,
            "Open report",
        ]
    )
    link("Runs", len(rows["Runs"]) - 1, "L", report)
    rows["Costs"].append(
        [
            rid,
            *parts,
            None,
            credits,
            "Recorded usage; common reconciliation separate; not invoice reconciled",
        ]
    )
    for t in timing:
        j = next(x for x in jobs if x["job_id"] == t["job_id"])
        name = people.get(j["subject_entity_id"], "Zafran Security")
        meta = r / "review" / j["job_id"]
        p = read(meta / "dossier.json")
        cs = read(meta / "imported-claims.json")
        authored = {f["id"]: f for s in p["sections"] for f in s["findings"]}
        stored = {c["value_json"]["dossier_entry"]["id"]: c["value_json"] for c in cs}
        diff = [
            fid for fid, f in authored.items() if stored.get(fid, {}).get("finding") != f["finding"]
        ]
        assert not diff, (folder, name, diff)
        checks.append(
            {
                "run": rid,
                "subject": name,
                "authored": len(authored),
                "stored": len(stored),
                "finding_text_differences": diff,
            }
        )
        pre = elapsed(t["start"], t["formation_model_start"])
        jr = len(rows["Jobs"])
        rows["Jobs"].append(
            [
                rid,
                name,
                t["status"],
                day(t["total_seconds"]),
                day(pre),
                day(t["formation_to_import_seconds"]),
                day(t["import_to_narrative_seconds"]),
                len(authored),
                len(stored),
                "Saved",
                t["model_calls"],
                float(t["model_usd"]),
                t["start"],
                t["finish"],
                t["job_id"],
            ]
        )
        eid = next(x["execution_id"] for x in costs if x["job_id"] == t["job_id"])
        mc = [x for x in calls if x["execution_id"] == eid]
        act = activity.get(t["job_id"], {})
        rows["Trace metrics"].append(
            [
                rid,
                name,
                len(mc),
                sum(x["input_tokens"] or 0 for x in mc),
                sum(x["cache_read_input_tokens"] or 0 for x in mc),
                sum(x["output_tokens"] or 0 for x in mc),
                day(t["model_seconds_sum"]),
                act.get("tool_counts", {}).get("read_file"),
                act.get("identical_repeat_reads"),
                None,
                None,
            ]
        )
        for label, fn in [
            ("Claim JSON", "dossier.json"),
            ("Readable dossier", "dossier.md"),
            ("Imported claims", "imported-claims.json"),
        ]:
            output(rid, name, label, meta / fn)
        page = (
            r
            / ("account" if j["subject_type"] == "account" else "person-" + j["subject_entity_id"])
            / "page.md"
        )
        output(
            rid,
            name,
            "Saved narrative",
            page,
            "Account may include common reconciliation; see initial version separately."
            if j["subject_type"] == "account"
            else "Researcher-authored contact page.",
        )
        for tid in sorted({x["langfuse_trace_id"] for x in mc if x.get("langfuse_trace_id")}):
            output(
                rid,
                name,
                "Langfuse execution",
                trace + tid,
                "Observable execution; private deliberations not reproduced.",
            )
    for label, fp in [
        ("Review report", report),
        ("Source acquisition manifest", r / "all-raw/manifest.json"),
        ("Action summary", r / "activity-latest.json"),
        ("Timing", r / "timing.json"),
        ("Model call metadata", r / "review/agent_model_call.json"),
        ("Provider cost ledger", r / "review/provider_call_ledger.json"),
        ("Trace verification", r / "trace-verification.json"),
        ("Initial account narrative", r / "account-initial/page.md"),
    ]:
        output(rid, "Run", label, fp)
    for tid in sorted(
        {
            x.get("extras_json", {}).get("langfuse_trace_id")
            for x in ledger
            if x["label"] == "account-reconciliation-v1"
        }
        - {None}
    ):
        output(rid, "Common Muse reconciler", "Langfuse reconciliation", trace + tid)
    normalized.append(
        {
            "id": rid,
            "folder": folder,
            "start": start,
            "research_end": end,
            "settled_at": settle,
            "research_wall_seconds": wall,
            "settled_seconds": totalwall,
            "parts": parts,
            "total": sum(parts),
            "credits": credits,
            "report": str(report),
            "counts": counts,
            "model_calls": len(calls),
            "resource_pin": manifest["resource_pin"],
        }
    )

for q in read(OUT / "muse-xhigh-quality-evidence.json")["probes"]:
    m = q["muse_xhigh"]
    refs = ", ".join(f"{f['subject']} {f['finding_id']}" for f in m["findings"])
    rows["Quality"].append(
        [
            "Z7",
            q["probe"],
            m["assessment"].replace("_", " "),
            m["note"],
            refs,
            len(m["acquired_passage_matches"]),
            "Open evidence",
        ]
    )
    link("Quality", len(rows["Quality"]) - 1, "G", quality)
for title, assessment, note, refs in [
    (
        "Wrong-employer attribution",
        "Confirmed source contradiction",
        "Secureworks and Ivanti bullets became current Zafran remit; error reaches Vari page. Full returned profile clearly separates employers.",
        "Vari F004 vs F006 and profile headings",
    ),
    (
        "Narrative citation support",
        "Specifics absent from cited claim",
        "Initial Amex February event cites only Cisco F007; hackathon hours cite F024 hiring/joining. Facts have raw support, but cited claims do not contain those specifics.",
        "Initial money-and-momentum / why-now",
    ),
    (
        "Import text fidelity",
        "109 of 109 preserved",
        "Programmatic comparison found no finding-text differences between 109 authored entries and imported records. This does not validate factual accuracy or prove all research was selected.",
        "31 account / 53 Nick / 25 Vari",
    ),
]:
    rows["Quality"].append(["Z7", title, assessment, note, refs, None, "Open evidence"])
    link("Quality", len(rows["Quality"]) - 1, "G", quality)
rows["Quality"].append(
    [
        "Z8",
        "Comparable person research",
        "Not the requested subjects",
        "GLM selected Tom/Sanaz rather than fixed Nick/Vari. Final outputs are available; no new full semantic grading of these different people in this update.",
        "49 account / 33 Tom / 55 Sanaz",
        None,
        "Open status",
    ]
)
link("Quality", len(rows["Quality"]) - 1, "G", ROOT / "glm53-medium/FINAL-STATUS.md")
for rid, entity, cat, what, confidence in [
    (
        "Z7",
        "Common reconciliation",
        "Response-shape contract",
        "Revision175 failed: Each update needs page and section only. Revision176 completed. All research jobs and pages survived.",
        "Confirmed logs; common Muse model, separate from researcher",
    ),
    (
        "Z7",
        "Vari narrative",
        "Recovered tool arguments",
        "Narrative shape/quotation errors required revised calls; final contact page stored and job completed.",
        "Observed recovery; semantic attribution error remains separately",
    ),
    (
        "Z8",
        "Committee selection",
        "Assignment deviation",
        "Account nominated Tom Anthony and Sanaz Yashar instead of the fixed Nick Fisher and Vari Kaur. Both nominated people completed.",
        "Confirmed subjects; not a controlled person comparison",
    ),
    (
        "Z8",
        "Account finalization",
        "Invalid references / unresolved tool failures",
        "Rejected invalid unprocessed-source IDs, then nine unresolved failed nodes. Account ended needs_review despite saved49 findings and two pages.",
        "Confirmed; do not equate failure with lost research",
    ),
    (
        "Z8",
        "Tom finalization",
        "Recovered completion schema",
        "Unsupported subject_id in CompletionNotes rejected; corrected and completed.",
        "Confirmed recovery",
    ),
    (
        "Z8",
        "Common reconciliation",
        "Response-shape contract",
        "Revisions203 and204 failed: Each update needs page and section only. Generation settled needs_review with existing pages intact.",
        "Confirmed; common Muse reconciliation, not GLM researcher",
    ),
]:
    report = quality if rid == "Z7" else ROOT / "glm53-medium/FINAL-STATUS.md"
    rows["Failures"].append([rid, entity, cat, what, confidence, "Open evidence"])
    link("Failures", len(rows["Failures"]) - 1, "F", report)
rows["Method"] = [
    [
        "Latest retry audit",
        "Z7 is Muse xhigh on the same Zafran/Nick/Vari workload: all109 authored findings reviewed, 20 comparative probes plus attribution/citation/import checks. Z8 adds GLM final lifecycle and artifacts only; Tom/Sanaz differ from the fixed comparison.",
    ],
    [
        "No complete truth set",
        "At least five source-specific account omissions established for Z7; not a denominator for percentage recall. Grok also omitted useful evidence. Successful import/completion is not semantic validation.",
    ],
]
(OUT / "retry-workbook-update.json").write_text(
    json.dumps(
        {"rows": rows, "links": links, "runs": normalized, "import_checks": checks}, indent=2
    )
)
(OUT / "retry-import-checks.json").write_text(json.dumps(checks, indent=2))
print(json.dumps({"runs": normalized, "import_checks": checks}, indent=2))
