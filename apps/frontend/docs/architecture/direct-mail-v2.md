# Project materials V2

Status: local frontend preview, updated 2026-10-26. V1 remains on port 5000; V2 on 5001, branch `feat/direct-mail-infrastructure-v2`. No live orders, payments, agent runs or publishing. Email belongs to the separate email branch.

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
