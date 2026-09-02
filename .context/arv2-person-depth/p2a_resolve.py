"""Phase 2a — resolve the media shortlist to fetchable artifacts.

YouTube: watch page -> ytInitialPlayerResponse -> title, lengthSeconds, caption tracks.
Podcast: episode page -> RSS feed -> MP3 enclosure + itunes:duration.
Walled (LinkedIn-native / X-native video): recorded as unfetchable_walled, never fetched.

No paid calls here (plain HTTP with a browser UA). Everything is ledgered anyway.
"""

import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p_lib as C  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# The shortlist: top 1-2 media items per person, chosen from media_candidates_triaged.json
# + the A12 targeted round. Items whose SUBJECT is another person at the same company are
# marked target_speaks="unknown" and verified from the transcript, never assumed.
SHORTLIST = [
    # --- Vineet Edupuganti (Cogent CEO) -- richest media footprint in the set
    dict(person="vineet_edupuganti", id="vin_siemens",
         url="https://www.youtube.com/watch?v=8x_RZ4yIRbw",
         kind="youtube", title_hint="Vineet Edupuganti - 2016 Siemens Competition Individual Grand Prize Winner",
         target_speaks="likely", note="short clip -> the raw-audio-embedding demo candidate"),
    dict(person="vineet_edupuganti", id="vin_ep297",
         url="https://www.youtube.com/watch?v=_OHZyK0nugs",
         kind="youtube", title_hint="Ep 297 AI, Cybersecurity & the Future of Business - Vineet Edupuganti CEO @Cogent",
         target_speaks="likely", note="long-form interview"),
    dict(person="vineet_edupuganti", id="vin_hackervalley",
         url="https://hackervalleystudio.podbean.com/e/the-rise-of-the-autonomous-blue-team-with-vineet-edupuganti/",
         kind="podcast", title_hint="The Rise of the Autonomous Blue Team with Vineet Edupuganti",
         target_speaks="likely", note="podbean -> RSS enclosure"),
    # --- Alastair Paterson (Harmonic CEO)
    dict(person="alastair_paterson", id="ala_gcsp265",
         url="https://cloudsecuritypodcast.libsyn.com/ep265-beyond-shadow-it-unsanctioned-ai-agents-dont-just-talk-they-act",
         kind="podcast", title_hint="Cloud Security Podcast by Google EP265",
         target_speaks="likely", note="libsyn -> RSS enclosure"),
    dict(person="alastair_paterson", id="ala_sysk",
         url="https://www.buzzsprout.com/2215185/episodes/19393590-why-usage-intelligence-is-the-missing-layers-in-enterprise-ai-security-with-harmonic-security",
         kind="podcast", title_hint="Security You Should Know - Harmonic Security",
         target_speaks="unknown", note="buzzsprout -> RSS enclosure"),
    # --- Sanaz Yashar (Zafran CEO)
    dict(person="sanaz_yashar", id="san_boardroom",
         url="https://podcasts.apple.com/us/podcast/ai-summit-sanaz-yashar-co-founder-and-ceo-at-zafran-security/id1749699539?i=1000728",
         kind="podcast", title_hint="Boardroom Club - AI Summit: Sanaz Yashar",
         target_speaks="likely", note="apple podcasts -> lookup API -> feedUrl"),
    # --- Ana Corio / Tyler Chonoles (Harmonic) -- company podcasts, target may not speak
    dict(person="ana_corio", id="ana_coffee",
         url="https://www.youtube.com/watch?v=DBRuxk0YrQk",
         kind="youtube", title_hint="Autocomply AI presents Coffee and Compliance with guests Harmonic Security",
         target_speaks="unknown", note="verify who actually speaks"),
    # --- Alexander Semien (Cogent) -- his only located speaking artifact
    dict(person="alexander_semien", id="sem_cogentyt",
         url="https://www.youtube.com/watch?v=fbn5EJagBmQ",
         kind="youtube", title_hint="How Cogent Security sandboxes AI agents that touch customer data",
         target_speaks="unknown", note="likely Geng Sng, verify"),
    # --- Mandar Marathe (UPTIQ)
    dict(person="mandar_marathe", id="man_uptiqyt",
         url="https://www.youtube.com/watch?v=GS8qgXDfpHM",
         kind="youtube", title_hint="See Uptiq for Equipment Finance in Action",
         target_speaks="unknown", note="product video, verify"),
    dict(person="mandar_marathe", id="man_cu20",
         url="https://www.buzzsprout.com/268738/episodes/13811630-cu-2-0-podcast-episode-273-uptiq-s-lending-platform-for-holistic-advisors",
         kind="podcast", title_hint="CU 2.0 Podcast Episode 273 UPTIQ",
         target_speaks="unknown", note="buzzsprout -> RSS enclosure"),
]

# Explicitly recorded as never-fetched (walled), per the brief.
WALLED = [
    dict(person="alexander_semien",
         url="https://www.linkedin.com/posts/cogentsecurity_cogents-head-of-growth-alexander-semien-activity-7460449",
         kind="linkedin_native_video",
         note="Cogent's own post featuring Semien on camera. LinkedIn-native video is walled -> never fetched."),
    dict(person="mandar_marathe",
         url="https://www.linkedin.com/posts/mandarmarathe_financial-expertise-meets-ai-inside-uptiq-activity-7452",
         kind="linkedin_native_video",
         note="'Watch the full video' UPTIQ post. LinkedIn-native video is walled -> never fetched."),
]

YT_ID = re.compile(r"(?:v=|youtu\.be/|/live/)([A-Za-z0-9_-]{11})")


def yt_probe(item):
    vid = YT_ID.search(item["url"])
    vid = vid.group(1) if vid else None
    out = {"video_id": vid}
    r = C.live_fetch(item["url"], label=f"yt_{item['id']}", timeout=40, retries=2)
    html = r["text"]
    out["http"] = r["status"]
    m = re.search(r"ytInitialPlayerResponse\s*=\s*(\{.*?\});", html, re.S)
    if not m:
        m = re.search(r'ytInitialPlayerResponse"\]\s*=\s*(\{.*?\});', html, re.S)
    if m:
        try:
            pr = json.loads(m.group(1))
        except Exception:
            depth, end = 0, None
            s = m.group(1)
            for i, ch in enumerate(s):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            pr = json.loads(s[:end]) if end else {}
        vd = (pr.get("videoDetails") or {})
        out["title"] = vd.get("title")
        out["author"] = vd.get("author")
        out["length_s"] = int(vd.get("lengthSeconds") or 0)
        out["short_description"] = (vd.get("shortDescription") or "")[:1500]
        out["view_count"] = vd.get("viewCount")
        tracks = (((pr.get("captions") or {}).get("playerCaptionsTracklistRenderer") or {})
                  .get("captionTracks") or [])
        out["caption_tracks"] = [{"lang": t.get("languageCode"), "kind": t.get("kind"),
                                  "name": ((t.get("name") or {}).get("simpleText")
                                           or ((t.get("name") or {}).get("runs") or [{}])[0].get("text")),
                                  "baseUrl": t.get("baseUrl")} for t in tracks]
        st = (pr.get("playabilityStatus") or {})
        out["playability"] = st.get("status")
        out["playability_reason"] = st.get("reason")
    else:
        out["parse_error"] = "ytInitialPlayerResponse not present in served HTML"
        out["html_bytes"] = len(html)
        out["consent_or_bot_wall"] = ("consent" in html[:5000].lower()
                                      or "sign in to confirm" in html.lower())
    return out


def rss_from_page(item):
    """Find an RSS feed for a podcast episode page, then the MP3 enclosure + duration."""
    out = {}
    url = item["url"]
    if "podcasts.apple.com" in url:
        pid = re.search(r"/id(\d+)", url)
        if pid:
            lk = C.live_fetch(f"https://itunes.apple.com/lookup?id={pid.group(1)}&entity=podcast",
                              label=f"applelookup_{item['id']}", accept="application/json", timeout=30)
            try:
                j = json.loads(lk["text"])
                res = (j.get("results") or [{}])[0]
                out["feed_url"] = res.get("feedUrl")
                out["podcast_name"] = res.get("collectionName")
            except Exception as e:  # noqa: BLE001
                out["apple_lookup_error"] = str(e)
    if not out.get("feed_url"):
        r = C.live_fetch(url, label=f"pod_{item['id']}", timeout=40, retries=2)
        out["page_http"] = r["status"]
        html = r["text"]
        out["page_bytes"] = len(html)
        m = re.search(r'type=["\']application/rss\+xml["\'][^>]*href=["\']([^"\']+)', html) \
            or re.search(r'href=["\']([^"\']+)["\'][^>]*type=["\']application/rss\+xml', html)
        if m:
            out["feed_url"] = m.group(1)
        if "buzzsprout.com" in url:
            fid = re.search(r"buzzsprout\.com/(\d+)/", url)
            if fid and not out.get("feed_url"):
                out["feed_url"] = f"https://feeds.buzzsprout.com/{fid.group(1)}.rss"
        if "libsyn.com" in url and not out.get("feed_url"):
            sub = url.split("//")[1].split(".")[0]
            out["feed_url"] = f"https://{sub}.libsyn.com/rss"
        if "podbean.com" in url and not out.get("feed_url"):
            sub = url.split("//")[1].split(".")[0]
            out["feed_url"] = f"https://{sub}.podbean.com/feed.xml"
        # direct mp3 on the page
        mp3 = re.findall(r"https?://[^\s\"'<>]+\.mp3[^\s\"'<>]*", html)
        if mp3:
            out["mp3_on_page"] = mp3[:3]
    if out.get("feed_url"):
        f = C.live_fetch(out["feed_url"], label=f"rss_{item['id']}", accept="application/rss+xml",
                         timeout=60, retries=2)
        out["feed_http"] = f["status"]
        xml = f["text"]
        out["feed_bytes"] = len(xml)
        items = re.split(r"<item[ >]", xml)[1:]
        want = re.sub(r"[^a-z0-9]+", " ", (item.get("title_hint") or "")).strip().split()
        best, best_score = None, -1
        for it in items:
            t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
            title = (t.group(1) if t else "").strip()
            norm = re.sub(r"[^a-z0-9]+", " ", title.lower())
            score = sum(1 for w in want if w.lower() in norm)
            if score > best_score:
                enc = re.search(r'<enclosure[^>]*url="([^"]+)"[^>]*', it)
                dur = re.search(r"<itunes:duration>(.*?)</itunes:duration>", it)
                pub = re.search(r"<pubDate>(.*?)</pubDate>", it)
                desc = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", it, re.S)
                best_score, best = score, {
                    "episode_title": title,
                    "mp3_url": enc.group(1) if enc else None,
                    "itunes_duration": dur.group(1) if dur else None,
                    "pub_date": pub.group(1) if pub else None,
                    "description_head": re.sub(r"<[^>]+>", " ", (desc.group(1) if desc else ""))[:2500],
                }
        out["match_score"] = best_score
        out["episode"] = best
        out["n_items_in_feed"] = len(items)
    return out


def main():
    t0 = time.time()
    resolved = []
    for item in SHORTLIST:
        print(f"\n== {item['person']} / {item['id']} ({item['kind']})")
        rec = dict(item)
        try:
            rec["probe"] = yt_probe(item) if item["kind"] == "youtube" else rss_from_page(item)
        except Exception as e:  # noqa: BLE001
            rec["probe"] = {"error": f"{type(e).__name__}: {e}"}
        resolved.append(rec)
        time.sleep(0.4)
    for w in WALLED:
        resolved.append(dict(w, id="walled_" + w["person"], probe={"status": "unfetchable_walled"},
                             target_speaks="n/a"))
    json.dump(resolved, open(os.path.join(HERE, "media_resolved.json"), "w"), indent=2)
    el = time.time() - t0
    C.timing_record("P2a_media_resolve", el, f"{len(SHORTLIST)} probes + {len(WALLED)} walled")
    print(f"\nresolved -> media_resolved.json in {el:.1f}s")
    for r in resolved:
        p = r.get("probe") or {}
        if r["kind"] == "youtube":
            print(f"  {r['id']:<18} len={p.get('length_s')}s captions={len(p.get('caption_tracks') or [])} "
                  f"play={p.get('playability')} {str(p.get('parse_error') or '')[:40]}")
        elif r["kind"] == "podcast":
            ep = (p.get("episode") or {})
            print(f"  {r['id']:<18} feed={bool(p.get('feed_url'))} match={p.get('match_score')} "
                  f"dur={ep.get('itunes_duration')} mp3={bool(ep.get('mp3_url'))}")
        else:
            print(f"  {r['id']:<18} {p.get('status')}")


if __name__ == "__main__":
    main()
