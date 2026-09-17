# Rebase onto research-streaming — 2026-09-12

Founder requested rebasing the current Semarang branch onto research-streaming.
Fetched both named origin branches. Local and remote research-streaming agreed at
6222e496190c71687a6f11636095c123961ddb84; the target contributed 49 commits beyond
merge base 7949a63e6d33250c0f1a1a9105d324430ab4fb5d.

Saved original brand-context-polish tip 8c4e580595359319eb797a30472e18d684649c85 as
codex/brand-context-polish-before-research-streaming-20260912. Replayed all 12 commits
without conflicts. New implementation tip: 23d73c181. git range-diff marks every
replayed patch equal; target ancestry and clean diff checks passed. Pre-existing
untracked screenshots/attachments/diagrams were preserved.

Validation: 657 selected frontend tests passed across Brand Context, Projects,
Chat shell, Onboarding, Accounts and project API routes. Design-system build, lint
and production build passed; only the two existing canvasOperations warnings remain.
Alembic has one head, c90aaea30a88. uv initially could not access its external cache;
used the existing .venv Python to inspect heads instead. No database migration or
server restart was performed; this session verifies Git integration, not a new live
research run. Other workspaces' branches and processes were untouched.

Remote update uses an explicit force-with-lease pinned to the original remote tip,
under the founder's standing commit-and-push instruction, so unexpected remote work
cannot be overwritten. This note is the sole additional post-rebase commit.
