# `web_search@1`: an open-web search for Head-of-ABM and the design agents

**Date:** 2026-09-22 · **Branch:** `research-streaming-v3` (lome lane) · **Status:** implemented on `feat/add-general-purpose-web-search-exa` (cut from `research-streaming-v3`, 2026-09-22; live proofs §4.5–4.6 owed, founder-triggered)

## 1. What this is, and what it is not

No agent on the platform can search the open web today. Head-of-ABM v60 grants no Exa tool; the
design role's only web instrument is the web lane's page fetch for a URL it already knows. The
platform's own research — discovery, account deep research, contact discovery, contact deep
research, onboarding — is deliberately target-locked, and that stays exactly as it is. This spec
adds one general-purpose search the agents reach for **last**, for the things the platform never
researched because nobody could predict them: a conference the seller is organising, a workshop,
a topic outside the seller's products, a fact the claim store and the seller's knowledge files do
not settle.

The founder's framing, kept verbatim in spirit: the agent first goes through the claim store for
anything about a target account or a contact, and through the seller's knowledge files for
anything about the seller; only when those come back **empty, vague or inconclusive** does the
web search come in, and the answer then says so plainly, so the human knows which facts came from
the platform's research and which from a search just now.

**Not this.** Not a replacement for any existing research tool. Not a claim writer: what the
search returns is text for the agent to read and use in the turn, never a claim, never verified,
never presented as research the platform did. Not MCP: the repo has no MCP-to-tool bridge, the
one hand-rolled MCP client is slated for deletion, and an MCP call would bypass the provider
ledger the in-house client already writes. Not `exa_py` called directly from a harness: same
ledger problem, and two copies of the call.

**The old rule.** The M8B roadmap (item 15) ruled "general-purpose Exa web search as an
unrestricted agent tool" out of scope, and M8C, M8D and M06A repeated it. The founder's ruling of
2026-09-22 is that the M-series is history, not governance: one dated line at M8B item 15 records
the supersession so nobody rediscovers the rule as live, the ARV2 master plan's Track O item
stops saying "Exa MCP", and the other three specs are left as they are.

## 2. Design

### 2.1 The tool

One governed tool, `web_search@1`, built like `exa_search_evidence@1` but over the client's
cheap `search` call with the founder's exact request shape:

```
POST /search
{ "query": …, "type": "deep-lite", "numResults": ≤10,
  "outputSchema": {"type": "text"}, "contents": {"highlights": true, "text": {…}} }
```

| Input | Type | Default | Bounds | On the wire |
| --- | --- | --- | --- | --- |
| `query` | str | required | 1–400 chars | `query` |
| `num_results` | int | 10 | 1–10 | `numResults` |
| `include_domains` | list[str] | none | ≤10 | `includeDomains`, only when passed |
| `exclude_domains` | list[str] | none | ≤10 | `excludeDomains`, only when passed |
| `start_published_date` | str (ISO date) | none | — | `startPublishedDate`, only when passed |
| `end_published_date` | str (ISO date) | none | — | `endPublishedDate`, only when passed |

Every optional key is absent from the body unless the caller passed it — the client's standing
rule ("only what the caller asked for goes on the wire"), so Exa's own defaults apply. Nothing
else is exposed: no `category`, no `livecrawl`, no text-length knob.

**Client changes.** `search_body` / `ExaClient.search` gain two optional keys they lack today,
`exclude_domains` → `excludeDomains` and `output_schema` → `outputSchema`, both absent unless
passed. `type` already passes through, so `deep-lite` needs nothing.

**Output**, one text block for the agent, not a claim:

1. the written answer Exa returns for a deep-lite search with a text output schema, when it
   returns one;
2. then one block per hit — title, URL, published date, and its highlight passages.

The typed output model carries the same content as fields (`answer: str | None`,
`results: list[{title, url, published_date, highlights}]`) so the journal and the receipt hold
structure; the rendered text is what the model reads.

**Classification.** Effect class `spend`; replay at-least-once (a retry may search again and
land a second ledger row — money spent twice is recorded twice, no domain row is written, nothing
converges); `operation_id_required`; journal-safe display fields `query`, `num_results`,
`include_domains`, `exclude_domains`, the two dates. **No skill-pin guard**: unlike the evidence
tool it is not tied to one procedure; the profile grant and the prompt do the governing.

**Spend.** Pre-spend estimate one cent; the ledger row carries what Exa metered
(`costDollars.total`) through the existing `exa_cost_reader`. No raw-body artifact is kept, so
there is no artifact-store refusal; the ledger row is the record. **No per-turn search budget**
(ruling 2026-09-08, no pre-emptive caps): the turn's existing round and call limits bound it.

**Refusals**, both before any spend:

| Code | When | Next move for the agent |
| --- | --- | --- |
| `exa_not_configured` | no `CLUE_EXA_API_KEY` in this process | tell the human web search is not available on this deployment; do not answer from memory instead |
| `query_empty` | blank query | write the question |

### 2.2 Grant and injection

**Head-of-ABM.** The tool is built once in `toolbelt_wiring` beside the sandbox and evidence
tools, from the same settings and secrets, so every process that composes the toolbelt has it.
`head-of-abm@v62` pins `web_search@1`; the registry grants it to `HEAD_OF_ABM`; the profile
comment names the reason (general use, last resort). The registry refuses a grant no profile
pins, so the bump and the grant land together.

**Design, both lanes.** The registry grant adds `DESIGN`; `design@v3` pins the tool. The
platform half is a fourth method on `DesignPlatformReads` (`web_search(...)`) that invokes the
governed tool through the same journaled `ToolInvoker` under the turn's identity, exactly as the
three account reads do — a fresh operation id per call, so two searches in one turn are never
collapsed into one receipt. The runtime half is a fourth entry in `make_platform_read_tools`;
both `harness.py` (scene) and `harness_web.py` (web) already call it, so one addition serves both
lanes and the design runtime imports nothing new. The tool answers a JSON string like its
siblings; a governed refusal comes back as `{"error": "refused", "reasons": [...]}` and any other
failure as `{"error": "<code>"}`, recorded, never raised. The module keeps its name; its
docstring gains a paragraph saying this is the first spend tool riding the reads seam.

**Identity and spend attribution.** The ledger row is stamped with the workspace only, on both
roles — `LedgerStamp(workspace_id=ctx.workspace_id)`, exactly as `exa_search_evidence@1` stamps —
because the journaled invoker's `ToolContext` carries no project id (corrected 2026-09-22 while
planning; the earlier draft of this paragraph said the design row would carry the leg's project id,
which the design lane's OWN drain does but this seam cannot). Project attribution lives in the
journal: on Head-of-ABM the call is bound to the execution's `project` pin like every sibling tool,
and on design the `tool_invocation` row sits under the leg's turn. The design role has no skill-pin
guard for spend tools, and this spec adds none.

### 2.3 The words the agents read

Plain language, clear rather than condensed (standing rule). Three places.

**Tool description** (identical on both roles):

> Search the open web and read back what it found: a short written answer, then up to ten
> results with title, URL, date and highlighted passages. Use this last. What the platform has
> already researched is in the claim store and in the seller's knowledge files, and those come
> first, every time. Reach for this only when you have looked there and what you need is not
> there, or is vague or inconclusive, or when the human has brought you something the platform
> never researched, like an event, a workshop or a topic outside the seller's products. What it
> returns is text for you to read and use now. It is not a claim, it is not verified, and it must
> not be presented as research the platform did.

**Head-of-ABM** — prompt v15 and manual v9, one new version each, no other behaviour change:

- `SYSTEM.md` gains one paragraph after the existing one about the seller's knowledge files. In
  order: a question about a target account or a contact goes to the claims first, through the
  reads. A question about the seller goes to the knowledge files first. Only when those come
  back empty, vague or inconclusive does the web search come in, and the answer then says so
  plainly, so the human knows which facts came from the platform's research and which from a
  search just now.
- `manual-tools` gains a `web_search@1` entry in the house shape: effect class `spend`, spends
  yes, opens no gate, replay identity the ledger row, the inputs table above, the outputs table,
  the two refusals with their next move, "Taught by" the new prompt paragraph. The chapter's
  title line moves to `head-of-abm@v62`. The manual index and its siblings move with it as the
  manual builder requires.

**Design, both lanes.** The scene tools skill gains a "Web search" paragraph under "Platform
reads": the tool exists on a chat-opened design session and is absent in the editor's own agent
box and the CLI; it answers JSON like its siblings; it comes after the reads and the seller's
files; it is for the brief's subject when the platform has nothing on it, such as an event page.
The web lane's prompt (`prompts.py`, at both platform-reads sentences) gets the same paragraph.

**No new skill** for either role. The ordering rule is a paragraph, not a procedure.

### 2.4 Record

- `docs/specs/M8B-exa-sumble-account-deep-integration-roadmap.md` item 15: one dated line,
  "Superseded 2026-09-22 by `docs/superpowers/specs/archive/2026-09-22-web-search-tool-design.md`;
  M8B's target-locked acquisition is untouched."
- `docs/specs/ARV2-MASTER-PLAN.md`, the Track O "Exa MCP search tool" item: one dated note that
  it landed as a direct governed tool (`web_search@1`), not MCP.
- No new env key or flag. `CLUE_EXA_API_KEY` already exists in `.env.example` and in this
  lane's `.env`.

## 3. Not in scope

- Any change to discovery, account or contact research, or onboarding — they keep their own
  target-locked tools and the agent is told to use those first.
- Page contents / reference-page fetching for the scene lane. Search returns highlights; a full
  page is a separate ask.
- A per-turn search budget, a skill-pin guard for design spend, a raw-body artifact.
- Rewriting the M8C / M8D / M06A out-of-scope bullets.

## 4. Acceptance

**Offline (every item a test) — all four DONE 2026-09-22:**

1. **DONE 2026-09-22.** `search_body`: `excludeDomains` and `outputSchema` present only when
   passed; `type` passes `deep-lite` through; highlights present when on; the four optional
   filters absent by default.
2. **DONE 2026-09-22.** The tool: both refusals fire before any spend; a canned Exa response
   renders to the agreed text and typed output; one ledger row per call carrying the provider's
   metered cost; the journal shows only the safe display fields.
3. **DONE 2026-09-22.** Grants: `head-of-abm@v62` and `design@v3` pin `web_search@1`, the
   registry grants both roles, and the existing catalog / registry / manual-drift gates
   (`tests/agents/test_catalog.py`, `tests/agents/test_manual_drift.py`,
   `tests/api/test_agent_registry_wiring.py`) stay green — they refuse a grant no profile pins
   and a manual that drifts from the profile's surface.
4. **DONE 2026-09-22.** Design: the fourth tool appears in the runtime's tool list
   (`agent_runtime/tests/test_platform_reads.py`); `DesignPlatformReads.web_search` reaches the
   invoker under the turn's identity with a fresh operation id
   (`tests/api/test_design_platform_reads_db.py`).

**Live, founder-triggered (spends real Exa cents):**

5. A Head-of-ABM turn on this lane about something the platform never researched (a conference)
   — the reply uses the search and says which facts came from it.
6. A design leg for an event page on the same subject — the design agent searches, the ledger
   row carries the leg's project id, the artifact reflects what it found.
