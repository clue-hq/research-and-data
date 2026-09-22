"""H18 — the AI Ark FIELD INVENTORY: every response field with its real Hotel Equities value.

Walks the saved raw responses. Zero provider calls. birth_date is already scrubbed from raw/;
the walker hard-skips it as a second guard.
"""
import json
import os

SKIP = {"birth_date", "birthDate", "birthday"}
MAXV = 340


def walk(obj, prefix="", rows=None, depth=0):
    rows = rows if rows is not None else []
    if depth > 6:
        return rows
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in SKIP:
                rows.append({"field": f"{prefix}{k}", "type": "REDACTED",
                             "value": "NEVER RECORDED (run rule)"})
                continue
            walk(v, f"{prefix}{k}.", rows, depth + 1)
    elif isinstance(obj, list):
        if not obj:
            rows.append({"field": prefix.rstrip("."), "type": "list", "value": "[] (EMPTY)"})
        elif isinstance(obj[0], (dict, list)):
            rows.append({"field": prefix.rstrip("."), "type": f"list[{len(obj)}]",
                         "value": f"{len(obj)} items -> fields below"})
            walk(obj[0], prefix.rstrip(".") + "[0].", rows, depth + 1)
            if len(obj) > 1:
                rows.append({"field": prefix.rstrip(".") + "[*]", "type": "list values",
                             "value": json.dumps(
                                 [x.get("name") or x.get("title") or x.get("type")
                                  or (x.get("school") or {}).get("name")
                                  if isinstance(x, dict) else x for x in obj],
                                 ensure_ascii=False)[:MAXV]})
        else:
            rows.append({"field": prefix.rstrip("."), "type": f"list[{len(obj)}] scalar",
                         "value": json.dumps(obj, ensure_ascii=False)[:MAXV]})
    else:
        v = json.dumps(obj, ensure_ascii=False)
        rows.append({"field": prefix.rstrip("."),
                     "type": ("null (EMPTY)" if obj is None else type(obj).__name__),
                     "value": (v[:MAXV] + ("…" if len(v) > MAXV else ""))})
    return rows


inv = {}
R = "raw"

co = json.load(open(f"{R}/h3_companies_hotelequities.json"))
inv["POST /v1/companies"] = {
    "request": co["_request_body"], "http": co["_http_status"], "elapsed_s": co["_elapsed_s"],
    "credits_billed": 0.1, "envelope_fields": sorted(co["_body"].keys()),
    "totalElements": co["_body"].get("totalElements"),
    "fields": walk(co["_body"]["content"][0])}

pd = json.load(open(f"{R}/h9_people_ben_rafter.json"))
inv["POST /v1/people (person object)"] = {
    "request": pd["_request_body"], "http": pd["_http_status"], "elapsed_s": pd["_elapsed_s"],
    "credits_billed": 0.5, "subject": "Ben Rafter (representative full person object)",
    "envelope_fields": sorted(pd["_body"].keys()),
    "totalElements": pd["_body"].get("totalElements"),
    "fields": walk(pd["_body"]["content"][0])}

ex = json.load(open(f"{R}/h9_email_ben-rafter-623a702.json"))
inv["POST /v1/people/export/single (email block)"] = {
    "request": ex["_request_body"], "http": ex["_http_status"], "elapsed_s": ex["_elapsed_s"],
    "credits_billed": 1.0, "subject": "Ben Rafter",
    "envelope_fields": sorted(ex["_body"].keys()),
    "note": "the export returns the SAME person object as /v1/people plus one extra top-level "
            "block: `email`. Only the `email` block is inventoried here.",
    "fields": walk(ex["_body"].get("email") or {}, prefix="email.")}

cr = json.load(open(f"{R}/h3_credit_before.json"))
inv["GET /v1/credit"] = {
    "http": cr["_http_status"], "elapsed_s": cr["_elapsed_s"], "credits_billed": 0.0,
    "result": "401, empty body — no readable balance endpoint on this key; credits in this run "
              "are counted from returned-result arithmetic (carried finding, identical to the "
              "Zafran run)."}

fail = json.load(open(f"{R}/h9_email_albert-smith-3aa9318.json"))
inv["POST /v1/people/export/single — the 404"] = {
    "request": fail["_request_body"], "http": fail["_http_status"],
    "elapsed_s": fail["_elapsed_s"], "credits_billed": 0.0,
    "result": "HTTP 404 on the exact LinkedIn URL AI Ark itself returned from /v1/people for the "
              "same person. New wire finding: the export index and the people index disagree.",
    "body": fail["_body"]}

adp = json.load(open("h1_adp.json"))
inv["GET workforcenow.adp.com job-requisitions (FREE, for contrast)"] = {
    "credits_billed": 0.0, "cost_usd": 0.0,
    "centres": adp["summary"]["centres"],
    "reqs_returned": adp["summary"]["total_open_reqs"],
    "req_field_names": adp["summary"]["req_field_names"],
    "no_description_text": adp["summary"]["no_job_description_text"],
    "bonus": f"meta.links LOCATION enumerates "
             f"{adp['summary']['properties_in_location_filter']} named properties — a free "
             f"portfolio roster nobody would think to ask for"}

json.dump(inv, open("h18_ark_field_inventory.json", "w"), indent=2)

lines = ["# AI Ark field inventory — Hotel Equities (every field, with its real value)\n"]
for ep, d in inv.items():
    rows = d.get("fields") or []
    empty = [r for r in rows if "EMPTY" in str(r.get("type")) or r.get("value") == "null"]
    print(f"{ep}: {len(rows)} field rows, {len(empty)} empty/null")
    lines.append(f"\n## `{ep}`\n")
    for k in ("request", "http", "elapsed_s", "credits_billed", "totalElements", "subject",
              "result", "note", "envelope_fields", "centres", "reqs_returned", "bonus",
              "no_description_text"):
        if k in d:
            lines.append(f"- **{k}**: `{json.dumps(d[k], ensure_ascii=False)[:600]}`")
    if rows:
        lines.append(f"\n| field | type | real value for Hotel Equities |\n|---|---|---|")
        for r in rows:
            v = str(r["value"]).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| `{r['field']}` | {r['type']} | {v} |")
        lines.append(f"\n**{len(rows)} field rows, {len(empty)} empty/null.**")
    if d.get("req_field_names"):
        lines.append("\nPer-requisition field names: `"
                     + "`, `".join(d["req_field_names"]) + "`")
open("h18_inventory.md", "w").write("\n".join(lines))
print("\nwrote h18_ark_field_inventory.json + h18_inventory.md")
