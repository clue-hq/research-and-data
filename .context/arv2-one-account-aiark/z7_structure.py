"""Z7 — structure the narrative sources into closed-field-key claims (one call, gpt-5-mini).

Deterministic provider facts (AI Ark, Ashby, emails, Gemini usage) are NOT sent to the model —
they are assembled in code in z8. This call only converts prose (Exa deep report, own-site text,
Gemini transcripts) into claims with VERBATIM evidence spans.
"""
import json, os, sys, time
sys.path.insert(0, ".")
import z_lib as C  # noqa: E402
sys.path.insert(0, os.path.abspath(os.path.join("..", "arv2-smoke-cluehq")))
import field_catalog as F  # noqa: E402

deep = open("report_account_zafran_deep.md").read()
own = json.load(open("raw/z2_own_site.json"))
own_text = "\n\n".join(f"### {r.get('url')}\n{(r.get('text') or '')[:5000]}"
                       for r in (own.get("results") or []))
tr_sanaz = open("transcripts/sanaz_boardroom.md").read()
tr_nick1 = open("transcripts/nick_supporting_cc.md").read()
tr_nick2 = open("transcripts/nick_moscow_mule.md").read()
pulse = [x for x in json.load(open("z3_media_resolve.json"))["identity_binding"]]

BUNDLE = f"""=== SOURCE A: Exa deep-reasoning dossier (2026-09-02) ===
{deep}

=== SOURCE B: zafran.io own-site pages (Exa /contents livecrawl 2026-09-02) ===
{own_text}

=== SOURCE C: Gemini transcript — Sanaz Yashar on the Boardroom Club podcast (42:49),
source https://podcasters.spotify.com/pod/show/boardroomclub/episodes/AI-Summit-Sanaz-Yashar--Co-Founder-and-CEO-at-Zafran-Security-e36d9ai ===
{tr_sanaz[:26000]}

=== SOURCE D: Gemini transcript — Nick Fisher, "Supporting Cocktail Chemistry" (01:31),
source https://www.youtube.com/watch?v=8_YWBtq4eic ===
{tr_nick1}

=== SOURCE E: Gemini transcript — Cocktail Chemistry "Perfect Moscow Mule" (04:14),
source https://www.youtube.com/watch?v=avcD5WVLCYs ===
{tr_nick2}

=== SOURCE F: Nick Fisher's own LinkedIn article "Why I joined Zafran Security",
source https://www.linkedin.com/pulse/why-i-joined-zafran-security-nick-fisher-jqinf ===
{(pulse[1]['text'] if len(pulse) > 1 else '')[:3000]}
"""

CATALOG = ("ACCOUNT FIELD KEYS:\n" + "\n".join(f"  {k} — {v[2]}" for k, v in F.ACCOUNT_FIELDS.items())
           + "\n\nCONTACT FIELD KEYS:\n" + "\n".join(f"  {k} — {v[2]}" for k, v in F.CONTACT_FIELDS.items())
           + "\n\nCONTACT FACET (personal) FIELD KEYS:\n"
           + "\n".join(f"  {k} — {v[2]}" for k, v in F.FACET_FIELDS.items()))

SYS = """You convert research prose into typed claims. You NEVER invent anything.

HARD RULES
  * `evidence_span` MUST be a VERBATIM substring copied from the bundle. If you cannot copy an
    exact span, do not emit the claim.
  * Only use field keys from the supplied catalog. Anything that does not fit goes in
    `proposed_fields` with a suggested key name — never force it into a wrong key.
  * `outreach_safe` is false for: anything about the Cisco acquisition rumour, anything about a
    person's origin/nationality/religion/family/children, anything negative about the company
    (ARR shortfalls, burn, founder departure, competitive criticism), and anything you would not
    say out loud to the person in a first email. These may still be recorded as claims — they are
    just not outreach material.
  * `use_class` is one of: business_public, professional_public, personal_public_self_stated,
    sensitive_excluded.
  * Never record a birth date, age, health, religion, political view, or family/children detail.
  * A person's own words from a transcript are `personal_public_self_stated` when about their life
    and `professional_public` when about their work.
  * If a source is a third-party report rather than the company, say so in `source_kind`."""

USER = f"""{CATALOG}

Return STRICT JSON:
{{
 "account_claims": [{{"field_key": "...", "value": <json>, "evidence_span": "<verbatim>",
    "source_url": "...", "source_kind": "company_primary|third_party_press|job_posting|
    transcript_self|provider_database|analyst_estimate", "confidence": "high|medium|low",
    "use_class": "...", "outreach_safe": true|false}}],
 "contact_claims": [{{"person": "Sanaz Yashar|Nick Fisher|Vari Kaur|Tom Anthony|Ben Seri",
    "field_key": "...", "value": <json>, "evidence_span": "<verbatim>", "source_url": "...",
    "source_kind": "...", "confidence": "...", "use_class": "...", "outreach_safe": true|false,
    "media_timestamp": "MM:SS or null"}}],
 "proposed_fields": [{{"suggested_key": "...", "why": "...", "value": <json>,
    "evidence_span": "<verbatim>", "source_url": "..."}}],
 "negatives_and_risks": [{{"what": "...", "status": "REFUTED|UNRESOLVED|CONFIRMED",
    "evidence_span": "<verbatim>", "source_url": "...", "outreach_safe": false}}]
}}

Be thorough: aim for 25-40 account claims and 20-35 contact claims. Every voice quote from a
transcript MUST carry its media_timestamp.

BUNDLE:
{BUNDLE}"""

t0 = time.time()
out = C.openrouter("openai/gpt-5-mini",
                   [{"role": "system", "content": SYS}, {"role": "user", "content": USER}],
                   label="z7_structure", reasoning={"effort": "minimal"},
                   response_format={"type": "json_object"}, max_tokens=32000)
txt = ((out.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
try:
    data = json.loads(txt)
except Exception as e:
    print("PARSE FAIL", e); print(txt[:1500]); sys.exit(1)
json.dump(data, open("z7_structured.json", "w"), indent=2)
print(f"  account_claims={len(data.get('account_claims') or [])} "
      f"contact_claims={len(data.get('contact_claims') or [])} "
      f"proposed={len(data.get('proposed_fields') or [])} "
      f"negatives={len(data.get('negatives_and_risks') or [])}")
C.timing_record("Z7_structure", time.time() - t0, "one gpt-5-mini call")
print(f"Z7 {round(time.time()-t0,1)}s spend={C.total_spend()}")
