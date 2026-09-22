"""H14 — read, in full, the primary pages the per-person deep calls surfaced.

The deep calls quoted from these pages; this fetches the pages themselves so every quote that
reaches a deliverable can be span-checked against the source text in code, not trusted from a
model's summary.
"""
import json
import sys
import time

sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

PAGES = [
    # the buying process, in the company's own words — the single most important page for Conduit
    "https://www.hotelequities.com/he-labs.htm",
    "https://www.hotelequities.com/blog/hotel-equities-ceo-talks-he-labs--our-new-innovation-and-incubation-division/",
    # the COO's consistency-at-scale thesis
    "https://www.hotelequities.com/blog/al-smith-discusses-how-simplicity-drives-consistent-luxury-service-at-scale/",
    "https://www.hotelequities.com/files/6564/Hotel_Equities_Names_Al_Smith_as_President.pdf",
    # the technology seat, in his own words
    "https://hotelmanagement.mydigitalpublication.com/june-july-2026/page-13",
    # the CEO on technology and culture
    "https://www.hotelinvestmenttoday.com/Deals/Management/Hotel-Equities-new-CEO-charts-path",
    "https://www.travelmediagroup.com/190-tmg-hospitality-trailblazers-ben-rafter/",
    "https://novacancynews.com/springboards-ben-rafter-on-building-smarter-faster-and-more-human-hotels/",
    "https://www.hotelequities.com/blog/hotel-equities-ceo-ben-rafter-joins-american-hotel-and-lodging-associations-board-of-directors/",
    # the champion's pre-merger biography (hometown, travel, tennis pro)
    "https://www.springboardhospitality.com/team/",
    # portfolio + outdoor
    "https://www.hotelequities.com/our-hotels.htm",
    "https://www.hotelequities.com/blog/hotel-equities-selected-to-operate-postcard-cabins/",
]

t0 = time.time()
res = C.exa_contents(PAGES, label="h14_key_pages", text_chars=20000, livecrawl="preferred",
                     timeout=300)
out = {}
for x in (res.get("results") or []):
    txt = x.get("text") or ""
    out[x.get("url")] = {"title": x.get("title"), "published": x.get("publishedDate"),
                         "chars": len(txt), "text": txt[:26000]}
    print(f"  {len(txt):>6} chars  {(x.get('publishedDate') or '?')[:10]:10s}  {x.get('url')}")

missing = [u for u in PAGES if not any(u.rstrip('/') == k.rstrip('/') for k in out)]
print(f"\n  not returned: {len(missing)}")
for u in missing:
    print("   -", u)

json.dump({"pages": out, "missing": missing, "statuses": res.get("statuses")},
          open("h14_key_pages.json", "w"), indent=2)
C.timing_record("H14_key_pages", time.time() - t0, f"{len(PAGES)} primary pages")
print(f"\nH14 {round(time.time()-t0,1)}s spend={C.total_spend()}")
