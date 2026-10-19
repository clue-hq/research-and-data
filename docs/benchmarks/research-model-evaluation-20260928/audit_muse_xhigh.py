"""Read-only evidence comparison; no model/provider calls or database writes."""

import json, re
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
M = BASE / ".artifacts/zafran-muse-xhigh-glm-retry-20260928/muse-xhigh"
G = BASE / ".artifacts/zafran-three-model-medium-20260928/grok46"
JOBS = {
    "account": "59d4870e-2207-56ca-a50b-e76ab86f6a53",
    "nick": "1a912ee3-806b-50ca-a0b5-d927cab2f677",
    "vari": "d9a7b71f-fa01-5b6b-8599-3119e6461527",
}
read = lambda p: json.loads(p.read_text())
docs = {s: read(M / "review" / j / "dossier.json") for s, j in JOBS.items()}
findings = {
    s: {f["id"]: f for sec in d["sections"] for f in sec["findings"]} for s, d in docs.items()
}
baseline = read(OUT / "quality-evidence.json")
raw = []
for op in read(M / "all-raw/manifest.json"):
    if op["kind"].startswith("quality_tool:"):
        continue
    p = M / "all-raw" / op["exported_file"]
    d = read(p)
    b = json.loads(d["body_utf8"]) if d.get("body_utf8") else d
    for item in b.get("results", []):
        raw.append(
            {
                "subject": next((s for s, j in JOBS.items() if j == op["job_id"]), None),
                "file": str(p),
                "url": item.get("url"),
                "text": "\n".join(str(item.get(k, "")) for k in ["title", "text", "highlights"]),
            }
        )

# Explicit editorial assessments, backed by exact saved finding objects and provider passages.
P = [
    (
        "preserved",
        "account:F026;vari:F016",
        r"building ABM end.to.end|shoulder.to.shoulder",
        "Like Grok A41/V22–23: preserves Vari’s own end-to-end ABM and Sales-partnership words. Strong useful signal.",
    ),
    (
        "preserved_bundled",
        "account:F011,F012,F013;vari:F021,F022",
        r"large team and a large budget",
        "Hands-on HubSpot work, account tiers, buying groups and outcome measures survive. Grok A30–32 separates the units better. Muse interpretation “production-constrained” is stronger than a lean-role requirement proves.",
    ),
    (
        "account_omission_recovered_person",
        "nick:F047",
        r"Common Room|Monday at 9:30",
        "The full workflow was in account media-discovery results but omitted from the account JSON. Nick later preserves all five tools and the self-built Claude workflow. Grok retained it at account stage.",
    ),
    (
        "preserved_bundled",
        "account:F024;nick:F061",
        r"shipping real workflows",
        "Distinctive “shipping real workflows” survives in both stages. Account F024 unnecessarily combines the 2026 hiring post with a separate April 2024 joining/Gong article.",
    ),
    (
        "account_omission_recovered_person",
        "nick:F046",
        r"overwrite.{0,40}pipeline|no human would",
        "Account acquired the warning but omitted it. Nick quotes both concrete harms, improving on the earlier Muse max run. Grok also recovered both in person research, with clearer attribution of the relayed Lemkin practices.",
    ),
    (
        "account_omission_recovered_person",
        "nick:F048",
        r"working demo.{0,50}hours",
        "Exact idea-to-demo-in-hours passage was in account-deep returned sources but absent from account findings. Nick restores it. Grok retained it at both stages.",
    ),
    (
        "partial_account_recovered_person",
        "account:F023;nick:F043,F044,F070",
        r"record.store|comic store|Pokemon cards",
        "Account retained the 2024 record-store campaign but omitted acquired 2026 comic-store details. Nick preserves both distinct tactics and reported results, broadly comparable to Grok person depth.",
    ),
    (
        "selection_and_discovery_gaps",
        "account:F001",
        r"Exposure Gateway|Zero Day Agent|Asset Ownership Agent",
        "Zero Day Agent and the September Asset Ownership Agent announcement were returned but have no substantive findings. Exposure Gateway was not found in the targeted saved-result scan. Grok A21/A22 retained dated author, mechanism, integrations and response workflow.",
    ),
    (
        "partial_with_omission",
        "account:F006,F007",
        r"Amex|30.40 million|layoff|down.round",
        "Series C and Cisco survive. A direct February Amex announcement was retrieved but omitted. Grok also captured later journalist ARR/acquisition context; that adverse reporting was not located in Muse returned-result scans. Funding is not marketing budget.",
    ),
    (
        "discovery_gap",
        "account:F027",
        r"Havdala.{0,180}Nvidia|Nvidia.{0,180}Havdala",
        "No departure passage located in Muse returned results. Grok A91 retained a qualified secondary report. Muse founder/leadership lists do not replace this dated contrary evidence; neither run proves the external report is true.",
    ),
    (
        "selection_omission",
        "",
        r"5X.{0,30}new|new \$\$\$|MTTR.{0,30}80",
        "The same account-deep results include Sanaz’s “5X in new $$$$$” and almost-80% MTTR statement. Neither appears in Muse authored findings. Grok also omitted the 5X signal: the baseline is not complete.",
    ),
    (
        "mixed_scope_and_contradiction",
        "account:F019,F024;nick:F041,F065;vari:F020",
        r"Gong|6sense|Demandbase|Outreach",
        "Career tools and employer installations are usually distinguished well. But account F019 says Gong was not named in any Zafran source while F024 already cites Nick’s first-week Gong-call research. That contradiction survives the final account narrative.",
    ),
    (
        "rich_shortform_preservation",
        "nick:F030,F031,F032",
        r"Cocktail Chemistry|audience cares",
        "Strong book/hobby/audience-feedback wording, visible on the contact page. Grok also had an additional first-person kitchen/hobby passage not located in Muse acquisition. One very large Muse book finding bundles several independently usable details.",
    ),
    (
        "lead_only",
        "nick:F033",
        r"CocktailGPT|cocktailgpt.com",
        "Project name, profile description and date retained; no project-site fetch. Similar limitation to Grok, behind the earlier Muse max run which inspected the site. Do not claim all available side-project depth was exhausted.",
    ),
    (
        "lead_only",
        "nick:F034",
        r"Get out of the building|technical curiosity|IT doesn.t want to be",
        "Publication titles survive, not the actual old article/deck arguments. Both this retry and Grok miss substance found by the earlier Muse max run; a reason to retain a cross-run evidence union.",
    ),
    (
        "listing_only_no_transcription",
        "nick:F080,F081,F082,F083,F084",
        r"Zero Trust in Healthcare|value.based care|BYOD",
        "Muse keeps ISMG/Okta metadata, performs no recording-resolution or transcription call, and stops after discovering listings. Grok obtained actual ISMG speech with speaker/history qualifications. No failed transcription attempt establishes provider unavailability here.",
    ),
    (
        "source_review_failure",
        "vari:F009,F010",
        r"Successfully integrated CRM",
        "Axiom integration is present but downgraded to synthesis-only insufficient context, despite the directly returned profile containing the full Salesforce–HubSpot quote. Grok V10 uses that passage correctly. Both preserve the truncated 25% metric without inventing an endpoint.",
    ),
    (
        "thinner_profile_discovery",
        "vari:F014,F024,F025",
        r"arzgsjcfpzxh|6o2fh9ncjbr7|Fundamentals of Next.Gen",
        "Education and thin outside-work footprint are qualified. Explicit 6sense/Demandbase certification findings are absent; exact credential passages not located in acquired-result scan. Grok retains credentials; neither should invent hobbies.",
    ),
    (
        "material_attribution_and_claim_hygiene_defects",
        "account:F015,F024,F030,F031;nick:F084,F091,F100;vari:F004,F006,F023,F024",
        r"",
        "Vari F004 assigns Secureworks and Ivanti experience to current Zafran. Research gaps and analyst characterizations are stored as supported observations. Independent posts/events/people remain bundled. Grok also has bookkeeping, duplication and bundling defects; it is a comparative baseline, not gold truth.",
    ),
    (
        "published_useful_but_inaccurate_in_places",
        "account:F019,F024;nick:F046,F047;vari:F004",
        r"",
        "All initial pages are saved. Nick’s page preserves strong quotations and seller-relevance caveats. Vari’s page repeats the wrong-employer remit; account tooling contradicts its own Gong evidence. Final account page includes common Muse reconciliation, assessed separately from initial authoring.",
    ),
]
rows = []
for old, (status, refs, pat, note) in zip(baseline["probes"], P):
    fs = []
    for part in refs.split(";"):
        if not part:
            continue
        subject, ids = part.split(":")
        for fid in ids.split(","):
            fs.append(
                {
                    "subject": subject,
                    "finding_id": fid,
                    "dossier_path": str(M / "review" / JOBS[subject] / "dossier.json"),
                    "finding": findings[subject][fid],
                }
            )
    matches = []
    if pat:
        for x in raw:
            m = re.search(pat, x["text"], re.I | re.S)
            if m:
                matches.append(
                    {k: v for k, v in x.items() if k != "text"}
                    | {"excerpt": x["text"][max(0, m.start() - 200) : m.end() + 800]}
                )
    rows.append(
        {
            "probe_id": old["probe_id"],
            "key": old["key"],
            "probe": old["probe"],
            "grok46": old["models"]["grok46"],
            "muse_xhigh": {
                "assessment": status,
                "note": note,
                "findings": fs,
                "acquired_passage_matches": matches,
            },
        }
    )
evidence = {
    "scope": "Latest Muse xhigh retry versus completed Grok4.6 medium Zafran research. All 109 Muse findings and three narratives reviewed; 20 targeted comparative probes with saved provider-result excerpts. Not an exhaustive recall denominator or independent web fact-check. No new paid calls.",
    "probes": rows,
}
(OUT / "muse-xhigh-quality-evidence.json").write_text(
    json.dumps(evidence, indent=2, ensure_ascii=False)
)

# Preserve the earliest account section versions, before the common reconciler edited them.
blocks = read(M / "review/display_block.json")
selected = {}
for b in sorted(blocks, key=lambda x: x["generated_at"]):
    if b["subject_kind"] == "account":
        selected.setdefault((b["page"], b["section_key"]), b)
initial = M / "account-initial"
initial.mkdir(exist_ok=True)
(initial / "display-blocks.json").write_text(json.dumps(list(selected.values()), indent=2))
lines = [
    "# Muse xhigh initial account narrative",
    "",
    "Earliest saved version of each section, before common reconciliation. Literal text; claim links remain in the accompanying JSON.",
    "",
]
for b in selected.values():
    d = b["body_json"].get("_quality_draft", b["body_json"])
    lines += ["## " + b["page"] + " / " + b["section_key"], ""]
    lines += [s.get("text", "") + "\n" for s in d.get("intro", [])]
    for item in d.get("items", []):
        lines += ["### " + item.get("h2", ""), ""] + [
            s.get("text", "") + "\n" for s in item.get("body", [])
        ]
(initial / "page.md").write_text("\n".join(lines))


def link(label, p):
    return f"[{label}]({p})"


def mdref(f):
    return link(f["subject"] + " " + f["finding_id"], f["dossier_path"])


table = []
for r in rows:
    g = r["grok46"]
    m = r["muse_xhigh"]
    table.append(
        "| "
        + str(r["probe_id"])
        + " | "
        + r["probe"]
        + " | "
        + g["note"]
        + " | "
        + m["note"]
        + " | "
        + (", ".join(mdref(f) for f in m["findings"]) or "No retained finding")
        + " |"
    )
report = (
    """# Muse xhigh retry versus Grok 4.6 medium: research-quality review

**Decision: keep Grok 4.6 medium as the quality baseline for now. Muse xhigh is a substantially faster, cheaper candidate, with strong Nick research, but it is not a demonstrated quality-equivalent replacement.** Its most consequential defect is a wrong-employer attribution in Vari’s current remit that propagates into her narrative. Account coverage is also narrower, including omissions from material already acquired.

## Scope and fairness

This review reads all 31 account, 53 Nick and 25 Vari Muse findings, their review statuses and interpretations, the saved narratives, original returned source passages and observable tool activity. It compares 20 established probes with the same Clue→Zafran Grok 4.6 medium baseline (52 account, 49 Nick, 38 Vari findings). Counts describe authored records, not independently correct facts. The source scan separates direct result text/highlights from Exa’s generated report and excludes duplicated quality-tool wrappers.

Both use resource revision 24 and the retained seller context. The retry ran after runtime completion/delegation repairs. Live search returns different evidence, effort settings differ, and reconciliation is a separate common Muse call. This is a practical end-to-end comparison, not proof that effort or model choice alone caused each difference. No new research was purchased for this audit. Neither run is an exhaustive truth set.

## Completion, time and recorded spend

| Measure | Grok 4.6 medium | Muse 1.3 xhigh retry |
|---|---:|---:|
| Account job | 15m45s | 7m06s |
| Nick job | 19m11s | 10m39s |
| Vari job | 13m24s | 8m58s |
| Research wall (overlapping jobs) | 30m13s | 16m11s |
| Through reconciliation settlement | 30m16s | 18m45s |
| Research-model calls | 185 | 186 |
| Research-model USD | $12.102434 | $5.920997 |
| Exa USD | $0.293000 | $0.281000 |
| Deepgram + embeddings USD | $0.082165 | $0 |
| Common reconciliation USD | $0.174809 | $0.338008 |
| Preflight USD | $0.000818 | $0.00052925 |
| Total recorded USD | $12.653226 | $6.54053425 |
| AI Ark credits (separate) | 3.1 | 3.1 |
| Saved authored findings | 139 | 109 |
| Initial narrative pages | Account overview + insights; Nick; Vari | Account overview + insights; Nick; Vari |
| Formal outcome | Person finalization failed; outputs saved; generation settled partial | All research jobs completed; reconciliation succeeded after one failed update |

Muse is about **48.3% cheaper** and **38.0% faster through settlement** in this pair. Its research wall is 46.5% shorter. It did not achieve that by using fewer model calls; it made almost the same number. It also did less media follow-through and narrower account authoring. Do not interpret the entire gain as a like-for-like efficiency improvement.

## The findings that most affect the decision

### 1. Wrong-employer attribution reaches the user

Muse Vari **F004** says “For her Zafran role Kaur reports” and quotes cybersecurity demand-engine responsibilities plus lead-scoring/distribution responsibilities. The returned full profile places the first set under **Secureworks, June 2022–May 2025**, and the second under **Ivanti, March 2015–July 2017**. The Zafran heading only establishes the current title/dates; it does not contain those remit bullets. F006 separately records the Secureworks context correctly, so this is not simply missing information.

The contact narrative then says “at Zafran she reports building a B2B demand-generation engine” and that she currently owns the SDR handoff. The error therefore survives source acquisition, dossier review, import and narrative. Qualifications about truncated highlights do not repair the wrong employer. Grok’s retained profile/career findings do not make this same current-role transfer.

### 2. Strong Nick evidence is preserved—but account research drops already-acquired material

Nick’s Muse findings preserve the five-tool Monday BDR workflow (F047), both pipeline-overwrite/prospect-blast harms (F046), Claude Code idea-to-demo-in-hours (F048), ZafranGPT’s actual uses (F045), both record-store and comic-store campaigns (F043/F044/F070), and his cocktail-book/audience-feedback story (F030). His page presents many of these with direct quotations and qualified seller relevance. This is a real strength, not merely a large finding count.

But the account agent had already received the Monday workflow, guardrails post, demo-in-hours passage and comic-store post. It omitted those specifics from its own JSON; Nick later recovered them. Reconciliation improves the final account page, but that does not make the initial account selection complete or reliable when that person job is absent.

### 3. At least five acquired account signals lack their own substantive saved finding

These are source-specific omissions from the authored JSON, not a claim that the whole topic disappeared or every final page omitted every detail:

| Acquired material | What remains missing | Qualification |
|---|---|---|
| February 24 Amex investment announcement | Its date and financial-services rationale as a distinct finding | F007 names Amex as an existing investor, but does not record this event. The initial narrative adds February without an appropriate supporting claim. |
| Company feed: Zero Day Agent | Its detection/exposure-assessment workflow | Generic platform description is not this initiative. |
| September 1 Asset Ownership Agent announcement | Named recent initiative | Company-feed excerpt is an available lead; fuller technical details need source context. |
| Sanaz’s “5X in new $$$$$ compared to last year” | Her attributed wording | The metric is ambiguous; it must not be normalized into ARR. |
| Same Sanaz post: almost-80% lower customer MTTR | That specific attributed result | Do not convert a company-reported result into independently verified performance. |

Grok also omitted Sanaz’s 5X statement. Exposure Gateway, Havdala’s reported departure and later adverse financial reporting were found by Grok but not located in Muse’s targeted returned-result scan: those are discovery gaps, distinguished from selection omissions above.

### 4. Evidence can be present while the agent says it is missing

Muse account **F019** says Gong was not named in any Zafran source. Its own **F024** cites Nick’s joining article and first-week Gong calls, and Nick F041 retains the passage. The final account Tools section still says Gong was not named, while another section describes those calls. This is a direct internal inconsistency, not an uncertainty about company-wide deployment: a scoped use statement would be supported.

Muse Vari **F010** labels her Axiom Salesforce–HubSpot integration “synthesis-only” and insufficient context. The full profile returned during preliminary search contains the exact first-person integration bullet. Grok V10 preserves it directly. Muse’s caution is preferable to fabricating evidence, but here it incorrectly discounts good evidence it already possessed.

There is also a narrative-to-claim fidelity gap: the initial Money section adds the February Amex event while citing only the Cisco finding F007. Initial Why now adds the hackathon’s hours detail while citing F024, which contains the hiring and joining posts instead. The original research supports these facts, but the selected claim references do not carry the added specifics. A fact can be true in the raw evidence and still be incorrectly sourced in the narrative.

### 5. Media and promising leads stop too early

Nick’s ISMG interview and Okta webinar listings are saved, but Muse makes no media-resolution or transcription call and no person-stage page fetch after deep research. Grok obtains actual ISMG speech, with historical-role/speaker caveats. Muse’s “no playable long-form transcript was located” is a limit of this investigation, not proof that the material is inaccessible.

CocktailGPT and older publications remain profile/listing leads. Grok is also limited here; earlier Muse max did better on the project-site follow-up and old authored PMM article/deck. Different runs have complementary discoveries, so replacing a model should be evaluated against their useful evidence union, not just one winner’s count.

### 6. Claim hygiene remains imperfect in both

Muse account F015 stores unanswered team/list-size questions as a supported observation; F030/F031 mix fit assessment or negative search results with factual claims. Nick F084/F091 include research-coverage bookkeeping; F100 is an analyst character portrait stored as observation. Vari F023 is likewise synthesis and F024 a coverage inventory. These belong in research notes or explicit interpretation, unless a source itself makes the statement.

Independent events are still bundled: account F024 joins two posts from different years; F029 combines event periods; Nick F072 combines several launches/events. Full sentences are often preserved, but separately correctable signals are not always separate. Grok also has bookkeeping, repeated summaries and overclassified conflicts, so “baseline” does not mean the claim-selection problem is solved.

## Twenty-probe comparison

| # | Probe | Grok baseline | Muse retry | Exact Muse findings |
|---|---|---|---|---|
"""
    + "\n".join(table)
    + """

## What the observable execution explains

- Account: 52 read_file calls, 6 section saves; about 3m42s before formation, 1m40s formation→import, 51s import→narrative.
- Nick: 106 read_file calls, 10 section saves; about 5m46s before formation, 3m35s formation→import, 47s import→narrative.
- Vari: 56 read_file calls; 7 section-save attempts in the action trace; about 4m57s before formation, 1m51s formation→import, 1m55s import→final narrative.
- No exact repeated-read requests were reported in the captured activity summary. This does not prove all reads were necessary or that overlapping excerpts were absent.
- Both people used preliminary searches, media discovery and a deep call, but no targeted page-fetch/transcription continuation followed. Read volume alone therefore does not establish effective follow-through.
- All 186 research model IDs and 36 provider-attempt IDs were found in Langfuse. This check does not audit every filesystem callback. Private model deliberations are not reproduced.
- Vari repaired narrative-shape/quotation validation errors and completed. Common reconciliation first failed with “Each update needs page and section only”; the subsequent revision succeeded. These runtime outcomes are separate from semantic quality.

## Recommended next decision

Do not replace the quality baseline solely on this cheaper successful completion. First use a **fixed saved-evidence replay**, with the existing standard unchanged, to test employer/date attribution, acquired-source coverage and media/side-project follow-through. That isolates selection/reasoning from Exa search variance and avoids another full research purchase. The acceptance cases should remain evaluation fixtures, not hardcoded Zafran instructions.

Muse’s Nick result is credible evidence that it can produce useful, specific research. The account omissions and Vari attribution error prevent a blanket “same quality at half cost” conclusion. Grok remains the safer current baseline; neither result is ready to be treated as error-free without review.

## Inspectable artifacts

"""
)
for label, p in [
    ("Exact 20-probe evidence", OUT / "muse-xhigh-quality-evidence.json"),
    ("Source checks", M / "review/targeted-source-checks.json"),
    ("Vari full returned profile", M / "review/vari-profile-source.txt"),
    ("Muse initial account narrative", initial / "page.md"),
    ("Muse final reconciled account narrative", M / "account/page.md"),
    ("Nick narrative", M / "person-a503cf2b-0ce4-4867-8e80-d47764e89d01/page.md"),
    ("Vari narrative", M / "person-b0b87722-4292-444b-bfc5-4eaa371b7ca8/page.md"),
    ("Provider acquisition manifest", M / "all-raw/manifest.json"),
    ("Observable action summary", M / "activity-latest.json"),
    ("Timing", M / "timing.json"),
    ("Trace ID verification", M / "trace-verification.json"),
    ("Grok run report", G / "REPORT.md"),
]:
    report += "- " + link(label, p) + "\n"
(OUT / "MUSE-XHIGH-QUALITY.md").write_text(report)
print(
    "Reviewed",
    sum(len(x) for x in findings.values()),
    "findings;",
    len(rows),
    "probes;",
    len(raw),
    "returned source records (including repeats).",
)
