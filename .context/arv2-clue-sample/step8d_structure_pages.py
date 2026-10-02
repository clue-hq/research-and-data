"""Step 8d — structure the raw page text the earlier bundle never contained.

PROCESS FINDING: rounds 8b/8c were fed the deep reports plus a hand-written digest of the
gap-fill findings — not the raw `/contents` page text. So the single richest artifact of the whole
run (the $0.004 four-page fetch, which carries the full provider roster, the three-ASC
accreditation sentence and the 2020 procedure volumes) was never structured. The structuring pass
can only structure what is in its bundle. This step feeds the raw pages and captures the remainder.
"""

import json
import os

from clue_lib import HERE, openrouter, save_raw
from step8_structure import FIELD_CATALOG, STAMPING, parse_json_content

pages = json.load(open(os.path.join(HERE, "raw", "step4_g1_own_pages.json")))
bundle = []
for res in pages.get("results") or []:
    bundle.append(f"\n=== PAGE: {res.get('url')} ===\n{(res.get('text') or '')[:9000]}")
extra = json.load(open(os.path.join(HERE, "raw", "step4b_modmed_confirm.json")))
for res in extra.get("results") or []:
    if "wanda" in (res.get("url") or "").lower():
        bundle.append(f"\n=== PAGE: {res.get('url')} ===\n{(res.get('text') or '')[:6000]}")
BUNDLE = "\n".join(bundle)

SYSTEM = f"""You convert finished research into structured claim rows for a claim store.

{FIELD_CATALOG}
{STAMPING}

OUTPUT: ONE JSON object {{"claims": [...], "proposed_fields": [...]}}.
claims[] item: {{"entity","field_key","is_proposed_field","value_json","evidence_span",
"source_url","origin","identity_binding","use_class"}} — the last two only on contact.facet.* rows.
proposed_fields[] item: {{"field_key","entity_type","value_type","value_schema","description",
"reuse_scope","why_needed"}}.

The bundle below is the RAW TEXT of pages from the practice's own website. Entity id for the
account is "account:charleston-gi-specialists"; for the CEO it is "contact:wanda-punteney".
Every claim's `origin` is "exa_cheap" (these came from cheap page fetches).

COVERAGE CHECKLIST — emit a row for each of these, one fact per row:
 - EVERY named gastroenterologist, pathologist, physician assistant and named administrative
   staff member, each as its own row carrying their name and credentials exactly as printed, and
   flagging the ones printed as "Retired".
 - The stated count of board-certified gastroenterologists on the roster page (note it differs
   from counts stated elsewhere — emit what THIS page says).
 - The statement about how many endoscopy centres the practice operates and their certification
   and licensure status.
 - EVERY figure in the "2020 Practice Statistics" block, each as its own row.
 - The referring-physician page's description of the appointment request form, and EACH named
   downloadable form.
 - The published practice phone and fax.
 - Every office/endoscopy-centre address printed in the page footer.
 - The open-access "no referral needed" scheduling statement.
 - The patient-portal name, and the CEO's title and stated year of joining from her bio page.
 - The site-wide promotional banner about colorectal cancer screening age.

RULES: never invent a fact, quote or URL; evidence_span must be text that literally appears in the
bundle; source_url is mandatory; prefer an existing catalog key, invent one only when nothing fits.
Return ONLY the JSON object, starting with '{{'. No prose, no markdown fence.
"""

resp = openrouter(
    "z-ai/glm-4.7",
    [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "RAW PAGE BUNDLE\n\n" + BUNDLE},
    ],
    label="step8d_pages",
    response_format={"type": "json_object"},
    reasoning={"enabled": False},
    max_tokens=32000,
    timeout=1500,
)
parsed, err = parse_json_content(resp)
if not parsed:
    raise SystemExit(f"failed: {err}")
save_raw("step8d_pages_parsed", parsed)
print(f"claims={len(parsed.get('claims') or [])} proposed={len(parsed.get('proposed_fields') or [])}")

merged = json.load(open(os.path.join(HERE, "structured_raw.json")))
merged["claims"].extend(parsed.get("claims") or [])
merged["proposed_fields"].extend(parsed.get("proposed_fields") or [])
json.dump(merged, open(os.path.join(HERE, "structured_raw.json"), "w"), indent=2)
print("merged total:", len(merged["claims"]))
