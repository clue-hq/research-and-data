# Stage-0 durable official-site crawling — C3 provider contract

**Status:** C3 implemented and verified; C4 durable acquisition/recovery has not started

**Parent:** [durable official-site crawl implementation plan](./FI-stage0-durable-official-site-crawl-plan.md)

**Depends on:** C0 frozen `PageFetcher` seam, C1 PostgreSQL ledger, and C2 URL/safety policy

---

## 1. C3 outcome and boundary

C3 supplies two interchangeable implementations of the frozen one-page `PageFetcher` protocol:

- `adapters/firecrawl_page/FirecrawlPageFetcher` — hosted, potentially paid acquisition through
  Firecrawl's single-URL `scrape` operation;
- `adapters/scrapling_page/ScraplingPageFetcher` — local, credit-free acquisition through a
  host-pinned Scrapling/curl transport.

Both declare immutable `PageFetcherCapabilities` and return the same `PageFetchResult` model.
Neither adapter owns a frontier, crawl depth, recursion, deduplication, scheduling, page priority,
robots policy, run state, claim writing, or background continuation. C5 receives a configured
`PageFetcher` object; it may inspect capabilities, but it may not branch on either provider name.

The provider SDKs are lazy-imported only in their provider packages. The shared adapter helper is
provider-neutral and only maps already captured HTML into the C2 link-observation contract.

## 2. Firecrawl single-page contract

One `fetch_one(request)` invocation performs exactly one async SDK call. The live client is built
with SDK retries disabled because only the durable C4 attempt ledger may authorize another
dispatch. Client construction and credential/SDK validation happen when the adapter is composed,
before C4 can mark an attempt dispatched:

```text
AsyncFirecrawl.scrape(
  request.requested_url,
  formats=[html, links],
  only_main_content=false,
  timeout=request.timeout_seconds
)
```

Requesting rendered HTML instead of provider-normalized prose preserves exact page bytes for C4
artifact hashing and lets the same C2 HTML extractor produce anchors/canonical observations for
both providers. Provider link output may supplement those observations; duplicates are removed by
`(discovered_url, relation)`. Returned links remain untrusted observations until C5 applies URL,
domain, depth, and page-ceiling policy.

Firecrawl declares:

| Capability | Value / consequence |
|---|---|
| Single page only | `true`; no crawl, map, batch, sitemap, depth, or recursive option exists in the adapter |
| Operation lookup / idempotency key | unsupported in this adapter version |
| Redirect chain | not reported; C5 must fail closed on a materially changed unreported final URL |
| Outgoing links | reported from captured HTML plus the provider link list |
| Cost | configured estimate, currently one cent; not asserted as actual provider billing; an explicit zero-credit receipt is `no_spend` |
| Receipt | sanitized `scrape_id`, `credits_used`, and `cache_state` only when supplied |
| Pre-dispatch no-spend proof | unavailable after the SDK call begins |

The adapter never preserves a raw provider payload, headers, credentials, exception string, or
token. Unless its receipt explicitly reports zero credits, a returned provider result—even an HTTP
error, external final URL, bad MIME, missing body, or oversized body—is `spend_confirmed` with
estimated cost because the hosted operation completed. It is permanent/policy-refused rather than
automatically retryable.

An SDK exception or timeout after dispatch is deliberately
`ambiguous + spend_unknown`. It carries no invented receipt and cannot authorize a blind retry.
C4 must reconcile or quarantine the durable dispatched attempt. Caller cancellation propagates
instead of being converted into a result.

## 3. Scrapling single-page contract and connect-time safety

The local adapter has no provider-credit spend. A successful page, HTTP error, policy refusal,
timeout, size refusal, or transport error therefore uses `no_spend`; transient transport errors and
HTTP 408/425/429/5xx are `retryable_no_spend`.

The default `ScraplingPinnedTransport` implements the C2 rebinding seam rather than relying on a
preflight DNS lookup alone:

1. resolve a bounded set of addresses through the injected C2 `AddressResolver`;
2. refuse if any address is non-public;
3. pin libcurl to exactly that approved set with `CurlOpt.RESOLVE`;
4. disable automatic redirects, ambient proxy environment variables, and transport retries;
5. stream into a bounded decompressed-byte collector;
6. convert the captured response through Scrapling's response/parser boundary;
7. for each 301/302/303/307/308, validate the same allowed-host set, detect loops/ceiling, resolve
   again, and establish a new pinned connection;
8. return the complete manual redirect chain with the terminal page.

The outer adapter deadline covers the entire redirect sequence, not a fresh full timeout per hop.
The injected-transport test seam is rechecked for host, status, MIME, and byte size so a test or
future transport cannot bypass the typed result invariants.

Scrapling declares no provider receipt, operation lookup, idempotency support, or actual monetary
cost. It does declare redirect-chain and outgoing-link support and can prove no provider-credit
spend.

## 4. Provider boundaries and dependency enforcement

The C3 source layout follows the C0 ownership manifest:

```text
adapters/
  page_fetcher_common.py       provider-neutral typed mapping helpers
  firecrawl_page/__init__.py   only Firecrawl SDK edge
  scrapling_page/__init__.py   only Scrapling/curl SDK edges
official_site/
  contracts.py                 frozen provider-neutral request/result/capability types
  discovery.py                 shared HTML link extraction
  safety.py                    approved-address connector seam
```

Import-linter now makes `official_site` independent from other worker packages except the exact C3
contract/discovery/safety imports above. It also treats `curl_cffi` as a provider transport SDK and
allows that import only inside `adapters/scrapling_page`. The research package declares
`curl-cffi>=0.13,<1` directly because C3 uses its public pinning API rather than relying on
Scrapling's transitive dependency.

The static acceptance suite:

- scans every research source file and refuses eager or out-of-package Firecrawl, Scrapling, and
  curl imports;
- parses the Firecrawl adapter AST and refuses crawl/map/batch operations and recursive/depth/
  sitemap/limit options;
- proves the local SDK connector contains DNS pinning, disabled auto-redirects, disabled ambient
  proxies, and zero hidden retries;
- scans coordinator-owned `official_site` modules and rejects provider-name branching;
- imports the locked SDKs and checks the exact single-page/pinning primitives still exist.

## 5. Verification and C4/C5 handoff

The C3 suite exercises the same success contract against both providers and records exact call
counters. It also covers:

- attribute- and dictionary-shaped Firecrawl SDK results;
- sanitized receipt mapping and duplicate-link collapse;
- hosted paid success/error/timeout/exception spend classification;
- local HTTP retry matrix, MIME/body/size/final-host validation, timeout cancellation, and typed
  transport failures;
- private-IP refusal before connect, external redirect refusal before the next connect, redirect
  loop/ceiling enforcement, and DNS re-resolution/pinning for every hop;
- redirect and canonical/anchor provenance;
- concurrent invocations with exactly one URL transport call per invocation;
- protocol runtime conformance, immutable capability declarations, lazy SDK imports, dependency
  contracts, Ruff, mypy, and the retained C0/C2 suites.

C4 must persist `prepared` and `dispatched` before invoking these adapters, retain the body-free
metadata/receipt, store successful bytes, and prevent any automatic redispatch of
`spend_unknown`. C5 must wrap the adapters in the C2 preflight and post-response validation flow,
bound links to the configured ceiling before discovery insertion, and select a registered fetcher
without provider-name branching. C3 does not wire a production coordinator or make a live provider
call.
