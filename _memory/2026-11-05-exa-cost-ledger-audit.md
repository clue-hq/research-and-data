# Exa cost ledger audit against Exa's request logs (2026-11-05)

Compared `provider_call_ledger` (Exa rows, trial DB) with Exa's dashboard request logs, call by
call on request id, for 2026-11-03 00:00 UTC to about 2026-11-05 11:38 UTC. Search and contents only:
those logs did not return Agent runs, Websets or 402 refusals.

## Result
- All 1,488 ledger calls with HTTP 200 are in Exa's logs at the same cost: $8.809 on both sides.
- Exa logged $84.68 in the window. The ledger holds 10.4% of it, because hand research and the
  `shank-GTM` key never write to the ledger.
- By key: trial $8.809, other `default` key use $45.742, `shank-GTM` $30.131, no key $0.001. `clue-prod` none.

## The $50 top-up of 2026-11-04
Added between 11:37:49 UTC (last 402) and 11:52:30 UTC (first success). Last success on it was
2026-11-05 05:42:27 UTC; the next calls we made got 402 at 07:19 UTC. Logged spend in that window:
$48.906 = trial $3.325 + other `default` use $34.202 + `shank-GTM` $11.379.
The $34.202 was read as the Harvey hand research from its queries: $24.044 is law-firm worded and
$10.158 is unclear. Exa does not label sessions, so this split is an inference.

## Open
- Not reconciled: Websets per call (we calculate it; 30-day $1.93 ledger vs $1.98 dashboard), Agent
  ($5.70 ledger vs $27.47 dashboard over 30 days, some likely production), fixed fees ($27.08).
- Production ledger was not read; `clue-prod` was not compared.
- Old ledger rows from the Agent poll bug (2026-09-28, $57.50) are still inflated in local databases.
- A timed-out call records NULL cost, and retries record only the final attempt.
- Hand research on the `default` key has no cost record of its own.
- Raw per-request logs stayed in the browser; nothing from them was saved here.

---

# Crash recovery of a turn with a tool call open: findings (2026-11-05, same session)
Nothing changed yet. The no-progress guard (`d6b7579c0`, incident 2026-09-29, ~15 silent re-dispatches
a second holding a fleet task forever) did its job on recipe 40's Dwayne job; the gap is below it.
After a worker dies, `_recover` abandons the open interaction child, the drive loop sees it as ready,
the re-dispatch writes no event, and the guard fails the execution. This was first recorded as open in
`_memory/2026-10-22-agent-workspace-f3-spec.md` ("mid-tool-call turns are not resumed"). The re-dispatch
refusal is read from code, not yet reproduced in a test.
Agent then ran on: 9 model calls, $0.757, after the execution had failed. An AI Ark lookup had returned
8 s before the kill. Any fix keeps the guard, which only catches silent loops: a loop writing an event
each pass would pass it, so the fix also needs an attempt limit and its own test.
