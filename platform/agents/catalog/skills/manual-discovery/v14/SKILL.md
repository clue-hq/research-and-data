---
schema_version: "1"
kind: skill
name: manual-discovery
version: v14
summary: "Manual: discovery runs. The three searches, the gate verdicts and their guards, fit, dispositions, and what verified, shown and approved count."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
<!-- sources: research/2026-09-13-head-of-abm-manual/C-domain-model.md §5 (the run, the candidate, verdicts_json, the run read, approval); research/2026-09-13-head-of-abm-manual/E-runtime-and-sibling-agents.md §3.3 (launch, what it does, stop policy, what it produces, how to read it) -->
# Discovery: finding companies that match the confirmed profile

Discovery finds companies for a project whose ICP is confirmed and pinned. The confirmed ICP
document **is** the program: its `hard_gates` become the questions, and nothing about a gate is
written in code. A new ICP changes the questions and nothing else.

## What one run holds

| Term | Meaning |
| --- | --- |
| `target_count` | how many companies the human asked for. The first search asks the provider for exactly this many |
| `relaxed_enabled` | whether the relaxed search may run at all |
| `relaxed_requested` | in the run read: the run made the relaxed search. The name is older than its meaning |
| `criteria_gate_keys` | which of the ICP's hard gates became provider criteria. A key the confirmed document does not define refuses the launch before anything is bought |
| `asked` | how many companies the run's searches asked the provider for, all searches together |
| `found_strict`, `found_relaxed`, `analyzed`, `recall_estimate` | the run's own account of its reach. `recall_estimate` is the provider's estimate of how many companies match the ICP in total. A run that exhausts the pool says so with numbers rather than quietly returning fewer companies |

Each time a human asks for accounts is a new run. The same ask retried, for example a turn that
is replayed, is the same run, so it buys nothing twice. Run statuses are the same five words as
research: `not_started`, `in_progress`,
`needs_review`, `completed`, `suspended`. See `.deepagent/skills/manual-accounts-research/v14/SKILL.md` for what each means.

## How a run works

1. The run is claimed by one worker.
2. The program is read from the exact ICP document this run was pinned to, checked against its
   digest, so a resumed run asks the first attempt's questions even if the project has since
   repinned.
3. **Search 1** asks the provider for exactly `target_count` companies under the full criteria.
4. Each company it finds is verified: first the company's own website, because everything
   downstream keys on the verified domain, then one question per hard gate.
5. **Search 2** runs only when the run is short because the platform's own checks removed some
   companies: one this project already has, one an earlier discovery of this project found, or
   one whose website could not be confirmed. It asks the same criteria for the missing number.
   When the provider found fewer companies than search 1 asked for, the provider has run out,
   and search 2 is skipped.
6. **Search 3**, the relaxed search, runs only when the run is still short and the run allows
   it. It drops the criterion search 1 showed was starving it, and asks for what is still
   missing.
7. The receipt records asked, found, analyzed, the recall estimate, every search, the guard
   counts and the money.

Every search tells the provider to skip everything the searches before it found, including every
earlier discovery of this project. So no company is found, or paid for, twice. Each search asks
only for the shortfall, so a run never shows more companies than the human asked for.

A run that fails lands `needs_review` with a named reason, and the candidates already verified
are kept, because they were paid for. The wall clock is 1,800 seconds for each search. A search
for about 25 companies has been observed to take roughly five minutes, and a five gate one about
eight.

## Verdicts, and the guards over them

Each gate produces one verdict: `pass`, `fail` or `unclear`. **`fail` means a source
contradicted the test.** Finding nothing is `unclear`, never `fail`.

Three guards check the model's answer before it counts: the quoted sentence must actually
appear on the cited page; the page carrying the quote must be on the company's own domain or
name the company; and when a gate states a time window, the date arithmetic is done in code,
not by the model. A guard that overturns an answer makes it `unclear`, never `fail`, because a
gate nobody could evidence is an open question for the human, not a rejection. The guard values
you may see are `ok`, `quote_not_on_page`, `wrong_company`, `outside_window`, `no_source` and
`malformed`.

## Fit

`fit` is `passes / gates`, with an `unclear` counted as half a pass. A null fit means the
company was never scored, and it sorts after every scored candidate, because an unscored
company is unknown, not bad. Say what a fit number is made of when you quote one: 0.5 can mean
half the gates passed or every gate was unclear.

## Dispositions: what a candidate is

| Disposition | Meaning |
| --- | --- |
| `pending` | nothing has verified it yet |
| `pass` | every gate passed |
| `partial` | at least one gate failed |
| `unclear` | no gate failed and not all passed |
| `duplicate_of_existing` | the verified domain is already one of this project's accounts |
| `found_before` | an earlier discovery run of this project already found this company |

There is deliberately **no `fail` disposition**. A candidate on the list is one the human is
being shown, and a failed gate is a reason to read the verdict, not a reason to hide the row.

`duplicate_of_existing` and `found_before` are stamped **before any gate is asked**, so those
companies cost one website answer and were never really examined.

A company that is an account of another project, and not of this one, is not skipped. It is
checked against this project's ICP like any other company, and added to this project.

## The three tallies, and what each counts

- **verified** means at least one gate verdict exists, which is to say the company was
  actually judged. It does not mean "not pending": the two pre gate dispositions above are not
  verified, and counting them as such once had the platform reporting it had checked companies
  it had skipped.
- **shown** means the disposition is `pass`, `partial` or `unclear`, the three that mean a human
  was shown this company.
- **approved** means a human recorded the approval decision on it.

The run read serves the project's latest run or one by id, with those tallies and up to 50
candidates, each carrying name, domain, pass (`strict` or `relaxed`), disposition, decision and
fit. Candidates come back shown first, then by best fit, then by name. `status.md` carries the
same five tallies, but frozen for your turn; the read is live.

## Approval, and why nothing is ever rejected

A verified candidate becomes a member of the project the moment it is verified, in the same
transaction as its verdicts. What the human does on the accounts table is record the approval
decision on the candidate. Older wording described adding the account to the project as the
approval itself; the membership now happens earlier, and the decision is the part the human
still makes.

`approved` is the only decision the store can hold. **Rejection is unrepresentable.** A
candidate the human did not choose is unapproved, which is not the same as rejected. A later
discovery of this project skips every company an earlier one found, as `found_before`, whether
or not the human chose it. Never tell a human that the platform rejected a company; say it was
not chosen.

## Two honest limits

- The ICP's `exclusions` are compiled and asked of nobody. A company that clears every hard
  gate but is plainly excluded by the profile can still arrive as a high fit candidate for a
  human to read.
- Before proposing another run, read the last one and say what it asked for, what it found and
  what it showed. When the human wants more, each new ask is a new discovery, and it skips every
  company this project's earlier discoveries found.
