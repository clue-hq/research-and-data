# Fresh Muse xhigh and GLM medium retries — 28 September 2026

User authorized fresh paid retries after the model comparison. Both launched at 11:39:37 UTC (17:09:37 IST); account executions began at 11:39:41 UTC.

| Run | Model | Research effort | Isolated database port | Worker PID |
|---|---|---|---|---|
| [Muse](muse-xhigh/manifest.json) | meta/muse-spark-1.3 | xhigh | 59391 | 93464 |
| [GLM](glm53-medium/manifest.json) | z-ai/glm-5.3 | medium | 59392 | 93463 |

Scope: Clue → Zafran; fixed Nick Fisher and Vari Kaur, identity confirmation required; fresh account and person investigations, JSON dossiers, imports, owned narratives, focused reconciliation. Three worker slots per environment. The common focused reconciler remains separately configured Muse; it is not attributed to GLM when comparing research-model quality.

Both runs use revision 24 and resource pin `19d896284ac0c8fa8427808c73117c7b680fde8b7d5f767ae79663ac78b6c790`, matching earlier trials. Retained seller/ICP/persona inputs and the shared delegation brief were reused; no previous target claims, contacts, evidence or research jobs were copied. Zero target baseline verified in both manifests. Skills have not been retuned for this retry.

Runtime launch commit: `b5f0239a1`, including `bde9c65f9` completion ownership and person-delegation preservation repairs. Each manifest and working-tree diff record the launch state. This is a fresh runtime-fix retry, not a byte-identical reproduction of the earlier backend. Historical outputs are untouched.

Provider preflights accepted both efforts, Langfuse installed, and the first actual account requests independently verified xhigh/medium. Research currently running; no final quality, duration or total cost result yet.

## Read-only inspection

Run `.venv/bin/python <run-root>/harness/pulse.py` from the repository root to refresh each run's `pulse.json`; `monitor.json` includes jobs, providers, pages and reconciliation. Worker logs and event files stay in each isolated run folder. The harness also includes review/export/timing/trace verification scripts for the final audit. Do not interrupt these experiments or reuse their private database configuration for another run.

Same logical run/job IDs can occur across isolated databases; always identify this test by its artifact root and database as well as the ID. Credentials are restricted to private harness/config files, excluded from this report.
