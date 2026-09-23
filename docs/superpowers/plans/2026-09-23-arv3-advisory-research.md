# Research quality: verification deferred, all findings visible

Founder ruling: September 23, 2026. This supersedes the blocking relationship and research-page
verification requirements of the September 22 research-quality spec/plan for new quality runs.
The immediate goal is useful, comprehensive source-based research and narrative quality.

## Behavior

- Accept acquired source data as reported. The LLM judges relevance, role, interpretation and
  uncertainty. Employment, location, organizational-scope and buying-remit proofs are not required.
- Committee selection records the chosen contact, persona, role and rationale. It does not create
  an employment assessment or require the old relationship-assessment contract. Source acceptance
  is not a claim that independent verification occurred.
- Agents record plain findings with a topic, free text/JSON, source references and optional notes.
  They do not fill field-catalog validation, quote-offset or semantic-assessment forms. Provider
  mappings still reuse their saved records. Catalog shape mismatches do not reject advisory writes.
- Narrative specialists receive complete findings, including qualified, unresolved, disputed and
  superseded observations, with their status/notes. The former narrative view removed the text of
  non-supported claims; that suppression is disabled for this revision.
- Narrative publication does not require confirmed membership, outreach eligibility, supported-only
  claims, primary-quote proof, a separate value-narrative claim, a fresh digest, or every recipe
  section. Seller relevance can be written directly on both account and person pages. Citations
  are encouraged; uncertainty is shown in plain language.
- All stored research findings appear in a visible section alongside the narrative. Quality labels
  cannot remove them. Existing restricted sections are exposed in the page; overview watch-outs
  are served as visible research notes. Custom narrative sections are retained. Updated or disputed
  citations add qualifications without deleting narrative text.
- Missing optional processing dispositions do not turn a published research result into a
  verification failure. Missing pages/provider failures remain honest coverage observations.

## Implementation and scope

The internal quality profile remains v4; its current immutable resource revision is six. Earlier
revisions remain available for replay. New quality launches pin revision six; child jobs retain
that revision and frontend reads recover it from the saved launch pin. The shared launch-profile
setting is unchanged. No historical run or stored research output is rewritten by this change.

The existing claim store, scoped evidence storage, source retention, fleet execution, model/provider
ledgers, tracing, and durable tool receipts remain the persistence/execution path. Workspace access,
actual erasure/revocation and identity keys continue to apply. No new environment flag or parallel
research pipeline is introduced. Source IDs prevent cross-workspace access; they are not a request
for independent relationship verification.

Research agents use `record_research_finding@1`, committee nomination revision two and page
publication revision two. The generated narrative remains the LLM's work; the complete findings
section is a loss-prevention view of stored research, not another model or a rewritten report.

## Verification

Offline tests exercise source report → finding → narrative input → page, uncertainty and withdrawal
remaining visible, phone/contact information remaining visible, source-based committee selection
without employment proofs, person-page/openers without relationship gates, exact launch-policy
selection on reads, and the real parent/specialist runtime with replay and trace/artifact receipts.
Historical strict-path regressions are retained. Paid-provider narrative quality still needs a new
live acceptance run; this development does not claim live acceptance.

Completed offline verification: **24 tests passed** across advisory findings, committee/person
handoff, claims/pages, specialist tools, real runtime/replay, relationship compatibility, driver
and provider modules. Ruff and diff checks passed; mypy passed 14 quality modules. All historical
and revision-six catalog hashes validate, and the three new governed profiles resolve. No paid
provider call was made. The frontend wire contract was validated using the actual display model.
