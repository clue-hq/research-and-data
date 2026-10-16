"""The fixed request templates of the onboarding lane (ARV2-ONBOARDING-PLAN.md §4).

Behaviour lives in the system prompt, shape lives in the output schema (Exa's own rule). Every
template here is a pure function or constant: the driver (O3) and the evidence tool (O4) pass them
to :class:`~clue_api.arv2.exa_client.ExaClient` and never author a schema of their own.

Three of the four are **Agent** requests (full JSON Schema allowed). The persona-evidence one is a
``/search`` deep-reasoning request and must stay within Exa's documented limits for that surface:
nesting depth 2, ten properties, no citation fields (grounding is returned separately).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

__all__ = [
    "COMPANY_OVERVIEW_SYSTEM_PROMPT",
    "CUSTOMER_REVIEWS_SYSTEM_PROMPT",
    "EXISTING_CUSTOMERS_SYSTEM_PROMPT",
    "PERSONA_EVIDENCE_SYSTEM_PROMPT",
    "PRODUCT_RESEARCH_SYSTEM_PROMPT",
    "company_overview_output_schema",
    "company_overview_query",
    "customer_reviews_output_schema",
    "customer_reviews_query",
    "existing_customers_output_schema",
    "existing_customers_query",
    "persona_evidence_output_schema",
    "product_research_output_schema",
    "product_research_query",
]


def _nullable(kind: str, **extra: Any) -> dict[str, Any]:
    return {"type": [kind, "null"], **extra}


def _string_list(max_items: int, description: str | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "array", "maxItems": max_items, "items": {"type": "string"}}
    if description:
        node["items"]["description"] = description
    return node


# -- 4.2 company overview (ARV2-COMPANY-OVERVIEW-CONTRACT.md §2; live-validated 2026-09-07) -------

_COMPANY_OVERVIEW_QUERY = """\
Research {company} and create a comprehensive report covering these areas:

**==The Origin Story==**

- How did this company start? What problem were they solving?
- Who are the founders? What's their background and previous experience?
- Early funding, initial customers, and first product iterations

**==The Business Reality==**

- How does this company make money? What's their revenue model?
- Are they profitable? What's their financial trajectory?
- Who funds them? Latest valuation and investor expectations

**==What They Actually Do==**

- Current products and services – skip the marketing fluff
- How their technology works under the hood
- Key features that matter to users
- Product evolution and major pivots

**==The Market Position==**

- Who are their main competitors? How do they stack up?
- What's their competitive advantage? Is it defensible?
- Market size, share, and growth potential
- Target customers and use cases

**==The Customer Reality==**

- Who actually uses this? Customer segments and personas
- Positive reviews and success stories
- Complaints, negative feedback, and common problems
- Customer retention and satisfaction data

**==The People==**

- Current leadership team and key employees
- Company culture and employee reviews
- Team size, hiring patterns, and organizational structure

**==The Problems==**

- What criticism do they face? Industry controversies
- Failed products or initiatives
- Operational challenges and technical debt

**==The Future==**

- Product roadmap and strategic direction
- Market trends that help or hurt them
- Partnerships, acquisitions, and expansion plans
- Regulatory risks and opportunities

**==Recent Context==**

- Latest news, announcements, and developments
- Industry changes affecting the company
- Geopolitical pressures and international strategy

company name is {company}"""


def company_overview_query(company_name: str) -> str:
    """The nine-section query as run on 2026-09-07; the schema is the filter on what comes back."""
    return _COMPANY_OVERVIEW_QUERY.format(company=company_name)


COMPANY_OVERVIEW_SYSTEM_PROMPT = (
    "Prefer the company's own domain first, then press and case studies, then third-party "
    "sources. Every section states where each fact came from. Quote the company's own phrasing "
    "for its value proposition and any customer count. Do not enumerate individual products; "
    "another document owns the catalog. Do not reproduce customer reviews; another document owns "
    "them. If a fact cannot be established, leave the field null and add it to not_found. Never "
    "estimate silently; label any estimate as an estimate inside the text."
)


def company_overview_output_schema() -> dict[str, Any]:
    """ARV2-COMPANY-OVERVIEW-CONTRACT.md §2.3, verbatim."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["facts", "sections", "competitors", "named_customers", "not_found"],
        "properties": {
            "facts": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "legal_name": _nullable("string"),
                    "website": _nullable("string", format="uri"),
                    "founded_year": _nullable("integer"),
                    "headquarters": _nullable("string"),
                    "employee_range": _nullable(
                        "string",
                        description="e.g. 51-200, as publicly stated or estimated; say which",
                    ),
                    "funding_total_usd": _nullable("number"),
                    "latest_round": _nullable(
                        "string", description="round name, amount, date, lead investor"
                    ),
                    "investors": _string_list(15),
                    "revenue_model": _nullable(
                        "string",
                        description=(
                            "how they charge: per seat, per encounter, platform fee, services"
                        ),
                    ),
                    "pricing_posture": _nullable(
                        "string",
                        description="published prices, quote-only, freemium, enterprise-only",
                    ),
                    "industries_served": _string_list(10),
                    "geographies": _string_list(10),
                    "customer_count_claim": _nullable(
                        "string",
                        description=(
                            "the company's own stated number, verbatim, with where it was stated"
                        ),
                    ),
                    "regulatory_posture": _nullable(
                        "string",
                        description=(
                            "certifications and compliance claims relevant to buyers, "
                            "e.g. HIPAA, SOC 2, BAA availability"
                        ),
                    ),
                },
            },
            "sections": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "origin_story",
                    "business_model",
                    "positioning",
                    "market_position",
                    "customer_segments",
                    "leadership",
                    "recent_context",
                ],
                "properties": {
                    "origin_story": {
                        "type": "string",
                        "description": (
                            "Markdown. Founding problem, founders and their prior experience, "
                            "first customers and early product."
                        ),
                    },
                    "business_model": {
                        "type": "string",
                        "description": (
                            "Markdown. How they make money, pricing posture, funding trajectory. "
                            "No valuation speculation."
                        ),
                    },
                    "positioning": {
                        "type": "string",
                        "description": (
                            "Markdown. Value proposition in the company's own words, the "
                            "differentiators they claim, and the portfolio described in one "
                            "paragraph. Do NOT list individual products; another document owns "
                            "the catalog."
                        ),
                    },
                    "market_position": {
                        "type": "string",
                        "description": (
                            "Markdown. Main competitors and how the company stacks up, "
                            "defensibility, market size and growth where sourced."
                        ),
                    },
                    "customer_segments": {
                        "type": "string",
                        "description": (
                            "Markdown. Who buys and who uses it: segments, roles, organisation "
                            "types and sizes, use cases. Cite case studies. Do not reproduce "
                            "reviews; a separate document owns them."
                        ),
                    },
                    "leadership": {
                        "type": "string",
                        "description": (
                            "Markdown. Current leadership team with titles. No employee reviews "
                            "or culture commentary."
                        ),
                    },
                    "recent_context": {
                        "type": "string",
                        "description": (
                            "Markdown. Announcements, partnerships, expansion, hiring signals "
                            "from the last 12 months, each dated."
                        ),
                    },
                },
            },
            "competitors": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "how_they_compare"],
                    "properties": {
                        "name": {"type": "string"},
                        "website": _nullable("string", format="uri"),
                        "how_they_compare": {
                            "type": "string",
                            "description": "one or two sentences, sourced",
                        },
                    },
                },
            },
            "named_customers": {
                "type": "array",
                "maxItems": 30,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "segment": _nullable("string"),
                        "evidence_kind": {
                            "type": "string",
                            "enum": ["case_study", "logo_wall", "press", "review", "other"],
                        },
                    },
                },
            },
            "not_found": _string_list(
                20, "an item that was searched for and could not be established, stated plainly"
            ),
        },
    }


# -- 4.3 customer reviews ----------------------------------------------------------------------


def customer_reviews_query(company_name: str, domain: str) -> str:
    return (
        f"Find what customers say about {company_name} ({domain}) as a vendor: reviews on G2, "
        "Capterra, Trustpilot, app marketplaces, EHR/partner marketplaces, Reddit and professional "
        "communities, plus the company's own case studies and testimonials. Separate praise from "
        "complaints. Quote verbatim."
    )


CUSTOMER_REVIEWS_SYSTEM_PROMPT = (
    "Quote every review verbatim, at most 40 words, with its URL, platform, rating and date "
    "when shown. Record the reviewer's role and organisation type; never the reviewer's name. "
    "Name a person only when the vendor's own case study names them, and then with their title. "
    "Separate praise from complaints honestly; say plainly when the corpus is thin. Leave a field "
    "null and add it to not_found rather than estimate."
)


def customer_reviews_output_schema() -> dict[str, Any]:
    """ARV2-ONBOARDING-PLAN.md §4.3."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "summary",
            "themes_positive",
            "themes_negative",
            "reviews",
            "case_studies",
            "not_found",
        ],
        "properties": {
            "summary": {
                "type": "string",
                "description": (
                    "Markdown, 1–2 paragraphs: overall sentiment, volume and where reviews live. "
                    "Say plainly when the corpus is thin."
                ),
            },
            "themes_positive": _string_list(8),
            "themes_negative": _string_list(8),
            "reviews": {
                "type": "array",
                "maxItems": 40,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["platform", "quote", "sentiment", "source_url"],
                    "properties": {
                        "platform": {"type": "string"},
                        "source_url": {"type": "string", "format": "uri"},
                        "quote": {"type": "string", "description": "verbatim, 40 words max"},
                        "sentiment": {"type": "string", "enum": ["positive", "mixed", "negative"]},
                        "rating": _nullable("number"),
                        "date": _nullable("string"),
                        "reviewer_role": _nullable("string"),
                        "reviewer_org_type": _nullable(
                            "string",
                            description=(
                                "e.g. multi-specialty group, 20 clinicians. "
                                "Never the reviewer's name."
                            ),
                        ),
                        "product_mentioned": _nullable("string"),
                    },
                },
            },
            "case_studies": {
                "type": "array",
                "maxItems": 15,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["customer", "source_url"],
                    "properties": {
                        "customer": {"type": "string"},
                        "source_url": {"type": "string", "format": "uri"},
                        "outcome_claim": _nullable(
                            "string",
                            description="the stated result, verbatim, e.g. '38% fewer no-shows'",
                        ),
                        "named_person": _nullable(
                            "string",
                            description=(
                                "only if the seller's own case study names them, with title"
                            ),
                        ),
                    },
                },
            },
            "not_found": _string_list(10),
        },
    }


# -- existing customers (spec 2026-10-16-discovery-excludes-seller-customers §4.1) ----------------


def existing_customers_query(company_name: str, domain: str) -> str:
    return (
        f"Find every company that is an existing customer of {company_name} ({domain}). First work "
        f"out what buying from {company_name} means. Then read {company_name}'s own site: its "
        "sitemap, customers and case-study pages, press releases, news and logo walls. Then search "
        "announcements by buyers themselves, news coverage, reviews, and the industry's own "
        "purchase trackers or registries. List every customer found, with every website domain it "
        "uses."
    )


EXISTING_CUSTOMERS_SYSTEM_PROMPT = (
    "List only companies that buy or use the product, directly or through a buying coalition or "
    "marketplace; name the coalition or marketplace in via. Leave out investors, grant-givers, "
    "registries, technology and integration partners, suppliers and competitors, even when they "
    "appear on the same logo wall. Every customer must be named on a page you found; never infer a "
    "customer from its industry. Give every website domain the customer uses, a group's brand "
    "domains as well as its corporate one. Check that each domain's website is really that "
    'company; otherwise leave it out. Mark a sweeping claim such as "300+ brands including X" as '
    "weak_mention. Quote verbatim, at most 40 words. Also list every domain the seller itself uses "
    "in seller_domains."
)


def existing_customers_output_schema() -> dict[str, Any]:
    """Spec §4.1. An Agent request, so the full JSON Schema is allowed; page citations come back in
    the run's ``grounding``, never as fields here."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["customers", "seller_domains"],
        "properties": {
            "customers": {
                "type": "array",
                "maxItems": 300,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "domains", "relationship", "evidence_kind", "quote"],
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "the customer company's name as written on the page",
                        },
                        "domains": _string_list(
                            10, "a website domain the customer uses, e.g. marriott.com"
                        ),
                        "relationship": {
                            "type": "string",
                            "enum": [
                                "direct",
                                "through_coalition",
                                "through_marketplace",
                                "weak_mention",
                            ],
                        },
                        "via": _nullable(
                            "string", description="the coalition or marketplace, when there is one"
                        ),
                        "evidence_kind": {
                            "type": "string",
                            "enum": [
                                "logo_wall",
                                "case_study",
                                "testimonial",
                                "press",
                                "review",
                                "tracker",
                                "other",
                            ],
                        },
                        "quote": {"type": "string", "description": "verbatim, 40 words max"},
                    },
                },
            },
            "seller_domains": _string_list(10, "a website domain the seller itself uses"),
        },
    }


# -- 4.4 per-product research --------------------------------------------------------------------


def product_research_query(
    *,
    product_name: str,
    company_name: str,
    official_url: str | None,
    sibling_names: Sequence[str],
) -> str:
    parts = [
        f"Research the product {product_name} by {company_name}: what it does, its explicitly "
        "stated capabilities, use cases, who it is for, integrations, published pricing and "
        "packaging, differentiators, competitors for this product specifically, and customer "
        "evidence (case studies, testimonials, outcomes) that names this product."
    ]
    if official_url:
        parts.append(f"Its official page is {official_url}; read it first and cite it.")
    if sibling_names:
        parts.append(
            "This company also sells "
            + ", ".join(sibling_names)
            + "; this report is NOT about those — mention them only where "
            f"{product_name} integrates with or bundles them."
        )
    return " ".join(parts)


PRODUCT_RESEARCH_SYSTEM_PROMPT = (
    "Describe only this product. A capability is one explicitly stated capability in the "
    "company's own words, never an inference. Pricing is null unless published for this product. "
    "Competitors are for this product, not the company. Leave a field null or empty and add the "
    "gap to not_found rather than fill it from a sibling product or a guess."
)


def product_research_output_schema() -> dict[str, Any]:
    """ARV2-ONBOARDING-PLAN.md §4.4 — the old lane's nine product topics as the vocabulary."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "overview",
            "capabilities",
            "use_cases",
            "integrations",
            "pricing",
            "differentiators",
            "competitors",
            "customer_evidence",
            "not_found",
        ],
        "properties": {
            "overview": {
                "type": "string",
                "description": "Markdown, 1–2 paragraphs, this product only.",
            },
            "capabilities": _string_list(
                15, "one explicitly stated capability, in the company's words"
            ),
            "use_cases": _string_list(10),
            "integrations": _string_list(20),
            "pricing": _nullable(
                "string",
                description=(
                    "published prices and packaging for this product only; null if not published"
                ),
            ),
            "differentiators": _string_list(8),
            "competitors": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "website": _nullable("string", format="uri"),
                        "how_they_compare": _nullable("string"),
                    },
                },
            },
            "customer_evidence": {
                "type": "array",
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["customer", "source_url"],
                    "properties": {
                        "customer": {"type": "string"},
                        "source_url": {"type": "string", "format": "uri"},
                        "outcome_claim": _nullable("string"),
                    },
                },
            },
            "who_it_is_for": _nullable(
                "string",
                description="buyer and user roles, organisation types, in the company's words",
            ),
            "not_found": _string_list(10),
        },
    }


# -- 4.5 persona evidence (a /search deep-reasoning request: depth ≤ 2, ≤ 10 properties) ---------

PERSONA_EVIDENCE_SYSTEM_PROMPT = (
    "Prefer first-person accounts by people in the named role: forum posts, interviews, "
    "reviews, talks, job postings. Never paraphrase a quote; return it verbatim with its "
    "speaker's role. Return nothing rather than a weak match."
)


def persona_evidence_output_schema() -> dict[str, Any]:
    """Five properties, two levels; citations come back in ``output.grounding``, never here."""
    return {
        "type": "object",
        "required": ["passages"],
        "properties": {
            "passages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["quote", "speaker_role"],
                    "properties": {
                        "quote": {"type": "string", "description": "verbatim, 60 words max"},
                        "speaker_role": {
                            "type": "string",
                            "description": "the speaker's role/title as stated or evident",
                        },
                        "org_type": {"type": "string"},
                        "topic": {
                            "type": "string",
                            "description": "pain | language | tooling | trigger | objection",
                        },
                    },
                },
            }
        },
    }
