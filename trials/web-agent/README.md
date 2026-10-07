# Website deepagent trials

A place to iterate on the website agent's skills without touching the platform. Nothing here is
imported by the platform, and the platform's skills and prompts are not changed.

## What a trial run is

`run_trial.py` runs one real website-agent turn in this process:

- **Same agent:** the platform's design runtime (`lumen_agent`, via `lumen_api.run_web_agent_turn`),
  unchanged.
- **Same data:** the platform's governed research reads (account research, claims, seller files,
  `web_search`), composed the way the fleet worker composes them.
- **Same input:** replayed from a finished platform run's `design_agent_run` row: brief,
  account card, brand-kit pin and asset snapshot. The default is Syracuse, Run 3 of 2026-10-06.
- **Different skills:** `skill-set/` is rebuilt for every run. It is the platform's
  `knowledge_docs`, plus `overlay/`, minus the paths in `removed.txt`.
- **Different prompt lines:** only those in `prompt_overrides.py`, each an exact replacement of
  the platform's current text.

The agent's workspace (plan.md, previews, logs) goes to `workspace/`. Results are copied to
`runs/<label>/`: `response.json`, `plan.md`, `previews/`, `prompt.md` and
`skill-set-changes.txt`. No platform document is written; the page exists only in
`response.json`.

## Run

```bash
set -a; source .env; set +a
.venv/bin/python trials/web-agent/run_trial.py --label <name>
```

Options:
- `--source-run <run_id>`: replay a different platform run (for example a Conduit account).
- `--brief-file <path>`: replace that run's brief, for example to try the new brief format.
- `--with-example`: include the Syracuse worked example. Leave it out when the trial is Syracuse
  itself, or the agent can copy it.

A run spends real model and Exa money (about what the original run cost) and needs the lane's
design API up (`LUMEN_API_ORIGIN`) so previews can load images.

## Changing the skills

Edit files under `overlay/` (paths mirror `knowledge_docs/`), add a path to `removed.txt`, or edit
`prompt_overrides.py`. Platform skill files are picked up fresh on each run, so the trial always
tests the overlay against the platform's current skills.
