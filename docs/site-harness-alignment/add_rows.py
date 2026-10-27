"""Append ledger rows for one source (site agent alignment; copied from docs/design-harness-alignment).

Usage:  python3 add_rows.py <source_id> <src_path> <<'ROWS'
@ TOPIC applies strength loc
verbatim text (may span lines)
~ optional note
ROWS

Re-running a source id REPLACES that source's ledger file (idempotent per source), unless
--append is given: then the rows are added after the source's existing rows (a later family's pass).
"""
import json, sys
from pathlib import Path

# Family 1 (page argument): KIND ARGUMENT STRUCTURE SUBSTANCE ACTION PEOPLE IDENTITY SHELL PLAN SCOPE ASK
# Family 2 (wording and evidence): SOURCING CLAIMS PROOF OFFPAGE VOICE HEADLINE COPY EVIDENCE
# Family 3 (imagery and media): IMAGERY ASSETS GENERATE LOGOS PRODUCTUI MOTION
# Later families: LAYOUT BRAND (4) · REVIEW (5) · TOOLS READING OUTPUT MECHANICS
TOPICS = {"KIND","ARGUMENT","STRUCTURE","SUBSTANCE","ACTION","PEOPLE","IDENTITY","SHELL","PLAN","SCOPE","ASK",
          "EVIDENCE","COPY","SOURCING","CLAIMS","PROOF","OFFPAGE","VOICE","HEADLINE","IMAGERY","ASSETS","GENERATE","LOGOS","PRODUCTUI","MOTION","LAYOUT","BRAND","REVIEW","TOOLS","READING","OUTPUT","MECHANICS"}
STRENGTHS = {"must","must-not","should","prefer","may","default","fact"}
append = "--append" in sys.argv
args = [a for a in sys.argv[1:] if a != "--append"]
sid, src = args[0], args[1]
rows, cur = [], None
for raw in sys.stdin.read().splitlines():
    if raw.startswith("@ "):
        if cur: rows.append(cur)
        topic, applies, strength, *loc = raw[2:].split()
        assert topic in TOPICS, topic
        assert strength in STRENGTHS, strength
        cur = {"topic": topic, "applies": applies, "strength": strength, "loc": " ".join(loc), "text": [], "note": []}
    elif raw.startswith("~ ") and cur:
        cur["note"].append(raw[2:])
    elif cur is not None:
        cur["text"].append(raw)
if cur: rows.append(cur)
path = Path(__file__).parent / "ledger" / f"{sid}.jsonl"
existing = [json.loads(l) for l in open(path)] if append and path.exists() else []
start = len(existing)
out = list(existing)
for i, r in enumerate(rows, start + 1):
    out.append({"id": f"{sid}-{i:02d}", "src": src, "loc": r["loc"], "topic": r["topic"],
                "applies": r["applies"], "strength": r["strength"],
                "text": " ".join(" ".join(r["text"]).split()), "note": " ".join(r["note"])})
path.write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in out))
print(f"{sid}: {len(out) - start} rows added, {len(out)} in all -> {path.name}")
