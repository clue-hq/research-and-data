# Account research: port the reviewed discovery-first trials

Status: implemented locally; focused offline verification passed. Paid live acceptance remains
pending. Founder approved the production port and changing new-launch default to v4 on 24 September.

## Result

New platform research launches default to `catalog_version=v4`, resource revision 12. Account jobs
select account profile v12, system prompt v10 and account-dossier skill v3. Person jobs retain the
reviewed person profile v11-person and both person skills. Claim/narrative specialists remain v6.
The default is aligned in Settings, `.env.example` and local `.env`. Existing running processes
have not been restarted: they must reload configuration/code to use this selection. No deployment,
fleet launch, provider purchase or application database mutation was performed for this port.

Previously launched runs continue to resolve their original resource hashes. All earlier prompts,
skills, profiles, provider configurations and trial snapshots remain unchanged and loadable.

## Investigation behavior

1. Read the Head-of-ABM brief and relevant selected seller/product/ICP/persona references. Batch
   independent reads and reuse material already available. Project-selected variants still win.
2. Choose complementary ordinary Exa `type=auto` searches before the main deep assignment:
   operating model, relevant teams, public professional statements, hiring/workflows/systems,
   financing and organizational change. Adapt to the actual seller; no fixed query count or
   per-section checklist. Deep-request additional queries supplement these searches.
3. Follow discovered executives, leaders and practitioners for useful professional statements.
   Search systems through responsibilities and workflows before guessing familiar vendor names.
   Expand promising excerpts with targeted page reads. Avoid repetitive or unproductive searches.
4. Keep a concise, source-linked `/work/pre-deep-review.md` note, then author a self-contained
   eleven-area Exa assignment and complementary additional queries. Seller-fit thresholds and
   buying-role judgments remain with the account agent. Launch once the assignment is useful;
   do not exhaust all channels first. Synchronous runtime behavior is unchanged.
5. Review the dossier together with returned original results. Inspect source overviews, useful
   complete records, highlights, links and fresh fields at familiar URLs. Retain source-only
   details and prior professional-voice findings while expanding company breadth. Follow concrete
   unresolved questions, including relevant media, without crawling everything.
6. Report missing results as limits of the investigation, not proof of absence. Retain supplied
   contrary evidence with attribution. Preserve exact quotation wording; label paraphrases.
   No new date, relationship, verification, completeness or presentation gate is introduced.
7. After developing the account picture, select useful people using web discoveries and AI Ark
   SMART/profile matching. Aim for four or five if supported and within the actual committee cap;
   do not pad. Preserve source references and distinguish observed remit from buying hypotheses.
   Nominate through existing tools with an account-authored person-specific `research_brief`.
   Existing typed enrichment, profile reuse and work-email enrichment remain; paid phones do not.
8. Continue the existing claim/narrative delegation and durable finalization lifecycle. Source
   references and useful source-only discoveries accompany the handoff, not just the dossier.

The instructions are general. They contain no Zafran/Premier people, missing vendor answers or
benchmark discoveries. The existing fictional Clue→Acme teaching example remains clearly marked
as instructional material, excluded from actual requests.

## Exact governed instructions and pins

- `platform/agents/catalog/research-quality/prompts/quality-account-research/v10/SYSTEM.md`
- `platform/agents/catalog/research-quality/skills/account-dossier/v3/SKILL.md`
- `platform/agents/catalog/research-quality/profiles/quality-account-research/v12/profile.yaml`
- `platform/agents/catalog/research-quality/recipe-v12.json`
- `platform/agents/catalog/research-quality/launch-v4-r12.json`

Provider system prompt and request configuration remain the tested account-deep v1 resources:
`platform/agents/catalog/research-quality/provider-requests/account-deep/v1/`.
This port changes how the account agent investigates and authors the query; it does not replace
those reviewed provider settings. The native runtime materializes the new full skill and the
existing person-research-briefing skill, rather than relying on an isolated trial filesystem.

## Production handoff and retained seams

Revision-12 account ordinary searches/pages now use the same durable operation mechanism already
used by person investigation. Their complete wire requests identify `account_search`/`account_page`
operations. `ToolRuntime.operate`, ProviderCaller, the drain, ledger, raw artifacts and existing
trace/model journals remain the execution path. The original account search label is retained.

Search/page/deep acquisition receipts now link `source_navigation` and `source_review_path` for
these account jobs. Existing authorized source-review views serve paginated overviews, complete
result references and added/changed fields; `previous_capture` never implies the agent read it.
Unchanged account wire settings: ordinary searches request 1,500 text characters; page reads use
the agent's max_chars; deep research defaults to 40 results with highlights and one extra link.
These are retrieval bounds, not a guarantee of complete sources. No trial code is imported.

Media uses the existing discovery, candidate resolution, transcription, transcript-open/search
capabilities. This does not repair or certify every public YouTube retrieval route. Person tools,
nomination schemas, budgets, grants, asynchronous fleet lifecycle and narrative refresh are retained.

**Prior research boundary:** `/research/claims/0.json` exposes permitted context-scoped findings;
`/evidence/index/0.json` exposes original evidence authorized for the current run/account. Automatic
cross-run original-source grants are not implemented here. The skill tells the agent to reuse
only material actually supplied/available and disclose unavailable originals. It must not pretend
that all historical runs or independent evaluation folders are accessible.

## Verification and acceptance

Focused offline checks cover immutable/current/historical resource selection, default launch into
revision 12, full account skill materialization in the real governed Deep Agent, native model-call
journaling and finalization replay, ordinary auto search → deep call → fresh-field review → page
read, original-field pagination, worker reconstruction, committed-request reuse without repurchase,
ledger settlement, erasure/revocation, both nomination routes and durable person briefs/profile
reuse. Existing person and media checks run alongside these. Database tests use only the isolated
`clue_account_port_20260924` database and scripted transports/models, with rollback-based fixtures.

Verification is integration evidence, not proof of autonomous production research quality. The
next acceptance is a fresh v4 platform account run using normal Head-of-ABM delegation; review
actual preliminary queries, page choices, generated Exa query/additional queries, source reads,
media follow-through, committee reasoning/person briefs, report, duration and cost/trace records.
Compare with retained trial and account-only PoC outputs kept outside agent inputs. Claim mapping
and presentation quality remain separate evaluation dimensions.

Across focused batches, 260 distinct offline tests passed. Scoped Ruff lint/format, mypy for
the six changed production modules, and all 28 dependency
contracts passed. Full-repository `make check` was not run. The task-created test database was
removed after verification; existing database/fleet processes were left as found.
