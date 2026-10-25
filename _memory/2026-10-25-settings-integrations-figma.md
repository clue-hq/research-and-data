# Settings Integrations Figma design — 2026-10-25

- User requested a minimal Settings → Integrations / CRM management design from their pasted brief, matching the existing Clue settings screens and tokens. Design-only work; no frontend/backend implementation.
- File `NcLl2r0dzVDN28xAQCwvM1`, page `1735:38951` (Settings-dev-ready). Added a separate section `2308:1590`; original screens untouched.
- Main frames: not connected `2308:1591`, HubSpot management `2308:1592`, Salesforce management `2308:1593`, connected overview `2308:1594`, needs-attention overview `2308:1595`.
- Supporting boards: connection/confirmation dialogs `2310:2264`; loading, expired, failed, field setup/partial/missing, member restrictions and empty permissions `2310:2463`; activity/undo/empty/filter/pagination states and design decisions `2310:2602`.
- Reused Satoshi Variable typography, existing sidebar/Button components, vector CRM logos and bound color/spacing/radius variables. Final audit: 376 editable text nodes, 177 component instances, zero horizontal overflow. Screenshots reviewed for both provider screens and all three state boards.
- Draft assumptions are labelled on the activity review board: overwrite settings owner/admin-only (provisional in brief); Fully automatic omitted; Undo sends a request to the original chat for approval. Sample records are illustrative.
- Discovery returns exceeded Figma's 48 KB output limit; compact JSON.stringify output solved this. One attempted prototype overlay reaction was rejected and rolled back; deliverable is editable static designs, not a wired prototype. Subsequent visual fixes succeeded and were verified.
- No new design variables or component definitions. No runtime changes, remote Git publication, or actual CRM actions.
