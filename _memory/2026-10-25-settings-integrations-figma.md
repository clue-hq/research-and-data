# Settings Integrations Figma design — 2026-10-25

- User requested a minimal Settings → Integrations / CRM management design from their pasted brief, matching the existing Clue settings screens and tokens. Design-only work; no frontend/backend implementation.
- File `NcLl2r0dzVDN28xAQCwvM1`, page `1735:38951` (Settings-dev-ready). Added a separate section `2308:1590`; original screens untouched.
- Main frames: not connected `2308:1591`, HubSpot management `2308:1592`, Salesforce management `2308:1593`, connected overview `2308:1594`, needs-attention overview `2308:1595`.
- Supporting boards: connection/confirmation dialogs `2310:2264`; loading, expired, failed, field setup/partial/missing, member restrictions and empty permissions `2310:2463`; activity/undo/empty/filter/pagination states and design decisions `2310:2602`.
- Reused Satoshi Variable typography, existing sidebar/Button components, vector CRM logos and bound color/spacing/radius variables. Final audit: 376 editable text nodes, 177 component instances, zero horizontal overflow. Screenshots reviewed for both provider screens and all three state boards.
- Draft assumptions are labelled on the activity review board: overwrite settings owner/admin-only (provisional in brief); Fully automatic omitted; Undo sends a request to the original chat for approval. Sample records are illustrative.
- Discovery returns exceeded Figma's 48 KB output limit; compact JSON.stringify output solved this. One attempted prototype overlay reaction was rejected and rolled back; deliverable is editable static designs, not a wired prototype. Subsequent visual fixes succeeded and were verified.
- No new design variables or component definitions. No runtime changes, remote Git publication, or actual CRM actions.

## Field clarity follow-up
- User found the unlabelled right-hand Company/Contact labels confusing: they read like field values. Replaced both provider cards with explicit record groups and short explanations/examples; renamed the heading to Clue fields in the provider and the status to Ready.
- Verified the actual field registry and R-13.2: company research link and contact profile link are distinct fields. Both designs now show four fields: tier, company research link, committee role, contact link. Corrected the partial-setup state too.
- Rechecked card screenshots, fixed the longer heading wrapping, resized the full screens/sidebar, and checked horizontal overflow (none). No runtime code changes.

## Activity deferred; state placement clarified
- Founder removed What Clue changed from the current design scope, including the entire 08 Activity & undo states board. Deleted both provider activity cards and their undo footnotes, removed board `2310:2602`, and resized the CRM screens to 1396/1428 px high.
- Clarified review captions: board 06 contains modal dialogs; board 07 contains inline replacement states, except the Set up Clue's fields confirmation modal. These are static editable designs, not a wired prototype.
- Reviewed updated HubSpot page and board 07 screenshots; no activity/undo UI remnants or horizontal overflow remain in the section. No runtime changes.

## Agent-led CRM preparation revision
- Founder approved replacing field diagnostics with the agent's progress and user decisions: Clue performs setup; owners/admins authorize it in chat. Main provider cards (`2309:1950`, `2309:2323`) are now compact Research in HubSpot/Salesforce summaries with View details.
- Board 07 (`2310:2463`) renamed Connection & agent setup states. Preserved linked card IDs: `2310:2501` approval needed (Review request), `2310:2518` preparing, `2310:2535` field deleted (Ask Clue to restore), `2310:2591` could not finish (Ask Clue to retry). Added permission-blocked card `2338:2403`; member view explains pending owner/admin approval and offers read-only details.
- Removed standalone setup confirmation modal `2310:2569`. Review/retry/restore actions are specified to open the relevant chat; View details expands inline, without field configuration controls.
- Expanded details examples: HubSpot ready `2338:2427`, HubSpot permission blocked `2338:2477`, Salesforce ready `2338:2538`. Explain field purposes, creation progress, blocker/recovery when applicable, and where fields appear. Field creation does not populate records. Company fit mapping is explicit: High/Medium/Low -> Tier 1/2/3; absent fit -> no tier write. Preserved the founder's shift toward fit language in permissions/revoke copy.
- Screenshot QA: full HubSpot and Salesforce pages, preparing/approval cards, and expanded blocked/ready details. Final audit: zero horizontal overflow, zero old Repair/Partly set up/manual setup copy, all text Satoshi Variable; 324 text nodes and 157 component instances in section. Static editable designs only; no runtime implementation. Activity remains removed.
