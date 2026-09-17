---
schema_version: "1"
kind: skill
name: manual-discovery
version: v2
summary: "Manual: discovery runs. Strict and relaxed passes, the gate verdicts and their guards, fit, dispositions, and what verified, shown and approved count."
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
| `target_count` | how many companies the human asked for |
| `strict_count` | how many the provider is asked for, which is larger than the target |
| `relaxed_enabled` | whether a widened second search may run at all |
| `relaxed_requested` | the human read a finished run's numbers and asked for the relaxed pass. That is their decision, not yours to assume |
| `criteria_gate_keys` | which of the ICP's hard gates became provider criteria. A key the confirmed document does not define refuses the launch before anything is bought |
| `asked`, `found_strict`, `found_relaxed`, `analyzed`, `recall_estimate` | the run's own account of its reach. A run that exhausts the pool says so with numbers rather than quietly returning fewer companies |

The run id is the digest of the request, so asking the same thing twice is one run, one search
and one bill. Run statuses are the same five words as research: `not_started`, `in_progress`,
`needs_review`, `completed`, `suspended`. See `.deepagent/skills/manual-accounts-research/v2/SKILL.md` for what each means.

## How a run works

1. The run is claimed by one worker.
2. The program is read from the exact ICP document this run was pinned to, checked against its
   digest, so a resumed run asks the first attempt's questions even if the project has since
   repinned.
3. The **strict pass** asks the provider for companies under the full criteria.
4. Each candidate is verified: first the company's own website, because everything downstream
   keys on the verified domain, then one question per hard gate.
5. The **relaxed pass** runs only if the run came up short and the run allows it, widening by
   dropping the criterion the strict pass showed was starving it.
6. The receipt records asked, found, analyzed, the recall estimate, the guard counts and the
   money.

A run that fails lands `needs_review` with a named reason, and the candidates already verified
are kept, because they were paid for. The wall clock is 1,800 seconds. A webset of about 25
companies has been observed to take roughly five minutes, and a five gate one about eight.

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
| `duplicate_of_existing` | the verified domain is already an account here |
| `not_chosen_before` | an earlier run showed this company and the human did not choose it |

There is deliberately **no `fail` disposition**. A candidate on the list is one the human is
being shown, and a failed gate is a reason to read the verdict, not a reason to hide the row.

`duplicate_of_existing` and `not_chosen_before` are stamped **before any gate is asked**, so
those companies cost one website answer and were never really examined.

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
candidate the human did not choose is unapproved, which is not the same as rejected, and a
later run remembers it as `not_chosen_before` and does not surface it again. Never tell a human
that the platform rejected a company; say it was not chosen.

## Two honest limits

- The ICP's `exclusions` are compiled and asked of nobody. A company that clears every hard
  gate but is plainly excluded by the profile can still arrive as a high fit candidate for a
  human to read.
- Before proposing another run, read the last one and say what it asked for, what it found and
  how many were approved. Starting a second run for the same target does not start a second
  run; the platform re-runs the existing one.
