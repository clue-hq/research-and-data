"""B4c — extend the tier-1 AI Ark lane to the accounts 4-5 committees. ZERO new provider calls.

B4's CONTACT_ENTITY map only covered the six top-3 people who got email exports, so Vendelux and
Uptiq ended with 0 tier-1 claims even though their rosters were already bought and paid for. This
rebuilds lane A over every roster person whose CURRENT company matches the account (same-name
discipline), re-merges against the cached lane-C responses in raw/, and rewrites claims_*.json.
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, ".")
import b_lib as C  # noqa: E402
from field_catalog import ACCOUNT_FIELDS, CONTACT_FIELDS, FACET_FIELDS  # noqa: E402

_ns = {"__name__": "_b4_defs", "json": json, "sys": sys, "time": time, "C": C,
       "ACCOUNT_FIELDS": ACCOUNT_FIELDS, "CONTACT_FIELDS": CONTACT_FIELDS,
       "FACET_FIELDS": FACET_FIELDS, "catalog_text": lambda: ""}
_head = open("b4_structure.py").read().split("# ---------------------------------"
                                             "--------------------------------- load the")[0]
exec(compile(_head, "b4_structure.py<definitions-only>", "exec"), _ns)  # noqa: S102
ACCTS, WS, stamp, _prio = _ns["ACCTS"], _ns["WS"], _ns["stamp"], _ns["_prio"]

t0 = time.time()
rosters = json.load(open("b1c_ark_rosters.json"))
emails = json.load(open("b2b_emails.json"))
boards = json.load(open("b0_boards.json"))
base = json.load(open("b4_structure_raw.json"))
site_text = json.load(open("b1a_site_text.json"))
job_text = json.load(open("b1a_job_text.json"))
gapfill = json.load(open("b1d_gapfill.json"))
negatives = json.load(open("b3_negatives.json"))

# entity id for every roster person, derived not hand-listed
ACCT_TOKEN = {"zafran": "zafran", "cogent": "cogent", "harmonic": "harmonic",
              "vendelux": "vendelux", "uptiq": "uptiq"}
DEEP_CONTACT = {"zafran": "contact:vari-kaur", "cogent": "contact:alexander-semien",
                "harmonic": "contact:ana-corio"}
DEEP_NAME = {"zafran": "Vari Kaur", "cogent": "Alexander Semien", "harmonic": "Ana Corio"}


def eid(name):
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return "contact:" + s


lane_a, committee = [], {}
for key, (name, domain, ent) in ACCTS.items():
    people = (rosters.get(key) or {}).get("people", [])
    kept, rejected = [], []
    for p in people:
        co = (p.get("current_company") or "")
        # SAME-NAME DISCIPLINE: current employer must be this account, not a look-alike.
        ok = ACCT_TOKEN[key] in co.lower() and "sigma" not in co.lower()
        (kept if ok else rejected).append({"name": p["full_name"], "title": p["title"],
                                           "current_company": co,
                                           "linkedin": p["linkedin"], "start": p.get("start")})
        if not ok:
            continue
        cent = eid(p["full_name"])
        li = p["linkedin"]
        lane_a.append(stamp({"field_key": "contact.current_title", "value_json": p["title"],
                             "evidence_span": f'profile.title = "{p["title"]}" with '
                                              f'position_groups[0].company.name = "{co}"'},
                            source_key="ai_ark", tier=1, method="api", source_url=li,
                            entity=cent, priority_default=2))
        if p.get("start"):
            lane_a.append(stamp(
                {"field_key": "contact.facet.career_history",
                 "value_json": [{"org": co, "role": p["title"], "start": str(p["start"]),
                                 "end": "present"}],
                 "evidence_span": f'position_groups[0] = {{company: "{co}", title: '
                                  f'"{p["title"]}", date.start: "{p["start"]}"}}'},
                source_key="ai_ark", tier=1, method="api", source_url=li,
                entity=cent, priority_default=3))
    committee[key] = {"admitted": kept, "rejected_same_name": rejected,
                      "roster_returned": len(people),
                      "roster_total_available": (rosters.get(key) or {}).get("totalElements")}

for e in emails:
    if not e.get("email"):
        continue
    lane_a.append(stamp(
        {"field_key": "core.work_email",
         "value_json": {"address": e["email"], "status": e["email_status"],
                        "domain_type": e["domain_type"], "verdict": e["verdict"],
                        "checked_at": e["checked_at"]},
         "evidence_span": f'email.output[0] = {{address: "{e["email"]}", status: '
                          f'"{e["email_status"]}", domainType: "{e["domain_type"]}", '
                          f'mx.provider: "{e.get("mx_provider")}", found: true}}'},
        source_key="ai_ark", tier=1, method="api", source_url=e["linkedin"]
        if "linkedin" in e else None, entity=eid(e["name"]), priority_default=2))

json.dump(committee, open("b4c_committees.json", "w"), indent=2)


def corpus_for(key):
    parts = [open(f"report_account_{key}.md").read(), site_text.get(key, ""), job_text.get(key, "")]
    if os.path.exists(f"report_contact_{key}.md"):
        parts.append(open(f"report_contact_{key}.md").read())
    for blk in (gapfill, negatives):
        for v in blk.values():
            for r in (v or {}).get("results", []):
                parts.append(r.get("text") or "")
    return "\n".join(parts)


def cached_contact_claims(key):
    path = f"raw/b4b_structure_contact_{key}.json"
    if not os.path.exists(path):
        return [], []
    resp = json.load(open(path))
    txt = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    if txt.strip().startswith("```"):
        txt = txt.split("```", 2)[1].split("\n", 1)[1]
    try:
        p = json.loads(txt)
    except Exception:  # noqa: BLE001
        return [], []
    return (p.get("contact_claims") or []), (p.get("proposed_fields") or [])


defects = {"unregistered_field": [], "missing_source_url": [], "unquoted_evidence": [],
           "missing_priority": 0, "string_confidence": 0, "dropped": 0}
per_account = {}

for key, (name, domain, ent) in ACCTS.items():
    corpus = corpus_for(key)
    own = {eid(p["name"]) for p in committee[key]["admitted"]}
    own |= {eid(e["name"]) for e in emails if e["account"] == key}
    if key in DEEP_CONTACT:
        own.add(DEEP_CONTACT[key])
    claims = [c for c in lane_a + base["lane_b"] if c["entity"] == ent or c["entity"] in own]

    rows = list(base["lane_c_raw"][key]["parsed"].get("account_claims") or [])
    proposed = list(base["lane_c_raw"][key]["parsed"].get("proposed_fields") or [])
    if key == "zafran":
        proposed = base["proposed_from_b"][:1] + proposed
    cc, cp = cached_contact_claims(key)
    rows += [dict(r, _entity=DEEP_CONTACT[key]) for r in cc]
    proposed += cp

    for row in rows:
        fk = row.get("field_key")
        target = row.get("_entity") or ent
        if fk not in ACCOUNT_FIELDS and fk not in CONTACT_FIELDS and fk not in FACET_FIELDS:
            defects["unregistered_field"].append(f"{key}:{fk}")
            defects["dropped"] += 1
            continue
        if not row.get("source_url"):
            defects["missing_source_url"].append(f"{key}:{fk}")
            defects["dropped"] += 1
            continue
        if isinstance(row.get("confidence"), str):
            defects["string_confidence"] += 1
        if _prio(row.get("priority"), None) is None:
            defects["missing_priority"] += 1
        span = (row.get("evidence_span") or "").strip()
        if span and span[:70] not in corpus:
            defects["unquoted_evidence"].append(f"{key}:{fk}")
        claims.append(stamp(row, source_key="exa_research", tier=4, method="llm_synthesis",
                            source_url=row.get("source_url"), entity=target, priority_default=3))

    seen, dedup = set(), []
    for p in proposed:
        k = p.get("field_key")
        if k and k not in seen:
            seen.add(k)
            dedup.append(p)

    counts = {
        "total": len(claims),
        "by_tier": {str(t): sum(1 for c in claims if c["source_tier"] == t) for t in (1, 2, 4)},
        "by_priority": {str(p): sum(1 for c in claims if c["priority"] == p) for p in (1, 2, 3)},
        "account_entity": sum(1 for c in claims if c["entity"] == ent),
        "contact_entity": sum(1 for c in claims if c["entity"] != ent),
        "distinct_contacts": len({c["entity"] for c in claims if c["entity"] != ent}),
    }
    json.dump({"account": name, "domain": domain, "entity": ent, "workspace_id": WS,
               "run": "arv2-smoke-cluehq", "research_date": "2026-08-31",
               "claim_counts": counts,
               "committee_same_name_audit": committee[key],
               "claims": claims, "proposed_fields": dedup},
              open(f"claims_{key}.json", "w"), indent=2)
    per_account[key] = counts
    print(f"  claims_{key}.json: {counts['total']} claims "
          f"(t1={counts['by_tier']['1']} t2={counts['by_tier']['2']} t4={counts['by_tier']['4']}) "
          f"P1={counts['by_priority']['1']}/P2={counts['by_priority']['2']}/"
          f"P3={counts['by_priority']['3']} | {counts['distinct_contacts']} contacts | "
          f"{len(dedup)} proposed")

summary = {"per_account": per_account, "defects": defects,
           "model": "openai/gpt-5-mini", "reasoning": {"effort": "minimal"},
           "total_claims": sum(v["total"] for v in per_account.values()),
           "total_contacts": sum(v["distinct_contacts"] for v in per_account.values())}
json.dump(summary, open("claims_summary.json", "w"), indent=2)
C.timing_record("B4c_patch_committees", time.time() - t0, "0 provider calls")
print("\nDEFECTS:", json.dumps(defects))
print(f"TOTAL CLAIMS {summary['total_claims']} across {summary['total_contacts']} contacts")
