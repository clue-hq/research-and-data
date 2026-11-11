"""Simulates media_acquisition._acquire_youtube's recovery zip after covered_window re-asked."""
from clue_api.footprint.gemini_media_client import Transcript, TranscriptLine, covered_window, join_windows, youtube_windows

def part(first, last, tag):
    lines = (TranscriptLine(ts_s=first, speaker="Speaker 0", text=f"{tag}-start"),
             TranscriptLine(ts_s=last, speaker="Speaker 0", text=f"{tag}-end"))
    return Transcript(model="m", text="\n".join(l.text for l in lines), lines=lines, finish_reason="STOP")

windows = youtube_windows(7200, 2400)  # 3 windows
# Live run: w0 stops early at 1000s -> re-asked from 1000 (answers to 2380); w1 fine; w2 Gemini 503.
answers = {(0, 2400): part(0, 1000, "w0"), (1000, 2400): part(0, 1380, "w0b"), (2400, 4800): part(0, 2390, "w1")}
bodies = []
def transcribe(s, e):
    if (s, e) not in answers:
        raise RuntimeError("503")
    bodies.append(answers[(s, e)])
    return answers[(s, e)]
try:
    [p for s, e in windows for p in covered_window(transcribe, s, e)]
except RuntimeError:
    pass
print("windows:", windows, "saved 2xx bodies:", len(bodies))
# recovery path: `if len(bodies) == len(windows)` then zip(windows, bodies, strict=True)
assert len(bodies) == len(windows)
rec = join_windows([(start, b) for (start, _), b in zip(windows, bodies, strict=True)])
for l in rec.lines:
    print(f"  {l.ts_s:5d}s {l.text}")
print("finish_reason:", rec.finish_reason, "(w2 = 4800-7200 never transcribed)")
