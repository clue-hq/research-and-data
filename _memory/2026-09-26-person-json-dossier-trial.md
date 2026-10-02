# Person saved-dossier JSON trial

- Founder requested testing the claim-ready JSON approach on an existing person
  investigation, and confirmed close reuse of the account dossier skill.
- Prepared nick-03 saved research as person-dossier-replay-20260926/nick-01 with 194
  reassembled evidence records, retained context/brief and the shared formation
  rules. New PERSON.md adds person-specific guidance; no acquisition tools.
- Running configured person Grok model with native Deep Agents, local audit and
  Langfuse. Historical inputs preserved; no fleet/person jobs or publication.
- Shared importer now accepts the bound contact scope and writes contact findings;
  original account entry point remains an alias. Person metadata is conservative
  retention metadata, not identity verification or outreach approval.
- Offline checks: 28 focused tests pass; four isolated Postgres tests pass, including
  person subject preservation/replay and account-retarget refusal. Ruff passes.
- Inspection mistakes: queried nonexistent job subject_kind column (actual
  subject_type); corrected read-only query. One pytest filename used singular
  claim instead of claims; corrected, then all selected tests passed.
- Completed: 79 findings in eight sections, 51 model calls, $3.249254 recorded cost,
  818.44s. Native compaction archived successfully; no acquisition calls.
- Isolated run-09 imported all 79 to the bound contact; repeat reused all IDs.
  Independent stored-export comparison passed every original value, metadata,
  source set, resolved relationship and contact/field scope. Original DB unchanged.
- Admission initially rejected the old trial media_result label. Transaction
  rolled back; adapter maps it to provider_record while retaining original kind
  and unchanged bodies. Retry succeeded. Independent verifier initially expected
  finding id at the wrong level; dossier_entry.id fixed the checker, no claim edits.
- Review: person-dossier-replay-20260926/nick-01/REVIEW.md. Public voice and personal
  projects retained, but an available recommendation excerpt was mislabelled as
  report-only; employer context, a scrape gap and repeated tool summary remain in
  findings; two location conflicts bundled. No semantic acceptance claimed.
- Derived Markdown heading corrected from Account to Person; canonical JSON and
  frozen receipt unchanged. Five affected tests passed after renderer change;
  focused Ruff/mypy/diff checks pass. No running trial processes remain. No
  production adoption, reconciliation or publication in this slice.
