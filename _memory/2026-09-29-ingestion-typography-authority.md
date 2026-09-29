# Ingestion typography authority — 2026-09-29

- Continued the active native-website goal after completing the requested deep
  trace. Generation remains on hold. No Project Instructions, branding seeding,
  standalone builder, runtime reload or live document/kit mutation.
- Root cause: normalizer retained an early incomplete CSS sample instead of a
  later complete rendered sample. Defaults and font-custody substitution became
  the kit's authored heading styles. Provenance and generated grammar mislabeled
  those derived values as observed, despite correct source measurements existing.
- Shared ingestion now ranks complete rendered samples first, excludes unresolved
  CSS variables from family selection and rejects nonpositive/nonfinite sizes.
  Numeric defaults/substitutions no longer receive measured provenance; partial
  evidence retains its source locator. Generated grammar makes measured source
  responsive styles authoritative over a derived fallback ramp.
- RED: five regression failures reproduced original behavior; two further tests
  reproduced contradictory guidance and missing partial-evidence provenance.
  GREEN: 76 focused ingestion/normalizer/unit/grammar checks passed; six DB cases
  excluded. Reviewed golden changes only affect provenance/confidence. Engine
  round-trip checks are included; no migration or engine source changes.
- One overly broad intermediate selection reached a DB-dependent fixture and
  failed at sandbox connection before a write. The final offline selection
  excludes all DB cases. Initial read-only replay queried nonexistent `id`;
  verified DAL uses `job_id`, corrected query, replay succeeded without writes.
- Exact saved ingestion replay yielded captured main/section heading values
  (56/400 and 48/400), with rendered provenance. This is producer-level evidence,
  not proof that the live agent follows the source-format contract.
- Open: the prior native run registered zero typography references and finalizes
  with `not_declared`; coverage must be required for source-based raw roles.
  Refreshing an existing approved kit is separate from fixing future ingestion.
  Keep the current live page unchanged until the diagnosed path is verified.
- Existing shared skill files already require source measurements/reference
  binding. This change fixes the generated brand guidance contradicting them.
  Other pending account-handoff edits and unrelated working-tree changes are
  excluded from this checkpoint. Local commit only; no push authorized.
- Closing verification: new regression module passes Ruff, producer files add
  no diagnostics beyond their existing baseline (4/10/15 respectively), and
  `git diff --check` passes. Golden review mechanically confirms no token-value
  changes in the existing website/PDF fixtures. Native quality remains unqualified.
