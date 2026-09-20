# Saved Conduit pilot: V2

The V2 source code, prompts, tests and result reports were already committed under `experiments/brand-context-agent-v1/` (the directory name is historical). This frozen V2 snapshot adds the saved outputs that the experiment's `runs/` ignore rule kept off GitHub. This delivery contains no V1 project or viewer.

| Version | Documents | Original assets | Source records | Original preview |
| --- | ---: | ---: | ---: | --- |
| V2 expanded rework | 25 | 56 | 103 | localhost:3046 |

V2 includes its ready-to-view website, original images/logos/ads and previews, structured documents, source evidence, candidate synthesis, revision/history records, research findings, review/disposition records, sales exercises and evaluation/accounting reports, organized Markdown knowledge files and brand pack. Original asset bytes and document text are preserved. Reused evidence retains its original lineage; that does not add a separate V1 project.

The source experiment and its running previews were not edited or restarted. These are supervised research drafts, not proof of an autonomous Exa pipeline or approved brand governance.

## Open after cloning or pulling

From the repository root, using Python 3 only; no API keys, model calls, database or build required:

```sh
python3 deliverables/brand-context-pilot/tools/serve.py --version v2 --port 3056
```

Open `http://127.0.0.1:3056/`. This port avoids the original 3046 viewer. Choose another unused port if needed. Serve only V2's `public/` directory; the helper deliberately does not expose private review records and provider receipts above it.

## What stays local

Credentials/environment files, local databases and the raw database-baseline export, process locks/logs, provider response/page caches, compiled Python caches and the downloaded provider model catalog. These are not omitted feature implementations. `snapshot-manifest.json` lists every copied path/hash and every excluded runtime path with its reason. Public extracted research sources and saved outputs are included; raw fetched HTML and request caches remain in the original local run.

Read the [Exa pipeline handoff](../../docs/brand-context-research-handoff-v1/README.md) for the proposed scalable replacement. Do not feed these supervised answers into a fresh-run quality evaluation.

## Offline verification

```sh
python3 deliverables/brand-context-pilot/tools/verify_snapshots.py
```

This verifies the V2 tree, viewer manifest, document/asset counts and asset references, and checks that no V1 delivery exists. When the original local run directory exists it also checks every copied byte against it. It never starts research or modifies snapshots.
