"""B4 — structuring: free-form research -> typed claim rows. The founder's "sample database".

THREE LANES, and the split is the point:
  A. AI ARK  -> tier 1 / `api` / source_key `ai_ark`. Built DETERMINISTICALLY in Python.
     A model may NEVER author a tier-1 claim (the tier-4-iff-synthesis rule makes anything a model
     writes tier 4 by construction).
  B. ASHBY / company careers API -> tier 2 / `official_scrape` / source_key `ashby_public`.
     Also deterministic: dates, titles, comp bands and the isListed flag come straight off the API.
  C. EXA deep reports + own pages -> tier 4 / `llm_synthesis` / source_key `exa_research`.
     `openai/gpt-5-mini`, reasoning `minimal`, ONE SUBJECT PER CALL, closed field-key list.

Every claim carries priority 1|2|3 per the ARV2 signal rubric. Unmappable facts -> proposed_fields.
"""

import json
import sys
import time

sys.path.insert(0, ".")
import b_lib as C  # noqa: E402
from field_catalog import ACCOUNT_FIELDS, CONTACT_FIELDS, FACET_FIELDS, catalog_text  # noqa: E402

WS = "workspace:clue-smoke-2026-08-31"
ACCTS = {
    "zafran": ("Zafran Security", "zafran.io", "account:zafran-security"),
    "cogent": ("Cogent Security, Inc.", "cogent.com", "account:cogent-security"),
    "harmonic": ("Harmonic Security, Inc.", "harmonic.security", "account:harmonic-security"),
    "vendelux": ("Vendelux", "vendelux.com", "account:vendelux"),
    "uptiq": ("UPTIQ, Inc.", "uptiq.ai", "account:uptiq"),
}
CONTACT_ENTITY = {
    "Vari Kaur": "contact:vari-kaur", "Nick Fisher": "contact:nick-fisher",
    "Alexander Semien": "contact:alexander-semien", "Cameron Coles": "contact:cameron-coles",
    "Ana Corio": "contact:ana-corio", "Tyler Chonoles": "contact:tyler-chonoles",
}
_CONF = {"high": 0.85, "medium": 0.65, "med": 0.65, "low": 0.4}


def _prio(raw, default):
    try:
        p = int(raw)
        return p if p in (1, 2, 3) else default
    except (TypeError, ValueError):
        return default


def _conf(raw, default):
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return max(0.0, min(1.0, float(raw)))
    if isinstance(raw, str):
        return _CONF.get(raw.strip().lower(), default)
    return default


def stamp(row, *, source_key, tier, method, source_url, entity, priority_default):
    fk = row["field_key"]
    out = {
        "entity": entity, "field_key": fk,
        "value_json": row.get("value_json", row.get("value")),
        "evidence_span": (row.get("evidence_span") or "")[:600] or None,
        "source_url": source_url or row.get("source_url"),
        "source_key": source_key, "source_tier": tier, "extraction_method": method,
        "verification_status": "unverified", "claim_flavor": "field",
        "reuse_scope": "tenant_private", "workspace_id": WS,
        "confidence": _conf(row.get("confidence"), 0.9 if tier == 1 else
                            (0.85 if tier == 2 else 0.7)),
        "priority": _prio(row.get("priority"), priority_default),
    }
    if fk.startswith("contact."):
        out["identity_binding"] = row.get("identity_binding", "strong")
    if fk.startswith("contact.facet."):
        out["use_class"] = row.get("use_class") or FACET_FIELDS[fk][3]
    return out


# ------------------------------------------------------------------ load the corpora
rosters = json.load(open("b1c_ark_rosters.json"))
emails = json.load(open("b2b_emails.json"))
boards = json.load(open("b0_boards.json"))
site_text = json.load(open("b1a_site_text.json"))
job_text = json.load(open("b1a_job_text.json"))
gapfill = json.load(open("b1d_gapfill.json"))
negatives = json.load(open("b3_negatives.json"))

GAP_FOR = {"zafran": "g_zafran_mktg", "cogent": "g_cogent_mktg",
           "harmonic": "g_harmonic_abm", "uptiq": "g_uptiq_agency"}
NEG_FOR = {"zafran": "n_zafran", "cogent": "n_cogent", "harmonic": "n_harmonic"}


def bundle_text(block, cap):
    return "\n\n".join(
        f"SOURCE {r['url']} [published {r.get('published')}]\n{(r.get('text') or '')[:1400]}"
        for r in (block or {}).get("results", [])
    )[:cap]


# ---------------------------------------------------------- LANE A: AI Ark, tier 1, deterministic
lane_a = []
for key, (name, domain, ent) in ACCTS.items():
    r = rosters.get(key) or {}
    for p in r.get("people", []):
        # SAME-NAME DISCIPLINE: admit only people whose CURRENT company is the account.
        co = (p.get("current_company") or "").lower()
        acct_token = name.split()[0].lower()
        if acct_token not in co or "sigma" in co:
            continue
        cent = CONTACT_ENTITY.get(p["full_name"])
        if not cent:
            continue
        li = p["linkedin"]
        lane_a.append(stamp({"field_key": "contact.current_title", "value_json": p["title"],
                             "evidence_span": f'profile.title = "{p["title"]}" with '
                                              f'position_groups[0].company.name = '
                                              f'"{p["current_company"]}"'},
                            source_key="ai_ark", tier=1, method="api", source_url=li,
                            entity=cent, priority_default=2))
        if p.get("start"):
            lane_a.append(stamp(
                {"field_key": "contact.facet.career_history",
                 "value_json": [{"org": p["current_company"], "role": p["title"],
                                 "start": str(p["start"]), "end": "present"}],
                 "evidence_span": f'position_groups[0] = {{company: "{p["current_company"]}", '
                                  f'title: "{p["title"]}", date.start: "{p["start"]}"}}'},
                source_key="ai_ark", tier=1, method="api", source_url=li,
                entity=cent, priority_default=2))
for e in emails:
    if not e.get("email"):
        continue
    cent = CONTACT_ENTITY[e["name"]]
    lane_a.append(stamp(
        {"field_key": "core.work_email",
         "value_json": {"address": e["email"], "status": e["email_status"],
                        "domain_type": e["domain_type"], "verdict": e["verdict"],
                        "checked_at": e["checked_at"]},
         "evidence_span": f'email.output[0] = {{address: "{e["email"]}", status: '
                          f'"{e["email_status"]}", domainType: "{e["domain_type"]}", '
                          f'mx.provider: "{e.get("mx_provider")}"}}',
         "priority": 2},
        source_key="ai_ark", tier=1, method="api",
        source_url=f"https://www.linkedin.com/in/{e['name'].lower().replace(' ', '-')}",
        entity=cent, priority_default=2))

# ------------------------------------------- LANE B: Ashby / careers API, tier 2, deterministic
lane_b, proposed_from_b = [], []
GTM_DEPTS = ("marketing", "gtm", "go to market", "sales", "customer success", "finance")
for key, (name, domain, ent) in ACCTS.items():
    b = boards.get(key) or {}
    jobs = b.get("all_jobs") or []
    gtm = [j for j in jobs if (j.get("department") or "").strip().lower() in GTM_DEPTS]
    mktg = [j for j in gtm if (j.get("department") or "").strip().lower() in
            ("marketing", "gtm", "go to market")]
    eng = [j for j in jobs if "engineer" in (j.get("department") or "").lower()
           or (j.get("department") or "").upper() in ("R&D",)]
    if b.get("http") == 200:
        lane_b.append(stamp(
            {"field_key": "account.hiring_velocity_eng", "value_json": float(len(eng)),
             "evidence_span": "Ashby public posting API job_board/" + b["slug"] +
                              f": {len(eng)} live engineering/R&D reqs of {len(jobs)} total "
                              "(isListed=true)"},
            source_key="ashby_public", tier=2, method="official_scrape",
            source_url=f"https://api.ashbyhq.com/posting-api/job-board/{b['slug']}",
            entity=ent, priority_default=3))
        # no registered field for GTM hiring -> proposed, with a real example from this account
        if mktg:
            j = mktg[0]
            proposed_from_b.append({
                "field_key": "account.hiring.gtm_open_roles", "entity_type": "account",
                "value_type": "list[object]",
                "value_schema": {"type": "array", "items": {
                    "type": "object", "required": ["title", "published_at", "still_listed"],
                    "properties": {"title": {"type": "string"},
                                   "department": {"type": "string"},
                                   "location": {"type": "string"},
                                   "published_at": {"type": "string"},
                                   "days_open": {"type": "integer"},
                                   "comp_band": {"type": "string"},
                                   "still_listed": {"type": "boolean"},
                                   "url": {"type": "string"}}}},
                "description": "Live go-to-market/marketing requisitions with published date and a "
                               "still-listed flag verified against the ATS on the research date.",
                "reuse_scope": "public_footprint",
                "hypothesis": "This is the single highest-signal ABM buying indicator and the "
                              "catalog has no home for it: account.hiring_velocity_eng covers "
                              "ENGINEERING only. An open GTM req names the seat the client's "
                              "product substitutes for, carries a salary band that is the price "
                              "anchor, and its AGE is the intent signal (a 105-day-open ABM req "
                              "means they cannot hire it). Without this field every Clue P1 "
                              "signal has to be smuggled into account.operational_pain as prose.",
                "example_value": [{"title": j["title"], "department": j["department"],
                                   "location": j["location"], "published_at": j["publishedAt"],
                                   "comp_band": j["comp"], "still_listed": True,
                                   "url": j["url"]}],
                "example_evidence_span": f'Ashby posting API: title="{j["title"]}" '
                                         f'department="{j["department"]}" '
                                         f'publishedAt="{j["publishedAt"]}" isListed=true',
                "example_source_url": j["url"], "priority": 1,
            })

C.save_raw("b4_lane_a_ai_ark", lane_a)
C.save_raw("b4_lane_b_ashby", lane_b)
print(f"lane A (ai_ark, tier1/api): {len(lane_a)} claims")
print(f"lane B (ashby_public, tier2/official_scrape): {len(lane_b)} claims, "
      f"{len(proposed_from_b)} proposed")

# ------------------------------------------------------------------ LANE C: gpt-5-mini synthesis
PRIORITY_RUBRIC = """
SIGNAL PRIORITY — every claim MUST carry `priority`: 1, 2 or 3.
  priority 1 (top; shown first): ACTIVE BUYING INTENT. Go-to-market/marketing hiring (quote the
    req), fresh funding (amount/date/investors), a vacant or newly-filled marketing/growth seat, a
    tooling gap (no ABM/intent platform), an executive publicly naming a GTM bottleneck or growth
    commitment, and any timing event less than 6 months old.
  priority 2 (supporting): firmographics that QUALIFY the account (headcount, vertical, customers,
    outcome metrics), committee composition, titles and personas, tech stack.
  priority 3 (context): history, culture and resonance, background facts, personal hooks.
"""

SYSTEM = f"""You convert free-form research reports into typed claim rows for a claim store.

ABSOLUTE RULES
1. You may ONLY use a field_key from the catalog given to you. If a fact does not fit any catalog
   key, DO NOT force it — put it in proposed_fields instead.
2. value_json MUST validate against that field's value_schema exactly (right JSON type, required
   properties present, enum values exact).
3. evidence_span MUST be a VERBATIM substring of the material given to you — copy the quoted text
   exactly as it appears. Never paraphrase into evidence_span. If there is no quote for a fact,
   omit the fact entirely.
4. source_url MUST be the URL the material attributes that fact to. Every row needs one. Never
   invent a URL and never reuse an unrelated one.
5. NEVER emit a row for anything marked "NOT FOUND". Never emit an automated/LinkedIn REVENUE
   ESTIMATE as core.annual_revenue — an estimate is not a reported number; skip it or use
   core.revenue_band only if the material states a band.
6. NEVER emit special-category personal data (health, religion, politics, sexual orientation,
   ethnicity, union membership, criminal matters, family/bereavement, home address, personal
   phone/email).
7. Do NOT emit provenance fields (source_key, tier, extraction_method, verification_status): the
   caller stamps those. Emit only field_key, value_json, evidence_span, source_url, confidence,
   priority, and for contact.facet.* also use_class.
8. Prefer fewer, well-evidenced rows over many thin ones. One row per field per distinct fact.
{PRIORITY_RUBRIC}
Return ONLY a JSON object with the keys the user message asks for.
Each proposed field: {{"field_key","entity_type","value_type","value_schema","description",
"reuse_scope","hypothesis","example_value","example_evidence_span","example_source_url",
"priority"}} where description is agent-facing and hypothesis is one paragraph on why an ABM
platform needs this field."""

MODEL = "openai/gpt-5-mini"
REASONING = {"effort": "minimal"}


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


only = sys.argv[1:] or list(ACCTS)
t_all = time.time()
all_out = {}

for key in only:
    name, domain, ent = ACCTS[key]
    t0 = time.time()
    corpus = (
        f"# DEEP RESEARCH REPORT (Exa deep-reasoning, one call)\n"
        f"{open(f'report_account_{key}.md').read()[:30000]}\n\n"
        f"# THE COMPANY'S OWN PAGES + FUNDING ANNOUNCEMENTS (fetched verbatim)\n"
        f"{site_text.get(key, '')[:22000]}\n\n"
        f"# THE COMPANY'S OWN LIVE GO-TO-MARKET JOB REQS (Ashby posting API, verbatim; "
        f"every one below is STILL LISTED on 2026-08-31)\n{job_text.get(key, '')[:22000]}\n\n"
        f"# TARGETED GAP-FILL SEARCH RESULTS\n"
        f"{bundle_text(gapfill.get(GAP_FOR.get(key)), 12000)}\n\n"
        f"# REPUTATION / NEGATIVES SEARCH RESULTS\n"
        f"{bundle_text(negatives.get(NEG_FOR.get(key)), 10000)}\n"
    )
    user = (f"# FIELD CATALOG (the ONLY keys you may use)\n{catalog_text()}\n\n"
            f"# ACCOUNT: {name} ({domain}). Entity id: {ent}\n"
            f"# The client selling INTO this account is Clue (cluehq.ai), an AI-native ABM "
            f"orchestration platform: deep account research, buying-committee mapping, "
            f"per-account microsites, LinkedIn/Meta paid media, and direct mail. Judge priority "
            f"against THAT sale.\n\n{corpus}\n\n"
            f"Emit ONLY account-entity claims for {ent} now.\n"
            f'Return {{"account_claims":[...], "proposed_fields":[...]}}.')
    open(f"structuring_bundle_{key}.txt", "w").write(SYSTEM + "\n\n=====\n\n" + user)
    parsed, resp = run(f"b4_structure_{key}", user)
    all_out[key] = {"parsed": parsed, "usage": resp.get("usage"),
                    "elapsed_s": resp.get("_elapsed_s")}
    C.timing_record(f"B4_structure_{key}", time.time() - t0, "gpt-5-mini, one subject")
    print(f"  -> {key}: {len(parsed.get('account_claims') or [])} claims, "
          f"{len(parsed.get('proposed_fields') or [])} proposed")

json.dump({"lane_a": lane_a, "lane_b": lane_b, "proposed_from_b": proposed_from_b,
           "lane_c_raw": all_out}, open("b4_structure_raw.json", "w"), indent=2)
C.timing_record("B4_structure_accounts_TOTAL", time.time() - t_all, f"{len(only)} account calls")
print(f"\nPHASE B4-accounts {round(time.time()-t_all,1)}s spend={C.total_spend()}")
