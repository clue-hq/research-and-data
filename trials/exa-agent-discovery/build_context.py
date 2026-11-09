"""Build one discovery trial's context from a seller's brand files.

Reads the confirmed ICP document (its front matter's hard gates and the body's one-line summary,
offer table and rivals line), the product catalog, and the customers table, and writes the
context JSON that run_trial.py fills the prompt with. The output names a customer's companies, so
write it outside the repository.

    uv run python trials/exa-agent-discovery/build_context.py \
        --icp <icp.md> --catalog <catalog.md> --customers <customers.md> \
        --seller-name Illumio --target-count 5 --out <context.json>
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from clue_api.arv2.knowledge_frontmatter import parse_front_matter


def _section(body: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", body, re.M | re.S)
    return match.group(1).strip() if match else ""


def _customers(text: str) -> list[dict[str, object]]:
    rows = []
    for line in _section(text, "Customers").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0] in {"Customer", ""} or set(cells[0]) <= {"-"}:
            continue
        domains = [d.strip() for d in cells[1].split(",") if d.strip()]
        rows.append({"name": cells[0], "domains": domains})
    own = re.search(r"Seller's own domains:\s*(.+)", text)
    if own:
        rows.append({"name": "the seller itself", "domains": [own.group(1).strip()]})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--icp", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--customers", required=True, type=Path)
    parser.add_argument("--seller-name", required=True)
    parser.add_argument("--target-count", type=int, default=5)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    front, body = parse_front_matter(args.icp.read_text())
    catalog, _ = parse_front_matter(args.catalog.read_text())
    rivals = re.search(r"^Rivals:\s*(.+)$", body, re.M)
    context = {
        "seller_name": args.seller_name,
        "seller_offer": " ".join(
            f"{p['name']}: {p['short_description']}" for p in catalog.get("products", [])
        ),
        "icp_summary": "\n\n".join(
            part
            for part in (
                _section(body, "In one line"),
                _section(body, "Company criteria"),
                _section(body, "What " + args.seller_name + " sells them"),
            )
            if part
        ),
        "gates": [
            {"key": g["key"], "rule": g["rule"], "test": g.get("test", "")}
            for g in front["hard_gates"]
        ],
        "competitors": rivals.group(1).strip() if rivals else "",
        "exclude": _customers(args.customers.read_text()),
        "target_count": args.target_count,
        "query": _section(body, "In one line"),
    }
    args.out.write_text(json.dumps(context, indent=2, ensure_ascii=False))
    print(
        f"wrote {args.out}: {len(context['gates'])} gates, {len(context['exclude'])} excluded, "
        f"competitors: {context['competitors'][:80]}"
    )


if __name__ == "__main__":
    main()
