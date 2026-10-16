# 2026-10-16 — Scene-ad follow-up speed: diagnosis + baseline (branch feat/scene-delete-key, stack on clue_nashville_pm_clone)

## Founder ask
Follow-up edits on an existing ad ("change this text") take as long as a first draft. Wants: read only what the
task needs, act, review once, correct once, stop.

## Verified causes (code + traces)
1. Session carries the whole previous conversation: first draft opened at 37k tokens and closed at 162k; the
   follow-up OPENED at 159–167k (cache expired → ~28–34 s first call), growing every turn.
2. Every turn runs the first-draft routine (prompts.py:1170-1290): batched gather → rewrite + validate
   creative-direction.json (receipts reset per turn, substrate.py:478-484) → delegate author → render/view →
   whole-design critique → finalize gates. No edit path: apply_operations / apply_structured_edit exist
   (substrate.py:851,902) but are in neither author_tools nor orchestrator_tools (harness.py:659,758).
3. Design runtime (lumen_agent, scene + web) has NO tool-result clearing / stale-preview pruning; only stock
   deepagents summarization (85% of window or 170k tokens), which did not fire. Research has
   BatchedToolResultClearing (platform/agents/clue_agents/tool_result_clearing.py) + compaction. harness.py:553
   lists history pruning as planned, never landed.
4. ~100 s of setup before the agent starts (exit judge 6.5 s; a 59 s silent gap after design_job.started —
   unexplained, needs timing logs; style-group call 9.6 s; session restore 14 s).

## Baseline (Conduit, "Atrium Hospitality 1:1 LinkedIn ad", doc_e15da7b1…, thread thr_202a671…)
Follow-up 1 "Change the headline to "Hand off the overnight desk."" (run_3593eca119dc…):
waited 9 m 22 s; run 7 m 22 s agent wall; change landed 7 m 15 s after send; 27 model calls; opening context
159k (128 cached); 3.13M input tokens; $2.06; critique REJECTED twice (headline wraps to 2 lines) yet finalized
edit_applied. Over the founder's 7-minute stop rule, so follow-up 2 was not sent.
Earlier follow-up (2026-10-05, run_30bd348…, different ad): 5 m 15 s, 24 calls, opening 167k, $3.22.
Report: `scripts/design_followup_timings.py --document <doc>`.
