# Head-of-ABM research briefing, 2026-09-23

## Founder decision and rollback

- Founder rejected the runtime context compiler as overengineering. The Head of ABM should
  author one readable project/run assignment matching the two approved previews, reuse it
  across accounts, and give the researcher references to complete pinned documents.
- Reverted the entire `7e9b7e944` checkpoint with `4456b508c`. The revert's tree is identical
  to `579d85c85`; typed-provider boundaries and phone-removal checkpoints are preserved.
- The ignored `.artifacts/research-brief-previews-20260923/` files are historical output of
  the rejected compiler, not previews of the replacement skill or a live research result.

## Replacement

- Added `account-research-briefing@v1`: source review, brand/project ICP and persona pins,
  distinct selected products, concise synthesis, complete references and the approved
  examples. It teaches the existing `launch_arv2_account_research.directive_text` handoff.
- Head-of-ABM profile v63 adds that skill and Stage-0 v36's instruction to open it before
  launch. System prompt, tools, model, limits and manual grants remain as in v62. Existing
  resource versions remain immutable; current registry and composer selectors use v63.
- Only research execution addition: substitute `{{account_name}}` and `{{account_domain}}`
  once at job composition, using the job's identity. Works in quality and older account/person
  composition. Plain directives, arbitrary braces and the shared stored brief are preserved.
- No automatic Exa appendix, new context compiler, additional model, schema, database change,
  source retrieval, validation gate or presentation restriction was added.
- Complete pinned document views already exist in the quality runtime at
  `/research/context.json`. Local/default research catalog remains v2, whose older context
  supplies ICP/personas inline; this work does not switch it to the quality runtime. The
  skill explicitly distinguishes those capabilities rather than promising inaccessible refs.

## Verification and boundaries

- Focused catalog/manual/profile/privacy/contracts/driver suite: 125 collected, two skipped;
  initial failure was one stale Stage-0 version expectation. Corrected it and reran both
  affected privacy/registry files: 48 passed. In total all 123 runnable focused tests pass.
- Driver tests inspect the actual offline model input for two account identities using the
  same directive template, and ensure the stored template remains unchanged. Another case
  checks ordinary braces and substitution-looking account names are not recursively expanded.
- Ruff checks, formatting, driver mypy, and whitespace checks pass. No full-suite or live
  output-quality certification. The complete revert also restores the prior tests removed
  or changed by the rejected checkpoint, including its incidental provider-fixture edits.
- Initial git revert could not write the external worktree index in the sandbox; the scoped
  authorized revert succeeded through command approval. The shell has `python3`, not `python`.
- No paid calls, fleet changes, server restarts, database mutation, push or PR. Preexisting
  cumulative-review/catalog edits and untracked audit/report material were left untouched.

## Example revision

- Founder explicitly requested revising the newly authored local `account-research-briefing/v1`
  file: one fictional Acme example, removal of the second example, and a short seller-context
  note explaining why the brief emphasizes GTM capacity, campaign workload and buying roles.
- Updated that file and its v63 profile digest in place for this local revision; the active
  registry manifest expectation follows the new bytes. No runtime behavior changes.
- Both focused registry/disclosure checks and whitespace validation pass. No live calls.

## Explicit launch and system-prompt references

- Added the briefing skill path and `directive_text` instruction to the model-facing
  `launch_arv2_account_research@1` description. Its input/output schemas and behavior are unchanged.
- New Head-of-ABM prompt v16 has an Account deep research section pointing at that same skill.
  Active profile/composer selection moves to v64; earlier prompt/profile bytes are preserved.
- Updated the manual source note and generated manual v10; Stage-0 v37 updates its manual
  links. These are versioned documentation copies, not a new execution layer. The briefing
  skill itself remains v1 with the single Acme example.
- Focused catalog, generated-manual drift, profile, privacy and contract tests pass (two
  database-dependent skips). Existing disclosure coverage now checks the path in Stage-0,
  the active system prompt, actual tool descriptor and the loaded manual. Ruff, formatting
  and whitespace checks pass. No live calls, runtime restart, database changes or push.
