---
name: create-website
description: Use when building a website or a new section from inspected brand sources, choosing exact reuse, slot rebinding, variants, repair, raw composition, or typed authoring.
---

# Compose a website from inspected source

Read `web-source-readiness` before a new source-faithful page. Its evidence
sets the available lanes; an approved kit alone does not establish reusable
sections. For an existing page, `edit-website` owns the smallest sufficient
edit and preservation of human work.

## Learn this seller's visual grammar

Inspect representative sources with `view("cloned_section:<id>")` and
`inspect_cloned_section(fragment_id="<id>")`: the first shows pixels; the
second supplies HTML/CSS, slots and human overrides. Establish container
relationships, type hierarchy, heading measure, density, surface changes,
image purpose/crop, CTA shape and responsive rearrangement. Name the relevant
ancestor for each new band in the existing plan. A palette is not a grammar.
If preview or source is missing/truncated, state the limitation; never claim
a full-source remix from the visible prefix.

## Choose the smallest sufficient construction

| Required change | Callable path |
|---|---|
| Exact released band | `insert_cloned_section(fragment_id, index=None, slot_values_json=None)`; on an empty page, batch ordered ids through `assemble_cloned_sections(fragment_ids_json, slot_values_json=None)`. JSON arguments are strings. |
| Existing text/link/image/visibility slots suffice | Rebind the returned slot keys. On an existing pin, `web_ops(operations_json)` sets its complete kind payload; preserve other slots and human overrides. |
| Healthy band needs a structural campaign change | Pin it, then `repair_cloned_section(fragment_id, html, rung, note, css=...)` with `note="campaign variant: ..."`; read `repair-cloned-sections`. |
| A diagnosed source defect | Read `repair-cloned-sections`; prefer a suitable released repair already in that lineage. |
| Missing band, inspected sources establish its grammar | `compose_web_section(html, css, section_role="other", label=None, note="...")`, then explicitly pin the returned id. This is new composition, not captured source. |
| Deep node editing, typed components or attribute-level derivation are required | Use the [typed authoring reference](../web-source-readiness/references/authoring-vocabulary.md) before `author_web_page` / `author_web_subtree`. |

Pinning tools accept plain slot values; existing-pin `web_ops` requires the
externally tagged values in the [slot JSON reference](../edit-website/references/scoped-editing.md#slot-json-for-an-existing-fragment).
Preserve `{{account.*}}` markers inside their existing values. Personalization alone is
not a reason to discard source fragments. A whole-page `author_web_page`
replaces its page: do not use it after pinning a source skeleton or campaign
chrome, or for a local correction. Keep atomic validation, diagnostic patching,
real asset registration and existing node identity rules from the reference.

## Preserve context and campaign intent

Retain source responsive rules, inherited font/custom-property/root-unit
context, assets, image ratios and section rhythm. For new raw bands, carry the
inspected heading/body font families and roles explicitly: semantic `h1`/`h2`
tags alone do not recreate a captured display font. Compare these bands with
adjacent source typography after rendering. A literal 10px source root
and a 16px host are not interchangeable; do not change the shared host root
or arbitrarily shrink headings to hide that defect. Raw CSS still passes
custody/sanitizer boundaries; scripts and unsupported runtime behavior do not
survive merely because markup was captured.

`campaign-landing-page` owns the chrome choice. Native source navigation,
minimal campaign chrome and an explicitly authored replacement are deliberate
choices, not interchangeable fallbacks. `mint_campaign_shells()` creates
shells; inspect its returned lifecycle before `assemble_abm_page(...)`.
Draft shells cannot be pinned. Do not approve a kit or call a repair-release
tool to bypass that state. Where the brief allows alternate chrome, inherit
the seller's measured mark, spacing and button treatment and identify it as
new work. Never silently switch chrome after a refusal.

Keep one conversion intent across header, hero and closing CTA. A booking
label must lead to a real booking path, or to a supported dialog with the
same valid destination; a homepage link is not a booking flow. Preserve
legitimate secondary/legal actions. Keep operational gaps in the report.

## Render before claiming fidelity

Use the role's available review path: the director/solo agent calls
`render_web_preview()`, then views 1440/768/375 and returned state captures;
an author without that tool hands back to the director. Compare with inspected
source and real neighbors: heading hierarchy, density, contrast, crop,
responsive context and working CTAs. Load `review-website` for the full check.
Passing ingestion or clone checks is not visual acceptance. Report exact
reuse, new work, adaptation and unverified behavior separately.
