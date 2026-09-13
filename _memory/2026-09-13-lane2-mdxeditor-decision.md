# Lane 2 — MDXEditor selection (2026-09-13)

- Founder selected MDXEditor after a read-only comparison of existing editor/toolbar packages.
  Current checkout: Semarang, branch `visual-polish`. This session updates planning only.
- Revised lane index, Plan-tab frontend Task 5, toolbar plan/brief and parent R10/R11/section 4.3.
  MDXEditor replaces the proposed homemade CodeMirror toolbar/commands; Preview remains
  react-markdown + remark-gfm. Knowledge/Plan/ICP/persona share one visual editor.
- Native library block selector/table editing replace separate heading buttons/fixed table
  templates. Existing Save/Discard, Markdown-body API, version conflicts and front-matter
  ownership are preserved. No package, application, environment or runtime changes made.
- Official docs checked: toolbar, public theming/icons, Next client-only setup, initial Markdown
  value and normalization callbacks, source recovery and formatting-control option props.
  Actual selected-release compatibility and browser behavior remain to be verified in Task 5.
- Acceptance explicitly includes no dirty state from opening/normalization, undo to baseline,
  recoverable source after import failure, dirty drafts vs refreshed IDs, persistence and long
  text/table/code containment. Visual serialization may normalize source formatting.
- Also aligned parent section 4.3 with the already-ratified plan-part auto-open signal and removed
  Lane-2 checks that hardcoded another workspace's frontend port.
- Tooling: first full-file patch was rejected because delete/add targeted the same paths; retried
  as updates successfully. Two guessed MDXEditor API URLs did not resolve; no unverified APIs
  were made implementation requirements.
- Follow-up: execute the compatibility prototype before migration; complete Lane 2's unchecked
  tasks and browser proof. No production implementation or live acceptance is claimed here.
- Closing verification: reviewed the five planning diffs, checked cross-document editor ownership
  and reset lifecycle, and ran `git diff --check` successfully. No application tests were run for
  this documentation-only change. The pre-existing untracked evidence/diagram files were untouched.
