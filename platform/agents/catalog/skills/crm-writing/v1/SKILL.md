---
schema_version: "1"
kind: skill
name: crm-writing
version: v1
summary: "Propose CRM writes for the person to approve on a card; act on the answer, repair failures, and undo through the write log."
roles:
  - head_of_abm
readiness_requirements: []
tools:
  - name: connect_crm
    version: "1"
    input_schema_sha256: b931b8aba2d54709cd85dcd6a24006e05b8eca8141a204e3f038ffbf8c79b7b2
    output_schema_sha256: fe5d80d6d7029cf58299db6535df86a83b5ae1be78821787d42690da4130f0ce
  - name: crm_write_log
    version: "1"
    input_schema_sha256: 17871b5c66e4df7e60acb3640152f096ca7abc4bddc3daabf737570d7345cfb3
    output_schema_sha256: fbd5dbbedac51a71215c9c05bce1e3dbcb5703406892a4f84177f0e0f0543ff8
  - name: find_crm_actions
    version: "1"
    input_schema_sha256: 20fa09f6729c71065926a620dc20aee770993516b7f83298187e2bc3333575c0
    output_schema_sha256: effb910afc51b18957479533d8ce879483165961cb26e785856e279630cbeab6
  - name: manage_crm_grants
    version: "1"
    input_schema_sha256: 9809d75e02ea3134d5e6a8a3ccd7e611223534963a8f9bbbfa56bc2dfad1497b
    output_schema_sha256: 956632841f74d3e72deefbd3046a677bd00a0a87dd97a801d9546b5b7fef3721
  - name: propose_crm_changes
    version: "1"
    input_schema_sha256: 4df276a6bfc8255bf2ddbec8e832de2daac96c9009de955532c0c02724f0f8b5
    output_schema_sha256: d8227de9b75aeaefd1757ae6ce8fb094128f60b7223554d8ab23f8cb3e7ef587
framework: deepagents
framework_version: ">=0.6,<0.7"
---
# Write to the CRM

Clue can propose changes to the workspace's CRM. The person approves them on a card, and Clue
sends them. This skill says what Clue writes and why, when to propose a write, how to propose it,
and what to do with the answer and the results.

## 1. What Clue writes, and why

Clue writes only these things:

- Target accounts, added to a Clue list (HubSpot) or to the project's Clue campaign (Salesforce).
- HubSpot's "Target account" and "ICP tier" fields.
- Contacts for the buying-committee members Clue found.
- A company or account that is missing from the CRM.

Nothing else for now: no notes, emails, meetings, tasks or deals. Clue never merges records and
never deletes them.

Write mostly to what Clue owns: its own lists, campaigns and fields. That way the customer's own
workflows are not set off. Never change a rep's standard fields unless the person asks.

## 2. When to propose writes

Propose writes only when the person asks, or when the work clearly calls for it (for example,
"put the target accounts into HubSpot"). Never propose writes on your own after a research job
finishes.

If the CRM is not connected, say so and point the person to connecting it with `connect_crm`.

## 3. Finding the write action

Search with `find_crm_actions` the same way as for reads. Describe what you want to do, such as
"add contacts to a list". Never put customer names or emails in the search text.

Pick an action that is marked as a write. If the tool says an action is not allowed, Clue cannot
make that write yet; say so plainly.

## 4. One proposal per decision

Put everything that belongs to one decision into one `propose_crm_changes` call. Give each change
a short reason; the person reads it on the card (for example, "tier from the confirmed ICP").

Do not split one decision into many cards. A new proposal replaces a card that has not been
answered yet, so finish one proposal before you start another.

## 5. What may be written about a person

You may write:

- the first and last name;
- the job title;
- the link to their company;
- their buying role;
- their work email, but only if it is verified. When there is no verified email, write no
  contact;
- their LinkedIn URL, but only when Clue is sure it is this person.

Never write:

- phone numbers;
- personal research, such as interests, posts and similar;
- sensitive data;
- consent fields, such as opt-out, subscription or do-not-call.

A field Clue may not use for that person in outreach is not written either. The same rules apply
to people in the EU and outside it.

## 6. After proposing

The turn ends on the card. Do not repeat the card in prose; say in one line what is waiting.

When the person answers, Clue sends the changes in the background, and the chat wakes up with the
results.

- **"Don't allow".** Say that nothing was sent. Do not propose the same changes again unless the
  person asks.
- **Some changes unticked.** Respect that.
- **"Always allow".** Those kinds of change go out later without a card. Overwriting a value a
  person set always asks.

## 7. When changes fail or are skipped

- **Failed.** Read the CRM's own message. Repair what can be repaired (for example, a picklist
  value that is not allowed), and propose only the repaired rows.
- **Skipped because the record changed in the CRM since the card.** Say so. Propose again only if
  the person still wants it.
- **CRM disconnected or switched.** The unsent changes were closed. Propose them again after the
  person reconnects.

## 8. The write log and undo

`crm_write_log` answers questions such as "what did Clue change this week?".

To undo a change:

- **A field change.** Propose the old value with `reverses_write_id` set to that change's
  `write_id`. It goes through the card again.
- **An addition to a list or campaign.** Propose the matching removal. Clue removes only members
  it added itself.
- **A created record.** Clue does not undo it. Tell the person to delete it in the CRM if they
  want it gone.

`manage_crm_grants` lists the "Always allow" permissions, and revokes one when the person asks
(for example, "stop setting ICP tier without asking"). Clue never grants them itself.
