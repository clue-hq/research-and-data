"""B2b — AI Ark email export, <=2 contacts per top-3 account, 6 total. NO phone calls.

Billing: 0.5cr profile + 0.5cr email, the email half charged only if an address is found.
Record BOTH `status` and `domainType` — "verified" only when SMTP + VALID; a CATCH_ALL domain is
`catch_all_valid`, never flattened to a bare address.
"""

import json
import sys
import time

sys.path.insert(0, ".")
import b_lib as C  # noqa: E402

TARGETS = [
    ("zafran", "Vari Kaur", "Head of Growth Marketing", "champion",
     "https://www.linkedin.com/in/varinderkaur"),
    ("zafran", "Nick Fisher", "VP Marketing", "economic_buyer",
     "https://www.linkedin.com/in/nicholastfisher"),
    ("cogent", "Alexander Semien", "Head of Growth", "champion",
     "https://www.linkedin.com/in/alexander-semien"),
    ("cogent", "Cameron Coles", "VP of Marketing", "economic_buyer",
     "https://www.linkedin.com/in/cameroncoles"),
    ("harmonic", "Ana Corio", "Director of Demand Generation", "champion",
     "https://www.linkedin.com/in/anastasiacorio"),
    ("harmonic", "Tyler Chonoles", "Growth and Demand Gen Marketing Manager", "technical_evaluator",
     "https://www.linkedin.com/in/tyler-chonoles-106405a0"),
]

t_all = time.time()
rows = []
for acct, name, title, persona, url in TARGETS:
    t0 = time.time()
    slug = url.rstrip("/").split("/")[-1]
    out, status, el = C.ark("/v1/people/export/single", {"url": url},
                            label=f"b2b_email_{acct}_{slug}", est_credits=1.0)
    email = out.get("email") or {}
    # the canary observed {"state": "DONE", "output": [...]} on the email block
    outputs = email.get("output") if isinstance(email.get("output"), list) else []
    first = outputs[0] if outputs else {}
    addr = first.get("email") or email.get("email") or first.get("value")
    est = first.get("status") or email.get("status")
    dtype = first.get("domainType") or email.get("domainType")
    found = bool(addr)
    credits = 1.0 if found else 0.5
    pos = (out.get("position_groups") or [{}])[0]
    cur_co = ((pos.get("company") or {}).get("name"))
    verdict = ("verified" if (str(est).upper() == "VALID" and str(dtype).upper() == "SMTP")
               else ("catch_all_valid" if str(est).upper() == "VALID" else "unverified"))
    C.ark_ledger(f"b2b_email_{acct}_{slug}", "POST /v1/people/export/single", status, el, credits,
                 f"found={found} status={est} domainType={dtype}")
    row = {
        "account": acct, "name": name, "expected_title": title, "persona": persona,
        "linkedin": url, "http": status,
        "ark_full_name": (out.get("profile") or {}).get("full_name"),
        "ark_title": (out.get("profile") or {}).get("title"),
        "ark_current_company": cur_co,
        "same_name_ok": bool(cur_co),
        "email": addr, "email_status": est, "domain_type": dtype, "verdict": verdict,
        "credits": credits, "elapsed_s": el,
        "email_block_keys": list(email.keys())[:12],
    }
    rows.append(row)
    print(f"  {acct}/{name}: email={addr} status={est} domainType={dtype} -> {verdict} "
          f"({credits}cr) | ark_title={row['ark_title']} @ {cur_co}")
    C.timing_record(f"B2b_email_{acct}_{name.replace(' ','_')}", time.time() - t0, verdict)

json.dump(rows, open("b2b_emails.json", "w"), indent=2)
C.timing_record("B2b_emails_TOTAL", time.time() - t_all, f"{len(TARGETS)} exports")
print(f"\nPHASE B2b {round(time.time()-t_all,1)}s spend={C.total_spend()} "
      f"credits={C.total_credits()}")
