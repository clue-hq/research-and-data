"""Read the trial runs' activity from Langfuse (read-only): tool calls in order, and the model's
reasoning/text per round, since a given time. Uses this worktree's CLUE_LANGFUSE_* keys.

    uv run python trial/lf_watch.py <since-ISO> [--out file.jsonl]
"""
import json, os, sys
import httpx

since = sys.argv[1]
c = httpx.Client(base_url=os.environ["CLUE_LANGFUSE_HOST"], timeout=120,
                 auth=(os.environ["CLUE_LANGFUSE_PUBLIC_KEY"], os.environ["CLUE_LANGFUSE_SECRET_KEY"]))
rows, cur = [], None
while True:
    p = {"fromStartTime": since, "limit": 200, "fields": "core,basic,io",
         "environment": os.environ.get("CLUE_LANGFUSE_ENVIRONMENT", "")}
    if cur: p["cursor"] = cur
    r = c.get("/api/public/v2/observations", params=p); r.raise_for_status(); j = r.json()
    rows += j["data"]; cur = (j.get("meta") or {}).get("cursor")
    if not cur or not j["data"]: break
out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
if out:
    with open(out, "w") as f:
        for o in rows: f.write(json.dumps(o, default=str) + "\n")
print(len(rows), "observations;", len({o["traceId"] for o in rows}), "traces")
