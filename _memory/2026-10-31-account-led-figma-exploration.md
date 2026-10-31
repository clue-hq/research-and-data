# Account-led work: Figma exploration — 2026-10-31

- User asked for mockups to review the revised account-led ABM/direct-mail approach. This was Figma-only work; application code, localhost, V1 and existing Figma pages were unchanged.
- Verified branch: `feat/direct-mail-infrastructure-v2`; checkout was clean before documenting this session.
- Existing Clue file: `NcLl2r0dzVDN28xAQCwvM1`. New page: **Account-led work · Exploration · Oct 31**, `2418:2`. Review guide: `2453:964`.
- Design link: https://www.figma.com/design/NcLl2r0dzVDN28xAQCwvM1/Clue?node-id=2453-964
- Prototype start: https://www.figma.com/proto/NcLl2r0dzVDN28xAQCwvM1/Clue?page-id=2418%3A2&node-id=2453-964&starting-point-node-id=2453%3A964&scaling=scale-down&content-scaling=fixed

## Screens

1. Project priorities — `2419:41`
2. Account approach and evidence — `2419:226`
3. Morgan gift and note together — `2446:155`
4. Morgan revision after feedback — `2446:355`
5. Optional recipient landing page — `2447:304`
6. Taylor gift and distinct note — `2447:479`
7. Send authorization — `2448:440`
8. Delivery and changing seller context — `2448:607`
9. Priorities across 500 accounts — `2450:559`
10. Account-wide ad — `2451:647`
11. Separate ad destination — `2451:849`

## Proposed behavior, not an implemented backend contract

- Existing account research and seller context inform an approach before gift generation. The scale scenario shows 500 researched accounts, 24 priorities and eight recipient proposals across four chosen accounts; it does not generate gifts for every account.
- Review one recipient's gift and note together. Feedback changes Morgan's gift and note, exposes the differences and applies only to Morgan. Three compact gift choices remain visible.
- A recipient page is optional. Shared ads and their account-level destinations belong to a separate advertising campaign, with explicit audience and review scope.
- Individual content review remains; two reviewed sends can receive a combined spend authorization. The example gifts cost $58/$65; complete sends cost $91/$98. This new example authorizes up to $189 total. It does not reserve funds. Budget range remains $50–$100 for gift search with a $120 gift ceiling.
- Changed recipient, destination, material version or higher total requires renewed authorization. No new automatic content-approval policy was adopted.
- Tracking distinguishes vendor ordering, Clue receipt, preparation/QC and carrier shipment. A seller update proposes holding additional outreach and preparing a meeting brief. Office delivery does not prove personal receipt.
- All research, people, prices and outcomes are illustrative. Prototype buttons connect the Snowflake story and ad previews. Chat, filters, search and other account rows are illustrative, not functioning controls. No real ordering, sending, publication or tracking integration.

## Design and verification

- Reused published Clue Button, Badge and Input components, semantic variables, Satoshi Variable text styles, the existing project header, and native editable product/ad/page artwork from the Oct 29 exploration. Caveat is used for note previews.
- Created a reusable recipient navigation component `2418:3` in the new page's component staging area, away from the screen grid.
- Initial screenshots exposed text clipping: `resize()` resets text auto-resize, and horizontal HUG containers were using the wrong axis. Corrected helper order and repaired affected new nodes. Expanded note previews and repaired badge width hugging.
- Checked all 11 product screens with screenshots and layout-bound inspection; no direct-child overflow remained in the authored containers. The guide was also visually checked. Reactions use valid frame destinations and the page has guide, recipient-flow, scale and ad starting points.
- Do not claim these mockups are deployed or replace the existing localhost implementation. Further implementation needs founder review of the design and the usual contract-gap review before backend integration.
