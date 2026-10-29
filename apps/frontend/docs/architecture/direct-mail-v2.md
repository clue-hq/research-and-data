# Project materials V2

Status: recipient-first walkthrough implemented 2026-10-27 after founder approval. Local frontend preview on port 5001, branch `feat/direct-mail-infrastructure-v2`; V1 code, data and port 5000 are unchanged. This implementation is ready for product review, not a claim of live backend integration or final design acceptance. No orders, payments, agent runs or publishing execute. Email belongs to its separate branch.

## Current project artifact library — 2026-10-28

This revision supersedes the older Gallery navigation below. The chat tab is **Artifacts**, with **Project artifacts** as its heading. Direct Mail retains its sending/tracking workspace; Account → Artifacts retains its library across campaigns. V1 remains unchanged.

- The project library shows generated material across this project's campaigns and chats. Its default grid groups landing pages, ads, gifts, cards/notes and native documents. At scale it shows up to four previews per type; View all opens paginated results (24 per page). Account, campaign, material type and search share one filter bar.
- Needs review groups gift/card/page/cost by **recipient send**, with one explicit decision per send. Only individually reviewed, current revisions can be selected for bulk approval. Separate ads and standalone pages have their own content approval. Neither content approval nor send approval implies delivery, publication or ad launch.
- Target accounts keeps actual project membership and research data. Its Artifacts column uses the same native-plus-generated feed as the library, with type badges and material counts. Selecting it clears stale material/filter state and opens that account's project materials. The hard-coded 500-researched banner and hidden one-campaign restriction are removed. The sample project currently has 1007 accounts; Field conversations is one 500-account campaign within it.
- Native design files and project documents are in this library and open their existing editors. No separate Files or Earlier campaigns entrance is needed in chat. Historical campaign work is available through the campaign filter.
- Preview and review remain beside chat. The library stays mounted; explicit Back restores its filter/search/scroll context. The expand control uses the existing shell.

### Frontend replacement seam

`buildProjectLibrary` reuses `buildAccountLibrary` over project-scoped canonical mailers, pages and creatives, and merges the normalized native `projectGalleryItems` feed. `summarizeAccountMaterials` reads that same feed for table counts. These are read projections, not a new store of gifts/notes/pages.

`useArtifactLibrary` owns URL filtering and preview state. `libraryFilterPatch` resets pagination only when a filter changes. `useLibraryApproval` holds explicit ID/revision snapshots for the existing DirectMailRepository approval command. Content approval uses WorkspaceRepository.approveContent with a pinned ID/version, retains the approved copy/version, and broadcasts to all library views. Presentation components remain transport-free.

This remains an isolated frontend demo: paginated rendering is implemented, server pagination is not. Aryan should replace full-state local reads with scoped paginated repository queries, enforce identity/version/permissions on the server, and reconcile the proposed content approval command before live integration. No endpoint or production contract has been changed.

The visible tab changed; `surface=gallery` remains the compatible internal pane key. New library state uses `material`, `materialsAccount`, `campaign`, `type`, `libraryRecipient`, `libraryStatus`, `librarySearch`, `libraryPage`, `view`, `libraryReview` and `review`. Legacy catalog switches no longer choose a different project library. Unknown material IDs show an unavailable state.

## Current recipient walkthrough — 2026-10-27

The additive **Field conversations** campaign has 500 accounts and 1,000 fictional recipients. Snowflake has Morgan Lee (review) and Taylor Reed (in transit). Existing drafts, approvals and earlier campaigns are retained.

- Start in the native project chat and Target Accounts grid. Its campaign scope contains 500 researched sample accounts. The Artifacts column opens two recipient sets; company names still open account research. The original owner filters, column controls and paging remain available.
- Gallery, account Artifacts, global Artifacts and Direct Mail use the same `MaterialsBrowser` and `OutreachReview`. Choose an account, then a recipient. Gift, physical card/note, recipient page, exact cost and tracking stay in that context.
- Review three gifts, choose card/handwriting, edit the note and sender, preview/edit the page, mark its current version reviewed, then confirm address and itemized cost. Individual review can mark a send ready for bulk approval. The bulk dialog lists only the selected, individually reviewed sends.
- Approval preserves the gift, note, card/font, address, cost limit and page version. It starts at Approved; it does not invent order/shipping events. Taylor's separate seeded shipment shows inbound receipt, preparation evidence, outbound tracking, and QR readiness, explicitly as illustrative events.
- The shared queue renders 25 accounts per page with search and status filters. Native Target Accounts keeps 25/50/100 paging. Neither mode expands thousands of artifacts by default.
- Earlier campaigns are a separate legacy catalog and exclude walkthrough mailers. Shared ads remain account-scoped there. This focused campaign does not implement new ad or email authoring. Native files/documents keep their existing editors.

### Current local data and routing seam

`walkthrough.fixture.ts` adds the campaign idempotently. `account-materials/model/outreach.ts` projects the canonical mailers into account rows. Versioned current pages live once in `DirectMailState.pages`; a mailer references `pageId`, and an approval stores an immutable page snapshot. Page edit/review/invalidation commands run through `DirectMailRepository` and the atomic IndexedDB store. See the frontend proposal in `docs/api-contracts/direct-mail.md` before backend integration.

Preview-only query keys are `materialsAccount`, `recipient` (mailer id), `review` (gift/note/page/review/tracking), `q`, `status`, `p`, and `catalog` (files/earlier). The canonical pane remains `surface=gallery`; no `?artifact=` route is introduced. Explicit native-table entry replaces the selected account and clears stale recipient/tab/catalog keys. V2-only pane navigation uses Next's native history integration to avoid competing asynchronous query writes.

Mailer draft recovery remains in its existing per-tab store. Page edits have a separate version-bound per-tab buffer; Save/Discard is required before leaving the page tab or approving cost, and revisiting a recipient restores the buffer. Starting edits invalidates shared review so another view cannot bulk-approve stale readiness. Publishing and QR assignment remain separate fulfillment steps.

### Verification

50 relevant model/repository regression tests pass, covering 500-account identity, page version boundaries, legacy preservation, explicit account routing and draft recovery. Token build, lint (0 errors; 11 existing warnings) and production webpack build passed. Browser QA verified card/page review, persisted page editing, itemized $98 demo approval to tracking, 25-row paging of 500 accounts, account switching/reload, and Taylor's two delivery legs. A fresh reviewer identified three important issues; all were fixed and rechecked. V1 worktree remained clean. Full repository raw `tsc` includes pre-existing test-source errors outside this change; the configured production build and its TypeScript gate passed.

## Previous implementation and audit record

The sections below describe the earlier implementation and the audit that led to the approved focused walkthrough. Where they differ, the current walkthrough above governs.

## Entry and customer flow

Start at `/projects/10m-landing-page-campaign/chats/thread-primary?surface=target-accounts`. The former `/plan` route redirects here. The original Clue Target Accounts grid has an optional Artifacts column. Company names still open account research; Artifacts opens Gallery scoped to that account. The table stays mounted, preserving search, filters, selection, page and scroll.

Gallery reuses Direct Mail's table, typography, controls and its actual `MailerReview` and `MailerTracking` components. Choose a recipient, then review the three gifts, card/handwriting, note, address and itemized cost. Explicit confirmation writes the canonical mailer approval; its same view becomes tracking. Actual shipping events are never synthesized by approval.

Account-level ads and separate recipient landing pages sit beside gifts and notes. Scope is explicit in each row. A recipient filter retains account-wide creative and excludes another recipient's material. A page has its own version; editing the note does not increment the page. Pages/ads are previews and are not published/launched. Card QR assignment and verification remain fulfillment work.

Project chat has a compact materials handoff. Account Artifacts and global Artifacts use the same browser and canonical records. Existing design files/documents remain accessible through their original viewer/editor. Account owner and actual prepared sender are distinct.

## Data seam for Aryan

`features/account-materials/model/materials.ts` is a pure UI read projection over workspace creative and Direct Mail state. It never copies note bodies or writes approvals. Material identity is `gift:<mailerId>`, `note:<mailerId>` or the creative ID, with project/account/contact scoping. `queryMaterials` filters and renders at most 25 rows. Existing Target Accounts retains its 25/50/100 paging.

`features/account-materials/data/materials.fixture.ts` adds one existing Snowflake identity, two fictional recipients and their assets to saved V2 data without replacing original drafts/approvals. Other catalog rows include research-pending scale fixtures, with no invented findings. `account-preview.fixture.ts` provides honest blank/sample account details for preview navigation. No training corpus copied.

Preview is enabled only by the existing fail-closed `isFrontendPreviewMode` gate and providers. Live account and design HTTP contracts are unchanged. The optional Accounts column is enabled only by the V2 composition. Browser IndexedDB stores remain `clue-orchestration-preview-v2` and `clue-direct-mail-preview-v2`; transactions and cross-tab notifications are unchanged.

For integration, provide account/contact-scoped creative reads and a real Direct Mail repository behind these seams. Keep presentation transport-free. Review API contracts before enabling this for live workspaces. Server pagination, creative approvals/publication, real fulfillment events, territory routing and agent execution are not claimed by this preview.

## Preview links

Canonical pane remains `?surface=gallery`. Optional frontend-preview query parameters `materialsAccount=<accountId>` and `material=<materialId>` initialize the shared browser; they do not change the design artifact URL contract, use `?artifact=`, or authorize backend integration. Unknown/out-of-scope materials show an unavailable state.


## Product and visual audit — 2026-10-26

**Decision boundary:** audit and discussion only. No application code, fixtures, approvals, orders, publishing, or runtime configuration changed during this review. The founder confirmed the proposed review unit: **open an account, then review each recipient’s complete outreach together; shared ads remain at account level; individual artifacts remain searchable.** This confirmation does not approve the rest of the redesign or authorize backend integration.

Reviewed branch `feat/direct-mail-infrastructure-v2`, implementation commit `24a91e8de`, localhost:5001. V1 remains separate. The previous green build/tests established technical behavior, not product coherence; they do not override the findings below.

### Method and evidence

Pass 1 inspected active screens in the browser, their rendered text/layout, and the components/models behind them. Pass 2 followed account → materials → recipient → related asset → tracking, then tested reload, alternative entry points, full-width versus split chat, and scale assumptions. The comparison baseline is Clue’s existing Accounts table/shell and resolved design-system package, not a new visual theme.

Browser observations used a 1164 × 655 viewport, both split and expanded work pane. Twenty-three local evidence captures are in `/Users/shashank/.codex/visualizations/2026/10/25/01a170c0-6670-70b0-98f0-99bf1fea01a9/direct-mail-audit/`. Screenshots are not copied into the repository. This was not a fresh live-Figma comparison, a complete mobile/keyboard/contrast certification, a load test, or an audit of unrelated product modules. Approval, upload, charge, order, and publication actions were deliberately not executed. Underlying source and all active changed surface families were reviewed; retired custom workspace components were inspected as source, not presented as active pages.

### Surface inventory and verdict

All routes below are on localhost:5001. Project means `10m-landing-page-campaign`; chat means its `chats/thread-primary` route.

| Surface / state | Observed result | Required direction | Evidence |
| --- | --- | --- | --- |
| Projects list and project entry | Native project list is clear. V2 project root and former `/plan` redirect to the account table; project/channel ownership and performance context are missing from that destination. | Keep the shell; restore concise project and selected-campaign context around the existing table. | 22; route source |
| Project chat | Chat still asks to research OpenAI/Anthropic while a separate card advertises prepared Snowflake/Fieldwork materials. | Use one coherent post-research conversation with references to actual selected accounts, recommendations, and pending decisions. | 01, 17 |
| Target Accounts | Original table, filters, paging, and research click remain useful. 1007 sample accounts; 25 rows per page. In split view Company and Artifacts consume almost all visible width; owner and next action are off-screen. | Reuse this table with a campaign-working column preset. Count recipients and outstanding decisions, not only files. | 17 |
| Gallery — campaign materials | Flat file rows split gift, note and page into separate review tasks. The same status column means approval, draft state, or shipment progress. | Default to account → recipient review; keep type-based file browsing as another view of the same catalog. | 01, 23 |
| Gallery — design files/documents | A second Gallery appears inside Gallery, with another toolbar, an Account materials card and Open Gallery links back to the enclosing view. Count says 2 artifacts while Snowflake has 7 materials. | One catalog, one toolbar and one count definition. Remove the nested catalog and handoff-card loop. | 02 |
| Recipient landing-page preview | Shows a composed sample page and Needs review, but has no review resolution, revision request, publish action, or real editor handoff. | Use the canonical artifact preview/editor; expose version, review state and destination readiness. | 03 |
| Shared ad preview | Correctly labels account-wide scope. Switching from a recipient’s page to the shared ad loses recipient context in the related navigation. Audience/destination/launch are unverified. | Retain the originating recipient context; show shared use explicitly. Ad destination and launch readiness belong to the ad program. | 04 |
| Gift selection | Three options, product imagery and evidence disclosure are useful. Copy and selection can diverge: Priya’s chosen coffee set retains a notebook-like note. Merchant links are pending. | Present an agent-prepared recommendation; changing the gift triggers a visible dependency/review check, not silent content rewriting. | 05 |
| Card and note | Live paper/handwriting preview is valuable. Setup instructions, template controls and QR explanation crowd the main review. | Default to reviewing the prepared card; disclose card/font/template controls on edit. Keep content and physical readiness distinct. | 06 |
| Address and cost review | Itemized total and disabled approval for missing receiving address are useful safeguards. Eight editable address fields dominate the screen; gift guidance is elsewhere. | Show the prepared receiving route and only unresolved fields; keep full manual editing available. Put cost and exact approval scope beside the rendered outreach. | 07 |
| Approved/delivered note opened from Gallery | Clicking Card & note opens the entire shipment journey; the note is below the primary timeline. | Open the requested preview first. Tracking is a separate view of the same recipient record. | 18 |
| Delivery tracking | Two shipment legs and carrier-versus-personal-receipt distinction are sound. Milestones, leg cards and activity repeat information. Delivered sample still awaits QR assignment; linked page is unpublished. | Current state, next action, responsible party, ETA/update confidence first; evidence and event history on demand. Correct sample dependencies. | 08 |
| Preparation tracking | Current quality inspection is shown, but multiple generic future steps precede supporting evidence. Casey’s note still reads like the notebook example despite a travel cup. | Prioritize the active stage and exceptions; make the sample content internally consistent. | 21 |
| Direct Mail queue | Useful focused operating table, cost and bulk-selection mechanism. Campaign is mostly a string beneath Gift; there is no campaign-level objective/owner/result summary. | Keep as the workspace-wide mail operations view, with campaign/owner/attention filters and the same recipient preview. | 09 |
| New campaign dialog | Name/project/recipient checkboxes/card/font/spend fields create manual setup. Source derives candidates from existing mailers, not the researched buying committee. | Agent proposes program and recipient cohort from research; human reviews a concise proposal. Keep manual setup as a fallback. | 10; hook source |
| Card/font/note library | Physical previews and production-validation distinction are useful. Separate template organization overlaps the workspace Templates concept. | Reusable card/font/note resources need clear roles and contextual selection; do not intermingle reusable masters with recipient instances. | 11 |
| Budgets and credits | Shows $50–100 preferred gift range, $120 gift-price ceiling, no reservation and per-send approval. Guidance is detached from the work it controls. | Keep the guidance-versus-actual-spend distinction visible in campaign context. Financial provider behavior remains outside this prototype. | 12 |
| Global Artifacts | 23 materials in one catalog; switching to native design files gives All artifacts 0. No project/campaign filter on the added catalog. | One searchable workspace catalog with project/campaign/account/recipient/type scope and shared preview. | 13, 14 |
| Account Artifacts | Correctly scopes seven materials to Snowflake, but repeats the account name, header, filters and nested catalog choice. | Same recipient-first review, fixed to this account, with campaign context when multiple programs apply. | 15 |
| Account overview and Contacts | Overview has an illustrative summary and empty evidence. Contacts returns **404**, although two recipients appear in materials. Contact fixture repository recognizes only older sample accounts. | A coherent, explicitly fictional research/committee example must back the prepared outreach. Unsupported details should never appear as broken navigation. | 16, 20; repository source |
| Selection/reload | Account table → Snowflake → Taylor note changes pane to Gallery but does not serialize account/recipient/material. Reload returns All accounts / 23 materials. | Stable, contract-reviewed object references and preserved review position across entry/reload/back. Do not invent a forbidden `?artifact=` contract. | 19 |
| Expanded versus split layout | Expanded Gallery table begins at y=392 in a 655px-tall viewport. Wide filters stack vertically; narrow mode hides the cost/details and action columns. | One compact context/toolbar area; preserve essential decision data when narrowing; avoid nesting full-page layouts inside a small pane. | 01, 13, 15, 23 |

### Prioritized findings

**High — fix the operating model before polishing:**

1. **Fragmented catalog and review unit.** Gifts, notes, pages and generic documents live in overlapping catalogs with contradictory totals and a Gallery-within-Gallery loop. Approved note click opens tracking. These are user-facing structural failures, not color issues.
2. **Disconnected research story.** The sample chat, target list, empty account research, 404 committee and prepared outreach do not tell one verifiable story. The frontend must demonstrate the relationship to existing research without pretending new research ran.
3. **Campaign identity is incomplete.** The materials projection has no campaign ID; mailers have a campaign string; the separate workspace model has campaign rows. Owners and reporting cannot reliably join these separate concepts. The global catalog lacks project/campaign filters.
4. **Review promises exceed available actions.** Landing pages and ads say Needs review/Draft but have no meaningful resolution path. Those static renders are not evidence of integration with the existing design/editor/publication workflow.
5. **Dependency and fulfillment contradictions.** Gift choice does not explain a stale accompanying note; the delivered example still has pending QR preparation and an unpublished destination. Versioned mailer snapshots are valuable but do not yet cover all connected asset dependencies.
6. **Agentic behavior is mostly absent from the demonstration.** Campaign creation asks people to select old mailer contacts and defaults manually. No coherent agent proposal, researched committee selection, cohort preparation, exception resolution or outcome follow-up is demonstrated. Local state changes must not be described as live agent work.
7. **Scale is only partially demonstrated.** Pagination bounds visible account rows, but the prepared outreach sample has six mailers and 23 materials. This does not validate hundreds of recipient reviews, server pagination, batch decisions or multi-campaign operations.

**Medium — correct alongside the model:**

8. Review selection is lost on reload; shared-ad navigation loses the originating recipient context. Source confirms local selection state without route write-back.
9. Tracking has a next-stage sentence but does not prioritize an actionable exception, responsible party, update freshness and sales follow-up together. Operational, content approval and business outcomes need separate states.
10. Current owner display is useful but campaign manager, account owner, actual sender and follow-up owner are not consistently distinguished. Territory labels are not a working assignment mechanism.
11. Typography uses Satoshi as intended. The main visual defects are hierarchy, excessive navigation, inconsistent table density, stacking filters, repeated borders/containers, small unrendered preview thumbnails and scarce usable preview area. Literal 11/13/18px values mirror parts of the scale but bypass semantic typography contracts. Do not replace Clue’s legitimate 14/20 body and 11/16 captions with a generic 16px redesign.
12. Implementation debt increases drift: view/filter/controller logic is concentrated in MaterialsBrowser TSX; style overrides reach into other modules by class-name substrings; retired custom plan/workspace components remain. Reuse canonical projections/controllers/renderers rather than continuing wrapper composition.

### What remains worth keeping

The existing Target Accounts component and its research navigation; native shell and chat; Clue tokens and shared controls; canonical mailer draft/approval records; exact approved snapshots; three-gift choice; handwritten-card rendering; explicit receiving-address readiness; itemized spend confirmation; individual review plus bulk approval; two shipping legs; package photos; versioned local adapters and preview isolation. Reuse these foundations after simplifying composition.

## Proposed direction for discussion

The recipient-first review unit is confirmed. The following structure and sequence are recommendations, not an approved implementation specification.

### Two approaches considered

- **Unify the catalogs but keep individual files as the default.** Smaller change; useful to designers looking for a particular page or ad. It still makes a reviewer assemble each person’s gift, message, destination and delivery context. Retain this as a secondary file-browsing mode.
- **Account table with recipient outreach reviews, backed by one catalog — recommended and confirmed as the review unit.** The reviewer opens an account and chooses a recipient. The gift, card/note, landing page, rationale, sender and cost belong to one coordinated review. Account-wide ads are clearly shared. Designers can still open any canonical asset independently.

A separate board or new campaign dashboard is not the first fix. A later board can project the same campaign participation records if it answers an operational need; it must not introduce another workflow or duplicate state.

### Responsibilities of existing surfaces

| Surface | One primary job |
| --- | --- |
| Project chat | State an outcome, set scope, steer recommendations, resolve consequential decisions. Agent messages reference the same objects the work pane displays. |
| Target Accounts | Choose and monitor the cohort. Use existing table with a campaign-working preset: account, owner, recipients, materials/readiness, next decision and execution summary. Keep the research preset available. |
| Gallery in the chat | Review the selected account’s prepared recipient outreach. Same preview at one account and at 1000; next/previous review and batch scope change, not the UI model. |
| Account Artifacts | The same review and catalog fixed to one account, across its project/campaign participation. |
| Workspace Artifacts | Search/reuse/discover canonical artifacts across projects, accounts, types and versions. Selecting one opens the same preview in context. |
| Direct Mail | Monitor and act on physical sends across projects: approvals, blockers, delivery, spend. Selecting a row opens the same recipient record. |
| Templates and reusable mail resources | Store reusable masters, cards, handwriting and message structures, distinguished from generated recipient instances. Their exact consolidation needs a targeted design pass. |

A compact selected-campaign summary belongs around the existing project table: objective, owner, cohort, budget guidance and decision/execution counts. A campaign filter changes the same table and Gallery. This restores campaign visibility without requiring another permanent sidebar destination.

### Data relationships that make the experience coherent

Use the repository’s existing terminology: a **project** is the overall ABM motion; a **campaign** is one channel program inside it. An account can participate in several campaigns; do not nest it permanently under one. Gift-led and content-led are strategies, not separate applications or mandatory global stages.

The proposed connected record carries references, not copied blobs:

1. Project and channel campaign; campaign manager and intended business outcome.
2. Target-account membership; account owner/territory; buying-committee contact and role.
3. Existing promoted research claim references and persona value narrative; recommendation reason and freshness.
4. Recommended action for that person, including why gift-led or content-led is appropriate. Skipped channels remain explicitly absent.
5. Canonical artifact/version references: gift proposal, chosen physical product, card design, final note, recipient page, and any account-wide ad used by the campaign. Reusable template revision and generated instance remain distinct.
6. Human decisions and exact approval snapshot: gift/variant, rendered note/card, sender, receiving route, itemized cost, permitted maximum and relevant content versions.
7. Execution records: merchant order, inbound shipment, receiving/quality evidence, physical card/QR assignment, packaging and outbound shipment.
8. Engagement and sales outcomes: published destination, observed visit/reply/meeting events and follow-up owner, with source and uncertainty. A scan or carrier delivery is not proof of personal receipt or a meeting.

Artifacts can be referenced by several actions/campaigns without duplication. A physical send is an operational record with linked artifacts; it is not just another image file. The UI’s complete-recipient review is a projection of those references, not a second copy of the note or landing page.

This follows existing architecture: harness REQ-20/21 (shared human/agent operations and typed object refs), Doc A (honest tool/agent/runtime vocabulary), and Doc S (research-grounded content, exemplar/template finalization, versioned derivation and ranked review). API and route changes require a separate contract-gap review before integration. The existing project contract expressly forbids reviving `?artifact=` and records artifact deep-link identity as an unresolved decision.

### Intended post-research customer flow

1. **Start from known research.** In the existing project chat: “Prepare direct mail for these accounts using the research we already have.” The agent uses current account/committee/context references and flags only consequential missing or stale evidence.
2. **Propose the approach.** Show recommended cohort, recipient roles, account rationale, sender assignment, gift guidance and channel mix. An ad/page-first account is not forced through gift selection. The user adjusts the plan in natural language or in the same table.
3. **Prepare the work.** The agent proposes three gifts, one recommended choice, a relevant note/card, and the appropriate page; it validates dependencies and surfaces exceptions. At scale, reusable finalized designs and bounded generation produce recipient instances. No invented sources or fake successful agent runs.
4. **Review one person’s complete outreach.** Show why this person, why now, sender, rendered gift/card/page and all-in cost together. The main action is specific to the unresolved decision. Alternatives and edit controls are available without becoming a required form-filling exercise.
5. **Approve the exact send.** Preserve the founder’s individual-review-plus-bulk-approval rule. A cohort can be prepared in bulk and reviewed in a continuous queue, then approved as a clearly itemized batch. Strategy/template approval is not permission to purchase/send. Guidance reserves no credits; spend still needs explicit approval. Changed dependencies must visibly invalidate the affected decision rather than silently reusing approval.
6. **Execute and track.** Show what is happening, what is blocked, who owns the next action and when the next update is expected. After Clue’s quality check, shipment proceeds without another customer photo-approval gate; photos remain available as evidence.
7. **Support the sales follow-up.** Once meaningful evidence arrives, suggest a contextual next action for the assigned rep. Show known engagement and meetings separately from delivery. Email execution remains owned by the separate email workstream.

Do not promise a numerical “100×” improvement without measurement. The intended reduction is repeated setup and hunting: reuse research, prepare related assets together, preserve context, batch mechanical work, and ask only for decisions the user actually needs to make. Individual review remains a real human cost under the current policy.

### Same interface at one account and at scale

At one account the same table is filtered to one row; the same review contains its recipients. At 500–1000, filters/saved views narrow the cohort, recipients are paginated, and the review has a visible position plus next unreviewed item. Selection scope must distinguish this page, selected rows, and all matching results. Show separate counts for accounts, recipients, sends and artifacts.

The default account row summarizes decisions and execution, not thousands of expanded child files. Account and recipient selectors stay visible while previews change. Opening an account, artifact or chat reference must preserve the selected campaign and return position. Shared assets carry a scope label and backlinks to their uses; they do not inherit a particular recipient’s identity accidentally.

### Tracking and analytics model

Do not collapse these into one Status field:

| Dimension | Examples | Customer question |
| --- | --- | --- |
| Preparation/readiness | Preparing, missing receiving route, ready for review | What does the agent need to finish? |
| Decision/approval | Unreviewed, reviewed, approved version, changes require review | What am I being asked to decide? |
| Physical execution | Approved, ordered, inbound, received, quality check, outbound, delivered | Where is the gift and what happens next? |
| Digital readiness | Draft, approved, published destination, QR assigned, QR verified | Will the linked experience work when used? |
| Engagement/outcome | Observed visit, reply, meeting booked, opportunity event | Did this help start or advance a conversation? |

Tracking opens with current state, next owner/action, update time and appropriate ETA; then two delivery legs and package/card evidence; event history expands below. Surface exceptions before a long list of completed steps. A delivery date replaces a stale expected date. If a page/QR is required by the approved send, readiness must be resolved before dispatch; a mailer without that dependency should say so explicitly.

Campaign rollups use those same records: target accounts, prepared recipients, approvals due, blocked sends, in-progress/delivered sends, approved/actual spend, observed engagement and meetings. Do not mix recipient counts with asset counts or imply causal revenue attribution from a scan. A dedicated analytics page can follow once these definitions and event contracts are agreed.

### Visual formula

- Preserve Satoshi, Clue semantic colors, existing typography roles, table density options, shared buttons, input/dropdown and shell contracts. Avoid a cosmetic theme replacement.
- One location indicator, one compact filter/selection bar, one primary work area, one contextual main action. Remove the redundant inner Gallery and repeated account headings.
- Use actual gift, rendered note and page/ad thumbnails. A generic document icon is only a fallback, not the main preview for generated creative.
- Reuse a preview body that works in both the chat work pane and full-width mode. Do not embed a complete standalone page, including its full chrome, inside another page.
- Keep scope, sender, cost and unresolved decision visible at narrow pane widths. Collapse secondary metadata/controls rather than hiding decision-critical information.
- Show the prepared output first; put editing/configuration behind deliberate controls. Retain clear loading, unavailable, stale, changed, failed and empty states.
- Visual QA must cover actual panel widths, long names/notes, multi-recipient accounts, mixed statuses, missing data and keyboard focus. The current audit does not certify these states as solved.

### Recommended next sequence, after discussion

1. Agree the object relationships and responsibilities above; retain the already confirmed recipient review unit.
2. Produce one focused design walkthrough within the existing shell: researched account → recipient review → exact cost approval → current tracking/next action. Also show an account with two recipients and a content-led account in that same shell.
3. Review the single-account composition and its 500-account table/queue state together, including an exception and an unpublished-page dependency. Do not build every route again before this is accepted.
4. Implement the agreed shared projection and preview once, route existing surfaces into it, and remove superseded wrappers. Keep fixtures clearly isolated behind repositories for Aryan. No backend contract decisions inside TSX.
5. Re-audit task completion and visual fidelity across all entry points before expansion. Gates include: no nested Gallery, no broken account/committee links, exact subject opens on click, stable return/reload context, consistent record/version/cost across surfaces, coherent tracking dependencies, and explicit batch approval scope.

Historical audit boundary (2026-10-26): implementation was paused for approval. On 2026-10-27 the founder authorized the focused two-recipient / 500-account walkthrough documented above. Broader channel orchestration remains future work.
# Account artifact library (October 27 revision)

Account → Artifacts now defaults to all saved work for that account across campaigns. It is a persistent library, not a recipient approval screen. `AccountArtifactLibrary` projects canonical mailers, pages, campaign creative and native account files through `buildAccountLibrary`; it keeps editable content and immutable approval snapshots in their existing repositories.

- Cards are grouped into landing pages, ads, gifts, cards/notes, and files. Grid/list, search, campaign, recipient and approval filters share the same records. Results are bounded to 24 items.
- A material preview shows its campaign, project, recipient or account scope, version and approval separately from delivery/publication. The campaign name filters the library to that program. Related materials never cross campaign/project boundaries.
- “Review recipient outreach” opens the existing gift/note/page/cost workflow for that exact mailer. Approved outreach opens tracking. Entering an account never starts a review automatically.
- Account library means all campaigns for the account; project Gallery is the project working context; the workspace Artifacts entry is workspace-wide. These are scopes over canonical artifacts, not separate asset stores. The existing project Gallery queue remains the operational outreach view in this revision.
- URL state: `material` selects a library item; `campaign`, `type`, `libraryRecipient`, `libraryStatus`, `librarySearch`, `libraryPage`, `view` describe the library; `libraryReview=1` explicitly opens review and `review` chooses its step. `projectId` remains return context, not a filter on account history. Old `catalog=earlier/files` links now open the unified account library. Browser Back retains the selected campaign and item.
- Campaign metadata is optional on the preview creative schema. A narrow additive migration assigns known old demo records to their existing campaigns. Unknown native files remain unassigned; no campaign is inferred from file type or title. The account file HTTP contract is unchanged. Backend campaign IDs/history queries still require a contract review with Aryan before integration.
- Local demo inspection informed the separation of campaign versions from account activity. No recording or frames were copied into the repository.
