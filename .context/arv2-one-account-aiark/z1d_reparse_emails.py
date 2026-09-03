"""Z1d — re-parse the 4 saved AI Ark export responses. ZERO new calls, zero new credits.

Wire fact (carried from the smoke test): the address key inside `email.output[]` is `address`,
not `email`/`value`. Z1c's parser looked for the wrong key. Raw was saved before parsing, so the
fix is free.
"""
import json, os, sys, time
sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

FILES = [("Vari Kaur", "champion", "z1c_email_varinderkaur"),
         ("Nick Fisher", "economic_buyer", "z1c_email_nicholastfisher"),
         ("Sanaz Yashar", "executive_sponsor", "z1c_email_sanaz-yashar"),
         ("Tom Anthony", "adjacent_buyer", "z1c_email_tomanthonyjr")]

rows, credits_real = [], 0.0
for name, persona, label in FILES:
    d = json.load(open(os.path.join("raw", label + ".json")))["_body"]
    prof = d.get("profile") or {}
    pos = (d.get("position_groups") or [{}])[0]
    cur_co = ((pos.get("company") or {}).get("name"))
    em = d.get("email") or {}
    first = (em.get("output") or [{}])[0]
    addr = first.get("address")
    st, dt = first.get("status"), first.get("domainType")
    found = bool(addr) and bool(first.get("found"))
    credits = 1.0 if found else 0.5
    credits_real += credits
    verdict = ("verified_smtp" if (str(st).upper() == "VALID" and str(dt).upper() == "SMTP")
               else ("catch_all_valid" if str(st).upper() == "VALID" else "not_found"))
    rows.append({
        "name": name, "persona": persona, "ark_full_name": prof.get("full_name"),
        "ark_title": prof.get("title"), "ark_current_company": cur_co,
        "same_name_check": "PASS" if cur_co == "Zafran Security" else f"CHECK ({cur_co})",
        "email": addr, "email_state": em.get("state"), "email_status": st, "domain_type": dt,
        "sub_status": first.get("subStatus"),
        "mx_record": (first.get("mx") or {}).get("record"),
        "mx_provider": (first.get("mx") or {}).get("provider"),
        "mx_found": (first.get("mx") or {}).get("found"),
        "mx_google": (first.get("mx") or {}).get("google"),
        "free": first.get("free"), "generic": first.get("generic"),
        "found": first.get("found"), "checked_at": first.get("date"),
        "verdict": verdict, "credits": credits,
        "email_output_field_names": sorted(first.keys()),
    })
    print(f"  {name}: {addr} | {st}/{dt}/{first.get('subStatus')} | mx={(first.get('mx') or {}).get('provider')} "
          f"| free={first.get('free')} generic={first.get('generic')} -> {verdict} ({credits}cr)")

# correct the ledger credits
led = json.load(open("cost_ledger.json"))
by_label = {r["name"].lower().replace(" ", ""): r for r in rows}
for r in led:
    if r.get("provider") == "ai_ark" and r.get("label", "").startswith("z1c_email_"):
        slug = r["label"].replace("z1c_email_", "")
        m = {"varinderkaur": "Vari Kaur", "nicholastfisher": "Nick Fisher",
             "sanaz-yashar": "Sanaz Yashar", "tomanthonyjr": "Tom Anthony"}[slug]
        row = [x for x in rows if x["name"] == m][0]
        r["credits_estimated_prebooked"] = r["credits"]; r["credits"] = row["credits"]
        r["note"] = f"actual: found={row['found']} -> {row['credits']}cr"
json.dump(led, open("cost_ledger.json", "w"), indent=2)
json.dump(rows, open("z1d_emails_parsed.json", "w"), indent=2)
ark_cr = round(sum(float(r.get("credits") or 0) for r in led if r.get("provider") == "ai_ark"), 2)
print(f"\nZ1d re-parse: {credits_real}cr on emails; AI Ark run total = {ark_cr}cr")
