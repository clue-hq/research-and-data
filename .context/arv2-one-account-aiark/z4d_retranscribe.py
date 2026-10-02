"""Z4d — the 42:49 podcast re-run on gemini-3.5-transcribe after flash-lite LOOPED.

flash-lite produced 329 timestamped lines of which only 120 were unique; sustained repetition
began at [12:41]. This re-runs the SAME uploaded file on the dedicated transcription model and
measures whether the loop is a model artefact.
"""
import json, os, re, sys, time
sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

FILE_URI = json.load(open("raw/z4b_file_upload_sanaz_boardroom.json"))["uri"]
DUR = 2569
MODEL = "gemini-3.5-transcribe"
PROMPT = """Transcribe this entire podcast episode. The guest is Sanaz Yashar, co-founder and CEO
of Zafran Security; the host is Yossi Carmazin.

Output ONLY transcript lines, each starting with an [MM:SS] timestamp and a speaker label:
[03:41] Sanaz Yashar: <verbatim words>
Cover the WHOLE episode from 00:00 to the end. Never repeat a passage you have already emitted.
Never invent words. Mark unintelligible audio [inaudible]."""

t0 = time.time()
parts = [{"file_data": {"file_uri": FILE_URI, "mime_type": "audio/mpeg"}}, {"text": PROMPT}]
out = C.gemini_generate(MODEL, parts, label="z4d_transcribe_sanaz", timeout=3000,
                        max_output_tokens=32000, audio_seconds=DUR)
cands = out.get("candidates") or []
text = "".join(p.get("text") or "" for p in ((cands[0].get("content") or {}).get("parts") or [])) if cands else ""
fr = cands[0].get("finishReason") if cands else None
lines = [m.groups() for m in
         (re.match(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.*)$", ln.strip()) for ln in text.splitlines())
         if m]
uniq = len({t for _, t in lines})
print(f"finishReason={fr} chars={len(text)} lines={len(lines)} unique={uniq}")
last_ts = lines[-1][0] if lines else None
open(os.path.join("transcripts", "sanaz_boardroom_transcribe_model.md"), "w").write(
    f"# Gemini transcript (dedicated model) — Boardroom Club: Sanaz Yashar\n"
    f"model: {MODEL}\nduration: 00:42:49\n\n## TRANSCRIPT\n" + text)
um = out.get("usageMetadata") or {}
json.dump({"model": MODEL, "usageMetadata": um, "cost_usd": C.gemini_cost(um),
           "elapsed_s": out.get("_elapsed_s"), "chars": len(text), "finishReason": fr,
           "timestamped_lines": len(lines), "unique_lines": uniq,
           "last_timestamp": last_ts,
           "flash_lite_comparison": json.load(open("z4b_transcript_quality.json"))},
          open("z4d_transcribe_meta.json", "w"), indent=2)
C.timing_record("Z4d_retranscribe", time.time() - t0, MODEL)
print(f"last_ts={last_ts} spend={C.total_spend()}")
