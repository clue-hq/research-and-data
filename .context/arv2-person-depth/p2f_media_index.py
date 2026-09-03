"""Phase 2f — media_index.json: what each media item IS, what the no-key fallback actually
delivered, and the EXACT Gemini token/cost math for the run we could not make.

Gemini price sheet used (2.5 Flash-Lite / gemini-embedding-2), per the brief:
  audio input   $0.30 / 1M tokens, audio is billed at 32 tokens per SECOND
  text output   $0.40 / 1M tokens
  text embed    $0.20 / 1M tokens        (gemini-embedding-2)
  raw-audio embed $0.00016 / second      (gemini-embedding-2, native audio)
Speech-rate assumption for the OUTPUT estimate: 150 spoken words/min, 1.35 tokens/word,
plus one [MM:SS] stamp every 15s at ~5 tokens each. Assumptions are stated, not hidden.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p_lib as C  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TR = os.path.join(HERE, "transcripts")

AUDIO_TOK_PER_S = 32
P_AUDIO_IN = 0.30 / 1_000_000
P_TEXT_OUT = 0.40 / 1_000_000
P_TEXT_EMBED = 0.20 / 1_000_000
P_AUDIO_EMBED_PER_S = 0.00016
WORDS_PER_MIN = 150
TOK_PER_WORD = 1.35
STAMP_EVERY_S = 15
TOK_PER_STAMP = 5


def dur_to_s(v):
    if v is None:
        return 0
    s = str(v).strip()
    if s.isdigit():
        return int(s)
    parts = [int(x) for x in s.split(":") if x.isdigit()]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return 0


def gemini_math(duration_s):
    audio_tok = duration_s * AUDIO_TOK_PER_S
    words = duration_s / 60.0 * WORDS_PER_MIN
    out_tok = int(words * TOK_PER_WORD + (duration_s / STAMP_EVERY_S) * TOK_PER_STAMP)
    transcribe = audio_tok * P_AUDIO_IN + out_tok * P_TEXT_OUT
    embed_text = out_tok * P_TEXT_EMBED
    embed_audio = duration_s * P_AUDIO_EMBED_PER_S
    return {
        "duration_s": duration_s,
        "duration_hms": f"{duration_s//3600:d}:{(duration_s%3600)//60:02d}:{duration_s%60:02d}",
        "audio_input_tokens": audio_tok,
        "est_output_tokens_timestamped": out_tok,
        "cost_transcribe_usd": round(transcribe, 6),
        "cost_embed_transcript_text_usd": round(embed_text, 6),
        "cost_embed_raw_audio_usd": round(embed_audio, 6),
        "cost_transcribe_plus_text_embed_usd": round(transcribe + embed_text, 6),
    }


def read_len(fn):
    p = os.path.join(TR, fn)
    if not os.path.exists(p):
        return 0, 0
    t = open(p).read()
    body = t.split("\n\n", 1)[1] if "\n\n" in t else t
    return len(body), len(re.findall(r"\[\d{1,2}:\d{2}\]", body))


SPEAKS = {
    "vin_siemens": "YES - verified: the whole clip is his own Siemens Competition presentation",
    "vin_ep297": "YES - verified: he is the interviewed guest throughout",
    "vin_hackervalley": "YES - episode title names him as the guest (mp3 unread, no key)",
    "ala_gcsp265": "YES - verified in transcript: \"Today, we're joined by Alistair Patterson, the CEO and co-founder of Harmonic Security\"",
    "ala_sysk": "YES - episode title: \"...with Harmonic Security CEO Alastair Paterson\" (mp3 unread, no key)",
    "san_boardroom": "YES - episode title names her as the guest (mp3 unread, no key)",
    "ana_coffee": "NO - verified in transcript: the guests are \"Ed and James from Harmonic Security\"; Ana Corio never appears",
    "sem_cogentyt": "NO - verified: the speaker is Geng Sng (Cogent co-founder/CTO), not Alexander Semien",
    "man_uptiqyt": "UNKNOWN - no transcript indexed; product voiceover, uncredited",
    "man_cu20": "UNKNOWN - show notes name UPTIQ but no speaker; mp3 unread, no key",
}

EXTRA_ITEMS = {
    "ala_gcsp265": {"mirror_id": "ala_gcsp265_yt",
                    "mirror_url": "https://www.youtube.com/watch?v=qu51DBOkrNE",
                    "mirror_note": "the podcast's own YouTube mirror; Exa HAS its transcript"},
}


def main():
    resolved = json.load(open(os.path.join(HERE, "media_resolved.json")))
    index = []
    for r in resolved:
        p = r.get("probe") or {}
        t = r.get("transcript") or {}
        if r["kind"] == "linkedin_native_video":
            index.append({
                "id": r["id"], "person": r["person"], "url": r["url"], "kind": r["kind"],
                "status": "unfetchable_walled",
                "note": r["note"], "duration_s": None, "gemini_math": None,
                "fallback_delivered": {"source": "walled", "chars": 0, "timestamps_in_text": 0,
                                       "verdict": "never fetched (walled by design)"},
            })
            continue
        if r["kind"] == "youtube":
            dur = p.get("length_s") or 0
            title = p.get("title") or r["title_hint"]
            channel = p.get("author")
            mp3 = None
        else:
            ep = p.get("episode") or {}
            dur = dur_to_s(ep.get("itunes_duration"))
            title = ep.get("episode_title") or r["title_hint"]
            channel = None
            mp3 = ep.get("mp3_url")
        chars, stamps = read_len(f"{r['id']}_exa_page.txt")
        if not chars:
            chars, stamps = read_len(f"{r['id']}_shownotes.txt")
            src = "rss_shownotes" if chars else "nothing"
        else:
            src = "exa_indexed_page"
        extra = EXTRA_ITEMS.get(r["id"])
        if extra:
            mchars, mstamps = read_len(f"{extra['mirror_id']}_exa_page.txt")
            if mchars > chars:
                chars, stamps, src = mchars, mstamps, "exa_indexed_youtube_mirror"
        cap = (t.get("status") == "ok")
        index.append({
            "id": r["id"], "person": r["person"], "url": r["url"], "kind": r["kind"],
            "title": title, "channel_or_show": channel,
            "mp3_enclosure": mp3,
            "duration_s": dur,
            "target_speaks": SPEAKS.get(r["id"], r.get("target_speaks")),
            "youtube_caption_track_listed": bool(p.get("caption_tracks")),
            "youtube_timedtext_fetch": ("BLOCKED: http 200, 0 bytes, text/html on all 5 request forms"
                                        if r["kind"] == "youtube" else None),
            "fallback_delivered": {
                "source": src, "chars": chars, "timestamps_in_text": stamps,
                "verdict": ("full ASR transcript, NO timestamps" if src.startswith("exa_indexed") and chars > 8000
                            else "show-notes / page stub only" if chars else "nothing"),
            },
            "timestamps_in_text": stamps,
            "gemini_math": gemini_math(dur) if dur else None,
            "extra": extra,
        })
    fetchable = [i for i in index if i["duration_s"]]
    tot_s = sum(i["duration_s"] for i in fetchable)
    tot_tr = sum(i["gemini_math"]["cost_transcribe_usd"] for i in fetchable)
    tot_emb = sum(i["gemini_math"]["cost_embed_transcript_text_usd"] for i in fetchable)
    shorts = [i for i in fetchable if i["duration_s"] < 180]
    tot_audio_emb_shorts = sum(i["gemini_math"]["cost_embed_raw_audio_usd"] for i in shorts)
    summary = {
        "gemini_key_present_at_start": False,
        "gemini_key_present_at_media_phase": False,
        "gemini_key_recheck_note": ".env re-read immediately before Phase 2; file mtime unchanged (Aug 29). No CLUE_GEMINI_API_KEY.",
        "items_total": len(index),
        "items_with_duration": len(fetchable),
        "items_walled_never_fetched": len([i for i in index if i["kind"] == "linkedin_native_video"]),
        "total_media_seconds": tot_s,
        "total_media_hours": round(tot_s / 3600.0, 2),
        "price_sheet": {
            "audio_input_usd_per_1m_tokens": 0.30, "audio_tokens_per_second": 32,
            "text_output_usd_per_1m_tokens": 0.40,
            "text_embedding_usd_per_1m_tokens": 0.20,
            "raw_audio_embedding_usd_per_second": 0.00016,
            "model_transcribe": "gemini-2.5-flash-lite", "model_embed": "gemini-embedding-2",
        },
        "assumptions": {"words_per_minute": WORDS_PER_MIN, "tokens_per_word": TOK_PER_WORD,
                        "timestamp_every_s": STAMP_EVERY_S, "tokens_per_timestamp": TOK_PER_STAMP},
        "would_have_cost_usd": {
            "transcribe_all": round(tot_tr, 4),
            "embed_all_transcripts_text": round(tot_emb, 4),
            "embed_raw_audio_short_clips_only": round(tot_audio_emb_shorts, 4),
            "TOTAL_full_media_layer": round(tot_tr + tot_emb + tot_audio_emb_shorts, 4),
            "per_hour_of_audio_transcribe": round(tot_tr / (tot_s / 3600.0), 4) if tot_s else None,
            "embed_raw_audio_if_applied_to_ALL_items": round(tot_s * P_AUDIO_EMBED_PER_S, 4),
        },
        "no_key_fallback_delivered": {
            "youtube_public_timedtext": "DEAD — 200/0 bytes/text-html on baseUrl, fmt=json3, fmt=srv3, fmt=vtt, fmt=ttml, classic lang=en, kind=asr, c=WEB",
            "exa_indexed_youtube_page": "WORKS — carries the full ASR transcript text for 4/5 videos, but with NO timestamps",
            "podcast_mp3": "enclosure URLs resolve, but nothing can read them without a transcription model",
            "podcast_shownotes": "2-4 kB of marketing copy per episode; not voice",
        },
    }
    json.dump({"summary": summary, "items": index},
              open(os.path.join(HERE, "media_index.json"), "w"), indent=2)
    print(json.dumps(summary["would_have_cost_usd"], indent=2))
    print(f"\ntotal media {summary['total_media_hours']}h across {len(fetchable)} items\n")
    print(f"{'id':<20}{'person':<20}{'dur':>7}{'speaks':>10}{'chars':>8}{'stamps':>7}  source")
    for i in index:
        fb = i["fallback_delivered"]
        print(f"{i['id']:<20}{i['person']:<20}{str(i['duration_s'] or '-'):>7}"
              f"{str(i.get('target_speaks')):>10}{fb['chars']:>8}{fb['timestamps_in_text']:>7}  {fb['source'] if 'source' in fb else 'walled'}")


if __name__ == "__main__":
    main()
