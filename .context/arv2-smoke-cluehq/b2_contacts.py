"""B2 — contacts for the TOP-3 by RESEARCHED intent: Zafran, Cogent, Harmonic.

Researched intent (not Agent A's prediction) put Vendelux out of the top-3 because its own
Series-B material shows it already ships campaign generation + outbound orchestration + booking
agents (a D6 competitor-overlap risk), and Harmonic's ABM req turned out to be actively recruited
three weeks ago rather than stale.

One Exa deep-reasoning call on the PRIMARY contact per account (the person who owns the ABM seat),
then AI Ark email export for <=2 contacts per account, <=6 total. NO phone calls (credit discipline).
"""

import json
import sys
import time

sys.path.insert(0, ".")
import b_lib as C  # noqa: E402

PRIMARY = {
    "zafran": {
        "name": "Vari Kaur (Varinder Kaur)",
        "title": "Head of Growth Marketing, Zafran Security",
        "linkedin": "https://www.linkedin.com/in/varinderkaur",
        "lock": """Vari Kaur (also published as Varinder Kaur), Head of Growth Marketing at
Zafran Security (zafran.io, the AI-native threat-exposure-management cybersecurity company in New
York). She is based in Easton, Pennsylvania, has ~20 years of experience, and previously held
Director, Demand Generation & Technology at Secureworks, Director Demand Generation at ReSource Pro,
and Director Demand Generation and Technology at Axiom. She reports into Nick Fisher, VP Marketing.
She is the hiring manager for the "Senior Manager, ABM & Integrated Campaigns" req.
EXCLUDE anyone else named Kaur, and anyone at a different company.""",
        "probe": """SPECIFIC QUESTIONS: What has she publicly written or said about demand
generation, ABM, account research, campaign production, small teams, budgets, or AI in marketing?
Quote her posts verbatim with URLs and dates. What did she do at Secureworks and what scale of
programs did she run? Has she publicly named any tools she uses? Has she spoken at any events or
on any podcasts? What does she say about the ABM role she is hiring for?""",
    },
    "cogent": {
        "name": "Alexander Semien",
        "title": "Head of Growth, Cogent Security",
        "linkedin": "https://www.linkedin.com/in/alexander-semien",
        "lock": """Alexander Semien, Head of Growth at Cogent Security, Inc. (cogent.com — the San
Francisco AI vulnerability-management startup founded 2024, NOT Cogent Communications the ISP, NOT
Cogent Infotech, NOT sigma-Cogent Solutions). He joined Cogent in August 2025 and posts publicly and
frequently on LinkedIn. EXCLUDE anyone at any other Cogent-named company.""",
        "probe": """SPECIFIC QUESTIONS: Quote his public LinkedIn posts verbatim with dates and
URLs — especially anything about hiring for growth, marketing team building, what he told CEO
Vineet Edupuganti when he interviewed, Black Hat, AI in cybersecurity marketing, pipeline, ABM,
account research, or the tools his team uses. What was he doing before Cogent and for how long?
Where is he based? Has he spoken at conferences (e.g. THREATCON1)? What is his relationship to
Cameron Coles, VP of Marketing at Cogent?""",
    },
    "harmonic": {
        "name": "Ana Corio (Anastasia Corio)",
        "title": "Director of Demand Generation, Harmonic Security",
        "linkedin": "https://www.linkedin.com/in/anastasiacorio",
        "lock": """Ana Corio (Anastasia Corio), Director of Demand Generation at Harmonic Security
(harmonic.security — the AI data-security / AI-governance company founded 2023, NOT Harmonic Inc
NASDAQ HLIT, NOT harmonic.fun). She joined Harmonic in September 2024, is based in San Francisco,
and was previously Director of Demand Generation at Material Security (Jul 2021 - Sep 2024), where
she was the first marketing hire. EXCLUDE anyone at any other Harmonic-named company.""",
        "probe": """SPECIFIC QUESTIONS: Quote her public LinkedIn posts verbatim with dates and
URLs — especially the hiring posts for the ABM (account-based marketing) manager role, what she
says the role covers, and anything about demand generation, intent/signal-based marketing, budgets,
small teams, direct mail, events, or tools. Was the ABM Manager, Strategic Accounts role FILLED —
is there anyone now at Harmonic Security with an ABM or campaign title, named? What did she build
at Material Security? Who else is on the Harmonic marketing team by name (she has publicly named
Michael Marriott, Mariana Padilla, Lexy Marchbank, Tyler Chonoles, Maya Smith, Jackson Harrower)
and what are their titles?""",
    },
}

SYSTEM = """You are a B2B contact researcher producing an evidence-grounded profile on ONE named
person for a go-to-market team. Today is 2026-08-31.

TARGET LOCK — the ONLY subject is:
{lock}

RULES
  * Every factual assertion carries a VERBATIM quote and the URL it came from.
  * If you cannot find something, write "NOT FOUND". Never guess, never infer, never compose a
    plausible-sounding post they did not write.
  * SAME-NAME DISCIPLINE: only admit material where the person's CURRENT employer matches the lock
    exactly. Name and discard any same-name person you encounter.
  * EXCLUDE special-category personal data entirely: health, religion, politics, sexual
    orientation, ethnicity, union membership, criminal matters, family/bereavement, home address,
    personal phone, personal email. Do not report them even if public.
  * Professional public material only: role, tenure, employer history, public posts, talks,
    publications, stated professional interests and communication style.
"""

CHARTER = """Produce a cited markdown profile of {name} — {title}.

1. IDENTITY — full name, exact current title, employer, start date, location, LinkedIn URL, and any
   same-name person you excluded.
2. CAREER HISTORY — every prior employer with role and dates, and the source for each.
3. WHAT THEY OWN TODAY — scope of the role, who they report to, who reports to them, team size.
4. PUBLIC VOICE — every public post, talk, podcast, article or quote you can find, VERBATIM, with
   date and URL. This is the most important section: quote generously and exactly.
5. COMMUNICATION STYLE — how they write (tone, length, humour, emoji, formality), evidenced by the
   quotes above, not asserted.
6. STATED PROFESSIONAL INTERESTS & PRIORITIES — what they say matters to them at work.
7. HOOKS FOR A COLD APPROACH — the three most specific, most recent, professionally-appropriate
   things a seller could reference, each with its quote and URL. Nothing personal or sensitive.
8. WHAT WOULD ANNOY THEM — any stated pet peeve about vendors, outreach, or marketing practice.
{probe}
"""

only = sys.argv[1:] or list(PRIMARY)
t_all = time.time()
out_summary = {}

for key in only:
    p = PRIMARY[key]
    t0 = time.time()
    resp = C.exa(
        {
            "query": CHARTER.format(name=p["name"], title=p["title"], probe=p["probe"]),
            "type": "deep-reasoning",
            "systemPrompt": SYSTEM.format(lock=p["lock"]),
            "numResults": 20,
            "stream": False,
            "contents": {
                "text": {"maxCharacters": 10000},
                "highlights": {"query": f"{p['name']} {p['title']} posts career",
                               "maxCharacters": 2000},
            },
            "outputSchema": {
                "type": "object", "required": ["report"], "additionalProperties": False,
                "properties": {"report": {
                    "type": "string",
                    "description": "The cited markdown profile answering every numbered section, "
                                   "with a verbatim quote and URL behind every assertion and "
                                   "explicit NOT FOUND markers.",
                }},
            },
        },
        label=f"b2_contact_{key}", timeout=900, est_usd=0.05,
    )
    text = C.deep_report_text(resp)
    open(f"report_contact_{key}.md", "w").write(text)
    el = time.time() - t0
    C.timing_record(f"B2_contact_deep_{key}", el, f"{p['name']}")
    out_summary[key] = {"person": p["name"], "chars": len(text),
                        "not_found": text.count("NOT FOUND"), "elapsed_s": round(el, 1),
                        "cost_usd": (resp.get("costDollars") or {}).get("total")}
    print(f"  -> {key}/{p['name']}: {len(text)} chars, {text.count('NOT FOUND')} NOT FOUND, "
          f"{round(el,1)}s")
    time.sleep(1.2)

json.dump(out_summary, open("b2_contact_summary.json", "w"), indent=2)
C.timing_record("B2_contact_deep_TOTAL", time.time() - t_all, f"{len(only)} contact deep calls")
print(f"\nPHASE B2-deep {round(time.time()-t_all,1)}s spend={C.total_spend()} "
      f"credits={C.total_credits()}")
