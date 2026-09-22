"""H13 — gemini-embedding-2 retrieval demo over the real transcripts.

Chunks every TIMESTAMPED transcript by timestamp window (so a hit carries an MM:SS), embeds each
chunk as RETRIEVAL_DOCUMENT (768d), embeds the real questions as RETRIEVAL_QUERY, ranks by cosine,
and prints top hits WITH timestamps. Measures tokens, cost and latency for every call, and
computes the raw-audio-embedding counterfactual at $0.00016/second for the record.
"""
import json
import math
import os
import re
import sys
import time

sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

TS = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.*)$")
MI = json.load(open("media_index.json"))


def chunks_from(path, person, page_url, title, window_lines=10):
    txt = open(path).read()
    k = txt.find("## TRANSCRIPT")
    body_txt = txt[k + 13:] if k >= 0 else txt
    body = []
    for ln in body_txt.splitlines():
        ln = ln.strip()
        if ln.startswith("## "):
            break
        if ln and TS.match(ln):
            body.append(ln)
    out, buf = [], []
    for ln in body:
        buf.append(ln)
        if len(buf) >= window_lines:
            out.append(buf)
            buf = []
    if buf:
        out.append(buf)
    res = []
    for b in out:
        m0, m1 = TS.match(b[0]), TS.match(b[-1])
        res.append({"person": person, "source": page_url, "title": title,
                    "start": m0.group(1) if m0 else "?", "end": m1.group(1) if m1 else "?",
                    "text": " ".join(b)})
    return res


t_all = time.time()
docs = []
for item in MI["items"]:
    p = f"transcripts/{item['slug']}_timestamped.md"
    if not os.path.exists(p):
        continue
    cs = chunks_from(p, item["person"], item["page_url"], item["title"])
    print(f"  {item['slug']:24s} {len(cs)} chunks")
    docs += cs

print(f"\n== embedding {len(docs)} document chunks (gemini-embedding-2, 768d) ==")
d_tok = d_cost = 0.0
t0 = time.time()
for d in docs:
    r = C.gemini_embed(d["text"], label="h13_doc", task_type="RETRIEVAL_DOCUMENT", dim=768)
    d["vec"] = r["values"]
    d_tok += r["tokens"]
    d_cost += r["cost_usd"]
    if not r["values"]:
        print("   EMBED FAIL:", r["_raw_head"][:200])
        break
doc_elapsed = round(time.time() - t0, 2)
print(f"   {len(docs)} chunks | {int(d_tok)} tokens | ${round(d_cost,6)} | {doc_elapsed}s | "
      f"dim={len(docs[0]['vec']) if docs and docs[0].get('vec') else 0}")

QUERIES = [
    "What does Ben Rafter say about AI or technology in hotel operations?",
    "What does Ben Rafter say frustrates consistency, service or labor at scale across hotels?",
    "How does Hotel Equities choose, beta-test or evaluate vendors and new technology?",
    "What does Ben Rafter say about guest-facing service, the front desk and guest interaction?",
]


def cos(a, b):
    n = min(len(a), len(b))
    if not n:
        return 0.0
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(x * x for x in a[:n]))
    nb = math.sqrt(sum(x * x for x in b[:n]))
    return dot / (na * nb) if na and nb else 0.0


print(f"\n== {len(QUERIES)} retrieval queries ==")
q_tok = q_cost = 0.0
report = []
for q in QUERIES:
    t1 = time.time()
    r = C.gemini_embed(q, label="h13_query", task_type="RETRIEVAL_QUERY", dim=768)
    q_tok += r["tokens"]
    q_cost += r["cost_usd"]
    ranked = sorted(docs, key=lambda d: cos(r["values"], d.get("vec") or []), reverse=True)[:3]
    hits = [{"rank": i + 1, "score": round(cos(r["values"], d["vec"]), 4), "person": d["person"],
             "timestamp": f"[{d['start']}–{d['end']}]", "episode": d["title"][:80],
             "source": d["source"], "text": d["text"][:800]}
            for i, d in enumerate(ranked)]
    report.append({"query": q, "query_tokens": r["tokens"], "query_cost_usd": r["cost_usd"],
                   "latency_s": round(time.time() - t1, 2), "hits": hits})
    print(f"\nQ: {q}")
    for h in hits:
        print(f"  #{h['rank']} score={h['score']} {h['timestamp']} :: {h['episode'][:60]}")
        print(f"     {h['text'][:260]}")

media_seconds = MI["summary"]["total_media_seconds"]
summary = {
    "model": "gemini-embedding-2", "dim": 768, "chunks": len(docs),
    "doc_tokens": int(d_tok), "doc_cost_usd": round(d_cost, 6), "doc_elapsed_s": doc_elapsed,
    "query_tokens": int(q_tok), "query_cost_usd": round(q_cost, 8),
    "total_embed_cost_usd": round(d_cost + q_cost, 6),
    "media_seconds_indexed": media_seconds,
    "raw_audio_embedding_would_have_cost_usd": round(media_seconds * 0.00016, 4),
    "raw_audio_multiple": round((media_seconds * 0.00016) / (d_cost + q_cost), 1)
    if (d_cost + q_cost) else None,
    "queries": report,
}
json.dump(summary, open("h13_retrieval_demo.json", "w"), indent=2)
C.timing_record("H13_embed_retrieval", time.time() - t_all,
                f"{len(docs)} chunks + {len(QUERIES)} queries")
print(f"\nH13 {round(time.time()-t_all,1)}s embed_total=${summary['total_embed_cost_usd']} "
      f"| raw-audio embedding would have cost ${summary['raw_audio_embedding_would_have_cost_usd']}"
      f" ({summary['raw_audio_multiple']}x) | run spend={C.total_spend()}")
