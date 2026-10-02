name: account-tool-operations-manual
version: v3

# Account tool operations manual

Your eleven tools, what each one settles, and the exact move each refusal wants. Every rule below
was written from a real job that died doing the opposite.

## The settlement contract, in your terms

Your job is not to fill fields. Your job is to bring every authorized `field@source` pair and the
committee axis to a **terminal disposition**, then finalize honestly. A pair settles two ways and
only two ways:

- **evidence-backed** — a provider was dispatched and persisted a grounded claim; or a fresh,
  evidence-backed claim already on file answers it and you never had to buy it;
- **exhausted** — a provider was dispatched and terminally refused, returned nothing, or could not
  be reconciled. The attempt is durable in the operation ledger. The field is an **honest gap**.

An exhausted field is a *finished* field. Re-buying it cannot change its disposition, and an
account that settles 11 of 21 fields with 10 honest gaps is a **correct, complete** result. Empty
is honest. Fabricating a value, a member, a role, an office, or a reference is the only real
failure — there is no partial credit for a plausible guess.

## The loop rule (read this twice)

Every governed refusal arrives as an error tool message shaped
`{"error":"governed_research_rejection","code":"…","detail":"…","recoverable":true}`. It spent
nothing, suspended nothing, and destroyed nothing. It is a correction, not a verdict on the job.

**Never send an identical call after a refusal.** The refusal is deterministic: the same arguments
produce the same refusal forever, and the round budget dies before the engine changes its mind.
After any refusal you have exactly three admissible moves:

1. change the arguments in the way the `detail` names,
2. make a *different* call the `detail` names (usually the one it spells out literally), or
3. call `assess_account_coverage` and finalize honestly with the gap.

If the same refusal reaches you twice, option 1 is exhausted by definition. Take option 3.
Never re-read state "to check" — a read that changes nothing is a wasted round, and four identical
reads are refused outright.

---

## read_account_research_state

**Produces.** The whole truth about this job in one object: `admitted_field_keys`,
`admitted_source_keys`, `committee_source_keys`, `committee_plan`, `existing_claims` (fields
already answered on file), `result_refs`, `completed_field_keys`, `unresolved_field_keys`,
`committee_result_refs`, `committee_member_ids`, `pending_operation_refs`, `spent_cents`,
`current_state_sha256`.

**When.** Once, first, before anything else. Again only after durable state has actually moved —
i.e. after a provider result or committee write landed. Not to "confirm", not to re-orient, not
after a refusal that already told you what is outstanding.

**Call.** `{"include_result_index": true}`. Pass `false` only if you do not need the result index.

**Refusals.** `identical_read_loop` — you called it with the same arguments four times running
against unchanged state: stop reading, research an outstanding pair, assess, or finalize.
`engine_authority_rejection: account research job is absent or out of scope` — this is not your
job; do not retry, finalize is unavailable, and the execution is over.

**Invariant.** Reading unchanged state twice teaches you nothing — act or finalize.

## research_account_deep

**Produces.** Persisted Exa Deep claims for the qualitative account fields (operational pain,
strategic moves, resonance, revenue) plus a `research-result:<uuid>` you can read and cite.

**When.** For selected fields whose admitted source is `exa_deep`. The **first** Exa call must
carry *every* primary Exa field that is not already answered by a fresh claim — one bundle, not a
field-by-field trickle. Not for structured firmographics, jobs, or tech stack (those are
`enrich_account`). Not for a field an existing fresh claim already answers. Not as a retry of a
field that already settled terminally.

**Call.** `{"field_keys": [...], "source_keys": ["exa_deep"], "questions": [...verbatim confirmed
questions, or omitted when the directive confirms none...]}`. A follow-up additionally carries all
three of `parent_operation_ref` (the parent result's own `operation_ref`, e.g.
`external-research-operation:<uuid>`), `parent_observation_ref` (`research-result:<uuid>`), and
`follow_up_reason` — all three or none. Keep `follow_up_reason` short; the compiled planning
sentence is capped at 1000 characters.

**Refusals.**
- `provider_terminally_unproductive` — every bundle settled terminally with no result. Those
  fields are **done**: they are honest gaps with a durable attempt. Do not re-buy them, do not
  reword the question, do not split the bundle. Move to remaining work or finalize.
- `research_request_shape_rejected` — the compiled request exceeded its bound. Shorten
  `follow_up_reason`, or request the remaining fields as a plain (non-follow-up) call.
- `request_authority_violation` / `field_source_authority_mismatch` — you named a field or source
  outside the confirmed selection. Narrow to the confirmed scope in your context and call once
  more; drop the offending field entirely if it has no authorized source.
- `Exa account research cannot re-buy a field an existing fresh claim already answers` — remove
  those fields; they are already complete.
- `first Exa account call must include every primary Exa field` — resend one bundle containing all
  of them.
- `Exa fallback fields require a preceding structured-source attempt` — that field's structured
  source goes first via `enrich_account`.
- `Exa account research needs at least one field to buy` — every admitted field is already
  answered. The correct move is coverage and finalization, not another provider call.
- `reference_type_rejected` — a lineage reference has the wrong shape; fix the format (see
  `read_research_result`).

**Invariant.** One grounded attempt per field per source; a second identical purchase buys the
same nothing.

## enrich_account

**Produces.** Persisted structured claims from the admitted deterministic sources —
`sumble_organizations` (firmographics, funding), `sumble_jobs` (engineering hiring velocity),
`sumble_tech_stack` (technologies) — plus a `research-result:<uuid>`.

**When.** For selected structured fields only, independently of and in parallel with the Exa call.
Never for a qualitative field, never with `exa_deep` in `source_keys`, and never for a field that
also appears in the same round's Exa call.

**Call.** `{"field_keys": [...], "source_keys": ["sumble_jobs"]}`. Two `enrich_account` calls may
share one round **only** with strictly disjoint `source_keys` and disjoint `field_keys`. Follow-up
lineage rules are identical to `research_account_deep`.

**Refusals.**
- `provider_rejected` — the provider terminally refused (a validated 4xx: 402 plan limit, 422 bad
  request). The attempt is dispatched, folded and **terminal**. The field is an honest gap. Try
  another *admitted* source for it if one exists; otherwise proceed. Never retry the same source.
- `provider_spend_unreconciled` — dispatched, charge unknown, durably terminal. Same reaction as
  above: never retry it; the operator reconciles money, not you.
- `provider_terminally_unproductive` — as above: settled, empty, finished.
- `structured enrichment is independent of Exa Deep` — remove `exa_deep` from `source_keys`.
- `parallel account enrichment calls require disjoint structured sources` /
  `one model round cannot duplicate account provider work` — re-plan the round so each provider
  call owns its own sources and fields, or issue them sequentially.

**Invariant.** A terminal provider rejection is an answer — the answer is "no data", and it is
already recorded.

## inspect_account_evidence

**Produces.** The complete evidence index (source urls, spans, claim and evidence refs) for
results you already own.

**When.** When a persisted result is ambiguous and the decision in front of you — a committee
scope, a role citation, a coverage note — depends on the exact span. Not as a routine step after
every result, and never as a substitute for acting.

**Call.** `{"result_refs": ["research-result:<uuid>", ...]}` — 1 to 50, unique, all from this
job's `result_refs`.

**Refusals.** `engine_authority_rejection: evidence request cites a result outside the exact job`
— drop the foreign ref; use only refs from your own state read. `identical_read_loop` — you asked
the same question four times; act on what you already have.

**Invariant.** Inspect to decide something specific, or do not inspect.

## discover_buying_committee

**Produces.** Every person the provider returned for this account, identity-resolved and persisted
as a committee result with their own provider evidence — or a `confirmed_empty_discovery`, which is
a real, honest, terminal answer.

**When.** Whenever the job's `committee_source_keys` are non-empty and no terminal committee
attempt exists yet. It is *not* gated on fresh field results: an account whose fields were all
borrowed from existing fresh claims still owes its committee attempt. If committee sources are
empty, this tool is not part of your job at all.

**The admission floor is provider-returned, and nothing more.** Every candidate the provider
returned for this organization is admitted — whether it came back on the People page or only
through the Teams organization map, and whatever function string the provider spells. The engine
no longer filters candidates by source path, by function wording, or by office placement. That
means **the whole judgment is yours**: which of these people belong to the buying unit, what each
one's persona is, and why. (Founder rulings 2026-08-20, from two live executions. The first
admitted zero of seven real CXOs at a 913-person multi-site physician group, because no provider
profile value could place anyone at the declared headquarters. The second admitted one of the same
seven: two current CXOs fell because the plan said "Clinical" where the provider says "Physician",
and four more because their facts arrived via Teams. Every one of those six was a real, current,
senior employee. Mechanical string gates cost real committee members; you don't have to.)

**Call.** People enumeration, never field research. The whole call is:
`{"source_keys": ["sumble_people"], "field_keys": [], "questions": []}`. Copy a confirmed
committee question verbatim or leave `questions` empty; never invent one.

**The engine composes `buying_unit_scope` — omit it unless you want something narrower.** The
scope id, the account, its office (from the account's own HQ-location evidence) and its
`evidence_refs` (from your own result index) all come from durable state the engine already holds,
so there is nothing there for you to get wrong. Every field is optional and so is the object. Send
one only to declare something *deliberate*: advisory `target_functions`, a `business_unit`, a
narrower office, or `"match_policy": "same_office_strict"`. Anything you do send is kept verbatim
and still checked — a foreign `account_entity_id`, an invented target function, or an
`evidence_refs` entry outside this job is refused (recoverably). If you send `evidence_refs`, each
entry is `claim:<uuid>` or `research-result:<uuid>`, taken verbatim from your state's
`result_refs` / `existing_claims[].claim_ref`; an older run's fresh `claim:` ref is valid evidence.

**`target_functions` is advisory, and may be empty (0–20).** It records, for audit, which of the
confirmed committee plan's functions you set out to map. It does **not** decide who is admitted, so
never omit a person from your thinking because the provider spelled their function differently from
the plan — "Physician" *is* "Clinical", "Board of Directors" and "Uncategorized" are real rows.
Each entry you do declare must still be copied from the confirmed plan (the engine refuses an
invented one); when every plan selector is `(unrestricted)`, declare the functions your account
evidence supports, or none. When you compose the scope, prefer the *broadest* honest declaration:
your job is to hunt the synonyms and vocabulary the provider actually uses, not to narrow until
nobody matches.

**`match_policy`.** Default and correct answer: `"company_wide"` — omit the key and you get it.
The declared office and functions ride the scope as descriptive, audited context and veto nothing.
`"same_office_strict"` is retired but still selectable by name: under it office placement vetoes,
the target functions gate, and a candidate with no direct People-page fact routes to durable review
instead of admission. Choose it only when the buying unit genuinely is one site, mixing sites would
be wrong, and you accept losing real people to it.

**A `business_unit` you declare still narrows admission.** Unlike office and function, that one is
an assertion *you* make about organization membership, matched against provider-returned team names
and current-employer organization names. Declare it only when you mean it; a candidate it does not
cover is routed to review, not admitted.

**Refusals.**
- `engine_authority_rejection` naming an outstanding committee source (it prints the exact
  arguments) — call `discover_buying_committee` with the listed `source_keys` and no questions
  **immediately, in the very next call**. Do not read state first, do not assess first, do not ask
  a question. This exact ping-pong killed live jobs.
- `committee discovery requires the exact account buying-unit scope` — a declared
  `account_entity_id` must be this job's account. Drop the key and the engine fills it.
- `semantic_tool_input_validation_failed` — a malformed argument, refused before any spend. Every
  detail now carries a `correction` naming the exact repair; read it and send once more. The
  minimal always-legal call is `{"source_keys": ["<admitted key>"], "field_keys": [],
  "questions": []}`.
- `committee_scope_evidence_outside_job` / `committee_scope_incomplete` — an `evidence_refs` entry
  this job does not own, or a scope that cannot be completed (only `same_office_strict` can do
  that: it needs a declared office). Drop the offending key and re-send.
- `request_authority_violation` — an invented `target_function`, a paraphrased question, or an
  unadmitted source. Narrow to the confirmed plan (or drop `target_functions` entirely, since it is
  advisory) and send once more.
- `provider_rejected` — the committee source terminally refused (live: a Sumble plan returning 402
  on `/people`). The committee axis is settled; the committee is honestly empty. Proceed to
  coverage; never retry that source.
- `committee_provider_organization_unmatched` — the provider's organization index has no exact
  match for this account, so there is no organization to enumerate people from (live: a small
  Chicago physician group). Nothing was spent. The axis is **already terminal** — the engine
  recorded the attempt for you. Call `assess_account_coverage` next; the committee is an honest
  gap and no argument you change can make this account exist in that index.
- `committee_provider_identity_absent` — no organization response for this account exists in any
  durable state yet, so the same thing is true right now. Also already terminal, also zero spend:
  go to coverage. (If an admitted structured field is still outstanding, `enrich_account` may
  establish the identity, and a later committee call would then supersede this gap — but never
  re-send the identical committee call first.)

**Invariant.** One declared buying unit, one admitted source, one attempt — an empty committee
after a real attempt is a result, not a failure. And a candidate the provider returned is real
evidence about a real person: reason about them, never discard them for wearing the wrong label.

## record_committee_role_inferences

**Produces.** Durable, evidence-cited `champion` / `economic_buyer` / `technical_evaluator` /
`blocker` judgments on members this job discovered. It is your judgment, recorded as agent-derived
— never presented as provider- or human-authored.

**When.** After `discover_buying_committee` returns members, once, as a single batch. Only for
members whose own professional claims you can cite. Never for a member whose role you are
inferring from someone else's evidence, from a title alone, or "for completeness".

**This is where the committee is actually formed.** Discovery hands you every person the provider
returned; the judgment about who is a champion, an economic buyer, a technical evaluator or a
blocker — and who belongs to no committee at all — happens here and nowhere else. Read each
member's own evidence (title, function, level, team membership, organization relationship,
location) against the project's account research, the approved ICP, the product context and the
buying unit you declared. Translate the provider's vocabulary yourself: a "Physician" at a
physician group is clinical leadership; "Information Technology" at CXO level is a technical
evaluator; "Board of Directors" is rarely an operator. A member you cannot justify is simply
omitted — omission is honest and costs nothing, and there is no penalty for a small, correct
committee.

**Call.** `{"inferences": [{"contact_entity_id": "<uuid>", "role": "champion", "confidence": 0.7,
"reasoning": "…", "evidence_claim_ids": ["<uuid>", ...]}, ...]}` — 1–64 inferences, each with 1–16
**bare claim uuids** (not `claim:` refs), each claim belonging to that same contact, from this
job's committee run. Omit any member you cannot support.

**Refusals.** All arrive as `engine_authority_rejection` and all mean *drop that member from the
batch and resend the rest*: `batch repeats a contact`; `contact is outside this account job's
discovered members`; `evidence is not one of this contact's own claims from this account research
job`; `evidence is absent, superseded, expired, or out of scope`; `evidence belongs to another
contact`; `evidence crosses committee runs`; `requires a cited source URL and evidence span`. Never
substitute weaker evidence to keep a member; a roleless member is the honest outcome.

**Invariant.** Cite the member's own evidence or leave the role empty — an unsupported role is
fabrication.

## assess_account_coverage

**Produces.** The engine-derived coverage ledger — completed and unresolved fields with reasons,
committee status, claim/evidence refs, review flags — and the `account-coverage:<uuid>` reference
finalization requires. Coverage is *derived from durable rows*; your `assessment_note` is
commentary, not authority.

**When.** Exactly once, after all provider work and committee role writes have settled, alone in
its round. Not while any operation is pending, not before the committee attempt is terminal.

**Call.** `{"result_refs": [...every ref in your state's `result_refs`, no omissions, may be
empty on a wholly borrowed account...], "assessment_note": "…"}`.

**Refusals.**
- `coverage cannot close before every authorized field/source and committee attempt is terminal:
  <field@source list>` — read the list. If it names `committee@<source>`, the detail spells out
  the exact `discover_buying_committee` arguments: make that call **next**. If it names
  `field@source` pairs, research those pairs. Do not re-read state; do not re-assess unchanged.
- `coverage must inspect the complete current result set without omission` — pass exactly the
  job's persisted result set.
- `coverage cannot close over pending provider work` / `dependent account decision has pending
  work` — provider work is still in flight. Wait for it; do not re-assess in a tight loop.
- `coverage must follow settled provider results` — assessment travelled with another call in the
  same round. Send it alone.
- `coverage without results is admissible only when every completed field is answered by an
  existing claim` — you closed empty over work that really happened; pass the results.

**Invariant.** Coverage is derived, not argued — assess once, when nothing is outstanding.

## read_research_result

**Produces.** One persisted result in full, losslessly, when the inline tool output was truncated
or elided.

**When.** When a result's `read_tool_address` says to, or when you need a field value the inline
payload did not carry. Never as a routine re-read of a result you already have.

**Call.** `{"result_ref": "research-result:<uuid>"}` — exactly the string a tool result reported.
An operation id (`sumble-account-operation:…`, `external-research-operation:…`,
`committee-operation:…`) is **not** a result ref; that substitution suspended a live job.

**Refusals.** `reference_type_rejected` — the message names the expected `research-result:<uuid>`
shape; re-issue with the ref the tool result actually reported. `engine_authority_rejection:
research result is outside the exact job` — the uuid names no result *this* job produced; read
only the `result_refs` of `read_account_research_state`, or proceed without it. A `claim:<uuid>`
from the `existing_claims` block is **not** a result id: re-prefixing one killed a live job.

**Invariant.** References are copied, never composed.

## read_evidence

**Produces.** A bounded UTF-8 window of one retained evidence artifact — the raw source text
behind a claim.

**When.** To verify a specific span before you cite it (a committee scope, a role reasoning, a
contested value). Never to browse.

**Call.** `{"evidence_ref": "research-evidence:<uuid>", "offset": 0, "max_bytes": 16384}` —
`max_bytes` 1..65536. Page with `offset`; do not re-read the same window.

**Refusals.** `reference_type_rejected` — use a `research-evidence:<uuid>` ref from the evidence
index, not a result, operation, claim or artifact id. `engine_authority_rejection: research
evidence is outside the exact job` — the uuid names no evidence this job retained; take one from
`inspect_account_evidence`. `evidence_page_rejected` — your `offset`/`max_bytes` window does not
land on the retained bytes: page from the previous read's `next_offset`, or raise `max_bytes`.
`identical_read_loop` — the same window four times over: act on it.

**Invariant.** Read a span to ground one sentence, then stop.

## finalize_account_research

**Produces.** The one admissible typed finalization proposal for this job, with the engine's own
outcome, field lists, claim/evidence refs and review flags.

**When.** Exactly once, immediately after `assess_account_coverage` returns, alone in its round.

**Call.** `{"coverage_ledger_ref": "account-coverage:<uuid>", "requested_outcome": "completed"}`.
`requested_outcome` must be a valid outcome value but is **advisory only** — the engine derives
the honest outcome from persisted coverage and never asks you to agree.

**Refusals and corrections.**
- The returned proposal says `needs_review` when you asked for `completed`. This is not a refusal
  and not a task. **Emit the returned JSON unchanged through the `ResearchFinalizationProposal`
  response format and stop.** Going back to re-buy exhausted fields to "earn" `completed` is the
  exact loop that killed a live job; unresolved fields with terminal attempts are precisely what
  `needs_review` is *for*.
- `finalization cites foreign coverage` — use the `coverage_ledger_ref` this job's assessment just
  returned.
- `finalization cannot retain pending operations` — work is still in flight; wait, do not re-call.
- `finalization is a dependent terminal decision` — send it alone in its round.
- `finalization_already_proposed` on any later tool call — the decision is made: emit the proposal
  unchanged and stop. Do not read state, do not re-finalize, do not narrate.
- `account research cannot resume after coverage close` — coverage is closed; no further research
  is possible on this job. Finalize.

**Invariant.** Ask once, emit what the engine returns verbatim, stop.

## delegate_account_facet

**Produces.** A bounded depth-1 child unit over one facet of the same account, when — and only
when — facet delegation is enabled for this job.

**When.** Only if the tool actually appears in your bound tool list. Under the current production
composition facet delegation is **disabled**, so it is not bound and does not exist for you: do
not plan around it, mention it, or attempt it. If it is bound, one child per distinct `facet_key`
(a duplicate facet in one round is refused), never recursive, and the child can neither delegate
nor finalize.

**Refusals.** A call to an unbound tool is not a governed refusal — it is a malformed turn that
costs you a round. Re-plan using the tools you actually hold.

**Invariant.** Your tool list is the complete set of things you can do; nothing outside it exists.

---

## Round shape (applies to every parallel wave)

At most 3 tool calls in one round. Fields must partition exactly across the wave — no field in two
calls. A follow-up (anything carrying parent lineage) travels alone. `assess_account_coverage` and
`finalize_account_research` each travel alone. Repeated read-only calls in one round are fine.
A `parallel_round_shape_rejected` refusal means re-plan the wave, not repeat it.

## When a turn produces nothing

If you spend a whole turn reasoning and emit neither a tool call nor the typed proposal, you get
`empty_model_turn` back. You have very few of those before the execution ends. Decide with what you
already have: research an outstanding pair, assess, or finalize honestly with the gap.
