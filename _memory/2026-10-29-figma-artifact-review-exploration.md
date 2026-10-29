# Figma artifact review exploration — 2026-10-29

- User explicitly requested a separate page inside the existing Clue Figma file, with multiple concrete screens. This session made no application/runtime changes; v1 and localhost v2 remain unchanged.
- Verified branch: `feat/direct-mail-infrastructure-v2`; worktree was clean before this note.
- Created page **Artifact review · Exploration · Oct 29**, node `2356:2`, in file `NcLl2r0dzVDN28xAQCwvM1`.
- Page URL: https://www.figma.com/design/NcLl2r0dzVDN28xAQCwvM1/Clue?node-id=2356-2

## Screens and prototype

1. Project artifacts beside chat — `2364:766`
2. Account ad review — `2359:210`
3. Morgan gift and note — `2360:181`
4. Morgan personal page — `2361:399`
5. Ad revision comparison — `2362:566`
6. Review across 500 accounts — `2365:1037`
7. Reviewed-send cost authorization — `2366:1235`
8. Recipient shipment tracking — `2367:1304`
9. Ad's account-wide destination — `2368:1342`
10. Taylor gift and note — `2370:1640`
11. Taylor personal page — `2371:1773`

- All screens are 1680 × 1000 native editable Figma compositions, with reusable artifact and rail components. Main click paths are linked (76 navigation actions); two prototype entry flows start at the library and the scale review.
- This is a design prototype using fictional recipients, research, costs and shipment events. Clicks navigate illustrative states; they do not execute sends, model calls, live research, publishing or cost authorization. Secondary controls are design affordances, not a complete functional application.
- The walkthrough starts with library → ad → account page → Morgan gift/note → Morgan page → Taylor gift/note → Taylor page → cost → tracking. The ad also opens a two-version revision comparison. Needs review opens the scaled review.

## Decisions represented

- Library finds materials; focused review shows a thumbnail rail, one material (or the meaningful gift/note pair), and material-scoped Clue reasoning.
- Account-wide LinkedIn ad and account landing page stay distinct from personal recipient pages. Scope, campaign, version, evidence and destination stay visible.
- Two recipients have different gifts, notes, pages and rationales. Example evidence is labeled; the coffee gift does not claim an established personal preference.
- Eight individual artifacts appear as six review items because each gift/note pair is reviewed together.
- Scaled review retains the same composition and shows saved progress, held recipients and next-item actions. It does not approve unseen items automatically.
- Content approval is separate from purchasing/sending. Itemized estimates are $91 and $98; combined estimate $189, explicit maximum $240 ($120 per recipient), with further approval for excess cost. No budget reservation is shown.
- Tracking covers order → Clue receipt → preparation/quality check → shipment → in transit, plus illustrative preparation images. Office delivery and personal receipt remain distinct.

## Design and verification

- Inspected the original Projects/chat gallery frame `1339:40934` and reused its page header. Imported Clue Design System Button and Badge components, semantic color variables and the matching `sm/text-sm` style; Satoshi Variable UI, Caveat for handwriting.
- Existing Figma pages were preserved. All new compositions/components live on the new page.
- Visually checked all 11 compositions and corrected recipient thumbnails, count semantics, account-page CTA, badge sizing, selected rail states and Taylor evidence. Native layer/type/font checks found no blank text and no screenshot-image-filled UI nodes. The screens use editable text, vectors and component instances.
- Figma tool pitfalls: imported remote component/variable IDs may not resolve across calls; re-import by key. Use component properties for button text, not nested text characters. Resolve token RGBA values before binding paint on instance overrides. Prototype NAVIGATE cannot target the source's own top-level frame.
- Opened account ad review in the embedded Figma view. No backend integration or production changes were attempted.
