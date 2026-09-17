"""Phase 2c — fallback-of-the-fallback. YouTube's public timedtext endpoint is CLOSED
(HTTP 200 / 0 bytes / text-html on every form, verified 5 ways). So try Exa's indexed
copy of each media page: some YouTube pages carry an indexed transcript, and podcast
hosts often publish a transcript/show-notes page Exa has crawled.

This is the honest measurement of 'what can you get with no Gemini key'.
"""

import json
import os
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
    urls, ids = [], []
    for r in resolved:
        if r["kind"] in ("youtube", "podcast"):
            urls.append(r["url"])
            ids.append(r["id"])
    out = C.exa_contents(urls, label="p2c_media_pages", text_chars=25000, timeout=300)
    by_url = {}
    for res in out.get("results") or []:
        by_url[(res.get("url") or "").rstrip("/")] = res
    for r in resolved:
        if r["kind"] not in ("youtube", "podcast"):
            continue
        res = by_url.get(r["url"].rstrip("/")) or {}
        txt = res.get("text") or ""
        ex = {"exa_indexed_chars": len(txt), "exa_title": res.get("title")}
        # a real transcript reads as continuous speech; a page stub does not
        ex["looks_like_transcript"] = len(txt) > 4000 and txt.count(".") > 60
        r.setdefault("transcript", {})["exa_fallback"] = ex
        if txt:
            open(os.path.join(TR, f"{r['id']}_exa_page.txt"), "w").write(
                f"# EXA INDEXED COPY of {r['url']}\n# title: {res.get('title')}\n"
                f"# chars: {len(txt)}\n\n{txt}")
            ex["file"] = f"transcripts/{r['id']}_exa_page.txt"
    json.dump(resolved, open(path, "w"), indent=2)
    el = time.time() - t0
    C.timing_record("P2c_exa_media_pages", el, "exa /contents over 10 media pages")
    print(f"\n{el:.1f}s. spend=${C.total_spend()}")
    for r in resolved:
        ex = ((r.get("transcript") or {}).get("exa_fallback") or {})
        if ex:
            print(f"  {r['id']:<20} chars={ex.get('exa_indexed_chars'):>7} "
                  f"transcript_like={ex.get('looks_like_transcript')}  {str(ex.get('exa_title'))[:50]}")


if __name__ == "__main__":
    main()
