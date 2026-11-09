# Exa Agent discovery trial

A standalone trial, outside the platform code: can one Exa Agent run (`POST /agent/runs`) find
target accounts for a seller, check the ICP's hard gates, and judge each company the way a seller
would — does it build its own tool in-house, does it already use a competitor, when might that
contract end, are its people unhappy with their current tool — with a source and an exact quote
behind every answer?

Nothing here touches the platform's discovery lane (`clue_api/arv2/discovery_*`). Once the trial
is good enough, the platform design and code come afterwards.

## The rule being tried (founder, 2026-11-10)

- The hard gates decide whether a company is on the list at all. The seller's competitors (a
  company whose main business is selling the same kind of product) are left out, as today.
- Every company that passes stays on the list as **top** or **caveat**. A caveat company fits the
  ICP but a signal makes it a weaker first target: it builds the tool in-house, or it uses a
  competitor and nothing suggests it wants to switch. It is kept, with a **remark** saying why, but
  it does not count toward the number asked for.
- A contract ending within 3 to 6 months, or clear unhappiness with the current tool, is an
  **opportunity** and keeps a company top.

## Files

| File | What it is |
| --- | --- |
| `system_prompt.md` | the instruction block, with `{placeholders}` filled from the seller's files |
| `output_schema.json` | one record per company: gates, the four findings, priority, remark |
| `build_context.py` | reads the confirmed ICP, product catalog and customers table into a context JSON |
| `run_trial.py` | fills the prompt, creates the run, polls it, saves `request.json`, `run.json`, `companies.json` |
| `check_quotes.py` | reopens every cited page and checks each quote is really on it |

Customer data (the context JSON and every run's output) stays outside the repository.

## Running it

```bash
set -a; source .env; set +a
uv run python trials/exa-agent-discovery/build_context.py --icp <icp.md> --catalog <catalog.md> \
    --customers <customers.md> --seller-name <Seller> --target-count 5 --out <dir>/context.json
uv run python trials/exa-agent-discovery/run_trial.py --context <dir>/context.json --effort high --out <dir>/run1
uv run python trials/exa-agent-discovery/check_quotes.py --run <dir>/run1
```

`run_trial.py` spends money: one Exa Agent run (fixed efforts $0.012 to $1.00; `auto` is metered
up to a $5 default cap). `check_quotes.py` makes one Exa `/contents` call per ten cited pages.
