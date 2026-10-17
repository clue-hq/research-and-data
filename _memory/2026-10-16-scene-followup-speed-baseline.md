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

## 2026-10-16/17 — fix landed and measured (solo; commits 059cb55da, 30bcf5beb, 7567c2bd7)
- Founder: design agents ALWAYS solo (now in CLAUDE.md/AGENTS.md, env files, code defaults). Target: a small
  targeted edit ≤ 4 min send-to-done; revamps may take longer. Token clearing explicitly deferred (separate card).
- Change: solo prompt "Follow-up turns" section (read only what the user's message needs; inspect touched nodes;
  apply_structured_edit; preflight/render/view once; fix once; finalize edit_applied; no critique/round files;
  revamp → full routine; unsure → ask) + apply_structured_edit given to the solo agent + setup-step timing logs.
- Live run (2026-10-17, same ad, "Change the headline to "Let Conduit take the night desk."", run_aa561140b4d8…):
  **2 m 27 s** send-to-done (was 9 m 22 s); 8 model calls (27); 465k input tokens (3.1M); $0.53 ($2.06).
  Agent followed the routine: structured_edit_applied → preflight → render → one view → edit_applied. Headline correct.
- Remaining costs in that run: first model call 57 s (128k uncached opening context → the deferred clearing work);
  ~12 s routing + dispatch; setup steps ~10 s (auto_ad_references 5.4 s incl. the style-group call, brand kit 1 s,
  asset library 1 s, session manifest 0.8 s); ~9 s harness start; ~20 s after finalize.
- The silent 59 s minute did NOT recur. It ended at the style-group call inside resolve_auto_ad_references last
  time, so it was most likely reference resolution on a cold cache (first turn after dushanbe moved to R2 storage);
  unproven — design_turn.setup_step will show it if it comes back.
