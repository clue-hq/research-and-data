# Asset vision reproduction — 2026-09-22

## Outcome

Four user-approved live OpenRouter calls completed. The same Wynwood and Arbio preview bytes that accompanied the bad stored descriptions were recognized as logos in every replay, including both production-prompt/schema calls. Neither the Wynwood portrait nor the Arbio circuit-board failure reproduced.

This shows that the configured model/provider path can recognize these exact previews. It does **not** identify the historical failure's cause, demonstrate a fix, or certify the production descriptions as reliable. The leading unresolved hypothesis remains intermittent model/provider visual-grounding failure. No specific provider can be blamed from this experiment.

There is a concrete narrower finding: results disagree about the backgrounds of the same transparent PNGs. Some describe a white background, while others describe the blue-gray RGB values held in fully transparent pixels. This is consistent with differing alpha handling or visual interpretation, but raw model outputs alone cannot prove the providers' preprocessing implementation.

## Authorization and scope

- User requested reproduction, then explicitly approved four paid calls sending the two previews and existing source metadata to OpenRouter.
- Automatic approval review initially blocked execution before any calls were sent. Execution resumed only after the user's explicit `Approve` reply.
- No application code, runtime configuration, asset descriptions, overrides, or ingestion jobs were changed. Existing services were not restarted.
- Spend was recorded through the existing provider seam in the isolated diagnostic workspace `ws_san_diego_asset_quality_sample`. All four ledger drains succeeded.
- Four calls total; no automatic HTTP retry, no follow-up model calls, no provider pinning.
- Total provider-reported cost: **$0.0166839**.

## Method and limits

The script reconstructed each `DescribeItem` from the audit snapshot's preview bytes, analyzed preview metadata, human context and source occurrences. SHA-256 was checked before sending and again against the actual captured wire request. Each request contained exactly one image attachment.

Production cases used the current `OpenRouterDescriber._invoke` to construct the actual system prompt, user manifest and strict JSON schema. This construction was captured offline, then sent through the normal `spend.openrouter_call` and `HttpxTransport` with a recording transport wrapper. No mock provider response was used in the live tests. Full outgoing JSON bodies and incoming response bodies were saved locally; credential headers were not saved.

Minimal cases used the identical preview, the same model and temperature, a short image-only OCR/description instruction, no source metadata, no system prompt and no response schema. They set `max_tokens=700`. Production cases retained the production output settings. Both used automatic routing with `require_parameters=true`.

Important limitations:

- These are **production-prompt/schema replays**, not copies of historical wire receipts, which were never retained. Exact preview bytes and stored analyzed context are preserved, but the historical evidence entry's kind/filename hint is not in the analyzed-input record. The replay used `kind=image` and the registry filename. The still-running ingestion had no persisted evidence JSON, and the affected entry was not available from a completed brand-kit record at inspection time. Kit evidence targets can use a different hint and omit the registry filename.
- The original providers are unknown. The four new calls went to four different providers; therefore this is not a controlled same-provider prompt comparison.
- Both prompt pairs succeeded at subject recognition. There is no evidence here that simplifying the prompt fixes the historical failure.
- Production replay latencies and costs differ from the minimal requests, but provider and output-budget differences prevent attributing those differences solely to the prompt.
- The HTTP request timeout was 100 seconds; this is a transport timeout, not an absolute wall-clock deadline. One response took 112.89 seconds. No retry occurred.

## Results

All four calls used `deepseek/deepseek-v4.1-flash`, temperature 0, and returned HTTP 200 with finish reason `stop`.

| Asset / request | Actual provider | Result | Background described | Seconds | USD |
| --- | --- | --- | --- | ---: | ---: |
| Wynwood / production prompt + schema | Venice | Correct Wynwood House wordmark, asterisk and registration mark | Muted teal/gray; claimed solid | 32.92 | 0.0091125 |
| Wynwood / minimal vision | SiliconFlow | Correct Wynwood House wordmark and symbols | White | 4.05 | 0.0004389 |
| Arbio / production prompt + schema | DigitalOcean | Correct Arbio logo; description was terse | White; claimed opaque | 112.89 | 0.0069537 |
| Arbio / minimal vision | Wafer | Correct Arbio wordmark | Grayish-blue | 7.15 | 0.0001788 |

Both structured results passed the application's schema/source-occurrence validator. Subject recognition was correct, but output quality still had defects: the Arbio structured response included leading commas in several fields and generic `Not applicable` text, and both structured descriptions treated transparent artwork as opaque/background-colored content.

## Transparency evidence

Both images contain opaque black lettering and fully transparent pixels whose hidden RGB channels equal **(76, 105, 113)**.

| Asset | Preview size | Fully transparent blue-gray pixels | Preview SHA-256 |
| --- | --- | ---: | --- |
| `asset_ing_a99a08190a65a455` | 512 × 137 | 52,168 | `5337550b43bae4346505409235f423ef2b6ac82ddc758b8f0d9ba2e9058bf6d8` |
| `asset_ing_bdb03352de1a1c47` | 384 × 127 | 31,059 | `f48d5764f8b11900209054027377982ede06b382b0faa5089a43d33a443f88d3` |

Proper compositing ignores the hidden RGB values where alpha is zero. Simply discarding alpha exposes those values as a visible blue-gray background. The current preview code preserves RGBA and does not standardize the analysis matte. The provider responses are consistent with that distinction, but the experiment did not send opaque controls, so it does not establish alpha stripping as the exact upstream mechanism.

This finding helps explain inaccurate background/transparency descriptions. It does **not** explain or reproduce a person replacing Wynwood, or circuitry replacing Arbio.

## What the evidence supports

1. The two exact preview byte sequences are decodable and recognizable through the live model path.
2. The current production prompt/schema can produce correct subject identification for both images.
3. A model name does not hold the serving provider constant in this configuration. Requests specify `require_parameters` but no `only`/`order` constraint. OpenRouter documents automatic provider load balancing and optional provider controls: <https://openrouter.ai/docs/guides/routing/provider-selection>.
4. Input transparency is not normalized, and the returned background descriptions vary in a way consistent with different handling of alpha.
5. The earlier audit's confirmed acceptance defect remains: structural validation allows ungrounded/refusal/placeholder descriptions to become ready. This explains why bad descriptions were accepted, not why the model originally generated them.

## Next diagnostic, not executed

A controlled follow-up should pin one provider and compare repeated identical production requests with the same logo composited onto an explicit opaque background. Test the original and opaque input under both minimal and production prompts, retaining wire receipts. That separates provider variation, alpha treatment and prompt/schema effects more effectively than these automatically routed calls. It would require additional paid calls beyond the four approved here.

## Receipts

Local, uncommitted diagnostic material: `.context/asset-vision-replay-20260922/`. `results.json` contains the checked summary; each timestamped case has `.input.json`, `.request.json`, `.response.json`, `.transport.json` and `.summary.json`. `replay.py` records the reconstruction and call path. Raw responses may contain provider-generated reasoning and are not copied into this report.

| Case | OpenRouter generation ID | Receipt filename prefix |
| --- | --- | --- |
| Wynwood production | `gen-1790022406-QRu4n36TWnWEwiZT7GCT` | `202645977254-wynwood-production` |
| Wynwood minimal | `gen-1790022439-g3op1uAN9ByyM1UjSlVZ` | `202718982785-wynwood-minimal` |
| Arbio production | `gen-1790022443-IHsIzQqKbuAsb77obKoE` | `202723103034-arbio-production` |
| Arbio minimal | `gen-1790022556-e9WFY6f3xLqjJI9pTMCK` | `202916065600-arbio-minimal` |

Verification: four captured requests, one image each, all sent preview hashes matched the affected historical analyzed-preview hashes; four successful HTTP results and ledger drains; both production analyses passed the current validator. No application build/test gate was needed because application code did not change.
