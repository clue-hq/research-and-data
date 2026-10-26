# Design agent context: the seller and the target account, at will

**Status:** design note for founder review (2026-09-19). No plan, no code.
**Depends on:** design session continuity (`2026-09-18-design-session-continuity-design.md`, shipped on `design/account-binding`) — the session workspace this note writes into, and the exit judge v2 that hands a message about another artifact back to Head-of-ABM.

## 1. The ruling this note implements

Founder, 2026-09-19:

1. **The brief stays the primary channel.** Head-of-ABM keeps writing the ask, the channel, the products with their claims, the audience or persona group, the target account and its hook for a 1:1, and the strategy and messaging for the creative. Nothing in this note replaces that.
2. **The target account is reached by tools, not files.** The design agent must never be unable to find something about the target account when it wants it. It reads the account's research the way Head-of-ABM does, and the account-adaptation skill teaches it how.
3. **Scope is the project, not a tag.** Whether the user typed `@Premier` or just "Premier Gastroenterology", the brief names the account in words and the design agent finds it among the project's accounts. No account ids are passed, no scoping contract is added to Head-of-ABM's tools. Do not over-engineer this; the agents are intelligent.
4. **The seller's knowledge is accessible as files in the session workspace**, listed the way the brand card is listed today. Reading them is the agent's call. The prompt never labels them optional.
5. **Contact-level personal claims reach the design agent only through the tools**, under the use-class governance that already exists. They are never written into a file.
6. **Multiple accounts on one leg: deferred.** Nothing here blocks it, and nothing here decides it.
7. The same machinery serves every scale. A 1:1 creative reads the account. A 1:few or a generic creative never calls the account reads because the brief names no account, and works from the brief and the seller files. There is no mode switch.

## 2. What is true today (why this note exists)

Verified on the Premier Gastroenterology run of 2026-09-18 (session `dsess_7bd05469…`):

- The design agent receives the target account and the seller's products **only as words Head-of-ABM chose to type into the brief**. In that run the brief carried the account name and domain, the three products with one line each, and one quoted claim with its source. That was all the account research the ad could draw on.
- The bundle's `claim_refs` carry ids and governance stamps, never values. The design agent has no tool that can open them. Its own account-adaptation skill says "bare claim IDs without accessible values/evidence cannot support copy", so today those refs are a dead end.
- The seller reaches the agent as the brand kit only: `brand_card.json` (colours, type, logos, tone words, kit images), `brand_colors.json`, `source_assets.json`. The kit knows what Insight Health looks like, not what it sells or to whom.
- A target-account card (name, domain, logo) is frozen into the envelope only for web pages bound to an account. A scene ad has no account context beyond the brief.
- Head-of-ABM has three governed reads the design role does not: `read_project_accounts@1`, `read_account_research@2` (the paged contract; `@1` is frozen for replay and granted to nobody), `read_claims@1` (`platform/api/clue_api/arv2/read_tools.py`), and its Stage-0 skill teaches their use (overview first; `overview_not_written` is not a failure; page to `next_offset` before counting; narrow by `field_prefix`; a spilled receipt is read from the file it names).

## 3. Target model

### 3.1 The brief (unchanged)

Head-of-ABM's brief is the intent and the framing. No new fields on `open_design_leg`; `brief` stays free text. The brief's own line "Account: Premier Gastroenterology (pgalr.com)" is what the design agent starts from when it reads more.

### 3.2 Three governed reads for the design role

`read_project_accounts@1`, `read_account_research@2` and `read_claims@1` are granted to `AgentRole.DESIGN` in the registry (`agent_registry_wiring.py`) and the design profile catalog. Same tools, same contracts, same receipts and journal, same idempotency. Their authority is what it is for Head-of-ABM: workspace- and project-scoped through the turn's identity. No per-account scoping is added.

**Contact claims.** `read_claims@1` already answers for a contact entity under the use-class gate. That gate is the whole of the personal-data rule for this note; nothing is added or relaxed.

**How the design runtime reaches them.** The design runtime never reads the platform database and imports no research internals (the seam rule). It runs the trio synchronously on a worker thread while the platform owns the event loop and the connection pool. The established bridge for exactly this is `clue_api.design_memory_runtime` (the scoped-preference resolver): the platform composes a callable at its composition root, hands it to the design turn host, and the design side runs it through `asyncio.run_coroutine_threadsafe` onto the platform loop with a bounded wait. This note adds one more injected capability of that shape:

- Platform side (`design_fleet.py`, beside `preference_resolver_factory` and `spend_drain`): a `research_reader_factory(envelope) -> ResearchReader | None` that returns three closures, one per read, each invoking the governed tool through the platform's tool invoker under the turn's identity and returning the tool's own output shape as JSON. Absent on the design API's own routes and on the CLI, exactly like the preference resolver.
- Design side (`lumen_agent`): three LangChain tools, `read_project_accounts`, `read_account_research`, `read_claims`, wrapping the closures, added to the solo agent's tool list (and the orchestrator's on the trio path) only when a reader was injected. Their descriptions are the platform tools' own descriptions. Every call is journaled by the platform tool, so the cost and the receipt land where Head-of-ABM's do.

### 3.3 The seller as files in the session workspace

At leg open, the platform renders two files into the session workspace beside `brand_card.json`, from the same compiled cards Head-of-ABM's context is built from:

- `workspace/seller/company.md` — the Client Knowledge Card v2 (`compile_client_knowledge_card_v2`): what the company is, its positioning, known fields, open gaps stated as gaps, the product catalog index. Plus the brand knowledge documents the seller approved, as the brand library already lists them.
- `workspace/seller/products.md` — the Product Knowledge Card (`compile_product_knowledge_card`) for each product confirmed on the project, at the project's pinned product selection version: what it does, for whom, proof points with their sources, open gaps.
- Optionally, when the project has pinned an ICP: `workspace/seller/audience.md` — the project's pinned ICP document and its personas, as the project pins them.

The versions rendered are recorded in the delegation bundle (Client-KB version, product selection version, ICP version), the same discipline as the production context receipts, so a replay reads the same facts. The files are regenerated at every leg open on that session's document, never edited in place by the agent (the backend marks `seller/` read-only for the agent, like `knowledge_docs/`).

**What the prompt says.** The solo prompt's gather step lists `brand_card.json, state.json` today. It gains `seller/` in the same breath, as a thing that is in the workspace. Nothing says "optional", nothing says "required".

### 3.4 The skills

Design-runtime skills, under `knowledge_docs/views/scene/skills/`:

- **account-adaptation** gains a short section, "Reading the account", written in the plain style of Head-of-ABM's Stage-0 skill: find the account named in the brief with `read_project_accounts` (query by name or domain; page if needed); read `read_account_research` with `section: "overview"` first, and `section: "claims"` when the overview is not written or a specific fact is needed; narrow with `field_prefix` from the families the answer lists; page to `next_offset` before stating a count; bind copy to the claim ids the reads return through `evidence_refs`; say when a field is empty rather than inventing. The sentence "bare claim IDs without accessible values/evidence cannot support copy" stays, and now has a remedy beside it: open them.
- **scene-brief-copy** gains one line in its gather: the seller files exist and the account reads exist for a named target company.
- The `tools` skill (the function surface) lists the three reads with their return shapes.
- No new skill. No mode-specific guidance.

Skill text is founder-reviewed before it lands (standing rule).

### 3.5 What does not change

Head-of-ABM's tools and brief; the exit judge; the brand kit as the visual truth; the creative-direction evidence discipline; the account card for web pages; erasure (the seller files live in the session folder and go with it; account facts are never written to disk by this note, so a DSAR at the store is complete).

## 4. Consequences for cost and behaviour

- A 1:1 turn that reads the account spends one to three tool calls it did not spend before; each is a database read, not a model call, and each is journaled and priced like Head-of-ABM's.
- A generic or 1:few turn spends nothing new.
- The seller files add a few kilobytes to the workspace; they enter the model's context only when read.

## 5. Open points for the plan

- Whether `seller/audience.md` ships in the first cut or waits for the personas discussion.
- The exact markdown rendering of the two cards (they are JSON models today; Head-of-ABM reads them as cards inside its context bundle, not as files).
- Whether the read tools' spilled-receipt path (large results written to a file the receipt names) needs the design backend to admit that path; if it does, it is one more admitted root, like the conversation history.

## 6. Acceptance (live, spends money)

1. A 1:1 ad for an account named in words, no tag: the design turn's trace shows `read_project_accounts` resolving the name and `read_account_research` returning the overview or claims; the creative direction binds at least one line of copy to a claim id from that read; the receipts show the reads journaled under the design turn.
2. A generic creative on the same project: no account read is made; the seller files exist in the session workspace; the trace shows whether they were read, and nothing in the prompt told the agent either way.
3. `read_claims` for a contact of the target account answers under the use-class gate exactly as it does for Head-of-ABM, and nothing about that contact appears in any file under the session folder.
