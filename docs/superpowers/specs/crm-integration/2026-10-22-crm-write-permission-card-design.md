# CRM write permission card — design spec (for Figma)

The card that asks a person to allow Clue's writes to their CRM (Phase 2; design section 6.4;
rulings R-6.2–R-6.8, R-6.21). It appears in the chat when the agent proposes changes that no
standing permission covers, and the agent's turn ends on it.

It reuses the connect card's frame (Figma node 2251:5348) so the two read as one family.

**Status (2026-10-22, R-6.22):** this spec *is* the current card. Planning and building do not wait
for a Figma design; if one comes later, it refines this.

## 1. Frame and shared parts

- Width 520 px max (full width below that), padding 20, gap 20 between sections, radius 8,
  1 px border `border-subtle`, background `bg-neutral` — same as the connect card.
- **Header:** 40 × 40 symbol tile (radius 8, `brand-100`) with a 20 px icon, then title (18/24
  bold, `content-neutral`) and one line of description (`text-default`, `content-subtle`).
- **Captions:** 12/16, `content-subtle`. Buttons: the shared `Button`, size md (32 px); primary
  and transparent variants.
- CRM logos: the HubSpot and Salesforce logos already in `public/icons/crm/`.

## 2. The idea: groups, not rows

A batch can hold hundreds of changes ("add the 300 target contacts to the project list"). The card
shows **one line per group** — the same action on the same field — with a count, a summary of the
values, and the agent's reason. Opening a group lists its records. Only **changes that overwrite a
value a person set** are never grouped: each is listed on its own and starts unticked, so a person
approves every one explicitly (R-6.5).

## 3. States

### A. Asking (the card is waiting for an answer)

```
┌────────────────────────────────────────────────────────────┐
│ [icon]  Clue wants to update HubSpot                        │
│         For "Q4 hotel groups". Nothing is sent until you    │
│         allow it.                                           │
│                                                             │
│ ☑ Add 48 contacts to the list "Clue: Q4 hotel groups"   ▸  │
│     Why: the buying committees found for the 12 accounts    │
│                                                             │
│ ☑ Set "ICP tier" on 12 companies                       ▸  │
│     Empty today → Tier 1 (5), Tier 2 (7)                    │
│     Why: tiers from the confirmed ICP                       │
│                                                             │
│ ⚠ 2 changes overwrite a value a person set                 │
│   ☐ Acme Hotels · Lifecycle stage: Lead → Opportunity       │
│      Set by Priya Shah, 3 Oct                               │
│   ☐ Contoso Inns · ICP tier: Tier 3 → Tier 1                │
│      Who set it isn't known                                 │
│     Why: …                                                  │
│                                                             │
│ ☐ Always allow adding records to Clue lists and campaigns   │
│ ☐ Always allow setting "ICP tier" on companies              │
│                                                             │
│ Any member of this workspace can answer.                    │
│                                   [Don't allow] [Allow 60]  │
└────────────────────────────────────────────────────────────┘
```

**Header**
- Title: **"Clue wants to update {HubSpot | Salesforce}"**. Icon: the CRM's logo in the tile.
- Description: **"For "{project name}". Nothing is sent until you allow it."**

**Group line** (one per group)
- Checkbox (ticked by default). Three states: all records ticked, none, or some (indeterminate).
- Title — the action, the count and the target, in plain words (see the wording table, §5).
- Value summary, when the group sets a value: **"Empty today → Tier 1 (5), Tier 2 (7)"**; when it
  only adds or creates, omit it.
- **"Why: …"** — the agent's reason, at most two lines, then "more".
- A chevron ▸ on the right opens the group.

**Opened group**
- The records, one per row: checkbox · record name · a secondary line (company domain, or the
  contact's job title and company) · the value change for that record when it differs from the
  group summary.
- Scrolls inside the card past about 8 rows (max height ~320 px); a caption **"48 contacts"** sits
  above the list. A filter box appears only past 20 records.
- Unticking a record moves its group's checkbox to the indeterminate state.

**Overwrites section** (only when there are any)
- A warning line: **"⚠ {n} change(s) overwrite a value a person set"**.
- One row per change, **unticked by default**: record · field: before → after, and below it who set
  the current value and when ("Set by Priya Shah, 3 Oct"), or **"Who set it isn't known"** when the
  CRM keeps no history (Clue then assumes a person did).
- The reason under the rows.
- Never covered by "Always allow" (R-6.5): no standing-permission tick for these.

**Standing permissions**
- One tick per kind of change on the card, all unticked by default:
  **"Always allow {phrase}"** — e.g. "Always allow adding records to Clue lists and campaigns",
  "Always allow setting "ICP tier" on companies". (R-12.8, founder 2026-10-23: adding to and
  removing from lists and campaigns are one standing permission each, whatever the list holds, and
  are worded for all of them.)
- Ticking one makes it a standing permission when the person presses Allow; next time those changes
  skip the card. Revoked through chat ("stop setting ICP tier without asking") or the future
  Settings → Integrations page.
- **"Fully automatic"** is *not* on the card — it lives on the settings page (§7).

**Footer**
- Caption, left: **"Any member of this workspace can answer."** (R-6.8)
- Buttons, right: **Don't allow** (transparent) and **Allow {n}** (primary), where {n} is the number
  of ticked changes. With nothing ticked, the primary button reads **Allow** and is disabled.

### B. Sending (after Allow)

```
┌────────────────────────────────────────────────────────────┐
│ [spinner] Sending 60 changes to HubSpot                     │
│           Allowed by Aryan Keshri · 14:02                   │
│                                                             │
│  ▬▬▬▬▬▬▬▬▬▬▬▬▬▬░░░░░░  38 of 60                             │
│                                                             │
│  Clue carries on in this chat when it's done.               │
└────────────────────────────────────────────────────────────┘
```

- The groups collapse; a progress line shows how many changes have an answer from the CRM.
- No buttons. The card follows the real progress (it updates live, in every open tab).

### C. Done

```
┌────────────────────────────────────────────────────────────┐
│ [✓]  Changes sent to HubSpot                                │
│      Allowed by Aryan Keshri · 14:02                        │
│                                                             │
│  58 done · 2 failed · 1 skipped                             │
│                                                             │
│  ✓ Added 48 contacts to "Clue: Q4 hotel groups"             │
│  ✓ Set "ICP tier" on 10 of 12 companies                ▸    │
│  ✕ 2 failed                                                 │
│     Contoso Inns · ICP tier — HubSpot: "Property value is   │
│     not a valid option"                                     │
│     …                                                       │
│  – 1 skipped: changed in HubSpot since it was proposed      │
│                                                             │
│  Clue will fix the failed ones with you in this chat.       │
└────────────────────────────────────────────────────────────┘
```

- Header icon: the check tile (as on the connected card) when everything succeeded; a warning tile
  when anything failed.
- **Counts line:** done · failed · skipped (omit zeros).
- **Per group:** ✓ with the done count ("10 of 12" when some failed or were skipped); ▸ opens the
  records.
- **Failed:** each failed change on its own, with **the CRM's own message, verbatim** (R-6.2), e.g.
  *Salesforce: "Industry is required when Type is Customer"*.
- **Skipped:** unticked changes are not listed; a change whose record **changed in the CRM since the
  card was shown** is listed as skipped with that reason (it is never written, design 6.4).
- Caption: **"Clue will fix the failed ones with you in this chat."** when anything failed.

### D. Not allowed

- Collapsed to the header: muted icon, **"You didn't allow these changes"**, **"Declined by
  {name} · {time}"**. Nothing was sent. The groups can still be opened to see what was proposed.

### E. Replaced

- When the agent proposes again before this card was answered, this card collapses to
  **"Replaced by a newer proposal"** (muted, no buttons) — only one live write card per chat (§7).

### F. Paused

- When the CRM connection expires while sending: **"Paused — {CRM} needs to be reconnected"**, with
  the counts so far and a link to where the CRM is reconnected (the settings page, R-10.14).
  Sending resumes in order after reconnecting (design 6.6).

## 4. Behaviour

- **Answering locks the card** for everyone; other open tabs show the new state live.
- **Who answered** is always shown afterwards (allowed / declined by, and when).
- Changes covered by a standing permission never appear on a card; they are sent straight away and
  show only in the done summary of the agent's next message and in the write log.
- **Owner/admin-only change** — "Add Clue's own fields to {CRM}" (`clue_fields_setup`, design 6.8
  option B) — is shown **alone** on its own card, never with other groups, with no "Always allow".
  For a member who isn't an owner or admin, the Allow button is disabled with the caption
  **"Only an owner or admin can allow this."**

## 5. Wording per kind of change

| Kind | Group title (HubSpot) | Group title (Salesforce) | "Always allow" phrase |
|---|---|---|---|
| Add to list / campaign | Add {n} {companies / contacts} to the list "{list}" | Add {n} contacts to the campaign "{campaign}" | adding records to Clue lists and campaigns (R-12.8) |
| Remove from list / campaign | Remove {n} {companies / contacts} from the list "{list}" | Remove {n} contacts from the campaign "{campaign}" | removing records from Clue lists and campaigns (R-12.8) |
| Create a list / campaign | Create the list "{name}" | Create the campaign "{name}" | creating Clue lists / campaigns |
| Set a field | Set "{field label}" on {n} {companies / contacts} | Set "{field label}" on {n} {accounts / contacts} | setting "{field label}" on {companies / contacts} |
| Create contacts | Create {n} contacts | Create {n} contacts | creating contacts |
| Create companies | Create {n} companies | Create {n} accounts | creating companies / accounts |
| Mark possible duplicates | Mark {n} possible duplicates | Mark {n} possible duplicates | marking possible duplicates |
| Clue's own fields (admin) | Add Clue's own fields to HubSpot | Add Clue's own fields to Salesforce | — (never standing) |

Use the CRM's own field label (e.g. "ICP tier", "Buying role"), never an internal field id. Numbers
are written as digits. Singular when {n} is 1 ("Create 1 contact").

## 6. What the card receives (for engineering)

- `proposal_id`, `crm` (hubspot | salesforce), project name, state (asking · sending · done ·
  declined · replaced · paused).
- `groups`: kind, object, field label, title, count, value summary, reason, records (id, name,
  secondary line, before, after), and the standing-permission phrase.
- `overwrites`: record, field label, before, after, set by / set at (or unknown), reason.
- `outcome` (sending / done / paused): counts, per-group results, failed changes with the CRM's
  message, skipped changes with the reason, answered by and when.

## 7. Decided (founder, 2026-10-22, R-6.22)

1. **"Fully automatic"** lives on the settings page, not on the card.
2. **One live write card per chat:** a new proposal before the old one is answered replaces it
   (state E).
3. **Header icon** in the asking state: the CRM's logo (HubSpot or Salesforce) in the symbol tile.
