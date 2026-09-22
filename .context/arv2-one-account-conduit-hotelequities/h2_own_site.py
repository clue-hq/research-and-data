"""H2 — hotelequities.com own-site reads.

Direct HTTP GETs to hotelequities.com intermittently hang (a 2-minute stall was observed on a
prior run), so every direct fetch uses timeout<=20s, retries=1, and whatever fails or comes back
thin falls back to Exa /contents with livecrawl. Both attempts are ledgered, so the report can
say honestly which route served each page.
"""
import html
import json
import re
import sys
import time

sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

PAGES = [
    ("home", "https://hotelequities.com/"),
    ("team", "https://hotelequities.com/meet-our-team.htm"),
    ("careers", "https://hotelequities.com/careers"),
    ("blog", "https://hotelequities.com/blog/"),
    ("about", "https://hotelequities.com/about-us.htm"),
    ("portfolio", "https://hotelequities.com/our-hotels.htm"),
]

TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
STRIP = re.compile(r"<[^>]+>")


def text_of(h):
    t = TAGS.sub(" ", h or "")
    t = STRIP.sub(" ", t)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


t_all = time.time()
out = {"direct": {}, "exa": {}, "resolved": {}}

print("== A. direct fetches (timeout 20s, 1 try) ==")
need_exa = []
for name, url in PAGES:
    t0 = time.time()
    r = C.live_fetch(url, label=f"h2_direct_{name}", timeout=20, retries=1)
    txt = text_of(r["text"]) if r["status"] == 200 else ""
    out["direct"][name] = {"url": url, "http": r["status"], "elapsed_s": r["elapsed_s"],
                           "raw_bytes": len(r["text"]), "text_chars": len(txt)}
    print(f"   {name:10s} http={r['status']} {r['elapsed_s']}s text={len(txt)}")
    if r["status"] == 200 and len(txt) > 800:
        out["resolved"][name] = {"url": url, "route": "direct", "text": txt[:30000]}
    else:
        need_exa.append((name, url))

print(f"\n== B. Exa /contents fallback for {len(need_exa)} page(s) ==")
if need_exa:
    res = C.exa_contents([u for _, u in need_exa], label="h2_exa_fallback",
                         text_chars=14000, livecrawl="preferred", timeout=180)
    by_url = {}
    for x in (res.get("results") or []):
        by_url[(x.get("url") or "").rstrip("/")] = x
    for name, url in need_exa:
        x = by_url.get(url.rstrip("/")) or next(
            (v for k, v in by_url.items() if url.rstrip("/").split("//")[-1].split("/")[0]
             in k and (url.rstrip("/").rsplit("/", 1)[-1] in k or name == "home")), None)
        got = (x or {}).get("text") or ""
        out["exa"][name] = {"url": url, "resolved_url": (x or {}).get("url"),
                            "title": (x or {}).get("title"), "chars": len(got)}
        print(f"   {name:10s} exa chars={len(got)} -> {(x or {}).get('url')}")
        if got:
            out["resolved"][name] = {"url": (x or {}).get("url") or url, "route": "exa_contents",
                                     "title": (x or {}).get("title"), "text": got[:30000]}
    out["exa"]["_statuses"] = res.get("statuses")

# ---- mine the team page for names/titles (the committee ground truth) -----
team = (out["resolved"].get("team") or {}).get("text") or ""
blog = (out["resolved"].get("blog") or {}).get("text") or ""
TITLE_RE = re.compile(
    r"(Chief [A-Z][a-z]+(?: [A-Z][a-z]+)* Officer|President|Co-?Chairman|Chairman|"
    r"Chief Executive Officer|Chief Operating Officer|Chief Financial Officer|"
    r"Chief Information Officer|Chief Technology Officer|Chief Commercial Officer|"
    r"Chief Revenue Officer|Chief People Officer|Chief Development Officer|"
    r"(?:Executive |Senior |)Vice President(?: of [A-Z][A-Za-z ]+)?|SVP[^,.]{0,40}|"
    r"VP of [A-Z][A-Za-z ]+|Managing Director|Founder)")
out["team_titles_seen"] = sorted(set(TITLE_RE.findall(team)))[:80]
out["team_text_head"] = team[:4000]
out["blog_text_head"] = blog[:4000]
print("\n== team page titles seen ==")
for t in out["team_titles_seen"]:
    print("   -", t)

json.dump(out, open("h2_own_site.json", "w"), indent=2)
C.timing_record("H2_own_site", time.time() - t_all,
                f"{len(PAGES)} pages, {len(need_exa)} via exa fallback")
print(f"\nH2 {round(time.time()-t_all,1)}s resolved={len(out['resolved'])}/{len(PAGES)} "
      f"spend={C.total_spend()}")
