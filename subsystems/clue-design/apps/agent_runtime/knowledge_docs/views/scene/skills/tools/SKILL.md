---
name: tools
description: Use when choosing an available tool for a scene design step or recovering from a tool refusal.
---

# Scene tools

Use only tools registered for the current agent. Use inspect/view for evidence,
validate_creative_direction for the shared direction, checked compile/asset tools
for construction, preflight_design and render_preview for current artifacts, and
finalize_run only after the required review. Delegate only when the configured
runtime exposes and calls for delegation.

## Platform reads

`read_project_accounts`, `read_account_research` and `read_claims` answer from the platform's
research for this project: the accounts, one account's written overview or its claims, and a
narrowed claims question for an account or a contact. They return JSON; a governed refusal
returns `{"error": "refused", "reasons": [...]}` and any other failure `{"error": "<code>"}`,
to design around. They are present on a chat-opened design session and absent in the editor's
own agent box and the CLI. The account-adaptation skill says when and how to use them.
`seller/index.md` lists the brand's knowledge documents written into this workspace.

## Web search

`web_search` searches the open web and answers JSON like the reads: a short written answer,
then up to ten results with title, URL, date and highlighted passages, with the text to read in
`rendered`. It is present on a chat-opened design session and absent in the editor's own agent
box and the CLI. It comes after the account reads and after the seller's files in `seller/`,
every time: use it only when those have nothing on the brief's subject, or what they have is
vague, such as an event the seller is running, a workshop, or a topic outside its products. What it
returns is text you may design from now; it is not a claim, it is not verified, and it is never
presented as research the platform did. A refusal (`{"error": "refused", "reasons": [...]}`)
means no search happened; design from what you have and say what was missing.

`render_preview` returns the complete current native-copy inventory with scene
and preview bindings. Refresh it through `inspect(view="copy_review")` when
needed; use those page/node IDs and full words for `direction_review`, following
`knowledge/scene/review.md`. This is an observation of native text, not a factual
support or readability verdict. Keep the registered current review and omit
`critique_json` from `finalize_run` to reuse it.

All registered skills and shared resources remain available on demand during
composition, review and later revision. Read files via their
delivered virtual paths. Do not call an imagined knowledge
loader, export API or image-edit command. Tool descriptions define argument
schemas; `knowledge/lumen-dsl/*` defines DSL syntax. Asset/reference mechanics
live in `knowledge/scene/components.md` and `knowledge/scene/references.md`.
Run dependent writes, preflight and rendering sequentially; independent reads
may batch. A refusal is evidence to repair the named issue, never permission to
bypass the seam or report success.
