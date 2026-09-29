# Account handoff recovery — 2026-09-29

- Continued after the one authorized native qualification run. No additional
  generation, corrective prompt, service restart, project instructions or data
  mutation occurred in this continuation.
- Confirmed `_resolve_births` rejects off-project accounts but its error advised
  dropping the binding. The native trace had followed that advice. Home account
  mentions can reference workspace accounts without adding project membership.
- Existing membership contract was preserved: the human add-to-project route
  also approves discovered candidates. No automatic membership/approval was added.
- Corrected invalid-ID and off-project recovery messages to preserve the target
  and report the prerequisite. Added bound-target preflight to the canonical
  website contract and linked it from account personalization. Generic pages and
  explicitly unbound templates are exempt; a bound account with sparse research
  can still support a requested invitation.
- One read-only offline pressure check selected the intended action for four
  cases: off-project handoff, already-unbound Design brief, sparse-but-bound
  invitation, generic page. This is not a production-model compliance proof.
- 38 existing shared-contract delivery, family/materialization and solo-runtime
  checks passed; Ruff on the changed API file and `git diff --check` passed.
  Pytest emitted cleanup warnings for an older nonempty temporary garbage folder.
- The correction is instructional: a generic birth with no account ID is still
  valid at the API. Mechanical preservation of account-specific intent remains
  open and must not convert a mere reference into discovery approval. No new
  DB behavior was introduced or claimed tested.
- Native typography, interaction fidelity, mobile density and account-story
  qualification remain open. The original single-run audit is authoritative for
  observed quality; these offline checks do not qualify its page.
- Closing: source correction reviewed for only the three intended files;
  unrelated existing modifications left untouched. Local checkpoint only; no push.
