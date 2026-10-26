# Settings → Integrations — live check findings (2026-10-26)

Live check of the CRM Settings → Integrations pages (Figma `2308:1590`, rulings R-14.6, R-15.1–R-15.3;
plan `docs/superpowers/plans/2026-10-25-crm-settings-integrations.md`) on the nashville stack, after
the stack DB was migrated in place to `280cce98bc76`. Garner Health (Salesforce test org) and
Conduit AI (HubSpot test portal 247744687). The founder clicked Connect and signed in.

## What passed

- **Overview** (board 04): connected card with Manage; after disconnect, the "CRM · Connect" card
  (board 01); the column sits centred like the board at full width.
- **Provider page** (boards 02/03): Connection, Research in {CRM}, Permissions, Overwrites; HubSpot
  says portal/companies, Salesforce organization/accounts.
- **Research setup from Settings, both CRMs:** Approval needed (the new "Clue fit level" field was
  missing) → "Review request" with no pending card opened `/projects/{id}?prompt=…` with
  "Set up Clue's fields in {CRM}." in the composer, nothing sent, `?prompt` dropped from the address
  (Task 8) → sent → setup card → "Review request" then linked straight to that chat → Allow →
  Preparing with the details table → Ready (Salesforce: 2 created, 14 already there).
- **Overwrites:** "Follow 'Always allow'" asks in a dialog and stores `follow_grants`; "Always ask me"
  saves without a dialog.
- **Revoke:** a standing permission (seeded with `writes.insert_grant`, since no card in the test
  project could offer one) shows as "Always set Clue fit level on accounts", the dialog matches
  board 06, the list empties.
- **Disconnect:** board 06 dialog; the connection becomes `disconnected`, its grants are revoked, the
  Composio connected account is deleted (GET → 404), the page returns to the overview.
- **Connect again from Settings (same portal), twice:** the first time made a new row, because the
  old row was connected before Clue stored portal ids (expected, R-14.5: an unidentified account
  is a new connection) and now reads "Portal 247744687"; the second time **reused that row**,
  active again, with no grants carried over. The callback tab says "HubSpot is connected".

## Founder review on the page (2026-10-26)

- Keep the "‹ Integrations" back link + CRM name heading (not the board's "Integrations / HubSpot").
- Drop "Connected on" and the "Reconnecting the same … keeps your permissions and history." line
  under an owner's buttons (a member still reads "Ask an owner or admin…").
- "Where to find this in {CRM}" and the read-only line are one paragraph, on both CRMs.
- The connect callback page's grey fills the whole window.

All four done: `619b4eb4d`, `48a13caf8`.

## Defects and findings

- **L-1 — radio names (false finding).** The browser tool listed the overwrite radios as "ask" /
  "follow_grants"; each input sits inside its `<label>`, so the accessible name is the visible text.
- **L-2 — Preparing never turned Ready without a reload. Fixed `619b4eb4d`:** the page re-reads
  itself every 5 s while the state is Preparing (the account pages' `usePendingSectionsRefresh`).
  Live proof still owed: both CRMs finished their setup in about two seconds.
- **L-3 — Ready missed the design's second sentence. Fixed `619b4eb4d`.**
- **L-4 — placeholder account names** ("HubSpot portal", "Salesforce organization") on connections
  made before Clue stored portal ids / org names; a reconnect fills them (seen live for HubSpot).
- **L-6 — Approval needed just after Allow. Fixed `690f47bdd`:** the card goes queued/sending a
  moment before its change; in that gap the page fell back to Approval needed and did not re-read.
  A card that is queued/sending now reads Preparing. Test
  `test_preparing_once_the_card_is_allowed_before_its_change_is_queued`.
- **L-7 — a page opened in the same second as Allow** can still load before the server has the
  answer and stay on Approval needed until reloaded (it only re-reads while Preparing). Accepted.
- Next.js keeps the previous page hidden in the DOM; the browser tool then finds every element
  twice. Not a product issue.

## Not exercised

- The member view (founder testing it with a member login).
- Change CRM (switch to the other CRM), an expired connection's Reconnect, the needs-attention and
  permission-needed states live (covered by tests and the fixture env `CLUE_CRM_SETTINGS_FIXTURE`).
