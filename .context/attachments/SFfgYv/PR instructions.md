The user likes the current state of the code.

The current branch is design-fleet-parallelism.
The target branch is origin/research-streaming.
The user requested a PR.

Follow these steps to create a PR:

- If you have any skills related to creating PRs, invoke them now. Instructions there should take precedence over these instructions.
- Run `git status` to check for uncommitted changes. If there are any, review them with `git diff` and commit them. Follow any instructions the user gave you about writing commit messages.
- If the branch has no upstream or has unpushed commits, push with `git push -u origin HEAD`. If the branch tracks a remote branch with a different name or on a different remote, push to that upstream instead.
- Use the `mcp__conductor__GetWorkspaceDiff` tool to review the PR diff
- Use `gh pr create --base research-streaming --title <title> --body <description>` to create a PR onto the target branch.

If any of these steps fail, ask the user for help.

## PR Title

The user has provided this PR title. Use it exactly as-is:
Design agent reads the target account and finds the seller's knowledge at will

## PR Description

The user has provided this PR description. Use it exactly as-is:
The design deepagent can now find anything it needs about the seller and the target account without changing what Head-of-ABM puts in the brief. The design role gains the three governed account reads (`read_project_accounts@1`, `read_account_research@2`, `read_claims@1`) through a new immutable profile `design@v2`, and a platform-composed `DesignPlatformReads` object (same loop-bridge injection as the scoped-preference resolver) hands chat-opened leg turns those reads as LangChain tools, journaled and priced exactly like Head-of-ABM's, with a read's refusal reaching the agent as its reason codes. The seller's pinned brand-knowledge documents (company, product catalog, per-product research, ICPs, personas) plus the project's confirmed product set land once per session in a read-only `workspace/seller/` folder that the prompt's gather step names alongside the brand card. The account-adaptation, brief-and-copy and tools skills teach the reads and the seller folder; the editor's own routes and the CLI are byte-identical. Also carried: the design note, the six-task plan, the memory closing entry, and the tracked `.context` session attachments.

