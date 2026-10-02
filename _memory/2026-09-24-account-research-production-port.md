# Account discovery-first production port — 2026-09-24

- Founder approved porting the reviewed complementary-search account trials into production,
  then explicitly selected v4 as the default for new launches. Existing runs keep exact pins.
- Implementing immutable quality revision 12/account profile v12, prompt v10, dossier skill v3.
  Person v11-person and claim/narrative v6 stay unchanged. No paid live calls or worker changes.
- Trial behavior: complementary auto searches, relevant team/professional voice, workflow-first
  tool discovery, selective page expansion, source-linked pre-deep note, agent-authored deep
  assignment, full-source review and adaptive follow-ups, reasoned committee/person handoff.
- Production ordinary account searches/pages needed durable operation references to connect the
  existing full-result views. Reusing the person operation/drain path with unchanged account
  wire settings; no trial imports, direct provider bypass, new verification or presentation gate.
- Existing source grants are run/account-scoped. Instructions explicitly limit reuse to supplied
  material and available scoped findings; this port does not add automatic cross-run source grants.
- `.env`, `.env.example` and Settings default changed to v4 together. No running processes restarted.
- Existing unrelated working-tree edits preserved. Verification and closing status pending.
- Completed immutable resources, actual profile selection, durable account search/page receipts,
  and source-navigation/source-review wiring. Account Exa wire settings preserved; original search
  label retained. Existing person profile/specialists and historical pins verified unchanged.
- Focused offline checks passed: current/historical resources, default launch→v4 revision 12,
  actual native skill materialization, model-call journaling, finalization replay, scripted
  provider search→deep→full-source review→page flow, new-worker reads, erasure/revocation,
  both nomination routes with durable person briefs, and person/media/provider regressions.
- Scoped Ruff, formatting, mypy and all 28 import contracts passed. No full-repo make check or
  paid live acceptance. Test database clue_account_port_20260924 removed after verification.
- Development failures resolved: a test used a nonexistent resolved-profile prompt_ref attribute;
  corrected to profile.prompt. One initial pytest invocation named a nonexistent brief test file;
  reran the actual quality_nomination suite. Formatter resolved initial long test lines.
- Closing state: new launches default to v4/revision 12 when processes load this checkout/config.
  Running processes were not restarted; existing jobs remain pinned. Next is founder-reviewed
  live account acceptance. Prior-source reuse remains limited to actually available scoped inputs.
- Verification inventory: 260 distinct offline tests passed across focused batches.
