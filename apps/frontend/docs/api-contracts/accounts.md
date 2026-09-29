# Accounts API contract

Status: implemented FI-2 read contract with authenticated frontend cutover.

Owner for backend integration: Aaryan.

As of the 2026-08-11 FI-2 cutover, Accounts and Contacts have no runtime fixture
mode. Their repositories always use the live `/frontend/v1` read surface.
Server Component reads derive the Clerk provider proof on the Next server,
resolve the selected workspace through Clue's membership store, and send
`Authorization` plus `X-Clue-Workspace-Id` to FastAPI. Browser-originated API
requests use the same resolver through the same-origin `/api/clue/**` BFF.
`CLUE_ACCOUNTS_API_BASE_URL`, `CLUE_WORKSPACE_ID`, legacy `X-Workspace-Id`, and
the unauthenticated Next rewrite are no longer part of this flow.

The frontend-authored proposal below is retained as history. The “As-built
backend read API” and “Authenticated frontend cutover” sections are the current
contract where the proposal differs.

## Shared response conventions

- Base path: `/api/v1`
- Content type: `application/json`
- Identifiers are opaque strings.
- Dates, when added, use ISO 8601 UTC strings.
- List pagination is cursor-based.
- Authentication is intentionally not assumed here; the chosen session layer
  should be applied consistently to every endpoint.

Error envelope:

```json
{
  "error": {
    "code": "ACCOUNT_NOT_FOUND",
    "message": "Account was not found",
    "requestId": "req_01J..."
  }
}
```

## Contract v1 — the accounts screens (ARV2 D3, 2026-09-08)

**This is the current contract for the five accounts-screen payloads.** It supersedes both older
sections below wherever they differ. Its presentation truth is the dummy frontend `clue-frontend`
@ `84f8ee7` (`src/features/accounts/model/*.ts`); its authority is
`docs/specs/ARV2-MASTER-PLAN.md` §6 and the D0 rulings, and *where each value is read from* —
endpoint, SQL, table column or claim `field_key` — is `docs/specs/ARV2-DATA-SOURCE-MAP.md`.

The contract is **executable**, not prose. The Zod schemas — with their amendments marked in place —
are this app's own accounts models at `apps/frontend/src/features/accounts/model/` (vendored under
`tests/api/contract_v1/zod/` at D3, moved here by the D4 re-lift), the pydantic wire models are
`platform/api/clue_api/frontend_read/contract_v1.py`, and
`tests/api/contract_v1/test_contract_v1.py` proves the three agree: the field sets match, a golden
payload of each shape parses through the real Zod, and **the field tables in this section list
exactly the fields on the wire**. Editing a table here without editing the models fails the build.

How to read the tables: `required` = the key is always present (its value may still be `null` when
the type says so); `optional` = the key is **omitted** when the backend does not know it. That
distinction is load-bearing — a Zod `.optional()` that is not `.nullable()` *rejects* an explicit
`null`, so "unknown" is an absent key, never a null one. Band-2 discipline still holds for ids,
enums and timestamps; the `*Label` fields are the deliberate, enumerated exceptions where the
backend owns the wording (a label is served precisely so the browser never derives it).

### Envelopes

| Endpoint | Envelope |
| --- | --- |
| `GET /frontend/v1/accounts` | `{ "data": Account[], "meta": { "total": int, "nextCursor": string \| null } }` |
| `GET /frontend/v1/accounts/{accountId}` | `{ "data": AccountDetail }` |
| `GET /frontend/v1/accounts/{accountId}/workspace` | `{ "data": AccountWorkspace }` |
| `GET /frontend/v1/accounts/{accountId}/contacts` | `{ "data": AccountContactSummary[], "meta": { "total": int } }` |
| `GET /frontend/v1/accounts/{accountId}/contacts/{contactId}` | `{ "data": AccountContactDetail }` |

The contacts envelope's `meta.total` is a v1 addition — the dummy's
`AccountContactsResponseSchema` carries only `data`, and the screen's "N contacts" count was
inferred. The payload schemas themselves are unchanged, which is why the parity test covers the
five payloads and not the envelopes.

**The `?contract=v1` parameter was removed 2026-09-09 (D4-b): one contract.** It selected between
these shapes and the FI-2 payloads while both were served; the FI-2 readers, their wire models and
the selector were all deleted, so every route now serves contract v1 unconditionally. A `contract`
query parameter is **ignored**, not refused — the adapters stopped sending it in the same change,
and 422ing a request the route can answer would have made the two halves undeployable apart.
Timestamps are UTC and `Z`-suffixed (`2026-09-08T12:00:00Z`) because `z.string().datetime()` accepts
an offset only with `{ offset: true }`, which these schemas do not set.

### D4 as built (2026-09-09)

The accounts feature in `apps/frontend` **is** the design build's (`clue-frontend`
`integration/live-backend-v1` @ `84f8ee7`), re-lifted file for file and re-pointed at these routes.
What follows is what shipped: the adapters, the fixture flag, the FI-2 behaviours the founder kept
and the ones that went, and the three rendering rules the wire leaves to the client.

#### Adapters

The five repositories in `src/features/accounts/data/` are the only code that talks to these
routes. Each one goes through `fetchRead` — the authenticated server request on a Server Component,
the same-origin `/api/clue/frontend/v1/…` BFF in the browser. (They sent `?contract=v1` on every
request until 2026-09-09; the surface serves one contract now, so no selector is sent.)

| Repository | Request |
| --- | --- |
| `accounts.repository.ts` | `GET /accounts?limit=200[&cursor=…][&projectId=…]` |
| `account-details.repository.ts` | `GET /accounts/{id}` |
| `account-workspace.repository.ts` | `GET /accounts/{id}/workspace` |
| `account-contacts.repository.ts` (list) | `GET /accounts/{id}/contacts` |
| `account-contacts.repository.ts` (detail) | `GET /accounts/{id}/contacts/{contactId}` |

**The list read returns the whole list.** The accounts table keeps the design build's browser-side
search, filter, sort and pagination, so `getAccounts()` follows `meta.nextCursor` at `limit=200`
(E1's `MAX_LIMIT`) and concatenates each page's `data` in server order. It stops after **25 pages —
5,000 rows** — and returns what it has; beyond that size the honest fix is server-side paging on the
screen, not a longer walk in the adapter. The returned `meta` is `{ total: <the server's own total>,
nextCursor: null }`: the count is the backend's, and there is nothing left for the caller to page.
`projectId` is the one query knob the backend owns and is forwarded; `search`, `sort`, `overallFit`,
`researchStatus`, `limit` and `cursor` are browser-side concerns and are deliberately **not** sent,
because E1 has no parameter for them and a silently-ignored parameter is worse than none.

**Record 404s are `null`, everything else throws.** `ACCOUNT_NOT_FOUND` and `CONTACT_NOT_FOUND`
resolve to `null` on E2, E3, E4 and E5 (on E4 that means "no such account" — an account with no
committee is `[]`). E1 never 404s. Every other failure — a wrong mount, a disabled read surface, an
auth or transport error — is a `ClueApiError`, which the page turns into a typed recovery screen via
`accounts-read-result.ts`. There is no retry against a second transport and no partial answer.

**Fixtures are an explicit opt-in, never a fallback.** `CLUE_ACCOUNTS_FIXTURE_MODE=true` — the exact
string, read in exactly one module, `data/repository-mode.ts` — selects the design build's fixture
repositories for local work. Any other value (including unset) selects the live adapters, and a live
read that fails **fails**: it never falls back to fixture data. No file in the feature reads
`CLUE_API_BASE_URL`; both rules are guarded by static tests in
`data/account-live-repositories.test.ts`.

#### The FI-2 behaviours that were kept

Three pieces of the FI-2 accounts screen outlived the re-lift (founder ruling 2026-09-09), ported
onto the design build's own components — no new component file, no Tailwind restyle:

- **Bulk actions with exactly two options.** The selection bar carries a project select with **Add
  to project** (`POST /frontend/v1/accounts/bulk-actions/add-to-project`, still the FI-2 route and
  still an idempotency-keyed submit) and **Send to chat** (the project chat transport, unchanged),
  plus Clear. The notice is the server's own counts (`"1 added · 1 already in project"`), never a
  client-side tally, and only accepted subjects are reflected onto the rows. Capabilities come from
  `readAccountBulkCapabilities()`; in fixture mode it returns the DISABLED constants without a
  backend call. A local draft row is never selectable. **The selection survives search, filter and
  sort** — it is cleared only by a successful add-to-project or the explicit Clear control.
- **The single-contact email lookup.** `startContactEmailLookup` then poll (3s) until
  `resolved`/`failed`, **capped at 40 polls (~2 minutes)**, after which the control states an honest
  timeout rather than polling forever. On `resolved` with exactly one address the row's `emailLabel`
  is set locally and its `emailStatus` becomes `"available"`; a conflicting multi-address result
  narrows to nothing and says "Multiple emails found". `emailLookup` is not a contract-v1 field, so
  this update is local to the loaded rows.
- **The typed recovery screen.** `accounts-read-result.ts` classifies transport failures and the
  accounts **layout** renders `accounts-recovery-screen.tsx` in place of the shell; detail,
  workspace and contact pages keep `notFound()` on a `null` record and let anything else surface.

#### The FI-2 behaviours that were dropped

- **The bulk email lookup** is gone entirely — `lookupContactEmails`, `readContactBulkCapabilities`,
  `ContactBulkCapabilities`, the contact-side bulk UI, and `BulkActionResponse.items[].emailLookup`
  in the frontend model. The backend still serves its bulk email route; nothing in the frontend
  calls it. A grep guard in `hooks/use-accounts-screen-controller.test.ts` keeps it out.
- **The Band-2 views** — `account-facts`, `evidence-list`, `table-pagination`, `account-avatar` and
  their models/formatters (`formatting.ts`, `prose.ts`, `evidence.ts`) — are deleted, not ported.
  The contract serves the labels those views used to derive.

#### Create is local and non-optimistic

There is **no write endpoint for account creation** on this surface yet. "New account" produces a
draft row entirely in the browser: `fitScore: null`, `overallFit: null`, bands `"Unknown"`,
`locationCount: 0`, empty `industryLabels` / `socials` / `projects` / `customFields`,
`primaryProjectId: null`, `researchStatus: "not_started"`, `logoPath: null`, and the `websiteUrl`
that was typed. Nothing is invented — no `fitScore: 0`, no `"Medium"` band. The row is marked
`isLocalDraft: true` on a **UI-only** type (`AccountSchema` does not carry the field and parsing
drops it), renders a text-only "Not saved yet", cannot be selected for a server action, and
disappears on reload. `POST /frontend/v1/accounts` is a recorded follow-up.

#### Three client-side rendering rules

- **The committee slot.** Contract v1 serves a `buying-committee` section inside `overviewDisplay`
  whose generated items restate the committee. The frontend renders the `buyingCommittee[]` **table**
  in that slot and drops the section's items; when a block omits the section, the split falls back to
  `how-to-approach` so the table stays where the design put it. (Whether the recipe should stop
  emitting that section is a D5 question.)
- **E4 `title: null` renders "—" client-side** (ruling S7). The dash is a presentation choice, not a
  wire value — the `"—"` placeholder exists on the wire only on E2's committee card.
- **`BuyingCommitteeMember.linkedinUrl` is nullable**; the link renders only when present.

#### Done on the backend (D4-b, 2026-09-09)

The FI-2 branches on E1/E2/E4/E5 and the `contract` query parameter are **deleted**: the FI-2
readers and wire models (`AccountDetail`/`neutralFacts`/`projectSections`, `ContactProfile`,
`AccountListRow`), `app.contract_mode`/`ContractDep`, the FI-2-only modules
(`committee.py`'s governed reader, `evidence.py`'s `EvidenceReference`, `prose.py`,
`account_activity.py` and the E6 route), the contact bulk email-lookup route, and the FI-2 route
tests all went with them. `tests/api/test_frontend_read_arv2_only_guard.py` is the standing rule
that keeps the old research lane off this path.

### D0 amendments (rulings)

The models differ from `84f8ee7` in exactly these places, each marked in the file with a
`// D0 ruling Rn/Sn` or `// D3 ruling` comment. `account-workspace.ts` is byte-identical.

| Ruling | Change | Why |
| --- | --- | --- |
| S11 | `ResearchStatusSchema` = `not_started \| in_progress \| needs_review \| completed \| suspended` | the backend's five M8D states; `fully_enriched` and `failed` never existed |
| S2 | `logoPath`, `accountLogoPath` become nullable | no logo pipeline exists in v1; the frontend renders its building glyph on `null`, and no third-party logo is fetched |
| R7 | `overallFit` becomes nullable | an unscored account has no band; `fitScore: 0` / `overallFit: "Medium"` was invented by `createLocalAccount` |
| S7 | contact `title` becomes nullable | no title claim → the row shows "—" rather than an invented title |
| S5 | `summaryParagraphs`, `businessParagraphs`, `overviewParagraphs` relax from `.min(1)` to `.default([])`; `AccountDetailSchema.industryLabels` likewise | the backend never fabricates prose for a legacy slot |
| R5 | `AccountContactDetailSchema` gains `emailClaimId` | the email chip resolves its evidence by claim id instead of substring-matching evidence text |
| R8 | `AccountContactDetailSchema` gains `lastModifiedAt` | the contact header showed the **account's** stamp; it is now the contact's own latest `verifiedAt` |
| D3 | `websiteUrl` becomes nullable | `'https://' + account_entity.primary_domain`, and an account may have no domain |
| D3 | `BuyingCommitteeMember.linkedinUrl` becomes nullable | a member resolved from a coverage row may have no LinkedIn URL; the dummy renders the link only when present |

### Backend-owned semantics

The frontend never re-derives any of these (master plan §6).

| Wire field | Backend rule |
| --- | --- |
| `ResearchEvidence` | one row per claim cited on the page; `claimId` = claim id; `quote` = the verbatim evidence span **or `null`** with `researchExcerpt` = the research sentence when no original-source quote exists (never a fabricated quotation); `sourceUrl` = source URL or `null` for private records (`verificationKind: "record"` — email checks, database rows); `verifiedAt` = `observed_at`; `publishedAt` = the source date when known; `mediaTimestamp` from the claim's media sub-fields; `outreachSafe` = the claim column; `sourceDomain` resolved server-side; `faviconUrl` may be `null` — the frontend resolves favicons by domain through its own proxy route; `title` = page title when captured |
| `body[].segments` | the display model's output is split into clause-level segments, each with the claim ids supporting that clause; chips render after the clause, not the sentence |
| `ResearchItem.priority` | the best (lowest number) `signal_priority` among the item's cited claims; the backend sorts P1 first |
| `fitDisposition` | on "Why they fit" items: `support` when the fit claim is satisfied, `caveat` when it is the honest negative |
| `intro[]` | narrative sections ("What they do", "Why they fit") carry their paragraphs as `intro`; items carry the evidence rows |
| `ResearchSection.empty` / `emptyMessage` | `empty` when the recipe matched nothing and the display model was not called; `emptyMessage` is optional server text, else the client prints "No {section} information found for {name}." Since 2026-09-16 it may instead read `"Not generated: <provider> refused (<reason>). Retries automatically."` (or `"… failing (<reason>). …"`) while a provider incident is open — see the note under the Section shape |
| `ResearchSection.pending` | `true` while a fleet task is writing the section (plan 2026-09-21): the section is `empty`, its `emptyMessage` is the served sentence `Synthesis in progress, please wait a few seconds.`, and the client re-reads the page every 5 s while any section is pending. Never `true` for a section whose recipe matched nothing. |
| restricted sections | `do-not-mention` / `context-only` / `watch-outs` are the only sections that ever receive `outreachSafe=false` claims; the frontend shows them under an "Internal notes" control and the overview page omits `watch-outs` |
| `sendLine` | contact page only; a separate field, never inside quotation marks; `channel` is served text |
| `h1` / counts / overall fit | `h1` is the section's served vocabulary **without counts or parentheticals**; counts are `items.length`; the overall fit is `overallFit`, never text parsed out of an `h1` |
| `insightSummary` | computed by the backend: `"{n} insights"` where n = items across non-restricted sections, and `"{m} people"` where m = committee members. The fixture's "42 reported in research" declared total is a fixture artifact and does not exist in production |
| `newSinceLastVisit` | the **frontend** computes it from `ResearchEvidence.verifiedAt` against a locally stored last-visit stamp; the backend serves `false` and keeps no visit row (decision D5) |
| `fitScore` / `overallFit` | both `null` when the account has not been scored (never `0`, never a guessed band); scoring writes both together (ruling R7 made `overallFit` nullable) |
| `owner` / `createdBy` | workspace users (CRM data, never agent-written); `owner` nullable, `createdBy` recorded at creation; display precedence: assigned `owner`, else `createdBy`, else "Unassigned" (ruling R6) — never the current viewer |
| `tenureLabel` / `employmentStartedAt` | the backend serves both; the frontend displays `tenureLabel` as-is and never computes tenure from the browser clock; `employmentStartedAt` exists for sorting and date display |
| `artifacts[]` | the workspace endpoint projects account-associated generated artifacts with `accountId`; `updatedAt` comes from the artifact record; no invented dates. Served since 2026-09-30 (S9's later slice): the account's design documents from every project |
| `activity[]` | actor is `clue` for agent actions and `person {id,name}` for user actions; `occurredAt` is ISO-8601; an unattributed event carries no actor at all; `isSample` appears only in fixtures |
| `customFields` | registry custom variables whose values are claims; `presentation` comes from the registry row; the first four active client-pack fields in registry order are `primary` (ruling S6) |
| `BuyingCommitteeMember.email` + `emailClaimId` | from the `core.work_email` claim; verification state lives in the evidence hover, not inline |
| `influence` | legacy persona-derived default (S8); contextual unverified/excluded membership returns null |
| `previewTitle` | `= name` in v1 (ruling S4) |
| display gating | E2–E5 select claims through `arv2_display_allowed` (ruling S10): use-class rules and the sensitive fail-close stay, but a `WEAK` identity binding no longer hides an `outreachSafe = true` claim |

### Not on the wire

By design, and not to be added without a ruling:

- `field_key` — the claim's registry key. Generic field rendering exists only for `customFields`.
- `use_class` — the compliance use-class of a claim.
- `source_type` — the resolver/source species behind a claim.
- **avatar images** for accounts and contacts beyond the optional `avatarUrl` asset path; no
  third-party avatar or logo fetch happens in v1.
- **dates on source chips and hover cards** (ruling R1): `verifiedAt` and `publishedAt` are served
  but rendered nowhere. `verifiedAt` feeds the frontend's new-since-last-visit computation.

The Next.js `/api/source-favicon` route and the accounts layout shell stay frontend-owned.

### Shared shapes

`ResearchEvidence`, referenced by E2, E3 and E5:

| field | type | required | rule |
| --- | --- | --- | --- |
| `claimId` | string | required | the claim's id — the join key for every citation chip |
| `sourceUrl` | url \| null | required (nullable) | `null` for private records |
| `sourceDomain` | string \| null | required (nullable) | resolved server-side |
| `faviconUrl` | url \| null | required (nullable) | the frontend may resolve its own |
| `title` | string \| null | required (nullable) | page title when captured |
| `quote` | string \| null | required (nullable) | the verbatim span, or `null` |
| `researchExcerpt` | string | optional | the research sentence when there is no quote |
| `publishedAt` | date (`YYYY-MM-DD`) \| null | required (nullable) | source date when known |
| `verifiedAt` | date (`YYYY-MM-DD`) | required | the claim's `observed_at` |
| `verificationKind` | `verified` \| `record` | optional (default `verified`) | `record` = a private record |
| `mediaTimestamp` | string \| null | required (nullable) | from the claim's media sub-fields |
| `provider` | string \| null | required (nullable) | the resolver that retrieved it |
| `outreachSafe` | bool | required | the claim column |

`ResearchDisplayBlock`, referenced by E2 (`overviewDisplay`), E3 (`insightsDisplay`) and E5
(`contactDisplay`):

```
DisplayBlock { page ∈ insights|overview|contact, sections[] }
  Section  { key, h1, empty, items[], intro[]?, restricted=false, defaultOpen=false, emptyMessage?, pending=false }
  Item     { id, h2, body[], sendLine|null, contactRefs[], inlineLead?, fitDisposition? ∈ support|caveat,
             subject?, priority ∈ 1|2|3, newSinceLastVisit=false }
  Sentence { text, claimIds[], segments[]? { text, claimIds[] } }
  SendLine { channel, text, claimIds[] }
  ContactRef { accountId, contactId, name, title?, persona?, emailState? ∈ verified|unverified|not_requested, avatarUrl? }
```

**`emptyMessage` while a provider incident is open (2026-09-16).** Spec
`docs/superpowers/specs/2026-09-16-provider-incidents-design.md`. When this read's own generation
halted on a provider, or when a provider incident is open right now, every section that is `empty`
and was not generated by this read carries the one served sentence

```
Not generated: model provider refused (key limit exceeded). Retries automatically.
```

— `"<provider label> refused (<reason>)"` for a refusal (a decision no retry changes) and
`"<provider label> failing (<reason>)"` for a fault that usually passes. The labels are the
backend's words (`clue_api.provider_incidents.provider_display` / `reason_words`), so the frontend
renders `emptyMessage` verbatim and never parses a provider or reason out of it. Sections that this
read *did* generate are untouched, and a page with nothing wrong keeps the client's
"No {section} information found for {name}." default.

**Shared sections (2026-09-21).** `context-only` on the insights page is the overview's
`watch-outs` block; `contact-insights` is the committee's `why-this-person` blocks in committee
order. Same items, same claim ids, the insights page's own `h1`/`defaultOpen`. They are never
`pending` on the insights page — their owner page carries that.

`BuyingCommitteeMember` (E2): `{ contactId, name, title, persona, email|null, emailClaimId|null,
linkedinUrl|null, whyTheyMatter }` — `persona` is served display text, e.g. `Economic buyer`, as it
is on every `persona` slot including `ContactRef`'s. `AccountOwner` (`owner`, `createdBy`, and the `person` actor):
`{ id, name, avatarUrl? }`. `AccountActivity` (E2, E3): `{ id, kind ∈
contacts|summary|created|artifact|updated, text, timeLabel, actor? ({type:"clue"} \| {type:"person",
id, name, avatarUrl?}), action?, occurredAt?, isSample? }`.

### E1 — Accounts list row (AccountSchema)

`GET /frontend/v1/accounts` → `data[]`.

| field | type | required | rule |
| --- | --- | --- | --- |
| `id` | string | required | opaque `account_entity` id |
| `name` | string | required | the account's resolved name |
| `logoPath` | path (`/…`) \| null | required (nullable) | `null` in v1 — no logo pipeline (S2) |
| `websiteUrl` | url \| null | required (nullable) | `https://` + `primary_domain`; `null` when there is no domain |
| `researchStatus` | enum (5) | required | the latest M8D job for this (account, project) |
| `researchStatusLabel` | string | optional | served wording for the status chip |
| `researchIsRefreshing` | bool | optional (default `false`) | a re-research run is in flight over an already-researched account |
| `overallFit` | `High` \| `Medium` \| `Low` \| null | required (nullable) | `null` until scored (R7) |
| `fitScore` | int 0–100 \| null | required (nullable) | `null` until scored; never `0` for unknown |
| `revenueBand` | string | required | served wording for the `core.revenue_band` claim — `"$10M–50M"`, `"$1B+"`, `"under $1M"`; `"Unknown"` when absent |
| `employeeBand` | string | required | the `core.employee_count` claim, banded |
| `locationCount` | int ≥ 0 | required | distinct known locations |
| `locationsLabel` | string | optional | served wording for the locations cell |
| `owner` | AccountOwner \| null | optional | `null` when unassigned — never the current viewer (R6) |
| `createdBy` | AccountOwner \| null | optional | recorded at creation |
| `industryLabels` | string[] | optional (default `[]`) | industry claims |
| `socials` | AccountSocial[] | optional (default `[]`) | `{id, label ∈ LinkedIn\|Twitter\|Facebook\|Instagram, url}` |
| `createdAt` | ISO-8601 datetime | optional | `account_entity.created_at` |
| `lastModifiedAt` | ISO-8601 datetime | optional | the account's latest claim `observed_at` |
| `primaryProjectId` | string \| null | optional | element 0 of the recorded membership policy |
| `projects` | AccountProject[] | optional (default `[]`) | `{id, name}` per targeting project |
| `customFields` | AccountCustomField[] | optional (default `[]`) | `{id, label, value, presentation ∈ text\|badge\|score, primary}` |

**FI-2 fields kept until D4.** The existing `/frontend/v1/accounts` row still serves `domain`,
`employeeCount`, `logoUrl`, `scores`, `projectResearchStatus`, `projectMemberships` and
`updatedAt`. They are superseded by the table above and are removed when the frontend re-lift (D4)
stops reading them.

### E2 — Account detail (AccountDetailSchema)

`GET /frontend/v1/accounts/{accountId}` → `data`. **Not a superset of E1**: the detail serves
labels where the list serves bands, and drops the list-only membership fields.

| field | type | required | rule |
| --- | --- | --- | --- |
| `id` | string | required | opaque `account_entity` id |
| `name` | string | required | the account's resolved name |
| `previewTitle` | string | required | `= name` in v1 (S4) |
| `logoPath` | path (`/…`) \| null | required (nullable) | `null` in v1 (S2) |
| `websiteUrl` | url \| null | required (nullable) | `null` when there is no domain |
| `websiteLabel` | string | required | the hostname the header prints — served, not parsed in the browser |
| `researchStatus` | enum (5) | required | latest M8D job for this (account, project) |
| `researchStatusLabel` | string | optional | served wording for the status chip |
| `owner` | AccountOwner \| null | optional | `null` when unassigned (R6) |
| `createdBy` | AccountOwner \| null | optional | recorded at creation |
| `industryLabels` | string[] | optional (default `[]`) | relaxed from `.min(1)` (S5) |
| `headcountLabel` | string | required | the rail's headcount wording |
| `locationsLabel` | string | required | the rail's locations wording |
| `revenueLabel` | string | required | served wording read from the `core.annual_revenue` object — `"$10M–25M"`, `"$10M+"`, `"up to $25M"`; else the band as a label (as E1's `revenueBand`); else `"Unknown"` |
| `foundedLabel` | string | optional | omitted when the founding year is unknown |
| `fundingLabel` | string | optional | served wording — the latest round joined to the running total, `"Series C · $60M · $130.5M"` (a round with no currency of its own borrows the total's); omitted when funding is unknown |
| `fitScore` | int 0–100 \| null | required (nullable) | `null` until scored |
| `fitScoreLabel` | string | optional | served wording for the score |
| `createdAt` | ISO-8601 datetime | required | `account_entity.created_at` |
| `lastModifiedAt` | ISO-8601 datetime | required | the account's latest claim `observed_at` |
| `socials` | AccountSocial[] | optional (default `[]`) | as E1 |
| `customFields` | AccountCustomField[] | optional (default `[]`) | as E1 |
| `overallFit` | `High` \| `Medium` \| `Low` \| null | required (nullable) | `null` until scored (R7) |
| `summaryParagraphs` | string[] | optional (default `[]`) | legacy prose slot; never fabricated (S5) |
| `businessParagraphs` | string[] | optional (default `[]`) | legacy prose slot; never fabricated (S5) |
| `fitCriteria` | AccountFitCriterion[] | required | `{id, matched, title, evidence}`; legacy, may be `[]` |
| `contacts` | AccountContact[] | required | `{id, name, avatarUrl?, title?, persona?, emailVerified?, hasDetail}`; `persona` is served display text, e.g. `Economic buyer` |
| `insights` | AccountInsight[] | required | `{id, source ∈ link\|linkedin\|x, title, dateLabel, url}` |
| `activity` | AccountActivity[] | required | see Shared shapes |
| `headerMetadata` | string[] | optional (default `[]`) | the header's served chip strings |
| `researchEvidence` | ResearchEvidence[] | optional (default `[]`) | one row per claim cited by `overviewDisplay` |
| `overviewDisplay` | DisplayBlock (`page: "overview"`) | optional | omitted when the overview has not been generated |
| `buyingCommittee` | BuyingCommitteeMember[] | optional (default `[]`) | `linkedinUrl` nullable (D3) |

**FI-2 fields kept until D4.** `neutralFacts`, `projectSections`, `committee`, `coverage`,
`summary`, `redirectedFrom`, `aliases`, `registryIds`, `hqGeo`, `domain`.

### E3 — Account workspace (AccountWorkspaceSchema)

`GET /frontend/v1/accounts/{accountId}/workspace` → `data`. The insights and artifacts tabs.

| field | type | required | rule |
| --- | --- | --- | --- |
| `accountId` | string | required | echoes the path id |
| `insights` | WorkspaceInsight[] | required | `{id, source ∈ link\|linkedin\|x, title, sourceLabel, url, summary}` |
| `insightSummary` | string[] | optional (default `[]`) | computed: `"{n} insights"`, `"{m} people"` |
| `researchEvidence` | ResearchEvidence[] | optional (default `[]`) | one row per claim cited by `insightsDisplay` |
| `insightsDisplay` | DisplayBlock (`page: "insights"`) | optional | omitted when the insights page has not been generated |
| `artifacts` | AccountArtifact[] | required | `{id, title, type ∈ presentation\|document\|web\|ad\|email, accountId?, projectName?, updatedAt?, thumbnailPath, lastEditedLabel}`; served since 2026-09-30: the design documents made for this account (through `design_account.account_entity_id`) from **every** project, newest first, `projectName` = the project's name, archived ones omitted; `thumbnailPath` = the gallery's `/api/clue/design/documents/{id}/thumbnail?v={current_version}` (render `unoptimized`: session-authenticated route); `type` `ad` or `web` |
| `activity` | AccountActivity[] | required | see Shared shapes |

**FI-2 fields kept until D4.** None — this endpoint is new in v1.

### E4 — Contacts list row (AccountContactSummarySchema)

`GET /frontend/v1/accounts/{accountId}/contacts` → `data[]`.

| field | type | required | rule |
| --- | --- | --- | --- |
| `id` | string | required | opaque `contact_entity` id |
| `name` | string | required | the contact's resolved name |
| `title` | string \| null | required (nullable) | `null` when no title claim exists; the row shows "—" (S7) |
| `persona` | string | required | served display text, e.g. `Economic buyer` — never the backend vocabulary value |
| `membershipState` | `candidate` \| `supported` \| `needs_verification` \| `excluded` \| null | optional (nullable) | assessment for the selected project/context; null for legacy data |
| `outreachEligible` | boolean | optional | false prevents outreach assumptions even when a contact channel exists |
| `membershipGaps` | string[] | optional | explicit unresolved employment/remit evidence, never inferred from geography alone |
| `personaTone` | `olive`\|`orange`\|`blue`\|`cyan`\|`green`\|`pink`\|`red` | required | the served chip tone for that persona |
| `influence` | `High` \| `Medium` \| `Low` \| null | required | null for contextual unverified/excluded membership; otherwise persona-derived default (S8) |
| `avatarUrl` | url or path (`/…`) | optional | omitted when unknown; no third-party avatar fetch |
| `emailStatus` | `available` \| `lookup` | required | whether a work-email claim exists |
| `emailLabel` | email | optional | present only when `emailStatus = available` |
| `socials` | (`linkedin`\|`x`\|`facebook`\|`instagram`\|`whatsapp`)[] | required | which social chips to render |
| `profileAction` | `none` \| `preview` \| `page` | optional (default `none`) | replaces the dummy's hard-coded featured contact |

**FI-2 fields kept until D4.** `titleRestricted`, `roleOnCommittee`, `signals`, `projectIds`,
`emailLookup`, row-level `linkedinUrl`, `professionalFacts`, the FI-2-shaped `evidence`, and
`redirectedFrom`.

### E5 — Contact detail (AccountContactDetailSchema)

`GET /frontend/v1/accounts/{accountId}/contacts/{contactId}` → `data`. The E4 row plus:

| field | type | required | rule |
| --- | --- | --- | --- |
| `id` | string | required | as E4 |
| `name` | string | required | as E4 |
| `title` | string \| null | required (nullable) | as E4 (S7) |
| `persona` | string | required | as E4 — served display text, e.g. `Economic buyer` |
| `membershipState` | `candidate` \| `supported` \| `needs_verification` \| `excluded` \| null | optional (nullable) | assessment for the selected project/context; null for legacy data |
| `outreachEligible` | boolean | optional | false prevents outreach assumptions even when a contact channel exists |
| `membershipGaps` | string[] | optional | explicit unresolved employment/remit evidence, never inferred from geography alone |
| `personaTone` | enum (7) | required | as E4 |
| `influence` | `High` \| `Medium` \| `Low` \| null | required | as E4 |
| `avatarUrl` | url or path (`/…`) | optional | as E4 |
| `emailStatus` | `available` \| `lookup` | required | as E4 |
| `emailLabel` | email | optional | as E4 |
| `socials` | enum[] | required | as E4 |
| `profileAction` | `none` \| `preview` \| `page` | optional (default `none`) | as E4 |
| `accountId` | string | required | the owning account |
| `accountName` | string | required | for the header crumb |
| `accountLogoPath` | path (`/…`) \| null | required (nullable) | `null` in v1 (S2) |
| `recentSignalsLabel` | string | required | the rail's recent-signals wording |
| `linkedinLabel` | string | required | the rail's LinkedIn wording |
| `linkedinUrl` | url | required | the contact's own profile URL |
| `xLabel` | string | optional | omitted when there is no X handle |
| `xUrl` | url | optional | omitted when there is no X handle |
| `emailVerifiedAt` | date (`YYYY-MM-DD`) | optional | when the email check ran |
| `emailClaimId` | string \| null | optional | the `core.work_email` claim behind the chip (R5) |
| `locationLabel` | string | optional | the rail's location wording |
| `bestFirstChannelLabel` | string | optional | the rail's channel recommendation |
| `educationLabel` | string | optional | the rail's education wording |
| `tenureLabel` | string | optional | served — never computed from the browser clock (R8) |
| `employmentStartedAt` | date (`YYYY-MM-DD`) | optional | for sorting and date display |
| `linkedinFollowers` | int ≥ 0 | optional | omitted when unknown |
| `linkedinCreator` | bool | optional | omitted when unknown |
| `locationClaimId` | string | optional | the claim behind the location row |
| `reports` | ContactRef[] | optional (default `[]`) | who reports to this person |
| `overviewParagraphs` | string[] | optional (default `[]`) | legacy prose slot; never fabricated (S5) |
| `evidence` | ContactEvidence[] | required | `{id, source ∈ link\|linkedin\|x, title, dateLabel, url}` |
| `researchEvidence` | ResearchEvidence[] | optional (default `[]`) | one row per claim cited by `contactDisplay` |
| `contactDisplay` | DisplayBlock (`page: "contact"`) | optional | omitted when the contact page has not been generated |
| `lastModifiedAt` | ISO-8601 datetime | required | the **contact's** own latest `verifiedAt` (R8) |
| `customFields` | AccountCustomField[] | optional (default `[]`) | as E1, keyed to the contact's own registry claims |

The four non-Nick fixture contact pages synthesize an "Account context" section (ruling R10); that
is fixture-only — a production page's sections come from `contactDisplay` and nothing else.

**FI-2 fields kept until D4.** `titleRestricted`, `roleOnCommittee`, `signals`, `projectIds`,
`emailLookup`, `professionalFacts`, the FI-2-shaped `evidence`, and `redirectedFrom`. *(Historical:
all of these went with the FI-2 readers on 2026-09-09 — see "Done on the backend (D4-b)" above.)*

## Implemented frontend read contract

> **Historical.** This is the frontend-authored *proposal* that started the integration. Contract v1 above is what is served; nothing here is live. Kept because the rulings further down cite it.

### `GET /api/v1/accounts`

Returns accounts for the Accounts table.

Query parameters:

| Parameter | Type | Notes |
| --- | --- | --- |
| `search` | string | Case-insensitive company-name search |
| `researchStatus` | enum | `not_started`, `in_progress`, `fully_enriched`, `failed` |
| `overallFit` | enum | `High`, `Medium`, `Low` |
| `projectId` | string | Return accounts associated with this project context |
| `sort` | enum | `name_asc`, `name_desc`, `project_asc`, `project_desc`, `fit_score_desc`, `fit_score_asc` |
| `cursor` | string | Opaque cursor from the previous response |
| `limit` | integer | Recommended default 50, maximum 100 |

Success response:

```json
{
  "data": [
    {
      "id": "openai",
      "name": "OpenAI",
      "logoPath": "/logos/openai.svg",
      "websiteUrl": "https://openai.com",
      "researchStatus": "fully_enriched",
      "researchIsRefreshing": true,
      "overallFit": "High",
      "fitScore": 75,
      "revenueBand": "$1 - $10M",
      "employeeBand": "100-200",
      "locationCount": 10,
      "primaryProjectId": "10m-landing-page-campaign",
      "projects": [
        {
          "id": "10m-landing-page-campaign",
          "name": "10x revenue campaign"
        },
        {
          "id": "conference-2026",
          "name": "conference 2026"
        }
      ]
    }
  ],
  "meta": {
    "total": 1,
    "nextCursor": null
  }
}
```

Current frontend validation is defined in
`src/features/accounts/model/account.ts`. Until a shared contract package is
introduced, that schema is the authoritative shape for this screen.

`projects` is a many-to-many account relationship. An account can participate
in multiple project contexts without duplicating the canonical account record.
`primaryProjectId` must reference one member of `projects` when present and is
used for stable project sorting; account name is the secondary sort key.
`projectId` filters by membership in the full `projects` array. Project is the
campaign/context boundary in Clue; Campaign is not a separate atomic entity.
Populate the Project filter catalog from `GET /api/v1/projects/sidebar`
(documented in `projects.md`) rather than inferring the complete catalog from a
paginated account response.

`logoPath` is frontend-compatible today. A future backend may instead return a
stable `logoUrl`; if that change is made, update the schema and adapters
together rather than mapping it inside table components.

### `GET /api/v1/accounts/:accountId`

Returns the record used by both the account preview drawer and the full account
page. The frontend validates this response in
`src/features/accounts/model/account-detail.ts`.

Success response:

```json
{
  "data": {
    "id": "openai",
    "name": "OpenAI",
    "previewTitle": "Synergy medical group",
    "logoPath": "/logos/openai-detail.svg",
    "websiteUrl": "https://openai.com",
    "websiteLabel": "www.openai.com",
    "researchStatus": "fully_enriched",
    "sizeLabel": "Large enterprise",
    "locationsLabel": "Global",
    "revenueLabel": "Private / not disclosed",
    "referralFit": "Medium",
    "directAccessFit": "High",
    "recallFit": "Medium",
    "overallFit": "High",
    "summaryParagraphs": ["Account summary paragraph"],
    "businessParagraphs": ["Business description paragraph"],
    "fitCriteria": [
      {
        "id": "enterprise-growth",
        "matched": true,
        "title": "Operates a large and rapidly growing enterprise business",
        "evidence": "Supporting account evidence"
      }
    ],
    "contacts": [
      {
        "id": "denise-dresser",
        "name": "Denise Dresser",
        "avatarUrl": "https://cdn.cluehq.ai/contacts/denise-dresser.jpg"
      }
    ],
    "insights": [
      {
        "id": "enterprise-revenue",
        "source": "link",
        "title": "OpenAI says enterprise now represents more than 40% of revenue",
        "dateLabel": "April 8, 2026",
        "url": "https://openai.com/"
      }
    ],
    "activity": [
      {
        "id": "contacts-added",
        "kind": "contacts",
        "text": "Clue added 14 new contacts",
        "timeLabel": "1 hour ago"
      }
    ]
  }
}
```

Valid `source` values are `link`, `linkedin`, and `x`. Valid `kind` values are
`contacts`, `summary`, and `created`.

Return `404` with the shared error envelope when `accountId` is unknown.

`previewTitle` exists because the source MVP frame displays a contextual drawer
title separately from the normalized account name. The backend may return the
same value for both fields when that distinction is not needed.

### `GET /api/v1/accounts/:accountId/contacts`

> Historical proposal. The FI-2 as-built Contacts contract begins below. Slice 10 supersedes the
> proposed `emailStatus` placeholder with a durable `emailLookup` result and two explicit POST
> mutations; no browser timer represents provider success.

Returns the contact-table rows. Contact records are kept outside the account
detail response so the backend can paginate and refresh them independently.

Each record includes `id`, `name`, `title`, `persona`, `personaTone`,
`influence`, `avatarUrl`, `emailStatus`, and a `socials` array. Runtime
validation lives in `src/features/accounts/model/account-contact.ts`.

`avatarUrl` is supplied by the backend or enrichment provider and should be a
stable, cacheable CDN URL. The frontend accepts either an absolute URL or a
public fixture path, displays initials when the image fails, and does not
scrape LinkedIn in the browser.

Recommended query parameters: `search`, `persona`, `influence`, `cursor`, and
`limit`.

### `GET /api/v1/accounts/:accountId/contacts/:contactId`

Returns one complete contact profile, including account identity, recent-signal
label, LinkedIn/X links, overview paragraphs, and evidence records. Return `404`
when either identifier is unknown.

### `GET /api/v1/accounts/:accountId/workspace`

> Historical proposal. FI-2 Slice 6 supersedes the Activity portion with the
> dedicated durable `GET /frontend/v1/accounts/{accountId}/activity` contract
> below. FI-2 Slice 7 removes Artifacts from the workspace model because no live
> Account-artifact read contract exists. The model now covers only the
> still-unserved legacy Insights proposal.

The remaining placeholder payload is:

```json
{
  "data": {
    "accountId": "openai",
    "insights": [
      {
        "id": "cro-appointment",
        "source": "link",
        "title": "Denise Dresser appointed Chief Revenue Officer",
        "sourceLabel": "https://openai.com/index/leadership",
        "url": "https://openai.com/",
        "summary": "Evidence summary"
      }
    ]
  }
}
```

The remaining schema is in `src/features/accounts/model/account-workspace.ts`.
Artifacts and Activity are no longer represented by this payload. A future
artifact integration adds its own typed live repository rather than reviving
this fixture-era aggregate.

## Planned write and configuration endpoints

### `POST /api/v1/accounts/query`

Executes the multi-condition filter shell without encoding a rule tree into a
long URL. The frontend validates rule shapes in
`src/features/accounts/model/account-query.ts`.

```json
{
  "search": "open",
  "rules": [
    {
      "id": "account-filter-1",
      "field": "project",
      "operator": "is",
      "value": "10m-landing-page-campaign",
      "join": "and"
    },
    {
      "id": "account-filter-2",
      "field": "overallFit",
      "operator": "is",
      "value": "High",
      "join": "and"
    }
  ],
  "sort": "project_asc",
  "cursor": null,
  "limit": 50
}
```

Allowed fields are `name`, `project`, `researchStatus`, `overallFit`,
`fitScore`, `revenueBand`, `employeeBand`, and `locationCount`. Allowed
operators are `contains`, `does-not-contain`, `is`, `is-not`, `greater-than`,
and `less-than`; the backend must reject invalid field/operator combinations
with `400 INVALID_FILTER_RULE`. Project values are project IDs, not display
labels. Apply rules in authored order, then sort, then cursor pagination.
Return the same response envelope as `GET /api/v1/accounts`.

### `POST /api/v1/accounts`

Create an account.

```json
{
  "name": "Acme",
  "websiteUrl": "https://acme.example"
}
```

Returns `201` with one account object.

### `PATCH /api/v1/accounts/:accountId`

Update editable account fields. Use partial-update semantics and return the
updated account object.

### `DELETE /api/v1/accounts/:accountId`

Archive or delete an account according to the backend retention policy.
Returns `204` on success.

### `POST /api/v1/accounts/:accountId/research`

Start or refresh research. Returns `202`.

```json
{
  "data": {
    "jobId": "research_01J...",
    "accountId": "openai",
    "status": "queued"
  }
}
```

### `GET /api/v1/accounts/:accountId/research`

Return current job status so the frontend can reconcile live state.

### `GET /api/v1/accounts/table-config`

Return the current user's saved column visibility and ordering.

### `PUT /api/v1/accounts/table-config`

Persist column visibility, ordering, widths, sort configuration, and the
authored filter rules. Project IDs must remain opaque stable identifiers.

## Integration checklist

1. Implement both frontend read contracts exactly as the validated shapes
   above.
2. Configure authentication plus the server-only `CLUE_API_BASE_URL`; there is
   no Accounts-specific origin or workspace environment variable.
3. Keep browser calls same-origin through `/api/clue`; Server Components call
   the same authenticated backend primitive directly and never loop back
   through their own Route Handler.
4. Derive provider proof and `X-Clue-Workspace-Id` on the Next server. Never
   accept a browser-authored workspace or authorization header.
5. Replace `logoPath` only through the schema and repository boundary.
6. Add contract tests using representative success, empty, and error payloads.
7. Keep table and detail records independently fetchable so list responses do
   not grow with research paragraphs, contacts, insights, and activity.
8. Keep accounts canonical and connect them to projects many-to-many; do not
   introduce Campaign as a second project-like account entity.
9. Apply filtering before sorting and cursor pagination, with account name as
   the project-sort tie-breaker.

## As-built backend read API (FI-2 slice 1, 2026-08-08) — ratified deviations

> **Historical — the FI-2 shapes below are no longer served.** They were deleted with the FI-2 readers on 2026-09-09 (D4-b); contract v1 above is the whole read surface. Kept because the ratified deviations and rulings recorded here are cited by the memory notes and by later sections of this file.

The proposal above is unchanged and stays the frontend's authored view. This
section records what the backend actually serves after FI-2 slice 1, so the Zod
schemas and HTTP adapters are written against the real wire. Every shape below
is copied from a passing test: `tests/integration/test_fi2_slice1_read_layer.py`
drives all four endpoints over one seeded workspace, and
`tests/api/test_frontend_read_*.py` cover each endpoint on its own.

The surface is flag-gated (`frontend_read_enabled`, default off; the routes 404
when it is off) and is served under `/frontend/v1`. The router's isolated
development fallback accepts `X-Workspace-Id`; an authenticated application
overrides that resolver with Lane B's principal service, which requires provider
proof plus `X-Clue-Workspace-Id`. The production frontend uses only the latter.
`GET /frontend/v1/health` remains an unscoped liveness probe.
It is read-only: no create, update, delete,
research-launch, query-POST, table-config, `search`, or `sort` endpoint exists
yet, and the only list query parameters are `projectId`, `cursor`, and `limit`.

### Endpoints and wire shapes

| Endpoint | Envelope |
| --- | --- |
| `GET /frontend/v1/accounts` | `{ data: [...], meta: { total, nextCursor } }` |
| `GET /frontend/v1/accounts/{accountId}` | the account object itself, no `data` wrapper |
| `GET /frontend/v1/accounts/{accountId}/contacts` | `{ data: [...], meta: { total } }` |
| `GET /frontend/v1/accounts/{accountId}/contacts/{contactId}` | the contact object itself, no `data` wrapper |
| `GET /frontend/v1/accounts/{accountId}/activity` | the durable activity object itself, no `data` wrapper |

List row:

```json
{
  "data": [
    {
      "id": "0f0f4e8c-4d1a-4f0b-9f2d-2b7a1c0d5e11",
      "name": "Acme",
      "domain": "acme.test",
      "employeeCount": 1200,
      "revenueBand": "100m_500m",
      "logoUrl": null,
      "projects": [
        {
          "projectId": "prj_a",
          "name": "Project A",
          "addedVia": "discovered",
          "addedAt": "2026-08-01T12:00:00Z"
        },
        {
          "projectId": "prj_b",
          "name": "Project B",
          "addedVia": "imported",
          "addedAt": "2026-08-01T12:05:00Z"
        }
      ],
      "primaryProjectId": "prj_a",
      "scores": [
        {
          "projectId": "prj_a",
          "fit": 0.81,
          "intent": 0.4,
          "icpKey": "alpha",
          "icpVersion": 1,
          "scoredAt": "2026-08-01T12:00:00Z"
        },
        {
          "projectId": "prj_b",
          "fit": 0.55,
          "intent": null,
          "icpKey": "beta",
          "icpVersion": 3,
          "scoredAt": "2026-08-01T12:00:00Z"
        }
      ],
      "researchStatus": [
        { "projectId": "prj_a", "status": "needs_review" },
        { "projectId": "prj_b", "status": "in_progress" }
      ],
      "updatedAt": "2026-08-01T12:00:00Z"
    }
  ],
  "meta": { "total": 3, "nextCursor": null }
}
```

Account detail:

```json
{
  "id": "0f0f4e8c-4d1a-4f0b-9f2d-2b7a1c0d5e11",
  "name": "Acme",
  "domain": "acme.test",
  "aliases": ["acme"],
  "registryIds": {},
  "hqGeo": null,
  "redirectedFrom": null,
  "summary": {
    "state": "available",
    "paragraphs": ["Acme is a multi-site healthcare operator."],
    "researchOutcome": "completed"
  },
  "neutralFacts": [
    {
      "fieldKey": "core.employee_count",
      "value": 1200,
      "freshness": "fresh",
      "observedAt": "2026-08-01T12:00:00Z",
      "provider": "clearbit"
    }
  ],
  "projectSections": [
    {
      "projectId": "prj_a",
      "name": "Project A",
      "addedVia": "discovered",
      "addedAt": "2026-08-01T12:00:00Z",
      "scores": [
        { "fit": 0.81, "intent": 0.4, "icpKey": "alpha", "icpVersion": 1, "scoredAt": "2026-08-01T12:00:00Z" }
      ],
      "narratives": [
        {
          "fieldKey": "account.value_narrative",
          "value": { "persona": "economic_buyer", "argument": "...", "angle_label": "roi" },
          "observedAt": "2026-08-01T12:00:00Z",
          "provider": "narrative_synthesis"
        }
      ],
      "insights": [
        {
          "fieldKey": "fi2read.campaign_insight",
          "value": "insight for A",
          "observedAt": "2026-08-01T12:00:00Z",
          "provider": "deep_research"
        }
      ]
    },
    {
      "projectId": null,
      "name": null,
      "addedVia": null,
      "addedAt": null,
      "scores": [],
      "narratives": [],
      "insights": []
    }
  ],
  "committee": [
    {
      "contactId": "3a1c...",
      "name": "Dana Buyer",
      "persona": "economic_buyer",
      "roleOnCommittee": "economic_buyer",
      "projectIds": ["prj_a", "prj_b"]
    }
  ],
  "coverage": {
    "researchedFieldCount": 6,
    "unresolvedFieldKeys": ["healthcare.npi"],
    "unresolvedFields": [
      {
        "fieldKey": "healthcare.npi",
        "description": "National Provider Identifier (deterministic registry id; tier-1)."
      }
    ]
  }
}
```

Contacts row and profile:

```json
{
  "data": [
    {
      "id": "3a1c...",
      "name": "Dana Buyer",
      "title": "VP Finance",
      "titleRestricted": false,
      "persona": "economic_buyer",
      "roleOnCommittee": {
        "value": "economic_buyer",
        "confidence": 0.87,
        "reasoning": "Owns the financial approval for this workflow."
      },
      "linkedinUrl": "https://linkedin.com/in/dana-buyer",
      "projectIds": ["prj_a", "prj_b"],
      "signals": { "typeCount": 1 },
      "emailLookup": null
    }
  ],
  "meta": { "total": 1 }
}
```

The profile is that row plus `accountId`, `accountName`, `redirectedFrom`,
`overview` (the same typed prose state as Account `summary`),
`professionalFacts` (`{ fieldKey, claimId, value, observedAt, provider,
restricted }`), and the claim-mapped `evidence` records specified by the FI-2
slice-5 section below.

`roleOnCommittee.reasoning` is the nullable agent-authored rationale from the same governed role
claim as `value` and `confidence`. The backend serves it whenever held and never derives it from a
title. The frontend schema preserves it, while the frontend remains the display authority: the
current buying-committee table and profile intentionally do not render this field.

`emailLookup` is `null` until a user requests enrichment. Once requested, it is
`{ lookupId, state, resolution, emails, retryable }`, where `state` is `pending | available |
not_found | withheld | unavailable | failed`. Each email is
`{ value, sources: [{ key, label }] }`. It is durable and therefore appears on
both the Contact row and profile after reload; it is separate from canonical
Contact identity and never implies `verified_email` promotion.

`resolution` retains the backend reconciliation result: `pending | matched |
single_source | conflict | none | withheld | unavailable | failed`. The frontend
does not render a verification/corroboration badge. It shows one address when
providers match, one address when only one returns a result, and two
source-labelled addresses when `resolution` is `conflict`.

The error envelope is the one documented above. Codes in use:
`UNAUTHORIZED` (401, missing workspace in the isolated development resolver;
the authenticated application instead rejects missing provider proof or
`X-Clue-Workspace-Id` through its principal resolver), `INVALID_CURSOR` (400),
`ACCOUNT_NOT_FOUND` (404), `CONTACT_NOT_FOUND` (404), `VALIDATION_ERROR` (422,
malformed identifier or out-of-range `limit`), `INTERNAL_ERROR` (500). Every
response also carries an `X-Request-Id` header matching `error.requestId`.

**`error.code` is an OPEN set — do not close the Zod enum.** Those six are the
codes this surface raises deliberately, but the framework layer beneath it also
emits generic ones: `NOT_FOUND` (an unknown route under the `/frontend/v1`
prefix — a path typo, not a missing account) and `BAD_REQUEST`. Parse `code` as
a string, branch on the known values, and fall back to the message for anything
else; a closed `z.enum([...])` turns a new backend code into a client-side
parse crash instead of a displayable error.

The read supports two explicitly exclusive pagination modes over `(createdAt,
id)` descending. Existing internal consumers may use opaque keyset `cursor`
pagination; a cursor the endpoint did not issue is a `400`. The browser table
uses one-based `page` plus `limit`, and receives `{ page, pageSize, totalPages }`
in `meta`; combining `page` and `cursor` is `400 INVALID_PAGINATION`. `limit`
defaults to 50 and is capped at **200** at the API, while the browser offers the
fixed page sizes 10, 20, 30, 50, 75 and 100. `projectId` filters by membership;
an unknown project returns an empty page, not a `404`, and returned rows still
carry their full `projects` array.

### Ratified deviations from the proposal

- **`projects[]` is `{ projectId, name, addedVia, addedAt }` — the proposed
  `{ id, name }` widened, not narrowed** (ratified 2026-08-08; was the Task-6
  blocker). `projectId` replaces `id`, `name` is the project record's own name
  resolved by a read-layer join, and `addedVia` / `addedAt` are new: they carry
  how and when the project acquired the account, which the proposal had no slot
  for. The accounts table can therefore search and sort on `project.name`
  (`src/features/accounts/model/account-query.ts`, lines 80-91) with no second
  endpoint and no client-side catalog join. The same `name` is on the detail's
  `projectSections[]`, resolved by the **same** batched read, so the table and
  the detail cannot disagree about a project's name.
  `name` is `string | null`: it is `null` for the unattributed section
  (`projectId: null` — there is no project to name) and for any section whose
  project id this workspace holds no `project` row for. That second case is
  reachable only on the detail, whose section ids can come from run lineage
  (which carries no foreign key to `project`); a membership row's project always
  resolves. Never render the id as a fallback name — an unnamed section is the
  honest rendering. Name resolution is workspace-scoped, so a foreign project id
  resolves to `null` rather than leaking another tenant's label. Cost: one
  batched statement per response, not one per membership.
- **`employeeBand: "100-200"` becomes `employeeCount: 1200`, an integer.** The
  backend holds a headcount claim, not a band; banding is a display decision the
  frontend owns.
- **`revenueBand` keeps its name but changes value space.** ~~It now carries the
  backend claim vocabulary (for example `100m_500m`), not the proposed
  `"$1 - $10M"` display string.~~ **[SUPERSEDED 2026-09-09 by the D4-b controller
  ruling]** the backend now serves the **label**, not the token — `10m_50m`
  becomes `"$10M–50M"`, `1b_plus` becomes `"$1B+"`, `under_1m` becomes
  `"under $1M"`, and `"Unknown"` when no claim exists. It is still not a closed
  enum (a token the backend cannot parse is passed through as written), so render
  it as an opaque display string; do **not** build a client-side label map, which
  is exactly the drift this ruling removes.
- **`scores[]` is a list keyed by `(projectId, icpKey, icpVersion)`, on both the
  list row and the detail section** — one project can score an account under
  several ICPs and versions, so a single `fitScore` would require guessing a
  winner. No representative run is chosen.
- **The two score surfaces are not symmetric: the list is attributed-only, the
  detail is not.** A list row's `scores[]` comes from a read that inner-joins
  run lineage to a project, so a score whose run maps to no project cannot
  appear there at all. The detail partitions the same claims into sections, so
  such a score lands in the `projectId: null` unattributed section. Consequence:
  the detail can show a score the list row does not, and the difference is
  always exactly the unattributed section. Reconcile list↔detail on attributed
  sections only; never compute a row-level "score count" from the detail.
- **`narratives[]` is plural, one per persona** — value narratives are written
  per persona, and collapsing them would drop the persona structure.
- **`researchStatus` is a per-project array, not a scalar**, with the
  backend-honest vocabulary `not_started | in_progress | needs_review |
  completed | suspended`. This supersedes the proposed
  `not_started | in_progress | fully_enriched | failed`. There is no `failed`:
  a crashed worker re-queues the job and suspends the fleet, so the honest state
  is always "halted, awaiting a human". `completed` means the job's own terminal
  outcome, not the stronger "fully enriched". An entry may name a project the
  account has **no** membership row for (research was launched for a project that
  no longer targets it); that is reported rather than hidden, so do not assume
  `researchStatus[].projectId` is always a member of `projects[]`. The committee
  and contacts union does **not** match that honesty: it iterates memberships
  only, so a non-member project that researched the account is visible in
  `researchStatus[]` / `projectSections[]` while its committee members surface
  nowhere — deliberate (the alternative attributes one project's committee to an
  account it does not target) and an anomaly state that should not occur.
- **`titleRestricted` (row) and `restricted` (profile fact) mark withheld
  values** — a display-denied field is served absent with the marker and with no
  provenance, while a field the backend simply does not hold is absent and
  unmarked. Absence and redaction are different answers and the wire says which.
- **`provider` is the raw backend source key** (`clearbit`, `sumble`,
  `committee_inference`, ...). No source display-name surface exists yet; a
  label belongs in a future source-registry column, not in an adapter map.
- **`observedAt` is the claim's observed time, falling back to its collection
  time** — the same reference-time rule the merge uses.
- **`signals` is `{ typeCount }`, not `{ count }` — it counts signal TYPES**
  (ratified 2026-08-08; the per-field unit was kept and the wire field renamed to
  say so). `typeCount` is how many of a two-family whitelist
  (`contact.facet.recent_post`, `contact.facet.public_appearances`) currently
  hold a display-eligible statement, so it is bounded by that whitelist's size
  and a list-valued field with five items still counts **1**. Label it as signal
  types ("2 signal types"), never as a count of items or posts.
- **Merged accounts redirect on the detail only.** `GET /accounts/{id}` follows a
  merged loser to its survivor and sets `redirectedFrom` to the requested account
  id. Account lists carry no redirect vocabulary at all — a merged loser simply
  does not appear as a row, and the `meta.total` does not count it.
- **The contact endpoints follow a merged account silently.** Both accept a
  merged-loser account id and serve the survivor's committee, but the contacts
  list has no marker of any kind, and the profile's `redirectedFrom` tracks a
  merged **contact** only: request a survivor contact under a merged account id
  and it is `null` while `accountId` is the survivor's. So a client that wants to
  correct a stale account link must compare `accountId` with the id it asked for.
- **`logoUrl` is always `null`** for now (it replaces `logoPath`); no logo
  pipeline exists, and the field is present so it can start returning values
  without a schema change.
- **`committee` and the contacts list are empty on live data today.** The
  governed committee reads the M8D research references, whose production writer
  is behind the R1 quarantine until the R11 DEEP-phase bridge lands. An empty
  committee is a `200` with an empty list, not a `404`. The seam itself is
  proven by fixtures, so no adapter change is needed when R11 lands.
- **Single-resource reads are not wrapped in `data`.** The account detail and
  the contact profile return the object itself; only the two lists use
  `{ data, meta }`. Either the adapters unwrap on the list side only, or the
  backend adds a wrapper — decide at the adapter flip.
- **Fact `value` payloads are opaque backend JSON.** `neutralFacts[].value`,
  `insights[].value`, `narratives[].value`, `professionalFacts[].value`, plus
  `registryIds` and `hqGeo`, are passed through verbatim from the claim, so their
  internal keys are the writer's (snake_case, e.g. the narrative's `angle_label`)
  and are not part of this layer's camelCase vocabulary. Type them as unknown
  JSON per `fieldKey`, not as a camelCase object.
- **A project section's `projectId` and membership fields are independently
  nullable.** `projectId: null` is the unattributed bucket (claims whose run maps
  to no project — manual ingestion and the documented lineage exemptions), always
  served last and only when it has content. `addedVia` / `addedAt` are also
  `null` for a project that produced research on the account **without** a
  membership row; that state should not occur, so it is reported rather than
  hidden. A project with a membership and no work still gets an empty section,
  because "targeted, nothing produced yet" is a real state. `name` is nullable on
  the same axis — see the `projects[]` entry above.
- **`coverage.researchedFieldCount` reads stronger than it is.** It counts the
  distinct fields holding at least one live, non-rejected claim for the account
  — from **any** writer, research or not: a stage-0 interview answer, a manual
  or CRM import, and a scoring write all increment it. It is "how many fields do
  we hold a value for", not "how many fields research completed", and it is not
  a percentage of anything (there is no denominator — the field registry is open
  by registration). Do not render it as research progress or drive a completion
  meter from it; the honest research-side companion is `unresolvedFieldKeys`,
  which names fields research *asked for* and could not answer.
  `unresolvedFields` carries the same keys with their field-registry descriptions,
  so a new dynamic/industry-pack field can explain itself without a frontend map.
- **`updatedAt` is the `account_entity` row's update time, not research or claim
  recency.** It moves when the entity record itself changes (identity
  resolution, a merge, an alias or registry-id write) and does **not** move when
  a new claim, score, or narrative lands on the account. A "last updated" or
  "last researched" badge that wants research recency must not use it — read the
  relevant `observedAt` (facts, narratives, insights) or `scoredAt` instead.
  `updatedAt` is a correct cache/sort key for the entity row, nothing more.
- **The detail carries no research status.** Status is a `(account, project)`
  fact served on the list row; a detail or preview badge must read it from the
  list response until a later slice adds it.
- **No display strings anywhere.** `sizeLabel`, `locationsLabel`,
  `revenueLabel`, `websiteLabel`, `dateLabel`, `timeLabel`, and
  `previewTitle` are not served; the frontend formats from semantic values.
  `domain` replaces `websiteUrl`. `freshness` is an enum that emits exactly
  `fresh` and `stale`: it reports the merge's own two states (a past-TTL winner
  is labelled, never dropped), and the backend's third disposition, `expired`,
  is a retention age-out that can never win a merge and so never reaches this
  wire.

### Ratified 2026-08-08 (FI-1 D-4–D-7, plus the operational rulings)

Founder-ratified; the record is `docs/specs/FI-accounts-contacts-contract-gap-review.md`
§9, the D-4–D-7 entry. These no longer gate anything — they are the decisions the
adapter flip (Task 6 of the slice-1 plan) implements. Most are frontend schema
decisions over the shapes above; where one implies further backend work, that is
called out rather than assumed.

1. **D-4 RATIFIED — nullable/optional everywhere the backend can be correctly
   empty, plus the honest availability/redaction vocabulary** (mirroring the
   backend's `ResearchItemState`), so the UI can tell **"not researched"** from
   **"researched, not found"** from "withheld by policy". No fabricated
   placeholders anywhere. Slice 1 ships a deliberately narrower form —
   nullability everywhere plus a boolean `restricted` / `titleRestricted` for the
   policy-withheld case — because this read layer serves the merge's current
   value and holds no per-field research-attempt state on the contact path; the
   account-level approximation is `coverage.unresolvedFieldKeys`, which names
   fields research asked for and could not answer. Adopt the full vocabulary in
   the schemas, and expect the backend to widen the wire when the per-field state
   exists. Nullability alone is required before any HTTP repository is enabled —
   the current schemas crash on it.
2. **D-5 RATIFIED — display strings leave the wire; the frontend owns all display
   formatting.** The backend sends semantic values. `timeLabel`, `dateLabel`,
   `editedLabel`, `sizeLabel`, `revenueLabel`, and `locationsLabel` become ISO
   timestamps and semantic values that the frontend formats; `personaTone` stays
   frontend-side.
3. **D-6 RATIFIED — the frontend adopts the backend vocabularies as-built,
   including `not_launchable` NOW.** `researchStatus` widens to the honest
   backend set; slice 1 serves `not_started | in_progress | needs_review |
   completed | suspended` and does **not** yet serve `not_launchable`, which
   depends on the launch surface owned by Lane D (FI-1 D-9) — it is ratified into
   the vocabulary ahead of Lane D so the schema is not widened twice. `persona`
   and `roleOnCommittee` adopt the four backend personas. The proposed
   `emailStatus` was absent in slice 1 and is superseded by Slice 10's typed
   `emailLookup` read/mutation contract. **`overallFit` is
   NOT invented** — the backend serves raw `scores[].fit`, and no tier badge,
   band cut, or adapter constant is introduced on this slice. `activity.kind`
   widens to the backend event kinds with a projection-layer label map (landed
   in Slice 6 on the dedicated Activity endpoint). `freshness` and `addedVia`
   are new enums this slice introduces.
4. **D-7 RATIFIED — the fixture-only fields are DROPPED for MVP, because they
   were placeholders for industry-pack custom fields.** That is the founder's
   clarification and it changes what "dropped" means: the hardcoded fixture
   fields — `referralFit` / `directAccessFit` / `recallFit`, `locationCount`,
   `xUrl` requiredness, non-LinkedIn `socials`, `influence`,
   `researchIsRefreshing`, `avatarUrl` (G1: no avatar pipeline, and the browser
   does not scrape) — are removed from the schemas outright, **not** preserved,
   respecced, or reproduced as constants. What they were standing in for is
   already served: when an account's industry carries an associated pack, that
   pack's custom fields arrive **dynamically** through the detail's
   registry-driven `neutralFacts` / `projectSections[].insights`, which are split
   by the field registry's declared species and enumerate nothing. So the
   frontend renders pack custom fields generically off `fieldKey` — a new pack
   field appears with no schema change and no adapter change — instead of binding
   named slots. Two notes carried over unchanged: the backend already serves an
   `intent` score the frontend does not use, and slice 1 does serve
   `roleOnCommittee.confidence` (the real signal behind `influence`).
   `logoPath` stays specified as backend work, not dropped: the cheapest real fix
   is a `core.company_logo_url` field plus a materializer, which is what
   `logoUrl: null` is waiting for.
5. **`signals` is a count of signal TYPES — the per-field unit is kept, the wire
   field is renamed `typeCount`.** See the `signals` entry in the ratified
   deviations above: a list-valued facet contributes 1, and the chip must be
   labelled as signal types, never as items.
6. **CORS posture: a same-origin proxy in production, an exact `localhost` origin
   in development, wildcard never.** Production serves the frontend and this API
   same-origin — the frontend proxies `/frontend/v1` rather than calling it
   cross-origin — so no cross-origin credentialed request is made at all (the
   proxy route is the adapter flip's to build); development allows the exact
   localhost origin, listed explicitly. `"*"` is refused structurally — the app
   raises at startup rather than allowing it, because Starlette echoes the origin
   when a wildcard is combined with credentials, which under trusted-header
   tenancy is a real cross-tenant exposure. A phase-2 cross-origin POST surface
   needs a deliberate widening decision, not a config tweak.
7. **`projects[].name` is served by the read layer** (the plan-owner addendum to
   the same ruling) — see the `projects[]` entry in the ratified deviations
   above. The former Task-6 blocker is closed.

### Frontend seam as flipped (Task 6, 2026-08-08)

The Zod schemas (`src/features/accounts/model/`) and HTTP adapters
(`src/features/accounts/data/`) are now written against the wire above. Five
decisions were taken at the adapter and are recorded here rather than left
implicit.

1. **The adapters unwrap on the list side only.** `GET /accounts` and
   `GET /accounts/{id}/contacts` parse `{data, meta}`; the account detail and
   the contact profile parse the bare object. This closes the "decide at the
   adapter flip" note in the single-resource deviation above — the backend
   keeps its shapes and no wrapper is added.
2. **`addedVia` is parsed as `z.string()`, not an enum.** The backend stores the
   raw registered channel behind a CHECK constraint (`discovered` / `imported` /
   `manual` / `directive` today) *specifically* so a read does not crash on a
   channel a later migration adds, so the frontend keeps the same posture:
   sentence-cased through a generic prettifier with no lookup table to drift.
   `researchStatus`, `persona` and `freshness` — closed backend enums — are the
   only `z.enum`s on this surface, plus `not_launchable`, ratified forward.
3. **SUPERSEDED 2026-08-11 — no Accounts-specific base URL or fixture
   switch.** Accounts and Contacts always use `/frontend/v1` through the shared
   server-only `CLUE_API_BASE_URL`. Removing `CLUE_ACCOUNTS_API_BASE_URL` means
   an unset variable can no longer silently substitute unrelated demo data.
4. **SUPERSEDED 2026-08-11 — tenancy comes from the authenticated session.**
   `CLUE_WORKSPACE_ID` and legacy `X-Workspace-Id` are removed from the
   frontend. The Next server resolves the provider session and selected Clue
   membership, then emits `Authorization` and `X-Clue-Workspace-Id`. FastAPI
   remains the final authorization authority and refuses missing, revoked, or
   cross-workspace memberships.
5. **`error.code` is carried, never switched on — and a `404` is not
   automatically an empty workspace.** A failed read raises
   `ClueApiError { code, status, requestId }` with `code` typed as a plain
   string. A `404` resolves to `null` only when the envelope names a
   record-level code — `ACCOUNT_NOT_FOUND` or `CONTACT_NOT_FOUND` — on an
   endpoint that has one. Every other `404` throws: a wrong base URL, a wrong
   prefix, or the read flag being off all produce the framework's generic
   `NOT_FOUND`, and rendering those as "this workspace has no accounts" hides a
   misconfiguration behind a plausible empty state. The list endpoint has no
   domain `404` by contract (an unknown project is an empty page), so a `404`
   there always throws. Errors are parsed leniently: a non-envelope body (a
   proxy error page) degrades to a status-only message that names the three
   things worth checking.
6. **The list is paginated, visibly.** The browser requests one numbered page
   through a server action, so the workspace header and base URL never reach
   the browser. Its footer renders first page, previous, editable current page,
   next, last page and the fixed 10/20/30/50/75/100 page-size choices. Authored
   filters/search still run over the current page and the footer says so when
   active. Changing any table view input clears selection before the next view.
7. **Every contacts row links to its own contact route.** The row's name cell is
   the link and the route param drives which profile is fetched, so rows 2..n
   are not dead clicks. The gated preview drawer — which could only ever open
   for one hard-coded contact — was removed rather than left as an affordance
   that works on one row.
8. **SUPERSEDED 2026-08-12 — unserved workspace tabs carry no runtime fixture
   data.** Account insights arrive on the Overview detail contract, so
   `account-workspace.repository.ts` retains only an explicit empty Insights
   model. Activity left that model in Slice 6 and always reads its dedicated
   durable endpoint. Artifacts left it in Slice 7: until a live Account-artifact
   contract exists, the route renders `capability_unavailable` and performs no
   artifact request. No tab invents a URL or preserves the former OpenAI demo
   workspace.

### Authenticated frontend cutover (2026-08-11)

Server Component reads call the authenticated backend primitive directly; they
do not perform a loopback HTTP request to Next. Browser-originated reads and
mutations use `/api/clue/**`, whose Route Handler uses that same primitive. The
shared path proves the Clerk session, re-loads Clue membership, strips
browser-authored authorization/workspace headers, and sends only the server
bearer plus `X-Clue-Workspace-Id` to FastAPI. `next.config.ts` no longer carries
the unauthenticated `/frontend/v1` rewrite.

There is no runtime fixture mode. The former Accounts, Account detail, Contact,
and Account-workspace fixture modules were removed. Test-local payload builders
may exercise Zod and repository contracts, and browser acceptance may seed
durable Postgres rows, but neither is reachable as an application fallback.
With the Insight Health onboarding-only seed, `GET /frontend/v1/accounts`
returns `{data: [], meta: {total: 0, nextCursor: null}}` and the page renders
“No accounts exist in this workspace yet.”

**Fields dropped from the frontend schemas (D-7).** `referralFit`,
`directAccessFit`, `recallFit`, `overallFit`, `locationCount`, `employeeBand`,
`influence`, `researchIsRefreshing`, `avatarUrl`, `previewTitle`, non-LinkedIn
`socials`, and every `*Label` display string are gone from the models, the
fixtures and the components. The "Overall fit" and "Locations" table columns
went with them and a "Projects" column took their place; the contacts table's
"Influence" column became "Committee role" (with its confidence) plus
"Signals". What those placeholders stood in for now renders dynamically: the
detail's registry-driven `neutralFacts` and `projectSections[].insights` are
laid out generically off `fieldKey` through a key→label prettifier, so an
industry pack's custom field appears with no schema change and no adapter
change. `logoUrl` is bound but always null, and the existing initials mark is
the rendering until `core.company_logo_url` exists.

**Verified live, 2026-08-08.** A throwaway database was migrated to head, seeded
with the canonical slice-1 workspace (the same fixture
`tests/integration/test_fi2_slice1_read_layer.py` builds: two projects, three
accounts, a governed committee, mixed statuses), and served by the real app with
`CLUE_FRONTEND_READ_ENABLED=true`; the frontend ran against it through
`next dev`. All four endpoints returned payloads the schemas parsed unchanged,
both directly and through the same-origin rewrite. The screens rendered live:
two ICP versions inside one project section, a fit-without-intent score shown as
`Intent —`, the unattributed bucket labelled as such, a withheld title rendering
`Withheld` beside a real one, `1 signal type`, and the null-heavy
membership-less row showing five honest absences. The full error matrix behaved
as specified — `ACCOUNT_NOT_FOUND` (404) resolved to the not-found page while a
wrong base URL produced a loud `500` naming the base, the mount and the flag;
`UNAUTHORIZED` (401), `INVALID_CURSOR` (400) and `VALIDATION_ERROR` (422) all
returned the documented envelope. CORS answered the exact listed dev origin and
refused an unlisted one. One live finding is recorded for whoever runs
`next dev` next: Next.js blocks cross-origin dev resources, so browse the dev
server on the SAME host string it prints (`localhost`), not `127.0.0.1`, or
server actions are refused.

**SUPERSEDED by FI-2 slice 4.** Account summary and Contact overview now have
typed live prose fields. The contact page's hard-coded "Last updated yesterday"
remains removed; no unsupported recency is inferred.

### Typed Account recovery (FI-2 slice 2, 2026-08-11)

Expected Account-list bootstrap failures are return values at the Accounts
data seam, not uncaught Server Component exceptions. The page renders one of
five recovery states from this closed frontend vocabulary; it never renders a
backend message, framework trace, exception digest, status code, or stack.

| Recovery kind | Transport evidence | User action |
| --- | --- | --- |
| `session_expired` | `401`, `AUTHENTICATION_REQUIRED`, or `SESSION_INVALID` | Sign in again. |
| `workspace_selection` | `WORKSPACE_SELECTION_REQUIRED`; during the auth-contract transition, the existing `WORKSPACE_FORBIDDEN` plus the exact safe server reason `a workspace selection is required` | Focus the authenticated workspace selector and choose a membership. |
| `forbidden` | `WORKSPACE_FORBIDDEN`, `PERMISSION_DENIED`, `IDENTITY_NOT_PROVISIONED`, `USER_DISABLED`, `MEMBERSHIP_STATE_CHANGED`, or another `403` | Open the access-denied recovery surface; never retry in place. |
| `service_unavailable` | Network refusal/timeout, `AUTHENTICATION_UNAVAILABLE`, `408`, `429`, or `5xx` | Retry the Account read. This is the only state with a retry action. |
| `contract_error` | Generic route `404`, validation/configuration status, malformed success JSON, Zod mismatch, or missing frontend/backend configuration | Contact support with the safe request reference when one exists; no reload loop. |

The open backend `error.code` set remains intact below this mapping. Unknown
expected HTTP refusals fail closed into `contract_error`; unexpected programming
exceptions still throw so engineering error boundaries and observability see a
real defect. The request id is copied into the recovery value, but the backend
message is discarded before the value reaches a component.

The protected session bootstrap uses the same distinction for failures that
occur before an Account page can render: provider/session service outages get a
retryable protected-service state, and frontend/backend configuration or wire
schema failures get a non-retryable support state. Authentication expiry and
membership refusal continue through the established sign-in and access-denied
routes. An absent, stale, or ambiguous workspace cookie routes to the explicit
workspace chooser; the frontend no longer silently selects the first membership.

### Linked Contact integrity and accessibility (FI-2 slice 3, 2026-08-12)

Account detail, the Contacts list and Contact detail now consume one governed
committee composition seam. That seam owns project membership, latest-run/product
scope, canonical Contact survival, strongly-bound role/persona eligibility and
workspace display policy once. The resulting invariant is structural: every
`committee[].contactId` and every Contacts-row `id` is addressable through
`GET /frontend/v1/accounts/{accountId}/contacts/{contactId}` under the same
workspace and policy. A member that does not clear that rule is omitted from
every linked surface together; the frontend does not author a broken link or
invent a non-navigable profile.

Addressability does not require a display name, title, LinkedIn identity,
signals, or completed deep research. An eligible Contact may therefore serve
`name: null`, unknown professional fields and zero signal types while retaining
a valid profile. A policy-withheld title remains `null` with
`titleRestricted: true`. A stale merged-Contact URL serves the canonical
survivor and sets `redirectedFrom` to the requested loser id.

The visible fallback for `name: null` is “Unnamed contact”; the opaque id is
never rendered as a name. Contact avatars beside a visible name are decorative
and absent from the accessibility tree. Contacts-grid rows are named
`Contact <name>` and their profile links are separately named
`Open <name> profile`, so the avatar, row and link no longer concatenate the
same person name. Selection behavior is defined by the Slice-9A contract below.

### Contact email enrichment (FI-2 slice 10, 2026-08-12)

The existing Contacts-row “Look up” control invokes these authenticated
same-origin BFF mutations:

- `POST /frontend/v1/accounts/{accountId}/contacts/{contactId}/email-lookup`
  creates or reuses the current observation-window lookup and kicks off any
  provider that has not already run.
- `POST /frontend/v1/accounts/{accountId}/contacts/{contactId}/email-lookup/{lookupId}/poll`
  advances only replay-safe pending provider operations. A terminal provider is
  never dispatched again.

The Next Route Handler derives the provider bearer and `X-Clue-Workspace-Id`
from the server session. FastAPI re-resolves the governed Account/Contact path
and requires `research.launch`; a browser-authored workspace or bearer header is
not trusted. The local-header path permits a development actor only when real
authentication is disabled; production cannot use that path.

Exa Websets and Sumble v9 People are independent acquisition sources. Sumble
uses one-person LinkedIn match mode with `select.attributes` explicitly naming
`email`; the provider's documented upper bound is 10 credits at the first
successful reveal. Exa imports the exact LinkedIn URL as one person and requests
one email enrichment. Provider request/response artifacts, operation ids,
realized credits/cost, an unverified `core.work_email` claim, lawful basis and
use decision are retained durably. The operation never writes
`contact_entity.verified_email` and never describes an address as deliverable or
independently verified. C5's stricter validated delivery workflow remains
unchanged for a later release.

The read projection reconciles provider observations without erasing conflict:

- matching normalized values render once;
- different values render separately with `Exa` / `Sumble` labels;
- a single found value renders even when the other source returns no result;
- two authoritative no-results render no address;
- configuration/provider failure, policy withholding and unknown spend remain
  distinct from no-result.

Budget-control UI and budget-based stopping are intentionally absent while
`CLUE_BUDGET_CONTROLS_ENABLED=false`; provider units/cost remain recorded. The
independent Slice-10 deployment switch is
`CLUE_FRONTEND_CONTACT_EMAIL_LOOKUP_ENABLED` (default off). Missing provider
credentials become an honest provider-unavailable state, not a fake success.
The browser may schedule polling while the backend says `pending`; the timer
never changes state by itself.

### Account and Contact bulk actions (FI-2 slice 9A, 2026-08-13)

Selection is available only when the authenticated backend capability says the
user may perform the corresponding action. It is page-scoped: the header
checkbox selects only selectable rows currently rendered on that numbered page.
Changing search, filters, sort, page or page size clears selection before the
new view is applied, so a hidden selected row cannot exist. The header control
reports checked, unchecked and mixed states. Workspace/account navigation also
creates a fresh controller and therefore an empty selection.

Capability reads:

- `GET /frontend/v1/accounts/bulk-capabilities` returns
  `{ addToProject: { allowed, maxItems: 100 }, addToChat: { allowed,
  maxItems: 100 }, projects }`. `projects` contains
  the workspace's non-archived projects; authorization is derived from
  `project.write`, never from a frontend role guess. `addToChat` additionally
  requires `thread.write` and the live chat surface.
- `GET /frontend/v1/accounts/{accountId}/contacts/bulk-capabilities` returns
  `{ lookupWorkEmails: { allowed, maxItems: 20 }, addToChat: { allowed,
  maxItems: 100 } }`. It requires a valid
  account-scoped read and is false unless `research.launch` is held and the
  Slice-10 service is configured. Contact `addToChat` is independent of email
  enrichment and follows the same chat/thread capability as Accounts.

Mutations use the same-origin BFF and require a nonempty `Idempotency-Key`:

- `POST /frontend/v1/accounts/bulk-actions/add-to-project` accepts one project
  and 1–100 explicit Account ids. It inserts only live canonical same-workspace
  Accounts with `project_account.added_via='manual'`. Existing membership is
  `unchanged`; missing, merged or foreign ids are item-level `ineligible`.
  It neither removes another membership nor launches research.
- `POST /frontend/v1/accounts/{accountId}/contacts/bulk-actions/email-lookup`
  accepts 1–20 explicit committee Contact ids, presents the one intent
  confirmation, and delegates each eligible strongly-anchored Contact to the
  existing governed Exa/Sumble service. Current-window lookups are `unchanged`;
  no-result is a completed empty outcome. There is no spend-approval screen.

Both return `{ operationId, state, counts, items }`. The parent operation and
every item outcome are durable in `frontend_bulk_action_operation` and
`frontend_bulk_action_item`. Reusing a key with the same canonical request
replays the stored response and does not dispatch providers again; reusing it
for another request is `409 IDEMPOTENCY_KEY_REUSED`. Partial success is explicit
through item outcomes and aggregate counts. Internal exception messages and
provider details never enter the browser response.

### Bulk selection to project chat (FI-2 slice 9B, 2026-08-13)

`Add to chat` is available on both counted selection bars for 1–100 currently
visible Account or Contact rows. It does not replace the existing Account
`Add to project` or Contact `Look up work emails` actions. It performs no
research, provider request, spend, project-membership write or other domain
mutation. The destination dialog chooses an existing project plus active chat,
or creates one idempotent new chat in that project. Opening the dialog is the
selection action; there is no additional confirmation prompt.

Before navigation the browser calls
`POST /api/v1/projects/{projectId}/composer-context/prepare` through the
same-origin BFF with the ordered selected `{objectType, objectId, version}`
references and an optional existing `threadId`. The server requires
`thread.write`, scopes the project/thread to the authenticated workspace,
refuses archived threads, resolves canonical current versions and hydrates
display-safe labels directly from live Account/Contact reads. The endpoint is
read-only draft preparation. It does not depend on the composer's bounded
mention catalog and it never creates project membership.

The cross-page browser handoff is stored in `sessionStorage` under an opaque
UUID with a 30-minute expiry; the URL carries only that UUID plus the selected
thread id, never the selected entity ids or labels. The originating table
selection clears only after the prepared handoff has been written and read
back successfully. Transfer failures leave the selection intact. The project
composer restores visible `@` chips from the handoff, while the eventual turn
submission revalidates and durably records the same ordered structured
references.

Those references belong only to the next accepted message. A failed submission
preserves the prompt and chips for retry. Once the turn endpoint returns its
durable acceptance receipt, the draft and handoff are consumed; the historical
user message retains the references and later messages do not inherit them.

### Live prose and user-facing vocabulary (FI-2 slice 4, 2026-08-12)

Account detail serves `summary`; Contact detail serves `overview`. Both are a
discriminated union derived from the current Lane-E synthesis claim:

| `state` | `paragraphs` | `researchOutcome` | Meaning |
| --- | --- | --- | --- |
| `available` | one or more strings | `completed` or `needs_review` | Current synthesis is displayable. |
| `not_composed` | `[]` | `null` | No live synthesis claim exists. |
| `restricted` | `[]` | `null` | A synthesis record exists but cannot be served. |

`account.summary` is excluded from `neutralFacts`, and `contact.overview` is
excluded from `professionalFacts`; prose is never rendered as a generic fact.
The UI selects the summary/overview copy from this state alone. In particular,
it does not infer “research incomplete” from project status while displaying a
completed synthesis.

The backend keeps semantic values unchanged (`1b_plus`, `product_led`,
`c_level`, `economic_buyer`, `champion`, `technical_evaluator`, `blocker`). The
frontend owns stable labels (`$1B+`, `Product-led`, `C-level`, `Economic buyer`,
`Champion`, `Technical evaluator`, `Blocker`) and applies them at render time,
so filters and model data retain the machine values. Unknown ordinary prose is
not sentence-cased. Dynamic research gaps use
`coverage.unresolvedFields[].description` from the effective field registry;
the key-to-label prettifier remains only a fallback heading.

Authenticated browser acceptance used the durable Insight Health workspace and
followed the live Accounts row into Northstar's preview, its Contacts table, and
all served Contact shapes. The Account summary and Dana Buyer overview rendered
their completed prose without contradictory incomplete-research copy; Chris
Blocker and the unnamed Contact rendered the not-composed state honestly. Named,
withheld, unnamed and stale-merged Contact URLs all survived a direct reload.
Every browser request resolved through the authenticated session-to-principal
chain and `/frontend/v1` with `200`, and the same-origin BFF Account-detail
request returned `200`. Browser rendering used the stable labels above while
API/model contract coverage retained the raw semantic values.

### Exact source and claim-mapped evidence (FI-2 slice 5, 2026-08-12)

Every rendered Account `neutralFact`, Account project `narrative`/`insight`,
and display-eligible Contact current claim carries an evidence record mapped to
the exact claim it supports:

```json
{
  "claimId": "0f0f4e8c-4d1a-4f0b-9f2d-2b7a1c0d5e11",
  "fieldKey": "contact.current_title",
  "sourceTitle": "sumble",
  "provider": "sumble",
  "sourceUrl": "https://evidence.example/reports/committee?version=2#finding",
  "evidenceSpan": "Dana Buyer is the current VP of Finance.",
  "confidence": 0.94,
  "freshness": "fresh",
  "observedAt": "2026-08-01T12:00:00Z",
  "protectedArtifactAvailable": true
}
```

`claimId` and `fieldKey` are the support mapping. `sourceTitle` is the registered
source identity, or the hostname when no registered source key exists; the
claim substrate does not hold fetched-page titles, so the API never invents
one from a URL path. `sourceUrl` is nullable and crosses the wire only when it
is an HTTP(S) URL with a hostname and no embedded credentials. The frontend
uses the complete `sourceUrl` as both the visible label and the `href`; it never
authors a more-specific label. A domain or profile root therefore remains a
domain or profile-root label instead of looking like a post or evidence span.
The legacy Account-workspace schema enforces the same invariant with
`sourceLabel === url`.

`evidenceSpan` is emitted only after the owning read has passed the same current
merge, retention and display policy used for the value. Contact evidence is one
record per displayed claim, not one chip per provider. A withheld or
retention-expired Contact claim contributes no value, `claimId`, provider, URL,
span, confidence, timestamp or artifact-existence signal.

`protectedArtifactAvailable` is only an opaque action capability. It never
contains a storage key or signed URL. The frontend derives one same-origin BFF
path from the Account/Contact and claim ids:

- `GET /api/clue/frontend/v1/accounts/{accountId}/evidence/{claimId}`
- `GET /api/clue/frontend/v1/accounts/{accountId}/contacts/{contactId}/evidence/{claimId}`

The corresponding FastAPI route reconstructs the current Account or governed
Contact read, requires that exact claim to remain displayed with a live
workspace-scoped artifact, re-resolves the retention-aware claim, validates the
artifact row and its content address/size, and then streams a bounded safe media
type. It does not redirect or presign. Responses are `private, no-store`,
`nosniff`, and CSP-sandboxed; active HTML/SVG is downgraded to plain text.
Unknown, foreign-workspace, erased, expired, withheld and no-longer-addressable
requests all return the same `404 EVIDENCE_NOT_FOUND` shape. A deployment with
no storage backend returns `503 EVIDENCE_SERVICE_UNAVAILABLE` rather than a
fabricated link.

The BFF forwards only the required response metadata (`Content-Type`,
`Content-Disposition`, `Cache-Control`, CSP and `X-Content-Type-Options`) while
retaining the authenticated server-derived provider proof and
`X-Clue-Workspace-Id` path. Browser-authored authorization/workspace headers
are still stripped. The provider bearer and artifact storage locator never
enter browser state.

### Durable Account activity (FI-2 slice 6, 2026-08-12)

`GET /frontend/v1/accounts/{accountId}/activity` is a read projection over the
append-only `research_subject_activity` ledger. It includes Account events and
Contact events for members of the Account's governed committee. A row is served
only when it resolves to the exact `research_view_event`, project, project run
and parent Account run named by that ledger row. A Contact event is additionally
required to belong to a project that selected that committee member. Unknown
event kinds, unresolved owner references, ungoverned Contacts and human rows
without a durable principal id are omitted rather than assigned invented copy
or actor identity. The response is newest-first by `(occurredAt, id)` and capped
at 100 events.

```json
{
  "accountId": "0f0f4e8c-4d1a-4f0b-9f2d-2b7a1c0d5e11",
  "state": {
    "committeeCount": 6,
    "summary": {
      "state": "available",
      "paragraphs": ["Acme is a multi-site healthcare operator."],
      "researchOutcome": "completed"
    }
  },
  "events": [
    {
      "id": "b5a9a584-e844-48d9-a964-e0b289dc4b8d",
      "kind": "research_view.updated",
      "occurredAt": "2026-08-12T09:02:00Z",
      "actorCategory": "system",
      "subject": {
        "type": "account",
        "id": "0f0f4e8c-4d1a-4f0b-9f2d-2b7a1c0d5e11",
        "name": "Acme"
      },
      "project": {
        "id": "prj_a",
        "name": "Insight Health campaign"
      },
      "projectRunId": "9dfa7ff6-8dd2-4e95-a0b0-461a2dfcf535",
      "accountRunId": "f84ac206-ec48-4c57-981f-e2f958f26b10",
      "reference": {
        "target": "account_insights",
        "eventId": "1f8cd58b-c545-4aa1-ac2b-dba68b51d5d3",
        "snapshotId": "e3b8e570-7705-4f2d-bc52-fb730773564f",
        "reportId": null,
        "sectionIds": ["summary"],
        "itemIds": ["summary-1"]
      }
    }
  ]
}
```

`state.committeeCount` is `len(AccountDetail.committee)` and `state.summary` is
the same `read_prose(account.summary)` result returned by Account detail. It is
not an activity event and makes no historical claim; it exists so the Activity,
Contacts and Overview/Insights tabs cannot present contradictory current state.
An Account with no qualifying ledger rows returns `events: []`, and the browser
renders “No durable activity exists for this account yet.”

The backend sends machine values and absolute ISO-8601 timestamps. The frontend
maps the three event kinds (`research_view.updated`,
`research_view.section_stale`, `research_view.recheck_completed`) and the
non-human actor categories (`system`, `agent`, `worker`) to stable labels, then
renders the timestamp in UTC. Account event titles drill into Account Insights;
Contact event titles and subject names drill into the governed Contact profile.
The current summary state links to Account Overview, and the resolved project
name links to `/projects/{projectId}`. Raw owner/fetch
references, payload bodies and relative `timeLabel` strings never cross the
contract.

### Account Artifact availability (FI-2 slice 7, 2026-08-12)

There is no live Account-artifact read surface in this slice. The Account
Artifacts route still authenticates and reads the Account detail so an unknown
or cross-workspace Account remains a domain `404`, then renders the typed
`capability_unavailable` state: “Account artifacts are not connected yet.” It
does not render a search field, sort/view buttons, fixture cards, preview modal
or images, and it does not issue a guessed artifact request.

The presentation contract reserves three exact states for a future live
adapter:

- `capability_unavailable`: this deployment has no live Account-artifact
  capability.
- `empty`: the live service authoritatively returned zero Account artifacts.
- `service_unavailable`: the live artifact service failed and the result is not
  known to be empty.

Those states have distinct titles and descriptions. Adding a live Account
artifact endpoint, sorting, grid/list presentation, and preview behavior is a
separate integration slice; it must introduce typed repository data and real
handlers together rather than restoring dormant controls.

### Project Target Accounts tab (lift from the dummy, 2026-09-11)

Lifted from the dummy frontend `clue-frontend` @ `e3bcea7`
(`docs/api-contracts/accounts.md` § "Project Target Accounts prototype"), edited
where this platform's seams differ. The dummy is presentation truth; the two
edits below are the seam, not the screen.

The project workspace exposes a permanent Target accounts tab next to Gallery.
Its shareable route is `/projects/:projectId/chats/:chatId?surface=target-accounts`;
`/projects/:projectId/accounts?thread=:chatId` redirects there. A threadless
`/projects/:projectId/accounts` redirects to `/projects/:projectId?surface=target-accounts`
instead: founder ruling R3 forbids the dummy's `thread-primary` fixture id in a
production URL, so `projectTargetAccountsHref` never emits it, and the project
landing route is the legacy absorber (ruling R1) that carries `surface` through
its own canonicalization to the resolved thread. A gallery card whose document
type is `table` **is** the project's account list, so it opens this surface
rather than an artifact tab (`features/chat-shell/model/gallery-card-target.ts`).

**Seam edit 1 — the BFF route composes three reads, not two.** The frontend
route `GET /api/projects/:projectId/accounts` returns
`{ accounts, availableAccounts, profile, bulkCapabilities }` in one uncached
(`Cache-Control: no-store`) document. `accounts` and `availableAccounts` come
from the accounts repository (`data/project-accounts.repository.ts`), which
forwards `projectId` to the backend read `GET /frontend/v1/accounts?projectId=`.
The cursor walk belongs to the list read itself (`data/accounts.repository.ts`):
it follows `meta.nextCursor` for at most `ACCOUNTS_PAGE_CAP` (25) pages of
`ACCOUNTS_PAGE_LIMIT` (200) rows and then returns what it has with
`meta.nextCursor: null`. A workspace or project larger than those 5,000 rows is
therefore **silently truncated** — the screen shows the first 5,000 and says
nothing; the honest fix at that size is server-side paging on the screen, not a
longer walk. Browser pagination runs over whatever that one read returned.
`availableAccounts` is the unscoped directory minus the current members.
`profile` is derived from the session — `getWorkspaceProfile(session)` — because
this platform has no settings feature to read a `SettingsWorkspace` from; the
session is resolved *outside* the route's try, so an authentication redirect is
never swallowed into a 502. `bulkCapabilities` is the existing server-declared,
fail-closed bulk-action capability read. A failed data read returns `502` with a
retry action; the parse contract is
`features/accounts/model/project-accounts.ts` (`ProjectAccountsResponseSchema`).

The table reuses the global account cell renderers, column controls, and density
tokens. Project membership is applied before search, filters, sort, and paging.
Page sizes are 25, 50, and 100; query changes reset to page 1. The header
checkbox selects the current page, while other selected pages remain selected.
Switching Gallery/Target accounts or opening an in-project account preview
preserves the mounted table state. Previews reuse the global full-height account
drawer, toolbar, contacts, and research presentation. The frontend read route
`GET /api/accounts/:accountId` loads the same detail repository and validated
`{ data: AccountDetail }` response as the global preview and full page. Missing
detail records return 404; upstream failures return 502 with a retry action.
Directory properties remain visible while details load or are unavailable.
Closing restores focus to the project table. Open as page always navigates to
the canonical workspace route `/accounts/:accountId`.

**Seam edit 2 — Add accounts is a real membership write** (founder ruling,
2026-09-11). It replaces the dummy's local-state-only paragraph, which is not
kept. The picked directory accounts are submitted through the existing bulk
action `POST /accounts/bulk-actions/add-to-project` — the screen controller's
`submitAddAccounts`, with a fresh `Idempotency-Key` per attempt — and the rows
learn about the additions only once the backend accepts. On success the served
lists are re-read so the picker stops offering an account that is now a member;
the table keeps its columns, selection and page across that re-read. A refusal
changes nothing on screen and says so, with a Try again action. No duplicate
account record is created: membership is the only thing written.

**Membership display correction (2026-09-12):** The global bulk picker starts
at "Choose a project"; Add to project stays disabled until an explicit choice.
Clearing or successfully submitting the selection resets that choice. The
result notice includes the chosen project's name alongside the backend counts.
The shared table controller reconciles each new server snapshot, retaining only
unsaved local drafts from its previous rows. This makes added members and updated
research fields visible on a tab re-read without remounting the table or losing
its filters, selection and column settings. The membership API is unchanged.

**Seam edit 3 — Add to chat, into the open chat** (founder request,
2026-09-11; not in the dummy, which has no such button on this tab). The tab's
selection bar carries an "Add to chat" button in the global bar's token (the
`Button` at size `md`) in the filled default variant, the founder's choice for
this placement. It is the global table's action minus its destination picker:
the tab already sits beside the chat it targets, so the selected accounts are
prepared through the same `POST /projects/:projectId/composer-context/prepare`
(every reference validated, its version pinned) against the current project and
the open thread — `thread_id: null` on a threadless project page, where the
composer's first send creates the thread — and the prepared entities land in
that mount's composer as selected context, exactly as a restored handoff would.
No handoff record is written and nothing navigates. The gate and the limit are
the global bar's (`bulkCapabilities.addToChat`, a real chat transport, and the
workspace's `composerCapabilities.contextRefs`); the selection clears only once
the chat holds the accounts, and a refusal is worded as the destination dialog
words it, shown in the conversation's existing context-handoff error line.
Frontend-only: the backend contract is unchanged.

**Seam edit 4 — the tab streams a live discovery run** (spec
`docs/superpowers/specs/2026-09-12-discovery-streaming-design.md`). A new read,
`GET /frontend/v1/projects/:projectId/discovery/current` (BFF mirror
`GET /api/projects/:projectId/discovery`), serves the project's latest discovery run:
`{ run_id, status, asked, found, verified, shown, started_at, finished_at }` or `null`. While
`status` is `not_started`/`in_progress` the chat shell polls it every 5 s, the "Target accounts"
tab label carries the chat's rotating loader glyph, and the tab re-reads
`/api/projects/:projectId/accounts` on every tick without dropping its rows, so verified
accounts appear as the driver lands them. A completed `launch_arv2_discovery` tool part on the
open thread opens the surface once (`chat-shell/model/discovery-launch-signal.ts`). Backend:
the driver now lists the webset on every poll tick and verifies new items in a bounded pool
(`CLUE_ARV2_DISCOVERY_VERIFY_CONCURRENCY`, default 4), one candidate's gates asked together;
a row still appears only after every gate is verified.

## Research quality generations — approved 2026-09-22, implemented locally; live acceptance pending

The research-quality design §10.2 and its implementation authorization govern this additive
contract. Existing account/contact layouts remain. New quality-profile reads carry `projectId`,
`contextId`, `generationId` and `qualityState` separately from job execution status. Account,
Insights and Contact reads accept `projectId` and `contextId`; an omitted context is resolved only
when unambiguous and returned explicitly. Ambiguity yields `context_required` with project choices,
never another project's narrative. Legacy unscoped output is labelled `legacy`.

`researchQuality` includes those identities, `qualityState` (researching/provisional/reconciled/
partial/needs_review/suspended/privacy_stopped/context_required/legacy), `refreshPending`, ordinary
non-sensitive `gaps`, and `contexts` choices. `DisplayBlock` carries the same metadata. Missing or
invalidated content remains visibly pending/qualified; privacy restrictions remain separate.
Committee members carry `membershipState` (candidate/supported/needs_verification/excluded),
`outreachEligible` and `membershipGaps`. Only supported current employment plus supported remit may
be presented as an established buying role. Counts use the same assessed membership reader.
For a contextual candidate, unverified or excluded member, `influence` is null and renders as
Unverified; the legacy persona default must not imply a verified influence level.
`membershipGaps` contains user-facing explanations, not internal assessment reason codes.

Cited sentences additionally carry `kind` (fact/inference/quote/qualified/gap) and qualifications.
An attributed provider report excerpt is not a primary quote. A value argument cites a narrative
claim backed by both account claims and exact pinned seller-document passages. Invalid historical
observations remain auditable but are unavailable to ordinary factual summaries. Stale writes are
refused atomically; rejected claims and revoked memberships are suppressed before asynchronous
refresh. Read requests do not invoke the old Luna writer for a quality generation.

## Miscellaneous research sections — approved and integrated locally 2026-09-27

Account Insights and Contact display blocks now include an owned `miscellaneous` section,
headed **Miscellaneous**, after the existing sections. Overview is unchanged. This uses the
existing `ResearchSection` shape; no new transport or component-specific field is needed.

The section contains additional source-linked findings not represented in the main narrative.
It is ordinary research (`restricted: false`), initially collapsed (`defaultOpen: false`),
with the same item text, attribution, qualifications and claim/source controls as other sections.
It is not the Internal notes surface. The narrative skills govern selection; the frontend neither
reclassifies claims nor invents residual content. Findings already explained elsewhere need not
be repeated, and distinctive personal interests can still receive prominence in the main narrative.

Backend recipe seeding offers the section to the account and person writers through
`read_narrative_inputs`; `write_research_narrative` stores it using the existing scoped claim-ID
resolution and page writer. Old/in-flight narratives may omit this additive section. A quality
page with no saved Miscellaneous block shows “No additional research findings have been published
yet.” and does not enter a refresh loop merely because this section was introduced. Existing
blocks still become stale when their underlying research changes. No historical content is
automatically moved or regenerated by this change.

Fixture account/contact pages expose the same empty section. The generic `ResearchDocument`
and `ResearchStack` render it as an independent native disclosure with source controls.
