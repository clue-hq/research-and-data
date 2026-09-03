"""Z10 — the AI Ark FIELD INVENTORY: every response field name with its real Zafran value.

Walks the saved raw responses. Zero provider calls. birth_date is already scrubbed from raw/;
the walker also hard-skips it as a second guard.
"""
import json, os

SKIP = {"birth_date", "birthDate", "birthday"}
MAXV = 400


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
            rows.append({"field": prefix.rstrip("."), "type": "list", "value": "[] (EMPTY)",
                         "n": 0})
        elif isinstance(obj[0], (dict, list)):
            rows.append({"field": prefix.rstrip("."), "type": f"list[{len(obj)}]",
                         "value": f"{len(obj)} items -> fields below"})
            walk(obj[0], prefix.rstrip(".") + "[0].", rows, depth + 1)
            if len(obj) > 1:
                rows.append({"field": prefix.rstrip(".") + "[*]", "type": "list values",
                             "value": json.dumps(
                                 [x.get("name") or x.get("title") or x.get("type")
                                  or x.get("school", {}).get("name")
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

co = json.load(open("raw/z1a_companies_zafran.json"))
inv["POST /v1/companies"] = {
    "request": co["_request_body"], "http": co["_http_status"],
    "elapsed_s": co["_elapsed_s"], "credits": 0.1,
    "envelope_fields": sorted(co["_body"].keys()),
    "totalElements": co["_body"].get("totalElements"),
    "fields": walk(co["_body"]["content"][0])}

pd = json.load(open("raw/z1b_people_name_vari_kaur.json"))
inv["POST /v1/people (person object)"] = {
    "request": pd["_request_body"], "http": pd["_http_status"], "elapsed_s": pd["_elapsed_s"],
    "credits": 0.5, "subject": "Vari Kaur (representative full person object)",
    "envelope_fields": sorted(pd["_body"].keys()),
    "totalElements": pd["_body"].get("totalElements"),
    "fields": walk(pd["_body"]["content"][0])}

ex = json.load(open("raw/z1c_email_varinderkaur.json"))
inv["POST /v1/people/export/single (email block)"] = {
    "request": ex["_request_body"], "http": ex["_http_status"], "elapsed_s": ex["_elapsed_s"],
    "credits": 1.0, "subject": "Vari Kaur",
    "envelope_fields": sorted(ex["_body"].keys()),
    "note": "the export returns the SAME person object as /v1/people plus one extra top-level "
            "block: `email`. Only the `email` block is inventoried here.",
    "fields": walk(ex["_body"]["email"], prefix="email.")}

cr = json.load(open("raw/z1a_credit_before.json"))
inv["GET /v1/credit"] = {"http": cr["_http_status"], "elapsed_s": cr["_elapsed_s"],
                         "credits": 0.0, "result": "401, empty body — no readable balance "
                                                   "endpoint on this key; credits in this run are "
                                                   "counted from returned-result arithmetic."}

ash = json.load(open("z2b_ashby.json"))["zafran-security"]
inv["GET api.ashbyhq.com/posting-api/job-board/zafran-security (FREE, for contrast)"] = {
    "http": ash["http"], "n_jobs": ash["n_jobs"], "board_top_keys": ash["board_top_keys"],
    "job_field_names": ash["job_field_names"], "credits": 0.0, "cost_usd": 0.0}

json.dump(inv, open("z10_ark_field_inventory.json", "w"), indent=2)
for ep, d in inv.items():
    rows = d.get("fields") or []
    empty = [r for r in rows if "EMPTY" in str(r.get("type")) or r.get("value") in ("null",)]
    print(f"{ep}: {len(rows)} field rows, {len(empty)} empty/null")
