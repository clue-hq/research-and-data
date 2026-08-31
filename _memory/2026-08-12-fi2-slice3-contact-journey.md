# FI-2 Slice 3 — live Contact journey

## Scope and decisions

- Closed `LF-CONTACT-001` and `LF-CONTACT-003` only.
- Left selection controls and the timer-only email lookup unchanged; both remain separately planned
  slices.
- Kept the HTTP-only Accounts/Contacts transport established by FI-2 Slice 1.

## Implementation

- Centralized the governed committee read in
  `platform/api/clue_api/frontend_read/committee.py`. Account detail, Contacts list and Contact
  detail now share the exact project membership, latest run/product scope, eligibility resolver and
  workspace display-policy decision.
- Preserved canonical merge resolution. A stale merged Contact id resolves to its surviving profile
  and returns `redirectedFrom`; an eligible member does not need a name, title, LinkedIn URL,
  signals or completed research to remain addressable.
- Added database-backed list/detail parity coverage for named, policy-withheld, unnamed/partial,
  merged and weak/unbound committee shapes. Every id emitted by Account detail or Contacts list is
  fetched through the real profile endpoint.
- Made avatars adjacent to visible Contact names decorative. Contacts-grid rows now expose
  `Contact <name>` while their nested links expose `Open <name> profile`; the same honest `Unnamed
  contact` fallback is shared.
- Recorded the resolved wire/accessibility invariant in the Accounts contract and closed the two
  defect-log rows locally.

## Acceptance evidence

- Frontend: 155 tests passed; ESLint, design-system build, `tsc --noEmit`, and the production
  webpack build passed.
- Backend: 112 frontend-read and FI-2 integration tests passed against the disposable local
  Postgres database; focused Ruff check and format check passed; `git diff --check` passed.
- Authenticated browser run used a durable Insight Health workspace in the disposable Slice-3
  database. The live Contacts table showed named, withheld-title and unnamed rows. Each linked URL
  opened and reloaded directly; the stale merged URL resolved to the survivor with a visible merge
  notice. Accessibility snapshots showed distinct concise row/link names and no runtime error.
- Browser/API logs confirmed 200 responses for all four direct profile shapes after enabling the
  existing chat/sidebar surface in the acceptance server.
- The final read-only SQL check found 3 accounts, 5 Contact identities including 1 merged record,
  and 11 Contact claims; no Contact claim was missing an evidence span or source key.

## Operational notes

- The first acceptance-server configuration intentionally disabled chat and exposed an unrelated
  sidebar 404/runtime overlay. Restarting the same API with its existing chat surface enabled made
  the final Contact acceptance run clean; no product code change was made for that setup issue.
- The full frontend test command needed the existing sandbox escalation because the TSX runner
  creates a local IPC socket. The backend database suite likewise needed local-Postgres access;
  without escalation the tests correctly reported the database as unreachable and skipped.
- A temporary seed script initially needed the repository root on `PYTHONPATH`, then needed its
  helper's workspace binding overridden before it could commit the acceptance data. The temporary
  script is outside the repository and is not part of the change.

## Residual boundary

- `LF-CONTACT-002` email enrichment and `LF-ACCOUNT-005` bulk selection remain open by explicit
  product decision. No fake enrichment success or selection behavior was added or removed here.
