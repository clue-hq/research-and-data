"""B2c — re-parse the 6 saved AI Ark export responses. ZERO new provider calls, zero new credits.

Wire correction worth recording: the address key inside `email.output[]` is **`address`**, not
`email`/`value`. B2b's parser looked for the wrong key and reported found=False for six exports
that all actually returned an address. The raw responses were saved before parsing (the run rule),
so the fix costs nothing. The ledger's credit figures are corrected here too: a found email is
1.0cr (0.5 profile + 0.5 email), not 0.5.
"""

import json
import os
import sys
import time

sys.path.insert(0, ".")
import b_lib as C  # noqa: E402

FILES = [
    ("zafran", "Vari Kaur", "Head of Growth Marketing", "champion",
     "b2b_email_zafran_varinderkaur"),
    ("zafran", "Nick Fisher", "VP Marketing", "economic_buyer",
     "b2b_email_zafran_nicholastfisher"),
    ("cogent", "Alexander Semien", "Head of Growth", "champion",
     "b2b_email_cogent_alexander-semien"),
    ("cogent", "Cameron Coles", "VP of Marketing", "economic_buyer",
     "b2b_email_cogent_cameroncoles"),
    ("harmonic", "Ana Corio", "Director of Demand Generation", "champion",
     "b2b_email_harmonic_anastasiacorio"),
    ("harmonic", "Tyler Chonoles", "Growth and Demand Gen Marketing Manager",
     "technical_evaluator", "b2b_email_harmonic_tyler-chonoles-106405a0"),
]

t0 = time.time()
rows, credits_real = [], 0.0
for acct, name, title, persona, label in FILES:
    d = json.load(open(os.path.join("raw", label + ".json")))
    prof = d.get("profile") or {}
    pos = (d.get("position_groups") or [{}])[0]
    cur_co = ((pos.get("company") or {}).get("name"))
    em = d.get("email") or {}
    out = em.get("output") or []
    first = out[0] if out else {}
    addr = first.get("address")
    st, dt = first.get("status"), first.get("domainType")
    found = bool(addr) and bool(first.get("found"))
    credits = 1.0 if found else (0.5 if d.get("_http_status") == 200 else 0.0)
    credits_real += credits
    verdict = ("verified" if (str(st).upper() == "VALID" and str(dt).upper() == "SMTP")
               else ("catch_all_valid" if str(st).upper() == "VALID" else "not_found"))
    rows.append({
        "account": acct, "name": name, "expected_title": title, "persona": persona,
        "http": d.get("_http_status"),
        "ark_full_name": prof.get("full_name"), "ark_title": prof.get("title"),
        "ark_current_company": cur_co,
        "same_name_check": ("PASS" if cur_co else "NO PROFILE RETURNED"),
        "email": addr, "email_status": st, "domain_type": dt,
        "mx_provider": (first.get("mx") or {}).get("provider"),
        "free": first.get("free"), "generic": first.get("generic"),
        "checked_at": first.get("date"),
        "verdict": verdict if found else "not_found",
        "credits": credits,
    })
    print(f"  {acct}/{name}: {addr or 'NOT FOUND'} | status={st} domainType={dt} "
          f"-> {rows[-1]['verdict']} ({credits}cr) | {prof.get('title')} @ {cur_co}")

json.dump(rows, open("b2b_emails.json", "w"), indent=2)

# correct the ledger rows in place (same call count, corrected credits)
led = json.load(open(C.LEDGER_PATH))
fix = {r["account"] + "|" + r["name"]: r["credits"] for r in rows}
label_to_key = {f[4]: f[0] + "|" + f[1] for f in FILES}
n = 0
for row in led:
    k = label_to_key.get(row.get("label"))
    if k and row.get("provider") == "ai_ark":
        row["credits"] = fix[k]
        row["note"] = (row.get("note", "") + " [corrected in B2c: address key is "
                       "email.output[].address]")
        n += 1
json.dump(led, open(C.LEDGER_PATH, "w"), indent=2)
C.timing_record("B2c_reparse_emails", time.time() - t0, "0 provider calls, ledger corrected")
print(f"\ncorrected {n} ledger rows. emails found: {sum(bool(r['email']) for r in rows)}/6, "
      f"real credits for exports: {credits_real}")
print(f"TOTAL spend={C.total_spend()} credits={C.total_credits()}")
