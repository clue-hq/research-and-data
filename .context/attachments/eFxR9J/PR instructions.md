The user likes the current state of the code.

The current branch is explain-r2-close-plan-simply.
The target branch is origin/integration/design-improvement.
The user requested a PR.

Follow these steps to create a PR:

- If you have any skills related to creating PRs, invoke them now. Instructions there should take precedence over these instructions.
- Run `git status` to check for uncommitted changes. If there are any, review them with `git diff` and commit them. Follow any instructions the user gave you about writing commit messages.
- If the branch has no upstream or has unpushed commits, push with `git push -u origin HEAD`. If the branch tracks a remote branch with a different name or on a different remote, push to that upstream instead.
- Use the `mcp__conductor__GetWorkspaceDiff` tool to review the PR diff
- Use `gh pr create --base integration/design-improvement` to create a PR onto the target branch. Keep the title under 80 characters. Keep the description under five sentences, unless the user instructed you otherwise. Describe not just changes made in this session but ALL changes in the workspace diff.

If any of these steps fail, ask the user for help.
