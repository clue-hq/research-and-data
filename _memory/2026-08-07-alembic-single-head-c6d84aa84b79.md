# 2026-08-07 — Alembic state: ONE head, `c6d84aa84b79` (correction of a false 4-head report)

**Authoritative fact (founder-confirmed + verified with `uv run alembic heads`):** the alembic
tree has **exactly one head, `c6d84aa84b79`** (`committee_selection_claims_ride_the_…`,
down_revision `0070930672a4`). It is identical on this branch and `origin/main`. **All new
migrations — including every Part-II `design_*` migration — chain off `c6d84aa84b79`** (the
first design migration sets `down_revision = "c6d84aa84b79"`). No `alembic merge` is needed.

**The error to not repeat:** an inventory pass reported *four* heads by counting the three
historical Phase-C branch tips (`2211464d398f` C1, `316c84a7a3a4` C2, `5ab2d13ca389` C3 — all
fanning out from `b366c985ca12`) plus the M8D-lane tip. Those Phase-C tips were **already
joined** by the merge revision **`fc1f3d22a167_merge_phase_c1_c2_c3.py`**
(`down_revision = ("2211464d398f", "316c84a7a3a4", "5ab2d13ca389")`), which C4
(`1b71451d48cd`) chains off, continuing C5 → C6 → C7 → M8B/M8C/M8D → `0070930672a4` →
`c6d84aa84b79`. Historical branchpoints stay visible in the revision graph forever; they are
**not** active heads.

**Rule:** never assess heads by eyeballing `down_revision` fan-outs in `alembic/versions/` —
run `uv run alembic heads` (script-level, needs no DB) and trust only that. The `make db-smoke`
single-head gate remains the enforcement.
