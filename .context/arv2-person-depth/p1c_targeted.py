"""Phase 1c — (a) one /contents batch over the 10 locked LinkedIn profiles (indexed copy),
(b) one targeted per-person 'prior employer + long-form voice' search, because the generic
A1-A11 angles under-serve people whose public voice lives under a FORMER employer's brand.
"""

import concurrent.futures as cf
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p_lib as C  # noqa: E402
from roster import BY_KEY, PEOPLE  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

TARGETED = {
    "vari_kaur": '"Vari Kaur" OR "Varinder Kaur" Secureworks Ivanti demand generation webinar panel speaker interview quote',
    "nick_fisher": '"Nick Fisher" cybersecurity marketing executive Zafran Snyk OR Rapid7 OR Recorded Future interview panel webinar',
    "sanaz_yashar": '"Sanaz Yashar" Mandiant Cybereason "Unit 8200" background career keynote fireside interview',
    "alexander_semien": '"Alexander Semien" growth marketing career background Black Hat post interview webinar previous company',
    "cameron_coles": '"Cameron Coles" Netskope OR Skyhigh Networks OR McAfee cloud security report author webinar interview',
    "vineet_edupuganti": '"Vineet Edupuganti" Stanford PhD research bioelectronics Siemens Competition background before Cogent',
    "ana_corio": '"Ana Corio" OR "Anastasia Corio" Material Security demand generation podcast webinar panel interview',
    "tyler_chonoles": '"Tyler Chonoles" marketing demand generation career background university interview webinar',
    "alastair_paterson": '"Alastair Paterson" Digital Shadows founder background university career keynote interview',
    "mandar_marathe": '"Mandar Marathe" UPTIQ OR Cognizant OR fintech marketing background webinar interview India',
}


def run_targeted(key):
    q = TARGETED[key]
    resp = C.exa({"query": q, "type": "auto", "numResults": 10,
                  "contents": {"text": {"maxCharacters": 1500}}},
                 label=f"p1c_{key}_A12_targeted", est_usd=0.01, timeout=180)
    return {"person": key, "angle": "A12_targeted_prior_voice", "query_verbatim": q,
            "include_domains": None, "label": f"p1c_{key}_A12_targeted",
            "http": resp.get("_http_status"), "elapsed_s": resp.get("_elapsed_s"),
            "cost_usd": (resp.get("costDollars") or {}).get("total"),
            "n_results": len(resp.get("results") or []),
            "results": [{"url": r.get("url"), "title": r.get("title"),
                         "published": r.get("publishedDate"), "author": r.get("author"),
                         "text_chars": len(r.get("text") or ""),
                         "text_head": (r.get("text") or "")[:600]}
                        for r in (resp.get("results") or [])]}


def main():
    t0 = time.time()
    # (a) LinkedIn indexed copies -- one batched call
    li = [p["linkedin"] for p in PEOPLE]
    contents = C.exa_contents(li, label="p1c_linkedin_profiles", text_chars=9000, timeout=300)
    got = {r.get("url", "").rstrip("/"): r for r in (contents.get("results") or [])}
    prof = {}
    for p in PEOPLE:
        r = got.get(p["linkedin"].rstrip("/")) or {}
        prof[p["key"]] = {"url": p["linkedin"], "title": r.get("title"),
                          "chars": len(r.get("text") or ""), "text": r.get("text") or ""}
    json.dump(prof, open(os.path.join(HERE, "linkedin_indexed.json"), "w"), indent=2)
    print("  linkedin indexed chars:", {k: v["chars"] for k, v in prof.items()})

    # (b) targeted searches
    rows = []
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(run_targeted, k): k for k in TARGETED}
        for f in cf.as_completed(futs):
            rows.append(f.result())
    rows.sort(key=lambda r: r["person"])

    sweep_path = os.path.join(HERE, "sweep_digest.json")
    sweep = json.load(open(sweep_path))
    sweep = [r for r in sweep if r.get("angle") != "A12_targeted_prior_voice"] + rows
    sweep.sort(key=lambda r: (r["person"], r["angle"]))
    json.dump(sweep, open(sweep_path, "w"), indent=2)

    el = time.time() - t0
    C.timing_record("P1c_targeted", el, "1 contents batch (10 LinkedIn) + 10 targeted searches")
    print(f"\nPhase 1c done in {el:.1f}s. spend=${C.total_spend()}")
    for r in rows:
        print(f"  {r['person']:<20} n={r['n_results']}")


if __name__ == "__main__":
    main()
