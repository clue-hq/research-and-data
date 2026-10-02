"""Exa Answer as the verifier — one structured question per ICP gate per company.

Websets found the companies; this asks Exa Answer (POST /answer, outputSchema) to verify each ICP
hard gate from fresh web evidence. The question is the gate's own test text from the ICP document;
nothing per-gate lives in code. The verdict, the quote and the URL come back as JSON; we keep one
guard: the quote must appear in a citation Exa returned (its text is requested), else `unclear`.

Usage: set -a; source .env; set +a; uv run python .context/arv2-websets-experiment/answer/run_answer.py [--only Name,Name] [--model exa|exa-pro|exa-fast]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from exa_common import ledger_append, request, save_raw  # noqa: E402

TODAY = "2026-09-10"

#: The ICP's hard gates, rule + test verbatim from the confirmed document
#: (.context/arv2-answer-key-knowledge/icp-clue-abm-buyers.md), tightened to the v3 stage ruling.
GATES = {
    "stage": {
        "rule": "The company's most recent priced funding round is a Series A or Series A extension, announced within the last 24 months",
        "test": "A dated announcement (press release, lead investor's post, or the company's own newsroom) that names the round and at least one investor. A seed-only, pre-seed, bootstrapped, public or PE-owned company, or one whose most recent round is Series B or later or a growth round, is outside the stated stage.",
    },
    "geography": {
        "rule": "US-headquartered",
        "test": "The HQ city and state on the company's own site, its LinkedIn page, or its funding announcement dateline is in the United States.",
    },
    "hiring": {
        "rule": "Actively hiring now, with at least one open go-to-market role",
        "test": "At least one requisition listed today on the company's own careers page or ATS board with a GTM title: sales, marketing, growth, ABM, demand generation, SDR or BDR, partnerships, revenue operations.",
    },
    "intent": {
        "rule": "At least one citable, dated buying-intent signal for outbound or account-based prospecting",
        "test": "A GTM requisition that describes list-building, outbound or account research as the job; a stated target-account list; a founder or growth leader publicly saying founder-led sales or outbound is at its limit; or a recent round explicitly earmarked for go-to-market expansion. Each with a verbatim quote and the URL it came from.",
    },
}

SYSTEM_PROMPT = (
    f"Today is {TODAY}. You are verifying one qualification test for one specific company. "
    "Use only what the sources say. The most recent dated announcement of an event is the authority "
    "on the company's current state; older announcements are history; company profile pages "
    "(LinkedIn, Crunchbase, CB Insights, Tracxn) are secondary to the company's own pages and to "
    "dated news. Never confuse the company with a same-name company on a different website. "
    "Answer pass only when a source states the fact; fail only when a source contradicts the test; "
    "otherwise unclear. The evidence_quote must be copied verbatim from the cited source."
)

OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["verdict", "reasoning", "evidence_quote", "evidence_url", "evidence_date"],
    "additionalProperties": False,
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "fail", "unclear"]},
        "reasoning": {"type": "string", "description": "One or two sentences: what the freshest relevant source says and how it decides the test."},
        "evidence_quote": {"type": "string", "description": "A verbatim sentence or fragment from the cited source that decides the verdict; empty if unclear."},
        "evidence_url": {"type": "string", "description": "The URL the quote comes from; empty if unclear."},
        "evidence_date": {"type": "string", "description": "The date of that source as shown on it (YYYY-MM-DD if known); empty if unknown."},
    },
}


def ask(company: str, url: str, gate: str, model: str) -> dict:
    spec = GATES[gate]
    query = (
        f"Company: {company} (website {url}).\n"
        f"Test to verify: {spec['rule']}.\n"
        f"How it is tested: {spec['test']}\n"
        f"Decide pass, fail or unclear for THIS company today, citing the freshest relevant source."
    )
    body = {"query": query, "model": model, "text": True, "systemPrompt": SYSTEM_PROMPT, "outputSchema": OUTPUT_SCHEMA}
    started = time.monotonic()
    status, out = request("POST", "https://api.exa.ai/answer", body, timeout=180)
    elapsed = round(time.monotonic() - started, 1)
    slug = "".join(ch if ch.isalnum() else "_" for ch in company)[:30]
    out["_request"] = body
    save_raw(f"answer_{model}_{slug}_{gate}", out)
    cost = float(((out.get("costDollars") or {}).get("total")) or 0)
    ledger_append({"arm": "A", "provider": "exa_answer", "model": model, "label": f"{slug}:{gate}", "http": status, "cost_usd": cost, "elapsed_s": elapsed})
    answer = out.get("answer") if isinstance(out.get("answer"), dict) else {"verdict": "unclear", "reasoning": f"non-object answer: {str(out.get('answer'))[:120]}", "evidence_quote": "", "evidence_url": "", "evidence_date": ""}
    # the one guard: the quote must exist in a returned citation's text (whitespace-normalised)
    quote = " ".join((answer.get("evidence_quote") or "").split())
    cited = [c for c in out.get("citations") or []]
    grounded = False
    if quote:
        for c in cited:
            text = " ".join((c.get("text") or "").split())
            if quote and quote[:120] in text:
                grounded = True
                break
    if answer.get("verdict") in ("pass", "fail") and not grounded:
        answer["verdict_after_guard"] = "unclear"
        answer["guard"] = "quote not found verbatim in any returned citation text"
    else:
        answer["verdict_after_guard"] = answer.get("verdict")
        answer["guard"] = "ok" if quote else "no quote"
    answer["_cost_usd"] = cost
    answer["_elapsed_s"] = elapsed
    answer["_citations"] = [(c.get("publishedDate") or "")[:10] + " " + (c.get("url") or "") for c in cited][:6]
    return answer


if __name__ == "__main__":
    model = "exa"
    if "--model" in sys.argv:
        model = sys.argv[sys.argv.index("--model") + 1]
    companies = json.loads((HERE / "companies.json").read_text())
    if "--only" in sys.argv:
        names = set(sys.argv[sys.argv.index("--only") + 1].split(","))
        companies = [c for c in companies if c["name"] in names]
    results = {}
    total = 0.0
    for c in companies:
        results[c["name"]] = {}
        for gate in GATES:
            a = ask(c["name"], c["url"], gate, model)
            results[c["name"]][gate] = a
            total += a["_cost_usd"]
            print(f"{c['name']:22} {gate:9} {a.get('verdict'):7} → {a['verdict_after_guard']:7} ${a['_cost_usd']:.4f} {a['_elapsed_s']:5.1f}s | {a.get('reasoning','')[:110]}", flush=True)
    (HERE / f"answers_{model}.json").write_text(json.dumps(results, indent=2))
    print(f"TOTAL ${total:.3f} for {len(companies)} companies × {len(GATES)} gates")
