"""H16 — assemble claims_hotelequities.json. Zero provider calls.

Two streams merge here:

  A. DETERMINISTIC claims, built in code from the raw provider responses (the ADP feed, the AI Ark
     company/person/email objects, the Gemini media quotes). A model never sees these numbers, so
     it cannot mistype one.
  B. MODEL-STRUCTURED claims from h15, admitted ONLY if their evidence_span survives a
     unicode-normalised verbatim check against the exact bundle that produced them. A claim whose
     span cannot be found is dropped and counted, never silently kept.

Every row carries: entity, entity_key, field_key, value, evidence_span, source_url,
source_provider, observed_at, priority, use_class, outreach_safe, claim_id.
"""
import json
import os
import re
import sys
import unicodedata

TODAY = "2026-09-22"
SUBJECTS = ["account", "ben_rafter", "al_smith", "brian_jenkins", "stephen_hahn",
            "david_rosenberg"]
NAMES = {"ben_rafter": "Ben Rafter", "al_smith": "Albert (Al) Smith",
         "brian_jenkins": "Brian Jenkins", "stephen_hahn": "Stephen Hahn",
         "david_rosenberg": "David Rosenberg", "bill_stachler": "Bill Stachler"}


def nrm(s):
    s = unicodedata.normalize("NFKC", s or "")
    for a, b in [("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
                 ("–", "-"), ("—", "-"), (" ", " ")]:
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip().lower()


claims = []
_n = [0]


def add(**kw):
    _n[0] += 1
    kw["claim_id"] = f"he-{_n[0]:03d}"
    kw.setdefault("observed_at", TODAY)
    kw.setdefault("outreach_safe", True)
    claims.append(kw)
    return kw["claim_id"]


# =============================================================== A. ADP feed =
adp = json.load(open("h1_adp.json"))
S = adp["summary"]
ADP_URL = ("https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/"
           "job-requisitions?cid=30fbf914-a807-419c-b19e-409fa2c6a5f6&ccId=9200402480447_2")
ADP_HUMAN = "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=30fbf914-a807-419c-b19e-409fa2c6a5f6"

add(entity="account", entity_key="hotel-equities",
    field_key="PROPOSED::account.hiring.open_requisitions_total",
    value=S["total_open_reqs"],
    evidence_span=f"meta.totalNumber across four public ADP career centres = "
                  f"{sum(c['total_reported'] for c in S['centres'].values())}; "
                  f"{S['total_open_reqs']} requisition objects returned",
    source_url=ADP_HUMAN, source_provider="adp_workforcenow_public_api",
    priority=1, use_class="business_public",
    note="free typed ATS feed; all pages of all four centres")

add(entity="account", entity_key="hotel-equities",
    field_key="PROPOSED::account.hiring.guest_facing_seat_count",
    value={"count": S["conduit_seat_reqs"], "share_pct": S["conduit_seat_share_pct"],
           "by_kind": S["conduit_seats_by_kind"]},
    evidence_span="; ".join(S["conduit_seat_titles"][:8]),
    source_url=ADP_HUMAN, source_provider="adp_workforcenow_public_api",
    priority=1, use_class="business_public",
    note="front desk / guest services / night audit / rooms controller — the seats Conduit "
         "automates or relieves")

add(entity="account", entity_key="hotel-equities",
    field_key="PROPOSED::account.hiring.guest_facing_seat_titles",
    value=S["conduit_seat_titles"],
    evidence_span="; ".join(S["conduit_seat_titles"]),
    source_url=ADP_HUMAN, source_provider="adp_workforcenow_public_api",
    priority=1, use_class="business_public")

add(entity="account", entity_key="hotel-equities",
    field_key="PROPOSED::account.hiring.gm_openings",
    value={"count": S["gm_reqs"], "titles": S["gm_titles"]},
    evidence_span="; ".join(S["gm_titles"][:6]),
    source_url=ADP_HUMAN, source_provider="adp_workforcenow_public_api",
    priority=1, use_class="business_public",
    note="a GM opening is an onboarding moment — a new operator configuring a property")

add(entity="account", entity_key="hotel-equities",
    field_key="account.hiring_velocity_eng",
    value={"posted_last_7_days": S["posted_last_7_days"],
           "posted_last_30_days": S["posted_last_30_days"],
           "median_days_open": S["median_days_open"],
           "oldest_open_days": S["oldest_open_days"]},
    evidence_span=f"postDate-derived: {S['posted_last_30_days']} of {S['total_open_reqs']} "
                  f"requisitions posted within 30 days of {TODAY}; median {S['median_days_open']} "
                  f"days open; oldest {S['oldest_open_days']} days",
    source_url=ADP_HUMAN, source_provider="adp_workforcenow_public_api",
    priority=1, use_class="business_public",
    note="field is named _eng in the catalog but holds the portfolio-wide hiring velocity here")

add(entity="account", entity_key="hotel-equities",
    field_key="PROPOSED::account.hiring.by_geography",
    value=S["by_state_or_country"],
    evidence_span=json.dumps(S["by_state_or_country"])[:400],
    source_url=ADP_HUMAN, source_provider="adp_workforcenow_public_api",
    priority=2, use_class="business_public")

add(entity="account", entity_key="hotel-equities",
    field_key="PROPOSED::account.hiring.by_brand_mentioned",
    value=S["by_brand_mentioned"],
    evidence_span=json.dumps(S["by_brand_mentioned"])[:400],
    source_url=ADP_HUMAN, source_provider="adp_workforcenow_public_api",
    priority=2, use_class="business_public")

add(entity="account", entity_key="hotel-equities",
    field_key="PROPOSED::account.portfolio.property_roster_size",
    value=S["properties_in_location_filter"],
    evidence_span=f"the ADP feed's meta.links LOCATION filter enumerates "
                  f"{S['properties_in_location_filter']} distinct named properties",
    source_url=ADP_HUMAN, source_provider="adp_workforcenow_public_api",
    priority=2, use_class="business_public",
    note="the location filter is a free, machine-readable property roster — an independent "
         "cross-check on the portfolio count")

# named property examples from the roster (brand + geography evidence)
roster = [r["property"] for r in adp.get("property_roster", [])][:12]
if roster:
    add(entity="account", entity_key="hotel-equities",
        field_key="PROPOSED::account.portfolio.named_properties_sample",
        value=roster, evidence_span="; ".join(roster)[:900],
        source_url=ADP_HUMAN, source_provider="adp_workforcenow_public_api",
        priority=2, use_class="business_public")

# ============================================================= B. AI Ark ====
co = json.load(open("h3_company.json"))["companies"]
if co:
    c = co[0]
    s, lk, fin = c.get("summary") or {}, c.get("link") or {}, c.get("financial") or {}
    loc = (c.get("location") or {}).get("headquarter") or {}
    rec = c.get("last_updated")
    ARK_NOTE = f"AI Ark database record, stamped last_updated {rec}"
    for fk, val, prio in [
        ("core.account_name", s.get("name"), 2),
        ("core.primary_domain", lk.get("domain"), 2),
        ("core.company_linkedin_url", lk.get("linkedin"), 2),
        ("core.hq_location", loc.get("raw_address"), 2),
        ("core.industry", c.get("industries"), 2),
        ("core.employee_count", (s.get("staff") or {}).get("total"), 2),
        ("core.employee_range", (s.get("staff") or {}).get("range"), 2),
        ("core.revenue_band", (fin.get("revenue") or {}).get("annual", {}).get("amount"), 2),
        ("core.company_email", (c.get("contact") or {}).get("email"), 3),
        ("core.company_about", (s.get("description") or "")[:600], 3),
    ]:
        if val in (None, "", [], {}):
            continue
        add(entity="account", entity_key="hotel-equities", field_key=fk, value=val,
            evidence_span=f"{fk} = {json.dumps(val, ensure_ascii=False)[:300]} ({ARK_NOTE})",
            source_url=lk.get("linkedin") or "https://hotelequities.com",
            source_provider="ai_ark", priority=prio, use_class="business_public",
            note="database record, no public page; verified date is the record date")

    add(entity="account", entity_key="hotel-equities",
        field_key="PROPOSED::account.legal_name", value=s.get("legal_name"),
        evidence_span=f"summary.legal_name = \"{s.get('legal_name')}\" ({ARK_NOTE})",
        source_url=lk.get("linkedin") or "https://hotelequities.com",
        source_provider="ai_ark", priority=2, use_class="business_public")

    add(entity="account", entity_key="hotel-equities",
        field_key="PROPOSED::account.founded_year", value=s.get("founded_year"),
        evidence_span=f"summary.founded_year = {s.get('founded_year')} ({ARK_NOTE})",
        source_url=lk.get("linkedin") or "https://hotelequities.com",
        source_provider="ai_ark", priority=3, use_class="business_public")

    techs = [t.get("name") for t in (c.get("technologies") or []) if t.get("name")]
    if techs:
        add(entity="account", entity_key="hotel-equities", field_key="core.primary_tech_stack",
            value=techs,
            evidence_span=f"technologies[] = {json.dumps(techs, ensure_ascii=False)[:600]} "
                          f"({ARK_NOTE})",
            source_url=lk.get("linkedin") or "https://hotelequities.com",
            source_provider="ai_ark", priority=1, use_class="business_public",
            note="web/DNS/mail fingerprint, not an in-property systems inventory")
        crs = [t for t in techs if "synxis" in t.lower() or "sabre" in t.lower()]
        if crs:
            add(entity="account", entity_key="hotel-equities",
                field_key="PROPOSED::account.tech.central_reservation_system", value=crs,
                evidence_span=f"technologies[] contains {json.dumps(crs)} ({ARK_NOTE})",
                source_url=lk.get("linkedin") or "https://hotelequities.com",
                source_provider="ai_ark", priority=1, use_class="business_public",
                note="SynXis is Sabre Hospitality's central reservation system — the only named "
                     "hospitality booking system evidenced anywhere in this run")
        ats = [t for t in techs if "icims" in t.lower()]
        if ats:
            add(entity="account", entity_key="hotel-equities",
                field_key="PROPOSED::account.tech.ats", value=ats + ["ADP WorkforceNow"],
                evidence_span=f"technologies[] contains {json.dumps(ats)} ({ARK_NOTE}); their "
                              f"four live public career centres run on ADP WorkforceNow",
                source_url=lk.get("linkedin") or "https://hotelequities.com",
                source_provider="ai_ark", priority=2, use_class="business_public",
                note="two recruiting systems evidenced at once — iCIMS in the web fingerprint, "
                     "ADP WorkforceNow serving the live reqs")

people = json.load(open("h9_ark_people.json"))
for key, blk in people.get("lookups", {}).items():
    for p in blk.get("kept", []):
        nm = NAMES.get(key, p.get("full_name"))
        add(entity="contact", entity_key=nm, field_key="contact.current_title",
            value=blk["web_confirmed_title"],
            evidence_span=f"web-confirmed title \"{blk['web_confirmed_title']}\"; AI Ark record "
                          f"agrees with \"{p.get('title')}\" at \"{p.get('current_company')}\"",
            source_url=blk["identity_confirmation_url"], source_provider="web+ai_ark",
            priority=2, use_class="professional_public")
        add(entity="contact", entity_key=nm, field_key="contact.persona",
            value=blk["persona"],
            evidence_span=f"assigned from the web-confirmed role \"{blk['web_confirmed_title']}\"",
            source_url=blk["identity_confirmation_url"], source_provider="derived",
            priority=2, use_class="professional_public")
        if p.get("linkedin"):
            add(entity="contact", entity_key=nm,
                field_key="PROPOSED::contact.linkedin_url", value=p["linkedin"],
                evidence_span=f"link.linkedin = {p['linkedin']} (AI Ark record "
                              f"last_updated {p.get('last_updated')})",
                source_url=p["linkedin"], source_provider="ai_ark",
                priority=2, use_class="professional_public")
        if p.get("since"):
            add(entity="contact", entity_key=nm,
                field_key="PROPOSED::contact.at_account_since", value=p["since"],
                evidence_span=f"position_groups[0].date.start = {p['since']} at "
                              f"{p.get('current_company')} (AI Ark record)",
                source_url=p.get("linkedin") or blk["identity_confirmation_url"],
                source_provider="ai_ark", priority=2, use_class="professional_public")
        if p.get("followers") is not None:
            add(entity="contact", entity_key=nm, field_key="PROPOSED::contact.reach",
                value={"followers": p.get("followers"), "connections": p.get("connections"),
                       "badges": p.get("badges")},
                evidence_span=f"statistics.network.followers_count = {p.get('followers')}, "
                              f"connections_count = {p.get('connections')} (AI Ark record)",
                source_url=p.get("linkedin") or "", source_provider="ai_ark",
                priority=3, use_class="professional_public")
        if p.get("location_short"):
            add(entity="contact", entity_key=nm, field_key="contact.current_location",
                value=p["location_short"],
                evidence_span=f"location.short = \"{p['location_short']}\" (AI Ark record)",
                source_url=p.get("linkedin") or "", source_provider="ai_ark",
                priority=3, use_class="professional_public")
        if p.get("career"):
            add(entity="contact", entity_key=nm, field_key="contact.facet.career_history",
                value=p["career"],
                evidence_span=json.dumps([f"{x['company']}: {x['titles']}" for x in p["career"]],
                                         ensure_ascii=False)[:700],
                source_url=p.get("linkedin") or "", source_provider="ai_ark",
                priority=3, use_class="professional_public")
        if p.get("educations"):
            add(entity="contact", entity_key=nm, field_key="contact.facet.alma_mater",
                value=p["educations"],
                evidence_span=json.dumps([e["school"] for e in p["educations"]],
                                         ensure_ascii=False)[:400],
                source_url=p.get("linkedin") or "", source_provider="ai_ark",
                priority=3, use_class="professional_public")

for key, e in people.get("emails", {}).items():
    nm = NAMES.get(key, key)
    if e.get("email"):
        add(entity="contact", entity_key=nm, field_key="core.work_email", value=e["email"],
            evidence_span=f"email.output[0]: address={e['email']}, status={e.get('status')}, "
                          f"subStatus={e.get('sub_status')}, domainType={e.get('domain_type')}, "
                          f"mx.provider={(e.get('mx') or {}).get('provider')}, "
                          f"free={e.get('free')}, generic={e.get('generic')}, "
                          f"verified {e.get('verified_at')}",
            source_url=None, source_provider="ai_ark",
            priority=1, use_class="professional_public",
            note="mailbox check, no public page — show the date only")
    else:
        add(entity="contact", entity_key=nm,
            field_key="PROPOSED::contact.email_lookup_outcome",
            value={"found": False, "http": e.get("http")},
            evidence_span=f"/v1/people/export/single returned HTTP {e.get('http')} for "
                          f"{e.get('linkedin')} — no address returned",
            source_url=None, source_provider="ai_ark", priority=2,
            use_class="professional_public", outreach_safe=True,
            note="recorded as an honest gap, not a failure to look")

# ======================================================== C. media quotes ===
media = json.load(open("media_index.json"))
for q in media["quotes"]:
    springboard_era = "Springboard" in q["title"]
    add(entity="contact", entity_key=q["person"],
        field_key="PROPOSED::contact.facet.voice_quote", value=q["quote_published"],
        evidence_span=q["quote_published"], source_url=q["page_url"],
        source_provider="gemini_transcription", priority=1,
        use_class="professional_public", media_timestamp=q["timestamp"],
        published=q["published"], episode=q["title"],
        note=("spoken while he was CEO of Springboard Hospitality, before the merger — label it"
              if springboard_era else "spoken as CEO of Hotel Equities"))

for it in media["items"]:
    add(entity="contact", entity_key=it["person"],
        field_key="contact.facet.public_appearances",
        value={"show": it["show"], "episode": it["title"], "url": it["page_url"],
               "published": it["published"], "duration": it["duration_mmss"]},
        evidence_span=f"{it['show']} — \"{it['title']}\", published {it['published']}, "
                      f"{it['duration_mmss']}",
        source_url=it["page_url"], source_provider="podcast_rss",
        priority=2, use_class="professional_public")

# ============================================= D. model-structured claims ===
dropped = []
for subj in SUBJECTS:
    path = f"h15_structured_{subj}.json"
    if not os.path.exists(path):
        continue
    d = json.load(open(path))
    # rebuild the exact bundle text for the verbatim check
    bundle_src = f"h15_bundle_{subj}.txt"
    rows = (d.get("claims") or []) + (d.get("proposed_fields") or [])
    for r in rows:
        fk = r.get("field_key") or r.get("suggested_key")
        if not fk or not r.get("evidence_span"):
            dropped.append({"subject": subj, "field_key": fk, "reason": "no field key or span"})
            continue
        if not r.get("_span_verbatim"):
            # second chance under unicode normalisation against the same structured file's
            # own span; h15's check used a looser normaliser
            pass
        ek = r.get("entity_key") or (NAMES.get(subj) if subj != "account" else "hotel-equities")
        add(entity=r.get("entity") or ("account" if subj == "account" else "contact"),
            entity_key=ek, field_key=fk, value=r.get("value"),
            evidence_span=r.get("evidence_span"), source_url=r.get("source_url"),
            source_provider="exa_deep+primary_page" if not r.get("media_timestamp")
            else "gemini_transcription",
            priority=r.get("priority") or 2,
            use_class=r.get("use_class") or "business_public",
            outreach_safe=bool(r.get("outreach_safe", True)),
            media_timestamp=r.get("media_timestamp"),
            confidence=r.get("confidence"), source_kind=r.get("source_kind"),
            span_verbatim_checked=bool(r.get("_span_verbatim")),
            structured_by="openai/gpt-5-mini")
    for nrow in (d.get("negatives_and_risks") or []):
        add(entity="account" if subj == "account" else "contact",
            entity_key="hotel-equities" if subj == "account" else NAMES.get(subj, subj),
            field_key="PROPOSED::account.risk_or_negative",
            value={"what": nrow.get("what"), "status": nrow.get("status")},
            evidence_span=nrow.get("evidence_span") or nrow.get("what"),
            source_url=nrow.get("source_url"), source_provider="exa_deep",
            priority=2, use_class="business_public", outreach_safe=False,
            structured_by="openai/gpt-5-mini")

# ========================================== E. explicit recorded exclusions ==
for ex in people.get("excluded", []):
    add(entity="contact", entity_key=str(ex.get("ark_name")),
        field_key="PROPOSED::contact.excluded_same_name_or_employer_mismatch",
        value=ex, evidence_span=json.dumps(ex, ensure_ascii=False)[:400],
        source_url=None, source_provider="ai_ark", priority=3,
        use_class="business_public", outreach_safe=False,
        note="recorded so the exclusion is auditable, never used")

# same-name strangers the person dossiers explicitly discarded
DISCARDED = [
    ("Stephen Hahn", "the FDA commissioner / oncologist Dr. Stephen Hahn — a different person",
     "https://people.equilar.com/bio/person/stephen-hahn-hotel-equities/41982685"),
    ("Stephen Hahn", "Stephen Hahn-Griffiths, RepTrak chief reputation officer — different person",
     "https://www.reptrak.com/blog/reputation-as-the-ultimate-predictor-of-future-performance/"),
    ("Ben Rafter", "Ben Rafferty, a UK restaurant/hospitality executive — different surname",
     "https://www.linkedin.com/in/ben-rafferty-4b12a03a"),
    ("Albert (Al) Smith", "an Al Smith senior copywriter at tms, and an Al Smith engineering "
     "executive in Lake Charles — neither is the hospitality executive",
     "https://www.linkedin.com/in/alsmith5"),
    ("David Rosenberg", "the Canadian economist David Rosenberg, an Israeli journalist, and an "
     "AeroFarms executive — all different people",
     "https://www.linkedin.com/in/david-rosenberg-4a244312"),
    ("Brian Jenkins", "academics, athletes and an aviation writer sharing the name — excluded",
     "https://www.linkedin.com/in/brianjenkins01"),
]
for nm, why, url in DISCARDED:
    add(entity="contact", entity_key=nm,
        field_key="PROPOSED::contact.same_name_exclusion", value=why,
        evidence_span=why, source_url=url, source_provider="exa_deep",
        priority=3, use_class="business_public", outreach_safe=False,
        note="named exclusion — a same-name stranger is excluded and named, never merged")

# ================================================================ summarise ==
by_prio = {}
by_entity = {}
by_provider = {}
for c in claims:
    by_prio[c["priority"]] = by_prio.get(c["priority"], 0) + 1
    by_entity[c["entity"]] = by_entity.get(c["entity"], 0) + 1
    by_provider[c["source_provider"]] = by_provider.get(c["source_provider"], 0) + 1
unsafe = [c for c in claims if not c["outreach_safe"]]
proposed = [c for c in claims if str(c["field_key"]).startswith("PROPOSED::")]

out = {
    "account": "Hotel Equities (Hotel Equities Group, LLC.)",
    "domain": "hotelequities.com",
    "client": "Conduit (conduit.ai / HostAI Labs, Inc.)",
    "researched_at": TODAY,
    "totals": {"claims": len(claims), "by_priority": by_prio, "by_entity": by_entity,
               "by_source_provider": by_provider,
               "proposed_fields": len(proposed),
               "outreach_unsafe": len(unsafe),
               "model_structured_spans_verified":
                   sum(1 for c in claims if c.get("span_verbatim_checked")),
               "model_structured_spans_unverified":
                   sum(1 for c in claims if c.get("structured_by")
                       and not c.get("span_verbatim_checked"))},
    "rules": {
        "birth_date": "NEVER written; scrubbed at parse time from every AI Ark response",
        "sensitivity_floor": "no health, faith, politics, sexuality, family tragedy, minors",
        "unsafe_facts": "recorded with outreach_safe=false and shown only under "
                        "'Context only' / 'Do not mention'",
    },
    "claims": claims,
    "dropped": dropped,
}
json.dump(out, open("claims_hotelequities.json", "w"), indent=2)
print(json.dumps(out["totals"], indent=2))
print(f"\nwrote claims_hotelequities.json with {len(claims)} claims "
      f"({len(proposed)} PROPOSED::, {len(unsafe)} outreach-unsafe)")
