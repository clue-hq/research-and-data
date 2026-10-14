---
schema_version: "1"
kind: skill
name: manual-discovery
version: v17
summary: "Manual: discovery runs. The search you write, how a run searches and excludes, the gate verdicts and their guards, fit, dispositions and the tallies."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
# Discovery: finding companies for this project

You run discovery with `launch_arv2_discovery`, and you write its search: what kind of company to
find, what every company must satisfy, and the checks run on every company found. Section 7b of
the stage0-interview skill says how to write them. The project's documents are your notes; nothing
reads text out of them for you.

## What one run holds

| Term | Meaning |
| --- | --- |
| `target_count` | how many companies the human asked for |
| `source` | `websets` or `search`, as you chose |
| `end_reason` | why the run ended: `filled`, `dry`, `round_cap`, `wall_clock`, `stopped` or `failed` |
| `summary` | what the run found, what it excluded and why, and what it cost — the same summary your end-of-run turn starts with |

Each time a human asks for accounts is a new run. The same ask retried is the same run, so it
buys nothing twice. Only one run is active in a project at a time.

## How a run works

1. The first search asks for `target_count` companies with your query and criteria, skipping every
   company this project already has or found before.
2. Each company found is checked: first its own website, then one question per gate.
3. A company is **excluded** when a `must` gate fails or a `must_not` gate passes. It does not join
   the project and does not count toward `target_count`. An unclear answer never excludes.
4. While the run has fewer companies than asked, it searches again with the **same** search —
   never a looser one — skipping everything seen so far, up to three more times.
5. It ends when it has enough companies, when a search finds nothing new, after the last allowed
   search, at the time limit, or when the human stops it. You then get a turn that starts with the
   summary.

## Verdicts, and the guards over them

Each gate produces one verdict: `pass`, `fail` or `unclear`. `fail` means a source contradicted the
rule; finding nothing is `unclear`. Three guards check the answer before it counts: the quoted
sentence must appear on the cited page; the page must be on the company's own domain or name the
company; and a time window is checked in code. A guard that overturns an answer makes it `unclear`.
The guard values you may see are `ok`, `quote_not_on_page`, `wrong_company`, `outside_window`,
`no_source` and `malformed`.

## Fit and dispositions

`fit` is over the `must` and `prefer` gates: a pass counts 1, an unclear counts one half.

| Disposition | Meaning |
| --- | --- |
| `pending` | nothing has verified it yet |
| `pass` | every scored gate passed |
| `partial` | a `prefer` gate failed |
| `unclear` | nothing failed and not everything passed |
| `excluded` | a `must` failed or a `must_not` passed; kept on the run only |
| `duplicate_of_existing` | already one of this project's accounts |
| `found_before` | an earlier discovery of this project found it |

Every candidate also names the search that found it: `strict` for every round of a run of the search you write; `relaxed` appears only on runs from before 2026-09-30, when the platform loosened a criterion by itself.

## The tallies

- **verified**: at least one gate verdict exists.
- **shown**: `pass`, `partial` or `unclear` — the companies added to the project.
- **excluded**: kept on the run with the gate that excluded them.
- **approved**: a human recorded the approval decision.

`approved` is the only decision the store holds; a company the human did not choose is not chosen,
never rejected.
