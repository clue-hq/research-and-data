# Saved-research dossier and narrative trial — 2026-09-27

User requested the current claim-JSON formation + approved narrative flow on another saved account.
Artifacts: `.artifacts/premier-dossier-narrative-20260927/`; source trial:
`.artifacts/account-discovery-trial-20260924/premier-01/`. No production source changes, application
DB writes, new research/enrichment, fleet, person-depth jobs or publication. Current approved formation
v2/account narrative v2/editorial v1 used with configured Grok 4.6, OpenRouter, Langfuse.

Initial formation authored 107 findings but did not finish. Parser rejected reciprocal conflict
references; after compaction, repeated invalid full-section replacements and scratch writes stalled
recovery. Stopped exact child process after 30m56s, 63 completed calls, $4.239162 returned usage.
A review-only continuation with a local metadata patch adapter was prepared/offline tested and
started; user then explicitly prioritized narrative. Stopped continuation at 48s/2 calls/$0.108510.
Cancellation leaves original receipts status=started; stop receipt and REVIEW explain actual state.
No import-ready completion claimed. Original inputs, outputs and attempts preserved.

Narrative used the original saved 107-finding draft directly via local ID adapter; completed 11
sections (including Miscellaneous), 5356 words, all supplied IDs cited, in 161.386s/3 calls/$0.518602.
No semantic completeness guarantee. Why-fit remains overlong (740 words). HTML/Markdown are in
`account/output/`; exact draft JSON in `account/dossier.json`. Native offline tool checks and live
narrative reference/schema validation passed. Formation draft retains parser errors.

Newly observed filter gap: current enrichment_only removes description but leaves summary.seo;
provider descriptive prose reached a finding. Do not attribute solely to old-report contamination.
Unfixed in this task. Other output defects and granular evidence in local REVIEW, not repeated here.

Langfuse exports timed out: initial run cloud trace has 133 TOOL observations vs191 local starts;
cloud incomplete. Narrative cloud trace retrieved both tools. Local full traces retained. Interrupted
in-flight requests may have unreturned cost; returned aggregate $4.866274 is not invoice reconciliation.
Browser-use blocked local file URL; no alternate URL/browser workaround attempted. Visual test not
claimed. Codex Markdown open requested (queued). User gets HTML/MD links. No production integration
or new paid retry authorized by this completion.
