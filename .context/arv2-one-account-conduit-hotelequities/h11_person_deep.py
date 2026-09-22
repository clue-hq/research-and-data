"""H11 — one Exa deep-reasoning call per confirmed committee member (<=5 total).

Usage: python3 h11_person_deep.py <person_key>

The prompt is the personal-depth charter from .context/arv2-person-depth/BRIEF.md, target-locked
to the exact person at the exact employer, with same-name exclusions named. The SENSITIVITY FLOOR
is absolute and is stated twice: no health, faith, politics, sexuality, family tragedy, minors —
never recorded, never used. "Not found" beats a guess, every time.
"""
import json
import sys
import time

sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

PEOPLE = {
    "ben_rafter": {
        "name": "Ben Rafter (Benjamin Rafter)",
        "title": "Chief Executive Officer, Hotel Equities",
        "linkedin": "https://www.linkedin.com/in/ben-rafter-623a702",
        "lock": ("Ben Rafter, Chief Executive Officer of Hotel Equities (hotelequities.com, "
                 "Atlanta/Alpharetta GA) since May 2025, previously Chief Executive Officer of "
                 "Springboard Hospitality (Honolulu) and before that the leader of Aqua "
                 "Hospitality / Aqua-Aston, which he took to being the largest hotel operator in "
                 "Hawaii. He co-founded Innerlinx (LiveBid), which was acquired by Amazon.com. He "
                 "serves on the Board of Directors of the American Hotel & Lodging Association "
                 "(AHLA). Hotel Equities describes him as 'a technology entrepreneur with "
                 "extensive experience scaling hotel platforms' and credits him with building "
                 "'tech-forward operating platforms, including Hospitality Intelligence (H.I.) "
                 "and HE Labs'."),
        "exclude": ("EXCLUDE any other Ben/Benjamin Rafter — the name appears on academics, "
                    "musicians and sportspeople. The subject is ONLY the hotel executive."),
        "known": ("Known long-form appearances to read first: the Hospitality Daily podcast "
                  "episodes with Josiah Mackenzie (podcast.hospitalitydaily.com/ben-rafter/, "
                  "/ben-rafter-tech/, /ben-rafter-ai-labor/, /ben-rafter-ai-hotel-performance/, "
                  "/ben-rafter-owner-economics/); the No Vacancy podcast (Aug 2025); TMG "
                  "Hospitality Trailblazers episode 190 (Dec 2025); 'Not Done with Sloan Dean' "
                  "(Dec 2025); a Skift interview (May 2026) on which technologies lift owner "
                  "margins. Find MORE than these, and find anything he has WRITTEN."),
    },
    "al_smith": {
        "name": "Albert 'Al' Smith",
        "title": "Chief Operating Officer, Hotel Equities",
        "linkedin": "https://www.linkedin.com/in/albert-smith-3aa9318",
        "lock": ("Albert ('Al') Smith, Chief Operating Officer of Hotel Equities "
                 "(hotelequities.com, Atlanta/Alpharetta GA), appointed July 2025. He most "
                 "recently served as Senior Vice President, Lifestyle Hotels at Highgate Hotels; "
                 "before that Senior Vice President at Pivot Hotels & Resorts for Davidson "
                 "Hospitality, where he created and grew their lifestyle division to twenty-five "
                 "hotels over a five-year tenure. A 20-year luxury hospitality veteran with "
                 "leadership roles at Viceroy Hotel Group, SBE and Kimpton Hotels & Restaurants."),
        "exclude": ("'Al Smith' and 'Albert Smith' are extremely common names — there are "
                    "politicians, athletes, musicians and a historic New York governor with this "
                    "name. EXCLUDE every one of them. Only the Hotel Equities / Highgate / Pivot "
                    "/ Viceroy / SBE / Kimpton hospitality executive is the subject. If you "
                    "cannot bind a source to THAT career, discard it and say so."),
        "known": ("Hotel Equities has published a blog post attributed to him about simplicity "
                  "driving consistent luxury service at scale — find it and quote it at length. "
                  "Also find his July 2025 appointment coverage (Hospitality Net appointment "
                  "79030411) and the November 2025 appointments release he is quoted in."),
    },
    "brian_jenkins": {
        "name": "Brian Jenkins",
        "title": "Head of HE Labs | EVP of Strategy, Hotel Equities",
        "linkedin": "https://www.linkedin.com/in/brianjenkins01",
        "lock": ("Brian Jenkins, Head of HE Labs and EVP of Strategy at Hotel Equities "
                 "(hotelequities.com, Atlanta/Alpharetta GA), appointed around May-June 2026. HE "
                 "Labs is the company's dedicated innovation and incubation division, focused on "
                 "'evaluating emerging technologies, developing AI-driven workflows, and "
                 "advancing new operating models that improve hotel performance'. Before "
                 "hospitality he was a strategy consultant at Capco in New York, advising "
                 "financial institutions on IT strategy, organizational restructuring, change "
                 "management and risk management."),
        "exclude": ("'Brian Jenkins' is a common name — there are academics, athletes, a "
                    "well-known airline/aviation writer and several executives at other firms. "
                    "EXCLUDE all of them. Only the Hotel Equities / HE Labs / ex-Capco subject "
                    "counts."),
        "known": ("Read the Hotel Equities announcement of his appointment to lead HE Labs and "
                  "the Hospitality Net appointment notice 79032251. Find anything he has said or "
                  "written about how he evaluates technology, what makes a pilot succeed or fail, "
                  "and what HE Labs has actually tested."),
    },
    "stephen_hahn": {
        "name": "Stephen Hahn",
        "title": "Vice President of Information Technology, Hotel Equities",
        "linkedin": "https://www.linkedin.com/in/stephen-hahn-41028112",
        "lock": ("Stephen Hahn, Vice President of Information Technology at Hotel Equities "
                 "(hotelequities.com, Atlanta/Alpharetta GA) since about October 2022. He joined "
                 "Hotel Equities through its strategic alliance with Coakley & Williams, where he "
                 "had been Chief Information Officer and a General Manager. He holds an Associate "
                 "of Arts in Hospitality Services Management, a BS in Business Administration and "
                 "a Master of Applied Computer Systems, both from University of Maryland "
                 "University College. He was featured in HOTEL MANAGEMENT Magazine in 2026 on how "
                 "Hotel Equities uses technology, automation and AI."),
        "exclude": ("EXCLUDE the oncologist/FDA commissioner Stephen Hahn, and every other "
                    "Stephen/Steve Hahn. Only the Hotel Equities IT executive is the subject."),
        "known": ("Find the HOTEL MANAGEMENT Magazine feature and quote it at length — it is the "
                  "single most valuable source for this person. Also look for any 'Tech Titan' or "
                  "similar hospitality-technology recognition, conference panels, HFTP/HTNG "
                  "involvement, and anything naming the SYSTEMS Hotel Equities runs."),
    },
    "david_rosenberg": {
        "name": "David Rosenberg",
        "title": "President, Focused Service Division, Hotel Equities",
        "linkedin": "https://www.linkedin.com/in/david-rosenberg-4a244312",
        "lock": ("David Rosenberg, President of the Focused Service Division at Hotel Equities "
                 "(hotelequities.com, Atlanta/Alpharetta GA), promoted to the role announced "
                 "10 November 2025, and at Hotel Equities since about February 2020."),
        "exclude": ("'David Rosenberg' is a common name — there is a well-known Canadian "
                    "economist, a film producer and several other executives. EXCLUDE all of "
                    "them. Only the Hotel Equities Focused Service president is the subject."),
        "known": ("Read the 10 November 2025 Hotel Equities appointments release and the CoStar "
                  "and Hotel Dive coverage of it."),
    },
}

KEY = sys.argv[1]
P = PEOPLE[KEY]

SYSTEM = f"""You are researching ONE named person for a business go-to-market record.
Today's date is 2026-09-22.

TARGET LOCK — the ONLY subject is:
  {P['lock']}

{P['exclude']}

HARD RULES
  * Every item is either a VERBATIM quote plus the URL it came from, or the words "not found".
    Never paraphrase a quote. Never infer. Never fill a gap with something plausible.
  * If a source might be a different person with the same name, DISCARD it and say which source
    you discarded and why. A same-name stranger's facts are worse than nothing.
  * SENSITIVITY FLOOR — ABSOLUTE. You must NEVER record, mention, infer or hint at: health or
    medical information, religion or faith, politics or political donations, sexuality, family
    tragedy or bereavement, or anything about children or other minors. If a source contains any
    of that, ignore it entirely and do not reference the source for that fact. This is not a
    preference; a violation makes the whole record unusable.
  * Family facts are admissible ONLY where the person published them about themselves (e.g. their
    own post announcing a milestone) and even then only the fact they chose to publish.
  * Mark anything reputationally sensitive, negative, or awkward as OUTREACH_UNSAFE and explain
    why — it may be recorded as context but must never be used in a message."""

CHARTER = f"""Produce a cited markdown dossier on {P['name']}, {P['title']}, under EXACTLY these
numbered headings. Use "not found" liberally and honestly.

{P['known']}

1. IDENTITY AND CAREER, WITH DATES. Every role with employer, exact title and start/end dates,
   newest first, and the URL naming each. What each move was for, in their own words where
   available. How long in the current seat.

2. EDUCATION. Institutions, degrees, fields, years, and any activities, societies or honours.

3. PUBLIC WRITING, TALKS, PODCASTS AND MEDIA. Every article they authored, podcast episode,
   webinar, conference panel, keynote, video or interview — with title, publisher/show, date and
   URL. Say which are the most substantive.

4. WHAT THEY OWN. Their actual scope of responsibility in this role: what reports to them, which
   budget or P&L, which decisions are theirs, and which they influence but do not own. Quote the
   company's own description of the role where it exists.

5. HOW THEY BUY AND HOW THEY THINK — the most important section. Verbatim quotes, each with URL
   and date, showing: how they evaluate technology or vendors; what they say makes a pilot or
   rollout succeed or fail; what they think about AI and automation in hotel operations; what they
   say about labor, staffing and the front line; what they say about guest experience and service
   consistency across many properties; what they say owners should demand. Give at least 5 quotes
   if the material exists, and say "not found" if it does not.

6. NON-SENSITIVE PERSONAL HOOKS, AS THEY STATE THEM. Hobbies, sports, side projects, causes,
   volunteering, boards and associations, hometown, alma-mater affiliation, awards and
   recognitions, books or podcasts they recommend, and self-published milestones. Each needs a
   verbatim quote or a precise fact plus its URL. NOTHING from the sensitivity floor above.

7. THE UNIQUE INSIGHT. The ONE thing about this person that a generic contact-enrichment database
   would never surface, with its evidence.

8. THREE GROUNDED OPENERS. Three specific opening lines a seller could honestly use, each tied to
   a named source with its URL and date. No flattery, no invented common ground.

9. WHAT YOU COULD NOT FIND. Be explicit and complete — this section is as valuable as the others.

10. DISCARDED SAME-NAME SOURCES. Every source you rejected because it was a different person with
    this name, with its URL and the reason.
"""

t0 = time.time()


def run(label):
    return C.exa({
        "query": CHARTER, "type": "deep-reasoning", "systemPrompt": SYSTEM,
        "numResults": 22, "stream": False,
        "contents": {"text": {"maxCharacters": 10000},
                     "highlights": {"query": f"{P['name']} {P['title']} quotes interview podcast "
                                             "technology AI labor guest experience career",
                                    "maxCharacters": 2000}},
        "outputSchema": {"type": "object", "required": ["report"], "additionalProperties": False,
                         "properties": {"report": {
                             "type": "string",
                             "description": "The cited markdown dossier answering every numbered "
                             "section of the charter, with a verbatim quote and URL behind every "
                             "assertion and explicit 'not found' markers."}}},
    }, label=label, timeout=1500, est_usd=0.05)


resp = run(f"h11_person_{KEY}")
text = C.deep_report_text(resp)
cost = (resp.get("costDollars") or {}).get("total") or 0
n = len(resp.get("results") or [])
if len(text) < 2500 or (n <= 9 and cost <= 0.016):
    print(f"  SILENT-FAIL SIGNATURE (n={n}, cost={cost}, chars={len(text)}) -> one retry")
    resp = run(f"h11_person_{KEY}_retry")
    t2 = C.deep_report_text(resp)
    if len(t2) > len(text):
        text = t2
open(f"report_person_{KEY}.md", "w").write(text)
el = time.time() - t0
C.timing_record(f"H11_person_deep_{KEY}", el, "one deep-reasoning call")
json.dump({"person": P["name"], "chars": len(text),
           "not_found": text.lower().count("not found"),
           "elapsed_s": round(el, 1), "n_results": len(resp.get("results") or []),
           "cost_usd": (resp.get("costDollars") or {}).get("total"),
           "result_urls": [r.get("url") for r in (resp.get("results") or [])]},
          open(f"h11_person_{KEY}_summary.json", "w"), indent=2)
print(f"\nH11[{KEY}] {round(el,1)}s chars={len(text)} spend={C.total_spend()}")
