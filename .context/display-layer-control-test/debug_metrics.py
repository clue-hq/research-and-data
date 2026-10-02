"""Print the offending quotes / numbers / off-recipe citations for one result key."""
import json, re, sys
import control_test as ct
key = sys.argv[1]
rec = [json.loads(l) for l in open("results.jsonl") if l.strip()]
rec = [r for r in rec if r["key"] == key][0]
page = rec["page"]; rows = ct.PAGES[page]["claims"]
corpus = ct.norm(" ".join(c["value"] + " " + c["quote"] for c in rows)); cnums = ct.corpus_numbers(rows)
fk_of = {c["claimId"]: c["fieldKey"] for c in rows}
allowed = {s[0]: set(s[3]) for s in ct.PAGES[page]["sections"] if s[4] == "safe"}
for s in rec["sections"]:
    for it in s.get("items") or []:
        texts = [str(it.get("h2") or "")] + [str(b.get("text") or "") for b in it.get("body") or [] if isinstance(b, dict)]
        quotable = " ".join(texts); full = quotable + " " + str(it.get("sendLine") or "")
        full = re.sub(r"\[?\s*zaf-\d{3}(?:\s*,\s*zaf-\d{3})*\s*\]?", " ", full); quotable = re.sub(r"\[?\s*zaf-\d{3}(?:\s*,\s*zaf-\d{3})*\s*\]?", " ", quotable)
        for q in ct.extract_quotes(quotable):
            pieces = [p for p in re.split(r"…|\.\.\.", q) if len(p.split()) >= 4]
            if pieces and not all(ct.norm(p) in corpus for p in pieces):
                print(f"[{s['key']}] QUOTE NOT VERBATIM: “{q[:140]}”")
        for tok in ct.NUM_RE.findall(full):
            v = ct.num_variants(tok)
            try:
                if float(list(v)[0]) < 13: continue
            except ValueError: continue
            if not (v & cnums):
                ctx = full[max(0, full.find(tok) - 60): full.find(tok) + 40].replace("\n", " ")
                print(f"[{s['key']}] NUMBER NOT IN PAYLOAD: {tok!r}  …{ctx}…")
        for b in it.get("body") or []:
            for cid in (b.get("claimIds") or []) if isinstance(b, dict) else []:
                if s.get("key") in allowed and cid in fk_of and fk_of[cid] not in allowed[s["key"]]:
                    print(f"[{s['key']}] OFF-RECIPE: {cid} ({fk_of[cid]})")
