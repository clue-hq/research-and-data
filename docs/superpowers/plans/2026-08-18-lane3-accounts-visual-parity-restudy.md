# Lane 3 — Accounts Visual Parity Re-Study (post-Phase-C), 2026-08-18

> **Audience:** the design co-founder (Lane 3) and the founder. This supersedes nothing — it is
> the *re-verified, component-placement-level* companion to the 2026-08-17 governance doc
> (`2026-08-17-lane-3-accounts-visual-parity.md`). That doc remains the rules-of-engagement
> (boundaries, method, escalation); this doc is the **current, exhaustive inventory of what is
> actually different**, re-measured after Phase C landed, with both frontends running live
> side-by-side and every finding anchored to file:line in both trees.
>
> **How this was produced (2026-08-18):** the dummy frontend (design baseline, `codex/chat-shell`
> tip `c7f2bc5`) served from `/tmp/clue-frontend-tip` on **localhost:3000** on fixture data; the
> integrated frontend (branch `platform/comprehensive-account-contact-research`, Phase R + Phase C
> complete) on **localhost:3020** against the real backend on **127.0.0.1:8005** and database
> **`clue_combined_browser_20260817_m1`** (the migrated clone of `clue_combined_browser_20260816_c1`
> — the original is one migration behind this branch and is preserved untouched). Screens were
> walked in a real browser on both sides (screenshot pairs in `/tmp/lane3-parity-20260818/`), and
> in parallel all 28 presentation files were read fully in both trees.

---

## 0. Reproduction notes (read before re-running the comparison)

1. **The backend must run with `CLUE_FRONTEND_READ_ENABLED=true`.** The repo-root `.env` does not
   set it, and without it every `/frontend/v1/accounts*` call 404s and the integrated `/accounts`
   renders the "Accounts needs support" recovery card. This exact trap was already hit and
   recorded on 2026-08-16 (`_memory/2026-08-16-combined-browser-acceptance.md`); it was hit again
   today and fixed the same way (restart the API with the flag exported).
2. **Dummy fixture ids are narrow.** The dummy's account-detail fixture answers **only**
   `openai`; the full contact fixture answers **only** `denise-dresser`. Any other id 404s
   (`account-details.repository.ts:13`, `account-contacts.repository.ts:28`). So the dummy
   reference walk is: `/accounts` → `/accounts/openai` (+ `/preview`, `/contacts`, `/insights`,
   `/artifacts`, `/activity`) → `/accounts/openai/contacts/denise-dresser`.
3. **The live database has zero contacts** (`contact_entity` count = 0 in the clone). Every
   contacts-surface finding below is therefore verified from code structure (both trees read in
   full), not from a populated live screen; the live contacts tab shows the (undesigned)
   empty-state + pagination footer.
4. **Live artifacts tab is hardcoded off**: the integrated route passes
   `state="capability_unavailable"` unconditionally (`app/(protected)/accounts/[accountId]/artifacts/page.tsx:19-21`).
5. Screenshot pairs from this run: `/tmp/lane3-parity-20260818/{dummy,int}-*.png`
   (list, preview, detail, detail-bottom, contacts, contact-profile, insights, activity, artifacts).

**Path shorthand used throughout:**
- **D:** `/tmp/clue-frontend-tip/src/features/accounts/…` (design baseline — identical to the
  co-founder's frozen `features/accounts` tree; re-verified unchanged `4e2a300..c7f2bc5`)
- **I:** `apps/frontend/src/features/accounts/…` (integrated)

---

## 1. Executive summary

The account/contact **routes and the workspace shell are at parity** — same eight routes, same
five-tab header (Overview / Contacts / Insights / Artifacts / Activity), same rail geometry.
(Note: the 2026-08-17 doc's §8 line about "invented five-tab navigation" is **stale** — the tab
bar exists in the design baseline and matches; do not remove it.)

Everything inside those frames drifted, in four repeating patterns:

1. **Inserted chrome the design never drew** — bulk-action bars, notice strips, a permanent
   pagination footer, recovery screens, add-to-chat dialogs — sandwiching the designed tables.
2. **Designed content sections deleted or replaced** — "About their business", the ICP-fit
   explainer (FitCriteria), "Insights & evidence" on the overview, the Artifacts grid, the rail's
   firmographic/fit rows and Activity panel, the contact preview drawer.
3. **Backend internals rendered as UI** — raw claim UUIDs, ICP keys + versions, `prj_…` ids,
   cutoff/rubric versions, `provider_estimate` / `company.financials.revenueAnnual` strings,
   raw JSON evidence blobs, `10m_50m` enum values, namespace sub-labels (`core`), provider
   bylines ("Exa websets · 16 Aug 2026"), em-dash placeholders everywhere. Live-confirmed on
   every integrated screen.
4. **Identity and color signal degraded** — logos → initials monograms everywhere; the green
   `FitBadge` treatment (the surface's only accent color) replaced by neutral `TokenBadge`;
   colored influence pills → plain text + bare percentages; multi-network social icons → LinkedIn
   only.

Counts from the full component read: **~30 EXTRA**, **4 MISPLACED**, **~35 MISSING**, **~40
STYLE-DRIFT** findings across 9 screens. Detail per screen in §3–§11; the three category
inventories the founder asked for are §2.

---

## 2. The three category inventories

### 2A. EXTRA — renders in the integrated tree, no counterpart anywhere in the design

*The "invented UI" class. Per the parity constitution these either get a designed slot, get
hidden, or go agent-/API-only — each is a §6/R9-style founder decision, not a restyle.*

| # | What | Where (integrated) | Screen | Live-verified |
|---|---|---|---|---|
| 1 | Bulk-action bar (count, native project `<select>`, Add to project, Add to chat, Clear, over-limit warning) | `I:accounts-screen.tsx:70-125` | Accounts list | code (needs selection) |
| 2 | Bulk-notice strip + "Dismiss" | `I:accounts-screen.tsx:127-141` | Accounts list | code |
| 3 | Inline load-recovery alert row under the table | `I:accounts-screen.tsx:163-190` | Accounts list | code |
| 4 | **Pagination footer** (`table-pagination.tsx`, 114L): range text, page chips/input, "Show max rows" native select, lucide icons | `I:accounts-screen.tsx:192-208`, `I:table-pagination.tsx:48-113` | Accounts list + Contacts | **yes** |
| 5 | `AddToChatDialog` mounts | `I:accounts-screen.tsx:209-213`, `I:account-contacts-screen.tsx:311-315` | List + Contacts | code |
| 6 | **Recovery screen** (`accounts-recovery-screen.tsx`, 103L; shadcn `var(--primary)`/`var(--ring)` tokens, alien to the surface) | mounted `app/(protected)/accounts/page.tsx:19` | `/accounts` alternate | **yes** (seen before flag fix) |
| 7 | "Projects" table column (comma-joined names; live: "Untitled project") | `I:accounts-table.tsx:372-380,483-496` + toolbar/filter entries | Accounts list | **yes** |
| 8 | Per-ICP multi-group fit-score cell (N icon+number groups) | `I:accounts-table.tsx:197-228` | Accounts list | code (single-ICP data live) |
| 9 | Em-dash `Absent` primitive threaded through every surface | `I:account-facts.tsx:21-28` (used in ~12 sites) | all | **yes** |
| 10 | "Withheld" policy pill | `I:account-facts.tsx:31-40` | list/detail/contacts | code |
| 11 | Indeterminate (mixed) checkbox third state | `I:account-checkbox.tsx:31-33` | List + Contacts | code |
| 12 | `account-avatar.tsx` initials-monogram primitive (60L) — mechanism behind every logo loss | `I:account-avatar.tsx:9-60` | all | **yes** |
| 13 | **"Research by project" section** as the overview's organizing principle, incl. lineage prose ("Claims whose run maps to no project…", "Unnamed project", "Targeted, nothing produced yet.") | `I:account-detail-screen.tsx:29-46,73-79,153-177` | Account overview | **yes** |
| 14 | Score chip `Fit 100 · Intent 0 · ICP <icpKey> v<N>` | `I:account-detail-screen.tsx:81-96` | Account overview | **yes** |
| 15 | Narrative/score cards dumping raw key/values (Tier, Icp key, Project id, Fit claim id, Cutoff version, Rubric version, Intent claim id, Disposition, Project run id) | `I:account-detail-screen.tsx:98-123` (+ `FactValue` object rendering) | Account overview | **yes — worst screen in the audit** |
| 16 | "Also known as" / "Registry ids" / "Headquarters" (joined `hqGeo` blob) rail rows | `I:account-detail-primitives.tsx:174-201` | Detail rail + drawer | **yes** |
| 17 | **"Researched fields" `FactList`** (unbounded registry dump: prettified field key + raw namespace sub-label + value + provenance byline) | `I:account-detail-primitives.tsx:203-210`, `I:account-facts.tsx:137-196` | Detail rail + drawer + contact profile ("Professional facts") | **yes** |
| 18 | `AccountCoveragePanel` — "N fields hold a value…" + "Research asked for these and could not answer them:" | `I:account-detail-primitives.tsx:232-278` | Detail rail + drawer (in the slot designed for Activity / "About their business") | **yes** |
| 19 | Merge-redirect notice paragraphs (account + contact variants) | `I:account-detail-primitives.tsx:50-57`, `I:contact-profile-content.tsx:61-68` | Detail + contact profile | code |
| 20 | Domain link line under the identity h1 | `I:account-detail-primitives.tsx:40-49` | Detail + drawer | **yes** |
| 21 | Persona label appended to committee rail rows | `I:account-detail-screen.tsx:203-207` | Detail rail | code |
| 22 | **"Research evidence" section + `evidence-list.tsx` cards** (112L): confidence pill, "Open retained evidence", verbatim span blockquote (live: raw JSON), freshness sentence, `Claim <uuid>` footer | `I:account-workspace-screens.tsx:93-105`, `I:evidence-list.tsx:12-112` | Insights tab + contact profile | **yes** |
| 23 | Insights empty state "No inspectable account evidence is served yet." | `I:account-workspace-screens.tsx:68-72` | Insights tab | code |
| 24 | `capability_unavailable` notice card replacing the Artifacts screen | `I:account-workspace-screens.tsx:126-141` | Artifacts tab | **yes** |
| 25 | "Current state: N contacts · <summary>" strip with cross-links | `I:account-workspace-screens.tsx:177-195` | Activity tab | **yes** |
| 26 | Activity cross-surface links (rows link to contacts/account/projects) + empty state | `I:account-workspace-screens.tsx:181-244` | Activity tab | **yes** (empty state) |
| 27 | "Signals" contacts column ("N signal types" / em dash) | `I:contacts/components/contact-row.tsx:117-127` | Contacts table | code |
| 28 | Contacts grid empty state "No committee members have been resolved…" | `I:account-contacts-screen.tsx:292-298` | Contacts table | **yes** |
| 29 | Resolved email address list as mailto links + per-address provider attribution ("(Apollo, Clay)") + four extra terminal states ("—", "Unavailable", "Try again", "Lookup failed") | `I:contacts/components/lookup-email-button.tsx:49-101` | Contacts email cell | code |
| 30 | "Projects" row on the contact profile field grid | `I:contact-profile-content.tsx:114-120` | Contact profile | code |
| 31 | Second table empty-state sentence "No accounts exist in this workspace yet." | `I:accounts-table.tsx:518-520` | Accounts list | code |

### 2B. MISPLACED — exists in both trees, but the integrated tree renders it in the wrong place

| # | What | Design placement | Integrated placement |
|---|---|---|---|
| 1 | **Contact profile body** | Rendered in BOTH the in-place preview drawer over the contacts table (`D:contacts/components/contact-preview.tsx:67`, 786px slide-over, `compact` variant) AND the full page | Full page **only** — the row's name cell became a route `Link` (`I:contacts/components/contact-row.tsx:76-88`), so inspecting a contact destroys table context (scroll, selection, search) |
| 2 | Contacts/Committee row in the account rail | Immediately after the fit rows, inside the compact details list (`D:account-detail-primitives.tsx:178-182`) | Renamed "Committee" and pushed **below** the unbounded "Researched fields" FactList (`I:account-detail-primitives.tsx:212-219`) — the people sink under the fact dump |
| 3 | Preview drawer 4th block | "About their business" prose (`D:account-preview-drawer.tsx:33-38`) | `AccountCoveragePanel` diagnostics occupy that slot (`I:account-preview-drawer.tsx:36-38`) |
| 4 | Contact evidence presentation | Compact 3-column link rows (16px source icon / truncated title / right-aligned date) inside "Insight & evidence" (`D:contact-profile-content.tsx:131-147`) | Full-width bordered cards stacked vertically (`I:evidence-list.tsx:21-110`) — same content concept, different component form and it now dominates the page height |

### 2C. MISSING — the design renders it, the integrated tree does not

| # | What | Design source | Consequence |
|---|---|---|---|
| 1 | **"Overall fit" table column** (green `--clue-fit-high-*` pill) | `D:accounts-table.tsx:385-396,244-254` | The grid's only saturated-color cell is gone; table reads monochrome |
| 2 | **"Locations" table column** | `D:accounts-table.tsx:433-444,283-291` | Column + its filter/columns-panel entries gone |
| 3 | "Overall fit" + "Locations" entries in Customise-columns and Filter panels | `D:accounts-toolbar.tsx:48,52`, `D:accounts-filter-panel.tsx:16-20,64-69` | Fields can't be re-enabled or filtered |
| 4 | Company logo images (table rows, identity tile, breadcrumb, contact rows, account row on profile) | `D:accounts-table.tsx:219-226`, `D:account-detail-primitives.tsx:39-47`, `D:account-workspace-shell.tsx:120-127`, `D:contact-full-screen.tsx:40-46`, `D:contact-profile-content.tsx:77-89` | Every brand mark is an initials monogram; `logoPath`/`accountLogoPath` left the schemas |
| 5 | Refresh spinner on completed-but-refreshing rows | `D:accounts-table.tsx:137-138` | In-flight refresh is visually silent |
| 6 | **"About their business" section** (overview + drawer) | `D:account-detail-screen.tsx:211-216`, `D:account-preview-drawer.tsx:33-38` | Half the account narrative never renders |
| 7 | **FitCriteria** (Overall fit badge + per-criterion pass/fail rows w/ evidence) | `D:account-detail-screen.tsx:18-53,217` | The "why does this account fit our ICP" explainer is gone |
| 8 | **"Insights & evidence" overview section** (source glyphs, external links, right-aligned dates, "See all" → insights tab) | `D:account-detail-screen.tsx:55-106,218` | No dated evidence feed, no in-content path to Insights |
| 9 | **Rail "Activity" panel** | `D:account-detail-screen.tsx:158-177,189` | Recency signal replaced by the Coverage report |
| 10 | Rail rows: Research status, Website, Size, Locations, Revenue, Referral fit, Direct access fit, Recall fit, Overall buying fit (9 of 10 designed rows) | `D:account-detail-primitives.tsx:149-177` | The rail's firmographics + all four fit dimensions unrepresented (drawer loses 7 of 10) |
| 11 | `FitBadge` green "High" variant (the accent treatment itself) | `D:account-detail-primitives.tsx:11-33` | Every pill on detail surfaces is neutral grey |
| 12 | **The whole Artifacts screen**: search, "Last viewed" sort, grid/list toggle, thumbnail card grid, preview lightbox | `D:account-workspace-screens.tsx:71-197` | Tab is a permanent dead end (hardcoded notice) |
| 13 | **`contact-preview.tsx`** (786px contact slide-over w/ header: close, name, "Open as page", link + ellipsis) + the `compact` profile variant | `D:contacts/components/contact-preview.tsx:1-71`, `D:contact-profile-content.tsx:52,57` | No in-place contact inspection; the drawer padding variant was deleted with it |
| 14 | Contacts "Influence" column as a colored pill | `D:account-contacts-screen.tsx:34`, `D:contacts/components/contact-row.tsx:86-96` | Replaced by "Committee role" plain text + bare `62%` |
| 15 | Multi-network social icons (x, facebook, instagram, whatsapp) | `D:contacts/components/contact-row.tsx:19-25,100-110` | LinkedIn only, em dash otherwise |
| 16 | Contact profile "X" row | `D:contact-profile-content.tsx:104-108` | Two-network identity block halved |
| 17 | "Email found" terminal label on lookup | `D:contacts/components/lookup-email-button.tsx:5-9` | Designed end state replaced by address lists/error words |
| 18 | Evidence source icons + right-aligned date column + "See all" on contact profile | `D:contact-profile-content.tsx:32-47,123-130,142-144` | Evidence loses source-at-a-glance and scannable recency |
| 19 | "Last updated <time>" header metadata on contact full page | `D:contact-full-screen.tsx:55-57` | Header right side is two bare icons (deliberate: value not served — needs a ruling or a seam) |
| 20 | Designed research-status vocabulary "Fully enriched" / "In progress…" / "Failed" | `D:accounts-table.tsx:74-79` | Integrated speaks "Completed / Not started / Suspended / Needs review / Not launchable" (live-confirmed) — different word set, sentence-cased but not the designed words |
| 21 | Persona tone variety (olive/cyan/pink unreachable; tone was per-contact on the wire) | `D:model/account-contact.ts:26` vs `I:model/account-contact.ts:27-32` | Persona color palette collapses to 4 of 7 |
| 22 | Designed insight rows on Insights tab render `sourceLabel`; integrated renders the raw URL | `D:account-workspace-screens.tsx:51-53` vs `I:85-87` | Underlined truncated URLs where a source name was designed |

### 2D. STYLE-DRIFT highlights (same element, same place, wrong rendering — live-confirmed unless noted)

- **Raw/registry-cased names render as-is**: `SOUTHERN OREGON NEUROSURGICAL & SPINE ASSOCIATES`,
  `CAPITAL NEUROSURGERY SPECIALISTS` (live, list + breadcrumbs). The §7.2 "no ALL-CAPS registry
  casing" rule is still being violated — there is no name-casing formatter in the render path.
- **Raw enum/id strings live on screen**: `10m_50m` (revenue band), `provider_estimate`,
  `company.financials.revenueAnnual`, `neurosurgery_practices_pacific_northwest v1`,
  `prj_6b5ef29beadd5ae2bcc91f4706fc1121`, claim UUIDs, `v-d6f1c5694c5b06cf` cutoff version,
  raw JSON blob in an evidence blockquote (Insights tab).
- **Em-dash texture**: Registry ids —, Headquarters —, Committee —, Revenue —, plus every sparse
  contact cell (design never renders a dash anywhere).
- Header labels: "Size" → "Employees" (table, columns panel, filter). Select-all label wording
  changed. "Insight & evidence" → "Evidence". "Role" → "Title", "Influence" → "Committee role"
  (with the old influence icon now mislabeled). Absolute UTC timestamps replace relative times on
  Activity. `formatToken` vs `formatSemanticToken` render the same value differently between the
  contacts table and the profile ("C level" vs "C-level").
- `DetailsRow` alignment `items-center` → `items-start` (+`pt-*`) — rail rows read top-aligned
  multi-line instead of the designed centered single-line.
- `AccountIdentity` lost its fixed `h-[100px]` — the first section's vertical rhythm shifts.
- Foreign vocabularies: `lucide-react` chevrons + native `<select>`/`<input type=number>` in the
  pagination bar; shadcn tokens in the recovery screen — the only two files in the surface not
  built from the design system.

---

## 3. Screen: Accounts list (`/accounts`)

**Design (3000):** `AccountsToolbar` (h1 + search | Customise columns / Sort / Filter / New
account) above a full-height table: ☑ / Company name (logo) / Research status (1 pill) /
Overall fit (green pill) / Fit score (icon+number) / Revenue / Size / Locations. Continuous
scroll, no footer. Preview opens at `/accounts/{id}/preview` as a right drawer over the list.

**Integrated (3020, live):** toolbar identical (byte-identical file except the columns array).
Table columns: ☑ / Company / Research status / Fit score / Revenue / **Employees** / **Projects**.
No Overall fit, no Locations. Initials avatars. Status words "Completed / Suspended / Not
started". Em-dashes in Revenue. Permanent pagination footer ("Showing 1—5 of 5", page input,
"Show max rows [20]"). On selection: bulk bar + notice strip insert above the table.

Everything in §2 tables #A1-12, #C1-5, #C20. The toolbar, filter-panel CSS, filter-select,
density selector, resize handle, readability CSS are **byte-identical** — the designed control
language is intact; the drift is in what columns/bars/states surround it.

## 4. Screen: Account preview drawer (`/accounts/{id}/preview`)

Design order: toolbar → identity (logo, name) → details list (10 rows incl. fit pills +
Contacts avatars) → "Account summary" → "About their business".
Integrated order (live): toolbar (title = name, "Open as page" intact) → identity (monogram +
domain link) → **5 different rows** (Account, Domain, Also known as, Registry ids —,
Headquarters —) → **Researched fields dump** (incl. the `provider_estimate` /
`company.financials.revenueAnnual` object) → Committee — → summary (or "The account summary is
unavailable for display.") → **Coverage** panel. See §2A #16-18, §2B #3, §2C #10-11.

## 5. Screen: Account overview (`/accounts/{id}`)

The worst screen in the audit. Design: identity → summary → About their business → FitCriteria →
Insights & evidence, with a rail of details/contacts/activity.
Integrated (live): identity (monogram + domain) → summary ("unavailable for display" here) →
**"Research by project"** → per-project "Untitled project — Added discovered · 16 Aug 2026" →
`Fit 100 · Intent 0 · ICP neurosurgery_practices_pacific_northwest v1` chip → **two "Tier" cards
printing 12-14 raw key/value lines each** (Icp key, Project id, Fit claim id, Cutoff version,
Rubric version, Intent claim id, Disposition, Project run id…). Rail: 5 identity rows +
Researched fields dump + Committee — + Coverage. See §2A #13-21, §2C #6-11.

## 6. Screen: Contacts tab (`/accounts/{id}/contacts`)

Design: h1 + search + Display popover; 6-column grid (☑ / Contact name / Title / Persona pill /
Influence pill / Email lookup / Social icons); row click opens the **in-place preview drawer**;
no footer. Integrated: 7 columns (Committee role text+%, new Signals column), conditional ☑
column (table edge moves 56px when bulk capabilities are off), bulk bar + notice strip +
pagination footer + AddToChatDialog, row click **navigates away**, empty state + em-dash texture.
Live shows the empty state + footer (DB has 0 contacts). See §2A #4-5,27-29, §2B #1, §2C #13-17.

## 7. Screen: Contact profile (`/accounts/{id}/contacts/{contactId}` and the missing drawer)

Design: avatar photo → name + persona pill → 7 field rows (Name / Account w/ logo / Role /
Influence / Recent signals / LinkedIn / X) → Overview prose → "Insight & evidence" compact link
rows w/ "See all". Integrated: initials avatar → name + pill → (merge note) → field rows
relabeled (Title / Committee role; Projects row added; X row gone; LinkedIn shows stripped URL;
"Recent signals" is a count) → Overview (3-state) → **"Professional facts"** FactList →
**"Evidence"** cards with claim UUIDs. Header loses "Last updated". See §2A #17,19,22,30,
§2B #4, §2C #16-19.

## 8. Screen: Insights tab

Design: h1 + list of insight links (source icon / title / underlined source label / summary).
Integrated (live): h1 → *(no insight rows served)* → **"Research evidence"** heading → cards:
"Exa websets / Supports Account name / 75% confidence / https://reboundmd.com /
Open retained evidence / <verbatim span — live shows a raw JSON object> / 16 Aug 2026 · Within
its freshness window · Claim b880d74c-…". When insights do serve, the integrated row renders the
raw URL where the design shows `sourceLabel`. See §2A #22-23, §2C #22.

## 9. Screen: Artifacts tab

Design: full artifact browser (search / sort / view toggle / thumbnail grid / lightbox).
Integrated (live): "Account artifacts are not connected yet — This workspace does not currently
provide a live Account artifact library." Nothing else. See §2A #24, §2C #12.

## 10. Screen: Activity tab

Design: h1 + hairline-spine timeline, one-line rows (icon + text + relative time).
Integrated (live): h1 + "Current state: 0 contacts · Summary restricted" link strip + empty
state. When populated: two-line rows, raw `research_view.*` event names, absolute UTC
timestamps, cross-surface links, changed icon set. See §2A #25-26.

## 11. Screen: Workspace shell (header/tabs/rail chrome)

**At parity** except: breadcrumb logo → initials monogram (§2C #4) and the "Open company
website" menu item is conditionally omitted when domain is null (design always renders it).
Tab set, hrefs, pill styling, rail widths, overlay behavior all match. The five-tab nav is
**designed**, not invented — strike the stale §8 line in the 2026-08-17 doc.

---

## 12. What this means for the Lane-3 worklist (unchanged rules, sharpened targets)

- The 2026-08-17 doc's §5 file worklist and §4 boundaries remain correct. This doc adds the
  *what-exactly* per file. The nine at-parity files re-verified byte-identical today.
- The **R9 undesigned-component set is confirmed live and has grown in precision**: to the six
  listed (account-facts, evidence-list, table-pagination, accounts-recovery-screen,
  account-avatar, bulk chrome) add the **"Research by project" overview section**, the
  **Coverage panel**, the **Activity "Current state" strip**, and the **email-result rendering**
  — all §6-class (real data, no designed slot; do not delete, do not restyle ad hoc).
- Two items in the MISSING list are *not* pure regressions and need a founder/seam decision
  before the co-founder can restore them: "Last updated" (no timestamp served) and the
  fit/influence pills (the integrated schemas dropped `overallFit`/`influence`; restoring the
  visuals needs the seam to serve display-approved values — escalation rule §8 of the
  governance doc applies: request the prop, never widen a schema).
- The fastest visible wins with zero seam risk, in order: restore the designed status
  vocabulary via `model/vocabulary.ts` additions (request), re-point evidence/facts surfaces
  behind (b)-hide rulings, restore "About their business" + FitCriteria + rail rows where the
  view models already carry the data, and regress the table column set.

*Method note for re-verification: all findings above cite exact file:line in both trees; each
was produced by a full read of the 28 presentation files on both sides plus a live click-through
of every screen on 3000 and 3020 on 2026-08-18. No component was sampled — the read was
exhaustive for `features/accounts/**` in both trees.*
