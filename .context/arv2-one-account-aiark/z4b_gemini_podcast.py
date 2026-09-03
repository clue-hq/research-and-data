"""Z4b — Gemini media layer, item 2: Sanaz Yashar's podcast appearance (Boardroom Club).

MP3 enclosure from the show's RSS -> Gemini Files API (resumable upload) -> generateContent.
Asks for an MM:SS timestamped transcript, speaker labels and verbatim quotes.
Cost from real usageMetadata.
"""
import json, os, sys, time, urllib.request
sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

MODEL = "gemini-3.5-flash-lite"
MP3 = ("https://anchor.fm/s/f695d6d8/podcast/play/106390290/"
       "https%3A%2F%2Fd3ctxlq1ktw2nl.cloudfront.net%2Fstaging%2F2025-7-9%2F"
       "405396769-44100-2-7287bb9271f44.mp3")
SLUG = "sanaz_boardroom"
DUR_S = 42 * 60 + 49
LOCAL = os.path.join("raw", f"{SLUG}.mp3")

PROMPT = """You are transcribing a public podcast episode for a business-research record.
The guest is Sanaz Yashar, co-founder and CEO of Zafran Security.

Return ONLY this structure, in plain text:

## META
speakers: <label every distinct speaker S1/S2/... with your best identification and the evidence>
guest_identity_evidence: <verbatim words in the audio that identify the guest; else NOT STATED>
duration_mmss: <total duration you observed>

## TRANSCRIPT
A full transcript of the WHOLE episode. Every line MUST start with an [MM:SS] timestamp and a
speaker label, like:
[03:41] S2 (Sanaz Yashar): <verbatim words>
Do not summarise, do not skip, do not stop early. Use the real spoken words.

## QUOTES
Exactly 5 verbatim quotes from the GUEST that reveal how she thinks, what she values, how she
buys/evaluates tools or vendors, what she is proud of, or what frustrates her. Format:
- "[MM:SS]" "<verbatim quote>" -> why it matters: <one line>

## BUYING_AND_VENDOR_SIGNALS
Any moment where the guest talks about buying, evaluating, choosing, or being sold to by
vendors/tools, or about how she runs go-to-market/marketing. Each as: [MM:SS] verbatim + one line.
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
        print("   resp:", t[:400]); return None
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
        print("   resp:", t2[:400]); return None
    C.save_raw(f"z4b_file_upload_{SLUG}", {k: v for k, v in f.items() if k != "downloadUri"})
    C.ledger_append({"provider": "gemini", "label": f"z4b_files_upload_{SLUG}",
                     "op": "files.upload", "http": s2, "elapsed_s": e2, "cost_usd": 0.0,
                     "bytes": size, "note": "Files API upload is free"})
    name = f.get("name")
    for _ in range(60):
        s3, _h, t3, _e = C._request(
            f"{C.GEMINI_BASE}/{name}?key={C.GEMINI_KEY}", method="GET", headers={},
            timeout=60, retries=2)
        st = (json.loads(t3) or {}).get("state")
        print(f"   state={st}")
        if st == "ACTIVE":
            return json.loads(t3)
        if st == "FAILED":
            return None
        time.sleep(5)
    return None


t_all = time.time()
if not os.path.exists(LOCAL):
    print("== downloading mp3 ==")
    t0 = time.time()
    req = urllib.request.Request(MP3, headers={"User-Agent": C.BROWSER_UA})
    with urllib.request.urlopen(req, timeout=600) as r, open(LOCAL, "wb") as f:
        f.write(r.read())
    dl = round(time.time() - t0, 2)
    C.ledger_append({"provider": "live_http", "label": f"z4b_mp3_download_{SLUG}",
                     "op": "GET mp3 enclosure", "http": 200, "elapsed_s": dl,
                     "cost_usd": 0.0, "bytes": os.path.getsize(LOCAL)})
    print(f"   {os.path.getsize(LOCAL)} bytes in {dl}s")

print("== uploading to Gemini Files API ==")
finfo = upload_file(LOCAL, "audio/mpeg", "boardroom-sanaz-yashar")
if not finfo:
    print("UPLOAD FAILED"); sys.exit(1)
print("   uri:", finfo.get("uri"), "state:", finfo.get("state"),
      "videoMetadata/duration:", finfo.get("videoMetadata"))

print("== generateContent ==")
parts = [{"file_data": {"file_uri": finfo["uri"], "mime_type": "audio/mpeg"}}, {"text": PROMPT}]
out = C.gemini_generate(MODEL, parts, label=f"z4b_podcast_{SLUG}", timeout=3000,
                        max_output_tokens=60000, audio_seconds=DUR_S)
cands = out.get("candidates") or []
text = ""
if cands:
    for p in (cands[0].get("content") or {}).get("parts") or []:
        text += p.get("text") or ""
fr = cands[0].get("finishReason") if cands else None
print("finishReason:", fr, "chars:", len(text))
if not text:
    print("RAW HEAD:", json.dumps(out)[:1500])
open(os.path.join("transcripts", f"{SLUG}.md"), "w").write(
    f"# Gemini transcript — Boardroom Club: AI Summit: Sanaz Yashar (Zafran Security)\n"
    f"source_mp3: {MP3}\nmodel: {MODEL}\nduration: 00:42:49\n\n" + text)
um = out.get("usageMetadata") or {}
json.dump({"mp3": MP3, "model": MODEL, "duration_s": DUR_S, "usageMetadata": um,
           "cost_usd": C.gemini_cost(um), "elapsed_s": out.get("_elapsed_s"),
           "chars": len(text), "finishReason": fr},
          open(f"z4b_{SLUG}_meta.json", "w"), indent=2)
C.timing_record(f"Z4b_gemini_podcast_{SLUG}", time.time() - t_all, MP3[:100])
print(f"\nZ4b {round(time.time()-t_all,1)}s spend={C.total_spend()}")
