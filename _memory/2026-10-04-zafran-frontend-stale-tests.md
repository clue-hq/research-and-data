# 2026-10-04 — Five failing Zafran account-research frontend tests: stale since 296922df1

Branch `fix/zafran-frontend-tests` (from origin/research-streaming 1ad82b6be).

Cause: commit 296922df1 (2026-09-27, "Add Miscellaneous sections to account and contact research
pages", founder-approved) appended an honest EMPTY `miscellaneous` section to the Zafran Insights
(position 6 → now 7 sections) and every contact page (now last), updating the fixtures but not
three test files. Three tests counted items/sections; two read the contact page's LAST section
(`sections.at(-1)`) expecting `do-not-mention`.

Fix (tests only, nothing weakened): item counts gain the trailing 0 plus an explicit
`miscellaneous.empty === true` check; the two positional lookups find `do-not-mention` by key; the
Insights section count is 7. Result: the three Zafran files 27/27; full `npm test` 3261 pass, 0 fail.
Note: a parallel session was also started on this task from a chip — keep only one fix.
