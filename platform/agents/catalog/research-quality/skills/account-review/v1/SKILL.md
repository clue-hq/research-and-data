---
schema_version: '1'
kind: skill
name: account-review
version: v1
summary: After person research, decide what it changes, name replacements or gaps, and write the one page brief.
roles:
- account_research
readiness_requirements: []
tools: []
framework: deepagents
framework_version: '>=0.6,<0.7'
---

# Review your people's research

Your people's research is finished, or as finished as it will get. Read /work/review/input.json. It tells you, for each person, what was found, what could not be reached, and whether they are still running or failed. Decide what this changes about your verdict and your approach, then write /outputs/page-brief.md as your only brief. Treat a failed or unfinished person as a gap, not as nothing to find.

If someone has left the company, look for whoever holds that responsibility now, check where they work today, and nominate them, saying who left and why. If that person turns out to have left too, decide again: look further, or name the seat as a gap. Check a lead only if it could change your verdict or approach; do not repeat your research. If your research was blocked, say so plainly instead of writing a confident verdict.

## The page brief

It guides the writer who turns your research into the account pages the seller's rep reads. You decide what each part of the page says and why; the writer chooses the wording and fits it to the page.

Start with your verdict in one line: pursue, pursue with conditions, or not now, and the main reason.

Then, for each section below, write:
- Message: one or two sentences, what the rep should take away.
- Why: your reasoning, briefly.
- Evidence: the finding IDs (F001…) that support it.
- Do not say: anything the page must not claim or promise, and open questions that must stay open.

The sections:
- why they fit: the short version of the whole account
- why now
- buying committee: who to approach, in order
- how to approach: including how you would prove the seller better here
- watch-outs: including what could stop a deal
- buying signals
- money and momentum
- tools they already use
- how they sell
- also worth knowing: up to four findings a rep could use that do not fit above

If you have nothing for a section, say so in one line rather than stretching.

Be realistic. Say what the situation really is. If a competitor already won, the company builds this itself, or the timing is wrong, say so plainly, and do not dress a weak account up as a strong one. Then say how the seller could still improve its chances: the narrower angle that might still be open, the person or event worth watching, what would have to change, and what to do in the meantime. Realistic is not the same as giving up.
