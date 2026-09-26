# r18 backend repairs — 2026-09-26

Founder authorized Deepgram cost tracking, generation/nomination deadlock prevention, then
oversized receipts; research-efficiency and narrative changes remain deferred. Requested
Langfuse coverage for all tool calls and progress explanations at completed checkpoints.
No new paid calls or fleet launches. Preserve existing unrelated working-tree edits.

## Deepgram cost checkpoint

Nova-3 prerecorded rate × provider-returned fractional duration now records estimated USD
through the existing ProviderCaller ledger/cost-report/Langfuse path. Marked inferred/estimate,
not invoice verified. Missing or failed metering remains unknown. Configurable mono/multi rates
are documented in .env.example and mirrored locally; current official PAYG rates checked at
https://deepgram.com/pricing. No transcription or automatic-retry changes.
14 offline client tests passed; media DB suite passed in isolated clue_r18_backend_repairs_20260926,
including ledger/trace/cost-report alignment and reuse without repurchase. No historical billing
rows rewritten; r18's old null charge remains historical, not silently treated as metered.

## In-progress backend work

Generation and nomination locks changed to NO KEY UPDATE, preserving writer serialization
without blocking FK KEY SHARE. Isolated two-connection test replays the log's FK acquisition:
old lock strengths produce 40P01, new ones complete; duplicate signals keep one revision.
The first minimal fixture omitted an FK recheck PostgreSQL can optimize away; explicit same
KEY SHARE acquisition now makes the recorded cycle deterministic. No broader lock rewrite.

Receipt repair composes the existing C5 spill sink for parent and child workspaces; hydration
now validates instead of model_copy bypassing size checks. A real 82-finding scripted import
exposed that old research profiles cannot read reads/. New resource revision 19 adds that
read-only prefix for all research roles, leaving old pinned resources and prompts unchanged.
Large-import finalization/trace test still being verified at this checkpoint.

## Deadlock checkpoint complete

Both lock-cycle regression variants pass (legacy 40P01 and repaired success). Five duplicate
signal deliveries retain one revision; five distinct concurrent events receive consecutive
revisions with no lost updates. Existing generation, early-person-release, driver and JSON
import suites pass: 18 focused DB checks in this final group. Changes are limited to nomination
parent locks and generation writer locks; cap/revision serialization remains exclusive.
