#!/usr/bin/env python3
"""Display-layer control test — how should claim rows become page copy?

Three questions, one harness:
  Q1  one call per section  vs  the whole page in one call   (Luna, both ways, + a cached-prefix variant)
  Q2  can a cheaper OpenRouter model write the page as well as gpt-5.6-luna?
  Q3  where does the cost go, and what keeps quality while cutting it?

Inputs are the REAL Zafran claims (.context/arv2-one-account-aiark/claims_zafran.json). Every output
is scored two ways: mechanical checks in code (quotes verbatim? numbers in the payload? claimIds
valid? unsafe facts leaked? P1 coverage? use-lines present?) and a blind LLM judge.

usage:  control_test.py --smoke | --run | --judge | --report
"""
import concurrent.futures as cf
import json, os, re, sys, time, pathlib, threading, random, urllib.request, urllib.error

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parents[1]
RAW = ROOT / "raw"; RAW.mkdir(exist_ok=True)
OUT = ROOT / "out"; OUT.mkdir(exist_ok=True)
RESULTS = ROOT / "results.jsonl"
LOCK = threading.Lock()

def env_key(name):
    for line in (REPO / ".env").read_text().splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"{name} missing in .env")
KEY = env_key("CLUE_OPENROUTER_API_KEY")

# ----------------------------------------------------------------------------- claims → payload
NAME_OF = {"nicholastfisher": "Nick Fisher", "varinderkaur": "Vari Kaur", "sanaz-yashar": "Sanaz Yashar",
           "tomanthonyjr": "Tom Anthony", "ben-seri": "Ben Seri"}
P1 = {"zaf-016","zaf-017","zaf-031","zaf-033","zaf-045","zaf-083","zaf-084","zaf-085","zaf-086","zaf-087","zaf-088",
      "zaf-089","zaf-090","zaf-091","zaf-092","zaf-093","zaf-095","zaf-100","zaf-101","zaf-102","zaf-110","zaf-113",
      "zaf-115","zaf-125","zaf-128","zaf-129","zaf-140","zaf-158","zaf-159","zaf-169","zaf-170","zaf-171","zaf-172","zaf-174"}
DROP_FIELDS = {"account.media_layer_index","account.media_transcript_quality_warning","contact.facet.excluded_lookalike",
               "account.employee_roster_sample","core.company_languages","core.industries_all","core.tech_stack_categorised",
               "core.legal_name","core.company_email","core.company_crunchbase_url","core.company_twitter_url"}
P3_CORE_KEEP = {"core.company_about","core.annual_revenue","core.revenue_band","core.employee_count","core.work_email",
                "core.primary_tech_stack","core.hq_location","core.founded_year"}

def subject_of(r):
    if r["entity"] == "account":
        return "Zafran Security"
    k = r["entity_key"]
    for slug, name in NAME_OF.items():
        if slug in k:
            return name
    return k

def domain_of(r):
    u = r.get("source_url") or ""
    if u.startswith("http"):
        return re.sub(r"^www\.", "", urllib.parse.urlsplit(u).hostname or "")
    p = (r.get("source_provider") or "")
    if "ai_ark" in p: return "AI Ark record"
    if "ashby" in p: return "Ashby job board"
    if "gemini" in p: return "media transcript"
    return "research bundle"
import urllib.parse

def load_claims():
    rows = json.load(open(REPO / ".context/arv2-one-account-aiark/claims_zafran.json"))["claims"]
    out = []
    for r in rows:
        fk = r["field_key"].replace("PROPOSED::", "")
        v = r.get("value")
        if fk in DROP_FIELDS: continue
        if isinstance(v, str) and v.strip().upper().startswith("NOT FOUND"): continue
        vs = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        q = str(r.get("evidence_span") or r.get("quote") or "")
        if fk.startswith("core.") and r.get("claim_kind") == "deterministic" and fk not in P3_CORE_KEEP:
            pr = 3
        elif r["claim_id"] in P1:
            pr = 1
        else:
            pr = 2
        out.append({"claimId": r["claim_id"], "entity": r["entity"], "subject": subject_of(r), "fieldKey": fk,
                    "value": vs[:700], "quote": q[:400], "sourceDomain": domain_of(r),
                    "observedAt": r.get("observed_at"), "priority": pr, "outreachSafe": bool(r.get("outreach_safe", True))})
    return out
ALL = load_claims()
UNSAFE_IDS = {c["claimId"] for c in ALL if not c["outreachSafe"]}

CLIENT = ("Clue — an AI-native account-based marketing (ABM) platform. It discovers target accounts, researches each "
          "account and its buying committee to this depth with a source on every fact, drafts personalised content, "
          "generates brand-aligned artifacts (landing pages, mailers, ads) and scales them across accounts. It plugs "
          "into HubSpot / Salesforce / Outreach; it does not replace them. The reader is a marketer at Clue planning "
          "outreach to the subject. 'We' / 'us' means Clue.")

CONTACT_SECTIONS = [
  ("why_this_person", "Why this person",
   "2–3 items. What this person owns, how they think, and why they matter to us. Each item has a `sendLine` starting 'In your email:' or 'In the platform:' saying how to use it.",
   ["contact.current_title","contact.persona","contact.job_level","contact.headline","contact.facet.self_summary","contact.facet.career_history",
    "contact.facet.publications","contact.facet.recent_post","contact.role_on_committee","account.abm_program_maturity","contact.facet.stated_skills",
    "contact.facet.recent_award","contact.facet.alma_mater"], "safe"),
  ("problem_now", "Their problem right now",
   "3–4 items. The concrete, current problems this person has that Clue addresses — their problem, not their product's pitch. Each item has a `sendLine`: a sentence the marketer can paste, starting 'In your email:' or 'On the landing page:' or 'In the platform:'.",
   ["account.abm_program_maturity","account.hiring_velocity","account.open_requisitions","account.gtm_tooling_stack","account.operational_pain",
    "account.strategic_moves","contact.facet.recent_post","contact.facet.publications","core.primary_tech_stack","account.resonance.buying_culture"], "safe"),
  ("openers", "Openers",
   "3–4 items, strongest first. Each item is ONE ready-to-send opening line grounded in one fact: the body explains the fact, the `sendLine` is the exact line, starting 'In your email:'. The strongest openers use the most specific safe fact available — a hobby they published, a line they wrote, a seat they cannot fill — never their job title. Use a personal-life hook at most once and add 'Use once, first line only.' to its body when you do.",
   ["contact.facet.hobby","contact.facet.voice_quote","contact.facet.recent_post","contact.facet.publications","contact.facet.career_history",
    "account.abm_program_maturity","contact.member_badges","contact.network_statistics","contact.facet.communication_style"], "safe"),
  ("angles", "Angles",
   "2–4 items. Channel plays: direct mail, landing page, content, event. Name the channel in the h2, say why in the body, and put the instruction in `sendLine` starting 'In the direct-mail brief:', 'Brief the design agent with:', 'On the landing page:' or 'For the event:'.",
   ["contact.facet.hobby","contact.facet.voice_quote","contact.current_location","account.resonance.buying_culture","account.strategic_moves",
    "account.claimed_outcomes_metrics","account.resonance.public_frustrations","contact.facet.publications"], "safe"),
  ("do_not_mention", "Do not mention",
   "One item per unsafe fact. h2 = the fact in a few words plus its status; body = why it must not be used in outreach.",
   ["*"], "unsafe"),
]
INSIGHT_ITEM = ("h2 = what happened, with the date or number. Body 2–4 sentences: the fact with verbatim quotes and dates, "
                "then one or two sentences starting 'What it means for us:'. contactRefs for every person named.")
INSIGHTS_SECTIONS = [
  ("buying_signals", "Buying signals", "3–4 items. " + INSIGHT_ITEM,
   ["account.open_requisitions","account.hiring_velocity","account.abm_program_maturity","account.strategic_moves","account.operational_pain",
    "account.resonance.buying_culture","account.hiring_velocity_eng"], "safe"),
  ("money_momentum", "Money & momentum", "2–3 items. " + INSIGHT_ITEM,
   ["account.recent_funding","account.total_funding","core.annual_revenue","core.revenue_band","core.employee_count"], "safe"),
  ("tools", "Tools they already use", "2–3 items. " + INSIGHT_ITEM,
   ["account.gtm_tooling_stack","core.primary_tech_stack","contact.facet.recent_post","contact.facet.publications"], "safe"),
  ("how_they_sell", "How they sell, and who they win", "2–3 items. " + INSIGHT_ITEM,
   ["account.named_customers","account.claimed_customer_logos","account.claimed_outcomes_metrics","account.product_packaging",
    "account.resonance.public_frustrations","account.resonance.eng_blog_tone","core.company_about"], "safe"),
  ("contact_insights", "Contact insights",
   "One item per person (there are 5 people in the claims): h2 = the single most useful thing that person said or did; body as an insight, ending 'What it means for us:'; contactRefs = that person.",
   ["contact.facet.recent_post","contact.facet.publications","contact.facet.voice_quote","contact.facet.certifications","contact.facet.career_history",
    "contact.current_title","contact.persona","contact.facet.stated_interests"], "safe"),
  ("context_only", "Context only — never use in outreach",
   "One item per unsafe fact; body states its status (refuted / unresolved / confirmed) and ends with 'Never mention.'",
   ["*"], "unsafe"),
]
PAGES = {
  "contact": {"subject": {"name": "Nick Fisher", "persona": "economic_buyer", "account": "Zafran Security"}, "sections": CONTACT_SECTIONS,
              "claims": [c for c in ALL if c["entity"] == "account" or c["subject"] == "Nick Fisher"]},
  "insights": {"subject": {"name": "Zafran Security", "domain": "zafran.io"}, "sections": INSIGHTS_SECTIONS, "claims": ALL},
}

def section_claims(page, sec):
    key, h1, instr, fields, mode = sec
    rows = PAGES[page]["claims"]
    if mode == "unsafe":
        return [c for c in rows if not c["outreachSafe"]]
    return [c for c in rows if c["outreachSafe"] and c["fieldKey"] in fields]

# ----------------------------------------------------------------------------- prompts
SYSTEM = """You are the DISPLAY layer of Clue, an ABM platform. You are given the exact fact rows ("claims") the backend holds for one subject, and you write the copy a revenue operator reads on the page. The operator has 15 seconds.

THE HARD RULES
1. You may not state anything the claims do not contain. No invented numbers, dates, employers, tenures, or inferences presented as facts. If it is not in a claim, it does not exist.
2. Inside `h2` and `text`, every quotation mark must wrap text copied verbatim from a claim's `value` or `quote`. Never paraphrase inside quotation marks. The `sendLine` field is different: it is YOUR writing — the exact line the marketer will paste — and it may embed a verbatim claim quote.
3. Every sentence you write lists the claimIds it is built from. Never write a sentence with no claimId. Never type a URL or a domain name — the frontend renders sources from claimIds.
4. Claims with outreachSafe=false may ONLY be used in the sections named `do_not_mention` / `context_only`. Never anywhere else.
5. A section with no usable claims is a real answer: return it with "empty": true and no items.
6. No marketing filler ("innovative", "cutting-edge", "leader in", "leverage"). Prefer the person's own words. Be concrete: names, dates, numbers, titles.
7. `client` describes who is reading. "We" / "us" means the client.

OUTPUT: return ONLY a JSON object, no prose, no code fences. Shape:
{"sections":[{"key":"<section key>","empty":false,"items":[{"h2":"<one line, max 110 characters: the fact and why it matters>","body":[{"text":"<one sentence>","claimIds":["<id>"]}],"sendLine":"<only where the section instruction asks for a line to paste; the exact line, starting with the channel tag the instruction gives>","contactRefs":[{"name":"<person named in this item, if any>"}],"priority":1}]}]}
Each item body is 2–5 sentences. `priority` is 1, 2 or 3 (1 = act on this first), taken from the strongest claim used."""

def sec_desc(sec, with_fields=True):
    key, h1, instr, fields, mode = sec
    d = {"key": key, "h1": h1, "instruction": instr}
    if with_fields:
        d["allowedFieldKeys"] = fields if mode == "safe" else ["every claim with outreachSafe=false"]
    return d

def user_whole(page):
    P = PAGES[page]
    return ("# PAGE\n" + json.dumps({"page": page, "subject": P["subject"], "client": CLIENT}, ensure_ascii=False) +
            "\n\n# SECTIONS TO WRITE, IN ORDER\n" + json.dumps([sec_desc(s) for s in P["sections"]], ensure_ascii=False, indent=1) +
            "\n\n# CLAIMS (this is everything you know)\n" + json.dumps(P["claims"], ensure_ascii=False, indent=1) +
            "\n\nWrite every section now, in order.")

def user_section_min(page, sec):
    P = PAGES[page]
    return ("# PAGE\n" + json.dumps({"page": page, "subject": P["subject"], "client": CLIENT}, ensure_ascii=False) +
            "\n\n# THE ONE SECTION TO WRITE\n" + json.dumps(sec_desc(sec), ensure_ascii=False, indent=1) +
            "\n\n# CLAIMS (this is everything you know)\n" + json.dumps(section_claims(page, sec), ensure_ascii=False, indent=1) +
            "\n\nWrite this one section now. Return {\"sections\":[<this section>]}.")

def user_section_cached(page, sec):
    # identical prefix for every section of the page (so the provider can cache it); the section is the suffix
    P = PAGES[page]
    prefix = ("# PAGE\n" + json.dumps({"page": page, "subject": P["subject"], "client": CLIENT}, ensure_ascii=False) +
              "\n\n# ALL SECTIONS OF THIS PAGE (context only — you will be told which one to write)\n" +
              json.dumps([sec_desc(s) for s in P["sections"]], ensure_ascii=False, indent=1) +
              "\n\n# CLAIMS (this is everything you know)\n" + json.dumps(P["claims"], ensure_ascii=False, indent=1))
    suffix = ("\n\n# WRITE ONLY THIS SECTION NOW: " + sec[0] + "\n" + json.dumps(sec_desc(sec), ensure_ascii=False) +
              "\nReturn {\"sections\":[<this one section>]}.")
    return prefix + suffix

# ----------------------------------------------------------------------------- OpenRouter
def call(model, system, user, label, response_json=True, timeout=420, reasoning=None):
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "usage": {"include": True}}
    if response_json: body["response_format"] = {"type": "json_object"}
    if reasoning is not None: body["reasoning"] = reasoning
    data = json.dumps(body).encode()
    last = None
    for attempt in range(4):
        t0 = time.time()
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=data, method="POST",
                                     headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json",
                                              "HTTP-Referer": "https://clue.local/display-control-test", "X-Title": "Clue display-layer control test"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                txt = r.read().decode(); status = r.status
        except urllib.error.HTTPError as e:
            txt = e.read().decode(errors="replace"); status = e.code
        except Exception as e:  # timeouts etc
            txt = json.dumps({"error": {"message": repr(e)}}); status = 0
        el = time.time() - t0
        try: out = json.loads(txt)
        except Exception: out = {"_unparsed": txt[:3000]}
        out["_http_status"] = status; out["_elapsed_s"] = round(el, 2); out["_attempt"] = attempt
        (RAW / f"{label}.a{attempt}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
        if status == 200 and (out.get("choices") or [{}])[0].get("message", {}).get("content"):
            return out
        last = out
        if status == 400 and response_json and "response_format" in json.dumps(out.get("error", {})):
            body.pop("response_format", None); data = json.dumps(body).encode(); response_json = False; continue
        time.sleep(3 + 5 * attempt + random.random())
    return last

def usage_of(out):
    u = out.get("usage") or {}
    cost = u.get("cost") or 0
    up = (u.get("cost_details") or {}).get("upstream_inference_cost") or 0
    return {"prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
            "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
            "cost_usd": float(cost) if cost else float(up), "cost_source": "openrouter" if cost else "upstream_byok",
            "elapsed_s": out.get("_elapsed_s")}

def parse_json(text):
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]; t = t.split("\n", 1)[1] if "\n" in t else t
    try: return json.loads(t)
    except Exception: pass
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        try: return json.loads(m.group(0))
        except Exception: return None
    return None

# ----------------------------------------------------------------------------- run configs
MODELS = {
  "luna": "openai/gpt-5.6-luna",
  "muse-1.3c": "meta/muse-spark-1.3-contributor",   # gated: needs the 18+ attestation at openrouter.ai/settings/preferences
  "muse-glimmer": "meta/muse-glimmer-30b",
  "gpt-5-nano": "openai/gpt-5-nano",
  "gpt-5-mini": "openai/gpt-5-mini",
  "gemini-2.5-fl": "google/gemini-2.5-flash-lite",
  "deepseek-v4-fl": "deepseek/deepseek-v4-flash",
  "qwen3.7-flash": "qwen/qwen3.7-flash",
  "glm-5.3-flash": "z-ai/glm-5.3-flash",
  "mistral-small": "mistralai/mistral-small-2603",
  "llama-4-mav": "meta-llama/llama-4-maverick",
}
JUDGE = "anthropic/claude-sonnet-5"

def run_config(model_key, mode, page, rep):
    key = f"{model_key}|{mode}|{page}|r{rep}"
    model = MODELS[model_key]
    calls = []
    sections = []
    if mode in ("whole", "whole_low"):
        out = call(model, SYSTEM, user_whole(page), label=key.replace("|", "_"),
                   reasoning={"effort": "low"} if mode == "whole_low" else None)
        u = usage_of(out); calls.append(u)
        obj = parse_json((out.get("choices") or [{}])[0].get("message", {}).get("content"))
        sections = (obj or {}).get("sections") if isinstance(obj, dict) else None
        json_ok = bool(sections)
    else:
        json_ok = True; sections = []
        for sec in PAGES[page]["sections"]:
            u_text = user_section_min(page, sec) if mode == "section_min" else user_section_cached(page, sec)
            out = call(model, SYSTEM, u_text, label=(key + "|" + sec[0]).replace("|", "_"))
            u = usage_of(out); calls.append(u)
            obj = parse_json((out.get("choices") or [{}])[0].get("message", {}).get("content"))
            got = (obj or {}).get("sections") if isinstance(obj, dict) else None
            if got and isinstance(got, list):
                got[0]["key"] = sec[0]; sections.append(got[0])
            else:
                json_ok = False; sections.append({"key": sec[0], "empty": True, "items": [], "_failed": True})
    rec = {"key": key, "model": model_key, "model_id": model, "mode": mode, "page": page, "rep": rep, "json_ok": json_ok,
           "n_calls": len(calls), "cost_usd": round(sum(c["cost_usd"] for c in calls), 6),
           "latency_sum_s": round(sum(c["elapsed_s"] or 0 for c in calls), 1), "latency_max_s": round(max(c["elapsed_s"] or 0 for c in calls), 1),
           "prompt_tokens": sum(c["prompt_tokens"] or 0 for c in calls), "completion_tokens": sum(c["completion_tokens"] or 0 for c in calls),
           "reasoning_tokens": sum(c["reasoning_tokens"] or 0 for c in calls), "cached_tokens": sum(c["cached_tokens"] or 0 for c in calls),
           "cost_source": calls[0]["cost_source"], "sections": sections or []}
    rec["sections"] = normalise_sections(rec["sections"])
    rec["metrics"] = mechanical(page, rec["sections"])
    render(rec)
    with LOCK:
        with open(RESULTS, "a") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"done {key:40s} json={json_ok} ${rec['cost_usd']:.4f} {rec['latency_sum_s']}s  "
          f"quotes_bad={rec['metrics']['quote_violations']}/{rec['metrics']['quotes_total']} nums_bad={rec['metrics']['numbers_not_in_payload']} "
          f"leaks={rec['metrics']['unsafe_leaks']} off_recipe={rec['metrics']['off_recipe']} p1={rec['metrics']['p1_coverage']} useline={rec['metrics'].get('useline_rate')}", flush=True)
    return rec

def normalise_sections(sections):
    """Models sometimes return strings where objects belong. Keep the dict-shaped parts, drop the rest, never crash."""
    out = []
    for s in sections or []:
        if not isinstance(s, dict): continue
        items = []
        for it in s.get("items") or []:
            if not isinstance(it, dict): continue
            body = []
            for b in it.get("body") or []:
                if isinstance(b, str): body.append({"text": b, "claimIds": []})
                elif isinstance(b, dict): body.append({"text": str(b.get("text") or ""), "claimIds": [c for c in (b.get("claimIds") or []) if isinstance(c, str)]})
            it = dict(it); it["body"] = body
            it["contactRefs"] = [r if isinstance(r, dict) else {"name": str(r)} for r in (it.get("contactRefs") or [])]
            if isinstance(it.get("sendLine"), dict): it["sendLine"] = str(it["sendLine"].get("text") or "")
            items.append(it)
        s = dict(s); s["items"] = items; out.append(s)
    return out

# ----------------------------------------------------------------------------- mechanical checks
def norm(s):
    s = s.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

NUM_RE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?\s?(?:million|billion|[mkb]\b|%|k\b)?", re.I)
def num_variants(tok):
    t = tok.lower().replace("$", "").replace(",", "").replace(" ", "")
    m = re.match(r"(\d+(?:\.\d+)?)(million|billion|m|k|b|%)?$", t)
    if not m: return {t}
    n, suf = m.group(1), m.group(2)
    v = {n}
    try:
        f = float(n)
        if suf in ("m", "million"): v.add(str(int(f * 1e6)))
        if suf in ("b", "billion"): v.add(str(int(f * 1e9)))
        if suf == "k": v.add(str(int(f * 1e3)))
        if f.is_integer(): v.add(str(int(f)))
    except ValueError: pass
    return v

def corpus_numbers(rows):
    text = " ".join(c["value"] + " " + c["quote"] + " " + str(c.get("observedAt") or "") for c in rows)
    nums = set()
    for tok in NUM_RE.findall(text):
        nums |= num_variants(tok)
    # dates like 2026-06-17 → also 17, 2026, 06
    for y, mo, d in re.findall(r"(\d{4})-(\d{2})-(\d{2})", text):
        nums |= {y, mo, d, str(int(d)), str(int(mo))}
    return nums

def extract_quotes(text):
    """Quoted spans: curly pairs by regex, straight pairs by sequential split (so a closing mark never pairs with the next opening)."""
    return re.findall(r'“([^”]{20,}?)”', text) + [seg for seg in text.split('"')[1::2] if len(seg) >= 20]

def mechanical(page, sections):
    rows = PAGES[page]["claims"]
    ids = {c["claimId"] for c in rows}
    corpus = norm(" ".join(c["value"] + " " + c["quote"] for c in rows))
    cnums = corpus_numbers(rows)
    unsafe_secs = {"do_not_mention", "context_only"}
    leak_words = ["acqui", "nvidia", "havdala", "cash burn", "20 million", "roughly $20", "steep discount", "struggled to demonstrate"]
    m = dict(items=0, sentences=0, sentences_no_claim=0, bad_claim_ids=0, quotes_total=0, quote_violations=0,
             numbers_total=0, numbers_not_in_payload=0, unsafe_leaks=0, useline_items=0, h2_over_110=0, words=0,
             empty_sections=0, failed_sections=0, dup_h2=0, url_typed=0, off_recipe=0, citations=0, ids_in_text=0)
    fk_of = {c["claimId"]: c["fieldKey"] for c in rows}
    allowed = {s[0]: set(s[3]) for s in PAGES[page]["sections"] if s[4] == "safe"}
    p1_avail = {c["claimId"] for c in rows if c["priority"] == 1}
    p1_cited = set()
    h2s = []
    expected = [s[0] for s in PAGES[page]["sections"]]
    m["sections_present"] = sum(1 for s in sections if s.get("key") in expected)
    m["sections_expected"] = len(expected)
    for s in sections:
        if s.get("_failed"): m["failed_sections"] += 1
        if s.get("empty") or not s.get("items"): m["empty_sections"] += 1
        for it in s.get("items") or []:
            m["items"] += 1
            h2 = str(it.get("h2") or ""); h2s.append(norm(h2))
            if len(h2) > 110: m["h2_over_110"] += 1
            texts = [h2]
            for b in it.get("body") or []:
                if isinstance(b, str): b = {"text": b, "claimIds": []}
                m["sentences"] += 1
                cids = b.get("claimIds") or []
                if not cids: m["sentences_no_claim"] += 1
                for cid in cids:
                    m["citations"] += 1
                    if cid not in ids: m["bad_claim_ids"] += 1
                    elif cid in p1_avail: p1_cited.add(cid)
                    if cid in UNSAFE_IDS and s.get("key") not in unsafe_secs: m["unsafe_leaks"] += 1
                    if s.get("key") in allowed and cid in fk_of and fk_of[cid] not in allowed[s["key"]]: m["off_recipe"] += 1
                texts.append(str(b.get("text") or ""))
            quotable = " ".join(texts)            # quote-verbatim rule applies to h2 + body text only
            send = str(it.get("sendLine") or "")
            full = quotable + " " + send           # numbers / leaks / use-lines / words see everything
            m["ids_in_text"] += len(re.findall(r"zaf-\d{3}", full))       # ids typed into prose = frontend would render them literally
            full = re.sub(r"\[?\s*zaf-\d{3}(?:\s*,\s*zaf-\d{3})*\s*\]?", " ", full)
            quotable = re.sub(r"\[?\s*zaf-\d{3}(?:\s*,\s*zaf-\d{3})*\s*\]?", " ", quotable)
            m["words"] += len(full.split())
            if re.search(r"https?://|www\.|\.(com|io|ai)\b", full): m["url_typed"] += 1
            if s.get("key") not in unsafe_secs:
                low = full.lower()
                if any(w in low for w in leak_words): m["unsafe_leaks"] += 1
            if page == "contact" and s.get("key") not in unsafe_secs:
                if re.search(r"in your email|on the landing page|in the platform|direct[- ]mail|brief the design agent|for the event", full, re.I):
                    m["useline_items"] += 1
            # quotes verbatim? (h2 + body only; sendLine is the writer's own line)
            for q in extract_quotes(quotable):
                pieces = [p for p in re.split(r"…|\.\.\.", q) if len(p.split()) >= 4]
                if not pieces: continue
                m["quotes_total"] += 1
                if not all(norm(p) in corpus for p in pieces): m["quote_violations"] += 1
            # numbers in payload?
            for tok in NUM_RE.findall(full):
                v = num_variants(tok)
                try:
                    if float(list(v)[0]) < 13: continue
                except ValueError: continue
                m["numbers_total"] += 1
                if not (v & cnums): m["numbers_not_in_payload"] += 1
    m["dup_h2"] = len(h2s) - len(set(h2s))
    m["p1_coverage"] = round(len(p1_cited) / max(1, len(p1_avail)), 2)
    m["useline_rate"] = round(m["useline_items"] / max(1, sum(len(s.get("items") or []) for s in sections if s.get("key") not in unsafe_secs)), 2) if page == "contact" else None
    return m

def render(rec):
    lines = [f"# {rec['page']} — {rec['model']} / {rec['mode']} / r{rec['rep']}  (${rec['cost_usd']:.4f}, {rec['latency_sum_s']}s)\n"]
    h1 = {s[0]: s[1] for s in PAGES[rec["page"]]["sections"]}
    for s in rec["sections"]:
        lines.append(f"\n## {h1.get(s.get('key'), s.get('key'))}" + ("  (EMPTY)" if s.get("empty") or not s.get("items") else "") + ("  (FAILED)" if s.get("_failed") else ""))
        for it in s.get("items") or []:
            lines.append(f"\n**{it.get('h2')}**  (P{it.get('priority')})")
            for b in it.get("body") or []:
                if isinstance(b, str): b = {"text": b, "claimIds": []}
                lines.append(f"{b.get('text')} [{', '.join(b.get('claimIds') or [])}]")
            if it.get("sendLine"): lines.append(f"➜ {it.get('sendLine')}")
            refs = [r.get("name") for r in it.get("contactRefs") or [] if isinstance(r, dict)]
            if refs: lines.append("→ " + " · ".join(refs))
    (OUT / (rec["key"].replace("|", "_") + ".md")).write_text("\n".join(lines))

# ----------------------------------------------------------------------------- judge
JUDGE_SYS = """You are grading the copy an ABM platform shows a marketer. You get (a) the fact rows ("claims") the writer was given, (b) the section instructions, (c) the writer's JSON output. You do NOT know which model wrote it. Grade strictly.

Score 1–5 each:
- faithfulness: every statement traceable to a claim; quotation marks wrap verbatim claim text; no invented numbers, dates, tenures or inferences stated as fact. (5 = nothing unsupported; 1 = fabrications)
- specificity: names, dates, numbers, titles, the person's own words — not generic. (5 = every item concrete)
- actionability: would a marketer at the client act on this as-is? On the CONTACT page, are the `sendLine` fields sendable, specific to this person, and grounded in the fact the item cites? On the INSIGHTS page no sendLine is asked for — do NOT penalise its absence there; judge whether each 'What it means for us' line tells the marketer what to do. (5 = yes, all of it)
- clarity: reads like a sharp colleague; no filler, no marketing-speak, no padding, h2 lines are genuinely one line. (5 = crisp)
- structure: follows the section instructions (item counts, use-lines, do-not-mention handling, contactRefs); unsafe facts only in the unsafe section. (5 = fully)
Then overall 1–10, one sentence naming the single worst problem, one sentence naming the best item.
Return ONLY JSON: {"faithfulness":n,"specificity":n,"actionability":n,"clarity":n,"structure":n,"overall":n,"worst_problem":"...","best_item":"..."}"""

def judge(rec):
    page = rec["page"]
    u = ("# PAGE: " + page.upper() + ("  (no sendLine is required on this page)" if page == "insights" else "  (sendLine required where the section instruction says so)") +
         "\n\n# CLAIMS THE WRITER WAS GIVEN\n" + json.dumps(PAGES[page]["claims"], ensure_ascii=False) +
         "\n\n# SECTION INSTRUCTIONS\n" + json.dumps([sec_desc(s) for s in PAGES[page]["sections"]], ensure_ascii=False) +
         "\n\n# THE WRITER'S OUTPUT\n" + json.dumps({"sections": rec["sections"]}, ensure_ascii=False) + "\n\nGrade it now.")
    out = call(JUDGE, JUDGE_SYS, u, label=("judge_" + rec["key"]).replace("|", "_"))
    obj = parse_json((out.get("choices") or [{}])[0].get("message", {}).get("content"))
    ju = usage_of(out)
    return {"scores": obj, "judge_cost_usd": ju["cost_usd"], "judge_elapsed_s": ju["elapsed_s"]}

# ----------------------------------------------------------------------------- drivers
def load_results():
    if not RESULTS.exists(): return {}
    recs = {}
    for line in RESULTS.read_text().splitlines():
        if line.strip():
            r = json.loads(line); recs[r["key"]] = r
    return recs

def configs():
    cfgs = []
    for page in ("contact", "insights"):
        for rep in (1, 2):
            cfgs.append(("luna", "whole", page, rep))
            cfgs.append(("luna", "section_min", page, rep))
            cfgs.append(("luna", "section_cached", page, rep))
            cfgs.append(("luna", "whole_low", page, rep))
            for mk in MODELS:
                if mk != "luna": cfgs.append((mk, "whole", page, rep))
    return cfgs

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--smoke"
    if arg == "--smoke":
        rec = run_config("luna", "whole", "contact", 0)
        print(json.dumps(rec["metrics"], indent=1))
        print(f"prompt_tokens={rec['prompt_tokens']} completion={rec['completion_tokens']} reasoning={rec['reasoning_tokens']} cost=${rec['cost_usd']}")
    elif arg == "--run":
        have = load_results()
        todo = [c for c in configs() if f"{c[0]}|{c[1]}|{c[2]}|r{c[3]}" not in have]
        print(f"{len(todo)} configs to run ({len(have)} already done)", flush=True)
        def safe(c):
            try: return run_config(*c)
            except Exception as e:
                print("FAILED", c, repr(e), flush=True)
        with cf.ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(safe, todo))
    elif arg == "--rescore":
        recs = load_results()
        for r in recs.values():
            r["sections"] = normalise_sections(r["sections"]); r["metrics"] = mechanical(r["page"], r["sections"]); render(r)
        with open(RESULTS, "w") as f:
            for r in recs.values(): f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print("rescored", len(recs))
    elif arg == "--judge":
        recs = load_results()
        todo = [r for r in recs.values() if not r.get("judge") and r["rep"] in (1, 2) and r.get("sections")]
        print(f"judging {len(todo)}", flush=True)
        def do(r):
            r["judge"] = judge(r); print("judged", r["key"], r["judge"]["scores"], flush=True); return r
        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(do, todo))
        with open(RESULTS, "w") as f:
            for r in recs.values(): f.write(json.dumps(r, ensure_ascii=False) + "\n")
    elif arg == "--report":
        recs = load_results()
        import statistics as st
        groups = {}
        for r in recs.values():
            if r["rep"] not in (1, 2): continue
            groups.setdefault((r["model"], r["mode"], r["page"]), []).append(r)
        def avg(xs): xs = [x for x in xs if x is not None]; return round(st.mean(xs), 2) if xs else None
        rows = []
        for (mk, mode, page), rs in sorted(groups.items(), key=lambda kv: (kv[0][2], kv[0][1] != "whole", -1 if kv[0][0]=="luna" else 0, kv[0][0])):
            M = [r["metrics"] for r in rs]; J = [(r.get("judge") or {}).get("scores") or {} for r in rs]
            rows.append({"page": page, "model": mk, "mode": mode, "n": len(rs), "json_ok": sum(r["json_ok"] for r in rs),
                         "cost": avg([r["cost_usd"] for r in rs]), "lat_sum": avg([r["latency_sum_s"] for r in rs]), "lat_max": avg([r["latency_max_s"] for r in rs]),
                         "in_tok": avg([r["prompt_tokens"] for r in rs]), "out_tok": avg([r["completion_tokens"] for r in rs]), "cached": avg([r["cached_tokens"] for r in rs]),
                         "items": avg([m["items"] for m in M]), "words": avg([m["words"] for m in M]),
                         "no_claim": avg([m["sentences_no_claim"] for m in M]), "bad_ids": avg([m["bad_claim_ids"] for m in M]),
                         "q_bad": avg([m["quote_violations"] for m in M]), "q_tot": avg([m["quotes_total"] for m in M]),
                         "n_bad": avg([m["numbers_not_in_payload"] for m in M]), "n_tot": avg([m["numbers_total"] for m in M]),
                         "leaks": avg([m["unsafe_leaks"] for m in M]), "off_recipe": avg([m["off_recipe"] for m in M]), "p1": avg([m["p1_coverage"] for m in M]), "useline": avg([m.get("useline_rate") for m in M]),
                         "h2_long": avg([m["h2_over_110"] for m in M]), "ids_txt": avg([m.get("ids_in_text", 0) for m in M]), "fail_secs": avg([m["failed_sections"] for m in M]), "empty_secs": avg([m["empty_sections"] for m in M]),
                         "j_faith": avg([j.get("faithfulness") for j in J]), "j_spec": avg([j.get("specificity") for j in J]), "j_act": avg([j.get("actionability") for j in J]),
                         "j_clar": avg([j.get("clarity") for j in J]), "j_struct": avg([j.get("structure") for j in J]), "j_overall": avg([j.get("overall") for j in J])})
        (ROOT / "summary.json").write_text(json.dumps(rows, indent=1))
        cols = ["page","model","mode","n","json_ok","cost","lat_sum","lat_max","in_tok","out_tok","cached","items","words","no_claim","bad_ids","q_bad","q_tot","n_bad","n_tot","leaks","off_recipe","p1","useline","h2_long","ids_txt","fail_secs","empty_secs","j_faith","j_spec","j_act","j_clar","j_struct","j_overall"]
        md = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for r in rows: md.append("| " + " | ".join("" if r[c] is None else str(r[c]) for c in cols) + " |")
        (ROOT / "summary.md").write_text("\n".join(md)); print("\n".join(md))
