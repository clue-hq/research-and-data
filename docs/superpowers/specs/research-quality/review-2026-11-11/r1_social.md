# R1 — adversarial review: footprint SOCIAL-POST stack (dd9a7d74a..HEAD)

Scope: `platform/api/clue_api/footprint/{social,social_types,short_links,treg_client,social_video,handles,text}.py`,
the social/handles jobs in `platform/api/clue_api/arv2/footprint_operations.py`, and the matching tests.
Offline suite `uv run pytest tests/footprint -q --ignore-glob='*_live.py'` is green (92 passed). Every
"reproduced" finding below was run with the repo's own `ScriptedTransport`/`ProviderCaller` wiring:

- `/private/tmp/claude-501/-Users-aryankeshri-conductor-workspaces-research-and-data-research-trial/7b4c6fab-cdd6-4591-80a2-9a98dab021da/scratchpad/review/repro_social.py`
  (run: `PYTHONPATH=. uv run python <path>` from the worktree)
- `/private/tmp/claude-501/-Users-aryankeshri-conductor-workspaces-research-and-data-research-trial/7b4c6fab-cdd6-4591-80a2-9a98dab021da/scratchpad/review/repro_redirect.py`
  (spins up a local 127.0.0.1 redirect-loop server; no paid or external call)

Not re-reported (already known): X text HTML-escaped; each short-link expansion is an acquisition_gap + trace;
social posts never become citable evidence files; no one-line overview for large histories.

---

## CRITICAL

### 1. Someone else's post in a person's LinkedIn feed is filed as `kind="own"`, and the receipt preview shows its words with no author
- **Where:** `social.py:196-219` (`_li_post`, `kind="own"` unconditionally for the posts endpoint, `kind="repost"` only when there is a reshare with no text); `footprint_operations.py:227-235` (`_title` → `own[:200]`) and `:238-252` (preview rows carry only title/url/published).
- **What is wrong:** fetchinio's posts list can contain posts *authored by someone else* — the project's own ledger records it (`media-and-social-sources-ledger.md:224`: "A post in a person's feed can be someone else's (a Meera Mani post appeared in Dilip's feed)"). The parser never compares `author.url`/`author.name` with the profile being read, so such a post becomes `kind="own"`, `text=<Meera's words>`. The type docs say `own` = the person's post. In the receipt the agent reads first, the row is just `title: "Meera's own words"`, url, date — under a job described as "Everything the person has posted on LinkedIn".
- **Failure scenario:** `linkedin_activity(..., "https://www.linkedin.com/in/dilip", "posts")` with an item `author.name="Meera Mani", content="Meera's own words"` → `Post(kind="own", author_name="Meera Mani", text="Meera's own words")`; preview `[{'title': "Meera's own words", 'url': ..., 'published': ...}]`. An agent quoting from the preview (or trusting `kind`) attributes Meera's words to Dilip — the misattribution class the product treats as the worst failure. The same unconditional `kind="own"` exists for Instagram (`social.py:444`, collab posts by another `user`) and Facebook (`social.py:484`, `author_url=profile` stamped on every post regardless of `author.name`).
- **Verified:** reproduced (repro_social.py, case B1).
- **Confidence:** high that the code does this; the provider shape is documented in the ledger as observed live.
- **Fix direction:** compare the item author with the requested profile (URL slug / URN) and file a mismatch as a distinct kind (or `own=False` with `shared`), and put author + kind into the preview title for any post not authored by the subject.

---

## IMPORTANT

### 2. A refusal on any page after the first is reported as `state="complete"` (no gap)
- **Where:** `social.py:107-119` (`_history`), together with the `parse` functions that return a `closed` verdict on error pages: X `:371-372` (`_closed(...) or "not_found"` for *any* `status >= 400`), company `:510-511` (same), Instagram/Facebook `:424-426` and LinkedIn `:233-234` (`_closed` → `"not_found"` whenever `status==404` or the message contains "not found"/"private"/"restricted").
- **What is wrong:** `if closed and not posts: return closed` only handles page 1. On page ≥2 a `closed` verdict skips the `reply.status >= 400 and not closed` gap branch (because `closed` is truthy), the page parses to `[]`, `fresh` is empty, the loop ends and returns `state="complete", gap=None`.
- **Failure scenarios (all reproduced):**
  - X: page 1 ok, page 2 → 429 ×4 (the wrapper retries 429, then hands it back) → `complete None 1 post` (A1). Any treg/TikHub 4xx mid-timeline (429, 401, 402, 403, 400) does the same.
  - LinkedIn: page 2 → 404 `{"message":"Pagination token not found"}` → `complete` (A4).
  - Instagram: page 2 → 404 `{"message":"Cursor not found"}` → `complete` (A7).
  The agent is told it has the whole history ("complete: every page the provider had") when it was cut.
- **Confidence:** high (reproduced).
- **Fix direction:** treat `closed` as an answer only on page 1; on later pages any `status >= 400` (or unparseable page) is `partial` with a gap.

### 3. X and company pages turn every refusal or error envelope into `not_found` (and treg out-of-credit is never latched)
- **Where:** `social.py:371-372` and `:510-511` (`_closed(body, status) or "not_found"`); `treg_client.py:63-76` (no `halt_rule` on the CallSpec).
- **What is wrong:** for X and company LinkedIn, *any* first-page 4xx, or a 200 whose `data` is not a dict, is reported as "the account does not exist".
- **Failure scenarios (reproduced):** first page 402 `{"error":"insufficient balance"}` → `not_found` (A2); first page 200 `{"code":400,"message":"Request failed, please retry","data":null}` → `not_found` (A3). Same for 401 (bad/empty `CLUE_TREG_API_KEY`, which the ledger says is the current trial state), 429, 403. `quality_provider_tools.py:252-269` then files it as `refused` with code `provider_refusal` — indistinguishable from a real "no such handle", so the agent concludes the person has no X presence. Because treg calls carry no `halt_rule`, a 402 out-of-credit is not latched either: every later footprint job keeps calling treg and keeps getting "not_found".
- **Confidence:** high (reproduced).
- **Fix direction:** reserve `not_found`/`private` for explicit provider statements (404 + not-found body, private flags); everything else on page 1 → `unavailable` with a gap naming the HTTP status; add a treg halt rule for 402.

### 4. A 200 with a non-JSON body or an error envelope is "complete, zero posts" (LinkedIn/Instagram/Facebook)
- **Where:** `social.py:232-252` (LinkedIn: `not isinstance(body, dict)` → `[], None, _closed(...)=None`), `:423-455` (Instagram), `:465-492` (Facebook); `treg_client.py:80-83` returns non-JSON as a string body.
- **What is wrong:** a 200 whose body is HTML/text, or a JSON body without `posts`/`items` (e.g. `{"success": false, "message": "Upstream timeout"}`), parses to no posts, no next page, no verdict → `state="complete"`, 0 posts, no gap.
- **Failure scenario (reproduced):** LinkedIn 200 `<html>upstream error</html>` → `complete None 0` (A5); 200 `{"success":false,"message":"Upstream timeout"}` → `complete None 0` (A6). The receipt then reads "empty": "this person has never posted on LinkedIn".
- **Confidence:** high (reproduced); how often the providers do this is unknown.
- **Fix direction:** a page that lacks the expected list key (or is not a dict) is an error page → `unavailable`/`partial` with a gap; ScrapeCreators' `success: false` should be read explicitly.

### 5. `partial` histories reach the agent as receipt status `completed` with no error code
- **Where:** `footprint_operations.py:238-260` + consumer `quality_provider_tools.py:251-269, 520-543`.
- **What is wrong:** the consumer treats `state` in {unavailable, empty, ambiguous, not_found, refused, failed} as refused; `partial` is none of these, so the receipt is `status="completed"`, `error_code=None`, `result_count=n`. The gap text lives only inside the saved JSON (`gap`, singular — the other footprint jobs use `gaps`, a list, and the consumer reads `value.get("gap")` only on the refused path). An agent that works from the receipt preview (20 newest posts) cannot tell a cut history from a whole one.
- **Verified:** read-only reasoning on both files (receipt model `AcquireResearchReceiptV2` has no other carrier).
- **Confidence:** high.

### 6. Short-link expansion follows HTTP redirects to any host with the unguarded transport; a redirect loop or bad encoding crashes the whole paid job
- **Where:** `short_links.py:46-61` (`_open` catches only `SpendError`), run inside the `"treg"` hop whose transport is `HttpxTransport` (`clue_spend/transport.py:86-96`: `follow_redirects=True`, catches only `TimeoutException`/`TransportError`, no body-size bound, no private-address check). Contrast `media_resolution.PublicMediaTransport` (validated public IPs, bounded body, no blind redirects), which the codebase already uses for exactly this kind of third-party GET.
- **What is wrong / scenarios:**
  - Crash: `httpx.TooManyRedirects` and `httpx.DecodingError` are `RequestError`s, not `TransportError`s, so they escape `HttpxTransport`, escape `caller.call`, escape `_open` (not a `SpendError`), propagate out of `pool.map` and out of `linkedin_activity`/`x_posts`/`company_linkedin_posts` **after** every timeline page was bought. Reproduced: a short link whose GET lands on a redirect loop → `linkedin_activity CRASHED after paying for its pages: TooManyRedirects` (repro_redirect.py). The money trail survives (`_dispatch` drains), but the result — all posts — is lost and the job reports an exception.
  - SSRF-lite / unbounded fetch: if `t.co` or `lnkd.in` answers with an HTTP 30x (the code relies on them answering 200 with a refresh/interstitial page for a browser UA; that is a behaviour observation, not a contract), the worker follows it to whatever the post author linked — including loopback/private addresses (the repro shows the transport happily following to 127.0.0.1) — downloads the full body into memory, and stores it in the raw sink (`keep_body` default `True`). `_address` then finds nothing and the link is silently "not opened".
- **Confidence:** crash path high (reproduced); SSRF exploitability medium (depends on the short-link services issuing HTTP redirects).
- **Fix direction:** open short links with `follow_redirects=False` (read the 30x `Location` as the answer — that is also the address you want) through the public-only transport; catch broad exceptions per link in `_open` and record them as not-opened.

### 7. Querying an X handle that differs from the account's current screen name marks every own post a "repost" and skips the long-quote read
- **Where:** `social.py:379-387` (`repost = ... or screen.lower() != handle_lower`), `:308-315` (`post.kind == "repost"` → quote never read in full and never flagged).
- **What is wrong:** the ledger records that TikHub "works on the renamed handle (Ana)" — i.e. an old handle (PDL often holds old handles) resolves to the account under its new `screen_name`. Every tweet then has `screen != handle`, so all of the person's own tweets become `kind="repost"` (their own words downgraded to someone else's repost), and a long quoted post inside one is kept at TikHub's ~280-char clip with `text_may_be_cut=False` — truncated text presented as complete. The same happens if the agent passes a handle with stray whitespace (`XPostsArgs.handle` is not stripped).
- **Failure scenario (reproduced, B3):** `x_posts(..., "ana_old")`, items with `screen_name="ana_new"` → `repost 'my take' (270, False)` and `repost 'my own words'`; only 1 request made (no full read).
- **Confidence:** high for the code path; medium for frequency.
- **Fix direction:** classify repost from `retweeted_tweet`/`RT @` only (or compare against the account id/screen name returned on page 1), never from handle string equality; mark any un-read long quote `text_may_be_cut` regardless of `kind`.

### 8. `find_handles` hides PDL failure as "no handles found"
- **Where:** `pdl_client.py:62-71` (transport error, 401, 402, 429, non-JSON → `None`), `handles.py:77-81`, `footprint_operations.py:375-405` (`gaps: [] if pdl else ["pdl_key_missing"]`, `state: "complete"`).
- **What is wrong:** a PDL outage, a bad key, an exhausted plan (402) or a rate limit all return `None`, which `find_handles` treats exactly like "PDL has no match". The job says `complete` with `gaps: []`, so the agent concludes the person has no X/Facebook accounts. Also PDL's `likelihood` is discarded (not requested via `min_likelihood`, not returned on `HandleCandidate`), so a weak name+company match at PDL's default threshold is presented with the same weight as a LinkedIn-anchored one.
- **Verified:** read-only reasoning (single-branch code; `status != 200 → None`).
- **Confidence:** high for the hidden failure; medium on how often PDL matches the wrong person (ledger: 0 wrong in 20).

---

## MINOR

### 9. X retweet without `retweeted_tweet` keeps the clipped "RT @…" text in `Post.text` with no cut flag
- `social.py:388-389` (`own = "" if original is not None else text`). `Post.text` is documented as "only the words of this post's author"; here it holds Bob's words in X's 140-char clipped form, and `Post` has no `text_may_be_cut`. Reproduced (B4): `repost N 'RT @bob: yyyy…' shared=None`. The `RT @` prefix makes it recognisable, so minor; the same branch also covers non-retweet items whose author ≠ handle (see 7), where the other author's full words sit in `text` with `kind="repost"` and no `shared`, and the preview title (`_title` → `own[:200]`) shows them with no "Reposted from".

### 10. A reaction's `published_at` is overwritten with the reaction time; the liked post's own date is lost
- `social.py:246-249`. The saved post carries the liked author's words with the date the *person* reacted (reproduced B2: liked post dated 2026-10-27 saved as 2026-10-29). A claim "X wrote on Oct 29" would be misdated, and there is no field left holding the original date. Keep both (e.g. `reacted_at`).
- Related: reactions' preview titles are the liked author's words with no author (`_title`); the job name gives context, so minor.

### 11. A short link cut mid-code is opened and mapped
- `short_links.py:21` regex stops at "…", so a quoted preview cut inside a link (`... https://t.co/Ab…`) yields `https://t.co/Ab`; it is opened and, if it resolves, mapped in `links` to an unrelated address. Reproduced (C1) with a scripted t.co answer: `{'https://t.co/Ab': 'https://unrelated.example/...'}` alongside `text_may_be_cut=True`. Real t.co codes are 10 chars, so a short prefix most likely 404s; low real-world risk. Skip links inside text flagged as possibly cut, or require the full code length. (Regex is also case-sensitive: `HTTPS://T.CO/…` is ignored.)

### 12. Company paging stops early when a page's oldest post falls on the requested `end_date`
- `social.py:555-556` + `:119` (`following != query`). If page N's oldest date equals the `end_date` it was asked for, `following == query` and paging stops as `complete`, even though that page brought new posts. Reproduced (D1): page 2 had a new post "1b" on the same day → stops, post "0" never fetched. Needs ≥ a page's worth of posts on one calendar day (or a short page), so rare. Also: `posted` on a reshare item is not established as the reshare's date (ledger only says text/url/poster are the original's); if it were the original's date, `min(dates)` would skip a range of the company's posts. Unverified, low confidence.

### 13. Any non-dict list item or string `author` crashes the reader (all pages lost from the result)
- `.get` on unchecked items: `social.py:197, 237-249, 263-270, 374-380, 428-436, 470-476, 513-517`, `social_video.py:27-28`, `handles.py` (fine). Reproduced (E1): `posts: ["oops"]`, `timeline: [None]`, `author: "Ada"` → `AttributeError`. Provider shape drift becomes a job exception rather than a skipped item.

### 14. The same long quoted post is fetched once per quote tweet
- `social.py:305-332` has no cache by `shared.post_id`; quoting one long thread several times pays for each. Small cost (0.1 ¢ each).

### 15. Leftover shim and stale reference
- `platform/api/clue_api/arv2/text.py` is now a `sys.modules` re-export of `footprint.text`; its only remaining importer is `tests/arv2/test_text.py`, and `arv2/structuring_client.py:295` still cites `clue_api.arv2.text.substring_verdict`. Dead indirection; point both at `clue_api.footprint.text` and delete it.

### 16. (pre-existing, moved code) `text.normalize_for_match` leaves double spaces after punctuation removal
- `text.py:40-41` collapses whitespace *before* blanking punctuation, so `"Hello, world"` → `"hello  world"` and `substring_verdict("hello world", "...Hello, world...")` → `NOT_FOUND` (verified). The docstring claims punctuation differences "cannot make a genuinely verbatim quote look invented". Moved verbatim from `arv2/text.py` and documented as a faithful PoC port, so out of this branch's change set; flagged because the footprint quote checks now import it.

### 17. Nits
- `SocialHistory.cost_usd` is a float sum without rounding in `_history` (`0.0015*3 = 0.0045000000000000005`); `_x_full_quotes` rounds, `_history` does not.
- `_closed` substring match `"private" in message` on any body (e.g. an auth error mentioning a "private key") would read as a private account.
- `handles._tail` keeps query strings (`facebook.com/profile.php?id=123` → handle `profile.php?id=123`, then probed on Instagram).

---

## Test gaps (why the above passes CI)
- No test feeds a 4xx/429 or an error envelope on page ≥2, a first-page 4xx to X/company, a 200 non-JSON body, or a `success:false` body (findings 2–4).
- No test has a LinkedIn/IG/FB item authored by someone else (finding 1), or an X timeline whose `screen_name` differs from the queried handle (finding 7).
- Short-link tests pin `WORKERS=1` because `ScriptedTransport` is order-dependent and not thread-safe; the concurrent path (8 workers) is never exercised, and no test covers redirects or non-`SpendError` exceptions (finding 6).
- `_pages.tco_page` puts the address unescaped in HTML; real t.co pages escape `&` — only the lnkd case tests unescaping (the code handles both, so not a defect).

## Checked and fine
- Dedup across pages by `post_id`; cursor-repeat and nothing-new stop conditions prevent infinite loops (bounded by distinct posts).
- `raw_ref` is the 0-based paged-call index, consistent with the docstring.
- Transport failure on page 1 → `unavailable`, page ≥2 → `partial` with a gap naming the page (for `ProviderTransportError`).
- Retweet with `retweeted_tweet`: own text emptied, full original in `shared` with its own author/URL; quote tweet keeps own words and quoted post separately; `reply_to_id` kept.
- Quote full-read: replaces only when the fetched text is at least as long; failure marks `text_may_be_cut`; cost added to history.
- `_x_length` weighting for wide characters; `_best_mp4` operator precedence is correct.
- `_bare` strips LinkedIn `?miniProfileUrn` tracking from author URLs.
- Short-link regex cannot be tricked into other hosts (`t.co.evil.com`, `notlnkd.in` don't match); results only include links that resolved to http(s); unique links opened once; pool size bounded at 8.
- Thread safety: `ProviderCaller` totals are locked and the hop's `BufferedLedger`/`BufferedRawSink` are lock-guarded; the `known` dict is mutated only on the calling thread.
- `treg_call`: token sent only in a header (masked), cost from `X-Treg-Cost-Micro`, 5xx → `ProviderTransportError`.
- Dates: X `%a %b %d … %z %Y`, ISO with `Z`, naive TikHub company dates assumed UTC, epoch ints; failures → `None`, not a crash.
