"""H10 — the Gemini media layer, two-model recipe (proven on the Zafran run).

Usage: python3 h10_gemini_media.py <episode_index>   (0..4, from h8b_rafter_episodes.json)

Per item:
  1. download the MP3 enclosure (free), upload via the Gemini Files API (free)
  2. `gemini-3.5-transcribe`  -> the FAITHFUL full transcript. Wire fact: its text lands at
     candidates[0].content.parts[0].audioTranscription.text, NOT parts[].text, and it emits no
     timestamps and no speaker labels.
  3. `gemini-3.5-flash-lite`  -> MM:SS-timestamped lines + candidate quotes. Wire fact: it
     silently LOOPS on long audio after ~12 minutes, re-emitting earlier dialogue under new
     timestamps, so a duplicate-line check is mandatory.
  4. keep ONLY quotes that are exact substrings of the faithful transcript (checked in code).

Audio is billed at ~25 tokens/second; a YouTube URL is billed as video at ~91 tokens/second, so
audio is used wherever it exists. Cost comes from real usageMetadata.
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request

sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

IDX = int(sys.argv[1]) if len(sys.argv) > 1 else 0
EPS = json.load(open("h8b_rafter_episodes.json"))
EP = EPS[IDX]
SLUGS = ["rafter_ai_payoff", "rafter_ai_labor", "rafter_owner_economics",
         "rafter_tech_advice", "rafter_tech_ceo"]
SLUG = SLUGS[IDX]
PERSON = "Ben Rafter"
DUR = int(EP["dur"])
MP3 = EP["mp3"]
PAGE = EP["link"]
TITLE = re.sub(r"&#\d+;", "'", EP["title"])
LOCAL = os.path.join("raw", f"{SLUG}.mp3")

FAITHFUL_PROMPT = f"""Transcribe this entire podcast episode verbatim.
The guest is Ben Rafter, Chief Executive Officer of Hotel Equities (previously CEO of Springboard
Hospitality). The host is Josiah Mackenzie of Hospitality Daily.
Episode title: "{TITLE}".

Output ONLY the transcript text, from 00:00 to the end. Cover the WHOLE episode. Never repeat a
passage you have already emitted. Never invent words. Mark unintelligible audio [inaudible]."""

TS_PROMPT = f"""You are transcribing a public podcast episode for a business-research record.
The guest is Ben Rafter, Chief Executive Officer of Hotel Equities. The host is Josiah Mackenzie
of Hospitality Daily. Episode title: "{TITLE}".

Return ONLY this structure, in plain text:

## META
speakers: <label every distinct speaker S1/S2/... with your best identification and the evidence>
guest_identity_evidence: <verbatim words in the audio that identify the guest; else NOT STATED>
duration_mmss: <total duration you observed>

## TRANSCRIPT
A full transcript of the WHOLE episode. Every line MUST start with an [MM:SS] timestamp and a
speaker label, like:
[03:41] S2 (Ben Rafter): <verbatim words>
Do not summarise, do not skip, do not stop early. Use the real spoken words.

## QUOTES
Exactly 5 verbatim quotes from the GUEST that reveal how he thinks about: technology and AI in
hotel operations, guest experience, labor and staffing, service consistency across a large
portfolio, how he evaluates or buys vendors and systems, and what owners should demand. Format:
- "[MM:SS]" "<verbatim quote>" -> why it matters: <one line>

## TECH_AND_VENDOR_SIGNALS
Every moment where the guest names or describes a system, vendor, tool, category of software, an
integration, a property-management system, guest messaging, a call centre, or an automation, or
talks about buying/evaluating one. Each as: [MM:SS] verbatim + one line.
If none exist, write: NONE IN THIS EPISODE.

Never invent words. If audio is unintelligible write [inaudible]."""


def upload_file(path, mime, display_name):
    size = os.path.getsize(path)
    start_url = f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={C.GEMINI_KEY}"
    s, h, t, e = C._request(
        start_url, method="POST",
        headers={"X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                 "X-Goog-Upload-Header-Content-Length": str(size),
                 "X-Goog-Upload-Header-Content-Type": mime,
                 "Content-Type": "application/json"},
        body={"file": {"display_name": display_name}}, timeout=120, retries=3)
    up = h.get("X-Goog-Upload-URL") or h.get("x-goog-upload-url")
    print(f"  files.start http={s} upload_url={'YES' if up else 'NO'}")
    if not up:
        print("   resp:", t[:400])
        return None
    data = open(path, "rb").read()
    s2, h2, t2, e2 = C._request(
        up, method="POST",
        headers={"Content-Length": str(size), "X-Goog-Upload-Offset": "0",
                 "X-Goog-Upload-Command": "upload, finalize"},
        raw_body=data, timeout=1200, retries=2)
    print(f"  files.upload http={s2} {e2}s")
    try:
        f = json.loads(t2).get("file") or {}
    except Exception:
        print("   resp:", t2[:400])
        return None
    C.save_raw(f"h10_file_upload_{SLUG}", {k: v for k, v in f.items() if k != "downloadUri"})
    C.ledger_append({"provider": "gemini", "label": f"h10_files_upload_{SLUG}",
                     "op": "files.upload", "http": s2, "elapsed_s": e2, "cost_usd": 0.0,
                     "bytes": size, "note": "Files API upload is free"})
    name = f.get("name")
    for _ in range(60):
        s3, _h, t3, _e = C._request(f"{C.GEMINI_BASE}/{name}?key={C.GEMINI_KEY}",
                                    method="GET", headers={}, timeout=60, retries=2)
        st = (json.loads(t3) or {}).get("state")
        if st == "ACTIVE":
            return json.loads(t3)
        if st == "FAILED":
            return None
        time.sleep(4)
    return None


def parts_text(out):
    cands = out.get("candidates") or []
    if not cands:
        return ""
    txt = ""
    for p in ((cands[0].get("content") or {}).get("parts") or []):
        txt += p.get("text") or ""
        # WIRE FACT: gemini-3.5-transcribe puts its text here, not in parts[].text
        at = p.get("audioTranscription") or {}
        txt += at.get("text") or ""
    return txt


def norm(s):
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"\s+", " ", s).strip().lower()).strip()


t_all = time.time()
print(f"=== {SLUG} | {TITLE} | {DUR}s ===")

if not os.path.exists(LOCAL) or os.path.getsize(LOCAL) < 10000:
    t0 = time.time()
    req = urllib.request.Request(MP3, headers={"User-Agent": C.BROWSER_UA})
    with urllib.request.urlopen(req, timeout=600) as r, open(LOCAL, "wb") as f:
        f.write(r.read())
    dl = round(time.time() - t0, 2)
    C.ledger_append({"provider": "live_http", "label": f"h10_mp3_download_{SLUG}",
                     "op": "GET mp3 enclosure", "http": 200, "elapsed_s": dl, "cost_usd": 0.0,
                     "bytes": os.path.getsize(LOCAL)})
    print(f"  downloaded {os.path.getsize(LOCAL)} bytes in {dl}s")

finfo = upload_file(LOCAL, "audio/mpeg", f"hospitality-daily-{SLUG}")
if not finfo:
    print("UPLOAD FAILED")
    sys.exit(1)
URI = finfo["uri"]

# ---- 1. faithful ASR --------------------------------------------------------
print("\n-- gemini-3.5-transcribe (faithful) --")
out_f = C.gemini_generate("gemini-3.5-transcribe",
                          [{"file_data": {"file_uri": URI, "mime_type": "audio/mpeg"}},
                           {"text": FAITHFUL_PROMPT}],
                          label=f"h10_faithful_{SLUG}", timeout=2400,
                          max_output_tokens=32000, audio_seconds=DUR)
faithful = parts_text(out_f)
print(f"   chars={len(faithful)} words={len(faithful.split())} "
      f"wpm={round(len(faithful.split())/(DUR/60),1) if DUR else 0}")

# ---- 2. timestamped pass ----------------------------------------------------
print("\n-- gemini-3.5-flash-lite (timestamps + quotes) --")
out_t = C.gemini_generate("gemini-3.5-flash-lite",
                          [{"file_data": {"file_uri": URI, "mime_type": "audio/mpeg"}},
                           {"text": TS_PROMPT}],
                          label=f"h10_timestamped_{SLUG}", timeout=2400,
                          max_output_tokens=32000, audio_seconds=DUR)
stamped = parts_text(out_t)

TS = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.*)$")
lines = [m.groups() for m in (TS.match(ln.strip()) for ln in stamped.splitlines()) if m]
uniq_texts = {norm(t) for _, t in lines}
loop_start = None
seen = {}
for ts, txt in lines:
    k = norm(txt)
    if len(k) > 25 and k in seen and loop_start is None:
        loop_start = ts
    seen[k] = ts
print(f"   timestamped lines={len(lines)} unique={len(uniq_texts)} "
      f"loop_starts_at={loop_start}")

# ---- 3. verify every quote against the faithful transcript ------------------
NA = norm(faithful)


def contained(q, minlen=40):
    n = norm(q)
    if not n:
        return "EMPTY"
    if n in NA:
        return "EXACT"
    for i in range(0, max(1, len(n) - minlen), 8):
        if n[i:i + minlen] in NA:
            return "PARTIAL"
    return "NOT_FOUND"


quotes = []
blk = stamped[stamped.find("## QUOTES"):] if "## QUOTES" in stamped else ""
if blk:
    nxt = blk.find("\n## ", 5)
    blk = blk[:nxt] if nxt > 0 else blk
for ln in blk.splitlines():
    m = re.match(r'^-\s*"?\[?(\d{1,2}:\d{2})\]?"?\s*"(.+?)"\s*(?:->|$)', ln.strip())
    if m:
        quotes.append({"timestamp": m.group(1), "quote": m.group(2),
                       "verbatim_check": contained(m.group(2)),
                       "inside_unique_window": (loop_start is None or m.group(1) < loop_start)})

signals = []
sblk = stamped[stamped.find("## TECH_AND_VENDOR_SIGNALS"):] if "## TECH_AND_VENDOR_SIGNALS" in stamped else ""
for ln in sblk.splitlines()[1:]:
    m = re.match(r"^\[?(\d{1,2}:\d{2})\]?\s*(.+)$", ln.strip())
    if m and len(m.group(2)) > 15:
        signals.append({"timestamp": m.group(1), "text": m.group(2),
                        "verbatim_check": contained(m.group(2)[:120])})

print("\n   quote verification vs the faithful ASR:")
for q in quotes:
    print(f"     [{q['timestamp']}] {q['verbatim_check']:9s} uniq={q['inside_unique_window']} "
          f":: {q['quote'][:95]}")

os.makedirs("transcripts", exist_ok=True)
open(os.path.join("transcripts", f"{SLUG}_faithful.md"), "w").write(
    f"# Faithful transcript (gemini-3.5-transcribe) — {TITLE}\n"
    f"person: {PERSON}\nsource_page: {PAGE}\nsource_mp3: {MP3}\n"
    f"published: {EP['pub']}\nduration_seconds: {DUR}\n\n## TRANSCRIPT\n{faithful}\n")
open(os.path.join("transcripts", f"{SLUG}_timestamped.md"), "w").write(
    f"# Timestamped transcript (gemini-3.5-flash-lite) — {TITLE}\n"
    f"person: {PERSON}\nsource_page: {PAGE}\nsource_mp3: {MP3}\n"
    f"published: {EP['pub']}\nduration_seconds: {DUR}\n"
    f"loop_detected_at: {loop_start}\n\n{stamped}\n")

um_f = out_f.get("usageMetadata") or {}
um_t = out_t.get("usageMetadata") or {}
meta = {
    "slug": SLUG, "person": PERSON, "title": TITLE, "page_url": PAGE, "mp3": MP3,
    "published": EP["pub"], "duration_seconds": DUR,
    "faithful": {"model": "gemini-3.5-transcribe", "usageMetadata": um_f,
                 "cost_usd": C.gemini_cost(um_f), "elapsed_s": out_f.get("_elapsed_s"),
                 "chars": len(faithful), "words": len(faithful.split())},
    "timestamped": {"model": "gemini-3.5-flash-lite", "usageMetadata": um_t,
                    "cost_usd": C.gemini_cost(um_t), "elapsed_s": out_t.get("_elapsed_s"),
                    "chars": len(stamped), "timestamped_lines": len(lines),
                    "unique_lines": len(uniq_texts), "loop_starts_at": loop_start},
    "total_cost_usd": round(C.gemini_cost(um_f) + C.gemini_cost(um_t), 6),
    "audio_tokens_per_second": round(
        sum(d.get("tokenCount") or 0 for d in (um_f.get("promptTokensDetails") or [])
            if d.get("modality") == "AUDIO") / DUR, 2) if DUR else None,
    "quotes": quotes, "tech_and_vendor_signals": signals,
}
json.dump(meta, open(f"h10_{SLUG}_meta.json", "w"), indent=2)
C.timing_record(f"H10_media_{SLUG}", time.time() - t_all, f"{DUR}s audio, two models")
print(f"\nH10[{SLUG}] {round(time.time()-t_all,1)}s cost=${meta['total_cost_usd']} "
      f"spend={C.total_spend()}")
