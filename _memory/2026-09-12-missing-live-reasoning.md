# Missing live reasoning — 2026-09-12

Founder reported that the implemented inline disclosure shows only Thinking on a
real Grok turn. Investigation only; preserve the discussion/plan/approval sequence
before changing gateway contracts. No application edits or server restarts.

Verified against Semarang, not a sibling workspace:
- Live browser response completed successfully but displayed no reasoning text.
- Turn `ddcf81fc-920c-5adc-8eb0-4870037fc6f7` has four reasoning creation/completion
  pairs, no reasoning text deltas or snapshot text, and one final-answer text delta.
  Read-only query asserted database `clue_semarang` and used READ ONLY transaction.
- Executing worker-2 PID 62233 belongs to Semarang. Its whitelisted launch settings
  already contain CLUE_CHAT_REASONING_TRACE_MODE=raw, CLUE_AUTH_ENVIRONMENT=local,
  HEAD_OF_ABM_AGENT_MODEL=x-ai/grok-4.6. This is not an absent local flag.
- `libs/clue-gateway/clue_gateway/agent_model.py::_build_openrouter_model` routes
  non-OpenAI models through ChatOpenAI chat completions. Installed langchain-openai
  1.4.1 explicitly does not preserve third-party reasoning response fields.
- Offline reproduction through its real `_convert_delta_to_message_chunk` followed
  by `reasoning_deltas_from_chunk` drops each synthetic reasoning, reasoning_content,
  and reasoning_details field: empty normalized extras, zero extracted fragments.
- The stream extractor assumes normalized reasoning blocks or reasoning_content in
  additional_kwargs, which this adapter never supplies on the Grok route.

Conclusion: a confirmed gateway compatibility defect prevents any provider-exposed
reasoning from reaching this UI on that path. The exact raw provider response for
this historical turn was not captured; do not claim proof that it emitted reasoning.
The frontend POC/fixture checks did not establish real provider delivery.

Proposed next slice: preserve provider-supported reasoning at the gateway adapter
seam, normalize into the existing trace stream, test ordinary text/tool isolation
and deduplication, then prove a real turn reaches the inline disclosure. Keep
production availability and durable trace retention separate decisions. No raw
reasoning, customer message content, or credentials retained in this note.

Tooling: local DB socket read initially hit sandbox permission denial, then passed
under approved read-only escalation. First dependency source read guessed Python
3.13; actual Semarang venv is Python 3.12. Use imports/globs for dependency paths.

Subsequent founder instruction explicitly includes this repair in the chat-polish
plan of action. Canonical plan now lives in
`apps/frontend/docs/architecture/ai-elements-and-reasoning.md`
(`#provider-reasoning-delivery-repair`), sequenced as CP1 in Projects §6A. This is
planning authorization, not a claim of a fixed adapter or live delivery. No
gateway dependency or application code changed during planning.
