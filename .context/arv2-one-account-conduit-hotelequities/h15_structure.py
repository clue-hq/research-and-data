"""H15 — structure the PROSE sources into closed-field-key claims. ONE subject per call.

Usage: python3 h15_structure.py <subject>
  subject in {account, ben_rafter, al_smith, brian_jenkins, stephen_hahn, david_rosenberg}

Deterministic provider facts (the ADP feed, the AI Ark objects, the verified emails, the Gemini
usage/quotes) are NOT sent to the model — they are assembled in code in h16, because a model
should never be given the chance to retype a number it could mistype. This call converts prose
ONLY (the deep-reasoning dossiers, the primary pages, the transcripts) into claims whose
evidence_span is a verbatim substring of the bundle.

Priority is keyed to CONDUIT's fit, not to a generic ABM rubric — the prompt says so explicitly.
"""
import json
import os
import sys
import time

sys.path.insert(0, ".")
import z_lib as C  # noqa: E402
import field_catalog as F  # noqa: E402

SUBJECT = sys.argv[1]

key_pages = json.load(open("h14_key_pages.json"))["pages"]
itr_pages = json.load(open("h14b_itr_pages.json"))
committee_pages = json.load(open("h6_committee_confirm.json"))["page_text"]
own = json.load(open("h2_own_site.json"))["resolved"]
media = json.load(open("media_index.json"))


def page(url, n=9000):
    for src in (key_pages, itr_pages):
        if url in src:
            return f"### SOURCE PAGE {url}\n{(src[url].get('text') or '')[:n]}\n"
    if url in committee_pages:
        return f"### SOURCE PAGE {url}\n{committee_pages[url][:n]}\n"
    return ""


def media_block(person):
    rows = [q for q in media["quotes"] if q["person"] == person]
    if not rows:
        return ""
    out = [f"### SOURCE: verified media quotes for {person} (wording is verbatim from the "
           f"gemini-3.5-transcribe faithful transcript; the MM:SS is from the timestamped pass)"]
    for q in rows:
        out.append(f'- [{q["timestamp"]}] episode "{q["title"]}" ({q["published"]}), '
                   f'url {q["page_url"]} :: "{q["quote_published"]}"')
    return "\n".join(out) + "\n"


BUNDLES = {
    "account": lambda: (
        "=== SOURCE A: Exa deep-reasoning account dossier (2026-09-22) ===\n"
        + open("report_account_hotelequities_deep.md").read()[:22000] + "\n\n"
        + "=== SOURCE B: hotelequities.com primary pages ===\n"
        + page("https://www.hotelequities.com/he-labs.htm")
        + page("https://www.hotelequities.com/blog/hotel-equities-ceo-talks-he-labs--our-new-innovation-and-incubation-division/")
        + page("https://www.hotelequities.com/blog/hotel-equities-earns-fourth-consecutive-1-ranking-as-marriotts-top-performing-franchise-management-company-based-on-intent-to-recommend-itr-scores/")
        + page("https://www.hotelequities.com/blog/al-smith-discusses-how-simplicity-drives-consistent-luxury-service-at-scale/")
        + page("https://www.hotelequities.com/blog/hotel-equities-and-springboard-hospitality-announce-strategic-merger/")
        + page("https://www.hotelequities.com/blog/hotel-equities-strengthens-leadership-team-with-key-executive-appointments-across-new-divisions/")
        + page("https://www.hotelequities.com/blog/hotel-equities-appoints-brian-jenkins-to-lead-he-labs--the-management-companys-new-innovation-division/")
        + page("https://www.hotelequities.com/blog/hotel-equities-selected-to-operate-postcard-cabins/")
        + page("https://www.hotelequities.com/blog/hotel-equities-new-ceo-charts-path/")
        + page("https://www.hotelinvestmenttoday.com/Deals/Management/Hotel-Equities-new-CEO-charts-path", 7000)
        + "\n=== SOURCE C: the company's own leadership page ===\n"
        + f"### SOURCE PAGE https://www.hotelequities.com/meet-our-team.htm\n"
        + (own.get("team", {}).get("text", "")[:12000]) + "\n\n"
        + "=== SOURCE D: the CEO's own words, from the transcripts ===\n"
        + media_block("Ben Rafter")),
    "ben_rafter": lambda: (
        "=== SOURCE A: Exa deep-reasoning person dossier ===\n"
        + open("report_person_ben_rafter.md").read()[:18000] + "\n\n"
        + "=== SOURCE B: primary pages ===\n"
        + page("https://www.hotelequities.com/he-labs.htm")
        + page("https://www.hotelequities.com/blog/hotel-equities-ceo-talks-he-labs--our-new-innovation-and-incubation-division/")
        + page("https://www.hotelequities.com/blog/hotel-equities-ceo-ben-rafter-joins-american-hotel-and-lodging-associations-board-of-directors/")
        + page("https://www.hotelequities.com/blog/hotel-equities-new-ceo-charts-path/")
        + page("https://www.hotelinvestmenttoday.com/Deals/Management/Hotel-Equities-new-CEO-charts-path", 8000)
        + page("https://www.travelmediagroup.com/190-tmg-hospitality-trailblazers-ben-rafter/", 12000)
        + "\n=== SOURCE C: his own recorded words ===\n" + media_block("Ben Rafter")),
    "al_smith": lambda: (
        "=== SOURCE A: Exa deep-reasoning person dossier ===\n"
        + open("report_person_al_smith.md").read()[:18000] + "\n\n"
        + "=== SOURCE B: primary pages ===\n"
        + page("https://www.hotelequities.com/blog/al-smith-discusses-how-simplicity-drives-consistent-luxury-service-at-scale/")
        + page("https://www.hotelequities.com/files/6564/Hotel_Equities_Names_Al_Smith_as_President.pdf")
        + page("https://www.hospitalitynet.org/appointment/79030411.html")
        + page("https://www.hotelequities.com/blog/hotel-equities-announces-key-leadership-appointments-after-strategic-merger-with-springboard-hospitality/")
        + page("https://www.hotelequities.com/blog/hotel-equities-strengthens-leadership-team-with-key-executive-appointments-across-new-divisions/")),
    "brian_jenkins": lambda: (
        "=== SOURCE A: Exa deep-reasoning person dossier ===\n"
        + open("report_person_brian_jenkins.md").read()[:18000] + "\n\n"
        + "=== SOURCE B: primary pages ===\n"
        + page("https://www.hotelequities.com/he-labs.htm")
        + page("https://www.hotelequities.com/blog/hotel-equities-appoints-brian-jenkins-to-lead-he-labs--the-management-companys-new-innovation-division/")
        + page("https://www.hospitalitynet.org/appointment/79032251/brian-jenkins")
        + page("https://www.springboardhospitality.com/team/", 14000)),
    "stephen_hahn": lambda: (
        "=== SOURCE A: Exa deep-reasoning person dossier ===\n"
        + open("report_person_stephen_hahn.md").read()[:18000] + "\n\n"
        + "=== SOURCE B: primary pages ===\n"
        + page("https://hotelmanagement.mydigitalpublication.com/june-july-2026/page-13", 8000)
        + page("https://www.linkedin.com/posts/hotel-equities_hotelequities-hospitalitytechnology-hotelmanagement-activity-7471283773595238400-nH7w")
        + page("https://people.equilar.com/bio/person/stephen-hahn-hotel-equities/41982685")
        + page("https://www.hotelequities.com/he-labs.htm")),
    "david_rosenberg": lambda: (
        "=== SOURCE A: Exa deep-reasoning person dossier ===\n"
        + open("report_person_david_rosenberg.md").read()[:18000] + "\n\n"
        + "=== SOURCE B: primary pages ===\n"
        + page("https://www.hotelequities.com/blog/hotel-equities-earns-fourth-consecutive-1-ranking-as-marriotts-top-performing-franchise-management-company-based-on-intent-to-recommend-itr-scores/")
        + page("https://www.hotelequities.com/files/6564/Hotel_Equities_Announces_Three_Key_Promotions_to_Executive_Leadership_Team.pdf")
        + page("https://www.hotelequities.com/blog/hotel-equities-strengthens-leadership-team-with-key-executive-appointments-across-new-divisions/")),
}

CATALOG = ("ACCOUNT FIELD KEYS:\n"
           + "\n".join(f"  {k} — {v[2]}" for k, v in F.ACCOUNT_FIELDS.items())
           + "\n\nCONTACT FIELD KEYS:\n"
           + "\n".join(f"  {k} — {v[2]}" for k, v in F.CONTACT_FIELDS.items())
           + "\n\nCONTACT FACET (personal) FIELD KEYS:\n"
           + "\n".join(f"  {k} — {v[2]}" for k, v in F.FACET_FIELDS.items()))

CONDUIT = """WHO "WE" ARE (the seller, for priority scoring only — never invent facts about us):
Conduit (conduit.ai, legal name HostAI Labs, Inc.), a 2024 San Francisco company, sells an AI
agent platform for HOSPITALITY OPERATIONS: chat and voice agents that handle guest communication
and internal work across existing systems, with escalation to humans. Its differentiators are a
single agent across phone and messaging, PMS WRITE-BACK (including a June 2026 two-way Oracle
OPERA integration through an MCP adapter), BRAND-OVER-PROPERTY configuration for portfolios, and
per-unit (not per-seat) pricing from $18-$48 per unit/month. A published customer case reports
90% automation across ~270 properties while holding quality scores at 4.8-4.9.

PRIORITY IS KEYED TO CONDUIT'S FIT:
  P1 = guest-services / front-desk / night-audit hiring volume and velocity; PMS and OPERA facts;
       guest-messaging tool gaps; merger-integration and new-division timing; new openings;
       executive quotes about technology, guest experience, labor or automation; vacant seats;
       anything that ties guest satisfaction to money.
  P2 = portfolio composition, brand mix, ITR ranking, division structure, the wider tech stack,
       committee composition.
  P3 = history, culture, background, personal hooks (which are P1 inside that person's own
       contact view)."""

SYS = f"""You convert research prose into typed claims. You NEVER invent anything.

{CONDUIT}

HARD RULES
  * `evidence_span` MUST be a VERBATIM substring copied character-for-character from the bundle.
    If you cannot copy an exact span, DO NOT emit the claim. This is checked in code afterwards
    and failures are dropped.
  * Only use field keys from the supplied catalog. Anything that does not fit goes in
    `proposed_fields` with a `PROPOSED::` key name — never force a fact into a wrong key.
  * `use_class` is one of: business_public, professional_public, personal_public_self_stated,
    sensitive_excluded.
  * `outreach_safe` is false for: anything negative about the company or a person, anything
    unresolved or disputed, anything about a person's origin, nationality, religion, family or
    health, and anything you would not say out loud to the person in a first email. Such claims
    may still be RECORDED — they are simply not outreach material.
  * NEVER record a birth date, age, health, religion, political view, sexuality, family tragedy,
    or anything about children. If the bundle contains it, ignore it completely.
  * A person's own words are `personal_public_self_stated` when about their life and
    `professional_public` when about their work.
  * Distinguish a company claim from a third-party report using `source_kind`.
  * "not found" in the bundle is NOT a claim. Do not emit claims for absences."""

USER_TMPL = """{catalog}

SUBJECT OF THIS CALL: {subject}

Return STRICT JSON:
{{
 "claims": [{{"entity": "account|contact", "entity_key": "<hotel-equities or the person's name>",
   "field_key": "<a catalog key>", "value": <json>, "evidence_span": "<VERBATIM substring>",
   "source_url": "...", "source_kind": "company_primary|third_party_press|job_posting|
   transcript_self|provider_database|analyst_estimate", "confidence": "high|medium|low",
   "observed_at": "2026-09-22", "priority": 1|2|3, "use_class": "...", "outreach_safe": true|false,
   "media_timestamp": "MM:SS or null"}}],
 "proposed_fields": [{{"suggested_key": "PROPOSED::...", "why": "...", "entity": "account|contact",
   "entity_key": "...", "value": <json>, "evidence_span": "<VERBATIM>", "source_url": "...",
   "priority": 1|2|3, "use_class": "...", "outreach_safe": true|false,
   "media_timestamp": "MM:SS or null"}}],
 "negatives_and_risks": [{{"what": "...", "status": "REFUTED|UNRESOLVED|CONFIRMED|NOT_FOUND",
   "evidence_span": "<VERBATIM>", "source_url": "...", "outreach_safe": false}}]
}}

Be thorough: aim for 30-45 rows in total across claims + proposed_fields. Every quote from a
transcript MUST carry its media_timestamp. Prefer facts a rep could NOT find on the homepage.

BUNDLE:
{bundle}"""

t0 = time.time()
bundle = BUNDLES[SUBJECT]()
print(f"  bundle chars: {len(bundle)}")
out = C.openrouter(
    "openai/gpt-5-mini",
    [{"role": "system", "content": SYS},
     {"role": "user", "content": USER_TMPL.format(catalog=CATALOG, subject=SUBJECT,
                                                  bundle=bundle)}],
    label=f"h15_structure_{SUBJECT}", reasoning={"effort": "minimal"},
    response_format={"type": "json_object"}, max_tokens=32000)
txt = ((out.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
try:
    data = json.loads(txt)
except Exception as e:
    print("PARSE FAIL", e)
    print(txt[:1500])
    sys.exit(1)
data["_bundle_chars"] = len(bundle)
data["_subject"] = SUBJECT
json.dump(data, open(f"h15_structured_{SUBJECT}.json", "w"), indent=2)

# ---- verbatim span check, in code ------------------------------------------
import re  # noqa: E402


def nrm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


NB = nrm(bundle)
ok = bad = 0
for row in (data.get("claims") or []) + (data.get("proposed_fields") or []):
    span = nrm(row.get("evidence_span"))
    row["_span_verbatim"] = bool(span) and span in NB
    ok += row["_span_verbatim"]
    bad += (not row["_span_verbatim"])
json.dump(data, open(f"h15_structured_{SUBJECT}.json", "w"), indent=2)
print(f"  claims={len(data.get('claims') or [])} proposed={len(data.get('proposed_fields') or [])} "
      f"negatives={len(data.get('negatives_and_risks') or [])} | spans verbatim {ok} / failed {bad}")
C.timing_record(f"H15_structure_{SUBJECT}", time.time() - t0, "one gpt-5-mini call")
print(f"H15[{SUBJECT}] {round(time.time()-t0,1)}s spend={C.total_spend()}")
