"""Z6 — gemini-embedding-2 retrieval demo over the real transcripts.

Chunks every transcript by timestamp window, embeds each chunk as RETRIEVAL_DOCUMENT (768d),
embeds 3 real questions as RETRIEVAL_QUERY, ranks by cosine, prints top hits WITH timestamps.
Measures tokens, cost and latency for every call. Also computes what embedding the RAW AUDIO
would have cost at $0.00016/sec, for the record.
"""
import glob, json, math, os, re, sys, time
sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

TS = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.*)$")


def chunks_from(path, person, source_url, window_lines=14):
    lines = open(path).read().splitlines()
    body, started = [], False
    for ln in lines:
        if ln.startswith("## TRANSCRIPT"):
            started = True; continue
        if started and ln.startswith("## "):
            break
        if started and ln.strip():
            body.append(ln.strip())
    out, buf = [], []
    for ln in body:
        buf.append(ln)
        if len(buf) >= window_lines:
            out.append(buf); buf = []
    if buf:
        out.append(buf)
    res = []
    for b in out:
        m0, m1 = TS.match(b[0]), TS.match(b[-1])
        res.append({"person": person, "source": source_url,
                    "start": m0.group(1) if m0 else "?", "end": m1.group(1) if m1 else "?",
                    "text": " ".join(b)})
    return res


SOURCES = [
    ("transcripts/sanaz_boardroom.md", "Sanaz Yashar",
     "https://podcasters.spotify.com/pod/show/boardroomclub/episodes/"
     "AI-Summit-Sanaz-Yashar--Co-Founder-and-CEO-at-Zafran-Security-e36d9ai"),
    ("transcripts/nick_supporting_cc.md", "Nick Fisher",
     "https://www.youtube.com/watch?v=8_YWBtq4eic"),
    ("transcripts/nick_moscow_mule.md", "Nick Fisher",
     "https://www.youtube.com/watch?v=avcD5WVLCYs"),
]
extra = "transcripts/nick_faceless.md"
if os.path.exists(extra) and os.path.getsize(extra) > 400:
    SOURCES.append((extra, "Nick Fisher", "https://www.youtube.com/watch?v=4gKLZrv2p8g"))

t_all = time.time()
docs = []
for p, person, url in SOURCES:
    if os.path.exists(p):
        cs = chunks_from(p, person, url)
        print(f"  {p}: {len(cs)} chunks")
        docs += cs

print(f"\n== embedding {len(docs)} document chunks (gemini-embedding-2, 768d) ==")
d_tok = d_cost = 0.0
t0 = time.time()
for d in docs:
    r = C.gemini_embed(d["text"], label="z6_doc", task_type="RETRIEVAL_DOCUMENT", dim=768)
    d["vec"] = r["values"]; d_tok += r["tokens"]; d_cost += r["cost_usd"]
    if not r["values"]:
        print("   EMBED FAIL:", r["_raw_head"][:200]); break
doc_elapsed = round(time.time() - t0, 2)
print(f"   {len(docs)} chunks | {int(d_tok)} tokens | ${round(d_cost,6)} | {doc_elapsed}s "
      f"| dim={len(docs[0]['vec']) if docs and docs[0].get('vec') else 0}")

QUERIES = [
    "What does Sanaz say about how she buys, evaluates or chooses security tools and vendors?",
    "What is Nick most proud of, and what does he invest his own time and money in?",
    "What frustrates Sanaz most about how vulnerability management works today?",
]


def cos(a, b):
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(x * x for x in a[:n])); nb = math.sqrt(sum(x * x for x in b[:n]))
    return dot / (na * nb) if na and nb else 0.0


print("\n== 3 retrieval queries ==")
q_tok = q_cost = 0.0
report = []
for q in QUERIES:
    t1 = time.time()
    r = C.gemini_embed(q, label="z6_query", task_type="RETRIEVAL_QUERY", dim=768)
    q_tok += r["tokens"]; q_cost += r["cost_usd"]
    ranked = sorted(docs, key=lambda d: cos(r["values"], d.get("vec") or []), reverse=True)[:3]
    hits = [{"rank": i + 1, "score": round(cos(r["values"], d["vec"]), 4), "person": d["person"],
             "timestamp": f"[{d['start']}–{d['end']}]", "source": d["source"],
             "text": d["text"][:700]} for i, d in enumerate(ranked)]
    report.append({"query": q, "query_tokens": r["tokens"], "query_cost_usd": r["cost_usd"],
                   "latency_s": round(time.time() - t1, 2), "hits": hits})
    print(f"\nQ: {q}")
    for h in hits:
        print(f"  #{h['rank']} score={h['score']} {h['person']} {h['timestamp']}")
        print(f"     {h['text'][:320]}")

media_seconds = 42 * 60 + 49 + 254 + 91  # sanaz + moscow mule (4:14) + supporting (1:31)
if len(SOURCES) == 4:
    media_seconds += json.load(open("z4a_nick_faceless_meta.json")).get("observed_seconds", 0) \
        if os.path.exists("z4a_nick_faceless_meta.json") else 0
summary = {
    "model": "gemini-embedding-2", "dim": 768, "chunks": len(docs),
    "doc_tokens": int(d_tok), "doc_cost_usd": round(d_cost, 6), "doc_elapsed_s": doc_elapsed,
    "query_tokens": int(q_tok), "query_cost_usd": round(q_cost, 6),
    "total_embed_cost_usd": round(d_cost + q_cost, 6),
    "raw_audio_embedding_would_have_cost_usd": round(media_seconds * 0.00016, 4),
    "raw_audio_seconds_considered": media_seconds,
    "queries": report,
}
json.dump(summary, open("z6_retrieval_demo.json", "w"), indent=2)
C.timing_record("Z6_embed_retrieval", time.time() - t_all,
                f"{len(docs)} chunks + {len(QUERIES)} queries")
print(f"\nZ6 {round(time.time()-t_all,1)}s embed_total=${summary['total_embed_cost_usd']} "
      f"| raw-audio embedding would have cost ${summary['raw_audio_embedding_would_have_cost_usd']}"
      f" | run spend={C.total_spend()}")
