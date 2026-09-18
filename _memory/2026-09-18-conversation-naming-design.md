# 2026-09-18 — conversation naming (chat titles + project names): design session

Branch `research-streaming-v3` (trenton lane). Purpose of the branch per the founder: replace
"Untitled project" / "New chat" / the 80-character first-message prefix with generated names, the
way ChatGPT names chats (a separate cheap model call over the opening exchange).

Spec: `docs/superpowers/specs/2026-09-18-conversation-naming-design.md` — awaiting founder review
of the written spec; the implementation plan comes after that.

Rulings taken in discussion: project named after the FIRST AGENT REPLY (not the first message);
chat title at the same moment (one call, both names on the Home path); hook inside the fleet turn
worker (engine turn-close path), no new task kind / SSE event / migration; generate once, manual
rename always wins (conditional `UPDATE … WHERE title IS NULL` / `name='Untitled project'`);
"first completed turn" so existing untitled rows name themselves on their next turn (no backfill);
model env knob default `openai/gpt-5.6-luna`; timeout 60 s ("which LLM responds in 5 s"); switch
defaults on.

Design consequence the founder should confirm at spec review: because the composer unlocks only
on the terminal turn event, the namer must not sit on the critical path — it starts when the reply
is known, the terminal event waits at most a 3 s grace, a slow call finishes detached, and the
frontend adds a bounded catch-up poll (every 5 s, ≤ 60 s) only while a placeholder is visible.

Verified facts that shaped it: `rename_thread`/`rename_project` are granted to no agent role;
`_first_thread_title` is the R0 rule in `chat/router.py`; the bootstrap idempotency check compares
the thread title (must drop that or replays 409 after naming); the ARV2 display's
`LunaSectionRunner` + `ProviderCaller` is the metered one-shot-call precedent; the engine reads the
reply back before `_project_turn_close` emits `turn_finished`.
