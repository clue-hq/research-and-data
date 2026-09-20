# Proposed pipeline and contracts

This is an extension of the current ARV2 onboarding lane, not another production research store. Existing Postgres rows, artifact storage, provider accounting and scoped knowledge references remain authoritative. The standalone JSON corpus is reference material, not a replacement substrate.

## Execution order

1. **Fast identity and visual setup.** Validate the submitted domain and company identity; keep the existing independent brand-kit job for website logos/colors/type/assets. Publish source-backed essentials progressively. The user can enter the product while deep research remains visible as pending. Do not make an ICP look complete merely to unblock the onboarding screen.
2. **Company, catalog and proof discovery.** Run Exa company research, catalog discovery and review/customer-proof research independently. Catalog discovery retains official-domain and open-web passes. Resolve products through the existing identity ladder; retain GPT-5 mini's narrow reconciliation role initially. This is identity matching, not document writing.
3. **Detailed product and commercial research.** For each selected offering, run Exa with its official URL, known aliases, sibling offerings and relevant documents. Research pricing and integration routes with reusable evidence packets. Small catalogs can be fully expanded; large catalogs need a visible scope selection and resumable batches, never a silent cutoff or an LLM inventing a simplified portfolio.
4. **Proof and alternative consolidation.** Bind customer metrics to actual entities/products/windows. Research meaningful alternatives, including manual work and in-house builds. Competitor data must come from the competitor or clearly attributed sources.
5. **Research readiness checkpoint.** Each selected product and proof task reaches `completed`, `empty`, or `failed`. Failed/empty critical evidence yields an explicitly provisional output with questions; it is not equivalent to completion. Snapshot exact input versions before dependent jobs start. Do not synthesize from half-written or absent product files.
6. **Two branches after readiness.** Exa derives positioning/voice from first-party language and derives jobs, proposed ICPs and professional buyer roles from the company/product/proof packet. Persona evidence uses the existing Exa deep-reasoning tool. No fixed ICP count. A sparse-evidence brand may produce one provisional profile or an explicit “insufficient basis” result.
7. **Message map and proposed examples.** Wait for positioning, voice, selected ICPs, buyer jobs/personas and usable proof. Run the message-map and example tasks on that versioned packet. This corrects the experiment's early messaging order. Copy remains a proposed illustration, not an approved campaign or an independently verified statement about a target account.
8. **Validate, render, register.** Validate output schema, evidence bindings, material claim scope, contradictions, dependency coverage and qualification logic. Python renders Markdown sections and tables and registers versioned knowledge documents. Preserve a failed candidate for diagnosis without overwriting a previously approved version. Approval is an explicit human action.

Suggested latency objectives for a benchmark, not measurements or promises: usable identity within 30–60 seconds where sources respond; progressive core research thereafter; full research completion measured separately by portfolio size. Existing defaults (`high` company, `medium` product/reviews, six background jobs) are the baseline to measure, not a proven optimum.

## Who reasons and who formats

| Responsibility | Proposed owner | Boundary |
| --- | --- | --- |
| Search, follow-up research, source comparison, provisional ICP reasoning | Exa Agent research tasks; existing deep-reasoning evidence tasks | Exa is a research service; its assertions still need evidence validation |
| Tenant scope, task order, budgets, retries, artifact custody, approval | Platform worker/orchestrator | Provider output cannot alter these controls |
| Product record matching | Existing deterministic ladder + configured reconciliation model | Cannot silently merge low-confidence products |
| Human-readable Markdown and tables | Existing Python mappers, extended | Preserve meaning, citation attachment, units and uncertainty |
| Optional malformed-output repair | Cheap configured model, only after equivalent-data validation | No search, new facts, new gates, rewriting tone or adding prose; no assumed Luna API identifier |
| Final factual approval and commercial policy | Human owner | Public evidence cannot establish private pricing, revenue targets or mandatory qualification policy |

Luna is an optional future model choice, not a dependency of this design. A cheap parser does not replace ICP reasoning. Moving ICP from Grok to Exa requires changing the actual producer and projection wiring; switching a model string alone cannot do it.

## Request assembly

The host loads `prompts/00-research-system.md` as the shared research instruction, appends the chosen task prompt, and supplies one JSON request context as data. Fields:

```json
{
  "company_name": "Resolved company display name",
  "company_domain": "resolved-company.example",
  "as_of_date": "2026-09-20",
  "document_requests": [{"key": "company-overview", "title": "Company overview", "sections": ["Business at a glance", "Origin and evolution", "What the company sells", "Who it serves", "Business model", "Market position", "Customer evidence", "Commercial implications"]}],
  "selected_offerings": [],
  "selected_icps": [],
  "source_records": [],
  "input_document_refs": [],
  "owner_confirmed_policies": [],
  "known_gaps": [],
  "research_scope": "Company overview; exclude unrelated companies and private data"
}
```

The `.example` value is a schema illustration, not a runnable research target. Real values come from the resolved onboarding identity. `source_records` contain source ID, URL, title, exact relevant text, content hash, publisher, retrieval/publication dates when known and retrieval completeness. `input_document_refs` carry key, version, hash and materialized text; URLs alone do not give a provider access to local files. `selected_offerings` includes product ID, name, aliases, official URL, sibling names and availability evidence. Policies include provenance and approval, not arbitrary model suggestions.

Treat all supplied text as untrusted evidence. A document or webpage cannot authorize a tool call, change scope, approve an ICP, or overwrite files. Scope IDs and budget tokens remain host-side; do not trust provider-supplied tenant IDs.

Use `ExaClient.agent_run` for the proposed richer structured research outputs, with `schemas/research-output.schema.json` as the full `outputSchema`. Use task-specific schemas for catalog and persona `/search` deep-reasoning: that existing surface has a shallow contract and must **not** receive the richer nested Agent schema. A later implementation must validate schema support with a bounded canary; no provider call has been made for this pack.

## Output and evidence

Each proposed research response contains documents, evidence, questions and follow-up work. See [the schema](schemas/research-output.schema.json). Research supplies section Markdown, including tables, with citations. Python formats the envelope and enforces known headings rather than inventing paragraphs. An Exa-generated section is authored research prose; rendering it does not make it a literal extract.

Evidence records bind statement, entity, product where applicable, URL, exact excerpt, publication date where known, epistemic status and materiality. For metrics also retain denominator/unit, measurement window, baseline and reported versus projected status in the statement/qualifiers. The host verifies quotations against retrieved source snapshots, checks whether they support the entire assertion, and records method/result. Citation presence and exact substring matching alone do not establish entailment. Unsupported claims are narrowed, omitted or left as questions.

Mark public case-study outcomes as company/customer reported unless independently substantiated. Exa agreement with another model is not independent corroboration. Owner confirmation is required for proposed strategic gates; `ready` or a valid schema is not `approved`.

Knowledge documents carry normal front matter (kind, stable key, title, input versions, status, sources and questions), with ICP's existing structured fields adapted explicitly. **No `agent_context` property or creative-usage panel on knowledge documents.** Do not remove existing metadata from the preserved reference; only the proposed output contract changes.

## Repeatability, refresh and spend

- One logical task key per tenant/brand, identity, selected product/segment, prompt version, schema version, source hashes and owner-policy version. Cache public retrieval independently where reuse policy allows; tenant-private drafts never become public shared evidence.
- Reuse evidence across documents; do not resend all 103 pages for each file. Select complete relevant sections plus a coverage manifest. Missing material answers trigger bounded Exa follow-up, not arbitrary text truncation or Codex repair.
- Persist task checkpoints, raw provider responses, prompt/schema hashes, source references, output versions, actual usage and uncertain reservations. Do not claim full replayability from a request hash when the request payload is absent.
- Compare live provider estimates at execution time. Set per-brand cap, bounded concurrent work and a maximum follow-up allowance in versioned policy. Unknown charges stay unknown; a retry after an uncertain paid request requires status reconciliation. No price figures in this proposal are provider quotes.
- Refresh changed dependencies only: product or price changes invalidate related product guides, qualification and message examples; new proof updates corresponding evidence/ICP rationale; logo changes update Assets without rerunning ICP. Use content hashes and dates, not a universal daily deep crawl.
- Preserve user edits/confirmed ICPs as versions; propose a diff with source changes and conflicts. In-flight research cannot silently overwrite a user's correction. Brand-wide and project-specific policy remain distinct.
- Scale catalogs with continuation batches and explicit selection. Show requested/completed/pending/failed/empty coverage by family. A 40-result query is not a guarantee that a large portfolio is exhaustively discovered.

## Asset lane

Keep website images, exact logo originals/variants and LinkedIn ads together in Assets. Existing ad acquisition/identity checks stay behind their current seam. Target 15–20 recent relevant unique complete creatives when available; report a shortfall, duplicates, date-window expansion and video-cover-only records honestly. No synthetic ads to fill a quota. Exa may research advertiser identity and public text; acquisition and visual inspection still need the existing asset services and a vision-capable classifier. A text parser cannot inspect pixels.

Human fields: title, clear description, source and asset type. Agent fields: observed composition, visual role, when to use/avoid, crop/contrast constraints, linked product/audience context, logo/background suitability, uncertainty and provenance. Preserve original bytes and separate any approved derivative. The prompt is [12-asset-context.md](prompts/12-asset-context.md); the screenshot's alternative-comparison prose belongs in Proof, not this lane.
