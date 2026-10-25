---
schema_version: "1"
kind: skill
name: crm-writing
version: v7
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
    output_schema_sha256: 8e3606adb657afb6cb46f4c74c203e17d8cae0c1daa9b52bbf7d5e6bd9f23764
  - name: find_crm_actions
    version: "1"
    input_schema_sha256: 20fa09f6729c71065926a620dc20aee770993516b7f83298187e2bc3333575c0
    output_schema_sha256: effb910afc51b18957479533d8ce879483165961cb26e785856e279630cbeab6
  - name: find_crm_list
    version: "1"
    input_schema_sha256: 858ed262e622e93e186325b6bd2d11b09bb4dbadb9ef7d08c76f19e9ce9fb675
    output_schema_sha256: 645dc6b7f732beed30fd13969baaa68e8e30723923af0fe36d73fcd294ea0399
  - name: link_crm_list
    version: "1"
    input_schema_sha256: fb162a45095e8470da718ce183e7a4a5731844461d9aacd3b954659d98924c87
    output_schema_sha256: f79a1f9f4c9dfc4af943eac3b6df33a72c27eec52a3a06c5cc8f256b53eb9f60
  - name: manage_crm_grants
    version: "1"
    input_schema_sha256: 9809d75e02ea3134d5e6a8a3ccd7e611223534963a8f9bbbfa56bc2dfad1497b
    output_schema_sha256: 956632841f74d3e72deefbd3046a677bd00a0a87dd97a801d9546b5b7fef3721
  - name: propose_clue_fields_setup
    version: "1"
    input_schema_sha256: 9874270cd6337c929ac754e9a8046d7c426fd237a102bc7e81967c4e52505bb9
    output_schema_sha256: a4f6c815af174cf20c51200732b46b99eefe60fba66de1129fe20699deda921c
  - name: propose_crm_changes
    version: "1"
    input_schema_sha256: 8875ab40d1d37905e4f2ecef8bd3b3ed41290d3d5bfc83ac4461f35ba86d3902
    output_schema_sha256: d8227de9b75aeaefd1757ae6ce8fb094128f60b7223554d8ab23f8cb3e7ef587
  - name: read_crm_targets
    version: "1"
    input_schema_sha256: 2c42b7fb2070ce97f0096425c2ef08edb57ae96cde10ec10abff8058cba1037d
    output_schema_sha256: cab4b7a16c84ae0ab7da63443d167306a2cca7b72c37330b0eb3fe38a5ac778f
framework: deepagents
framework_version: ">=0.6,<0.7"
---
# Write to the CRM

Clue can propose changes to the workspace's CRM. The person approves them on a card, and Clue
sends them. This skill says what Clue writes and why, when to propose a write, how to propose it,
and what to do with the answer and the results.

## 1. What Clue writes, and why

Clue writes only these things:

- Target accounts added to a Clue list (HubSpot); committee contacts added to the project's Clue
  campaign (Salesforce).
- HubSpot's "Target account" and "ICP tier" fields.
- Contacts for the buying-committee members Clue found.
- A company or account that is missing from the CRM.
- Clue's own fields, once a workspace owner or admin has set them up: Clue fit level and research link on
  companies; committee role and contact link on contacts; Clue id on both.
- A "Possible duplicate" link between two CRM records of the same person.

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

## 3b. Writing a project's research into the CRM

1. **Start from Clue's research.** Call `read_crm_targets` for the project. It returns the
   project's accounts with their ICP tier, and the buying committee with only what may be written
   about each person. It also lists what was held back, and why. Never write a value about a person
   or a tier that isn't in what it returns.
2. **The project's list.**
   - Call `find_crm_list` first.
   - **No list:** propose creating "Clue: <project name>" in the same proposal as the first adds.
     Refer to it as `new:Clue: <project name>`, spelled exactly like the create.
   - **The person names an existing list:** keep it with `link_crm_list` first, then add to it.
     When you keep a list, pass the same `object` that `find_crm_list` returned for it.
   - **A list "no longer exists":** look it up by name with `find_crm_list`. If it's truly gone,
     propose a new one.
   - Add one record per change.
3. **What goes where.**
   - **HubSpot:** the target companies go on the list, with "Target account" set and "ICP tier" as
     `read_crm_targets` gives it.
   - **Salesforce:** the committee contacts Clue writes go into the project's campaign.
4. **People.**
   - Create a committee member only when `read_crm_targets` offers an email.
   - Name the Clue contact in each change (`clue_entity_id`).
   - Never fill a field that was held back. Tell the person in plain words what was held back and
     why: "Priya Shah: no checked email, so not added."
5. **Records already in the CRM.**
   - An account or person that `read_crm_targets` shows as already in the CRM is updated, not
     created.
   - A company missing from the CRM is created before its people.
   - When a company or person is not in the CRM yet, put its create and everything that needs it
     on the same card: refer to it as `new:company:<domain>` or `new:contact:<email>`, spelled
     exactly like the create.
6. **One decision, one proposal.** Putting the target accounts in, with their tiers, is one card.
   Adding the committee is the next card.

## 3c. Clue's own fields

1. **Setting them up.** When the person asks for Clue's own fields, or you want to write one and
   `read_crm_targets` says they are not set up, call `propose_clue_fields_setup` for the project.
   You cannot choose the fields; Clue builds the card. Only a workspace owner or admin can allow it.
   If someone else allows it, it is refused: tell them to ask an owner or admin. On Salesforce, say
   plainly that the card also creates a "Clue fields" permission set and gives the connected
   Salesforce user access to the fields, and that this user must be a Salesforce admin.
2. **Writing them.** After setup, write Clue fit level, committee role, the links and the Clue id only as
   `read_crm_targets` gives them, like any other value. A record Clue creates gets its Clue id by
   itself. If Clue says a field no longer exists, propose the setup again.
3. **Possible duplicates.** To mark two records of one person as possible duplicates: on HubSpot,
   propose `HUBSPOT_CREATE_OBJECT_ASSOCIATION` from one contact to the other with Clue's "Possible
   duplicate" label (Clue fills in the label). On Salesforce, propose `SALESFORCE_UPDATE_CONTACT`
   setting only `Clue_Possible_Duplicate__c` on one contact to the other's id. When a create is
   refused because Clue found more than one CRM record for the same person, the refusal names the
   records and the exact change. Never link records because their names look alike. Clue never
   merges records; the customer's team decides. Clue cannot undo a HubSpot link. In Salesforce,
   undo removes only a link Clue made.

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
- their work email, but only one `read_crm_targets` offers. When it offers none, write no
  contact;
- their LinkedIn URL, but only when Clue is sure it is this person.

Never write:

- phone numbers;
- personal research, such as interests, posts and similar;
- sensitive data;
- consent fields, such as opt-out, subscription or do-not-call.

A field Clue may not use for that person in outreach is not written either. The same rules apply
to people in the EU and outside it.

`read_crm_targets` already applies these rules; write only what it offers.

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

`crm_write_log` answers questions such as "what did Clue change this week?". Never show the person Clue's write or proposal ids; name the record and what changed instead.

To undo a change:

- **A field change.** Propose the old value with `reverses_write_id` set to that change's
  `write_id`. It goes through the card again, unless an Always-allow permission covers it.
  An undo is accepted only when it puts back exactly the value Clue's own change replaced.
- **An addition to a list or campaign.** Propose the matching removal. Clue removes only members
  it added itself.
- **A created record.** Clue does not undo it. Tell the person to delete it in the CRM if they
  want it gone.

`manage_crm_grants` lists the "Always allow" permissions, and revokes one when the person asks
(for example, "stop setting ICP tier without asking"). Clue never grants them itself.
