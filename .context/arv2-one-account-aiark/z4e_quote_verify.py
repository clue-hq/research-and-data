"""Z4e — verify the flash-lite quotes against the faithful ASR, and mine the second half
of the episode that flash-lite never actually transcribed. Verbatim-checked in code."""
import json, re, sys, time, unicodedata
sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

asr = open("transcripts/sanaz_boardroom_transcribe_model.md").read()
asr = asr[asr.find("## TRANSCRIPT") + 13:]


def norm(s):
    s = unicodedata.normalize("NFKC", s or "").replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"\s+", " ", s).strip().lower()).strip()


NA = norm(asr)


def contained(q, minlen=40):
    n = norm(q)
    if n in NA:
        return "EXACT"
    # longest-window check: does a 40-char window of the quote appear?
    for i in range(0, max(1, len(n) - minlen), 10):
        if n[i:i + minlen] in NA:
            return "PARTIAL"
    return "NOT_FOUND"


t0 = time.time()
fl = []
t = open("transcripts/sanaz_boardroom.md").read()
blk = t[t.find("## QUOTES"):]
blk = blk[:blk.find("\n## ", 5)] if "\n## " in blk[5:] else blk
for ln in blk.splitlines():
    m = re.match(r'^-\s*"?\[?(\d{1,2}:\d{2})\]?"?\s*"(.+?)"\s*->', ln.strip())
    if m:
        fl.append({"timestamp": m.group(1), "quote": m.group(2),
                   "in_asr": contained(m.group(2)),
                   "in_flash_lite_unique_window": m.group(1) <= "12:38"})
print("flash-lite quote verification vs the faithful ASR:")
for q in fl:
    print(f"  [{q['timestamp']}] {q['in_asr']:9s} unique_window={q['in_flash_lite_unique_window']} "
          f":: {q['quote'][:90]}")

SECOND = asr[len(asr) // 2:]
PROMPT = ("Below is the verbatim second half of a podcast transcript. The guest is Sanaz Yashar, "
          "co-founder and CEO of Zafran Security.\n\nReturn STRICT JSON: "
          '{"quotes":[{"quote":"<EXACT substring copied character-for-character from the text>",'
          '"topic":"buying_or_vendors|leadership|hiring|competition|product_belief|personal",'
          '"why":"one line"}]}\n'
          "Give 6 quotes, each 12-45 words, each an EXACT substring. Prefer moments about how she "
          "buys/evaluates vendors, how she builds and runs the company, what she believes, and "
          "what she is proud of. Never paraphrase.\n\nTEXT:\n" + SECOND)
out = C.gemini_generate("gemini-3.5-flash-lite", [{"text": PROMPT}], label="z4e_second_half_quotes",
                        timeout=600, max_output_tokens=4000)
txt = "".join(p.get("text") or "" for p in
              ((out.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
mined = []
try:
    j = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
    for q in j.get("quotes") or []:
        q["verbatim_check"] = contained(q.get("quote", ""))
        mined.append(q)
except Exception as e:
    print("parse fail", e, txt[:400])
print("\nmined from the half flash-lite never transcribed:")
for q in mined:
    print(f"  [{q['verbatim_check']}] ({q.get('topic')}) {q.get('quote')[:150]}")
json.dump({"flash_lite_quotes_verified": fl, "second_half_mined_quotes": mined,
           "asr_chars": len(asr)}, open("z4e_quote_verification.json", "w"), indent=2)
C.timing_record("Z4e_quote_verify", time.time() - t0, "verify + mine")
print(f"\nZ4e spend={C.total_spend()}")
