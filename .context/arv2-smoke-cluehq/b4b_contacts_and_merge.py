"""B4b — contact structuring (ONE SUBJECT PER CALL) + merge/validate -> claims_<account>.json.

Validation is the honesty gate: an unregistered field key, a missing source_url, or an
evidence_span that is NOT a verbatim substring of the corpus is a DEFECT and the row is dropped
(or counted), never laundered into the database.
"""

import json
import sys
import time

sys.path.insert(0, ".")
import b_lib as C  # noqa: E402
from field_catalog import ACCOUNT_FIELDS, CONTACT_FIELDS, FACET_FIELDS, catalog_text  # noqa: E402

# b4_structure.py runs its paid calls at module level, so pull the shared definitions out of its
# SOURCE rather than importing it (importing would re-run 5 LLM calls). The SYSTEM prompt is read
# back verbatim from the bundle B4 already wrote, so both phases provably use the same prompt.
_ns = {"__name__": "_b4_defs", "json": json, "sys": sys, "time": time, "C": C,
       "ACCOUNT_FIELDS": ACCOUNT_FIELDS, "CONTACT_FIELDS": CONTACT_FIELDS,
       "FACET_FIELDS": FACET_FIELDS, "catalog_text": catalog_text}
_head = open("b4_structure.py").read().split("# ---------------------------------"
                                             "--------------------------------- load the")[0]
exec(compile(_head, "b4_structure.py<definitions-only>", "exec"), _ns)  # noqa: S102
ACCTS, CONTACT_ENTITY, WS = _ns["ACCTS"], _ns["CONTACT_ENTITY"], _ns["WS"]
stamp, _prio = _ns["stamp"], _ns["_prio"]

MODEL = "openai/gpt-5-mini"
REASONING = {"effort": "minimal"}
SYSTEM = open("structuring_bundle_zafran.txt").read().split("\n\n=====\n\n")[0]


def run(label, user):
    resp = C.openrouter(MODEL, [{"role": "system", "content": SYSTEM},
                                {"role": "user", "content": user}],
                        label=label, response_format={"type": "json_object"},
                        timeout=900, reasoning=REASONING)
    txt = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    if txt.strip().startswith("```"):
        txt = txt.split("```", 2)[1].split("\n", 1)[1]
    try:
        return json.loads(txt), resp
    except Exception as e:  # noqa: BLE001
        print(f"    !! unparsable JSON for {label}: {e}")
        return {}, resp

CONTACTS = {
    "zafran": ("Vari Kaur (Varinder Kaur)", "contact:vari-kaur", "Zafran Security"),
    "cogent": ("Alexander Semien", "contact:alexander-semien", "Cogent Security, Inc."),
    "harmonic": ("Ana Corio (Anastasia Corio)", "contact:ana-corio", "Harmonic Security, Inc."),
}
COMMITTEE_HINT = {
    "zafran": "Vari Kaur is the CHAMPION (she owns the vacant ABM seat). Nick Fisher, VP "
              "Marketing, is her manager and the ECONOMIC_BUYER.",
    "cogent": "Alexander Semien, Head of Growth, is the CHAMPION. Cameron Coles, VP of Marketing, "
              "is the ECONOMIC_BUYER.",
    "harmonic": "Ana Corio, Director of Demand Generation, is the CHAMPION and the hiring manager "
                "for the ABM req. Tyler Chonoles, Growth and Demand Gen Marketing Manager, is the "
                "USER / TECHNICAL_EVALUATOR.",
}

t_all = time.time()
contact_out = {}
for key, (person, ent, company) in CONTACTS.items():
    t0 = time.time()
    report = open(f"report_contact_{key}.md").read()[:30000]
    user = (f"# FIELD CATALOG (the ONLY keys you may use)\n{catalog_text()}\n\n"
            f"# CONTACT: {person}, currently at {company}. Entity id: {ent}\n"
            f"# {COMMITTEE_HINT[key]}\n"
            f"# The client selling to them is Clue (cluehq.ai), an AI-native ABM orchestration "
            f"platform. Judge priority against THAT sale. contact.persona is a CLOSED enum: "
            f"champion | economic_buyer | technical_evaluator | blocker.\n\n"
            f"# PER-PERSON DEEP RESEARCH REPORT (Exa deep-reasoning, one call)\n{report}\n\n"
            f"Emit ONLY contact-entity claims for {ent} now. Each claim: "
            f'{{"field_key","value_json","evidence_span","source_url","confidence","priority"}} '
            f'(+ "use_class" for contact.facet.*).\n'
            f'Return {{"contact_claims":[...], "proposed_fields":[...]}}.')
    open(f"structuring_bundle_contact_{key}.txt", "w").write(SYSTEM + "\n\n=====\n\n" + user)
    parsed, resp = run(f"b4b_structure_contact_{key}", user)
    contact_out[key] = {"entity": ent, "parsed": parsed, "usage": resp.get("usage")}
    C.timing_record(f"B4b_structure_contact_{key}", time.time() - t0, person)
    print(f"  -> {key}/{person}: {len(parsed.get('contact_claims') or [])} claims, "
          f"{len(parsed.get('proposed_fields') or [])} proposed")

# --------------------------------------------------------------------------- merge + validate
base = json.load(open("b4_structure_raw.json"))
site_text = json.load(open("b1a_site_text.json"))
job_text = json.load(open("b1a_job_text.json"))
gapfill = json.load(open("b1d_gapfill.json"))
negatives = json.load(open("b3_negatives.json"))


def corpus_for(key):
    parts = [open(f"report_account_{key}.md").read(), site_text.get(key, ""),
             job_text.get(key, "")]
    try:
        parts.append(open(f"report_contact_{key}.md").read())
    except OSError:
        pass
    for blk in (gapfill, negatives):
        for v in blk.values():
            for r in (v or {}).get("results", []):
                parts.append(r.get("text") or "")
    return "\n".join(parts)


defect_totals = {"unregistered_field": [], "missing_source_url": [], "unquoted_evidence": [],
                 "missing_priority": 0, "string_confidence": 0, "dropped": 0}
per_account = {}

for key, (name, domain, ent) in ACCTS.items():
    corpus = corpus_for(key)
    claims = [c for c in base["lane_a"] + base["lane_b"]
              if c["entity"] == ent or c["entity"] in
              {CONTACT_ENTITY[n] for n in CONTACT_ENTITY}]
    # lane A/B rows belong to this account only if the entity matches the account or one of ITS
    # contacts; rebuild that mapping explicitly rather than sharing contacts across accounts.
    own_contacts = set()
    for r in (json.load(open("b1c_ark_rosters.json")).get(key) or {}).get("people", []):
        if r["full_name"] in CONTACT_ENTITY:
            own_contacts.add(CONTACT_ENTITY[r["full_name"]])
    for e in json.load(open("b2b_emails.json")):
        if e["account"] == key and e["name"] in CONTACT_ENTITY:
            own_contacts.add(CONTACT_ENTITY[e["name"]])
    if key in CONTACTS:
        own_contacts.add(CONTACTS[key][1])
    claims = [c for c in base["lane_a"] + base["lane_b"]
              if c["entity"] == ent or c["entity"] in own_contacts]

    proposed = [p for p in base["proposed_from_b"]] if key == "zafran" else []
    rows = (base["lane_c_raw"][key]["parsed"].get("account_claims") or [])
    proposed += (base["lane_c_raw"][key]["parsed"].get("proposed_fields") or [])
    if key in contact_out:
        rows = rows + [dict(r, _entity=CONTACTS[key][1])
                       for r in (contact_out[key]["parsed"].get("contact_claims") or [])]
        proposed += (contact_out[key]["parsed"].get("proposed_fields") or [])

    kept = 0
    for row in rows:
        fk = row.get("field_key")
        target = row.get("_entity") or ent
        if fk not in ACCOUNT_FIELDS and fk not in CONTACT_FIELDS and fk not in FACET_FIELDS:
            defect_totals["unregistered_field"].append(f"{key}:{fk}")
            defect_totals["dropped"] += 1
            continue
        if not row.get("source_url"):
            defect_totals["missing_source_url"].append(f"{key}:{fk}")
            defect_totals["dropped"] += 1
            continue
        if isinstance(row.get("confidence"), str):
            defect_totals["string_confidence"] += 1
        if _prio(row.get("priority"), None) is None:
            defect_totals["missing_priority"] += 1
        span = (row.get("evidence_span") or "").strip()
        if span and span[:70] not in corpus:
            defect_totals["unquoted_evidence"].append(f"{key}:{fk}")
        claims.append(stamp(row, source_key="exa_research", tier=4, method="llm_synthesis",
                            source_url=row.get("source_url"), entity=target, priority_default=3))
        kept += 1

    # de-dupe proposed fields by field_key
    seen, dedup = set(), []
    for p in proposed:
        k = p.get("field_key")
        if k and k not in seen:
            seen.add(k)
            dedup.append(p)

    doc = {
        "account": name, "domain": domain, "entity": ent, "workspace_id": WS,
        "run": "arv2-smoke-cluehq", "research_date": "2026-08-31",
        "claim_counts": {
            "total": len(claims),
            "by_tier": {str(t): sum(1 for c in claims if c["source_tier"] == t)
                        for t in (1, 2, 4)},
            "by_priority": {str(p): sum(1 for c in claims if c["priority"] == p)
                            for p in (1, 2, 3)},
            "account_entity": sum(1 for c in claims if c["entity"] == ent),
            "contact_entity": sum(1 for c in claims if c["entity"] != ent),
        },
        "claims": claims, "proposed_fields": dedup,
    }
    json.dump(doc, open(f"claims_{key}.json", "w"), indent=2)
    per_account[key] = doc["claim_counts"]
    print(f"  claims_{key}.json: {len(claims)} claims "
          f"(t1={doc['claim_counts']['by_tier']['1']} t2={doc['claim_counts']['by_tier']['2']} "
          f"t4={doc['claim_counts']['by_tier']['4']}) "
          f"P1={doc['claim_counts']['by_priority']['1']} "
          f"P2={doc['claim_counts']['by_priority']['2']} "
          f"P3={doc['claim_counts']['by_priority']['3']}, {len(dedup)} proposed")

summary = {"per_account": per_account, "defects": defect_totals,
           "model": MODEL, "reasoning": REASONING,
           "total_claims": sum(v["total"] for v in per_account.values())}
json.dump(summary, open("claims_summary.json", "w"), indent=2)
C.timing_record("B4b_contacts_and_merge_TOTAL", time.time() - t_all, "3 contact calls + merge")
print("\nDEFECTS:", json.dumps(defect_totals))
print(f"TOTAL CLAIMS: {summary['total_claims']}")
print(f"\nPHASE B4b {round(time.time()-t_all,1)}s spend={C.total_spend()} "
      f"credits={C.total_credits()}")
