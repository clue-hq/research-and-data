---
name: web-source-readiness
description: Use when creating a source-faithful website, choosing captured sections, or diagnosing missing, stale, draft, degraded, or incomplete brand website sources before composition.
---

# Establish website source readiness

A brand kit is not a complete website capture. A released fragment is not a
fidelity verdict. Establish what this turn can actually reuse before choosing
how to build. Apply the same checks to any onboarded brand; never depend on a
named brand pack or an evaluation snapshot being in the live library.

Reuse already-returned inventory and inspected source within the current scope.
When differently phrased searches return the same fragment IDs, stop broad
searching and inspect the relevant candidates; that is no new evidence. Paginate
when the tool reports unseen results, and refresh only for a specific missing
source or changed version. Do not confuse necessary pagination with duplicate work.

## Read, classify, then choose

Retrieve in task order, not catalog order. If the request selects a component,
inspect that exact source/current pin first. For missing material, search by the
section's job and use returned page URLs to inspect relevant product, use-case
or customer-story sources; do not assume the homepage covers those roles.
Reuse source content already returned. Keep original captures distinct from
previous generated campaign variants, whose wording and design need rechecking.

1. Read `view("brand")` and `view("doc")`. Name the selected seller kit/version
   when exposed and the requested page purpose. Keep the target account's
   identity separate from the seller's visual system.
2. Reuse relevant source/keeper inventory already supplied. When absent, start
   with `search_cloned_sections(q="", limit=8)`. Use narrower role/query or
   known-page reads only for missing planned bands. Follow `next_offset` as `offset` with the same
   q/role/page_url when unseen matches matter; null ends that result set.
   `page_url` filters by an exact returned page URL, including query parameters;
   associated derivatives remain eligible. Check `inventory_truncated` and
   `inventory_note`: the registry can cap the scanned inventory separately from
   the result page. Changing search words cannot reveal rows outside that cap.
   Restart at offset 0 after a library change. Search lists released sections
   only: zero results means no matching reusable result, not no source page
   or no capture drafts.
3. For candidates, use `view("cloned_section:<returned id>")` for pixels and
   `inspect_cloned_section(fragment_id="<returned id>")` for HTML, CSS, slots,
   lineage and human text overrides. For more source, pass the returned
   `html_next_offset` / `css_next_offset` as `html_offset` / `css_offset`.
   Each stream is capped at 12,000 characters; null means finished. Pass a
   stream's total (`html_chars` / `css_chars`) to skip it while reading the other.
   Missing previews and unread source remain evidence gaps; do not claim to
   have inspected missing bytes. Pagination supplies inspection, not a targeted
   attribute-edit capability; use the repair skill to assess that separate limit.
   For copy-only work, inspect slots or paged `text_only=True` inventory instead
   of filling context with complete stylesheets. Complete HTML/CSS is required
   when actually changing structure. Read resolved layout evidence for a type
   mismatch; inspecting more unrelated pages cannot establish the missing face.
4. Check source provenance, kit association, capture time when available,
   required page/section coverage, dependency availability and rendered
   behavior separately. Record unknown fields as unknown. Use the
   [readiness reference](references/readiness.md) for version decisions,
   observed-link discovery and acquisition handoff.
5. Put one compact source decision in the existing page plan: chosen source
   ids/URLs, known kit/version, readiness by required band, relevant asset or
   behavior gaps, and the next action. Do not dump the catalog or create a
   second plan. Separate exact pin, slot rebind, campaign variant, defect
   repair and new composition as `create-website` describes.
   Tie each requested property to the source that establishes it: section/role
   and measured type/layout, asset/rendition, observed state, or named missing
   dependency. A catalog count or a list of URLs is not usable design evidence.

## Decide without overstating readiness

| Evidence | Action |
|---|---|
| Suitable released source, inspected and usable for this placement | Pin/rebind; still verify the assembled page. |
| Suitable source with a bounded visible defect | Diagnose; use `repair-cloned-sections` if supported. |
| Healthy source needs structural campaign changes | Derive a named campaign variant, preserving source grammar. |
| Required source is draft, absent, unreadable or missing dependencies | State the exact gap and hand acquisition/review to its real owner. Continue only the portions supported by evidence. |
| A new band is required and inspected sources establish its grammar | Compose it as new work; keep its provenance distinct from captures. |

Do not blanket-approve drafts, re-label a composed band as captured, bypass a
custody refusal, or turn missing original media into invented "originals."
Text fetched by `fetch_page` can ground copy and reveal links; it does not
capture a rendered website. A React-rendered typed WebDoc is editable platform
output, not recovered original React source. Captured CSS animation, saved
video, and canvas presence do not establish recovered JS/WebGL behavior.
