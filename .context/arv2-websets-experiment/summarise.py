"""Tables for the evaluation: distinct companies per arm, per-criterion verdicts, cost, timing."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
PRO_USD_PER_CREDIT = 449 / 100_000  # Pro plan: $449 for 100,000 credits
CORE_USD_PER_CREDIT = 49 / 8_000  # Core plan: $49 for 8,000 credits


def host(url: str | None) -> str:
    if not url:
        return ""
    h = (urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def search_arm() -> None:
    print("## Arm S — /search (three v3 queries, re-run)\n")
    total = 0.0
    for path in sorted(RAW.glob("search_*.json")):
        out = json.loads(path.read_text())
        cost = (out.get("costDollars") or {}).get("total") or 0
        total += cost
        hosts = Counter(host(r.get("url")) for r in out.get("results") or [])
        print(f"- `{path.stem}`: ${cost:.3f}, {sum(hosts.values())} pages, hosts: "
              + ", ".join(f"{h}×{n}" if n > 1 else h for h, n in hosts.most_common()))
    print(f"\nSearch spend: ${total:.3f}\n")


def webset_arm(arm: str) -> None:
    final = json.loads((RAW / f"webset_{arm}_final.json").read_text())
    rows = json.loads((RAW / f"webset_{arm}_items.json").read_text())
    search = (final.get("searches") or [{}])[0]
    progress = search.get("progress") or {}
    criteria = [c.get("description", "") for c in search.get("criteria") or []]
    print(f"## Arm {arm} — webset `{final.get('id')}`\n")
    print(f"- status {final.get('status')} / search {search.get('status')}; found {progress.get('found')}, "
          f"analyzed {progress.get('analyzed')}, completion {progress.get('completion')}%")
    for c in search.get("criteria") or []:
        print(f"- criterion successRate {c.get('successRate')}: {c.get('description')[:90]}…")
    green = [r for r in rows if all(e.get("satisfied") == "yes" for e in r.get("evaluations") or [])]
    credits = 10 * len(green)
    print(f"- items returned {len(rows)}, all-green {len(green)} → {credits} credits "
          f"(≈ ${credits * PRO_USD_PER_CREDIT:.3f} at Pro, ${credits * CORE_USD_PER_CREDIT:.3f} at Core)\n")
    print("| # | company | domain | HQ | employees | funding total | latest round | " + " | ".join(
        f"c{i + 1}" for i in range(len(criteria))) + " |")
    print("|---|---|---|---|---|---|---|" + "---|" * len(criteria))
    for i, r in enumerate(rows, 1):
        p = r.get("properties") or {}
        co = p.get("company") or {}
        fin = co.get("financials") or {}
        latest = fin.get("fundingLatestRound") or {}
        latest_txt = ""
        if isinstance(latest, dict) and latest:
            latest_txt = f"{latest.get('name') or ''} {latest.get('date') or ''} {latest.get('amount') or ''}".strip()
        hq = co.get("headquarters") or {}
        verdicts = " | ".join(
            {"yes": "✅", "no": "❌", "unclear": "❓"}.get(e.get("satisfied"), "?")
            for e in r.get("evaluations") or []
        )
        print(f"| {i} | {co.get('name') or p.get('description', '')[:40]} | {host(p.get('url'))} | "
              f"{hq.get('city') or ''} {hq.get('state') or ''} {hq.get('countryCode') or ''} | "
              f"{co.get('employees') or ''} | {fin.get('fundingTotal') or ''} | {latest_txt} | {verdicts} |")
    print()
    print("### Verdict reasoning, per item\n")
    for i, r in enumerate(rows, 1):
        co = (r.get("properties") or {}).get("company") or {}
        print(f"**{i}. {co.get('name')}**")
        for e in r.get("evaluations") or []:
            refs = ", ".join(host(x.get("url")) for x in e.get("references") or [])
            print(f"- {e.get('satisfied')}: {re.sub(r'\\s+', ' ', e.get('reasoning') or '')[:260]} [{refs}]")
        print()


if __name__ == "__main__":
    search_arm()
    for arm in ("W5", "W3"):
        if (RAW / f"webset_{arm}_items.json").exists():
            webset_arm(arm)
    ledger = json.loads((HERE / "ledger.json").read_text())
    print("## Ledger\n")
    for row in ledger:
        print("- " + json.dumps({k: v for k, v in row.items() if k != "at"}))
