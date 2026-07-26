# clue-agents

Provider-neutral contracts and policy for the Doc-A platform deepagent.

C6.0–C6.3 currently provide frozen agent contracts and ports, the isolated virtual workspace and
immutable resource materializer, strict folder-backed prompt/skill/profile catalogs, resolved
role/tool authority, progressive skill disclosure, a deterministic test model, durable turn and
receipt contracts, deterministic seven-layer context assembly, and body-free replay types.

Concrete provider, toolbelt, storage, and workspace-root adapters compose in `clue_api`; this
package does not import those implementations. The durable Postgres/artifact/history/replay/privacy
adapters compose in `clue_api`; agent construction, governed execution, and feature routing begin
in later C6 slices.

See `docs/specs/PC-C6-platform-deepagent-and-skills.md` and
`docs/architecture/clue-hq-platform-agent-runtime.md`.
