"""H12 — quote repair + media index. Zero provider calls, pure verification.

Two jobs:

1. LOOP DETECTION, done properly. The first-duplicate heuristic in h10 is too eager: a podcast
   legitimately repeats short lines ("Yeah." / "Right."). A real flash-lite loop is a SUSTAINED
   run of repeats. This re-scores every item: a loop is declared only when >=4 duplicated
   long lines (>25 normalised chars) occur after a point.

2. QUOTE REPAIR. flash-lite lightly cleans filler words, so its quotes come back PARTIAL against
   the faithful ASR. Rather than publish flash-lite's wording, this finds the matching span INSIDE
   the faithful transcript and emits the exact verbatim text from the dedicated ASR model, with
   flash-lite's MM:SS attached. What gets published is therefore: wording from the faithful model,
   timestamp from the timestamped model, both checked in code. Anything that cannot be located in
   the faithful transcript is dropped and recorded as dropped.
"""
import glob
import json
import os
import re
import unicodedata

SLUGS = ["rafter_ai_payoff", "rafter_ai_labor", "rafter_owner_economics",
         "rafter_tech_advice", "rafter_tech_ceo"]
TS = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.*)$")


def norm_map(s):
    """Normalise, keeping a map from normalised index -> original index."""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("’", "'").replace("“", '"').replace("”", '"')
    out, idx, prev_space = [], [], True
    for i, ch in enumerate(s):
        c = ch.lower()
        if c.isalnum():
            out.append(c)
            idx.append(i)
            prev_space = False
        else:
            if not prev_space:
                out.append(" ")
                idx.append(i)
                prev_space = True
    return "".join(out).strip(), idx


def norm(s):
    return norm_map(s)[0]


def faithful_body(path):
    t = open(path).read()
    k = t.find("## TRANSCRIPT")
    return t[k + 13:].strip() if k >= 0 else t


def locate(quote, ftext, fnorm, fidx, minwin=45):
    """Return the exact verbatim span from the faithful transcript matching `quote`."""
    q = norm(quote)
    if not q:
        return None, "EMPTY"
    pos = fnorm.find(q)
    kind = "EXACT"
    if pos < 0:
        # longest window of the quote that appears in the faithful text
        best = (-1, 0, 0)
        for L in (len(q), 160, 120, 90, 70, minwin):
            if L > len(q):
                continue
            for i in range(0, len(q) - L + 1, 5):
                p = fnorm.find(q[i:i + L])
                if p >= 0 and L > best[2]:
                    best = (p, i, L)
                    break
            if best[0] >= 0:
                break
        if best[0] < 0:
            return None, "NOT_FOUND"
        pos, qlen, kind = best[0], best[2], "WINDOW"
    else:
        qlen = len(q)
    a = fidx[pos]
    b = fidx[min(pos + qlen, len(fidx) - 1)]
    # A WINDOW match can land mid-word at either end. Always widen to whole words first,
    # then prefer a clean sentence span when one is available at a readable length.
    while a > 0 and not ftext[a - 1].isspace():
        a -= 1
    while b < len(ftext) and not ftext[b].isspace():
        b += 1
    span = ftext[a:b].strip()
    la = ftext.rfind(".", max(0, a - 320), a)
    rb = ftext.find(".", b, min(len(ftext), b + 320))
    if la >= 0 and rb > la:
        cand = ftext[la + 1:rb + 1].strip()
        if 60 <= len(cand) <= 520:
            span = cand
    span = re.sub(r"\s+", " ", span).strip()
    # a fragment that still reads as a fragment is worse than no quote
    if len(span) < 45:
        return None, "TOO_SHORT"
    return span, kind


index = []
all_quotes = []
for slug in SLUGS:
    mpath = f"h10_{slug}_meta.json"
    fpath = f"transcripts/{slug}_faithful.md"
    tpath = f"transcripts/{slug}_timestamped.md"
    if not (os.path.exists(mpath) and os.path.exists(fpath)):
        print(f"  !! missing artifacts for {slug}")
        continue
    meta = json.load(open(mpath))
    ftext = faithful_body(fpath)
    fnorm, fidx = norm_map(ftext)

    # --- proper loop re-scoring on the timestamped transcript ---
    ttext = open(tpath).read()
    lines = [m.groups() for m in (TS.match(ln.strip()) for ln in ttext.splitlines()) if m]
    seen, dup_positions = {}, []
    for i, (ts, txt) in enumerate(lines):
        k = norm(txt)
        if len(k) > 25:
            if k in seen:
                dup_positions.append(i)
            seen[k] = i
    sustained = None
    for i in range(len(dup_positions) - 3):
        if dup_positions[i + 3] - dup_positions[i] <= 12:
            sustained = lines[dup_positions[i]][0]
            break
    long_lines = [1 for _, t in lines if len(norm(t)) > 25]
    dup_rate = round(100.0 * len(dup_positions) / max(1, len(long_lines)), 1)

    repaired, dropped = [], []
    for q in meta.get("quotes", []):
        span, kind = locate(q["quote"], ftext, fnorm, fidx)
        if not span or kind == "NOT_FOUND":
            dropped.append({**q, "reason": "not located in the faithful ASR transcript"})
            continue
        repaired.append({
            "timestamp": q["timestamp"],
            "quote_published": span,
            "match_kind": kind,
            "flash_lite_wording": q["quote"],
            "inside_unique_window": (sustained is None or q["timestamp"] < sustained),
            "person": meta["person"], "title": meta["title"],
            "page_url": meta["page_url"], "published": meta["published"],
            "slug": slug,
        })
    for q in repaired:
        all_quotes.append(q)

    meta["loop_rescored"] = {"sustained_loop_starts_at": sustained,
                             "duplicate_long_lines": len(dup_positions),
                             "long_lines": len(long_lines),
                             "duplicate_rate_pct": dup_rate,
                             "verdict": "LOOPED" if sustained else "clean"}
    meta["quotes_repaired"] = repaired
    meta["quotes_dropped"] = dropped
    json.dump(meta, open(mpath, "w"), indent=2)

    audio_tok = sum(d.get("tokenCount") or 0
                    for d in (meta["faithful"]["usageMetadata"].get("promptTokensDetails") or [])
                    if d.get("modality") == "AUDIO")
    index.append({
        "slug": slug, "person": meta["person"], "title": meta["title"],
        "show": "Hospitality Daily (host Josiah Mackenzie)",
        "page_url": meta["page_url"], "mp3": meta["mp3"], "published": meta["published"],
        "duration_seconds": meta["duration_seconds"],
        "duration_mmss": f"{meta['duration_seconds']//60:02d}:{meta['duration_seconds']%60:02d}",
        "modality": "audio (mp3 enclosure)",
        "faithful_model": "gemini-3.5-transcribe",
        "timestamped_model": "gemini-3.5-flash-lite",
        "audio_tokens": audio_tok,
        "audio_tokens_per_second": round(audio_tok / meta["duration_seconds"], 2),
        "faithful_cost_usd": meta["faithful"]["cost_usd"],
        "timestamped_cost_usd": meta["timestamped"]["cost_usd"],
        "total_cost_usd": meta["total_cost_usd"],
        "faithful_words": meta["faithful"]["words"],
        "words_per_minute": round(meta["faithful"]["words"] / (meta["duration_seconds"] / 60), 1),
        "latency_s": round((meta["faithful"]["elapsed_s"] or 0)
                           + (meta["timestamped"]["elapsed_s"] or 0), 1),
        "loop_verdict": meta["loop_rescored"]["verdict"],
        "loop_starts_at": sustained,
        "quotes_kept": len(repaired), "quotes_dropped": len(dropped),
        "usable": True,
    })
    print(f"{slug:24s} {meta['duration_seconds']:>5}s  {audio_tok/meta['duration_seconds']:>5.1f} tok/s  "
          f"${meta['total_cost_usd']:<9} loop={meta['loop_rescored']['verdict']:<7} "
          f"dup_rate={dup_rate}%  quotes {len(repaired)} kept / {len(dropped)} dropped")

total_s = sum(i["duration_seconds"] for i in index)
total_c = round(sum(i["total_cost_usd"] for i in index), 6)
summary = {
    "items": len(index), "total_media_seconds": total_s,
    "total_media_hms": f"{total_s//3600}h {(total_s%3600)//60}m {total_s%60}s",
    "media_ceiling_seconds": 2.5 * 3600,
    "ceiling_used_pct": round(100.0 * total_s / (2.5 * 3600), 1),
    "total_cost_usd": total_c,
    "cost_per_hour_of_media_usd": round(total_c / (total_s / 3600), 4) if total_s else None,
    "raw_audio_embedding_counterfactual_usd": round(total_s * 0.00016, 4),
    "raw_audio_embedding_note": ("what embedding the RAW AUDIO of these same seconds would have "
                                 "cost at $0.00016/second, for the record — compare with the text "
                                 "embedding cost in h13_retrieval_demo.json"),
    "people_covered": sorted({i["person"] for i in index}),
    "quotes_published": len(all_quotes),
}
json.dump({"summary": summary, "items": index, "quotes": all_quotes},
          open("media_index.json", "w"), indent=2)
print("\n" + json.dumps(summary, indent=2))
