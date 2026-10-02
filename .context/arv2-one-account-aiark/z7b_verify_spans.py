"""Z7b — verify every evidence_span is a VERBATIM substring of the bundle sources. Zero calls."""
import json, os, re, sys, unicodedata

deep = open("report_account_zafran_deep.md").read()
own = json.load(open("raw/z2_own_site.json"))
corpus = deep + "\n".join((r.get("text") or "") for r in (own.get("results") or []))
for f in ["transcripts/sanaz_boardroom.md", "transcripts/nick_supporting_cc.md",
          "transcripts/nick_moscow_mule.md"]:
    corpus += open(f).read()
corpus += "\n".join(x["text"] for x in json.load(open("z3_media_resolve.json"))["identity_binding"])


def norm(s):
    s = unicodedata.normalize("NFKC", s or "")
    s = (s.replace("’", "'").replace("‘", "'").replace("“", '"')
         .replace("”", '"').replace("—", "-").replace("–", "-")
         .replace(" ", " "))
    return re.sub(r"\s+", " ", s).strip().lower()


NC = norm(corpus)
d = json.load(open("z7_structured.json"))
report = {"verbatim": 0, "not_verbatim": 0, "failures": []}
for bucket in ("account_claims", "contact_claims", "proposed_fields", "negatives_and_risks"):
    for c in d.get(bucket) or []:
        raw = c.get("evidence_span") or ""
        # the model sometimes stitches several real spans with "..."; check each fragment
        frags = [f for f in re.split(r"\.\.\.+|\u2026", raw) if len(norm(f)) >= 25]
        if not frags:
            frags = [raw]
        checked = [(norm(f), norm(f) in NC) for f in frags]
        ok = bool(checked) and all(v for _, v in checked)
        c["evidence_span_fragments_checked"] = len(checked)
        c["evidence_span_fragments_failed"] = [f[:120] for f, v in checked if not v]
        c["evidence_span_verbatim"] = ok
        if ok:
            report["verbatim"] += 1
        else:
            report["not_verbatim"] += 1
            report["failures"].append({"bucket": bucket,
                                       "field": c.get("field_key") or c.get("suggested_key")
                                       or c.get("what"),
                                       "span": (c.get("evidence_span") or "")[:200],
                                       "failed_fragments": c["evidence_span_fragments_failed"][:3]})
json.dump(d, open("z7_structured.json", "w"), indent=2)
json.dump(report, open("z7b_span_check.json", "w"), indent=2)
print(f"verbatim={report['verbatim']} not_verbatim={report['not_verbatim']}")
for f in report["failures"][:20]:
    print(f"  FAIL [{f['bucket']}] {f['field']}: {f['span'][:140]}")
