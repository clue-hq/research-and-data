"""H9 — AI Ark ENRICHMENT of the already-web-confirmed committee (v3 protocol step 2).

Every person here was confirmed FIRST from a non-AI-Ark URL (hotelequities.com/meet-our-team.htm,
the company's dated appointment posts, Hospitality Net appointment notices, the company's own
LinkedIn post naming its VP of Information Technology). AI Ark is used only to (a) re-confirm the
current employer, (b) supply the LinkedIn locator, career history and reach, and (c) export a
verified work email. An AI-Ark-only person is NEVER admitted. Any employer mismatch is dropped and
recorded.

Wire facts: the title filter is broken, so lookups are name-scoped + domain-scoped (0.5 cr per
profile returned). /v1/people/export/single is 1 cr when an address is found. Calls are paced
>=10.5s by z_lib and halt on 402/exhaustion. profile.birth_date is NEVER written.
"""
import json
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


# (key, name variants, web-confirmed title, persona, the NON-AI-Ark url that confirms them)
COMMITTEE = [
    ("ben_rafter", ["Ben Rafter", "Benjamin Rafter"], "Chief Executive Officer",
     "executive_sponsor", "https://www.hotelequities.com/meet-our-team.htm"),
    ("al_smith", ["Albert Smith", "Al Smith"], "Chief Operating Officer",
     "economic_buyer", "https://www.hospitalitynet.org/appointment/79030411.html"),
    ("brian_jenkins", ["Brian Jenkins"], "Head of HE Labs | EVP of Strategy",
     "champion", "https://www.hospitalitynet.org/appointment/79032251/brian-jenkins"),
    ("stephen_hahn", ["Stephen Hahn", "Steve Hahn"], "VP of Information Technology",
     "technical_evaluator", "https://www.hotelequities.com/meet-our-team.htm"),
    ("david_rosenberg", ["David Rosenberg"], "President, Focused Service",
     "divisional_operator", "https://www.hotelequities.com/blog/hotel-equities-strengthens-leadership-team-with-key-executive-appointments-across-new-divisions/"),
    ("bill_stachler", ["Bill Stachler", "William Stachler"], "SVP of Revenue Optimization",
     "adjacent_revenue", "https://www.hotelequities.com/meet-our-team.htm"),
]

# priority order for the <=4 paid email exports: sponsor -> buyer -> champion -> evaluator
EMAIL_PRIORITY = ["ben_rafter", "al_smith", "brian_jenkins", "stephen_hahn"]
MAX_EMAILS = 4


def row(p):
    pr = p.get("profile") or {}
    pos = p.get("position_groups") or []
    cur = pos[0] if pos else {}
    comp = cur.get("company") or {}
    st = p.get("statistics") or {}
    return {
        "full_name": pr.get("full_name"), "title": pr.get("title"),
        "headline": pr.get("headline"),
        "linkedin": (p.get("link") or {}).get("linkedin"),
        "location_short": (p.get("location") or {}).get("short"),
        "current_company": comp.get("name"),
        "current_company_url": comp.get("url"),
        "since": (cur.get("date") or {}).get("start"),
        "ark_id": p.get("id"),
        "department": p.get("department"),
        "followers": ((st.get("network") or {}).get("followers_count")),
        "connections": ((st.get("network") or {}).get("connections_count")),
        "badges": p.get("member_badges"),
        "educations": [{"school": (e.get("school") or {}).get("name"),
                        "degree": e.get("degree_name"), "field": e.get("field_of_study"),
                        "date": e.get("date")} for e in (p.get("educations") or [])],
        "career": [{"company": (g.get("company") or {}).get("name"),
                    "titles": [t.get("title") for t in (g.get("profile_positions") or [])],
                    "date": g.get("date")} for g in pos],
        "skills": (p.get("skills") or [])[:25],
        "awards": [{"title": a.get("title"), "date": a.get("date")} for a in (p.get("awards") or [])],
        "certifications": [{"name": c.get("name"), "authority": c.get("authority"),
                            "date": c.get("date")} for c in (p.get("certifications") or [])],
        "last_updated": p.get("last_updated"),
        "top_keys": sorted(p.keys()),
    }


t_all = time.time()
result = {"lookups": {}, "emails": {}, "excluded": []}

print("== A. name-scoped + domain-scoped people lookups (0.5 cr per profile returned) ==")
for key, variants, web_title, persona, confirm_url in COMMITTEE:
    if C.ARK_EXHAUSTED[0]:
        print("   AI Ark halted — skipping the rest")
        break
    body = {"contact": {"fullName": {"any": {"include": {"mode": "STRICT", "content": variants}}}},
            "account": {"domain": {"any": {"include": ["hotelequities.com"]}}},
            "page": 0, "size": 3}
    r = C.ark("/v1/people", body, label=f"h9_people_{key}", est_credits=1.5)
    out = scrub(r["_body"]) if isinstance(r["_body"], dict) else {}
    C.save_raw(f"h9_people_{key}", {"_http_status": r["_http_status"],
                                    "_elapsed_s": r["_elapsed_s"],
                                    "_request_body": body, "_body": out})
    ps = out.get("content") or []
    rows = [row(p) for p in ps]
    # employer guard: AI Ark must agree the person is at Hotel Equities
    kept, dropped = [], []
    for rr in rows:
        cc = (rr.get("current_company") or "").lower()
        if "hotel equities" in cc or "springboard" in cc:
            kept.append(rr)
        else:
            dropped.append(rr)
            result["excluded"].append({"looked_for": variants, "ark_name": rr["full_name"],
                                       "ark_title": rr["title"],
                                       "ark_current_company": rr["current_company"],
                                       "reason": "employer mismatch — not admitted"})
    result["lookups"][key] = {
        "variants": variants, "web_confirmed_title": web_title, "persona": persona,
        "identity_confirmation_url": confirm_url, "http": r["_http_status"],
        "totalElements": out.get("totalElements"), "returned": len(ps),
        "credits": 0.5 * len(ps), "kept": kept, "dropped": dropped}
    for rr in kept:
        print(f"   [KEEP] {rr['full_name']:22s} | {str(rr['title'])[:38]:38s} | "
              f"{rr['current_company']} | since={rr['since']} | {rr['linkedin']}")
    for rr in dropped:
        print(f"   [DROP] {rr['full_name']:22s} | {str(rr['title'])[:38]:38s} | "
              f"{rr['current_company']}  <- employer mismatch")
    if not ps:
        print(f"   [MISS] {variants} -> 0 results (AI Ark has no profile at this domain)")

print("\n== B. email export, priority order, <=4 (1 cr when found) ==")
sent = 0
for key in EMAIL_PRIORITY:
    if sent >= MAX_EMAILS or C.ARK_EXHAUSTED[0]:
        break
    kept = (result["lookups"].get(key) or {}).get("kept") or []
    if not kept:
        print(f"   skip {key}: no AI Ark profile / no LinkedIn locator")
        continue
    url = kept[0].get("linkedin")
    if not url:
        print(f"   skip {key}: profile has no linkedin url")
        continue
    slug = url.rstrip("/").split("/")[-1]
    r = C.ark("/v1/people/export/single", {"url": url}, label=f"h9_email_{slug}", est_credits=1.0)
    sent += 1
    out = scrub(r["_body"]) if isinstance(r["_body"], dict) else {}
    C.save_raw(f"h9_email_{slug}", {"_http_status": r["_http_status"],
                                    "_elapsed_s": r["_elapsed_s"],
                                    "_request_body": {"url": url}, "_body": out})
    email = out.get("email") or {}
    outputs = email.get("output") if isinstance(email.get("output"), list) else []
    first = outputs[0] if outputs else {}
    addr = first.get("address") or first.get("email") or first.get("value")
    result["emails"][key] = {
        "linkedin": url, "http": r["_http_status"],
        "ark_full_name": (out.get("profile") or {}).get("full_name"),
        "ark_title": (out.get("profile") or {}).get("title"),
        "ark_current_company": (((out.get("position_groups") or [{}])[0].get("company") or {})
                                .get("name")),
        "email": addr, "status": first.get("status"), "sub_status": first.get("subStatus"),
        "domain_type": first.get("domainType"), "mx": first.get("mx"),
        "free": first.get("free"), "generic": first.get("generic"),
        "verified_at": first.get("date"), "found": first.get("found"),
        "email_block_top_keys": sorted(email.keys()),
        "email_block_raw": email,
        "credits": 1.0 if addr else 0.5}
    print(f"   {key:16s} -> {addr}  status={first.get('status')}/{first.get('subStatus')} "
          f"mx={(first.get('mx') or {}).get('provider')} verified={first.get('date')}")

json.dump(result, open("h9_ark_people.json", "w"), indent=2)
C.timing_record("H9_ark_people", time.time() - t_all,
                f"{len(COMMITTEE)} name-scoped + {sent} email exports")
print(f"\nH9 {round(time.time()-t_all,1)}s credits={C.total_credits()} spend={C.total_spend()} "
      f"ark_halted={C.ARK_EXHAUSTED[0]}")
