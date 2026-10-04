---
name: account-adaptation
description: Use when scene creative addresses a named target company, adapts an approved ad for an account, or requests account-specific variants.
---

# Account adaptation

Compose with the selected communicative playbook; keep that family in `playbook`. Use `knowledge/scene/direction-contract.md` without new account fields or opaque IDs.
Read [account-identity-composition](/.deepagent/skills/account-identity-composition/SKILL.md)
for asset selection and identity treatment. This skill owns the account argument.

Separate the context before writing:

- Advertiser: who speaks, with its approved kit, product evidence and voice.
- Target identity: the exact company name/domain and the supplied or retrieved
  source that identifies it. An ambiguous name needs an identity gap, not a guessed domain/logo.
- Account facts: only what supplied or actually retrieved evidence says about
  that target. Metadata and a logo do not establish its needs, stack or results.
- Persona/use-case hypothesis: a proposed audience or relevance angle, recorded
  as an assumption, not an established account fact.
- Campaign intent: the message and real next step this creative should serve.
- Relationship evidence: what supports any customer, partner or endorsement
  statement. Co-placement and visual similarity establish no relationship.

Put actual source descriptions/excerpts in `evidence` and bind factual `copy`
through `evidence_refs`. Bare claim IDs without accessible values/evidence cannot
support copy. Scope personalization to the request:
- For an explicitly logo-only or exact-copy adaptation, preserve the approved
  message and record identity-only scope in `assumptions`.
- For requested audience/use-case relevance, join a supported advertiser capability
  to that supplied audience or task. Without account research, phrase this as an
  invitation or proposed use, not a claim about the target's actual needs or stack.
  Missing research does not turn that request into a logo-only adaptation.

## Reading the account

When the brief names a target company, you can read what research found about it; you are
not limited to the sentences in the brief.

1. Find the account: `read_project_accounts(query=<name or domain from the brief>)`. Read the
   answer's `total`; if the name is not on the first page, read again with `offset`. Never
   guess a domain or a logo for an account you did not find.
2. Read its research: `read_account_research(account_entity_id, section="overview")`. An answer
   of `overview_not_written` is normal for an account whose write-up is not done; then read
   `section="claims"`. An account that research has not run on refuses `section="claims"` with
   `account_not_researched`; say so in `review_needs` and design from the brief. Claims come in
   pages: when `next_offset` is not null, read again with that offset before you state a count
   or say a field is empty. Narrow with `field_prefix` only to a family the answer's `prefixes`
   lists.
3. Ask a specific question with `read_claims(entity_id, ...)` — one family, one source tier,
   only verified, only since a date, or a contact's claims.

Put what you read into `evidence` (the source and the excerpt) and bind copy to it through
`evidence_refs` with the claim id the read gave you. A fact you did not read is not a fact.
An empty field is an honest answer; narrow the message rather than fill the gap.
A read costs nothing and starts no research.

Carry the argument in artwork, requested companion copy, or both. A shared campaign
headline can stay if that complete argument serves the brief. Remove the company
name and logo mentally: identify what audience/task makes the message relevant.
If only the name changed, repair the argument or record the unmet request in
`review_needs`. Keep missing required proof explicit; never invent it.
An invitation is a scope of intent, not mandatory wording. Write natural useful
copy; keep internal phrases such as "an invitation for [company] marketers" in
assumptions unless this is an actual event invitation. Audit advertiser promises
separately from target facts: imperatives still imply capabilities. Coverage,
after-hours availability, compatibility and results need their own evidence;
"positioning" or proposed-use phrasing cannot excuse unsupported added meaning.

For a new account message, construct the argument before choosing a headline:

1. Identify the reader and the task this invitation offers them. Keep the target
   team distinct from its customers: a marketer reaching hotel operators is not
   a hotel operator. Choose the reader from the brief and advertiser capability;
   do not assign every advertiser the same marketing persona.
2. Select one evidenced advertiser mechanism that helps with that task. Inspect
   relevant product/source candidates for what the product actually does. A brand
   slogan establishes voice, not a mechanism or a target's need. Bind capabilities
   to the exact named product; a brand's portfolio does not prove one model does it all.
   A public statement someone at the target made is not your angle when it was about
   another topic or another vendor's product, for example a CEO praising an unnamed AI
   tool. Do not quote it, echo it or build the message on it.
3. Write a concrete proposition connecting that mechanism to the proposed task,
   then choose headline and support that express it together. Address the target
   as an invitation when only its identity is known. Record inferred relevance
   in `assumptions`; bind actual claims to `evidence_refs`. Keep unfulfilled proof
   requests in `review_needs`, not hidden behind the word `positioning`.
4. Choose what the reader should see as well as read: authentic product evidence,
   a useful native diagram, separate artwork, or deliberate type-led emphasis.
   A diagram can explain a supported selection, sequence or handoff with native
   geometry and editable labels; its arrows must represent that real relationship.
   A logo and decorative connector alone explain no product mechanism. Read the
   selected communicative playbook for execution; imagery remains optional unless
   requested. Judge whether the visible relationship makes this argument clearer.

For the name-removal test, state the task and mechanism still present in the
artwork/requested companion copy. An audience label alone supplies no mechanism.
Different accounts may share a useful task; do not invent distinctions or force
new wording merely to make variants look researched. Explicit exact-copy and
identity-only requests retain their original message instead of this rewrite.

When adapting approved creative, inspect its current scene with page/node/geometry
queries and view its render. For variants, put the advertiser kit, effective type,
palette and successful message/artwork groups in `preserve`, with intended changes
in `vary`. A user-approved size belongs to that inspected composition; never
transfer it to another brand as a default. Recompose and
remeasure for longer target names or different images without losing the intended
reading order. Vary messaging only when evidence changes the argument.

Preserve the advertiser's voice, palette and visual system unless a deliberate
departure is requested. Choose the identity treatment through the supporting
skill rather than treating a logo row as the creative concept. CTA presence
follows the actual next step; an awareness ad need not have one.

The direction's `copy` contains only native artwork text, including a separator.
Keep requested companion channel copy out of the image and direction schema; label it separately in the existing
`finalize_run` summary alongside the honest creative status; a loose final chat
message or file alone may not reach the handoff. Apply the same source limits
to that draft. Never report it published or claim delivery through an unreviewed
or failed handoff; name the remaining review gap.

Review the complete argument under `knowledge/scene/review.md`: exact identity,
relationship implications, evidence-scoped copy, placement-size reading order,
logo pixels, editable layers and preserved properties. Keep unresolved checks explicit. Engine audience/slot operations are primitives;
this skill provides neither a connected account picker nor all-account content
scaling. Report only the variants actually made and reviewed.
