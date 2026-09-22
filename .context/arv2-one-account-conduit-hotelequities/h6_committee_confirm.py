"""H6 — confirm the committee against PRIMARY pages (v3 protocol step 1, continued).

Reads, in full, the pages that actually name people and dates: the company's own appointment
posts (July 2025 post-merger, August 2025, November 2025 divisions, the May 2026 HE Labs
innovation-division post), the Hospitality Net appointment notices (dated, one person each), the
trade-press write-ups, and the company's LinkedIn post about its VP of Information Technology.

No AI Ark here. A person is only admitted to the committee if a NON-AI-Ark URL names them in the
role at Hotel Equities.
"""
import json
import re
import sys
import time

sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

PAGES = [
    # company's own appointment / leadership posts
    "https://www.hotelequities.com/blog/hotel-equities-strengthens-leadership-team-with-key-executive-appointments-across-new-divisions/",
    "https://www.hotelequities.com/blog/hotel-equities-announces-key-leadership-appointments-after-strategic-merger-with-springboard-hospitality/",
    "https://www.hotelequities.com/blog/hotel-equities-announces-key-executive-appointments-across-operations--finance--and-marketing-teams/",
    "https://www.hotelequities.com/blog/hotel-equities-appoints-brian-jenkins-to-lead-he-labs--the-management-companys-new-innovation-division/",
    "https://www.hotelequities.com/meet-our-team.htm",
    # merger primary
    "https://www.hotelequities.com/blog/hotel-equities-and-springboard-hospitality-announce-strategic-merger/",
    # dated appointment notices (one person each, with a date)
    "https://www.hospitalitynet.org/appointment/79030411.html",
    "https://www.hospitalitynet.org/appointment/79032251/brian-jenkins",
    # trade press on the November 2025 wave
    "https://www.hoteldive.com/news/hotel-equities-multiple-executive-changes/805275/",
    "https://www.costar.com/article/1415665623/us-hotel-hires-promotions-hotel-equities-promotes-two-executives-to-division-presidents",
    # the technology seat
    "https://www.linkedin.com/posts/hotel-equities_hotelequities-hospitalitytechnology-hotelmanagement-activity-7471283773595238400-nH7w",
    "https://people.equilar.com/bio/person/stephen-hahn-hotel-equities/41982685",
]

TITLE_NEAR = re.compile(
    r"([A-Z][a-zA-Z'\-]+(?:\s+[A-Z]\.)?\s+[A-Z][a-zA-Z'\-]+)"
    r"[^.\n]{0,60}?"
    r"((?:Co-)?Chairman|Chief [A-Z][a-z]+(?:\s[A-Z][a-z]+)?\s?Officer|"
    r"President,?\s?(?:[A-Z][A-Za-z ]{0,30}Division)?|"
    r"(?:Executive |Senior |)Vice President(?:\s+of\s+[A-Z][A-Za-z& ]{2,40}|,?\s+[A-Z][A-Za-z& ]{2,40})?|"
    r"Head of HE Labs|General Counsel)")

t_all = time.time()
res = C.exa_contents(PAGES, label="h6_committee_pages", text_chars=16000,
                     livecrawl="preferred", timeout=300)
rows = []
people = {}
for x in (res.get("results") or []):
    txt = x.get("text") or ""
    rows.append({"url": x.get("url"), "title": x.get("title"),
                 "published": x.get("publishedDate"), "chars": len(txt)})
    print(f"  {len(txt):>6} chars  {x.get('publishedDate') or '?':10.10s}  {x.get('url')}")
    if "hotel equities" not in txt.lower() and "hotelequities" not in (x.get("url") or ""):
        continue
    for nm, ti in TITLE_NEAR.findall(txt):
        ti = re.sub(r"\s+", " ", ti).strip(" ,.")
        if len(ti) < 6:
            continue
        people.setdefault(nm, {}).setdefault(ti, set()).add(x.get("url"))

print("\n=== people named on PRIMARY pages (name -> title -> urls) ===")
flat = {}
for nm, tis in people.items():
    flat[nm] = {ti: sorted(u for u in urls if u) for ti, urls in tis.items()}
for nm, tis in sorted(flat.items(), key=lambda kv: -sum(len(v) for v in kv[1].values())):
    for ti, urls in sorted(tis.items(), key=lambda kv: -len(kv[1])):
        print(f"   {nm:26s} | {ti[:62]:62s} | {len(urls)}")

full = {"pages": rows, "people_named": flat,
        "page_text": {x.get("url"): (x.get("text") or "")[:24000]
                      for x in (res.get("results") or [])},
        "statuses": res.get("statuses")}
json.dump(full, open("h6_committee_confirm.json", "w"), indent=2)
C.timing_record("H6_committee_confirm", time.time() - t_all, f"{len(PAGES)} primary pages")
print(f"\nH6 {round(time.time()-t_all,1)}s pages={len(rows)}/{len(PAGES)} spend={C.total_spend()}")
