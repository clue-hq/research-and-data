# Disconnect specialists from current research

- Founder explicitly requested disconnecting claim/narrative specialists while retaining their code. Scope is current revision 20 account/person research; historical pinned revisions keep their existing behavior. Person fleet-job delegation remains intact.
- `quality_research_wiring.py`: current profile registries register only ACCOUNT_RESEARCH. Research execution constructs specialist/delegation runtimes only when the selected profile declares delegation roles; current profiles declare none. No prompt, model, tool schema, or frozen resource changes.
- Tests assert current registries cannot resolve either specialist, historical registries remain valid, and native current account/person runs complete narrative storage and replay with specialist constructors forbidden.
- Verification: 11 focused offline tests plus 12 scripted database tests passed; Ruff lint/format and targeted mypy passed. Database tests used isolated local database `clue_specialist_disconnect_verify_20260927`, not the application database. Initial sandbox TCP attempt failed; approved local connection succeeded. An initial test-function formatting issue was corrected.
- No paid provider calls, worker restarts, pushes, or unrelated edits. Existing running workers must reload code before using this composition change.
