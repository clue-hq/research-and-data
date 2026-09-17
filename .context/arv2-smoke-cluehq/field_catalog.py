"""The REAL registered field keys, read from the platform schema on
origin/platform/comprehensive-account-contact-research (CORE_PACK, RESONANCE_PACK, FACET_PACK,
COMMITTEE_PACK, the icp starter packs, core.CONTACT_PROFESSIONAL_FIELD_KEYS).

Nothing here is invented: a key absent from this catalog must go to PROPOSED FIELDS.
"""

ACCOUNT_FIELDS = {
    "core.account_name": ("str", {"type": "string"}, "Canonical account name observation."),
    "core.primary_domain": ("str", {"type": "string"}, "Primary web domain."),
    "core.company_linkedin_url": ("str", {"type": "string"}, "Public LinkedIn company page URL."),
    "core.industry": ("str", {"type": "string"}, "Primary industry classification."),
    "core.company_about": ("str", {"type": "string"}, "Public company description/about text."),
    "core.employee_count": ("int", {"type": "integer"}, "Total headcount."),
    "core.employee_range": (
        "object",
        {
            "type": "object",
            "required": ["label"],
            "properties": {
                "label": {"type": "string"},
                "min": {"type": "integer"},
                "max": {"type": "integer"},
            },
        },
        "Employee range, used only when exact headcount is unavailable.",
    ),
    "core.hq_location": (
        "object",
        {
            "type": "object",
            "required": ["raw"],
            "properties": {
                "raw": {"type": "string"},
                "city": {"type": "string"},
                "region": {"type": "string"},
                "country": {"type": "string"},
                "country_code": {"type": "string"},
            },
        },
        "Normalized HQ/primary location plus the source's raw value.",
    ),
    "core.annual_revenue": (
        "object",
        {
            "type": "object",
            "required": ["amount", "currency", "as_of", "estimate_kind"],
            "properties": {
                "amount": {"type": "number"},
                "currency": {"type": "string"},
                "as_of": {"type": "string"},
                "estimate_kind": {
                    "type": "string",
                    "enum": ["reported", "provider_estimate", "third_party_estimate"],
                },
            },
        },
        "Annual revenue with currency, as-of date and reported/estimate semantics.",
    ),
    "core.revenue_band": (
        "enum",
        {
            "type": "string",
            "enum": [
                "under_1m",
                "1m_10m",
                "10m_50m",
                "50m_100m",
                "100m_500m",
                "500m_1b",
                "1b_plus",
            ],
        },
        "Bounded revenue band when exact sourced revenue is absent.",
    ),
    "core.company_email": ("str", {"type": "string"}, "Public general company contact email."),
    "core.company_phone": ("str", {"type": "string"}, "Public general company contact phone."),
    "core.primary_tech_stack": (
        "list[str]",
        {"type": "array", "items": {"type": "string"}},
        "Detected primary technologies.",
    ),
    "account.recent_funding": (
        "object",
        {
            "type": "object",
            "required": ["amount_usd"],
            "properties": {"amount_usd": {"type": "number"}, "round": {"type": "string"}},
        },
        "Most recent funding round.",
    ),
    "account.total_funding": (
        "object",
        {
            "type": "object",
            "required": ["amount_usd", "estimate_kind"],
            "properties": {
                "amount_usd": {"type": "number"},
                "estimate_kind": {
                    "type": "string",
                    "enum": ["reported", "provider_estimate", "third_party_estimate"],
                },
            },
        },
        "Total funding in USD with explicit estimate semantics.",
    ),
    "account.hiring_velocity_eng": (
        "number",
        {"type": "number"},
        "Engineering hiring velocity (count of open engineering roles).",
    ),
    "account.operational_pain": ("str", {"type": "string"}, "Synthesized operational pain."),
    "account.strategic_moves": ("str", {"type": "string"}, "Strategic moves / initiatives."),
    "account.resonance.culture": ("str", {"type": "string"}, "Cultural resonance signal."),
    "account.resonance.employee_sentiment": (
        "object",
        {
            "type": "object",
            "required": ["label"],
            "properties": {
                "label": {"type": "string", "enum": ["positive", "neutral", "negative", "mixed"]},
                "polarity": {"type": "number"},
                "summary": {"type": "string"},
            },
        },
        "Aggregate employee sentiment.",
    ),
    "account.resonance.attrition_signal": (
        "object",
        {
            "type": "object",
            "required": ["signal_type"],
            "properties": {
                "signal_type": {"type": "string", "enum": ["morale", "attrition", "layoff"]},
                "direction": {"type": "string", "enum": ["improving", "stable", "worsening"]},
                "summary": {"type": "string"},
            },
        },
        "Morale / attrition / layoff signal.",
    ),
    "account.resonance.eng_blog_tone": (
        "object",
        {
            "type": "object",
            "required": ["tone_label"],
            "properties": {"tone_label": {"type": "string"}, "summary": {"type": "string"}},
        },
        "Tone/voice of the company's engineering or company blog.",
    ),
    "account.resonance.public_frustrations": (
        "list[object]",
        {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["frustration"],
                "properties": {"frustration": {"type": "string"}, "summary": {"type": "string"}},
            },
        },
        "Publicly aired frustrations about the account.",
    ),
    "account.resonance.buying_culture": (
        "object",
        {
            "type": "object",
            "required": ["culture_label"],
            "properties": {"culture_label": {"type": "string"}, "summary": {"type": "string"}},
        },
        "'What it's like to buy here' - procurement culture.",
    ),
}

CONTACT_FIELDS = {
    "core.work_email": ("str", {"type": "string"}, "Selected contact's observed work email."),
    "core.direct_phone": ("str", {"type": "string"}, "Selected contact's observed direct phone."),
    "contact.current_title": ("str", {"type": "string"}, "Current professional title."),
    "contact.job_function": ("str", {"type": "string"}, "Current job function."),
    "contact.job_level": ("str", {"type": "string"}, "Current job level."),
    "contact.current_location": (
        "object",
        {
            "type": "object",
            "properties": {"raw": {"type": "string"}, "country": {"type": "string"}},
        },
        "Current professional location/country.",
    ),
    "contact.persona": (
        "str",
        {
            "type": "string",
            "enum": ["champion", "economic_buyer", "technical_evaluator", "blocker"],
        },
        "Buying-committee persona key (CLOSED enum - only these four values exist).",
    ),
    "contact.role_on_committee": (
        "object",
        {
            "type": "object",
            "required": ["role"],
            "properties": {
                "role": {
                    "type": "string",
                    "enum": ["champion", "economic_buyer", "technical_evaluator", "blocker"],
                },
                "rationale": {"type": "string"},
            },
        },
        "Inferred buying-committee role + plausibility rationale.",
    ),
}

# contact.facet.* — governed. EVERY facet claim must carry identity_binding AND use_class.
FACET_FIELDS = {
    "contact.facet.career_history": (
        "list[object]",
        {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["org"],
                "properties": {
                    "org": {"type": "string"},
                    "role": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                },
            },
        },
        "Professional history beyond the current title.",
        "professional-public",
    ),
    "contact.facet.alma_mater": (
        "list[str]",
        {"type": "array", "items": {"type": "string"}},
        "School(s) / university the person attended.",
        "personal-public-non-sensitive",
    ),
    "contact.facet.stated_interests": (
        "list[str]",
        {"type": "array", "items": {"type": "string"}},
        "Publicly stated interests / topics.",
        "personal-public-non-sensitive",
    ),
    "contact.facet.communication_style": (
        "object",
        {
            "type": "object",
            "required": ["style_label"],
            "properties": {"style_label": {"type": "string"}, "summary": {"type": "string"}},
        },
        "Inferred communication style / tone from public activity.",
        "professional-public",
    ),
    "contact.facet.public_appearances": (
        "list[object]",
        {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title"],
                "properties": {
                    "title": {"type": "string"},
                    "venue": {"type": "string"},
                    "url": {"type": "string"},
                    "date": {"type": "string"},
                },
            },
        },
        "Podcasts / talks / panels the person appeared in.",
        "professional-public",
    ),
    "contact.facet.publications": (
        "list[object]",
        {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title"],
                "properties": {
                    "title": {"type": "string"},
                    "venue": {"type": "string"},
                    "url": {"type": "string"},
                    "date": {"type": "string"},
                },
            },
        },
        "Articles / papers / books the person authored.",
        "professional-public",
    ),
    "contact.facet.recent_post": (
        "str",
        {"type": "string"},
        "Recent public post (personal hook).",
        "professional-public",
    ),
    "contact.facet.nickname": (
        "str",
        {"type": "string"},
        "Preferred / known-by name beyond the legal first name.",
        "personal-public-non-sensitive",
    ),
    "contact.facet.hobby": (
        "str",
        {"type": "string"},
        "Publicly stated hobby.",
        "personal-public-non-sensitive",
    ),
    "contact.facet.recent_award": (
        "str",
        {"type": "string"},
        "Recent award or recognition.",
        "professional-public",
    ),
    "contact.facet.conference_talk": (
        "str",
        {"type": "string"},
        "Conference talk given by the person.",
        "professional-public",
    ),
    "contact.facet.causes": (
        "list[object]",
        {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["cause"],
                "properties": {"cause": {"type": "string"}, "context": {"type": "string"}},
            },
        },
        "Publicly supported causes (sensitive by default).",
        "sensitive",
    ),
}


def catalog_text():
    lines = ["ACCOUNT FIELDS (entity = the account):"]
    for k, (vt, vs, desc) in ACCOUNT_FIELDS.items():
        lines.append(f"  {k} | value_type={vt} | {desc} | value_schema={vs}")
    lines.append("\nCONTACT FIELDS (entity = the contact; plain contact.*):")
    for k, (vt, vs, desc) in CONTACT_FIELDS.items():
        lines.append(f"  {k} | value_type={vt} | {desc} | value_schema={vs}")
    lines.append(
        "\nCONTACT FACET FIELDS (entity = the contact; GOVERNED - every claim MUST carry "
        "identity_binding and use_class):"
    )
    for k, (vt, vs, desc, uc) in FACET_FIELDS.items():
        lines.append(
            f"  {k} | value_type={vt} | {desc} | default use_class={uc} | value_schema={vs}"
        )
    return "\n".join(lines)
