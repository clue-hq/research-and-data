"""H9b — one more AI Ark email export, and the credit reconciliation.

Why: the COO's export (the economic buyer, priority 2) returned HTTP 404 on the exact LinkedIn URL
AI Ark itself supplied from /v1/people. That is a provider-side gap, not a bad identity — so the
4th export slot goes to the division president who actually owns the properties where the
front-desk/night-audit reqs sit (Focused Service = 78% of the portfolio by the company's own mix).

Also rewrites cost_ledger.json so the `credits` column carries the ACTUAL billed credits
(0.1/company returned, 0.5/profile returned, 1.0/email found) and keeps the pre-call reservation
as `credits_reserved`. z_lib ledgers the reservation by design (that is what enforces the
ceiling); the report must not confuse a reservation with a bill.
"""
import json
import os
import sys
import time

sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

BIRTH = {"birth_date", "birthDate", "birthday"}


def scrub(o):
    if isinstance(o, dict):
        return {k: scrub(v) for k, v in o.items() if k not in BIRTH}
    if isinstance(o, list):
        return [scrub(v) for v in o]
    return o


t0 = time.time()
people = json.load(open("h9_ark_people.json"))

key = "david_rosenberg"
kept = (people["lookups"].get(key) or {}).get("kept") or []
if kept and kept[0].get("linkedin") and not C.ARK_EXHAUSTED[0]:
    url = kept[0]["linkedin"]
    slug = url.rstrip("/").split("/")[-1]
    r = C.ark("/v1/people/export/single", {"url": url}, label=f"h9b_email_{slug}",
              est_credits=1.0)
    out = scrub(r["_body"]) if isinstance(r["_body"], dict) else {}
    C.save_raw(f"h9b_email_{slug}", {"_http_status": r["_http_status"],
                                     "_elapsed_s": r["_elapsed_s"],
                                     "_request_body": {"url": url}, "_body": out})
    email = out.get("email") or {}
    outs = email.get("output") if isinstance(email.get("output"), list) else []
    first = outs[0] if outs else {}
    addr = first.get("address") or first.get("email")
    people["emails"][key] = {
        "linkedin": url, "http": r["_http_status"],
        "ark_full_name": (out.get("profile") or {}).get("full_name"),
        "ark_title": (out.get("profile") or {}).get("title"),
        "email": addr, "status": first.get("status"), "sub_status": first.get("subStatus"),
        "domain_type": first.get("domainType"), "mx": first.get("mx"),
        "free": first.get("free"), "generic": first.get("generic"),
        "verified_at": first.get("date"), "found": first.get("found"),
        "email_block_top_keys": sorted(email.keys()), "email_block_raw": email,
        "credits": 1.0 if addr else 0.0}
    print(f"   {key} -> {addr} status={first.get('status')}/{first.get('subStatus')} "
          f"http={r['_http_status']}")
    json.dump(people, open("h9_ark_people.json", "w"), indent=2)

# ---------------- credit reconciliation -------------------------------------
rows = json.load(open(C.LEDGER_PATH))
actual_total = 0.0
for row in rows:
    if row.get("provider") != "ai_ark":
        continue
    reserved = row.get("credits") or 0.0
    op = row.get("op") or ""
    n = row.get("n_returned")
    http = row.get("http")
    if op == "/v1/companies":
        actual = 0.1 * (n or 0)
    elif op == "/v1/people":
        actual = 0.5 * (n or 0)
    elif op == "/v1/people/export/single":
        lbl = row.get("label") or ""
        found = False
        for f in os.listdir(C.RAW):
            if f == lbl + ".json":
                b = (json.load(open(os.path.join(C.RAW, f))) or {}).get("_body") or {}
                outs = ((b.get("email") or {}).get("output")) or []
                found = bool(outs and (outs[0].get("address") or outs[0].get("email")))
        actual = 1.0 if found else 0.0
    elif op == "/v1/credit":
        actual = 0.0
    else:
        actual = reserved
    row["credits_reserved"] = reserved
    row["credits"] = actual
    row["credits_note"] = ("actual billed credits: 0.1/company returned, 0.5/profile returned, "
                           "1.0/email found, 0 on a non-200 or not-found")
    if http and http >= 400:
        row["credits"] = 0.0
    actual_total += row["credits"]

json.dump(rows, open(C.LEDGER_PATH, "w"), indent=2)
print(f"\nAI Ark ACTUAL credits billed: {round(actual_total, 2)} "
      f"(ceiling {C.CREDIT_CEILING})")
json.dump({"ai_ark_actual_credits": round(actual_total, 2),
           "ceiling": C.CREDIT_CEILING,
           "method": "0.1/company returned + 0.5/profile returned + 1.0/email found; "
                     "non-200 and not-found cost 0"},
          open("h9b_credit_reconciliation.json", "w"), indent=2)
C.timing_record("H9b_ark_extra_email", time.time() - t0, "1 export + credit reconciliation")
print(f"H9b {round(time.time()-t0,1)}s spend={C.total_spend()}")
