"""Check every quote a trial run cited: is the sentence really on the page it names?

    set -a; source .env; set +a
    uv run python trials/exa-agent-discovery/check_quotes.py --run <run dir>

Reads companies.json, fetches each cited URL once through Exa /contents (live crawl when the
cached copy is missing), and checks each quote against the page text after folding case, quote
marks and whitespace. Writes quote_checks.json and prints one line per company. Spends a little:
one /contents call per distinct URL.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from pathlib import Path

import httpx


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"[‘’“”'\"`]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def evidence(company: dict) -> list[tuple[str, str, str]]:
    """(what, url, quote) for every cited item that carries a quote."""
    items = [(f"gate:{g.get('gate')}", g.get("url", ""), g.get("quote", "")) for g in company["gates"]]
    for key in ("builds_in_house", "current_competitor_product", "contract_timing"):
        found = company.get(key) or {}
        items.append((key, found.get("url", ""), found.get("quote", "")))
    for signal in company.get("dissatisfaction") or []:
        items.append(("dissatisfaction", signal.get("url", ""), signal.get("quote", "")))
    return [(what, url, quote) for what, url, quote in items if url and quote.strip()]


def fetch(client: httpx.Client, urls: list[str]) -> dict[str, str]:
    pages: dict[str, str] = {}
    for start in range(0, len(urls), 10):
        batch = urls[start : start + 10]
        body = {"urls": batch, "text": True, "livecrawl": "fallback"}
        response = client.post("/contents", json=body)
        for result in response.json().get("results", []):
            pages[result.get("url") or result.get("id")] = result.get("text") or ""
        for url in batch:
            pages.setdefault(url, "")
    return pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()

    companies = (json.loads((args.run / "companies.json").read_text()) or {}).get("companies", [])
    cited = {c["name"]: evidence(c) for c in companies}
    urls = sorted({url for items in cited.values() for _, url, _ in items})
    headers = {"x-api-key": os.environ["CLUE_EXA_API_KEY"]}
    with httpx.Client(base_url="https://api.exa.ai", headers=headers, timeout=120) as client:
        pages = fetch(client, urls)

    report = []
    for company in companies:
        rows = []
        for what, url, quote in cited[company["name"]]:
            page = pages.get(url, "")
            status = "no_page" if not page else ("found" if fold(quote) in fold(page) else "not_found")
            rows.append({"what": what, "url": url, "quote": quote, "status": status})
        found = sum(r["status"] == "found" for r in rows)
        print(f"{company['name']} [{company.get('priority')}]: {found}/{len(rows)} quotes on page")
        for row in rows:
            if row["status"] != "found":
                print(f"   {row['status']:9} {row['what']:28} {row['url'][:90]}")
        report.append({"company": company["name"], "checks": rows})
    total = sum(len(r["checks"]) for r in report)
    found = sum(row["status"] == "found" for r in report for row in r["checks"])
    print(f"\nall: {found}/{total} quotes found on their pages ({len(urls)} pages fetched)")
    (args.run / "quote_checks.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
