"""Provider response → KnowledgeDocument: the pure mappers of the onboarding lane.

Front matter is the machine contract (ARV2-COMPANY-OVERVIEW-CONTRACT.md §3.1,
ARV2-PRODUCT-CATALOG-CONTRACT.md §4); the body is the human-readable render under **fixed**
headings in a fixed order — product vocabulary, never model-written. A heading the model wrote
inside a section is demoted one level so the fixed ones stay the only H2s. ``not_found`` is
always rendered: an empty, named gap is a correct output.

Everything here is pure. ``cost`` on a document is the settling call's cost when the document
was built from a call, ``None`` when it was not (the import guard's documented exception).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import yaml

from clue_api.arv2.calls import CallCost
from clue_api.arv2.customer_domains import DomainCheck
from clue_api.arv2.exa_client import ExaAgentRun, ExaDeepResult

__all__ = [
    "KnowledgeDocument",
    "company_overview_document",
    "customer_reviews_document",
    "existing_customers_document",
    "demote_headings",
    "product_catalog_document",
    "product_research_document",
    "render_markdown",
    "slugify",
    "sources_by_field",
]

_HEADING = re.compile(r"^(#{1,5})(?=\s)", re.MULTILINE)
_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class KnowledgeDocument:
    kind: str
    folder: str
    path: str
    front_matter: dict[str, Any]
    body: str
    cost: CallCost | None


def render_markdown(document: KnowledgeDocument) -> str:
    front = yaml.safe_dump(
        document.front_matter, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    return f"---\n{front}---\n\n{document.body}"


def demote_headings(markdown: str, by: int = 1) -> str:
    return _HEADING.sub(lambda m: m.group(1) + "#" * by, markdown)


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug or "untitled"


def sources_by_field(grounding: Sequence[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in grounding:
        if not isinstance(row, dict) or not isinstance(row.get("field"), str):
            continue
        citations = [
            {"url": c.get("url"), "title": c.get("title")}
            for c in (row.get("citations") or [])
            if isinstance(c, dict) and isinstance(c.get("url"), str)
        ]
        confidence = row.get("confidence")
        out[row["field"]] = {
            "citations": citations,
            "confidence": confidence if isinstance(confidence, str) else None,
        }
    return out


# -- shared pieces ----------------------------------------------------------------------------


def _iso(as_of: date) -> str:
    return as_of.isoformat()


def _structured(run: ExaAgentRun) -> Mapping[str, Any]:
    return run.structured if isinstance(run.structured, dict) else {}


def _run_header(run: ExaAgentRun, *, kind: str, as_of: date, **scope: Any) -> dict[str, Any]:
    header: dict[str, Any] = {"kind": kind, "as_of": _iso(as_of), **scope}
    header["provider_run_id"] = run.run_id
    header["status"] = "ready" if run.status == "completed" else "failed"
    if run.status != "completed":
        header["error"] = {"code": run.error_code, "message": run.error_message}
    return header


def _run_footer(run: ExaAgentRun) -> dict[str, Any]:
    searches = run.usage.get("searches") if isinstance(run.usage, dict) else None
    return {
        "sources": sources_by_field(run.grounding),
        "cost_usd": str(run.cost_usd) if run.cost_usd is not None else None,
        "searches": int(searches) if isinstance(searches, int) else 0,
    }


def _section(title: str, body: str | None) -> str:
    text = (body or "").strip()
    content = demote_headings(text) if text else "_Not established._"
    return f"## {title}\n\n{content}\n"


def _list_section(title: str, items: Sequence[Any], empty: str) -> str:
    if not items:
        return f"## {title}\n\n_{empty}_\n"
    return f"## {title}\n\n" + "".join(f"- {item}\n" for item in items)


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    def cell(value: Any) -> str:
        return "" if value is None else str(value).replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def _sources_section(sources: Mapping[str, Mapping[str, Any]]) -> str:
    if not sources:
        return "## Sources\n\n_No field-level grounding was returned._\n"
    lines = ["## Sources", ""]
    for field, entry in sources.items():
        label = field.removeprefix("structured.")
        lines.append(f"- **{label}** ({entry.get('confidence') or 'unrated'})")
        for citation in entry.get("citations", []):
            title = citation.get("title") or citation.get("url")
            lines.append(f"  - [{title}]({citation.get('url')})")
    return "\n".join(lines) + "\n"


def _failure_note(run: ExaAgentRun) -> str:
    # The suffix is appended, never stripped back off: ``rstrip(" —")`` strips a character
    # *set*, so a provider message that legitimately ends in an em dash would lose it.
    note = f"- Research run did not complete: `{run.error_code or run.status}`"
    if run.error_message:
        note += f" — {run.error_message}"
    return note


# -- 4.2 company overview ----------------------------------------------------------------------

_FACT_LABELS: tuple[tuple[str, str], ...] = (
    ("legal_name", "Legal name"),
    ("website", "Website"),
    ("founded_year", "Founded"),
    ("headquarters", "Headquarters"),
    ("employee_range", "Employees"),
    ("funding_total_usd", "Funding total (USD)"),
    ("latest_round", "Latest round"),
    ("investors", "Investors"),
    ("revenue_model", "Revenue model"),
    ("pricing_posture", "Pricing posture"),
    ("industries_served", "Industries served"),
    ("geographies", "Geographies"),
    ("customer_count_claim", "Customer count (company claim)"),
    ("regulatory_posture", "Regulatory posture"),
)


def company_overview_document(
    run: ExaAgentRun, *, company_domain: str, as_of: date
) -> KnowledgeDocument:
    data = _structured(run)
    raw_facts = data.get("facts")
    facts: Mapping[str, Any] = raw_facts if isinstance(raw_facts, dict) else {}
    raw_sections = data.get("sections")
    sections: Mapping[str, Any] = raw_sections if isinstance(raw_sections, dict) else {}
    competitors = [c for c in (data.get("competitors") or []) if isinstance(c, dict)]
    customers = [c for c in (data.get("named_customers") or []) if isinstance(c, dict)]
    not_found = [n for n in (data.get("not_found") or []) if isinstance(n, str)]

    front = _run_header(run, kind="company-overview", as_of=as_of, company_domain=company_domain)
    front.update(
        {
            "facts": dict(facts),
            "competitors": competitors,
            "named_customers": customers,
            "not_found": not_found,
            **_run_footer(run),
        }
    )

    fact_lines = [
        f"- **{label}:** {', '.join(map(str, value)) if isinstance(value, list) else value}"
        for key, label in _FACT_LABELS
        for value in [facts.get(key)]
        if value not in (None, "", [])
    ]
    gaps = list(not_found)
    if run.status != "completed":
        gaps.append(_failure_note(run))
    body = "\n".join(
        [
            "# Company overview",
            "",
            "\n".join(fact_lines) if fact_lines else "_No facts were established._",
            "",
            _section("Origin story", sections.get("origin_story")),
            _section("Business model", sections.get("business_model")),
            _section("Positioning", sections.get("positioning")),
            _section("Market position", sections.get("market_position")),
            "## Competitors\n\n"
            + (
                _table(
                    ("Name", "Website", "How they compare"),
                    [
                        (c.get("name"), c.get("website"), c.get("how_they_compare"))
                        for c in competitors
                    ],
                )
                if competitors
                else "_Not established._\n"
            ),
            _section("Customer segments", sections.get("customer_segments")),
            "## Named customers\n\n"
            + (
                _table(
                    ("Name", "Segment", "Evidence"),
                    [(c.get("name"), c.get("segment"), c.get("evidence_kind")) for c in customers],
                )
                if customers
                else "_Not established._\n"
            ),
            _section("Leadership", sections.get("leadership")),
            _section("Recent context", sections.get("recent_context")),
            _list_section("Not established", gaps, "Nothing was left unestablished."),
            _sources_section(front["sources"]),
        ]
    )
    return KnowledgeDocument(
        kind="company-overview",
        folder="company",
        path="company/overview.md",
        front_matter=front,
        body=body,
        cost=run.cost,
    )


# -- 4.3 customer reviews ----------------------------------------------------------------------


def customer_reviews_document(
    run: ExaAgentRun, *, company_domain: str, as_of: date
) -> KnowledgeDocument:
    data = _structured(run)
    reviews = [r for r in (data.get("reviews") or []) if isinstance(r, dict)]
    case_studies = [c for c in (data.get("case_studies") or []) if isinstance(c, dict)]
    positive = [r for r in reviews if r.get("sentiment") == "positive"]
    negative = [r for r in reviews if r.get("sentiment") in ("negative", "mixed")]
    not_found = [n for n in (data.get("not_found") or []) if isinstance(n, str)]

    front = _run_header(run, kind="customer-reviews", as_of=as_of, company_domain=company_domain)
    front.update(
        {
            "themes_positive": list(data.get("themes_positive") or []),
            "themes_negative": list(data.get("themes_negative") or []),
            "reviews": reviews,
            "case_studies": case_studies,
            "not_found": not_found,
            **_run_footer(run),
        }
    )

    def quote_block(items: Sequence[Mapping[str, Any]]) -> str:
        if not items:
            return "_Not established._\n"
        out = []
        for r in items:
            who = " · ".join(
                str(x) for x in (r.get("reviewer_role"), r.get("reviewer_org_type")) if x
            )
            meta = " · ".join(
                str(x) for x in (r.get("platform"), r.get("rating"), r.get("date")) if x
            )
            out.append(
                f"> {r.get('quote', '').strip()}\n>\n> — {who or 'reviewer'} ({meta}) "
                f"[{r.get('platform')}]({r.get('source_url')})\n"
            )
        return "\n".join(out)

    gaps = list(not_found)
    if run.status != "completed":
        gaps.append(_failure_note(run))
    body = "\n".join(
        [
            "# Customer reviews",
            "",
            _section("Summary", data.get("summary")),
            _list_section("Themes: praise", front["themes_positive"], "None established."),
            _list_section("Themes: complaints", front["themes_negative"], "None established."),
            "## What customers praise\n\n" + quote_block(positive),
            "## What customers complain about\n\n" + quote_block(negative),
            "## Case studies\n\n"
            + (
                _table(
                    ("Customer", "Outcome claim", "Named person", "Source"),
                    [
                        (
                            c.get("customer"),
                            c.get("outcome_claim"),
                            c.get("named_person"),
                            c.get("source_url"),
                        )
                        for c in case_studies
                    ],
                )
                if case_studies
                else "_Not established._\n"
            ),
            _list_section("Not established", gaps, "Nothing was left unestablished."),
            _sources_section(front["sources"]),
        ]
    )
    return KnowledgeDocument(
        kind="customer-reviews",
        folder="proof",
        path="proof/customer-reviews.md",
        front_matter=front,
        body=body,
        cost=run.cost,
    )


# -- existing customers (spec 2026-10-16-discovery-excludes-seller-customers §4.3) ---------------


def _customer_source(grounding: Sequence[Any], index: int) -> str | None:
    """The first page Exa cited for customer ``index`` (its quote first, then its name)."""
    for field in (f"structured.customers[{index}].quote", f"structured.customers[{index}].name"):
        for row in grounding:
            if isinstance(row, dict) and row.get("field") == field:
                for citation in row.get("citations") or []:
                    if isinstance(citation, dict) and citation.get("url"):
                        return str(citation["url"])
    return None


def existing_customers_document(
    run: ExaAgentRun,
    *,
    company_domain: str,
    as_of: date,
    checks: Mapping[str, DomainCheck],
) -> KnowledgeDocument:
    """``proof/customers.md``. The list lives in the body only: the Brand-context editor copies a
    document's old front matter forward when a person edits its body, so a second copy there would
    silently ignore their correction. The front matter carries the run header and sources."""
    data = _structured(run)
    customers = [
        (index, c) for index, c in enumerate(data.get("customers") or []) if isinstance(c, dict)
    ]
    seller_domains = [d for d in (data.get("seller_domains") or []) if isinstance(d, str)]
    front = _run_header(run, kind="existing-customers", as_of=as_of, company_domain=company_domain)
    front.update(_run_footer(run))

    def domains(customer: Mapping[str, Any]) -> str:
        # Only the domains, so the Head of ABM can copy the cell into a brief's ``exclude`` as is.
        return ", ".join(str(domain) for domain in customer.get("domains") or [])

    def check(customer: Mapping[str, Any]) -> str:
        """``confirmed`` when every domain's homepage named the company; otherwise each domain
        that did not, with the page title that explains why."""
        doubts = []
        for domain in customer.get("domains") or []:
            found = checks.get(domain)
            if found is not None and found.status == "unconfirmed":
                doubts.append(f"{domain}: unconfirmed ({found.title or 'no answer'})")
        return "; ".join(doubts) or "confirmed"

    def how(customer: Mapping[str, Any]) -> str:
        via = customer.get("via")
        return (
            f"{customer.get('relationship')} via {via}"
            if via
            else str(customer.get("relationship"))
        )

    rows = [
        (
            c.get("name"),
            domains(c),
            check(c),
            how(c),
            c.get("evidence_kind"),
            c.get("quote"),
            _customer_source(run.grounding, index),
        )
        for index, c in sorted(customers, key=lambda pair: str(pair[1].get("name") or "").lower())
    ]
    table = (
        _table(
            ("Customer", "Domains", "Domain check", "How they buy", "Evidence", "Quote", "Source"),
            rows,
        )
        if rows
        else "_Not established._\n"
    )
    gaps = [_failure_note(run)] if run.status != "completed" else []
    body = "\n".join(
        [
            "# Existing customers",
            "",
            "## Customers\n\n" + table,
            "Seller's own domains: " + (", ".join(seller_domains) or company_domain) + "\n",
            _list_section("Not established", gaps, "Nothing was left unestablished."),
            _sources_section(front["sources"]),
        ]
    )
    return KnowledgeDocument(
        kind="existing-customers",
        folder="proof",
        path="proof/customers.md",
        front_matter=front,
        body=body,
        cost=run.cost,
    )


# -- 4.4 per-product research --------------------------------------------------------------------


def product_research_document(
    run: ExaAgentRun, *, product_id: str, product_name: str, product_slug: str, as_of: date
) -> KnowledgeDocument:
    data = _structured(run)
    competitors = [c for c in (data.get("competitors") or []) if isinstance(c, dict)]
    evidence = [c for c in (data.get("customer_evidence") or []) if isinstance(c, dict)]
    not_found = [n for n in (data.get("not_found") or []) if isinstance(n, str)]

    front = _run_header(
        run, kind="product-research", as_of=as_of, product_id=product_id, product_name=product_name
    )
    front.update(
        {
            key: data.get(key)
            for key in (
                "capabilities",
                "use_cases",
                "integrations",
                "pricing",
                "differentiators",
                "who_it_is_for",
            )
        }
    )
    front.update(
        {
            "competitors": competitors,
            "customer_evidence": evidence,
            "not_found": not_found,
            **_run_footer(run),
        }
    )

    gaps = list(not_found)
    if run.status != "completed":
        gaps.append(_failure_note(run))
    body = "\n".join(
        [
            f"# {product_name}",
            "",
            _section("Overview", data.get("overview")),
            _list_section("Capabilities", data.get("capabilities") or [], "Not established."),
            _list_section("Use cases", data.get("use_cases") or [], "Not established."),
            _section("Who it is for", data.get("who_it_is_for")),
            _list_section("Integrations", data.get("integrations") or [], "Not established."),
            _section("Pricing", data.get("pricing")),
            _list_section("Differentiators", data.get("differentiators") or [], "Not established."),
            "## Competitors\n\n"
            + (
                _table(
                    ("Name", "Website", "How they compare"),
                    [
                        (c.get("name"), c.get("website"), c.get("how_they_compare"))
                        for c in competitors
                    ],
                )
                if competitors
                else "_Not established._\n"
            ),
            "## Customer evidence\n\n"
            + (
                _table(
                    ("Customer", "Outcome claim", "Source"),
                    [
                        (c.get("customer"), c.get("outcome_claim"), c.get("source_url"))
                        for c in evidence
                    ],
                )
                if evidence
                else "_Not established._\n"
            ),
            _list_section("Not established", gaps, "Nothing was left unestablished."),
            _sources_section(front["sources"]),
        ]
    )
    return KnowledgeDocument(
        kind="product-research",
        folder="product",
        path=f"product/{product_slug}.md",
        front_matter=front,
        body=body,
        cost=run.cost,
    )


# -- 4.1 product catalog (ARV2-PRODUCT-CATALOG-CONTRACT.md §4) -----------------------------------

_CATALOG_KEYS = (
    "name",
    "short_description",
    "offering_kind",
    "family",
    "lifecycle",
    "official_url",
)


def product_catalog_document(
    result: ExaDeepResult, *, company_domain: str, as_of: date
) -> KnowledgeDocument:
    parsed = result.output_object if isinstance(result.output_object, dict) else {}
    raw_products = [p for p in (parsed.get("products") or []) if isinstance(p, dict)]
    by_field = sources_by_field(result.grounding if isinstance(result.grounding, list) else [])

    products: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_products):
        name = raw.get("name")
        description = raw.get("short_description")
        if not (
            isinstance(name, str)
            and name.strip()
            and isinstance(description, str)
            and description.strip()
        ):
            dropped.append({"index": index, "reason": "missing name or short_description"})
            continue
        prefix = f"products[{index}]"
        rows = [
            entry
            for field, entry in by_field.items()
            if field == prefix or field.startswith(prefix + ".")
        ]
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in rows:
            for citation in entry["citations"]:
                if citation["url"] not in seen:
                    seen.add(citation["url"])
                    sources.append(citation)
        confidences = [e["confidence"] for e in rows if e.get("confidence") in _CONFIDENCE_RANK]
        entry = {key: raw.get(key) for key in _CATALOG_KEYS}
        entry["aliases"] = []
        entry["sources"] = sources
        entry["grounding_confidence"] = (
            min(confidences, key=_CONFIDENCE_RANK.__getitem__) if confidences else None
        )
        products.append(entry)

    front: dict[str, Any] = {
        "kind": "product-catalog",
        "as_of": _iso(as_of),
        "company_domain": company_domain,
        "provider_request_id": result.request_id,
        "coverage_note": parsed.get("coverage_note"),
        "products": products,
        "dropped": dropped,
        "cost_usd": str(result.cost_usd) if result.cost_usd is not None else None,
    }
    lines = ["# Product catalog", ""]
    if front["coverage_note"]:
        lines += [f"_Coverage: {front['coverage_note']}_", ""]
    if products:
        lines.append(
            _table(
                ("Name", "Kind", "Family", "Lifecycle", "Official page", "Description"),
                [
                    (
                        p["name"],
                        p["offering_kind"],
                        p["family"],
                        p["lifecycle"],
                        p["official_url"],
                        p["short_description"],
                    )
                    for p in products
                ],
            )
        )
    else:
        lines.append("_No products were established._\n")
    if dropped:
        lines += ["## Dropped by the mapper", ""]
        for d in dropped:
            raw = raw_products[d["index"]]
            lines.append(f"- entry {d['index']}: {d['reason']} — `{raw}`")
        lines.append("")
    lines.append(_sources_section(by_field))
    return KnowledgeDocument(
        kind="product-catalog",
        folder="product",
        path="product/catalog.md",
        front_matter=front,
        body="\n".join(lines),
        cost=result.cost,
    )
