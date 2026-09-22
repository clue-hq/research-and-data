"""H7 — targeted gap searches for what the ONE deep call marked NOT FOUND.

The deep-reasoning call returned 30 NOT FOUND markers. The expensive ones for a Conduit sale are
the technology layer (PMS, guest messaging, who owns IT), the ITR claim, the labor picture and the
negatives. Cheap Exa searches beat a second deep call here because each gap is a narrow,
nameable question.

Note: the company's own LinkedIn post already names a VP of Information Technology whom the deep
call marked NOT FOUND — so the technology seat is the first thing to nail down.
"""
import json
import sys
import time

sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

QUERIES = [
    ("it_seat", "\"Hotel Equities\" \"Stephen Hahn\" vice president information technology hotel "
                "management magazine", 10),
    ("pms_stack", "\"Hotel Equities\" property management system PMS Opera OR FOSSE OR OnQ OR "
                  "Lightspeed OR choiceADVANTAGE hotel technology", 10),
    ("guest_messaging", "\"Hotel Equities\" guest messaging texting Canary OR Kipsu OR Akia OR "
                        "Quore OR Actabl OR Medallia OR Revinate technology partner", 10),
    ("he_labs", "\"HE Labs\" Hotel Equities innovation incubation division Brian Jenkins AI "
                "workflows technology", 10),
    ("itr_marriott", "\"Hotel Equities\" Marriott \"intent to recommend\" number one franchise "
                     "management company ranking", 10),
    ("sls_pipeline", "\"Hotel Equities\" SLS Punta del Este operator 2029 OR new openings pipeline "
                     "2026 management contract", 10),
    ("labor", "\"Hotel Equities\" front desk staffing labor shortage turnover hiring guest "
              "services hourly associates", 10),
    ("negatives", "\"Hotel Equities\" lawsuit OR settlement OR WARN notice OR layoffs OR receiver "
                  "OR foreclosure OR dispute owner hotel", 10),
    ("al_smith_voice", "Albert Smith OR \"Al Smith\" Hotel Equities chief operating officer "
                       "simplicity consistent luxury service at scale blog", 10),
    ("rafter_writing", "Ben Rafter Hotel Executive article future of hotel management OR Skift "
                       "technologies owner margins Hotel Equities", 10),
]

t_all = time.time()
res = {}
for label, q, n in QUERIES:
    out = C.exa({"query": q, "type": "auto", "numResults": n,
                 "contents": {"text": {"maxCharacters": 3000}}}, label=f"h7_{label}")
    rows = [{"url": x.get("url"), "title": x.get("title"), "published": x.get("publishedDate"),
             "text_head": (x.get("text") or "")[:1600]} for x in (out.get("results") or [])]
    res[label] = {"query": q, "cost_usd": (out.get("costDollars") or {}).get("total"),
                  "n": len(rows), "results": rows}
    print(f"\n[{label}] {len(rows)} results")
    for x in rows:
        print(f"   - {x['published'] or '?':10.10s} {(x['title'] or '')[:92]}")
        print(f"     {x['url']}")

json.dump(res, open("h7_gap_searches.json", "w"), indent=2)
C.timing_record("H7_gap_searches", time.time() - t_all, f"{len(QUERIES)} targeted exa searches")
print(f"\nH7 {round(time.time()-t_all,1)}s spend={C.total_spend()}")
