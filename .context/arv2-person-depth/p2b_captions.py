"""Phase 2b — the NO-GEMINI-KEY fallback: pull YouTube caption tracks (public timedtext,
no key) into timestamped transcripts, and pull podcast show-notes/transcript pages.

Writes transcripts/<id>.txt (MM:SS-stamped lines) + transcripts/<id>.json (cue list).
Fixes the ala_gcsp265 feed mismatch by matching on the episode NUMBER, not fuzzy words.
"""

import html as htmlmod
import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p_lib as C  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TR = os.path.join(HERE, "transcripts")


def mmss(sec):
    sec = int(float(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def fetch_caption(track_url, label):
    """timedtext: try the served baseUrl as-is, then &fmt=json3, then &fmt=srv3."""
    attempts = [track_url, track_url + "&fmt=json3", track_url + "&fmt=srv3"]
    for i, u in enumerate(attempts):
        r = C.live_fetch(u, label=f"{label}_try{i}", accept="text/xml", timeout=45, retries=2,
                         max_save=1200000)
        t = r["text"]
        if r["status"] == 200 and len(t) > 200:
            return {"url_form": ["baseUrl", "json3", "srv3"][i], "status": r["status"], "text": t}
    return {"url_form": "none", "status": r["status"], "text": t}


def parse_cues(text):
    cues = []
    s = text.strip()
    if s.startswith("{"):
        try:
            j = json.loads(s)
            for ev in j.get("events") or []:
                segs = ev.get("segs") or []
                words = "".join(x.get("utf8", "") for x in segs).strip()
                if words:
                    cues.append({"t": (ev.get("tStartMs") or 0) / 1000.0, "text": words})
            return cues, "json3"
        except Exception:
            pass
    for m in re.finditer(r'<(?:text|p)[^>]*?(?:start|t)="([\d.]+)"[^>]*>(.*?)</(?:text|p)>', s, re.S):
        t = float(m.group(1))
        t = t / 1000.0 if t > 100000 else t
        body = re.sub(r"<[^>]+>", "", m.group(2))
        body = htmlmod.unescape(htmlmod.unescape(body)).strip()
        if body:
            cues.append({"t": t, "text": body})
    return cues, "xml"


def write_transcript(mid, title, cues, meta):
    lines = [f"# {title}", f"# source: {meta.get('url')}", f"# cues: {len(cues)}", ""]
    buf, buf_t = [], None
    for c in cues:
        if buf_t is None:
            buf_t = c["t"]
        buf.append(c["text"].replace("\n", " "))
        if sum(len(x) for x in buf) > 260:
            lines.append(f"[{mmss(buf_t)}] " + " ".join(buf))
            buf, buf_t = [], None
    if buf:
        lines.append(f"[{mmss(buf_t)}] " + " ".join(buf))
    txt = "\n".join(lines)
    open(os.path.join(TR, f"{mid}.txt"), "w").write(txt)
    json.dump({"id": mid, "title": title, "meta": meta, "cues": cues},
              open(os.path.join(TR, f"{mid}.json"), "w"), indent=2)
    return txt


def refix_gcsp265(rec):
    """The fuzzy title match grabbed EP280. Re-scan the feed for the EP265 item."""
    feed = (rec.get("probe") or {}).get("feed_url")
    if not feed:
        return
    f = C.live_fetch(feed, label="rss_ala_gcsp265_refix", accept="application/rss+xml",
                     timeout=60, retries=2, max_save=2500000)
    items = re.split(r"<item[ >]", f["text"])[1:]
    for it in items:
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
        title = (t.group(1) if t else "").strip()
        if "EP265" in title.upper():
            enc = re.search(r'<enclosure[^>]*url="([^"]+)"', it)
            dur = re.search(r"<itunes:duration>(.*?)</itunes:duration>", it)
            pub = re.search(r"<pubDate>(.*?)</pubDate>", it)
            desc = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", it, re.S)
            rec["probe"]["episode"] = {
                "episode_title": title,
                "mp3_url": enc.group(1) if enc else None,
                "itunes_duration": dur.group(1) if dur else None,
                "pub_date": pub.group(1) if pub else None,
                "description_head": re.sub(r"<[^>]+>", " ", (desc.group(1) if desc else ""))[:4000],
            }
            rec["probe"]["match_score"] = "exact_EP265"
            print("   refixed ala_gcsp265 ->", title[:80])
            return
    print("   !! EP265 not found in feed")


def main():
    t0 = time.time()
    path = os.path.join(HERE, "media_resolved.json")
    resolved = json.load(open(path))
    for r in resolved:
        if r["id"] == "ala_gcsp265":
            refix_gcsp265(r)

    for r in resolved:
        p = r.get("probe") or {}
        if r["kind"] == "youtube":
            tracks = p.get("caption_tracks") or []
            if not tracks:
                r["transcript"] = {"status": "no_caption_track"}
                continue
            tr = tracks[0]
            print(f"\n== captions {r['id']} ({p.get('length_s')}s, {tr.get('name')})")
            got = fetch_caption(tr["baseUrl"], f"cap_{r['id']}")
            cues, fmt = parse_cues(got["text"])
            r["transcript"] = {
                "status": "ok" if cues else "empty_or_blocked",
                "source": "youtube_timedtext_public_no_key",
                "url_form": got["url_form"], "http": got["status"],
                "parse_fmt": fmt, "n_cues": len(cues),
                "asr": (tr.get("kind") == "asr"),
                "covers_s": round(cues[-1]["t"], 1) if cues else 0,
            }
            if cues:
                txt = write_transcript(r["id"], p.get("title") or r["title_hint"], cues,
                                       {"url": r["url"], "length_s": p.get("length_s"),
                                        "author": p.get("author")})
                r["transcript"]["chars"] = len(txt)
                r["transcript"]["file"] = f"transcripts/{r['id']}.txt"
            print(f"   -> {r['transcript']}")
        elif r["kind"] == "podcast":
            ep = p.get("episode") or {}
            r["transcript"] = {
                "status": "shownotes_only_no_key",
                "source": "rss_description",
                "chars": len(ep.get("description_head") or ""),
                "mp3_url_present": bool(ep.get("mp3_url")),
            }
            if ep.get("description_head"):
                open(os.path.join(TR, f"{r['id']}_shownotes.txt"), "w").write(
                    f"# {ep.get('episode_title')}\n# {r['url']}\n# mp3: {ep.get('mp3_url')}\n"
                    f"# duration: {ep.get('itunes_duration')}\n\n{ep['description_head']}")
                r["transcript"]["file"] = f"transcripts/{r['id']}_shownotes.txt"
    json.dump(resolved, open(path, "w"), indent=2)
    el = time.time() - t0
    C.timing_record("P2b_captions", el, "youtube timedtext + podcast show-notes (no Gemini key)")
    print(f"\ncaption phase {el:.1f}s. spend=${C.total_spend()}")
    for r in resolved:
        print(f"  {r['id']:<22} {json.dumps(r.get('transcript') or {})[:150]}")


if __name__ == "__main__":
    main()
