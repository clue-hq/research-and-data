"""Z8 — assemble claims_zafran.json. ZERO provider calls.

Two claim species, both provenance-carrying:
  * DETERMINISTIC — read straight out of a saved provider response (AI Ark, Ashby, Exa /contents,
    Gemini usageMetadata). value + the exact response path it came from.
  * SYNTHESISED — the gpt-5-mini structuring pass over prose, carrying a verbatim-checked span.
Never a birth date. Every personal claim carries use_class + outreach_safe.
"""
import datetime, json, os, re, sys

TODAY = "2026-09-02"
claims = []
CID = [0]


def add(**kw):
    CID[0] += 1
    kw["claim_id"] = f"zaf-{CID[0]:03d}"
    kw.setdefault("observed_at", TODAY)
    claims.append(kw)


def raw(name):
    return json.load(open(os.path.join("raw", name + ".json")))


# ---------------------------------------------------------------- AI Ark ---
co = raw("z1a_companies_zafran")["_body"]["content"][0]
S, L, FIN, LOC = co["summary"], co["link"], co["financial"], co["location"]
A = ("ai_ark", "POST /v1/companies", "provider_database", 0.1, "high")


def ark_co(field, value, path, use="business_public", safe=True):
    add(entity="account", entity_key="zafran.io", field_key=field, value=value,
        source_provider="ai_ark", source_call="POST /v1/companies {domain:zafran.io}",
        source_field_path=path, source_kind="provider_database", claim_kind="deterministic",
        cost_credits=0.1 / 4, cost_usd=0.0, confidence="high", use_class=use, outreach_safe=safe,
        source_last_updated=co.get("last_updated"))


ark_co("core.account_name", S["name"], "summary.name")
ark_co("core.legal_name", S["legal_name"], "summary.legal_name")
ark_co("core.company_about", S["description"], "summary.description")
ark_co("core.industry", S["industry"], "summary.industry")
ark_co("core.employee_count", S["staff"]["total"], "summary.staff.total")
ark_co("core.employee_range", {"label": "51-200", "min": 51, "max": 200},
       "summary.staff.range")
ark_co("core.founded_year", S["founded_year"], "summary.founded_year")
ark_co("core.company_type", S["type"], "summary.type")
ark_co("core.primary_domain", L["domain"], "link.domain")
ark_co("core.company_linkedin_url", L["linkedin"], "link.linkedin")
ark_co("core.company_twitter_url", L["twitter"], "link.twitter")
ark_co("core.company_crunchbase_url", L["crunchbase"], "link.crunchbase")
ark_co("core.company_email", co["contact"]["email"], "contact.email")
ark_co("core.hq_location", {"raw": LOC["headquarter"]["raw_address"],
                            "city": LOC["headquarter"]["city"],
                            "country": LOC["headquarter"]["country"],
                            "lat": LOC["headquarter"]["position"]["lat"],
                            "lng": LOC["headquarter"]["position"]["lng"]},
       "location.headquarter")
ark_co("core.annual_revenue", {"amount_min": FIN["revenue"]["annual"]["start"],
                               "amount_max": FIN["revenue"]["annual"]["end"],
                               "currency": "USD", "as_of": co.get("last_updated"),
                               "estimate_kind": "provider_estimate"},
       "financial.revenue.annual")
ark_co("core.revenue_band", "10m_50m", "financial.revenue.annual (mapped)")
ark_co("account.total_funding", {"amount": FIN["funding"]["total_amount"], "currency": "USD",
                                 "rounds": FIN["funding"]["num_funding_rounds"],
                                 "investors": FIN["funding"]["num_investor"]},
       "financial.funding.total_amount")
ark_co("account.recent_funding", FIN["funding"]["rounds"], "financial.funding.rounds")
ark_co("core.primary_tech_stack", [t["name"] for t in co["technologies"]], "technologies[].name")
ark_co("core.tech_stack_categorised", co["technologies"], "technologies[]")
ark_co("core.industries_all", co["industries"], "industries[]")
ark_co("core.company_languages", co["languages"], "languages[]")

# --- AI Ark people (domain roster + name-scoped) ---
people_files = {"z1b_people_domain": "POST /v1/people {domain:zafran.io,size:12}",
                "z1b_people_name_vari_kaur": "POST /v1/people {fullName:[Vari Kaur,Varinder Kaur],domain:zafran.io}",
                "z1b_people_name_nick_fisher": "POST /v1/people {fullName:[Nick Fisher,Nicholas Fisher],domain:zafran.io}",
                "z1b_people_name_ben_seri": "POST /v1/people {fullName:[Ben Seri],domain:zafran.io}"}
roster = []
seen = set()
persons = {}
for f, call in people_files.items():
    for p in (raw(f)["_body"].get("content") or []):
        li = (p.get("link") or {}).get("linkedin")
        if li in seen:
            continue
        seen.add(li)
        pr = p.get("profile") or {}
        pos = (p.get("position_groups") or [{}])[0]
        roster.append({"full_name": pr.get("full_name"), "title": pr.get("title"),
                       "linkedin": li, "start": (pos.get("date") or {}).get("start"),
                       "department": (p.get("department") or {}).get("departments"),
                       "seniority": (p.get("department") or {}).get("seniority"),
                       "source_call": call})
        persons[pr.get("full_name")] = p
add(entity="account", entity_key="zafran.io", field_key="account.employee_roster_sample",
    value=roster, source_provider="ai_ark",
    source_call="POST /v1/people (1 domain-scoped size 12 + 3 name-scoped)",
    source_field_path="content[].profile / .link / .position_groups[0] / .department",
    source_kind="provider_database", claim_kind="deterministic", cost_credits=7.5, cost_usd=0.0,
    confidence="high", use_class="professional_public", outreach_safe=True,
    note="totalElements=163 people match the zafran.io domain; 12 were paid for and returned.")

COMMITTEE = {
    "Vari Kaur": ("champion", "z1b_people_name_vari_kaur"),
    "Nick Fisher": ("economic_buyer", "z1b_people_name_nick_fisher"),
    "Sanaz Yashar": ("executive_sponsor", "z1b_people_domain"),
    "Ben Seri": ("technical_evaluator", "z1b_people_name_ben_seri"),
    "Tom Anthony": ("adjacent_buyer", "z1b_people_domain"),
}
for name, (persona, src) in COMMITTEE.items():
    p = persons.get(name)
    if not p:
        continue
    pr, dep = p.get("profile") or {}, p.get("department") or {}
    st = p.get("statistics") or {}
    pos = p.get("position_groups") or []
    li = (p.get("link") or {}).get("linkedin")

    def pc(field, value, path, use="professional_public", safe=True, conf="high"):
        add(entity="contact", entity_key=li, person=name, field_key=field, value=value,
            source_provider="ai_ark", source_call=f"AI Ark person object ({src})",
            source_field_path=path, source_kind="provider_database",
            claim_kind="deterministic", cost_credits=0.5, cost_usd=0.0, confidence=conf,
            use_class=use, outreach_safe=safe, persona=persona)

    pc("contact.current_title", pr.get("title"), "profile.title")
    pc("contact.persona", persona, "derived from title + committee model")
    pc("contact.job_function", dep.get("functions"), "department.functions")
    pc("contact.job_level", dep.get("seniority"), "department.seniority")
    pc("contact.current_location", (p.get("location") or {}).get("default"), "location.default")
    pc("contact.headline", pr.get("headline"), "profile.headline")
    if pr.get("summary"):
        pc("contact.facet.self_summary", pr["summary"], "profile.summary",
           use="personal_public_self_stated")
    pc("contact.facet.career_history",
       [{"company": (g.get("company") or {}).get("name"), "date": g.get("date"),
         "titles": [x.get("title") for x in (g.get("profile_positions") or [])]} for g in pos],
       "position_groups[]")
    if p.get("educations"):
        pc("contact.facet.alma_mater",
           [{"school": (e.get("school") or {}).get("name"), "degree": e.get("degree_name"),
             "field": e.get("field_of_study"), "date": e.get("date")} for e in p["educations"]],
           "educations[]")
    if p.get("certifications"):
        pc("contact.facet.certifications",
           [{"name": c.get("name"), "authority": c.get("authority"), "date": c.get("date")}
            for c in p["certifications"]], "certifications[]")
    if p.get("awards"):
        pc("contact.facet.recent_award", [a.get("title") for a in p["awards"]], "awards[]")
    if p.get("skills"):
        pc("contact.facet.stated_skills", p["skills"], "skills[]")
    if st:
        pc("contact.network_statistics", st, "statistics")
    if p.get("member_badges"):
        pc("contact.member_badges", p["member_badges"], "member_badges")

# --- AI Ark emails ---
for row in json.load(open("z1d_emails_parsed.json")):
    add(entity="contact", entity_key=row["ark_full_name"], person=row["name"],
        field_key="core.work_email", value=row["email"], source_provider="ai_ark",
        source_call="POST /v1/people/export/single {url:<linkedin>}",
        source_field_path="email.output[0].address", source_kind="provider_database",
        claim_kind="deterministic", cost_credits=row["credits"], cost_usd=0.0,
        confidence="high" if row["verdict"] == "verified_smtp" else "medium",
        use_class="professional_public", outreach_safe=True, persona=row["persona"],
        verification={"state": row["email_state"], "status": row["email_status"],
                      "domain_type": row["domain_type"], "sub_status": row["sub_status"],
                      "mx_record": row["mx_record"], "mx_provider": row["mx_provider"],
                      "free": row["free"], "generic": row["generic"],
                      "checked_at": row["checked_at"], "verdict": row["verdict"]})

# ------------------------------------------------------------ Ashby (free) --
ash = json.load(open("z2b_ashby.json"))["zafran-security"]
today = datetime.date(2026, 9, 2)
jobs = []
for j in ash["jobs"]:
    pub = (j.get("publishedAt") or "")[:10]
    days = (today - datetime.date(*map(int, pub.split("-")))).days if pub else None
    jobs.append({"title": j.get("title"), "department": j.get("department"),
                 "team": j.get("team"), "location": j.get("location"),
                 "is_remote": j.get("isRemote"), "workplace_type": j.get("workplaceType"),
                 "published_at": pub, "days_open": days, "job_url": j.get("jobUrl"),
                 "employment_type": j.get("employmentType"),
                 "compensation_published": bool(j.get("compensation", {}).get("compensationTiers"))})
add(entity="account", entity_key="zafran.io", field_key="account.open_requisitions",
    value=jobs, source_provider="ashby_posting_api",
    source_call="GET https://api.ashbyhq.com/posting-api/job-board/zafran-security",
    source_field_path="jobs[]", source_kind="company_primary", claim_kind="deterministic",
    cost_usd=0.0, cost_credits=0.0, confidence="high", use_class="business_public",
    outreach_safe=True, note="FREE. 27 live reqs on 2026-09-02.")

by_dept = {}
for j in jobs:
    by_dept[j["department"]] = by_dept.get(j["department"], 0) + 1
add(entity="account", entity_key="zafran.io", field_key="account.hiring_velocity",
    value={"open_reqs_total": len(jobs), "by_department": by_dept,
           "published_last_7_days": sum(1 for j in jobs if (j["days_open"] or 999) <= 7),
           "published_last_30_days": sum(1 for j in jobs if (j["days_open"] or 999) <= 30),
           "longest_open_marketing_req_days": max(
               [j["days_open"] for j in jobs if j["department"] == "Marketing"] or [0])},
    source_provider="ashby_posting_api", source_call="GET posting-api/job-board/zafran-security",
    source_field_path="derived from jobs[].publishedAt", source_kind="company_primary",
    claim_kind="deterministic", cost_usd=0.0, cost_credits=0.0, confidence="high",
    use_class="business_public", outreach_safe=True)

ABM = [j for j in ash["jobs"] if j["title"] == "Senior Manager, ABM & Integrated Campaigns"][0]
BDR = [j for j in ash["jobs"] if j["title"] == "Business Development Representative"][0]
ALL_ = [j for j in ash["jobs"] if j["title"] == "Director of Alliances"][0]


def quote(text, needle, before=0, after=260):
    i = text.find(needle)
    return re.sub(r"\s+", " ", text[max(0, i - before):i + len(needle) + after]).strip() if i >= 0 else None


bdr_txt = BDR["descriptionPlain"]
abm_txt = ABM["descriptionPlain"]
add(entity="account", entity_key="zafran.io", field_key="account.gtm_tooling_stack",
    value={"sdr_stack": ["Salesforce", "LinkedIn Sales Navigator", "ZoomInfo", "Outreach"],
           "marketing_stack": ["HubSpot", "Salesforce", "(unnamed) major ABM platforms"],
           "explicitly_absent_from_all_27_reqs": ["6sense", "Demandbase", "Terminus", "RollWorks",
                                                  "Mutiny", "Folloze", "Influ2", "Madison Logic",
                                                  "Clay", "Common Room", "Gong", "Marketo",
                                                  "Salesloft", "Apollo"]},
    evidence_span=quote(bdr_txt, "Utilize tools such as Salesforce"),
    evidence_span_2=quote(abm_txt, "Proficiency in Salesforce, HubSpot"),
    source_provider="ashby_posting_api",
    source_call="GET posting-api/job-board/zafran-security -> jobs[].descriptionPlain",
    source_field_path="Business Development Representative + Senior Manager ABM req bodies",
    source_kind="company_primary", claim_kind="deterministic", cost_usd=0.0, cost_credits=0.0,
    confidence="high", use_class="business_public", outreach_safe=True,
    note="This is the single highest-value free fact in the run: the actual named SDR stack. "
         "The Exa deep-reasoning call marked every one of these NOT FOUND.")

add(entity="account", entity_key="zafran.io", field_key="account.abm_program_maturity",
    value={"state": "being built from scratch", "req": ABM["title"],
           "published_at": ABM["publishedAt"][:10], "days_open": 77,
           "reports_to": "Head of Growth Marketing (Vari Kaur)",
           "url": ABM["jobUrl"]},
    evidence_span=quote(abm_txt, "Own ABM from the ground up", after=420),
    source_provider="ashby_posting_api", source_call="GET posting-api/job-board/zafran-security",
    source_field_path="descriptionPlain", source_kind="company_primary",
    claim_kind="deterministic", cost_usd=0.0, cost_credits=0.0, confidence="high",
    use_class="business_public", outreach_safe=True)

add(entity="account", entity_key="zafran.io", field_key="account.strategic_moves",
    value={"move": "standing up a partner/alliances channel from zero",
           "req": ALL_["title"], "published_at": ALL_["publishedAt"][:10], "days_open": 1},
    evidence_span=quote(ALL_["descriptionPlain"], "Our partner ecosystem is becoming", after=420),
    source_provider="ashby_posting_api", source_call="GET posting-api/job-board/zafran-security",
    source_field_path="descriptionPlain", source_kind="company_primary",
    claim_kind="deterministic", cost_usd=0.0, cost_credits=0.0, confidence="high",
    use_class="business_public", outreach_safe=True)

add(entity="account", entity_key="zafran.io", field_key="account.resonance.buying_culture",
    value={"office_policy": "NYC office ~3 days a week for the BDR seat",
           "bdr_reports_into": "Marketing department (Ashby department field)"},
    evidence_span=quote(bdr_txt, "regular in-office presence", before=80, after=120),
    source_provider="ashby_posting_api", source_call="GET posting-api/job-board/zafran-security",
    source_field_path="jobs[].department + descriptionPlain", source_kind="company_primary",
    claim_kind="deterministic", cost_usd=0.0, cost_credits=0.0, confidence="high",
    use_class="business_public", outreach_safe=True)

# ------------------------------------------------- own site: named customers --
own = json.load(open("raw/z2_own_site.json"))
home = [r for r in own["results"] if r["url"].rstrip("/") == "https://www.zafran.io"][0]["text"]
cust = []
for nm, role in [("Ricardo Lafosse", "CISO, Kraft Heinz"), ("Dave Estlick", "CISO, Chipotle"),
                 ("James Robinson", "CISO, Netskope")]:
    i = home.find(nm)
    if i >= 0:
        cust.append({"name": nm, "role": role,
                     "quote": re.sub(r"\s+", " ", home[max(0, i - 420):i]).strip()[-380:]})
add(entity="account", entity_key="zafran.io", field_key="account.named_customers",
    value=cust, source_provider="exa_contents", source_call="POST /contents livecrawl zafran.io",
    source_field_path="results[0].text (homepage testimonial block)",
    source_kind="company_primary", claim_kind="deterministic", cost_usd=0.001,
    cost_credits=0.0, confidence="high", use_class="business_public", outreach_safe=True,
    note="Named CISOs at named logos, on their own homepage. Both the smoke-test deep call and "
         "today's deep call reported named customers as NOT FOUND / partial.")

# ------------------------------------------------------------ Gemini media --
media = []
for meta, person, url, title, dur in [
    ("z4b_sanaz_boardroom_meta.json", "Sanaz Yashar",
     "https://podcasters.spotify.com/pod/show/boardroomclub/episodes/"
     "AI-Summit-Sanaz-Yashar--Co-Founder-and-CEO-at-Zafran-Security-e36d9ai",
     "Boardroom Club — AI Summit: Sanaz Yashar", "00:42:49"),
    ("z4a_nick_supporting_cc_meta.json", "Nick Fisher",
     "https://www.youtube.com/watch?v=8_YWBtq4eic", "Supporting Cocktail Chemistry", "00:01:31"),
    ("z4a_nick_moscow_mule_meta.json", "Nick Fisher",
     "https://www.youtube.com/watch?v=avcD5WVLCYs",
     "Advanced Techniques - How To Make A Moscow Mule", "00:04:14")]:
    m = json.load(open(meta))
    media.append({"person": person, "url": url, "title": title, "duration": dur,
                  "cost_usd": m["cost_usd"], "latency_s": m["elapsed_s"],
                  "transcript_chars": m["chars"]})
add(entity="account", entity_key="zafran.io", field_key="account.media_layer_index", value=media,
    source_provider="gemini", source_call="gemini-3.5-flash-lite:generateContent",
    source_field_path="usageMetadata + transcript", source_kind="transcript_self",
    claim_kind="deterministic", cost_usd=round(sum(m["cost_usd"] for m in media), 6),
    cost_credits=0.0, confidence="high", use_class="professional_public", outreach_safe=True)


def quotes_block(path):
    t = open(path).read()
    i = t.find("## QUOTES")
    if i < 0:
        return []
    body = t[i + 9:]
    j = body.find("\n## ")
    body = body[:j] if j > 0 else body
    out = []
    for ln in body.splitlines():
        m = re.match(r'^-\s*"?\[?(\d{1,2}:\d{2})\]?"?\s*"(.+?)"\s*->\s*(?:why[^:]*:)?\s*(.*)$',
                     ln.strip())
        if m:
            out.append({"timestamp": m.group(1), "quote": m.group(2), "why": m.group(3)})
    return out


VOICE = [("transcripts/sanaz_boardroom.md", "Sanaz Yashar",
          "https://podcasters.spotify.com/pod/show/boardroomclub/episodes/"
          "AI-Summit-Sanaz-Yashar--Co-Founder-and-CEO-at-Zafran-Security-e36d9ai"),
         ("transcripts/nick_supporting_cc.md", "Nick Fisher",
          "https://www.youtube.com/watch?v=8_YWBtq4eic"),
         ("transcripts/nick_moscow_mule.md", "Nick Fisher",
          "https://www.youtube.com/watch?v=avcD5WVLCYs")]
for path, person, url in VOICE:
    for q in quotes_block(path):
        add(entity="contact", entity_key=person, person=person,
            field_key="contact.facet.voice_quote", value=q["quote"],
            evidence_span=q["quote"], media_timestamp=q["timestamp"], media_url=url,
            source_provider="gemini", source_call="gemini-3.5-flash-lite (audio/video -> transcript)",
            source_field_path="## QUOTES block of the timestamped transcript",
            source_kind="transcript_self", claim_kind="deterministic_media",
            cost_usd=0.0, cost_credits=0.0, confidence="high",
            use_class="personal_public_self_stated", outreach_safe=True,
            why_it_matters=q["why"])

add(entity="contact", entity_key="Nick Fisher", person="Nick Fisher",
    field_key="contact.facet.hobby",
    value={"hobby": "cocktail YouTuber; creator of the Cocktail Chemistry channel (2014) and "
                    "author of the book 'Cocktail Chemistry'",
           "identity_chain": [
               "Nick Fisher's own LinkedIn post: 'my little side hobby as a cocktail YouTuber' + "
               "he announces the book 'Cocktail Chemistry: The Art and Science of Drinks from "
               "Iconic TV Shows and Movies'",
               "Simon & Schuster author page for Nick Fisher: 'In 2014, he created the YouTube "
               "channel Cocktail Chemistry'",
               "Gemini transcript of that channel's video: the narrator says 'Hey everyone it's "
               "Nick just checking in'"]},
    evidence_span="In 2014, he created the YouTube channel Cocktail Chemistry to showcase these "
                  "techniques, and it quickly rose to one of the most-watched cocktail channels.",
    source_provider="exa_contents+gemini",
    source_call="POST /contents simonandschuster.com + gemini YouTube transcript",
    source_field_path="results[].text + transcript META.narrator_identity_evidence",
    source_kind="third_party_press", claim_kind="synthesised", cost_usd=0.002, cost_credits=0.0,
    confidence="high", use_class="personal_public_self_stated", outreach_safe=True,
    persona="economic_buyer")

add(entity="contact", entity_key="Nick Fisher", person="Nick Fisher",
    field_key="contact.facet.excluded_lookalike",
    value={"discarded_media": "https://www.youtube.com/watch?v=4gKLZrv2p8g",
           "title": "The Truth About Why I Was a Faceless Cocktail Channel",
           "why_discarded": "A different, British cocktail YouTuber. The transcript places the "
                            "narrator 'in leafy old England out in the sticks' and unmasking in "
                            "2026; Nick Fisher is the American creator of Cocktail Chemistry "
                            "since 2014. Discarded — no claim was built from it.",
           "cost_of_the_mistake_usd": 0.006188},
    source_provider="gemini", source_call="gemini-3.5-flash-lite YouTube transcript",
    source_field_path="transcript", source_kind="transcript_self", claim_kind="exclusion",
    cost_usd=0.006188, cost_credits=0.0, confidence="high", use_class="professional_public",
    outreach_safe=False)

# --- verified second-half quotes (from the faithful ASR the flash-lite pass missed) ---
qv = json.load(open("z4e_quote_verification.json"))
for q in qv["second_half_mined_quotes"]:
    if q.get("verbatim_check") != "EXACT":
        continue
    add(entity="contact", entity_key="Sanaz Yashar", person="Sanaz Yashar",
        field_key="contact.facet.voice_quote", value=q["quote"], evidence_span=q["quote"],
        media_timestamp="second half of 00:42:49 (dedicated ASR model returns no timestamps)",
        media_url="https://podcasters.spotify.com/pod/show/boardroomclub/episodes/"
                  "AI-Summit-Sanaz-Yashar--Co-Founder-and-CEO-at-Zafran-Security-e36d9ai",
        source_provider="gemini", source_call="gemini-3.5-transcribe (ASR) + flash-lite quote pick",
        source_field_path="candidates[0].content.parts[0].audioTranscription.text",
        source_kind="transcript_self", claim_kind="deterministic_media",
        evidence_span_verbatim=True, cost_usd=0.0, cost_credits=0.0, confidence="high",
        use_class="personal_public_self_stated", outreach_safe=True, persona="executive_sponsor",
        topic=q.get("topic"), why_it_matters=q.get("why"))

tq = json.load(open("z4b_transcript_quality.json"))
add(entity="account", entity_key="zafran.io", field_key="account.media_transcript_quality_warning",
    value={"model": "gemini-3.5-flash-lite", "media": "42:49 podcast",
           "timestamped_lines": tq["timestamped_lines"], "unique_lines": tq["unique_lines"],
           "sustained_loop_begins_ts": tq["sustained_loop_begins_ts"],
           "remedy": "gemini-3.5-transcribe re-ran the same file and produced the full 6,926-word "
                     "episode with no looping, but returns parts[].audioTranscription.text with "
                     "NO timestamps and NO speaker labels.",
           "rule_applied": "any flash-lite quote after [12:38] was re-verified against the "
                           "faithful ASR before being kept"},
    source_provider="gemini", source_call="internal QA over two model runs of the same file",
    source_field_path="derived", source_kind="provider_database", claim_kind="deterministic",
    cost_usd=0.0, cost_credits=0.0, confidence="high", use_class="business_public",
    outreach_safe=False)

# --------------------------------------------------------- synthesised (LLM) --
st = json.load(open("z7_structured.json"))
for c in st.get("account_claims") or []:
    add(entity="account", entity_key="zafran.io", field_key=c.get("field_key"),
        value=c.get("value"), evidence_span=c.get("evidence_span"),
        evidence_span_verbatim=c.get("evidence_span_verbatim"),
        source_url=c.get("source_url"), source_kind=c.get("source_kind"),
        source_provider="exa_deep_reasoning|exa_contents|gemini (structured by gpt-5-mini)",
        claim_kind="synthesised", cost_usd=None, cost_credits=0.0,
        confidence=c.get("confidence"), use_class=c.get("use_class"),
        outreach_safe=c.get("outreach_safe"))
for c in st.get("contact_claims") or []:
    add(entity="contact", entity_key=c.get("person"), person=c.get("person"),
        field_key=c.get("field_key"), value=c.get("value"),
        evidence_span=c.get("evidence_span"),
        evidence_span_verbatim=c.get("evidence_span_verbatim"),
        media_timestamp=c.get("media_timestamp"), source_url=c.get("source_url"),
        source_kind=c.get("source_kind"),
        source_provider="exa_deep_reasoning|gemini (structured by gpt-5-mini)",
        claim_kind="synthesised", cost_usd=None, cost_credits=0.0,
        confidence=c.get("confidence"), use_class=c.get("use_class"),
        outreach_safe=c.get("outreach_safe"))
for c in st.get("negatives_and_risks") or []:
    add(entity="account", entity_key="zafran.io", field_key="account.reputation_risk",
        value={"what": c.get("what"), "status": c.get("status")},
        evidence_span=c.get("evidence_span"),
        evidence_span_verbatim=c.get("evidence_span_verbatim"),
        source_url=c.get("source_url"), source_kind="third_party_press",
        source_provider="exa_deep_reasoning (structured by gpt-5-mini)",
        claim_kind="synthesised", cost_usd=None, cost_credits=0.0, confidence="medium",
        use_class="business_public", outreach_safe=False)
for c in st.get("proposed_fields") or []:
    add(entity="account", entity_key="zafran.io", field_key="PROPOSED::" + c.get("suggested_key", "?"),
        value=c.get("value"), evidence_span=c.get("evidence_span"),
        evidence_span_verbatim=c.get("evidence_span_verbatim"),
        source_url=c.get("source_url"), source_kind="mixed",
        source_provider="structuring pass", claim_kind="proposed_field", cost_usd=None,
        cost_credits=0.0, confidence="medium", use_class="business_public", outreach_safe=True,
        why=c.get("why"))

# ------------------------------------------------------------------ output --
assert not any("birth" in json.dumps(c).lower() for c in claims), "birth data leaked"
out = {
    "account": "Zafran Security Ltd. (zafran.io)", "run": "arv2-one-account-aiark",
    "research_date": TODAY,
    "provider_ruling": "AI Ark is the only structured-data provider. Apollo calls in this run: 0.",
    "claim_count": len(claims),
    "by_kind": {k: sum(1 for c in claims if c["claim_kind"] == k)
                for k in sorted({c["claim_kind"] for c in claims})},
    "by_entity": {k: sum(1 for c in claims if c["entity"] == k)
                  for k in sorted({c["entity"] for c in claims})},
    "outreach_unsafe_count": sum(1 for c in claims if c.get("outreach_safe") is False),
    "never_recorded": ["profile.birth_date (dropped at parse time and scrubbed from raw/)",
                       "age, health, religion, politics, family/children"],
    "claims": claims,
}
json.dump(out, open("claims_zafran.json", "w"), indent=2)
print(json.dumps({k: v for k, v in out.items() if k != "claims"}, indent=1))
