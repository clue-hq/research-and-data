"""Phase 2d — pull the full indexed transcript for the one long-form item that has one,
and hunt for published transcript pages for the two podcast items whose target verifiably
speaks (Alastair x2, Sanaz x1). Records honestly when a transcript simply does not exist.
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p_lib as C  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TR = os.path.join(HERE, "transcripts")


def main():
    t0 = time.time()
    path = os.path.join(HERE, "media_resolved.json")
    resolved = json.load(open(path))
    byid = {r["id"]: r for r in resolved}
    found = {}

    # 1) full-length indexed transcript for the 31-min Vineet interview
    full = C.exa_contents(["https://www.youtube.com/watch?v=_OHZyK0nugs"],
                          label="p2d_vin_ep297_full", text_chars=120000, timeout=240)
    res = (full.get("results") or [{}])[0]
    txt = res.get("text") or ""
    if txt:
        open(os.path.join(TR, "vin_ep297_exa_page.txt"), "w").write(
            f"# EXA INDEXED COPY (full pull) of https://www.youtube.com/watch?v=_OHZyK0nugs\n"
            f"# chars: {len(txt)}\n\n{txt}")
        byid["vin_ep297"]["transcript"]["exa_fallback"]["exa_indexed_chars"] = len(txt)
        byid["vin_ep297"]["transcript"]["exa_fallback"]["full_pull"] = True
    print(f"  vin_ep297 full pull: {len(txt)} chars")

    # 2) hunt published transcript pages
    hunts = {
        "ala_gcsp265": 'Cloud Security Podcast by Google EP265 "Beyond Shadow IT" transcript Alastair Paterson Harmonic Security',
        "san_boardroom": 'Boardroom Club podcast "Sanaz Yashar" Zafran Security episode transcript AI Summit',
    }
    for mid, q in hunts.items():
        r = C.exa({"query": q, "type": "auto", "numResults": 8,
                   "contents": {"text": {"maxCharacters": 6000}}},
                  label=f"p2d_hunt_{mid}", est_usd=0.01, timeout=180)
        hits = []
        for x in (r.get("results") or []):
            t = x.get("text") or ""
            hits.append({"url": x.get("url"), "title": x.get("title"), "chars": len(t),
                         "transcript_like": len(t) > 4000 and t.count(".") > 60})
        found[mid] = hits
        best = [h for h in hits if h["transcript_like"]]
        byid[mid]["transcript"]["transcript_page_hunt"] = {
            "query_verbatim": q, "n_results": len(hits),
            "transcript_like_hits": [h["url"] for h in best],
            "verdict": "found" if best else "no_published_transcript_located",
        }
        print(f"  {mid}: {len(hits)} results, transcript-like={len(best)}")
        for h in hits[:5]:
            print(f"      {'T' if h['transcript_like'] else '-'} {h['chars']:>6} {str(h['title'])[:60]} {h['url'][:80]}")

    json.dump(resolved, open(path, "w"), indent=2)
    json.dump(found, open(os.path.join(HERE, "raw", "p2d_hunt_digest.json"), "w"), indent=2)
    el = time.time() - t0
    C.timing_record("P2d_transcript_hunt", el, "1 full contents pull + 2 transcript-page hunts")
    print(f"\n{el:.1f}s. spend=${C.total_spend()}")


if __name__ == "__main__":
    main()
