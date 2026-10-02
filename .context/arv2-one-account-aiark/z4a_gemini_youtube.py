"""Z4a — Gemini media layer, item 1: Nick Fisher's cocktail YouTube presence.

Public YouTube URL ingested directly via file_data.file_uri. Asks for an MM:SS timestamped
transcript, speaker labels, and verbatim quotes. Cost computed from real usageMetadata.
"""
import json, os, sys, time
sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

MODEL = "gemini-3.5-flash-lite"
VIDEO = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=avcD5WVLCYs"
SLUG = sys.argv[2] if len(sys.argv) > 2 else "nick_moscow_mule"

PROMPT = """You are transcribing a public YouTube video for a business-research record.

Return ONLY this structure, in plain text:

## META
title: <the on-screen/spoken title if stated, else NOT STATED>
duration_mmss: <total duration you observed>
speakers: <list every distinct speaker you can hear, labelled S1/S2/... with your best label>
narrator_identity_evidence: <verbatim anything the speaker says that names themselves or the channel; else NOT STATED>

## TRANSCRIPT
A full transcript. Every line MUST start with a [MM:SS] timestamp and a speaker label, like:
[00:12] S1 (narrator): <verbatim words>
Do not summarise. Do not skip sections. Use the real spoken words.

## QUOTES
Exactly 5 verbatim quotes that reveal how this person THINKS, what they VALUE, what they are
PROUD of, or how they approach craft/quality/experimentation. Format each as:
- "[MM:SS]" "<verbatim quote>" -> why it reveals something: <one line>
If the video contains fewer than 5 such moments, output only the ones that exist and then the
line: FEWER THAN 5 QUALIFYING MOMENTS EXIST.

Never invent words. If audio is unintelligible write [inaudible]."""

t0 = time.time()
parts = [{"file_data": {"file_uri": VIDEO}}, {"text": PROMPT}]
out = C.gemini_generate(MODEL, parts, label=f"z4a_yt_{SLUG}", timeout=1800,
                        max_output_tokens=32000)
cands = out.get("candidates") or []
text = ""
if cands:
    for p in (cands[0].get("content") or {}).get("parts") or []:
        text += p.get("text") or ""
print("finishReason:", cands[0].get("finishReason") if cands else None)
print("chars:", len(text))
if not text:
    print("RAW HEAD:", json.dumps(out)[:1200])
open(os.path.join("transcripts", f"{SLUG}.md"), "w").write(
    f"# Gemini transcript — {VIDEO}\nmodel: {MODEL}\n\n" + text)
um = out.get("usageMetadata") or {}
json.dump({"video": VIDEO, "model": MODEL, "usageMetadata": um,
           "cost_usd": C.gemini_cost(um), "elapsed_s": out.get("_elapsed_s"),
           "chars": len(text), "finishReason": cands[0].get("finishReason") if cands else None},
          open(f"z4a_{SLUG}_meta.json", "w"), indent=2)
C.timing_record(f"Z4a_gemini_youtube_{SLUG}", time.time() - t0, VIDEO)
print(text[:2500])
print(f"\nZ4a {round(time.time()-t0,1)}s spend={C.total_spend()}")
