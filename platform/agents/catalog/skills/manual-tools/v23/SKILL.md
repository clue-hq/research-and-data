---
schema_version: "1"
kind: skill
name: manual-tools
version: v23
summary: "Manual: every governed tool this role holds, with its address, effect, inputs, outputs, refusal codes and the next move for each, and what the human sees."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
# Tools: the governed surface of head-of-abm@v77

Every tool you hold, read off the live descriptor. The address is what the platform
registered; the model calls it under the bare name. A call is one governed plan: it is
validated, executed and journaled, and you get a bounded receipt or a typed refusal.
Nothing here grants anything. What you may call is stated once, by your resolved
resource and capability map, and that map is authoritative.

A refusal means nothing was recorded. Correct exactly what the reasons name and call
again, or tell the human what is blocking you. Never report a refused call as done.
Error shapes and the budget that stops a repair loop are in `.deepagent/skills/manual-errors/v23/SKILL.md` and
`.deepagent/skills/manual-limits/v23/SKILL.md`.

| Tool | Effect | Spends | Opens a gate | The human sees |
| --- | --- | --- | --- | --- |
| `inspect_statement_history@1` | read | no | no | Complete a project step |
| `launch_arv2_account_research@1` | spend | yes | no | Complete a project step |
| `launch_arv2_discovery@3` | spend | yes | no | Complete a project step |
| `launch_arv2_person_research@1` | spend | yes | no | Complete a project step |
| `open_design_leg@5` | write | no | no | Complete a project step |
| `propose_field@2` | write | no | no | Complete a project step |
| `propose_source@1` | write | no | no | Complete a project step |
| `read_account_research@2` | read | no | no | Review an account's research |
| `read_artifact@1` | read | no | no | Open an artifact |
| `read_arv2_account_research_run@1` | read | no | no | Complete a project step |
| `read_claims@1` | read | no | no | Query the claims |
| `read_discovery_run@3` | read | no | no | Review the discovery run |
| `read_project_accounts@1` | read | no | no | Review the project's accounts |
| `record_interview_answer@1` | spend | yes | no | Save your answer |
| `run_python@1` | write | no | no | Complete a project step |
| `submit_ingestion@1` | spend | yes | no | Complete a project step |
| `configure_project_targeting@1` | write | no | no | Complete a project step |
| `manage_products@1` | write | no | no | Update the product list |
| `web_search@1` | spend | yes | no | Search the web |
| `connect_crm@1` | write | no | no | Connect your CRM |
| `find_crm_actions@1` | read | no | no | Look up CRM actions |
| `run_crm_action@1` | spend | yes | no | Read from your CRM |
| `write_brand_document@1` | write | no | no | Update brand context |
| `propose_crm_changes@1` | write | no | yes | Propose CRM changes |
| `crm_write_log@1` | read | no | no | Review CRM changes |
| `manage_crm_grants@1` | write | no | no | Manage CRM permissions |

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

**See also.** `.deepagent/skills/manual-documents-decisions/v23/SKILL.md`.

## launch_arv2_account_research@1

**What it does.** Launch (or exactly replay) ARV2 account research: one governed research job per selected account on the shared fleet, pinned to the confirmed ICP artifact digest and the project's confirmed product-selection version. Call only when the current user action explicitly approves this exact account set and ICP. A successful result means the jobs were enqueued or replayed; it never means research has completed, and it authorizes no contact research. Before launching, read .deepagent/skills/account-research-briefing/v3/SKILL.md and write the project-specific delegation brief it teaches in directive_text, with account placeholders and references to the complete pinned documents. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#launch_arv2_account_research

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

**Taught by.** account-research-briefing v3, "Brief the account researcher" (.deepagent/skills/account-research-briefing/v3/SKILL.md); stage0-interview v38 section 7, "Launch account research".

**See also.** `.deepagent/skills/manual-siblings/v23/SKILL.md`, `.deepagent/skills/manual-gates-authority/v23/SKILL.md`, `.deepagent/skills/manual-accounts-research/v23/SKILL.md`.

## launch_arv2_discovery@3

**What it does.** Launch account discovery for one project with the search you write: what kind of company to find (query), what every company must satisfy (criteria), the checks run on every company found (gates, each with a role: must, must_not or prefer), and the companies to leave out with their domains (exclude: the seller's existing customers you chose from brand/knowledge/proof/customers.md, and the seller's own domains). Read section 7b of the stage0-interview skill before calling. The project needs a confirmed ICP and product set. A successful result means the run was created or replayed, never that companies were found; this conversation stays busy until the run ends and you get a turn with its summary. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#launch_arv2_discovery

- Effect class: `spend`.
- Spends: yes. This call costs money against the project's providers.
- Opens a human gate: no.
- Replay identity: workspace + project + the approving user action + the brief + target count.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `project_id`, `target_count`, `source`.
- The human sees: "Complete a project step".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `project_id` | `str` | required | none | — |
| `target_count` | `int` | `20` | ge=1, le=500 | — |
| `source` | `Literal['websets', 'search']` | required | none | — |
| `query` | `str` | required | none | — |
| `criteria` | `list[str]` | required | none | — |
| `gates` | `list[BriefGate]` | required | none | — |
| `exclude` | `list[ExcludedCompany]` | (built per call) | none | — |

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
| `discovery_in_progress` | A discovery is already running in another conversation of this project. Tell the human, and do not retry. |
| `brief_invalid` | Fix the field the message names and call again. |
| `discovery_tool_retired` | Do not retry this address; call the current launch_arv2_discovery with the brief you wrote. |
| `target_count_invalid` | Ask for at least one company and call again. |
| `project_not_found` | Take the project id from your project card and call again; do not guess one. |
| `project_icp_not_pinned` | Confirm an ICP at the ICP gate first; discovery searches against the version this project pinned and nothing else. |
| `icp_artifact_not_found` | Tell the human the pinned ICP document is missing from this workspace and must be confirmed again. |
| `icp_artifact_not_confirmed` | Confirm the ICP at the gate first; discovery does not search against a proposal. |
| `icp_digest_mismatch` | Tell the human the pinned ICP has changed since it was pinned, and that it must be confirmed again before discovery runs. |
| `icp_front_matter_invalid` | Tell the human which front-matter field the pinned ICP document is missing; it has to be authored and confirmed again. |

**Afterwards.** If you have not read section 7b of the stage0-interview skill ("Discover accounts for this project") in this conversation, read it before you call this tool. It says how to write the query, the criteria, the gates and the exclude list. A discovery run is queued with the brief you wrote. It leaves out every company on your exclude list and the seller's own domain, checks every other company against your gates, adds the ones that pass to this project's accounts, and searches again with the same brief for any shortfall, up to three more times. This conversation is busy until it ends; you then get a turn that starts with its summary.

**Taught by.** stage0-interview v45 section 7b, "Discover accounts for this project".

**See also.** `.deepagent/skills/manual-discovery/v23/SKILL.md`, `.deepagent/skills/manual-siblings/v23/SKILL.md`, `.deepagent/skills/manual-gates-authority/v23/SKILL.md`.

## launch_arv2_person_research@1

**What it does.** Launch (or exactly replay) ARV2 person research on named contacts of this workspace: one governed research job per person on the shared fleet, under a run of its own pinned to the project's currently confirmed ICP and product selection. Call only when the current user action explicitly approves researching these exact people. It researches existing contacts and never creates a person; a successful result means the jobs were enqueued or replayed, never that research has completed. `persona` is the committee seat each named person is given if they do not already hold one — it is what puts them on the account's contact list — and defaults to `user`. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#launch_arv2_person_research

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

**See also.** `.deepagent/skills/manual-siblings/v23/SKILL.md`, `.deepagent/skills/manual-accounts-research/v23/SKILL.md`, `.deepagent/skills/manual-claims/v23/SKILL.md`.

## open_design_leg@5

**What it does.** Hand this conversation to the design deepagent — the only way to get a website (or any design artifact) made. Use it the moment the user asks for a landing page, microsite, or page to be built or changed. For a NEW website pass doc_kind='web' and no document_id; for a NEW ad or any designed page pass doc_kind='scene' and no document_id. In both cases also pass artifacts, one item per artifact the user wants — a title the user would recognise, a note with that item's own words (its account, its emphasis), and account_id when the item is for a tagged research account; one item for one ad, twenty for twenty accounts, five for five variants with a distinct emphasis each; the shared ask stays in brief. Each item becomes its own document, opens in its own tab and iterates in its own design session, and they appear in the project's gallery immediately. Put the user's actual ask and your direction in brief — what the artifacts are for, who they are for, the angle, a suggested structure and the facts to draw on, with your private notes kept apart (the brief format is in the siblings chapter of the manual) — because Design sees the brief, not this conversation. Design writes the words on the page itself; do not write its copy. For an ad, you may suggest what its headline could say, but only as a suggestion: never tell Design to use your words. To keep working on an EXISTING artifact pass its document_id instead (doc_kind and artifacts are then refused). On a scene birth the design agent authors the page itself — size, unit (px for digital, mm/in for print) and layout come from the user's own words, so put everything the user said about format, dimensions, medium and purpose in brief. Do not infer or restate dimensions yourself; Design owns them. To resume a design session you closed by mistake, pass reopen_leg_id — a reopen ignores every other field. While the leg is open, every user message on this thread goes directly to Design — you will not see the thread again until the leg closes. Opening a leg starts the design work at once: the platform queues the leg's first design turn from the user's message on this turn, so the user does not need to send anything else. The tool itself makes no provider call; the queued design turn is what spends, and generating a page takes minutes, not seconds. Tell the user the design session is open and what is being made, and end your turn. Queued is not finished: never say the design is done.

- Effect class: `write`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: one design leg per delegating turn (leg id derived from the turn), and one born document per (leg, artifact position) — every birth, the leg and its document rows in one transaction.
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
| `artifacts` | `tuple[DesignArtifactSpec, ...]` | `()` | max_length=200 | What to make, one item per artifact (@5, spec §3.1 — this replaced @4's single `title`). REQUIRED (at least one item) on a document-less open; refused beside `document_id` or `reopen_leg_id`, which name artifacts that already exist. The 200-item schema bound is a sanity bound, not a product cap (ruling 5: no confirmation before spend, at any batch size). |
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
| `document_ids` | `tuple[str, ...]` | Every document of the leg, in position order (@5). `document_ids[0]` is `document_id` — the leg's own pin — and the list is served on every path, read back off `design_leg_document` for a replay or a reopen. |
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

**Afterwards.** A design leg is open on this thread, and its first design turn is already queued from the human's own message, so nobody needs to say anything to start it. The design agent takes over the conversation. You do not run again while it is open and you cannot close it; the human ends it by saying so. The artifact it produces appears in the project's gallery.

**Taught by.** Not taught by the current skill.

**See also.** `.deepagent/skills/manual-siblings/v23/SKILL.md`, `.deepagent/skills/manual-gates-authority/v23/SKILL.md`.

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

**See also.** `.deepagent/skills/manual-fields/v23/SKILL.md`, `.deepagent/skills/manual-claims/v23/SKILL.md`.

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

**See also.** `.deepagent/skills/manual-claims/v23/SKILL.md`, `.deepagent/skills/manual-gates-authority/v23/SKILL.md`.

## read_account_research@2

**What it does.** Read what research found about one account. section='overview' returns the written overview sections (prose citing claim ids), whole sections a page at a time: follow next_offset until it is null to read all of them. When the overview is not written yet the read refuses with overview_not_written — then read section='claims'. section='claims' returns the claims the account pages show, one page at a time: set limit for how many you want (default 40), follow next_offset until it is null, or narrow with field_prefix to one of the families listed in 'prefixes' (e.g. 'account.resonance', 'core'). A page can come back shorter than limit and still name a next_offset. Sensitive, unverified tier-4 and outreach-unsafe claims are held back and counted in 'excluded'. Read this before saying anything specific about an account. Effect-free. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#read_account_research

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
| `truncated` | `bool` | More exists than this page holds: continue with `offset = next_offset`, for claims and overview sections alike. |
| `excluded` | `dict[str, int]` | What the account pages' own gate held back, by reason: `sensitive`, `unverified`, `outreach_unsafe`. A non-zero count means "there is more here, and it is not servable". |
| `offset` | `int` | Where this page started: a claim index for claims, a section index for the overview. |
| `next_offset` | `int or None` | Where the next page starts, or `None` when this page ends the list. |
| `prefixes` | `dict[str, int]` | The account's claim families with their servable counts. |

*AccountOverviewSection*: One written section of an account's overview page, as it was stored.

| Field | Type | What it is |
| --- | --- | --- |
| `section_key` | `str` | — |
| `body_text` | `str` | `display_block.body_json` as JSON text, whole. Text rather than a nested object because the stored body has no bound of its own; the overview pages by whole section instead, so a long overview spreads across reads rather than losing its tail. |
| `body_truncated` | `bool` | This one section is larger than a whole page on its own, so its tail is not here. Every other section is served complete. |
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
| `insights_not_written` | The insights page has not been written yet. Read the overview or the claims instead, and do not describe it as missing research. |
| `context_required` | The account was researched in more than one project and this read could not tell which. Read section 'claims' instead, or ask the human to open the account in the app. |
| `account_not_researched` | Say plainly that nothing is known about this account yet, and offer to research it. |
| `no_claims_under_prefix` | Pick one of the families the refusal lists and read again; never invent a prefix. |
| `offset_past_end` | You have already read to the end. Stop paging and answer from what you have. |

**Afterwards.** Nothing changes. You hold what the store actually says about one account, which is what a statement about that account must rest on. Never state a fact about an account from memory of an earlier thread.

**Taught by.** stage0-interview v33 section 7c, "Read before you speak about accounts, claims and artifacts".

**See also.** `.deepagent/skills/manual-claims/v23/SKILL.md`, `.deepagent/skills/manual-fields/v23/SKILL.md`, `.deepagent/skills/manual-accounts-research/v23/SKILL.md`.

## read_artifact@1

**What it does.** Read one artifact from this project's gallery (a landing page or an ad) by its id: section=summary gives what it is, what it is called, its status, its version and the thread it was made on; section=content adds the document's page JSON as text, capped, with body_truncated saying whether there is more. Read this before describing an artifact or what it says. Effect-free. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#read_artifact

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

**See also.** `.deepagent/skills/manual-documents-decisions/v23/SKILL.md`, `.deepagent/skills/manual-workspace/v23/SKILL.md`.

## read_arv2_account_research_run@1

**What it does.** Read one ARV2 account-research run: what it was pinned to, its status, and the state of each account's job (including the failure code of anything that needs review). Effect-free; it never starts, resumes or changes research. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#read_arv2_account_research_run

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

**See also.** `.deepagent/skills/manual-siblings/v23/SKILL.md`, `.deepagent/skills/manual-accounts-research/v23/SKILL.md`.

## read_claims@1

**What it does.** Query the live claims about one account or contact: by field family (field_prefix), source tier, verification status, or collected since a date; paged; the same display gate as the account pages. Use read_account_research for the written overview. Effect-free. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#read_claims

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

**See also.** `.deepagent/skills/manual-claims/v23/SKILL.md`, `.deepagent/skills/manual-accounts-research/v23/SKILL.md`.

## read_discovery_run@3

**What it does.** Read the project's latest discovery run (or one by id): status, what was asked for and found, how many candidates the verifier judged against the ICP, how many were shown and approved, why the run ended and its summary, and the candidates with their verdict, best first. Companies a gate excluded are listed apart in excluded, each with the gate that excluded it. Page the candidates with offset and limit (default 25) and follow next_offset until it is null; candidate_total is the whole run on every page. Read this before proposing another discovery, and to answer what discovery found. It approves nothing. Effect-free. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#read_discovery_run

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
| `candidates` | `tuple[DiscoveryCandidateV3View, ...]` | The run's candidates without the excluded ones, shown-first and best-fit-first; each carries `excluded_by_gate` (always `null` here). |
| `candidate_total` | `int` | — |
| `offset` | `int` | — |
| `next_offset` | `int or None` | — |
| `source` | `str` | The search the run made: `websets` or `search`. |
| `end_reason` | `str or None` | Why the run ended — `filled`, `dry`, `round_cap`, `wall_clock`, `stopped` or `failed` — or `null` while it is still searching. |
| `summary` | `dict[str, Any] or None` | What the platform told you when the run ended: asked, added, excluded, unclear, the gates that excluded companies with one example each, the last search's criteria pass rates, the searches run, why it ended and the spend. `null` until the run ends. |
| `excluded` | `tuple[DiscoveryCandidateV3View, ...]` | The companies a gate excluded, with the gate, grouped by gate then by name. They were never added to the project's accounts. |
| `excluded_total` | `int` | Every excluded company of the run; `excluded` holds at most 50 of them. |

*DiscoveryCandidateV3View*: `read_discovery_run@3`'s candidate: `@2`'s, plus the gate that excluded it. A subclass rather than a new field on `DiscoveryCandidateView`, because that model is part of `@1`/`@2`'s output schema and a promoted profile pins its digest.

| Field | Type | What it is |
| --- | --- | --- |
| `name` | `str` | — |
| `domain` | `str` | — |
| `pass_` | `str` | — |
| `disposition` | `str` | — |
| `decision` | `str or None` | — |
| `fit` | `float or None` | — |
| `excluded_by_gate` | `str or None` | The key of the `must` gate that failed or the `must_not` gate that passed, for a candidate whose disposition is `excluded`; `None` for every other candidate. |

**Refusals**

| Code | Next move |
| --- | --- |
| `arv2_reads_not_composed` | Tell the human the reads are not wired on this deployment; do not answer from memory instead. |
| `project_not_found` | Take the project id from your project card and call again; do not guess one. |
| `no_discovery_run` | Say this project has not run discovery yet, and offer to run one. |
| `discovery_run_not_found` | Omit run_id to read this project's newest run; a run of another project is refused the same way one that never existed is. |

**Afterwards.** Nothing changes. You hold what the last discovery asked for, found, verified and showed. Say that before proposing another run; do not launch one to answer a question this read already answers.

**Taught by.** stage0-interview v43 sections 7b and 7c.

**See also.** `.deepagent/skills/manual-discovery/v23/SKILL.md`, `.deepagent/skills/manual-accounts-research/v23/SKILL.md`.

## read_project_accounts@1

**What it does.** List the accounts in one project with each account's research status (not_started, in_progress, needs_review, completed, suspended) and how it joined the project. Filter by name or domain to find one account; page with limit and offset when total is larger than the page you received. Read this before saying how many accounts there are, which are researched, or before proposing more discovery. Effect-free. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#read_project_accounts

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

**See also.** `.deepagent/skills/manual-accounts-research/v23/SKILL.md`, `.deepagent/skills/manual-discovery/v23/SKILL.md`.

## record_interview_answer@1

**What it does.** Invoke exact governed platform tool record_interview_answer@1. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#record_interview_answer

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

**See also.** `.deepagent/skills/manual-documents-decisions/v23/SKILL.md`, `.deepagent/skills/manual-claims/v23/SKILL.md`.

## run_python@1

**What it does.** Run a short Python script in a locked-down container over this turn's workspace. Use it to read files that plain text tools cannot open — PDFs, Word documents, slide decks, spreadsheets — and to do arithmetic or produce a CSV, a chart or a report. The script's working directory holds the same folders your file tools use: `attachments/` (read-only) holds every file anyone has attached in this project, `project/` and `brand/` are read-only too, and `scratch/`, `work/` and `outputs/` are yours to write. Write a file if you want to keep it; print what you want to read back. There is no network, so do not try to download anything, and nothing outside those folders exists. Output longer than 16 KB is written to a file and the result tells you its path. You get a few runs per turn, and the result says how many are left, so plan the script before you call. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#run_python

- Effect class: `write`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: this operation's journaled receipt.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `code`, `note`, `timeout_s`.
- The human sees: "Complete a project step".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `code` | `str` | required | min_length=1, max_length=65536 | The whole script, as source. It runs with no network and no arguments; anything it needs it reads from the workspace, and anything it produces it prints or writes to a file. |
| `timeout_s` | `float or None` | `None` | gt=0 | Ask for *less* wall-clock time than the operator allows — useful for a probe you expect to be instant. It is clamped to the operator's ceiling, so it can never buy more. |
| `note` | `str or None` | `None` | max_length=200 | One line saying what this run is for, carried into the journal beside the code. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `exit_code` | `int or None` | The script's exit status; `None` exactly when the run timed out. |
| `timed_out` | `bool` | — |
| `duration_ms` | `int` | — |
| `stdout` | `str` | The script's stdout, up to `INLINE_OUTPUT_BUDGET_BYTES`. |
| `stdout_spilled_to` | `str or None` | Workspace-relative path of the whole stdout when it was larger than the inline budget. |
| `stdout_truncated` | `bool` | The container's own output cap cut this stream before the tool ever saw the end of it. |
| `stderr` | `str` | — |
| `stderr_spilled_to` | `str or None` | — |
| `stderr_truncated` | `bool` | — |
| `files_written` | `tuple[dict[str, object], ...]` | `{"path": …, "size": …}` for every file this run wrote or changed and the policy kept. |
| `files_removed` | `tuple[dict[str, str], ...]` | `{"path": …, "reason": …}` for everything the post-run sweep took back out. |
| `runs_remaining` | `int` | How many runs this turn may still take. |

**Refusals**

| Code | Next move |
| --- | --- |
| `sandbox_unavailable` | Tell the human you cannot open the file on this deployment, and name the file; do not describe contents you never read. No run was spent. |
| `workspace_unavailable` | Do not retry. This call is outside a turn that owns a workspace, so report it and read what you can with the file tools. |
| `run_budget_exhausted` | Say what you have read so far and what is left, and do the rest in one script on the next turn. |

**Afterwards.** One script has run in the sandbox over this turn's workspace and is gone. What it printed is in stdout, or in the file stdout_spilled_to names when it printed more than the inline budget; what it left on disk is in files_written, and anything the workspace policy took back out is in files_removed. Nothing outside your own workspace changed, and runs_remaining says how many runs this turn has left. A file you have not opened is a file you have not read: do not describe an attachment from its name. The script itself is capped at 65,536 characters, which is a validation error rather than a refusal — split the work across runs instead of writing one enormous script.

**Taught by.** code-execution v1 section 1, "When to run code, when not to".

**See also.** `.deepagent/skills/manual-workspace/v23/SKILL.md`, `.deepagent/skills/manual-limits/v23/SKILL.md`.

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

**See also.** `.deepagent/skills/manual-documents-decisions/v23/SKILL.md`, `.deepagent/skills/manual-workspace/v23/SKILL.md`.

## configure_project_targeting@1

**What it does.** Apply this project's ICP and product set automatically, without asking for approval. Read the ICP first and supply its icp_key. Optional product_ids override its product set; otherwise use its products, the existing project set, or the brand's active products. Returns the confirmed artifact and product-selection version for use in the same turn. No gate opens and no research launches. Continue the user's task after this succeeds. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#configure_project_targeting

- Effect class: `write`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: project plus current ICP document and selected product set.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `icp_key`, `product_ids`.
- The human sees: "Complete a project step".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `icp_key` | `str` | required | min_length=1, max_length=200 | — |
| `product_ids` | `tuple[str, ...] or None` | `None` | min_length=1, max_length=200 | — |
| `source_turn_ref` | `str` | required | strip_whitespace=True, min_length=1, max_length=1000 | Injected by the platform from this turn. Never author one. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `project_id` | `str` | — |
| `icp_key` | `str` | — |
| `document_id` | `str` | — |
| `icp_artifact_key` | `str` | — |
| `icp_artifact_sha256` | `str` | — |
| `product_ids` | `tuple[str, ...]` | — |
| `product_selection_version` | `int` | — |
| `approval_mode` | `Literal['automatic']` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `targeting_turn_unavailable` | Use the current durable conversation turn; never invent a reference. |
| `targeting_project_unavailable` | Explain that this project is unavailable in the current workspace. |
| `icp_document_not_found` | Read or write the intended ICP document and use its exact icp_key. |
| `targeting_products_unavailable` | Read the brand catalog and choose its active product ids. |

**Afterwards.** The product set and exact ICP artifact are confirmed and pinned automatically. Continue the user's task using the returned artifact key, digest and product selection version; do not open an approval card. This call launches no research.

**Taught by.** stage0-interview v35 section 4, "Apply the products and ICP automatically".

**See also.** `.deepagent/skills/manual-documents-decisions/v23/SKILL.md`, `.deepagent/skills/manual-gates-authority/v23/SKILL.md`.

## manage_products@1

**What it does.** Change this brand's product list when the person asks you to: add a product, rename one, merge several into one (for example features that onboarding listed as separate products), or remove one. The change applies at once to the product list, the product pages, the catalog and every project that uses those products. For add and merge, write page_markdown: the product's page, from what you know and the pages being merged. If you only suspect the list is wrong, ask the person first instead of calling this. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#manage_products

- Effect class: `write`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: product_change keyed by the presenting turn and the call's inputs.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `action`, `product_id`, `product_ids`, `into_product_id`, `name`.
- The human sees: "Update the product list".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `action` | `Literal['add', 'rename', 'merge', 'remove']` | required | none | What to do to the brand's product list. |
| `product_id` | `str or None` | `None` | max_length=200 | rename / remove: the product to change. |
| `product_ids` | `tuple[str, ...] or None` | `None` | min_length=1, max_length=200 | merge: the products folded in. |
| `into_product_id` | `str or None` | `None` | max_length=200 | merge: fold into this existing product ... |
| `name` | `str or None` | `None` | max_length=240 | ... or (merge) into a product with this name; add / rename: the product's name. |
| `page_markdown` | `str or None` | `None` | max_length=200000 | add / merge: the product's page, written by you. |
| `source_turn_ref` | `str` | required | strip_whitespace=True, min_length=1, max_length=1000 | Injected by the platform from this turn. Never author one. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `change_id` | `str` | The change, as recorded in the brand's product change log. |
| `action` | `str` | — |
| `summary` | `str` | One sentence saying what changed, ready to tell the person. |
| `product_id` | `str` | The product the change is about (for a merge, the product the others were folded into). |
| `product_name` | `str` | — |
| `aliases` | `tuple[str, ...]` | Its other names, including the names of products merged into it. |
| `page_document_id` | `str or None` | The product page this call wrote, for add and merge. |
| `catalog_document_id` | `str` | The regenerated product catalog. |
| `projects_updated` | `int` | Projects whose product set moved to the new list. |
| `projects_needing_choice` | `int` | Projects left with no product, which keep their old set until the person chooses. |

**Refusals**

| Code | Next move |
| --- | --- |
| `products_input_invalid` | Add exactly the field the message names for this action and call again. |
| `products_page_required` | Write the product's page in page_markdown, from the pages being merged and what you know, and call again. |
| `products_turn_unavailable` | Do not retry. The turn reference is injected by the platform; report that this turn cannot be resolved. |
| `products_storage_unavailable` | Tell the person product changes cannot be saved on this deployment right now. |
| `product_not_found` | Read the product catalog again and use a product id from it. |
| `product_not_active` | Read the catalog again; that product was already merged or removed, so work from today's list. |
| `product_name_taken` | Ask the person for a different name, or merge into the product that already has it. |
| `name_invalid` | Use a product name between 1 and 240 characters. |
| `merge_invalid` | Name at least one other product to merge, and either into_product_id or name but not both. |

**Afterwards.** The brand's product list, its product pages and its catalog changed together, and every project that used a merged or removed product now uses the new list (each shows a notice in its chat). Old names are kept as "also called" names. Tell the person what changed in one sentence; the next turn's brand files already reflect it.

**Taught by.** No skill section; the tool's own description says when to call it (spec 2026-10-15 product management).

**See also.** `.deepagent/skills/manual-documents-decisions/v23/SKILL.md`.

## web_search@1

**What it does.** Search the open web and read back what it found: a short written answer, then up to ten results with title, URL, date and highlighted passages. Use this last. What the platform has already researched is in the claim store and in the seller's knowledge files, and those come first, every time. Reach for this only when you have looked there and what you need is not there, or is vague or inconclusive, or when the human has brought you something the platform never researched, like an event, a workshop or a topic outside the seller's products. What it returns is text for you to read and use now. It is not a claim, it is not verified, and it must not be presented as research the platform did.

- Effect class: `spend`.
- Spends: yes. This call costs money against the project's providers.
- Opens a human gate: no.
- Replay identity: ARV2 ledger row on provider_call_ledger keyed on the call; the tool writes no domain state.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `query`, `num_results`, `include_domains`, `exclude_domains`, `start_published_date`, `end_published_date`.
- The human sees: "Search the web".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `query` | `str` | required | min_length=1, max_length=400 | The question or topic to search for, in plain words. Up to 400 characters. |
| `num_results` | `int` | `10` | ge=1, le=10 | How many results to read back, 1 to 10. Ten is the default. |
| `include_domains` | `list[str]` | (built per call) | max_length=10 | Only these sites, up to ten. Leave empty to search the whole web. |
| `exclude_domains` | `list[str]` | (built per call) | max_length=10 | Never these sites, up to ten. Leave empty to exclude nothing. |
| `start_published_date` | `str or None` | `None` | max_length=32 | Only pages published on or after this date, as a plain ISO date such as 2026-01-01. Leave empty for no lower bound. |
| `end_published_date` | `str or None` | `None` | max_length=32 | Only pages published on or before this date, as a plain ISO date. Leave empty for no upper bound. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `answer` | `str or None` | The short written answer the search produced, or null when it produced none. |
| `results` | `list[WebSearchResultItem]` | Up to ten results, most relevant first. |
| `rendered` | `str` | The whole result as one text: the answer, then one numbered block per result. This is what you read. |
| `cost_usd` | `str` | What the search cost, as Exa metered it. |
| `request_id` | `str or None` | Exa's id for this request, for the ledger. |

*WebSearchResultItem*: One search result: what the page is called, where it is, when it was published, and the passages that matched.

| Field | Type | What it is |
| --- | --- | --- |
| `title` | `str or None` | The page's title, when Exa reported one. |
| `url` | `str or None` | The page's address. |
| `published_date` | `str or None` | When the page was published, when known. |
| `highlights` | `list[str]` | The passages from the page that matched the query. |

**Refusals**

| Code | Next move |
| --- | --- |
| `exa_not_configured` | Tell the human web search is not available on this deployment; do not answer the question from memory instead. |
| `query_empty` | Write the question you want searched, in plain words, then call again. |

**Afterwards.** Nothing changes on the platform. You hold the written answer and up to ten results with their highlighted passages, and one search has been charged to the workspace. Read it as what a search found today, not as a fact the platform verified: quote it as "a search found", never as a claim, and never write it into a project document as if research had established it. If the search did not settle the question, say so rather than searching again with the same words.

**Taught by.** head-of-abm prompt v15, the paragraph "Look things up in this order".

**See also.** `.deepagent/skills/manual-claims/v23/SKILL.md`, `.deepagent/skills/manual-accounts-research/v23/SKILL.md`.

## connect_crm@1

**What it does.** Report the workspace's CRM connection (HubSpot or Salesforce), or show the person a card to connect it. When the result's state is 'card', tell the person to use the card and end your turn: the chat continues by itself once the CRM is connected. Pass switch=true only when the person asked to replace the connected CRM with another one. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#connect_crm

- Effect class: `write`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: one connect card per presenting turn (crm_connect_request.turn_id).
- Pins the call is bound to: `project`.
- Journal-safe input fields: `switch`.
- The human sees: "Connect your CRM".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `switch` | `bool` | `False` | none | Only when the person asked to replace the connected CRM with another one. |
| `source_turn_ref` | `str` | required | strip_whitespace=True, min_length=1, max_length=1000 | Injected by the platform from this turn. Never author one. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `state` | `Literal['connected', 'card']` | — |
| `mode` | `Optional[Literal['connect', 'reconnect', 'switch']]` | — |
| `request_id` | `str or None` | — |
| `providers` | `list[Literal['hubspot', 'salesforce']]` | — |
| `can_connect` | `bool` | — |
| `connection` | `CrmConnectionView or None` | — |

*CrmConnectionView*: One row.

| Field | Type | What it is |
| --- | --- | --- |
| `provider` | `Literal['hubspot', 'salesforce']` | — |
| `status` | `str` | — |
| `connected_at` | `datetime` | — |
| `connected_by_user_id` | `str` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `crm_not_configured` | Tell the person the CRM integration is not set up on this deployment, and take the sales numbers by hand (crm-sales-analysis section 11). |
| `crm_turn_not_found` | Do not retry. The turn reference is injected by the platform; report that this turn cannot be resolved. |
| `crm_project_unavailable` | Explain that this conversation's project is unavailable in the current workspace. |

**Afterwards.** Either the workspace's CRM is connected (state "connected": which CRM, since when, by whom) or the chat now shows the person a connect card (state "card"). After a card, say in a sentence why connecting helps and end your turn: the chat continues by itself once the CRM is connected.

**Taught by.** crm-sales-analysis v2 section 2, "Connecting".

**See also.** `.deepagent/skills/manual-humans-screens/v23/SKILL.md`.

## find_crm_actions@1

**What it does.** Search the connected CRM's actions by what you want to do, e.g. 'search deals', 'deal pipeline stages', 'contacts of a company', 'run a SOQL query', 'update a company'. Returns each action's name, its input schema and its access: run a 'read' action with run_crm_action; a 'write' action is never run directly, propose it with propose_crm_changes so the person can approve it. Only reads and the writes Clue allows are listed. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#find_crm_actions

- Effect class: `read`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: none: a catalogue search writes nothing.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `query`, `limit`.
- The human sees: "Look up CRM actions".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `query` | `str` | required | strip_whitespace=True, min_length=1, max_length=200 | — |
| `limit` | `int` | `10` | ge=1, le=25 | — |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `provider` | `Literal['hubspot', 'salesforce']` | — |
| `actions` | `list[CrmActionView]` | — |

*CrmActionView*: One row.

| Field | Type | What it is |
| --- | --- | --- |
| `slug` | `str` | — |
| `access` | `Literal['read', 'write']` | `read`: run it with run_crm_action. `write`: propose it with propose_crm_changes. |
| `description` | `str` | — |
| `input_schema` | `dict[str, Any]` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `crm_not_configured` | Tell the person the CRM integration is not set up on this deployment, and take the sales numbers by hand. |
| `crm_not_connected` | Call connect_crm to ask the person to connect the CRM. |
| `crm_unavailable` | Try once more later in the turn; if it still fails, tell the person the CRM is not answering right now. |

**Afterwards.** A list of the connected CRM's actions that match the search, each with its input schema and its access. Nothing was read from the CRM. Run a read with run_crm_action; propose a write with propose_crm_changes.

**Taught by.** crm-sales-analysis v2 section 3, "Read the setup first"; crm-writing v1 section 3, "Finding the write action".

**See also.** `.deepagent/skills/manual-tools/v23/SKILL.md`.

## run_crm_action@1

**What it does.** Run one read action on the connected CRM (find it first with find_crm_actions). The whole result is written to a file in reads/ and you get back its path, how many records it holds, their field names and, when there are more pages, next_cursor to pass back as the page argument (HubSpot: 'after'; Salesforce: run SALESFORCE_QUERY_MORE with it). Analyse the file with run_python; do not paste records into the chat. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#run_crm_action

- Effect class: `spend`.
- Spends: yes. This call costs money against the project's providers.
- Opens a human gate: no.
- Replay identity: reads/<operation_id>.json, rewritten by a re-run of the same operation.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `slug`.
- The human sees: "Read from your CRM".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `slug` | `str` | required | strip_whitespace=True, min_length=1, max_length=200 | — |
| `arguments` | `dict[str, Any]` | (built per call) | none | — |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `provider` | `Literal['hubspot', 'salesforce']` | — |
| `slug` | `str` | — |
| `path` | `str` | Where the whole result was written; read it with the file tools or `run_python`. |
| `record_count` | `int or None` | — |
| `total` | `int or None` | — |
| `fields` | `list[str]` | — |
| `next_cursor` | `str or None` | — |
| `done` | `bool` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `crm_not_configured` | Tell the person the CRM integration is not set up on this deployment, and take the sales numbers by hand. |
| `crm_not_connected` | Call connect_crm to ask the person to connect the CRM. |
| `crm_connection_expired` | Call connect_crm; it shows the person a Reconnect card. |
| `crm_action_is_a_write` | Do not run it; propose the change with propose_crm_changes so the person can approve it (crm-writing section 4). |
| `crm_action_not_allowed` | Use find_crm_actions to find a read action that does what you need, and run that one. |
| `crm_action_failed` | Check the setup you read (field and stage names), fix the arguments the CRM's message points at, and run it again. |
| `crm_rate_limited` | Wait for the rest of your work in this turn, then try once more; if it still fails, say the CRM is busy. |
| `crm_unavailable` | Try once more later in the turn; if it still fails, tell the person the CRM is not answering right now. |
| `crm_reads_unavailable` | Tell the person CRM reads cannot be saved on this turn, and do not guess numbers. |
| `salesforce_api_disabled` | Explain that this Salesforce org has no API access (Professional Edition needs a paid add-on), and offer to take the numbers by hand. |
| `salesforce_api_share_exhausted` | Tell the person Clue has used its share of the org's API calls for today; work with what you already pulled and continue tomorrow. |
| `salesforce_limits_unavailable` | Try once more; if it still fails, tell the person Clue cannot check the org's API allowance right now, so it is not reading Salesforce. |

**Afterwards.** The whole result is in the file at `path` under reads/; you got only its record count, field names and next_cursor. Fetch every page, then read the files and compute in run_python. Never state a number you did not compute from these files.

**Taught by.** crm-sales-analysis v2 sections 6 and 7, "Pulling the deals" and "Compute in the sandbox".

**See also.** `.deepagent/skills/manual-workspace/v23/SKILL.md`, `.deepagent/skills/manual-limits/v23/SKILL.md`.

## write_brand_document@1

**What it does.** Publish a new version of a Brand-context document under company/, product/, audience/ or proof/ (for example company/sales-motion.md, or an updated proof/customers.md). Use it only when the person asks you to change a brand document, or a skill tells you to; never on your own initiative. The previous version is kept in its history, and the person can read and edit the document in Brand context. Write the whole document, not a change: read the current version from brand/, pass the version you read as based_on_version (from brand/index.json; leave it out only for a new document), and write it back with your changes. The product catalog cannot be written here. Give the document as markdown, or from_file for a file you wrote under outputs/ with run_python. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#write_brand_document

- Effect class: `write`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: the path's current brand-level version: identical bytes return it unchanged.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `path`, `kind`, `from_file`, `based_on_version`.
- The human sees: "Update brand context".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `path` | `str` | required | strip_whitespace=True, min_length=1, max_length=200 | `<company\|product\|audience\|proof>/<name>.md`, lower-case letters, digits and hyphens. |
| `kind` | `str or None` | `None` | none | What the document is, e.g. `sales-motion`. Needed only for a new document; an existing document keeps its kind. |
| `markdown` | `str or None` | `None` | max_length=1000000 | The document's Markdown, without front matter. Give this or `from_file`, not both. Never name an input `body`/`content`/`text`…: the agent's plan validator refuses any binding with one of those names (`clue_execution.graph._RAW_BODY_KEYS`), trial 1 F4. |
| `from_file` | `str or None` | `None` | none | A Markdown file you wrote in the sandbox, e.g. `outputs/sales-motion.md`. |
| `based_on_version` | `int or None` | `None` | ge=1 | The version you read, from `brand/index.json`. Leave it out only for a new document. |
| `source_turn_ref` | `str` | required | strip_whitespace=True, min_length=1, max_length=1000 | Injected by the platform from this turn. Never author one. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `document_id` | `str` | — |
| `path` | `str` | — |
| `version` | `int` | — |
| `unchanged` | `bool` | `True` when the bytes matched the current version, so nothing new was published. |

**Refusals**

| Code | Next move |
| --- | --- |
| `path_not_allowed` | Use a company/, product/, audience/ or proof/ document named <folder>/<name>.md, with a lower-case name of letters, digits and hyphens. |
| `document_generated` | Do not write this document; to change the product list, use manage_products. |
| `document_changed` | Someone saved this document after your turn began. Tell the person, and write it again on the next turn from the new version. |
| `markdown_or_file_required` | Give exactly one of markdown or from_file. |
| `kind_invalid` | Use a kind of lower-case letters, digits and hyphens, such as sales-motion. |
| `kind_required` | The document is new; add a kind, such as sales-motion, and call again. |
| `kind_mismatch` | Leave kind out, so the document keeps the kind it already has. |
| `markdown_empty` | Write the document's Markdown and call again. |
| `front_matter_not_allowed` | Remove the front-matter block and send the Markdown only. |
| `file_not_allowed` | Pass a path under outputs/, such as outputs/sales-motion.md. |
| `file_not_found` | Check files_written from your run_python call and pass the exact path it wrote. |
| `file_too_large` | Shorten the document to under 2 MB and write it again. |
| `file_not_text` | Write the file as UTF-8 Markdown text and call again. |
| `sandbox_unavailable` | Pass the document as markdown instead of from_file. |
| `storage_unavailable` | Tell the person brand documents cannot be saved on this deployment right now. |
| `turn_unavailable` | Do not retry. The turn reference is injected by the platform; report that this turn cannot be resolved. |
| `brand_unavailable` | Explain that this project's brand is unavailable in the current workspace. |

**Afterwards.** A new version of the brand document at `path` is current, attributed to the person whose turn this is; the previous version is kept in its history. `unchanged: true` means the bytes matched the current version and nothing new was published. The next turn's brand/knowledge/ shows it.

**Taught by.** crm-sales-analysis v2 sections 12 and 13, "Write company/sales-motion.md" and "Add the new customers".

**See also.** `.deepagent/skills/manual-documents-decisions/v23/SKILL.md`, `.deepagent/skills/manual-gates-authority/v23/SKILL.md`.

## propose_crm_changes@1

**What it does.** Propose changes to the connected CRM: one batch of write actions found with find_crm_actions (access 'write'), each with its arguments and a one-line reason the person reads. Clue checks every change, reads the values the CRM holds today, and sends at once the changes a standing permission covers. When state is 'awaiting_permission' a permission card asks the person: tell them to use the card and end your turn; the chat continues by itself when the changes are done. Put everything you want to change in one call. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#propose_crm_changes

- Effect class: `write`.
- Spends: no.
- Opens a human gate: yes, whose kind the output names. Put the gate id it returns into `open_gate_refs` when you finalize, or the human never sees the card.
- Replay identity: one crm_write_proposal per presenting turn and exact batch (proposal_id = uuid5 of the turn ref and the input digest).
- Pins the call is bound to: `project`.
- Journal-safe input fields: none.
- The human sees: "Propose CRM changes".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `changes` | `list[CrmChangeInput]` | required | min_length=1, max_length=500 | — |
| `source_turn_ref` | `str` | required | strip_whitespace=True, min_length=1, max_length=1000 | Injected by the platform from this turn. Never author one. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `proposal_id` | `str` | — |
| `state` | `Literal['queued', 'awaiting_permission']` | — |
| `gate_id` | `str or None` | — |
| `gate_ref` | `str or None` | — |
| `gate_kind` | `str or None` | — |
| `covered` | `int` | — |
| `needs_permission` | `int` | — |
| `groups` | `list[CrmChangeGroup]` | — |
| `overwrites` | `int` | — |

*CrmChangeGroup*: One row.

| Field | Type | What it is |
| --- | --- | --- |
| `kind` | `str` | — |
| `object` | `str` | — |
| `field` | `str or None` | — |
| `count` | `int` | — |
| `covered` | `bool` | A standing permission covers these: they are sent without asking. |
| `overwrites_person` | `bool` | These overwrite a value a person set; each is shown on the card on its own, unticked. |

**Refusals**

| Code | Next move |
| --- | --- |
| `crm_not_configured` | Tell the person the CRM integration is not set up on this deployment, so Clue cannot write to the CRM. |
| `crm_turn_not_found` | Do not retry. The turn reference is injected by the platform; report that this turn cannot be resolved. |
| `crm_not_connected` | Call connect_crm to ask the person to connect the CRM, and propose again once it is connected. |
| `crm_connection_expired` | Call connect_crm; it shows the person a Reconnect card. Propose again once they reconnect. |
| `crm_write_not_allowed` | Leave that change out, and tell the person plainly that Clue cannot make this write yet. |
| `crm_write_not_parsable` | Fix the arguments the message names, following the action's input schema from find_crm_actions, and propose again. |
| `crm_field_forbidden` | Leave that field out of every change and propose again; Clue never writes consent or phone fields, and writes only the allowed fields on a person (crm-writing section 5). |
| `crm_value_not_allowed` | Use one of the allowed values the message lists, and propose again. |
| `crm_removal_not_allowed` | Leave that removal out, and tell the person to remove the member in the CRM if they want it gone. |
| `crm_read_failed` | Try once more; if it still fails, tell the person Clue cannot read the CRM well enough to show the change right now. |
| `crm_nothing_to_change` | Tell the person the CRM already holds those values, so there is nothing to change. |
| `crm_action_failed` | Check the action's input schema against the CRM's message, fix the arguments, and propose again. |
| `crm_rate_limited` | Wait for the rest of your work in this turn, then try once more; if it still fails, say the CRM is busy. |
| `crm_unavailable` | Try once more later in the turn; if it still fails, tell the person the CRM is not answering right now. |
| `salesforce_api_disabled` | Explain that this Salesforce org has no API access (Professional Edition needs a paid add-on), so Clue cannot write to it. |
| `salesforce_api_share_exhausted` | Tell the person Clue has used its share of the org's API calls for today, and propose the changes again tomorrow. |
| `salesforce_limits_unavailable` | Try once more; if it still fails, tell the person Clue cannot check the org's API allowance right now, so it is not writing to Salesforce. |

**Afterwards.** The changes are recorded as one proposal. State "awaiting_permission" means the chat now shows the person a permission card; state "queued" means a standing permission covers every change and they are being sent. End your turn with one line on what is waiting: the chat continues by itself with the results once the changes are sent.

**Taught by.** crm-writing v1 sections 4 and 6, "One proposal per decision" and "After proposing".

**See also.** `.deepagent/skills/manual-gates-authority/v23/SKILL.md`, `.deepagent/skills/manual-humans-screens/v23/SKILL.md`.

## crm_write_log@1

**What it does.** Read what Clue changed (or tried to change) in the CRM, newest first: each change's record, field, the value before and after, its status and the CRM's message when it failed. By default the last 7 days; narrow by proposal_id (any age), record (its CRM id or part of its name), status or since_days. To undo a change, call propose_crm_changes with reverses_write_id set to its write_id: for a field update (kind 'field_update'), propose the same action with the before value; for adding someone to a list or campaign (kind 'list_membership'), propose the matching removal; for a removal, propose adding them back. Clue does not undo a created record (kinds 'create_contact', 'create_company'): tell the person to delete it in the CRM if they want it gone. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#crm_write_log

- Effect class: `read`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: none: reading the write log writes nothing.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `status`, `since_days`, `limit`.
- The human sees: "Review CRM changes".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `proposal_id` | `UUID or None` | `None` | none | One proposal's changes, however long ago (the week's window does not apply). |
| `record` | `Optional[Annotated[str, StringConstraints(strip_whitespace=True, to_upper=None, to_lower=None, strict=None, min_length=1, max_length=200, pattern=None, ascii_only=None)]]` | `None` | none | A record's CRM id, or part of its name. |
| `status` | `Optional[Literal['proposed', 'queued', 'sending', 'succeeded', 'failed', 'skipped']]` | `None` | none | — |
| `since_days` | `int` | `7` | ge=1, le=3650 | — |
| `limit` | `int` | `50` | ge=1, le=200 | — |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `writes` | `list[CrmLoggedWrite]` | — |

*CrmLoggedWrite*: One row.

| Field | Type | What it is |
| --- | --- | --- |
| `write_id` | `str` | — |
| `slug` | `str` | The write action and what it acts on, so an undo is one propose_crm_changes call. |
| `object` | `str` | — |
| `kind` | `str` | — |
| `when` | `datetime` | — |
| `record_label` | `str` | — |
| `record_ref` | `str or None` | — |
| `field` | `str or None` | — |
| `before` | `Any` | — |
| `after` | `Any` | — |
| `status` | `str` | — |
| `failure_kind` | `str or None` | — |
| `crm_message` | `str or None` | — |
| `reason` | `str` | — |
| `proposal_id` | `str` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `crm_not_configured` | Tell the person the CRM integration is not set up on this deployment, so there is no write log to read. |

**Afterwards.** Nothing changed. The rows are what Clue changed or tried to change in the CRM, newest first: each with its write_id, the value before and after, its status, and the CRM's message when it failed. To undo one, propose it again with reverses_write_id (crm-writing section 8).

**Taught by.** crm-writing v1 section 8, "The write log and undo".

**See also.** `.deepagent/skills/manual-tools/v23/SKILL.md`.

## manage_crm_grants@1

**What it does.** List or revoke the standing permissions ('Always allow') the person gave on CRM permission cards: action 'list' returns each one in plain words; action 'revoke' with its grant_id withdraws it, so those changes ask again. Permissions are given only on the card, never with this tool. Manual: .deepagent/skills/manual-tools/v23/SKILL.md#manage_crm_grants

- Effect class: `write`.
- Spends: no.
- Opens a human gate: no.
- Replay identity: crm_write_grant.revoked_at: a grant is revoked once; revoking it again (a replay) answers already_revoked and stamps nothing; a list writes nothing.
- Pins the call is bound to: `project`.
- Journal-safe input fields: `action`, `grant_id`.
- The human sees: "Manage CRM permissions".

**Inputs**

| Field | Type | Default | Bounds | What it is |
| --- | --- | --- | --- | --- |
| `action` | `Literal['list', 'revoke']` | required | none | — |
| `grant_id` | `UUID or None` | `None` | none | The grant to revoke (from a list). |
| `source_turn_ref` | `str` | required | strip_whitespace=True, min_length=1, max_length=1000 | Injected by the platform from this turn. Never author one. |

**Outputs**

| Field | Type | What it is |
| --- | --- | --- |
| `grants` | `list[CrmGrantView]` | The live standing permissions of the connected CRM (after a revoke, the ones left). |
| `revoked` | `CrmGrantView or None` | — |
| `already_revoked` | `bool` | The grant named in a revoke had been revoked before this call; nothing changed. |

*CrmGrantView*: One row.

| Field | Type | What it is |
| --- | --- | --- |
| `grant_id` | `str` | — |
| `phrase` | `str` | What the person reads, e.g. "Always allow setting “ICP tier” on companies — by Aryan, 22 Oct". |
| `scope_kind` | `str` | — |
| `kind` | `str or None` | — |
| `object` | `str or None` | — |
| `field` | `str or None` | — |
| `granted_by_user_id` | `str` | — |
| `granted_at` | `datetime` | — |

**Refusals**

| Code | Next move |
| --- | --- |
| `crm_not_configured` | Tell the person the CRM integration is not set up on this deployment, so there are no permissions to manage. |
| `crm_turn_not_found` | Do not retry. The turn reference is injected by the platform; report that this turn cannot be resolved. |
| `crm_not_connected` | Tell the person no CRM is connected, so there are no permissions to list or revoke. |
| `crm_grant_not_named` | List the permissions first, then revoke by the grant_id of the one the person named. |
| `crm_grant_not_found` | List the permissions again, and revoke by a grant_id from that list. |

**Afterwards.** `grants` lists the connected CRM's standing permissions ("Always allow") in plain words. After a revoke, `revoked` is the permission withdrawn, and those changes ask on a card again; `already_revoked: true` means it had been withdrawn before and nothing changed. Permissions are given only on the card, never with this tool.

**Taught by.** crm-writing v1 section 8, "The write log and undo".

**See also.** `.deepagent/skills/manual-gates-authority/v23/SKILL.md`.

## The framework file tools

Always installed beside the governed tools: `compact_conversation`, `edit_file`, `glob`, `grep`, `ls`, `read_file`, `write_file`, `write_todos`. They act on your virtual
workspace, never on a host. They are not governed: they write no receipt and no journal
row, and their errors are plain prefixed strings (`.deepagent/skills/manual-errors/v23/SKILL.md`).

| Tool | What it really does |
| --- | --- |
| `ls(path)` | A flat file walk, not a directory tree. `is_dir` is false on every entry; only the read-only mount roots are marked as directories, and only when you list the root itself. |
| `read_file(file_path, offset=0, limit=2000)` | `offset` and `limit` count LINES, not bytes. The default window is the first 2,000 lines; a longer file is silently cut at the window, so read on with a larger offset. |
| `write_file(file_path, content)` | Whole-file replace inside a writable prefix, with an allowed extension. The quota is checked before the write. |
| `edit_file(file_path, old_string, new_string)` | Compare-and-replace of exactly one occurrence. `replace_all=True` is refused outright. A source text that is absent or not unique is a conflict: copy the span again, never reword it. |
| `glob(pattern, path=None)` | `fnmatch` over a flat list, not a path glob: `*` crosses `/`, and `**` is only two stars. |
| `grep(pattern, path=None, glob=None)` | A plain substring test, not a regular expression, over every file the glob matched. Each matched file is read whole. |
| `write_todos(...)` | The framework's own scratch plan. It writes to graph state only: no file, no durable row, and the human never sees it. |

What you may read and write is the workspace policy in `.deepagent/skills/manual-limits/v23/SKILL.md`; the folders themselves are `.deepagent/skills/manual-workspace/v23/SKILL.md`.

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

Its refusals have their own budget, separate from the governed one (`.deepagent/skills/manual-limits/v23/SKILL.md`), and
the exact strings are in `.deepagent/skills/manual-errors/v23/SKILL.md`.
