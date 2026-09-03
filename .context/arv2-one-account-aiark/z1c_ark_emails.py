"""Z1c — AI Ark email export (/v1/people/export/single), <=4 committee members.

1cr when an address is found. Records the FULL email block shape for the field inventory.
birth_date is scrubbed before anything is written.
"""
import json, sys, time
sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

BIRTH = {"birth_date", "birthDate", "birthday"}
def scrub(o):
    if isinstance(o, dict): return {k: scrub(v) for k, v in o.items() if k not in BIRTH}
    if isinstance(o, list): return [scrub(v) for v in o]
    return o

TARGETS = [
    ("Vari Kaur", "Head of Growth Marketing", "champion", "https://www.linkedin.com/in/varinderkaur"),
    ("Nick Fisher", "VP of Marketing", "economic_buyer", "https://www.linkedin.com/in/nicholastfisher"),
    ("Sanaz Yashar", "Co-Founder & CEO", "executive_sponsor", "https://www.linkedin.com/in/sanaz-yashar"),
    ("Tom Anthony", "SVP, Global Sales", "adjacent_buyer", "https://www.linkedin.com/in/tomanthonyjr"),
]

t_all = time.time(); rows = []
for name, title, persona, url in TARGETS:
    slug = url.rstrip("/").split("/")[-1]
    r = C.ark("/v1/people/export/single", {"url": url}, label=f"z1c_email_{slug}", est_credits=1.0)
    out = scrub(r["_body"]) if isinstance(r["_body"], dict) else {}
    # re-write the scrubbed raw
    C.save_raw(f"z1c_email_{slug}", {"_http_status": r["_http_status"], "_elapsed_s": r["_elapsed_s"],
                                     "_request_body": {"url": url}, "_body": out})
    email = out.get("email") or {}
    outputs = email.get("output") if isinstance(email.get("output"), list) else []
    first = outputs[0] if outputs else {}
    addr = first.get("email") or email.get("email") or first.get("value")
    rows.append({
        "name": name, "persona": persona, "linkedin": url, "http": r["_http_status"],
        "ark_full_name": (out.get("profile") or {}).get("full_name"),
        "ark_title": (out.get("profile") or {}).get("title"),
        "email_block_top_keys": sorted(email.keys()),
        "email_block_raw": email,
        "email": addr,
        "credits": 1.0 if addr else 0.5,
        "export_top_keys": sorted(out.keys()),
    })
    print(f"   {name}: {addr} | block keys={sorted(email.keys())}")

json.dump(rows, open("z1c_emails.json", "w"), indent=2)
C.timing_record("Z1c_ark_emails", time.time() - t_all, f"{len(TARGETS)} exports")
print(f"\nZ1c {round(time.time()-t_all,1)}s credits={C.total_credits()} spend={C.total_spend()}")
