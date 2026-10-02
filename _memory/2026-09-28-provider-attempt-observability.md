# Provider attempt observability

User authorized per-attempt start/end, retry-reason and elapsed-time logging after an Exa person-depth request remained pending until cancellation.

Implemented at shared ProviderCaller transport boundary: structured provider.attempt.started/finished events correlated by call ID, provider/operation/label/attempt, timeout and Langfuse IDs; separate HTTP-attempt and retry-wait spans. Logs contain HTTP status or sanitized exception/cause class, no request bodies, headers or exception messages. Existing timeout, retry/backoff, ledger and raw-storage behavior retained. The shared seam also gives other providers the same diagnostics.

Exa thin-response retry emits a separate reason and span with first ledger ID, labels and measured result/report sizes. This distinguishes a second research request from a transport retry. A killed process cannot emit a final event; the pre-send start event remains the evidence of the unfinished attempt. No live provider call or worker restart performed.

Verification: 66 focused caller/Exa tests passed, including retry ordering/delay, exhaustion, pre-send visibility, interruption, Langfuse span creation and thin-response retries. Ruff and diff whitespace checks passed. Initial lint import-order failures corrected. Runtime Langfuse delivery still requires the next live test; offline tests verify instrumentation only.
