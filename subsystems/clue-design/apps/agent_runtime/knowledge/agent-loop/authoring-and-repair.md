# Agent Authoring And Repair Protocol

Status: supported now, recognized but not lowered, and future scaffold.

## Supported Now

The coordinator must run a controlled loop:

1. Load knowledge before authoring.
2. Ask for one coherent DSL block.
3. Compile the block.
4. Repair compile diagnostics before continuing.
5. Run preflight.
6. Repair preflight diagnostics before preview acceptance.
7. Export preview.
8. Validate preview bytes and metadata.
9. Ask the visual reviewer to inspect the rendered preview.
10. Pass reviewer feedback verbatim to the DSL author.
11. Stop only on acceptance, max iterations, or a deterministic failure.

All scene changes must flow through DSL compilation or checked core operations.
No Python-side direct scene mutation is allowed.

Preflight and visual diagnostics with explicit node/page/slot targets should
be treated as targeted repairs. Prefer checked structured operations for exact
node/page changes. If a DSL repair is used, it must not recreate an existing
page or reinsert existing node IDs. Duplicate page/node IDs are a repair
failure, not a successful revision.

Debug previews may be exported from scenes that still have preflight errors.
Those previews are for inspection only. They must show computed layout geometry
when the layout solver produced it, but they do not satisfy final acceptance.

## Recognized But Not Lowered

The runtime can recommend edit surfaces, but the mature DSL-vs-ops policy
should emerge from real trace evidence.

## Future Scaffold

Future agent-loop work should add:

- richer multi-agent planning
- exact visual target localization
- automatic gap triage
- user approval checkpoints
- API-persisted run traces
