"""Phase 3 — ONE Exa deep-reasoning call per person, the PERSONAL-DEPTH charter as the prompt.

Wire facts reused from the smoke test (do not rediscover): type="deep-reasoning";
outputSchema must carry exactly ONE string property; contents block + numResults ~20;
stream false; pace ~1/s; retry 429.

Every call is target-locked (exact person at exact employer + same-name exclusions) and
carries the Phase-1 URLs as "already-known sources - read these first".
"""

import concurrent.futures as cf
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p_lib as C  # noqa: E402
from roster import PEOPLE  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TRIAGE = json.load(open(os.path.join(HERE, "sweep_triage.json")))
MEDIA = json.load(open(os.path.join(HERE, "media_index.json")))
LINKEDIN = json.load(open(os.path.join(HERE, "linkedin_indexed.json")))

SYSTEM = """You are a meticulous, source-bound researcher building a PERSONAL dossier on ONE
named individual for B2B relationship-building. You are NOT writing marketing copy.

TARGET LOCK — the subject is EXACTLY this person and no one else:
{lock}

SAME-NAME EXCLUSIONS — these are DIFFERENT people. If a source is about them, say so and discard it:
{exclusions}

ABSOLUTE RULES
1. Every single assertion carries (a) a VERBATIM quote in double quotes from the source and
   (b) the source URL. For audio/video also give the timestamp if the source shows one.
2. If you cannot find something, write exactly "NOT FOUND". An empty, honest field is a CORRECT
   answer. Guessing, inferring, or padding is the only real failure. Do not write "likely",
   "probably", or "appears to" in place of evidence.
3. Never attribute to the target something said by a colleague, a company account, or a
   same-name person. If a source is a company post that merely mentions them, say so.
4. SENSITIVITY FLOOR — HARD. Do NOT record, quote, hint at, or infer ANY of the following, even
   if publicly available: health or medical information; religion or faith; political opinions,
   party affiliation or activism; sexuality or gender identity; family tragedy, bereavement,
   divorce or illness; anything about children or other minors; trade-union membership; criminal
   or legal matters. If a source contains these, ignore that part silently. Do not explain what
   you omitted.
5. Military/intelligence service, sport, and the arts ARE allowed as background. If a person has
   publicly discussed their own national origin or migration story in a first-person interview,
   you MAY record it as biography, but you MUST tag that line "[ORIGIN - NOT AN OUTREACH HOOK]".
6. Family milestones count ONLY if the person announced them THEMSELVES (their own wedding /
   new-job / new-baby post). Never search for or infer family details from any other source.
"""

CHARTER = """SUBJECT: {name}{alias}, {title} at {company} ({domain}). LinkedIn: {linkedin}.
Stated location: {location}.

ALREADY-KNOWN SOURCES — read these FIRST, they are confirmed to be about the target:
{known}

KNOWN LONG-FORM MEDIA where this person speaks (mine these for verbatim quotes):
{media}

Produce an exhaustive, cited dossier with these EXACT numbered sections. Use "NOT FOUND" liberally.

1. BACKGROUND
   - Hometown / where they grew up.
   - Alma mater(s): institution, degree, subject, years, and any student activities, societies,
     sports teams, or awards while there.
   - Early career: their FIRST jobs and how they got into this field, in their own words if possible.
   - Military, competitive-sport, music/arts, or other non-corporate background.
   - Languages they speak.

2. LIFE OUTSIDE WORK — ONLY AS THEY THEMSELVES STATE IT
   - Hobbies and sports they have posted about or put in a bio (running, climbing, cooking,
     gaming, etc.). Quote them.
   - Pets they have posted about.
   - Self-announced milestones (their own wedding / relocation / new-job / anniversary posts).
   - Causes, volunteering, boards, mentoring, pledges, alumni service.
   - Side projects, newsletters, communities they run or built.
   - Books, podcasts, tools or people they have publicly recommended.

3. VOICE — 3 to 5 VERBATIM QUOTES from LONG-FORM material
   Podcasts, webinars, conference talks, interviews, AMAs, authored articles, Substack/Medium.
   For each: the quote, the source name, the URL, the date, and a timestamp if it is audio/video.
   Prefer quotes that reveal HOW THEY THINK, not company boilerplate. If the only long-form
   material is a company press quote, say so explicitly.

4. PROFESSIONAL IDENTITY
   - What they personally own / are accountable for.
   - What they are visibly proud of (quote it).
   - Stated pet peeves, things that annoy them, things they say are broken.
   - How they buy or evaluate vendors/tools; any tools they have named publicly.

5. UNIQUE INSIGHT — the ONE thing about this person that a generic enrichment tool
   (Apollo, ZoomInfo, Clay) would NEVER surface. One paragraph, quote-backed. If there is
   genuinely nothing beyond a standard profile, say "NOT FOUND — thin public footprint" and
   say what channels you checked.

6. THREE COLD-APPROACH OPENERS
   Each opener: (a) the one-sentence opener text, (b) the SPECIFIC hook it is grounded in,
   (c) the verbatim quote behind that hook, (d) the URL. No generic openers. No flattery.
   Do not use anything tagged [ORIGIN - NOT AN OUTREACH HOOK].

7. WHAT WE COULD NOT FIND
   Name the categories that came back empty and the source types you checked to conclude that.

8. SAME-NAME CONTAMINATION LOG
   List every source you encountered that is about a DIFFERENT person of the same name, with URL,
   and say how you ruled it out. This section proves the target lock held.
"""


def known_block(key):
    t = TRIAGE.get(key) or {}
    urls = []
    for r in (t.get("strong_hits") or [])[:22]:
        urls.append(f"- {r['url']}  ({(r.get('title') or '')[:90]})")
    for r in (t.get("named_only_hits") or [])[:8]:
        urls.append(f"- {r['url']}  ({(r.get('title') or '')[:90]}) [names them; employer unconfirmed]")
    li = LINKEDIN.get(key) or {}
    if li.get("chars"):
        urls.append(f"- {li['url']}  (their LinkedIn profile, indexed copy available)")
    return "\n".join(urls) or "NONE"


def media_block(key):
    rows = []
    for it in MEDIA["items"]:
        if it["person"] != key:
            continue
        if str(it.get("target_speaks", "")).startswith("NO"):
            rows.append(f"- (DO NOT USE) {it['url']} — {it.get('target_speaks')}")
            continue
        rows.append(f"- {it['url']} — \"{(it.get('title') or '')[:95]}\" "
                    f"({it.get('duration_s')}s) — target_speaks: {it.get('target_speaks')}")
    return "\n".join(rows) or "NONE LOCATED"


def one(p):
    lock = (f"{p['name']}"
            + (f" (also published as {', '.join(p['aliases'])})" if p["aliases"] else "")
            + f", {p['title']} at {p['company']} ({p['domain']}), LinkedIn {p['linkedin']}, "
              f"located {p['location']}."
            + (f" Known prior employers: {p['known_history']}." if p["known_history"] else ""))
    q = CHARTER.format(
        name=p["name"],
        alias=(f" (also published as {', '.join(p['aliases'])})" if p["aliases"] else ""),
        title=p["title"], company=p["company"], domain=p["domain"],
        linkedin=p["linkedin"], location=p["location"],
        known=known_block(p["key"]), media=media_block(p["key"]))
    t0 = time.time()
    resp = C.exa({
        "query": q,
        "type": "deep-reasoning",
        "systemPrompt": SYSTEM.format(lock=lock, exclusions=p["exclusions"]),
        "numResults": 20,
        "stream": False,
        "contents": {
            "text": {"maxCharacters": 10000},
            "highlights": {"query": f"{p['name']} background hometown university hobbies podcast "
                                    f"interview quote personal", "maxCharacters": 2000},
        },
        "outputSchema": {
            "type": "object", "required": ["report"], "additionalProperties": False,
            "properties": {"report": {
                "type": "string",
                "description": "The exhaustive cited personal dossier answering every numbered "
                               "section of the charter, with a verbatim quote and URL behind "
                               "every assertion and explicit NOT FOUND markers."}},
        },
    }, label=f"p3_deep_{p['key']}", timeout=900, est_usd=0.05)
    text = C.deep_report_text(resp)
    open(os.path.join(HERE, f"person_{p['key']}.md"), "w").write(text)
    el = time.time() - t0
    C.timing_record(f"P3_deep_{p['key']}", el, "exa deep-reasoning, personal charter, 1 call")
    return {"key": p["key"], "chars": len(text), "not_found": text.count("NOT FOUND"),
            "elapsed_s": round(el, 1), "http": resp.get("_http_status"),
            "cost_usd": (resp.get("costDollars") or {}).get("total")}


def main():
    only = sys.argv[1:] or [p["key"] for p in PEOPLE]
    people = [p for p in PEOPLE if p["key"] in only]
    t0 = time.time()
    out = []
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        futs = []
        for i, p in enumerate(people):
            futs.append(ex.submit(one, p))
            time.sleep(1.2)  # pace ~1/s
        for f in cf.as_completed(futs):
            try:
                out.append(f.result())
            except Exception as e:  # noqa: BLE001
                print("  !! deep failed:", type(e).__name__, e, flush=True)
    el = time.time() - t0
    out.sort(key=lambda r: r["key"])
    json.dump(out, open(os.path.join(HERE, "p3_deep_summary.json"), "w"), indent=2)
    C.timing_record("P3_TOTAL", el, f"{len(people)} deep-reasoning calls, 3 threads")
    print(f"\nPhase 3 {el:.1f}s  spend=${C.total_spend()}")
    for r in out:
        print(f"  {r['key']:<20} {r['chars']:>7} chars  {r['not_found']:>3} NOT FOUND  "
              f"{r['elapsed_s']:>6}s  ${r['cost_usd']}")


if __name__ == "__main__":
    main()
