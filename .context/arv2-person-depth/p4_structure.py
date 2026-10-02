"""Phase 4 — structure into claims_people.json, ONE PERSON PER CALL (openai/gpt-5-mini,
reasoning minimal, closed field-key list). The model EXTRACTS and TYPES; it never invents.
The depth score is computed deterministically in python from the emitted rows, not asked for.
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p_lib as C  # noqa: E402
from roster import PEOPLE  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TR = os.path.join(HERE, "transcripts")
MODEL = "openai/gpt-5-mini"
REASONING = {"effort": "minimal"}

EXISTING_KEYS = [
    "contact.facet.career_history", "contact.facet.alma_mater", "contact.facet.stated_interests",
    "contact.facet.communication_style", "contact.facet.public_appearances",
    "contact.facet.publications", "contact.facet.recent_post", "contact.facet.nickname",
    "contact.facet.hobby", "contact.facet.recent_award", "contact.facet.conference_talk",
    "contact.facet.causes",
]
PROPOSED_KEYS = ["contact.facet.hooks", "contact.facet.openers", "contact.facet.voice_quote"]
ALL_KEYS = EXISTING_KEYS + PROPOSED_KEYS

CATEGORIES = ["background", "life_outside_work", "voice", "professional_identity",
              "unique_insight", "opener"]

SYS = """You convert a researched personal dossier into typed, evidence-bound claim rows.

HARD RULES
- You EXTRACT. You never invent, infer, summarise-into-a-new-fact, or soften a "NOT FOUND".
- Every row MUST carry a verbatim `evidence_quote` copied EXACTLY from the supplied material and
  a `source_url` that appears in the supplied material. If you cannot copy an exact quote, DROP
  the row. A short dossier producing 4 rows is correct; padding it to 20 is a failure.
- QUOTE PROVENANCE: the dossier NARRATES around quotations. Always copy the INNERMOST quoted
  string — the words the subject or the source actually wrote/said — never the dossier's own
  narration about them. If the dossier says: The profile states "I specialize in full-funnel
  strategy" — your evidence_quote is `I specialize in full-funnel strategy`, NOT the sentence
  beginning "The profile states". If the only available text is narration, DROP the row.
- Prefer quotes from MATERIAL 2 (LinkedIn) and MATERIAL 3 (transcripts), which are primary text,
  over MATERIAL 1 (the dossier), which is second-hand.
- `field_key` MUST come from the closed list. Nothing else is permitted.
- SENSITIVITY FLOOR (hard): never emit a row touching health, faith, politics, sexuality, gender
  identity, family tragedy, minors, union membership, or criminal/legal matters. Drop it silently.
- If the dossier tagged a line "[ORIGIN - NOT AN OUTREACH HOOK]", you MAY emit it as a
  `background` row but you MUST set `outreach_safe` to false. Never build an opener from it.
- `contact.facet.voice_quote` rows are ONLY for long-form spoken/authored material (podcast,
  video, talk, interview, authored article). A LinkedIn post is `contact.facet.recent_post`.
- `contact.facet.openers` rows: `value` is the opener sentence; `evidence_quote` is the verbatim
  hook it is built on; every opener must be usable as the first line of a cold message.
- Priority: P1 = specific, personal, recent, verbatim, usable in outreach right now.
  P2 = solid and specific but generic-ish or older. P3 = weak, background-only, or company-level.
- use_class: "professional-public" for work identity/voice/appearances; else
  "personal-public-non-sensitive". identity_binding is always "STRONG" (identity is pre-locked).
"""

USER = """SUBJECT (identity already locked, do not re-derive):
  name: {name}{alias}
  title: {title}
  company: {company} ({domain})
  linkedin: {linkedin}

CLOSED FIELD-KEY LIST — use ONLY these:
{keys}

CHARTER CATEGORIES for `charter_category`: {cats}

Return STRICT JSON, no prose, shaped exactly:
{{
  "claims": [
    {{"field_key": "<one of the closed list>",
      "value": <string, or array of strings, or object — whatever suits the field>,
      "evidence_quote": "<VERBATIM, copied exactly from the material below>",
      "source_url": "<a URL that appears in the material>",
      "source_timestamp": "<MM:SS or null>",
      "source_type": "<linkedin_profile|linkedin_post|youtube_transcript|podcast_transcript|podcast_shownotes|press|company_site|university|blog|directory|other>",
      "charter_category": "<one of the charter categories>",
      "priority": "P1|P2|P3",
      "use_class": "professional-public|personal-public-non-sensitive",
      "identity_binding": "STRONG",
      "outreach_safe": true,
      "note": "<optional short caveat, or empty>"}}
  ],
  "unique_insight": {{"text": "<one paragraph, or 'NOT FOUND — thin public footprint'>",
                      "evidence_quote": "<verbatim or empty>", "source_url": "<or empty>"}},
  "not_found": ["<charter category or sub-item that came back empty>", "..."],
  "same_name_contamination": ["<url — why it was ruled out>", "..."]
}}

=== MATERIAL 1: DEEP-RESEARCH DOSSIER (Exa deep-reasoning, personal charter) ===
{dossier}

=== MATERIAL 2: LINKEDIN PROFILE (indexed copy) ===
{linkedin_text}

=== MATERIAL 3: LONG-FORM MEDIA TRANSCRIPTS (where this person verifiably speaks) ===
{transcripts}

=== MATERIAL 4: CONFIRMED SOURCE URLS FROM THE SWEEP ===
{urls}
"""


def load_transcripts(key, media):
    chunks = []
    for it in media["items"]:
        if it["person"] != key:
            continue
        if str(it.get("target_speaks", "")).startswith(("NO", "UNKNOWN")):
            continue
        for suffix in ("_exa_page.txt", "_shownotes.txt"):
            fn = os.path.join(TR, it["id"] + suffix)
            if os.path.exists(fn):
                t = open(fn).read()
                body = t.split("\n\n", 1)[1] if "\n\n" in t else t
                chunks.append(f"--- MEDIA {it['id']} | {it.get('title')} | {it['url']} | "
                              f"{it.get('duration_s')}s | NOTE: this source has NO timestamps "
                              f"(YouTube caption endpoint is blocked; text came from Exa's index) ---\n"
                              + body[:38000])
                break
    # the EP265 youtube mirror carries Alastair's transcript under a different id
    if key == "alastair_paterson":
        fn = os.path.join(TR, "ala_gcsp265_yt_exa_page.txt")
        if os.path.exists(fn):
            t = open(fn).read()
            chunks.append("--- MEDIA ala_gcsp265 (YouTube mirror) | Cloud Security Podcast by "
                          "Google EP265 | https://www.youtube.com/watch?v=qu51DBOkrNE | 1734s | "
                          "NO timestamps ---\n" + (t.split("\n\n", 1)[1] if "\n\n" in t else t)[:38000])
    return "\n\n".join(chunks) or "NONE — no long-form media in which this person verifiably speaks was located."


def urls_block(key, triage):
    t = triage.get(key) or {}
    rows = [f"- {r['url']} ({(r.get('title') or '')[:80]})" for r in (t.get("strong_hits") or [])[:25]]
    return "\n".join(rows) or "NONE"


DEPTH_WEIGHTS = {"background": 20, "life_outside_work": 20, "voice": 25,
                 "professional_identity": 15, "unique_insight": 10, "opener": 10}


def depth_score(claims, unique_insight):
    """0-100 = category coverage x evidence quality. Deterministic, computed here."""
    detail = {}
    total = 0.0
    for cat, w in DEPTH_WEIGHTS.items():
        rows = [c for c in claims if c.get("charter_category") == cat]
        if cat == "unique_insight":
            txt = (unique_insight or {}).get("text") or ""
            got = bool(txt) and not txt.upper().startswith("NOT FOUND")
            q = 1.0 if (unique_insight or {}).get("evidence_quote") else 0.5
            sc = w * (1.0 if got else 0.0) * q
            detail[cat] = {"rows": 1 if got else 0, "score": round(sc, 1), "max": w}
            total += sc
            continue
        n = len(rows)
        # coverage: 0 rows -> 0; 1 -> .45; 2 -> .70; 3 -> .85; 4 -> .95; 5+ -> 1.0
        cov = [0, .45, .70, .85, .95, 1.0][min(n, 5)]
        p1 = sum(1 for r in rows if r.get("priority") == "P1")
        quoted = sum(1 for r in rows if len(r.get("evidence_quote") or "") >= 25)
        qual = 0.6 + 0.25 * (p1 / n if n else 0) + 0.15 * (quoted / n if n else 0)
        sc = w * cov * min(qual, 1.0)
        detail[cat] = {"rows": n, "p1": p1, "coverage": cov, "quality": round(min(qual, 1.0), 2),
                       "score": round(sc, 1), "max": w}
        total += sc
    return round(total, 1), detail


def one(p, media, triage, linkedin):
    key = p["key"]
    dossier = open(os.path.join(HERE, f"person_{key}.md")).read()
    user = USER.format(
        name=p["name"], alias=(f" (aka {', '.join(p['aliases'])})" if p["aliases"] else ""),
        title=p["title"], company=p["company"], domain=p["domain"], linkedin=p["linkedin"],
        keys="\n".join(f"  {k}" + ("   [PROPOSED — new field]" if k in PROPOSED_KEYS else "")
                       for k in ALL_KEYS),
        cats=", ".join(CATEGORIES),
        dossier=dossier[:40000],
        linkedin_text=(linkedin.get(key) or {}).get("text", "")[:9000],
        transcripts=load_transcripts(key, media),
        urls=urls_block(key, triage))
    open(os.path.join(HERE, f"structuring_bundle_{key}.txt"), "w").write(user)
    t0 = time.time()
    resp = C.openrouter(MODEL, [{"role": "system", "content": SYS},
                                {"role": "user", "content": user}],
                        label=f"p4_struct_{key}", response_format={"type": "json_object"},
                        timeout=900, reasoning=REASONING)
    txt = (((resp.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    try:
        obj = json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, re.S)
        obj = json.loads(m.group(0)) if m else {"claims": [], "_parse_error": txt[:2000]}
    claims = obj.get("claims") or []
    for c in claims:
        c["person_key"] = key
        c["person_name"] = p["name"]
        c["company"] = p["company"]
        c["identity_binding"] = "STRONG"
        c.setdefault("outreach_safe", True)
    score, detail = depth_score(claims, obj.get("unique_insight"))
    C.timing_record(f"P4_struct_{key}", time.time() - t0, "gpt-5-mini, one person")
    return {"person_key": key, "person_name": p["name"], "title": p["title"],
            "company": p["company"], "linkedin": p["linkedin"],
            "claims": claims, "unique_insight": obj.get("unique_insight"),
            "not_found": obj.get("not_found") or [],
            "same_name_contamination": obj.get("same_name_contamination") or [],
            "depth_score": score, "depth_detail": detail,
            "n_claims": len(claims),
            "n_p1": sum(1 for c in claims if c.get("priority") == "P1")}


def main():
    only = sys.argv[1:] or [p["key"] for p in PEOPLE]
    media = json.load(open(os.path.join(HERE, "media_index.json")))
    triage = json.load(open(os.path.join(HERE, "sweep_triage.json")))
    linkedin = json.load(open(os.path.join(HERE, "linkedin_indexed.json")))
    path = os.path.join(HERE, "claims_people.json")
    existing = json.load(open(path)) if os.path.exists(path) else {"people": {}}
    t0 = time.time()
    for p in PEOPLE:
        if p["key"] not in only:
            continue
        print(f"\n== {p['key']}")
        try:
            existing.setdefault("people", {})[p["key"]] = one(p, media, triage, linkedin)
            r = existing["people"][p["key"]]
            print(f"   claims={r['n_claims']} p1={r['n_p1']} depth={r['depth_score']}")
        except Exception as e:  # noqa: BLE001
            print(f"   !! FAILED {type(e).__name__}: {e}")
        json.dump(existing, open(path, "w"), indent=2)
    el = time.time() - t0
    C.timing_record("P4_TOTAL", el, f"{len(only)} gpt-5-mini structuring calls")
    print(f"\nPhase 4 {el:.1f}s spend=${C.total_spend()}")


if __name__ == "__main__":
    main()
