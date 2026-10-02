---
schema_version: "1"
kind: skill
name: manual-tools
version: v3
summary: "Manual: every governed tool this role holds, with its address, effect, inputs, outputs, refusal codes and the next move for each, and what the human sees."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
# Tools: the governed surface of head-of-abm@v56

Every tool you hold, read off the live descriptor. The address is what the platform
registered; the model calls it under the bare name. A call is one governed plan: it is
validated, executed and journaled, and you get a bounded receipt or a typed refusal.
Nothing here grants anything. What you may call is stated once, by your resolved
resource and capability map, and that map is authoritative.

A refusal means nothing was recorded. Correct exactly what the reasons name and call
again, or tell the human what is blocking you. Never report a refused call as done.
Error shapes and the budget that stops a repair loop are in `.deepagent/skills/manual-errors/v3/SKILL.md` and
`.deepagent/skills/manual-limits/v3/SKILL.md`.

| Tool | Effect | Spends | Opens a gate | The human sees |
| --- | --- | --- | --- | --- |
| `draft_account_research_directive@5` | write | no | no | Prepare the research plan |
| `get_research_view@1` | read | no | no | Complete a project step |
| `inspect_statement_history@1` | read | no | no | Complete a project step |
| `launch_arv2_account_research@1` | spend | yes | no | Complete a project step |
| `launch_arv2_discovery@1` | spend | yes | no | Complete a project step |
| `launch_arv2_person_research@1` | spend | yes | no | Complete a project step |
| `open_design_leg@4` | write | no | no | Complete a project step |
| `open_directive_confirmation_gate@1` | write | no | yes | Complete a project step |
| `open_icp_confirmation_gate@2` | write | no | yes | Prepare the profile for your review |
| `open_product_set_selection_gate@1` | write | no | yes | Complete a project step |
| `propose_field@2` | write | no | no | Complete a project step |
| `propose_source@1` | write | no | no | Complete a project step |
| `read_account_research@2` | read | no | no | Review an account's research |
| `read_artifact@1` | read | no | no | Open an artifact |
| `read_arv2_account_research_run@1` | read | no | no | Complete a project step |
| `read_claims@1` | read | no | no | Query the claims |
| `read_discovery_run@2` | read | no | no | Review the discovery run |
| `read_project_accounts@1` | read | no | no | Review the project's accounts |
| `record_interview_answer@1` | spend | yes | no | Save your answer |
| `submit_ingestion@1` | spend | yes | no | Complete a project step |

## draft_account_research_directive@5

**What it does.** Persist one non-spending immutable account-research directive draft only after the human has finished revising the conversational working plan. The result is a complete review preview, not human confirmation, spend authorization, launch, or research.

- Effect class: `write`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: ResearchDirectiveId(operation_id).
- Pins the call is bound to: `project`, `product`, `icp`, `field_registry`, `source_registry`.
- Journal-safe input fields: `project_id`, `product_id`, `icp_key`, `icp_version`.
- The human sees: "Prepare the research plan".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `project_id` | `str` | required | min_length=1, max_length=255 | Trusted current project; supplied by the platform. |
| `product_id` | `str` | required | min_length=1, max_length=255 | — |
| `icp_key` | `str` | required | min_length=1, max_length=255 | — |
| `icp_version` | `int` | required | ge=1 | — |
| `directive` | `ResearchDirectiveBodyDraftInput` | required | none | — |
| `account_overrides` | `tuple[ResearchDirectiveOverrideInput, ...]` | `()` | max_length=500 | — |
| `predecessor_id` | `Optional[ResearchDirectiveId]` | `None` | none | — |
| `user_instruction` | `str` | required | strip_whitespace=True, min_length=1, max_length=8000 | Injected by the platform from this turn. Never author one. |
| `source_turn_ref` | `str` | required | strip_whitespace=True, min_length=1, max_length=1000 | Injected by the platform from this turn. Never author one. |
| `profile` | `Literal['comprehensive', 'custom']` | `'comprehensive'` | none | — |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `directive_id` | `str` | — |
| `directive_ref` | `str` | — |
| `version` | `int` | — |
| `canonical_json_sha256` | `str` | — |
| `status` | `str` | — |
| `memory_outcome` | `str` | — |
| `future_thread_memory_persisted` | `bool` | — |
| `memory_refs` | `list[str]` | — |
| `account_override_refs` | `list[str]` | — |
| `preview_sha256` | `str` | — |
| `preview` | `ResearchDirectivePreview` | — |

*ResearchDirectivePreview*: Bounded complete review payload; questions remain explicitly labeled as hypotheses.

| Field | Type | What it is |
| --- | --- | --- |
| `directive_ref` | `str` | — |
| `version` | `int` | — |
| `status` | `str` | — |
| `account_ids` | `tuple[str, ...]` | — |
| `sealed_selection_ref` | `str or None` | — |
| `field_keys` | `tuple[str, ...]` | — |
| `hypotheses` | `tuple[ResearchQuestion, ...]` | — |
| `source_policy` | `ResearchSourcePolicy` | — |
| `committee_plan` | `ResearchCommitteePlan` | — |
| `privacy_policy` | `ResearchPrivacyPolicy` | — |
| `effort_policy` | `ResearchEffortPolicy` | — |
| `exclusions` | `tuple[str, ...]` | — |
| `account_overrides` | `tuple[ResearchDirectiveAccountPreview, ...]` | — |
| `memory_outcome` | `str` | — |
| `future_thread_memory_persisted` | `bool` | — |
| `unresolved_prerequisites` | `tuple[str, ...]` | — |
| `rendered_summary` | `str` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `memory_write_not_configured` | Tell the human this deployment cannot record research direction; nothing you do can compose the seam. |
| `research_directive_replay_conflict` | Do not send different direction under the same operation; start a fresh call with the direction you actually want. |
| `research_directive_invalid` | Fix exactly the scope, product, lineage or field the message names, then draft again. |

**Afterwards.** A draft research directive exists for the project run. It is a proposal only: it directs nothing until a human confirms it at the directive gate, and the lane it feeds is the retired one, so nothing in ARV2 reads it.

**Taught by.** Not taught by the current skill. This pair belongs to the retired research lane.

**See also.** `.deepagent/skills/manual-siblings/v3/SKILL.md`, `.deepagent/skills/manual-gates-authority/v3/SKILL.md`.

## get_research_view@1

**What it does.** Invoke exact governed platform tool get_research_view@1.

- Effect class: `read`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: exact workspace/project/run/product/subject read.
- Pins the call is bound to: `project_run`, `field_registry`, `verification_policy`.
- Journal-safe input fields: `project_id`, `project_run_id`, `subject_entity_id`, `product_id`.
- The human sees: "Complete a project step".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `project_id` | `str` | required | min_length=1 | — |
| `project_run_id` | `UUID` | required | none | — |
| `subject_entity_id` | `UUID` | required | none | — |
| `subject_entity_type` | `EntityType or None` | `None` | none | — |
| `product_id` | `str or None` | `None` | min_length=1 | — |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `view_id` | `str` | — |
| `snapshot_id` | `str or None` | — |
| `workspace_id` | `str` | — |
| `project_id` | `str` | — |
| `subject_entity_id` | `str` | — |
| `product_id` | `str or None` | — |
| `source_state_sha256` | `str` | — |
| `fetch_ref` | `str` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `research_view_workspace_not_admitted` | Stop using this tool and read the account with read_account_research instead. |
| `research_view_feature_disabled` | Stop using this tool and read the account with read_account_research instead. |
| `research_view_not_configured` | Stop using this tool and read the account with read_account_research instead. |
| `research_view_subject_not_found` | Stop using this tool; the subject it wants does not exist on this lane. Read the account with read_account_research instead. |

**Afterwards.** Nothing. It is a read, and on this deployment it is a read that cannot answer: it is disabled by flag and keyed to a project run this lane never writes.

**Taught by.** Not taught by the current skill. Use the ARV2 reads instead.

**See also.** `.deepagent/skills/manual-tools/v3/SKILL.md`, `.deepagent/skills/manual-accounts-research/v3/SKILL.md`.

## inspect_statement_history@1

**What it does.** Invoke exact governed platform tool inspect_statement_history@1.

- Effect class: `read`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: exact workspace/project read of durable Stage-0 history.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `project_id`, `statement_id`, `route_key`, `cursor`.
- The human sees: "Complete a project step".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `project_id` | `str` | required | min_length=1 | Trusted project authority; supplied by the platform, never by you. |
| `cursor` | `str or None` | `None` | min_length=1 | Opaque position marker. This is the tool that resolves the card's `statements_over_cap` and `excluded_statement_evidence_missing` omissions — pass their `cursor` verbatim to read exactly the rows the card could not carry. A `next_cursor` from a previous page continues that walk; leave it out to start at the newest row. Never build or edit one. |
| `statement_id` | `UUID or None` | `None` | none | One statement to read, with its whole correction lineage in both directions. Refused together with `route_key`: two selectors that disagree is a bug, not an intersection. |
| `route_key` | `str or None` | `None` | min_length=1 | Read every statement under one route key instead of one statement. Refused together with `statement_id`. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `project_id` | `str` | — |
| `view` | `str` | — |
| `statements` | `list[dict[str, object]]` | — |
| `page_size` | `int` | — |
| `returned` | `int` | — |
| `total_matching` | `int or None` | — |
| `candidates_scanned` | `int` | — |
| `has_more` | `bool` | — |
| `next_cursor` | `str or None` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `statement_selector_ambiguous` | Pass statement_id or route_key, never both, and call again. |
| `cursor_invalid` | Call again with no cursor to start from the first page; never build or edit a cursor by hand. |
| `cursor_kind_unsupported` | Use only a cursor this tool itself returned; a cursor from another tool addresses another list. |
| `statement_evidence_not_configured` | Tell the human the evidence reader is not wired here, and do not present the history as empty. |
| `stage0_project_not_found` | Name the project from your project card, and tell the human if that project is still refused. |

**Afterwards.** Nothing changes. You hold a page of what the human has stated, with each statement's quote and its corrections, and the cursor to continue from.

**Taught by.** Not taught by the current skill, though it is granted and it works.

**See also.** `.deepagent/skills/manual-documents-decisions/v3/SKILL.md`.

## launch_arv2_account_research@1

**What it does.** Launch (or exactly replay) ARV2 account research: one governed research job per selected account on the shared fleet, pinned to the confirmed ICP artifact digest and the project's confirmed product-selection version. Call only when the current user action explicitly approves this exact account set and ICP. A successful result means the jobs were enqueued or replayed; it never means research has completed, and it authorizes no contact research. Manual: .deepagent/skills/manual-tools/v3/SKILL.md#launch_arv2_account_research

- Effect class: `spend`.
- Spends: yes. This call costs money against the project's providers.
- Opens a human gate: no.
- Replay identity: workspace + project + account set + ICP digest + product-set version + profile digest.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `project_id`, `account_entity_ids`, `icp_artifact_key`, `product_selection_version`, `effort`, `committee_cap`.
- The human sees: "Complete a project step".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `project_id` | `str` | required | none | — |
| `account_entity_ids` | `tuple[str, ...]` | required | min_length=1, max_length=200 | — |
| `icp_artifact_key` | `str` | required | none | — |
| `icp_artifact_sha256` | `str` | required | none | — |
| `product_selection_version` | `int` | required | ge=1 | — |
| `effort` | `Literal['full', 'reduced', 'cheap-pass']` | `'full'` | none | — |
| `committee_cap` | `int` | `5` | ge=1, le=12 | — |
| `directive_text` | `str` | `''` | none | — |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `run_id` | `str` | — |
| `job_ids` | `tuple[str, ...]` | — |
| `replayed` | `bool` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `arv2_account_research_not_composed` | Tell the human the research lane is not wired on this deployment, and say the research did not start. |
| `launch_action_ref_missing` | Do not retry from an earlier message. Ask the human, in this turn, to name the accounts they want researched. |
| `lane_disabled` | Tell the human the research lane is switched off on this deployment, and say the research did not start. |
| `project_not_found` | Take the project id from your project card and call again; do not guess one. |
| `account_not_found:<id>` | Drop the account the code names, or ask the human to import or discover it first, then launch the rest. |
| `account_not_in_workspace:<id>` | Drop the account the code names; it belongs to another workspace and cannot be researched here. |
| `project_icp_not_pinned` | Confirm an ICP at the ICP gate first, then launch on a later turn. |
| `icp_artifact_not_project_pin` | Name the ICP artifact the project actually pinned, or drop the argument and let the pin speak. |
| `icp_artifact_not_found` | Tell the human the pinned ICP document is missing from this workspace and must be confirmed again. |
| `icp_artifact_not_confirmed` | Confirm the ICP at the gate first; a proposal is not something research can run against. |
| `icp_digest_mismatch` | Tell the human the pinned ICP has changed since it was pinned, and that it must be confirmed again before research runs. |
| `icp_front_matter_invalid` | Tell the human which front-matter field the pinned ICP document is missing; it has to be authored and confirmed again. |
| `product_selection_version_unknown` | Name a product-set version the message lists as confirmed, or omit it and let the current confirmation speak. |

**Afterwards.** A research run is queued for exactly the accounts you named, pinned to the ICP version the project pinned and the product set the human confirmed. A successful call means queued, never finished and never that anything was found. The launched-task card appears in chat on its own. Read the run with read_arv2_account_research_run, and the accounts with read_project_accounts.

**Taught by.** stage0-interview v33 section 7, "Launch account research".

**See also.** `.deepagent/skills/manual-siblings/v3/SKILL.md`, `.deepagent/skills/manual-gates-authority/v3/SKILL.md`, `.deepagent/skills/manual-accounts-research/v3/SKILL.md`.

## launch_arv2_discovery@1

**What it does.** Launch (or exactly replay) ARV2 verified account discovery for one project: a long list built from the confirmed ICP document version the project pinned, then verified company by company against that document's hard gates. Call only when the current user action explicitly approves searching for new accounts for this project. The ICP, the gates and the provider ask all come from the pinned document and the deployment's settings — never from this call — and a successful result means the run was created or replayed, never that companies have been found or approved. It approves nothing and researches nothing. Manual: .deepagent/skills/manual-tools/v3/SKILL.md#launch_arv2_discovery

- Effect class: `spend`.
- Spends: yes. This call costs money against the project's providers.
- Opens a human gate: no.
- Replay identity: workspace + project + pinned ICP digest + target count + provider ask + criteria gate keys.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `project_id`, `target_count`, `relaxed_enabled`.
- The human sees: "Complete a project step".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `project_id` | `str` | required | none | — |
| `target_count` | `int` | `20` | ge=1, le=500 | — |
| `relaxed_enabled` | `bool` | `True` | none | — |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `run_id` | `str` | — |
| `replayed` | `bool` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `arv2_discovery_not_composed` | Tell the human discovery is not wired on this deployment, and say no run started. |
| `launch_action_ref_missing` | Do not retry from an earlier message. Ask the human, in this turn, to confirm they want accounts discovered. |
| `lane_disabled` | Tell the human discovery is switched off on this deployment, and say no run started. |
| `target_count_invalid` | Ask for at least one company and call again. |
| `project_not_found` | Take the project id from your project card and call again; do not guess one. |
| `project_icp_not_pinned` | Confirm an ICP at the ICP gate first; discovery searches against the version this project pinned and nothing else. |
| `icp_artifact_not_found` | Tell the human the pinned ICP document is missing from this workspace and must be confirmed again. |
| `icp_artifact_not_confirmed` | Confirm the ICP at the gate first; discovery does not search against a proposal. |
| `icp_digest_mismatch` | Tell the human the pinned ICP has changed since it was pinned, and that it must be confirmed again before discovery runs. |
| `icp_front_matter_invalid` | Tell the human which front-matter field the pinned ICP document is missing; it has to be authored and confirmed again. |
| `unknown_criteria_gate_key` | Tell the human the pinned ICP's hard gates cannot be compiled into a search, and quote the gate the message names. |

**Afterwards.** A discovery run is queued against the ICP version the project pinned. It approves nothing: the candidates land on the accounts table with a verdict each, and a human adds the ones they want. Read it back with read_discovery_run before proposing another.

**Taught by.** stage0-interview v33 section 7b, "Discover accounts for this project".

**See also.** `.deepagent/skills/manual-discovery/v3/SKILL.md`, `.deepagent/skills/manual-siblings/v3/SKILL.md`, `.deepagent/skills/manual-gates-authority/v3/SKILL.md`.

## launch_arv2_person_research@1

**What it does.** Launch (or exactly replay) ARV2 person research on named contacts of this workspace: one governed research job per person on the shared fleet, under a run of its own pinned to the project's currently confirmed ICP and product selection. Call only when the current user action explicitly approves researching these exact people. It researches existing contacts and never creates a person; a successful result means the jobs were enqueued or replayed, never that research has completed. `persona` is the committee seat each named person is given if they do not already hold one — it is what puts them on the account's contact list — and defaults to `user`. Manual: .deepagent/skills/manual-tools/v3/SKILL.md#launch_arv2_person_research

- Effect class: `spend`.
- Spends: yes. This call costs money against the project's providers.
- Opens a human gate: no.
- Replay identity: workspace + project + contact set + resolved ICP digest + product-set version + profile digest.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `project_id`, `contact_entity_ids`, `persona`.
- The human sees: "Complete a project step".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `project_id` | `str` | required | none | — |
| `contact_entity_ids` | `tuple[str, ...]` | required | min_length=1, max_length=50 | — |
| `directive_text` | `str` | `''` | none | — |
| `persona` | `Persona` | `<Persona.USER: 'user'>` | none | The committee seat every named person is given, from the platform's closed vocabulary. It is what makes them visible on their account's contact list at all (W2), and it is only written for a person who does not already hold a seat. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `run_id` | `str` | — |
| `job_ids` | `tuple[str, ...]` | — |
| `replayed` | `bool` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `arv2_account_research_not_composed` | Tell the human the research lane is not wired on this deployment, and say the research did not start. |
| `launch_action_ref_missing` | Do not retry from an earlier message. Ask the human, in this turn, to name the people they want researched. |
| `lane_disabled` | Tell the human the research lane is switched off on this deployment, and say the research did not start. |
| `no_contacts` | Name at least one contact and call again. |
| `project_not_found` | Take the project id from your project card and call again; do not guess one. |
| `contact_not_found:<id>` | Drop the contact the code names, or ask the human to add that person first, then launch the rest. |
| `contact_merged:<id>` | Launch the surviving person the message names instead; claims written to a merged row are read by nothing. |
| `contact_without_account` | Drop that contact and tell the human their employer is not an account of this workspace; a person is researched at their employer. |
| `project_icp_not_pinned` | Confirm an ICP at the ICP gate first, then launch on a later turn. |
| `icp_artifact_not_found` | Tell the human the pinned ICP document is missing from this workspace and must be confirmed again. |
| `icp_artifact_not_confirmed` | Confirm the ICP at the gate first; a proposal is not something research can run against. |
| `icp_digest_mismatch` | Tell the human the pinned ICP has changed since it was pinned, and that it must be confirmed again before research runs. |
| `icp_front_matter_invalid` | Tell the human which front-matter field the pinned ICP document is missing; it has to be authored and confirmed again. |
| `product_set_not_confirmed` | Open the product-set gate and let the human confirm what this project sells, then launch on a later turn. |

**Afterwards.** A research run is queued for exactly the contacts you named. It researches people who already exist and never creates one; the persona you name is only the committee seat a person takes if they hold none. Queued is not finished.

**Taught by.** stage0-interview v33 section 8, "Research named people".

**See also.** `.deepagent/skills/manual-siblings/v3/SKILL.md`, `.deepagent/skills/manual-accounts-research/v3/SKILL.md`, `.deepagent/skills/manual-claims/v3/SKILL.md`.

## open_design_leg@4

**What it does.** Hand this conversation to the design deepagent — the only way to get a website (or any design artifact) made. Use it the moment the user asks for a landing page, microsite, or page to be built or changed. For a NEW website pass doc_kind='web' and no document_id: an empty web document is created and the leg is pinned to it, so the artifact appears in the project's gallery immediately. Pass title as the name the user would recognise ("Insight Health landing page"); omitted, it is taken from the brief. Put the user's actual ask in brief — what the page is for, who it is for, what it must say — because Design sees the brief, not this conversation. To keep working on an EXISTING artifact pass its document_id instead (doc_kind is then ignored). For a NEW ad or any designed page pass doc_kind='scene' and no document_id: an empty design document is created (no page yet) and the design agent authors the page itself — size, unit (px for digital, mm/in for print) and layout come from the user's own words, so put everything the user said about format, dimensions, medium and purpose in brief. Do not infer or restate dimensions yourself; Design owns them. To resume a design session you closed by mistake, pass reopen_leg_id — a reopen ignores every other field. While the leg is open, every user message on this thread goes directly to Design — you will not see the thread again until the leg closes. Opening a leg spends nothing and runs no design turn: the user's NEXT message is what starts generation, and generating a page takes minutes, not seconds. Tell the user the design session is open and end your turn.

- Effect class: `write`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: one design leg per delegating turn (leg id derived from the turn), and one born document per leg (document id derived from the leg) — both in one transaction.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `document_id`, `doc_kind`, `expected_document_version`, `brand_kit_id`, `brand_kit_version`.
- The human sees: "Complete a project step".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `source_turn_ref` | `str` | required | strip_whitespace=True, min_length=1, max_length=1000 | Injected by the platform from this turn. Never author one. |
| `brief` | `str` | required | min_length=1, max_length=16000 | The design brief — what the user wants made. Free text (D5: no fabricated content plane). |
| `document_id` | `str or None` | `None` | min_length=1, max_length=200 | Target document (nullable — a leg may create its document, §2.1). |
| `doc_kind` | `Optional[Literal['web', 'scene']]` | `None` | none | What to create when there is no `document_id` — REQUIRED on a document-less open. `web` births one empty website-mode document; `scene` births one empty, PAGELESS design document (genad2 ruling 1, 2026-08-23 — @3 took an `ad_format` and minted an artboard; the design deepagent owns page geometry now). With a `document_id` present the durable row's own kind is the truth and this field is ignored. |
| `title` | `str or None` | `None` | min_length=1, max_length=200 | The born document's title (F5). Absent ⇒ the brief's first ~8 words. Ignored when the leg pins an existing document — a delegation never renames someone else's artifact. |
| `expected_document_version` | `int or None` | `None` | ge=0 | The document version the agent believes is current. When present it must match the durable `current_version` exactly (the D5 CAS guard); when absent the current version is pinned. |
| `brand_kit_id` | `str or None` | `None` | min_length=1, max_length=200 | The D5 fail-closed brand pin — both fields or neither. |
| `brand_kit_version` | `int or None` | `None` | ge=1 | — |
| `claim_refs` | `tuple[ContactHandoffClaimRef, ...]` | `()` | max_length=200 | Governed claim edges (ids + stamps, never values) — the C8 §2.3 vocabulary. |
| `binding_set_ref` | `str or None` | `None` | min_length=1, max_length=500 | Design's real content vocabulary, both nullable (ruling D5a). |
| `template_revision_ref` | `str or None` | `None` | min_length=1, max_length=500 | — |
| `reopen_leg_id` | `str or None` | `None` | min_length=1, max_length=64 | The §2.2 mis-exit recovery: re-delegation NAMES the closed leg to reopen it. The same leg returns `open_awaiting_user` with its original bundle and history — context resumes, and the exit journal record survives. When present, the pin/bundle fields above are ignored: a reopen is a resumption, not a fresh delegation. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `leg_id` | `str` | — |
| `leg_ref` | `str` | — |
| `thread_id` | `str` | — |
| `bundle_artifact_key` | `str` | — |
| `bundle_sha256` | `str` | — |
| `document_id` | `str or None` | — |
| `document_version_guard` | `int or None` | — |
| `brand_kit_id` | `str or None` | — |
| `brand_kit_version` | `int or None` | — |
| `created` | `bool` | — |
| `document_created` | `bool` | `True` when this call BIRTHED the pinned document (@2). A replay of the same delegation returns the same `document_id` with `False` — the birth already happened, and nothing is created twice. |
| `reopened` | `bool` | `True` when this call reopened a closed leg (the mis-exit recovery path). |

**Refusals**

| Code | Next move |
| --- | --- |
| `design_leg_runtime_not_configured` | Tell the human design is not wired on this deployment; a leg opened here could never run. |
| `design_leg_storage_not_configured` | Tell the human this deployment has no artifact storage, so no design leg can open. |
| `design_leg_turn_ref_malformed` | Do not retry. The turn reference is injected by the platform, so this is a platform fault to report. |
| `design_leg_turn_not_found` | Do not retry. Report that this turn cannot be resolved and let the human start a new one. |
| `design_leg_turn_execution_missing` | Do not retry. Report that this turn has no execution row for the leg to attach to. |
| `design_leg_replay_closed` | Call again naming the closed leg in reopen_leg_id rather than opening a second one. |
| `design_leg_already_open` | Tell the human a design leg is already open on this thread and they can keep talking to Design. |
| `design_document_not_found` | Name a design document this workspace holds, or omit document_id and pass doc_kind to start a new one. |
| `design_document_pin_stale` | Re-read the document, take its current version, and delegate again. |
| `design_document_pin_incomplete` | Pass the document id alongside the expected version, or pass neither. |
| `design_leg_doc_kind_required` | Pass doc_kind 'web' for a new website or 'scene' for a new ad, or name an existing document_id. |
| `brand_kit_pin_incomplete` | Pass brand_kit_id and version together, or pass neither and let the platform choose. |
| `brand_kit_pin_not_found` | Name a brand kit version this workspace holds; there is deliberately no fallback to a default kit. |
| `design_bundle_too_large` | Trim the brief or the claim set and delegate again; the bundle carries references, not content. |
| `design_leg_reopen_not_found` | Name a design leg this workspace holds, or open a fresh one. |
| `design_leg_reopen_wrong_thread` | Only a leg of this conversation can be reopened; open a fresh one here instead. |
| `design_leg_reopen_not_closed` | Tell the human that leg is still open and they can simply keep talking to Design. |

**Afterwards.** A design leg is open on this thread and the design agent takes over the conversation. You do not run again while it is open and you cannot close it; the human ends it by saying so. The artifact it produces appears in the project's gallery.

**Taught by.** Not taught by the current skill.

**See also.** `.deepagent/skills/manual-siblings/v3/SKILL.md`, `.deepagent/skills/manual-gates-authority/v3/SKILL.md`.

## open_directive_confirmation_gate@1

**What it does.** Present the human with the confirmation gate for one drafted account-research directive and one exact account set: it records what you are asking them to approve and the server-computed maximum spend for that set. It spends nothing, confirms nothing, and launches nothing — end the turn awaiting input with the returned gate_ref, and only the human's own confirming turn can answer it.

- Effect class: `write`.
- Spends: no.
- Opens a human gate: yes, whose kind the output names. Put the gate id it returns into `open_gate_refs` when you finalize, or the human never sees the card.
- Replay identity: the presented gate for one turn + one exact directive revision.
- Pins the call is bound to: `project_run`, `research_directive`.
- Journal-safe input fields: `project_run_id`, `research_directive_id`, `account_entity_ids`.
- The human sees: "Complete a project step".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `project_run_id` | `str` | required | min_length=1, max_length=64 | — |
| `research_directive_id` | `str` | required | min_length=1, max_length=64 | — |
| `account_entity_ids` | `tuple[str, ...]` | required | min_length=1, max_length=500 | — |
| `source_turn_ref` | `str` | required | strip_whitespace=True, min_length=1, max_length=1000 | Injected by the platform from this turn. Never author one. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `gate_id` | `str` | — |
| `gate_ref` | `str` | — |
| `gate_kind` | `str` | — |
| `subject_ref` | `str` | — |
| `subject_revision` | `int` | — |
| `expected_subject_sha256` | `str` | — |
| `max_spend_cents` | `str` | — |
| `currency` | `str` | — |
| `account_count` | `int` | — |
| `addressee_user_id` | `str` | — |
| `created` | `bool` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `gate_subject_malformed` | Pass canonical identifiers, with each account named once, and call again. |
| `gate_turn_ref_malformed` | Do not retry. The turn reference is injected by the platform, so this is a platform fault to report. |
| `gate_turn_not_found` | Do not retry. Report that this turn cannot be resolved and let the human start a new one. |
| `gate_addressee_missing` | Do not retry. Report that this turn records no human the gate could be addressed to. |
| `gate_project_run_not_found` | Name a project run of this conversation's project and call again. |
| `account_discovery_not_started` | Tell the human account discovery has to finish before profiling can be proposed. |
| `account_discovery_in_progress` | Tell the human discovery is still running, and wait for it rather than opening the gate again. |
| `account_discovery_not_sealed` | Tell the human discovery did not finish cleanly and has to be run again first. |
| `account_discovery_seal_invalid` | Tell the human discovery's result is incomplete and has to be run again first. |
| `research_directive_not_found` | Name a directive of this conversation's project, or draft one first. |
| `research_directive_not_draft` | Only a current draft can be presented; draft a new one rather than re-presenting a settled directive. |
| `research_directive_invalid` | Fix exactly the scope or field the message names in the draft, then present it again. |

**Afterwards.** A gate card is waiting for the human, carrying the directive and its cost estimate. Put the returned gate id in open_gate_refs and end the turn awaiting_input, or the human never sees it. Nothing is authorized until they answer.

**Taught by.** Not taught by the current skill. This pair belongs to the retired research lane.

**See also.** `.deepagent/skills/manual-gates-authority/v3/SKILL.md`, `.deepagent/skills/manual-humans-screens/v3/SKILL.md`.

## open_icp_confirmation_gate@2

**What it does.** Present one of this brand's ICP knowledge documents to the current human for confirmation. Supply the icp_key of the document you have read; the platform derives and persists the exact document, digest, permitted decisions, project and addressee. This call confirms nothing. Then end the turn awaiting input with the returned gate_ref. Manual: .deepagent/skills/manual-tools/v3/SKILL.md#open_icp_confirmation_gate

- Effect class: `write`.
- Spends: no.
- Opens a human gate: yes, of kind `icp_confirmation`. Put the gate id it returns into `open_gate_refs` when you finalize, or the human never sees the card.
- Replay identity: one presenting turn plus one exact ICP knowledge document.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `icp_key`.
- The human sees: "Prepare the profile for your review".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `icp_key` | `str` | required | min_length=1, max_length=200 | — |
| `source_turn_ref` | `str` | required | strip_whitespace=True, min_length=1, max_length=1000 | Injected by the platform from this turn. Never author one. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `gate_id` | `str` | — |
| `gate_ref` | `str` | — |
| `gate_kind` | `Literal['icp_confirmation']` | — |
| `subject_ref` | `str` | — |
| `subject_revision` | `int` | — |
| `expected_subject_sha256` | `str` | — |
| `permitted_decisions` | `tuple[IcpGateDecision, ...]` | — |
| `addressee_user_id` | `str` | — |
| `created` | `bool` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `gate_turn_ref_malformed` | Do not retry. The turn reference is injected by the platform, so this is a platform fault to report. |
| `gate_turn_not_found` | Do not retry. Report that this turn cannot be resolved and let the human start a new one. |
| `gate_addressee_missing` | Do not retry. Report that this turn records no human the gate could be addressed to. |
| `icp_document_not_found` | Write the ICP document first with author_icp_document, then open the gate on that key in the same turn. |
| `icp_document_not_servable` | Open the gate on a proposed or confirmed ICP document; nothing else is something to say yes to. |
| `icp_already_confirmed_for_project` | Tell the human this project has already confirmed this exact document, and move on to what it unblocks. |
| `icp_gate_already_presented_elsewhere` | Tell the human this document is already waiting for an answer in another thread, and point them there. |
| `icp_gate_already_answered` | Tell the human this document already carries a human decision; author a new version if they want to change it. |

**Afterwards.** A gate card is waiting for the human, carrying the ICP document itself. Put the returned gate id in open_gate_refs and end the turn awaiting_input. Their approval mints a confirmed version and pins it to this project; you cannot confirm it yourself.

**Taught by.** stage0-interview v33 section 5, "Confirm the profile".

**See also.** `.deepagent/skills/manual-gates-authority/v3/SKILL.md`, `.deepagent/skills/manual-documents-decisions/v3/SKILL.md`, `.deepagent/skills/manual-humans-screens/v3/SKILL.md`.

## open_product_set_selection_gate@1

**What it does.** Ask the current human which of this brand's products this project is about. The platform derives the candidates from the brand's own product rows and the current product catalog; you may pass the icp_key you are working from to pre-check its products. This call confirms nothing. End the turn awaiting input with the returned gate_ref. Manual: .deepagent/skills/manual-tools/v3/SKILL.md#open_product_set_selection_gate

- Effect class: `write`.
- Spends: no.
- Opens a human gate: yes, of kind `product_set_selection`. Put the gate id it returns into `open_gate_refs` when you finalize, or the human never sees the card.
- Replay identity: one product-set presentation for one presenting turn and one brand catalog.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `icp_key`.
- The human sees: "Complete a project step".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `icp_key` | `str or None` | `None` | min_length=1, max_length=200 | The ICP the conversation is working from, if there is one. It only decides which candidates are *pre-checked*; it never decides what may be chosen, and it confirms nothing. |
| `source_turn_ref` | `str` | required | strip_whitespace=True, min_length=1, max_length=1000 | Injected by the platform from this turn. Never author one. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `gate_id` | `str` | — |
| `gate_ref` | `str` | — |
| `gate_kind` | `Literal['product_set_selection']` | — |
| `candidate_count` | `int` | — |
| `suggested_count` | `int` | — |
| `addressee_user_id` | `str` | — |
| `created` | `bool` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `product_set_turn_not_found` | Do not retry. Report that this turn cannot be resolved and let the human start a new one. |
| `product_set_addressee_missing` | Do not retry. Report that this turn records no human the gate could be addressed to. |
| `product_set_project_unavailable` | Do not retry. Report that this turn's project cannot be resolved. |
| `product_set_no_candidates` | Tell the human this brand has no products on record yet, and that onboarding has to add them before a set can be confirmed. |
| `icp_key_unknown` | Name a key a current ICP document actually carries, or omit icp_key and present every product. |

**Afterwards.** A gate card is waiting for the human, listing the brand's own products. Put the returned gate id in open_gate_refs and end the turn awaiting_input. Their choice becomes the project's confirmed product set, which the launches require.

**Taught by.** stage0-interview v33 section 5, "Confirm the products".

**See also.** `.deepagent/skills/manual-gates-authority/v3/SKILL.md`, `.deepagent/skills/manual-documents-decisions/v3/SKILL.md`, `.deepagent/skills/manual-humans-screens/v3/SKILL.md`.

## propose_field@2

**What it does.** Invoke exact governed platform tool propose_field@2.

- Effect class: `write`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: workspace + complete proposal scope + field key + immutable payload hash.
- Pins the call is bound to: `proposal_policy`, `brand`, `field_registry`.
- Journal-safe input fields: `scope`, `proposed_by_ref`.
- The human sees: "Complete a project step".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `brand_id` | `str` | required | none | Trusted brand authority; supplied by the platform, never by you. |
| `scope` | `ProposalScopeInput` | required | none | — |
| `payload` | `FieldProposalPayload` | required | none | — |
| `proposed_by_ref` | `str or None` | `None` | none | — |
| `project_id` | `str or None` | `None` | none | Trusted project authority; supplied by the platform, never by you. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `field_proposal_id` | `str` | — |
| `field_key` | `str` | — |
| `status` | `str` | — |
| `materialization_id` | `str or None` | — |
| `materialization_status` | `str or None` | — |
| `claim_ref` | `str or None` | — |
| `client_kb_version` | `int or None` | — |
| `refusal_code` | `str or None` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `proposal_scope_not_found` | Check the brand, product, project and ICP you named against your project card; one of them is not real, and the refusal deliberately does not say which. |
| `dynamic_client_kb_materializer_not_configured` | Tell the human this deployment cannot promote a client field automatically, and leave the proposal unmade. |

**Afterwards.** A field proposal is recorded for review. It registers nothing on its own: until it is promoted, no claim can be written against the key you proposed.

**Taught by.** Not taught by the current skill.

**See also.** `.deepagent/skills/manual-fields/v3/SKILL.md`, `.deepagent/skills/manual-claims/v3/SKILL.md`.

## propose_source@1

**What it does.** Invoke exact governed platform tool propose_source@1.

- Effect class: `write`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: workspace + complete proposal scope + source key + immutable payload hash.
- Pins the call is bound to: `proposal_policy`, `brand`, `source_registry`.
- Journal-safe input fields: `scope`, `proposed_by_ref`.
- The human sees: "Complete a project step".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `brand_id` | `str` | required | none | Trusted brand authority; supplied by the platform, never by you. |
| `scope` | `ProposalScopeInput` | required | none | — |
| `payload` | `SourceProposalPayload` | required | none | — |
| `proposed_by_ref` | `str or None` | `None` | none | — |
| `project_id` | `str or None` | `None` | none | Trusted project authority; supplied by the platform, never by you. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `source_proposal_id` | `str` | — |
| `source_key` | `str` | — |
| `status` | `str` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `proposal_scope_not_found` | Check the brand, product, project and ICP you named against your project card; one of them is not real, and the refusal deliberately does not say which. |

**Afterwards.** A source proposal is recorded for review. Nothing fetches from it until a human promotes it with a tier.

**Taught by.** Not taught by the current skill.

**See also.** `.deepagent/skills/manual-claims/v3/SKILL.md`, `.deepagent/skills/manual-gates-authority/v3/SKILL.md`.

## read_account_research@2

**What it does.** Read what research found about one account. section='overview' returns the written overview sections (prose citing claim ids); when the overview is not written yet the read refuses with overview_not_written — then read section='claims'. section='claims' returns the claims the account pages show, one page at a time: set limit for how many you want (default 40), follow next_offset until it is null, or narrow with field_prefix to one of the families listed in 'prefixes' (e.g. 'account.resonance', 'core'). A page can come back shorter than limit and still name a next_offset. Sensitive, unverified tier-4 and outreach-unsafe claims are held back and counted in 'excluded'. Read this before saying anything specific about an account. Effect-free. Manual: .deepagent/skills/manual-tools/v3/SKILL.md#read_account_research

- Effect class: `read`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: the account's live display_block rows and its live claims.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `account_entity_id`, `section`, `field_prefix`, `offset`, `limit`.
- The human sees: "Review an account's research".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `account_entity_id` | `str` | required | none | — |
| `section` | `Literal['overview', 'claims']` | `'overview'` | none | — |
| `field_prefix` | `str or None` | `None` | max_length=80 | — |
| `offset` | `int` | `0` | ge=0 | — |
| `limit` | `int` | `40` | ge=1, le=120 | Claims only: how many claims this page may hold. The receipt's byte budget is the other ceiling and usually the binding one, so a page may come back shorter than this and say so with `next_offset`; asking for fewer is how a model reads three families cheaply instead of paying for a hundred claims it will not quote. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `account_entity_id` | `str` | — |
| `account_name` | `str` | — |
| `section` | `str` | — |
| `overview` | `tuple[AccountOverviewSection, ...]` | The written sections when `section='overview'`, else empty. |
| `claims` | `tuple[AccountClaimView, ...]` | The account's servable claims when `section='claims'`, else empty. |
| `truncated` | `bool` | More exists than this page holds: continue with `offset = next_offset` (claims), or read the claims when a long overview was cut. |
| `excluded` | `dict[str, int]` | What the account pages' own gate held back, by reason: `sensitive`, `unverified`, `outreach_unsafe`. A non-zero count means "there is more here, and it is not servable". |
| `offset` | `int` | Where this page started in the account's servable claims. |
| `next_offset` | `int or None` | Where the next page starts, or `None` when this page ends the list. |
| `prefixes` | `dict[str, int]` | The account's claim families with their servable counts. |

*AccountOverviewSection*: One written section of an account's overview page, as it was stored.

| Field | Type | What it is |
| --- | --- | --- |
| `section_key` | `str` | — |
| `body_text` | `str` | `display_block.body_json` as JSON text, capped at `BODY_CHARS`. Text rather than a nested object because the stored body has no bound of its own — nothing in the display package limits how many items a section holds or how long one item is — and an unbounded blob is context the model pays for on every later turn of the thread. |
| `body_truncated` | `bool` | The body was longer than the cap and the tail is not here. |
| `cited_claim_ids` | `tuple[str, ...]` | — |
| `generated_at` | `str` | — |

*AccountClaimView*: One live claim about an account: the value, and what stands behind it.

| Field | Type | What it is |
| --- | --- | --- |
| `claim_id` | `str` | — |
| `field_key` | `str` | — |
| `value` | `Any` | — |
| `source_url` | `str or None` | — |
| `evidence` | `str` | The evidence span, clipped — a quote is here to be *checked*, not reproduced whole. A clipped span ends in `…` so a partial quote is never presented as a complete one. |
| `evidence_truncated` | `bool` | The span was longer than `EVIDENCE_CHARS`; what is here is its opening. |
| `tier` | `int` | — |
| `verification_status` | `str or None` | `claim.verification_status` — `unverified` / `verified` / `rejected`. Served so the model can say *how* a fact is known, not only what it is. |
| `outreach_safe` | `bool or None` | `claim.outreach_safe` — false rows never reach here; the field carries the fact anyway so the shape does not change if the gate ever admits a restricted section. |
| `collected_at` | `str` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `arv2_reads_not_composed` | Tell the human the reads are not wired on this deployment; do not answer from memory instead. |
| `account_not_found` | Take the account id from read_project_accounts and call again; a merged account is refused under its old id, so use the survivor. |
| `overview_not_written` | Read again with section 'claims', and say the overview has not been written yet rather than that the account is unresearched. |
| `account_not_researched` | Say plainly that nothing is known about this account yet, and offer to research it. |
| `no_claims_under_prefix` | Pick one of the families the refusal lists and read again; never invent a prefix. |
| `offset_past_end` | You have already read to the end. Stop paging and answer from what you have. |
| `offset_not_paged` | Drop offset; the overview is served whole. |

**Afterwards.** Nothing changes. You hold what the store actually says about one account, which is what a statement about that account must rest on. Never state a fact about an account from memory of an earlier thread.

**Taught by.** stage0-interview v33 section 7c, "Read before you speak about accounts, claims and artifacts".

**See also.** `.deepagent/skills/manual-claims/v3/SKILL.md`, `.deepagent/skills/manual-fields/v3/SKILL.md`, `.deepagent/skills/manual-accounts-research/v3/SKILL.md`.

## read_artifact@1

**What it does.** Read one artifact from this project's gallery (a landing page or an ad) by its id: section=summary gives what it is, what it is called, its status, its version and the thread it was made on; section=content adds the document's page JSON as text, capped, with body_truncated saying whether there is more. Read this before describing an artifact or what it says. Effect-free. Manual: .deepagent/skills/manual-tools/v3/SKILL.md#read_artifact

- Effect class: `read`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: the design document behind this project's gallery row.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `artifact_id`, `section`.
- The human sees: "Open an artifact".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `artifact_id` | `str` | required | none | The design-document id the gallery lists — what `project/artifacts/index.json` records. |
| `section` | `Literal['summary', 'content']` | `'summary'` | none | `summary` is the card: what it is, what it is called, where it came from. `content` adds the page JSON itself, which is what a question about the words on the page needs. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `artifact_id` | `str` | — |
| `kind` | `str` | `web` (a page) or `ad`. |
| `title` | `str` | — |
| `status` | `str` | — |
| `current_version_id` | `str` | — |
| `origin_thread_id` | `str` | The thread the artifact was made on, so the agent can point the human at the conversation. |
| `updated_at` | `str` | — |
| `body_text` | `str` | `content` only: the document's page JSON as text, capped at `READ_REFERENCES_BUDGET_BYTES`. `summary` leaves it empty. |
| `body_truncated` | `bool` | The page was larger than the cap and what came back is its beginning, not the whole of it. |

**Refusals**

| Code | Next move |
| --- | --- |
| `artifact_not_found` | Take the artifact id from the project's artifact index; an artifact of another project is refused the same way one that never existed is. |
| `project_not_found` | This turn carries no project, so there is no gallery to open. Say that rather than guessing at an artifact. |

**Afterwards.** Nothing changes. You hold one gallery artifact — what it is, what it is called, its status and the thread it was made on — and, if you asked for content, the words on the page as far as the cap allowed. When body_truncated is true, say so rather than describing a page you only saw the beginning of.

**Taught by.** stage0-interview v33 section 7c, "Read before you speak about accounts, claims and artifacts".

**See also.** `.deepagent/skills/manual-documents-decisions/v3/SKILL.md`, `.deepagent/skills/manual-workspace/v3/SKILL.md`.

## read_arv2_account_research_run@1

**What it does.** Read one ARV2 account-research run: what it was pinned to, its status, and the state of each account's job (including the failure code of anything that needs review). Effect-free; it never starts, resumes or changes research. Manual: .deepagent/skills/manual-tools/v3/SKILL.md#read_arv2_account_research_run

- Effect class: `read`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: current ARV2 account research run + job states.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `run_id`.
- The human sees: "Complete a project step".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `run_id` | `str` | required | none | — |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `run_id` | `str` | — |
| `status` | `str` | — |
| `icp_artifact_key` | `str` | — |
| `product_selection_version` | `int` | — |
| `effort` | `str` | — |
| `committee_cap` | `int` | — |
| `jobs` | `tuple[dict[str, str], ...]` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `arv2_account_research_not_composed` | Tell the human the research lane is not wired on this deployment, and do not describe the run as finished or failed. |
| `arv2_account_research_run_not_found` | Use the run id the launch returned; a run of another workspace is refused the same way one that never existed is. |

**Afterwards.** Nothing changes. You hold one research run's status and its per-account progress, which is how you answer "how is the research going?" without launching anything.

**Taught by.** stage0-interview v33 section 7, "Launch account research", for reading the run back.

**See also.** `.deepagent/skills/manual-siblings/v3/SKILL.md`, `.deepagent/skills/manual-accounts-research/v3/SKILL.md`.

## read_claims@1

**What it does.** Query the live claims about one account or contact: by field family (field_prefix), source tier, verification status, or collected since a date; paged; the same display gate as the account pages. Use read_account_research for the written overview. Effect-free. Manual: .deepagent/skills/manual-tools/v3/SKILL.md#read_claims

- Effect class: `read`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: the subject's live claims.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `entity_id`, `field_prefix`, `tier`, `verification_status`, `since`, `offset`, `limit`.
- The human sees: "Query the claims".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `entity_id` | `str` | required | none | An account OR a contact: the store keys claims on one entity id, and so does this read. |
| `field_prefix` | `str or None` | `None` | max_length=80 | `account.resonance` narrows to one family — the families the subject actually has come back in `prefixes` on every answer, including an empty one. |
| `tier` | `int or None` | `None` | ge=1, le=4 | The source tier: 1 deterministic API, 2 official source, 3 reputable third party, 4 LLM synthesis. Asking for 1–2 is how a turn quotes only what a deterministic source says. |
| `verification_status` | `Optional[Literal['unverified', 'verified', 'rejected']]` | `None` | none | — |
| `since` | `str or None` | `None` | none | An ISO-8601 date or datetime; claims collected at or after it. "What have we learned since the campaign started?" is this field. |
| `offset` | `int` | `0` | ge=0 | Continue from `next_offset` of the previous page. `0` starts over. |
| `limit` | `int` | `40` | ge=1, le=120 | How many claims this page may hold. The receipt's byte budget is the other ceiling and usually the binding one, so a page may come back shorter than this and say so. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `entity_id` | `str` | — |
| `entity_type` | `str` | `account` or `contact`, resolved from the rows — the read says what it read. |
| `claims` | `tuple[AccountClaimView, ...]` | The matching claims, gated exactly as the account pages gate them. (`AccountClaimView` is the shape; the name is historical — a contact's claim is served in the same shape.) |
| `excluded` | `dict[str, int]` | What the gate held back over the whole subject, by reason: `sensitive`, `unverified`, `outreach_unsafe`. A non-zero count means "there is more here, and it is not servable". |
| `prefixes` | `dict[str, int]` | The subject's servable claim families with their counts — the whole subject's, never this page's and never the filtered subset's, so a query that matched nothing still says what is there. |
| `offset` | `int` | Where this page started in the matching claims. |
| `next_offset` | `int or None` | Where the next page starts, or `None` when this page ends the list. |
| `truncated` | `bool` | More matched than this page holds: continue with `offset = next_offset`. |

*AccountClaimView*: One live claim about an account: the value, and what stands behind it.

| Field | Type | What it is |
| --- | --- | --- |
| `claim_id` | `str` | — |
| `field_key` | `str` | — |
| `value` | `Any` | — |
| `source_url` | `str or None` | — |
| `evidence` | `str` | The evidence span, clipped — a quote is here to be *checked*, not reproduced whole. A clipped span ends in `…` so a partial quote is never presented as a complete one. |
| `evidence_truncated` | `bool` | The span was longer than `EVIDENCE_CHARS`; what is here is its opening. |
| `tier` | `int` | — |
| `verification_status` | `str or None` | `claim.verification_status` — `unverified` / `verified` / `rejected`. Served so the model can say *how* a fact is known, not only what it is. |
| `outreach_safe` | `bool or None` | `claim.outreach_safe` — false rows never reach here; the field carries the fact anyway so the shape does not change if the gate ever admits a restricted section. |
| `collected_at` | `str` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `arv2_reads_not_composed` | Tell the human the reads are not wired on this deployment; do not answer from memory instead. |
| `entity_not_found` | Take the account id from read_project_accounts, or a contact id from a claim you already read; a merged entity is refused under its old id, so use the survivor. |
| `since_invalid` | Write since as a plain ISO date such as '2026-09-01', or drop it and read without it. |
| `offset_past_end` | You have already read to the end. Stop paging and answer from what you have. |

**Afterwards.** Nothing changes. You hold the claims about one account or contact that matched your filters, plus every family the subject actually has, so a query that matched nothing is answered with what is there rather than with a bare no.

**Taught by.** stage0-interview v33 section 7c, "Read before you speak about accounts, claims and artifacts".

**See also.** `.deepagent/skills/manual-claims/v3/SKILL.md`, `.deepagent/skills/manual-accounts-research/v3/SKILL.md`.

## read_discovery_run@2

**What it does.** Read the project's latest discovery run (or one by id): status, what was asked for and found, how many candidates the verifier judged against the ICP, how many were shown and approved, and the candidates with their verdict, best first. Page with offset and limit (default 25) and follow next_offset until it is null to see every candidate; candidate_total is the whole run on every page. Read this before proposing another discovery, and to answer what discovery found. It approves nothing. Effect-free. Manual: .deepagent/skills/manual-tools/v3/SKILL.md#read_discovery_run

- Effect class: `read`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: the project's latest arv2_discovery_run row and its candidates.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `project_id`, `run_id`, `offset`, `limit`.
- The human sees: "Review the discovery run".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `project_id` | `str` | required | none | — |
| `run_id` | `str or None` | `None` | none | Omitted means the project's newest run, which is what "how did discovery go?" means. |
| `offset` | `int` | `0` | ge=0 | How many candidates to skip. With `limit` this walks a run larger than one page — continue from the previous page's `next_offset`; `0` starts at the top. |
| `limit` | `int` | `25` | ge=1, le=50 | How many candidates this page may hold, best first. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `run_id` | `str` | — |
| `status` | `str` | — |
| `icp_key` | `str` | — |
| `icp_version` | `int` | — |
| `target_count` | `int` | — |
| `asked` | `int or None` | — |
| `found` | `int` | — |
| `verified` | `int` | — |
| `shown` | `int` | — |
| `approved` | `int` | — |
| `relaxed_requested` | `bool` | — |
| `started_at` | `str or None` | — |
| `finished_at` | `str or None` | — |
| `candidates` | `tuple[DiscoveryCandidateView, ...]` | — |
| `candidate_total` | `int` | — |
| `offset` | `int` | Where this page started in the run's ordered candidates. |
| `next_offset` | `int or None` | Where the next page starts, or `None` when this page ends the list. |

*DiscoveryCandidateView*: One company a discovery run surfaced, with the verdict the verifier gave it.

| Field | Type | What it is |
| --- | --- | --- |
| `name` | `str` | — |
| `domain` | `str` | — |
| `pass_` | `str` | Which §4 pass surfaced it — `strict` (the full criteria) or `relaxed` (the widened re-search). `pass` is the schema's word on both sides of the wire; the trailing underscore is Python's. The runner re-validates a dumped result in JSON mode, so the model must accept what it serializes — the 2026-09-13 live defect was a serialization-only alias. |
| `disposition` | `str` | `arv2_discovery_candidate.disposition`: `pending` until verified, then `pass` / `partial` / `unclear` / `duplicate_of_existing` / `not_chosen_before`. |
| `decision` | `str or None` | The human's approval — `approved`, or nothing at all. There is no recorded rejection. |
| `fit` | `float or None` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `arv2_reads_not_composed` | Tell the human the reads are not wired on this deployment; do not answer from memory instead. |
| `project_not_found` | Take the project id from your project card and call again; do not guess one. |
| `no_discovery_run` | Say this project has not run discovery yet, and offer to run one. |
| `discovery_run_not_found` | Omit run_id to read this project's newest run; a run of another project is refused the same way one that never existed is. |

**Afterwards.** Nothing changes. You hold what the last discovery asked for, found, verified and had approved. Say that before proposing another run; do not launch one to answer a question this read already answers.

**Taught by.** stage0-interview v33 sections 7b and 7c.

**See also.** `.deepagent/skills/manual-discovery/v3/SKILL.md`, `.deepagent/skills/manual-accounts-research/v3/SKILL.md`.

## read_project_accounts@1

**What it does.** List the accounts in one project with each account's research status (not_started, in_progress, needs_review, completed, suspended) and how it joined the project. Filter by name or domain to find one account; page with limit and offset when total is larger than the page you received. Read this before saying how many accounts there are, which are researched, or before proposing more discovery. Effect-free. Manual: .deepagent/skills/manual-tools/v3/SKILL.md#read_project_accounts

- Effect class: `read`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: current project_account rows + each account's latest ARV2 account job.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `project_id`, `limit`, `query`, `offset`.
- The human sees: "Review the project's accounts".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `project_id` | `str` | required | none | — |
| `limit` | `int` | `100` | ge=1, le=200 | — |
| `query` | `str or None` | `None` | max_length=120 | A name or domain fragment, case-insensitive. Without it, an account past the first page is reachable only by paging — and a model that reads one short page and stops would tell the human their account is not in the project. |
| `offset` | `int` | `0` | ge=0 | How many rows to skip. With `limit` this walks a project larger than one page. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `project_id` | `str` | — |
| `total` | `int` | — |
| `accounts` | `tuple[ProjectAccountView, ...]` | The project's accounts. `total` is the whole **filtered** membership; `len(accounts)` is the page, so the model can say "showing 100 of 240" rather than guessing at the rest. |

*ProjectAccountView*: One account in a project: who it is, where its research stands, and how it got here.

| Field | Type | What it is |
| --- | --- | --- |
| `account_entity_id` | `str` | — |
| `name` | `str` | — |
| `domain` | `str or None` | — |
| `research_status` | `str` | `arv2_research_job.status` verbatim — `not_started` / `in_progress` / `needs_review` / `completed` / `suspended`. An account with no job at all reads `not_started`. |
| `refreshing` | `bool` | The account has been researched before **and** is being researched again right now. |
| `added_via` | `str` | — |
| `added_at` | `str` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `arv2_reads_not_composed` | Tell the human the reads are not wired on this deployment; do not answer from memory instead. |
| `project_not_found` | Take the project id from your project card and call again; do not guess one. |

**Afterwards.** Nothing changes. You hold the project's accounts with each one's research status, which is the list status.md only summarises.

**Taught by.** stage0-interview v33 section 7c, "Read before you speak about accounts, claims and artifacts".

**See also.** `.deepagent/skills/manual-accounts-research/v3/SKILL.md`, `.deepagent/skills/manual-discovery/v3/SKILL.md`.

## record_interview_answer@1

**What it does.** Invoke exact governed platform tool record_interview_answer@1. Manual: .deepagent/skills/manual-tools/v3/SKILL.md#record_interview_answer

- Effect class: `spend`.
- Spends: yes. This call costs money against the project's providers.
- Opens a human gate: no.
- Replay identity: onboarding input + deterministic statement ids + RunId(operation_id).
- Pins the call is bound to: `artifact_input`, `stage0_skill`, `memory_switch`.
- Journal-safe input fields: `brand_id`, `client_entity_id`, `product_id`, `project_id`.
- The human sees: "Save your answer".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `brand_id` | `str` | required | none | Trusted brand authority; supplied by the platform, never by you. |
| `onboarding_input_id` | `str` | required | none | Injected by the platform from this turn. Never author one. The onboarding input that captured this turn. Trusted turn authority: supplied by the platform from the captured turn, never by you. It must exist in this workspace and carry the same `artifact_key`. |
| `artifact_key` | `str` | required | none | Injected by the platform from this turn. Never author one. Artifact key of that captured turn — the same key the onboarding input carries. Trusted turn authority: supplied by the platform, never by you. |
| `answer` | `str` | required | none | Injected by the platform from this turn. Never author one. The captured user message, byte-identical. Trusted turn authority: the platform loads these exact bytes from the captured artifact and verifies their SHA-256 against the onboarding input's `content_sha256`, so there is nothing here for you to retype. Every statement's quote offsets index into this exact string. |
| `client_entity_id` | `str` | required | none | Trusted client-entity authority; supplied by the platform, never by you. |
| `statements` | `list[InterviewStatement]` | required | none | One statement per material fact, preference, or project decision in the answer, each carrying its own exact quote offsets. A turn with nothing material is routed as one `unmapped` statement — routing nothing is never the honest answer. |
| `product_id` | `str or None` | `None` | none | Confirmed product this answer is about, when one exists. |
| `project_id` | `str or None` | `None` | none | Trusted project authority; supplied by the platform, never by you. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `statement_ids` | `list[str]` | — |
| `claim_refs` | `list[str]` | — |
| `memory_refs` | `list[str]` | — |
| `project_state_refs` | `list[str]` | — |
| `proposal_refs` | `list[str]` | — |
| `unmapped_statement_ids` | `list[str]` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `onboarding_input_not_found` | Do not retry. The captured input is injected by the platform, so this is a platform fault to report. |
| `memory_not_configured` | There is no memory route on this surface; route the preference as project state instead. |
| `quote_not_found_verbatim` | Copy the span from the human's message again, character for character, without retyping, tidying or re-punctuating it. |
| `interview_quote_empty` | Quote the human's actual words; a statement with no quote records nothing. |
| `claim_value_not_entailed` | Quote the sentence that actually states the fact, or correct the value to what the quote says, or route the statement as unmapped. |
| `claim_value_judge_unavailable` | Nothing was written. Try once more, or route the statement as unmapped rather than forcing the value through. |
| `interview_entity_required` | Name the contact the claim is about; only an account claim may omit the entity. |
| `interview_entity_not_found` | Use an entity id a read gave you; never author one. |
| `interview_entity_merged` | Record the statement against the surviving person the message names. |

**Afterwards.** Each routed statement is recorded against the human's own words, with the quote bound to the message it came from. Report what the receipt says was recorded, and never describe a refused statement as captured.

**Taught by.** stage0-interview v33 section 6, "Record what they told you".

**See also.** `.deepagent/skills/manual-documents-decisions/v3/SKILL.md`, `.deepagent/skills/manual-claims/v3/SKILL.md`.

## submit_ingestion@1

**What it does.** Invoke exact governed platform tool submit_ingestion@1.

- Effect class: `spend`.
- Spends: yes. This call costs money against the project's providers.
- Opens a human gate: no.
- Replay identity: workspace + artifact content hash + declared material-context hash.
- Pins the call is bound to: `artifact_input`, `ingestion_policy`, `brand`.
- Journal-safe input fields: `artifact_key`, `declared_context`.
- The human sees: "Complete a project step".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `artifact_key` | `str` | required | none | — |
| `brand_id` | `str` | required | none | Trusted brand authority; supplied by the platform, never by you. |
| `declared_context` | `DeclaredMaterialInput` | required | none | — |
| `project_id` | `str or None` | `None` | none | Trusted project authority; supplied by the platform, never by you. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `ingestion_job_id` | `str` | — |
| `artifact_key` | `str` | — |
| `status` | `str` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `ingestion_artifact_not_found` | Use the artifact key from the human's own upload; do not author one. |
| `ingestion_artifact_erased` | Ask the human to upload the file again before it can be ingested. |
| `ingestion_not_configured` | Tell the human ingestion is not wired on this deployment, and say the file was not read. |
| `ingestion_context_invalid` | Name the project for a project instruction, or the product for a product document, and call again. |

**Afterwards.** An ingestion job is queued for the uploaded file. Queued is not read: the extracted content arrives later, so do not describe what the document says on this turn.

**Taught by.** stage0-interview v33 section 6, for an upload the human has already made.

**See also.** `.deepagent/skills/manual-documents-decisions/v3/SKILL.md`, `.deepagent/skills/manual-workspace/v3/SKILL.md`.

## The framework file tools

Always installed beside the governed tools: `edit_file`, `glob`, `grep`, `ls`, `read_file`, `write_file`, `write_todos`. They act on your virtual
workspace, never on a host. They are not governed: they write no receipt and no journal
row, and their errors are plain prefixed strings (`.deepagent/skills/manual-errors/v3/SKILL.md`).

| Tool | What it really does |
| --- | --- |
| `ls(path)` | A flat file walk, not a directory tree. `is_dir` is false on every entry; only the read-only mount roots are marked as directories, and only when you list the root itself. |
| `read_file(file_path, offset=0, limit=2000)` | `offset` and `limit` count LINES, not bytes. The default window is the first 2,000 lines; a longer file is silently cut at the window, so read on with a larger offset. |
| `write_file(file_path, content)` | Whole-file replace inside a writable prefix, with an allowed extension. The quota is checked before the write. |
| `edit_file(file_path, old_string, new_string)` | Compare-and-replace of exactly one occurrence. `replace_all=True` is refused outright. A source text that is absent or not unique is a conflict: copy the span again, never reword it. |
| `glob(pattern, path=None)` | `fnmatch` over a flat list, not a path glob: `*` crosses `/`, and `**` is only two stars. |
| `grep(pattern, path=None, glob=None)` | A plain substring test, not a regular expression, over every file the glob matched. Each matched file is read whole. |
| `write_todos(...)` | The framework's own scratch plan. It writes to graph state only: no file, no durable row, and the human never sees it. |

What you may read and write is the workspace policy in `.deepagent/skills/manual-limits/v3/SKILL.md`; the folders themselves are `.deepagent/skills/manual-workspace/v3/SKILL.md`.

## finalize_turn

The mandatory terminal action, and the only thing that reaches the human. It is not a
toolbelt tool: no address, no effect class, no pins. Calling it ends the turn, so call
it once and last. A turn that never calls it commits nothing and shows the human
nothing.

- `status` is one of `completed`, `awaiting_input`, `blocked`, `failed`. Only `failed`
  may carry a `failure_code`, and `failed` must carry one.
- `user_message` is the message the human reads. `completed` must carry one.
- `awaiting_input` and `blocked` must identify what they wait for: `next_actions`,
  `open_gate_refs`, or a `user_message` that asks for it.
- `open_gate_refs` becomes the gate card; `domain_refs` of a plan-shaped object type
  becomes the plan card. Nothing else you write becomes a card.
- `assumptions` are stored as artifacts and are never shown to the human. If it matters,
  it belongs in `user_message`.
- Finalizing freezes `outputs/`: after it, a write there is a conflict.

Its refusals have their own budget, separate from the governed one (`.deepagent/skills/manual-limits/v3/SKILL.md`), and
the exact strings are in `.deepagent/skills/manual-errors/v3/SKILL.md`.

