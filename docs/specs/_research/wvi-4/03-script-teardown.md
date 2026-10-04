# WVI-4 / 03 - Client-side script teardown of person-level visitor ID vendors

Date: 2026-10-03. Method: read-only. Only public JavaScript files and public pages were fetched with
`curl` (normal GET, no forms submitted, no sign-ups). Obfuscated code was pretty-printed with
`js-beautify` and, for RB2B, statically de-obfuscated with a small Node script that evaluates only the
string-array decoder (the payload itself was never executed). Raw files are in
`/private/tmp/claude-501/wvi4-scripts/` (scratch, not committed).

Evidence labels:
- **[FETCHED]** seen directly in a downloaded script (file name given).
- **[FETCHED-3P]** seen in a public third-party dataset (DuckDuckGo `tracker-radar` JSON on GitHub) or a
  public repo that embeds the vendor snippet.
- **[INFERRED]** our reading of what the code implies, or what must happen server-side.
- **[NOT FOUND]** we could not obtain the script.

Third-party API keys that appear in vendor bundles (for example an ip-api key in RB2B, Firebase/Giphy keys
in Warmly) are deliberately not reproduced here.

---

## 0. Scripts obtained

| Vendor | Script URL fetched | Status |
|---|---|---|
| RB2B | `https://ddwl4m2hdecbv.cloudfront.net/b/<ACCOUNT>/<ACCOUNT>.js.gz` (two accounts: rb2b.com and retention.com configs, found inline on rb2b.com) | [FETCHED] `rb2b_1.raw`, `rb2b_2.raw` |
| Warmly | `https://opps-widget.getwarmly.com/warmly.js` then `.../widget-CoznTser.js` (440 KB bundle) | [FETCHED] `warmly.js`, `warmly_widget.js` |
| Vector | `https://cdn.vector.co/pixel.js` (232 KB) | [FETCHED] `vector_pixel.js` |
| Leadpipe | `https://leadpipe.aws53.cloud/p/<pixel-uuid>.js` then `https://cdn.pixel.leadpipe.com/pixels/<id>/p.js` | [FETCHED] `lp_*.js`, `leadpipe_p.js` |
| AudienceLab | `https://cdn.v3.identitypxl.app/pixels/<id>/p.js` (V3); legacy `cdn.audiencelab.io/pixel_V2.js` no longer resolves | [FETCHED] `audiencelab_v3.js` |
| Customers.ai (X-Ray) | `https://mm-uxrv.com/js/mm_<uuid>-<n>.js` (5 customer builds) | [FETCHED] `cai_mm_*.js`, `customersai_mm.js` |
| Koala | `https://cdn.getkoala.com/v1/<pk>/sdk.js` returned HTTP 429 (Cloudflare rate limit) every time; we used the public npm source `@getkoala/browser@1.29.0` (`src/analytics/*.ts`) | [FETCHED] npm source; CDN bundle [NOT FOUND] |
| Clearbit Reveal / HubSpot | `https://tag.clearbitscripts.com/v1/<pk>/tags.js`, `https://x.clearbitjs.com/v2/<pk>/tracking.min.js`; HubSpot `js.hs-scripts.com/<portal>.js`, `js.hs-analytics.net/analytics/.../<portal>.js`, `js.hscollectedforms.net/collectedforms.js` | [FETCHED] |
| Apollo | `https://assets.apollo.io/micro/website-tracker/tracker.iife.js` (also `app.apollo.io/listener/dwn_profiling.js` on apollo.io itself) | [FETCHED] |
| Leadfeeder / Dealfront | `https://sc.lfeeder.com/lftracker_v1_<id>.js` (dealfront.com and leadfeeder.com share the same site build) | [FETCHED] `leadfeeder.js` |
| Snitcher | `https://cdn.snitcher.com/releases/latest/radar.min.js` | [FETCHED] `snitcher_radar.js` |
| Opensend | `https://cdn.aggle.net/oir/oir.min.js` (byte-identical to `s.opensend.com/os.min.js`) | [FETCHED] |
| Userled | `https://sdk.userledclient.io?appId=<id>&snippetVersion=4.0.0` (found inside Hootsuite's public GTM container) | [FETCHED] `userled_sdk.js` |
| Ploy | No Ploy customer tag located. ploy.ai itself runs Snitcher Radar under namespace `ployTwo` plus `@mesh-interactive/mesh-sdk` | [NOT FOUND] for Ploy's own tag |
| Retention.com | No product pixel on retention.com (site is a Lovable build with Tinybird `/~flock.js` analytics). An RB2B build configured for `retention.com` exists | [NOT FOUND] for Retention's consumer pixel |
| Identity Matrix | DDG lists `app.identitymatrix.ai/trackingScript.js`, but `app.identitymatrix.ai` no longer resolves and the marketing site returns a Webflow 404 | [NOT FOUND] |
| Primis | `live.primis.tech/live/liveView.php` returned an empty body to curl; its Prebid build `live.primis.tech/content/prebid/prebidVid.10.23.27.min.js` was fetched | [FETCHED] partial |

---

## 1. Per-vendor findings

### 1.1 RB2B (the clearest picture of the whole industry)

Script is obfuscator.io output with a rotated string array, base64-encoded endpoint URLs, and a
config object frozen at the top. After de-obfuscation (`rb2b_1.deob.js`):

**Config** [FETCHED]: `label` (account id), `domains` allow-list, `geoFence: true` (US only),
`companyCollection: true`, `apiGateway: "9xgnrndqve"`, `captureExternalCookie`, `initDelay: 3000`,
`sessionDuration: 6000`.

**Gates before anything fires** [FETCHED]:
- Script must be served from one of three origins (S3 `b2bjsstore` path-style, S3 virtual-host style,
  or `ddwl4m2hdecbv.cloudfront.net/b/`), checked by comparing `btoa(currentScript.src)` prefixes.
- Not in an iframe, cookies enabled, not a bot (long UA blocklist plus `navigator.webdriver`,
  `screen.width === 0`, `callPhantom`).
- Consent: reads CookieYes (`cookieyes-consent`, `cookieyes-advertisement`) only.
- Geo/proxy: client-side call to `https://pro.ip-api.com/json?key=…&fields=proxy,hosting,isp,lat,long,zip,city,region,status,country,timezone,regionName,countryCode`. Result cached 20 days in `_reb2bgeo`. If `proxy` or `hosting` is true the person-ID calls are skipped; person resolution only when `countryCode === 'US'`.

**Three parallel third-party identity lookups** (`collect()` runs `fxf`, `td`, `li` with
`Promise.allSettled`, 3 s timeout each) [FETCHED]:

| Key | Call | Response field used | Stored as |
|---|---|---|---|
| `fxf` | `fetch("https://a.usbrowserspeed.com/cs?pid=3f6274…", {credentials:'include'})` | `md5_lower_case` | `_reb2bfxf`, 30 d |
| `td` | `fetch("https://alocdn.com/c/vn3d8u2u/a/xtarget/p.json", {credentials:'include'})` | `md5_email` | `_reb2btd`, 30 d |
| `li` | loads `https://b-code.liadm.com/lc2.js` with `liQ.push({config:{identityResolutionConfig:{publisherId:72731}}})`, then `liQ.resolve(cb, err, {qf: proxy?0.9:0.3, resolve:['md5','sha2']})` | `md5`, `sha2` | `_reb2bli`, `_reb2bsha`, 30 d |

- `alocdn.com` is owned by **TowerData (now AtData)** per DuckDuckGo tracker-radar [FETCHED-3P]; hence the
  key name `td`. TowerData is an email-intelligence company (ex-Rapleaf).
- `b-code.liadm.com` is **LiveIntent**. `publisherId: 72731` is RB2B's LiveIntent account. `qf` is
  LiveIntent's quality/confidence floor; RB2B lowers it to 0.3 normally and raises it to 0.9 for proxy IPs.
- `usbrowserspeed.com` has no declared owner in tracker-radar, is on about 1,048 sites, and exposes
  `/cs`, `/lds`, `/ncs` endpoints [FETCHED-3P]. Warmly's bundle names it **"FXF"** in its integrations
  table (`INTEGRATIONS.FXF.WEBHOOK`) [FETCHED]. Its `/cs` call accepts a redirect URL containing
  macros `${HEM_SHA256_LOWERCASE}` and `${UP_ID}` (seen in Warmly and Customers.ai) [FETCHED]. The real
  operator is not identifiable from client code [INFERRED: a pseudonymous identity-graph vendor that
  sells a third-party-cookie to hashed-email lookup; registered via a privacy proxy].

All three are **third-party-cookie reads**: `credentials:'include'` means the browser sends that vendor's
own cookie, and the vendor answers with the hashed email it previously bound to that cookie somewhere
else on the web.

**First-party signals** [FETCHED]:
- `ec_b2b=<32-hex>` URL param, stored as `_reb2bec` (360 d). This is an md5 of an email placed in links
  RB2B controls (its own outbound email) [INFERRED].
- HubSpot: when `utm_medium=email&utm_source=hs_email` is present it copies `hubspotutk` into `_reb2butk`
  (365 d); it also always grabs `hubspotutk` if present.
- Meta: reads `_fbp`, `_fbc`.
- Optional `captureExternalCookie`: read any named first-party cookie as `external_id`.
- `reb2b.assignIdentity(id)` public API, stored `_reb2beid`.
- Referrer (`_reb2bref`, 30 d), `document.title`, `location.href`.
- Own ids: `_reb2buid` (UUID, 360 d, cookie + localStorage), `_reb2bsessionID` (30 min).
- No canvas/WebGL/audio/font fingerprinting, no form listeners.

**Cookie hygiene trick** [FETCHED]: every identity cookie value is `btoa(value)` with the account label
spliced in at a per-key offset (`set(name, value, ttl, offset)`), so a naive reader of
`document.cookie` cannot see the md5. Cookies are `secure; samesite=strict; domain=<eTLD+1>`
(first-party, set by script).

**Beacon** [FETCHED]: `POST https://9xgnrndqve.execute-api.us-west-2.amazonaws.com/b2b`, body is
`btoa(JSON)` of `{label, type:'collect', account_data:{rb2b_md5, li_md5, li_sha256, td_md5, fxf_md5},
extra_data:{fbp, fbc, hs_hubspotutk, external_id, referrer, last_referrer, title, url, session_id,
guid, script_url, geo, options}}`. Sent only if a hashed email was obtained and geo is US, or if
`companyCollection` is on and the IP is not a proxy (company-level fallback).

**Verdict** [INFERRED]: RB2B's person ID is a client-side waterfall of three bought hashed-email lookups
(LiveIntent, TowerData, "FXF"), plus first-party ESP click ids, joined server-side to its own
md5-email to LinkedIn-profile graph. IP is used client-side only as a US/proxy gate.

### 1.2 Vector (vector.co)

[FETCHED `vector_pixel.js`, 12k lines pretty]
- Bundles a **white-labelled LiveIntent LiveConnect SDK** (`distributorId: "did-006l"`, version string
  `v3.17.0`). LiveIntent's collector endpoints are proxied through Vector's own domain:
  `api.vector.co/pixel/phoenix/rp`, `/phoenix/rpr`, `/phoenix/sync-container`, `/phoenix/idex`,
  plus direct `https://idx.liadm.com/nonId`.
- LiveConnect reads a list of **partner first-party cookies** from the page and ships them for
  resolution: `identifiersToResolve: "_sharedid, dsq__s, trc_cookie_storage, gup_anonid, _li_uuid, hid,
  _parrable_id, tmguid, ajs_user_id, globalTI_SID, muuid, dsq__u, dtm_token, _shopify_y, _pubcid,
  IXWRAPPERLiveIntentIp, s_vi, _fbp, _aalyticsuid, s_ecid"`.
- LiveConnect contains an email regex that finds raw or URL-encoded emails in strings (URL, page context)
  and replaces them with md5/sha1/sha256 hashes (`stringWithoutRawEmails`, `hashesFromOriginalString`).
  It also has `id5` collection and a cookie-based "decisions" store (`li_did`).
- **"FXF" cookie sync**: `script.src = "https://a.usbrowserspeed.com/cs?pid=b910e4…&puid=<pixelId>|<visitorId>"`.
- **Form sniffing**: a `MutationObserver` attaches a `submit` listener to every `<form>` (including ones
  added later), reads `input[type=email]`, `input[name*=email]`, `first_name`, `last_name` etc. and posts
  them as `data_source:"form_listener"`. Separate HubSpot form capture (`normalizeHubspotIdentifyData`)
  and Drift listeners. `formListeningState` defaults to `"us_only"`.
- "Cerebro" waterfall: `POST /pixel/<id>/visitor/<vid>/cerebro` with `externalId`, `sha256` (from
  LiveIntent), `hubspotutk`, `partnerId`. Settings flags `forceIdentityWaterfall`, `useCerebroWaterfall`,
  `nonUsVisitorsMode: "dont_reveal"`, `nonUsIpCompanyLookupEnabled`.
- Other endpoints: `/pixel/ip-info`, `/pixel/<id>/settings`, `/pixel/<id>/visitor-activity`,
  `/visitor/<vid>/utk-refresh`, `/visitor/<vid>/consent`, `/pixel/li`.
- URL params: `v_e*`, `v_t_*` (Vector-encoded link identity), `v_x_f_all` (feature flags).
- Cookie `vector_visitor_id` (`SameSite=None; Secure; domain=.<eTLD+1>`).
- No canvas/WebGL fingerprinting of its own.

### 1.3 Warmly

[FETCHED `warmly_widget.js`]
Warmly is an **orchestrator of other vendors' pixels**. On session creation the server returns a config
and the widget injects, per customer:
- RB2B (`rb2bScriptId`, or an "RB2B OEM API" variant `rb2bOemApiScriptId`, detected by
  `script[src*="ddwl4m2hdecbv.cloudfront.net"]`),
- Vector (`cdn.vector.co/pixel.js`, then `vector.load(orgId); vector.identify(sessionId)`),
- LiveIntent (`https://d-code.liadm.com/did-008f.min.js`, `liQd_did_008f.resolve`),
- "FXF": `https://a.usbrowserspeed.com/cs?pid=4dd5c5…&puid=<session>&r=<warmly>/v1/integrations/fxf/webhook/…?hem=${HEM_SHA256_LOWERCASE}&up_id=${UP_ID}&puid=<session>`.

Its own integrations table lists `RB2B.REGISTER/WEBHOOK`, `LIVE_INTENT.CAPTURE`, `VECTOR.REGISTER/WEBHOOK`,
`FXF.WEBHOOK` on `data.getwarmly.com`.

**Form sniffing** [FETCHED]: listens to `change` on every `input, select, textarea` (password fields
excluded), in the page and in same-origin iframes, plus a MutationObserver for new fields, and sends
`{type, name, value, class, elementId, page}` to its session server via `sessions.formFill`. This fires on
field change, before any submit.

Other: `localStorage.warmly_fingerprint` is just a random UUID (header `x-warmly-fingerprint`), not a
browser fingerprint; rrweb session recording preload; HubSpot `hubspotutk` state. warmly.ai itself also
loads an Upvert personalization pixel (reads `up_email` URL param) and a `pixel_kwargs` tag at
`icexyz.com/whm/assets/pixel.js` whose domain no longer resolves [NOT FOUND].

### 1.4 Leadpipe and AudienceLab (both are Delivr white-labels)

[FETCHED] The Leadpipe loader carries `{"wl":"<uuid>","wl_slug":"leadpipe"}` and loads the SDK from
`cdn.pixel.leadpipe.com/pixels/<id>/p.js`, whose first line is `"_delivrPixelLoaded_"+<id>`. The
AudienceLab V3 pixel at `cdn.v3.identitypxl.app/pixels/<id>/p.js` is **byte-identical** to Leadpipe's
after normalising UUIDs (`cmp` exit 0), and both hostnames CNAME to the same CloudFront distribution
`d2lu4chfijls8x.cloudfront.net`. Both post to `https://api.sitelytics.tech/pixel/core/api/send-event`.

Leadpipe loader [FETCHED]:
- `https://company.leadpipe.com/a.js?i=<b64 json>` (company/IP lookup),
- the Delivr SDK above,
- `https://cdn.rktad.com/sync/resolve?i=<pixel>&u=<b64 {pppid}>` (an ID-sync/resolve script; we did not
  request it),
- sends `Intl` timezone and `navigator.language`.

Delivr SDK [FETCHED]:
- `trackAllFormSubmissions`: document-level `submit` listener, `new FormData(form)`, masks fields whose
  name contains password/credit/ssn/card, truncates values at 100 chars, posts the **whole form** as
  `form_submission`. Events also include click, copy, scroll_depth, exit_intent, file_download, video_*,
  user_idle.
- All posts use `credentials:"include"`, so sitelytics.tech keeps its own third-party cookie.
- **Server-driven cookie sync**: the response may contain `redirect_to`, `second_redirect_to`,
  `third_redirect_to`; each is loaded as `new Image().src` (classic sync chain chosen server-side).
- **Sovrn hashed-email lookup**: if the response has `cookie_id`, `inject444Script` loads
  `//pxdrop.lijit.com/1/e/t.dhj?...pubid=delivr&puu=<cookie_id>` (lijit.com = **Sovrn**) with a callback
  that receives `md5_hem`, `sha1_hem`, `sha256_hem` and posts them to `/hem/enrichment` with partner id
  `pi:"444"`.

### 1.5 Customers.ai (X-Ray)

[FETCHED `cai_mm_*.js`, five customer builds]
- Endpoints: `https://a.aisiteanalytics.com/x/*` and `https://h2.aisiteanalytics.com/x/*`
  (`saxi`, `sax`, `saxv`, `saxe`, `y2`, `t_sa`, `sar`, `klc`, `t`), `api.mobilemonkey.com`, and a
  **first-party CNAME per customer**, e.g. `vnacg.anthros.com` which resolves (dig) to
  `customers.xray-superpixel.com`, loaded as `<cname>/load` (cookie set in the customer's own domain).
- LiveIntent: `https://d-code.liadm.com/did-0014.min.js`, `resolve:["md5","sha2","nonId"]`, tried at
  `qf` 0.8 then 0.1.
- "FXF": `a.usbrowserspeed.com/cs?pid=fdd086…&r=<aisiteanalytics>/x/sag?...gid=${HEM_SHA256_LOWERCASE}:${UP_ID}`.
- **Klaviyo exchange**: reads `_kx` URL param (Klaviyo click token) or the `$exchange_id` inside the
  `__kla_id` cookie and posts it to `/x/klc` [this turns the merchant's own Klaviyo into an email resolver].
- Meta: reads `_fbc`, `_fbp`, reconstructs `_fbc` from `fbclid`. Shopify: `_shopify_y`, Shopify checkout
  events (`checkout_contact_info_submitted`, `payment_info_submitted`) carry the email.
- **Form sniffing**: capture-phase `submit` and `click` listeners on a base64-obfuscated list of form
  selectors (decoded: `form#customer_login`, `form#create_customer`, `form.klaviyo-form`, `.hbspt-form form`,
  `form.hs-form`, `div.w-form form[id^='wf-form-']`, `form[action="/account/login"]`, newsletter and
  contact forms, Gravity/Elementor/Infusion/Nextiva). Walks shadow roots and iframes; skips
  passwords, card numbers, OTP fields; posts `{id, name, value, title, label}`. Also listens for
  `postMessage` from popup tools (`CollectedEmailEvent`, `POPUP_FORM_SUBMIT`).
- localStorage: `MobileMonkeyVisitCount`, `__xray_v/c/n`, `__xray_cid`, `__xray_bsid`, `__cai_sts`,
  `__cai_klc_v`; cookie `mmuid` [FETCHED-3P DDG].

### 1.6 Apollo website tracker

[FETCHED `apollo_tracker.js`, 4.8 KB, unminified enough to read]
- Endpoints on a separate non-apollo domain: `https://aplo-evnt.com/api/v1/intent_pixel/track_request`
  and `/can_track_visitor`.
- localStorage `apolloAnonId` (UUID), `<appId>_eventQueue`, `<appId>_canTrack` (24 h),
  `liveIntentData` (24 h).
- If the server says `can_track`, loads `https://d-code.liadm.com/did-0091.min.js` and calls
  `liQd_did_0091.resolve(..., {qf:"0.1", resolve:["md5","sha2","nonId"]})`. Every page_visit event
  carries `email_md5` and `email_sha2` from LiveIntent.
- Reads only utm_* and referrer. No form listener, no fingerprinting.
- Aside: apollo.io's own marketing site loads `app.apollo.io/listener/dwn_profiling.js` (namespace
  `dwn`, 190 KB), a fraud/bot device profiler with canvas, WebGL, OfflineAudioContext, UA-CH high
  entropy values. It is not part of the customer tracker.

### 1.7 Koala

[FETCHED npm `@getkoala/browser@1.29.0` source; CDN bundle 429]
- Host `https://api.getkoala.com` (beacons + websocket profile channel).
- Cookies/localStorage `ko_id` (anon, 365 d), `ko_e` (email, 365 d), `ko_sid` (1 d).
- **Form capture on submit** (capture phase, document and same-origin iframes), excludes a
  sensitive-name list (password, card, cvv, ssn, token, routing, account, ...), extracts `email`,
  first/last name, phone, company, title as traits.
- URL params: `ko_e` / `ko_email` (plain email), `utm_id` decoded as base64 email, `ko_trait_*`.
- Reads `hubspotutk` and posts it to `/web/projects/<p>/utk`; plugins listen to postMessage from
  Calendly, Drift, Intercom, Qualified, HubSpot forms, Navattic, Storylane, Arcade.
- No third-party identity script, no fingerprinting in the SDK source.

### 1.8 Clearbit (tags.js, now HubSpot Breeze Intelligence)

[FETCHED `clearbit_tags.js`, `clearbit_tracking.js`]
- `reveal.clearbit.com/v1/companies/reveal?authorization=pk_…&variable=reveal` (JSONP company-from-IP),
  `x.clearbitjs.com/v2/<pk>/tracking.min.js` (Segment analytics.js fork), `destinations.min.js`,
  `forms.js`.
- Cookies `cb_anonymous_id`, `cb_user_id`, `cb_group_id`, plus `cb_xid` / `cb_xid_fd` / `cb_xid_ts`:
  cross-domain id obtained by calling `https://<each customer domain>/v1/id/<writeKey>` (shares one id
  across the customer's own properties, not across the web).
- **Auto-identify**: wraps form `submit`, wraps `window.fetch` and regex-scans request bodies for
  `"email":"…"` or any `"x@y.z"`, wraps Segment/Amplitude/Heap/Mixpanel `identify`. Only fires on
  "valuable" paths (`login, register, signup, contact, pricing, request, ...`) or form classes
  (`hs-form`, `wpforms-form`, `elementor-form`, `jotform-form`) or actions posting to `formspree`,
  `list-manage` (Mailchimp), `sendgrid`, `activehosted`, etc. Free-mail domains are rejected
  (`looksLikeBusinessEmail`).

### 1.9 HubSpot tracking code

[FETCHED `hs_analytics.js`, `hs_collectedforms.js`]
- Bundles open-source **FingerprintJS** (comment `https://fpjs.dev/pro`, components incl. canvas,
  webGlBasics, audioBaseLatency, fonts, math, applePay, privateClickMeasurement) for the `__hsfp` value.
- Cookies `__hstc`, `hubspotutk`, `__hssc`, `__hssrc`; cross-domain link decoration with `__hstc`,
  `__hssc`, `__hsfp`; reads `__hs_email` URL param and calls `identify({email})`.
- `collectedforms.js` binds `submit` on non-HubSpot forms (opt-out class `hs-do-not-collect`) and posts
  to `collected-forms/submit/form`.
- Company reveal (Breeze/Clearbit) is server-side; nothing person-level from third parties in the client.

### 1.10 Leadfeeder / Dealfront

[FETCHED `leadfeeder.js`]
- Beacons `https://tr-rc.lfeeder.com` (+ `tr2.lfeeder.com` dual stack), company API
  `https://cs.lf-discover.com/companies/?api_key=…`.
- Cookie/localStorage `_lfa` (365 d), `_lfa_consent`, `__lfaCmClientId`.
- Form tracking (`formTrackingMode: configured_fields | all_but_excluded`), document `submit` plus
  iframe `submit`, tags a field as `suggestedLfProperty:"email"` if the value looks like an email,
  excludes password/hidden/card-like values. YouTube/Vimeo engagement.
- No third-party identity calls. Company-level IP matching is server-side.

### 1.11 Snitcher (Radar)

[FETCHED `snitcher_radar.js`]
- Endpoints `radar.snitcher.com` (api), `cdn.snitcher.com`, a "spotter" company-lookup URL.
- **Full browser fingerprint**, hashed per component group (`sh`, `sg`, `de`, `rs`, `ped`): canvas
  (a fixed test string with an emoji drawn and hashed), WebGL `UNMASKED_VENDOR/RENDERER`, font probing across ~40
  families, OfflineAudioContext oscillator hash, screen/DPR/timezone, plugins, UA, storage support.
- Form tracker on `focusin`/`change`/`submit` (document and iframes) building `traits.email`,
  `firstName` etc.; inline page code stashes `sn_email=` / `sn_eid=` URL params.
- Reads first-party cookies of other tools: `_ga`/`_ga_*` (GA4 session), `hubspotutk`, `__hssc`,
  `intercom-id-*`, `intercom-session-*`.
- localStorage prefix `radar_sn_`; TLD probe cookie `__sn_tld_probe`.
- No third-party ID sync in client. Fingerprint is used for cookieless session continuity
  [INFERRED], person ID via form/email params plus server-side IP.

### 1.12 Opensend (aggle.net)

[FETCHED `opensend_oir.js`]
- Default host `oirt.aggle.net` but supports a **`brandedLinkDomain`** (customer CNAME) to make the
  cookie first-party. Endpoints `/up`, `/evt`, `/swe`, `/echo` (fetched with `credentials:"include"`,
  i.e. reads aggle's third-party cookie), and DDG also shows `/tks`, `/csc` [FETCHED-3P].
- **Server-directed tag injection**: the response contains `{tag: "iframe"|"img"|"script", attrs}` and the
  SDK creates hidden 1x1 iframes/images/scripts. This is a server-controlled cookie-sync network: the
  partner list is not in the client code.
- Once the server resolves an email it **writes it into the merchant's ESP in the browser**:
  `klaviyo.identify({$email, oir_csync})`, `_Sendlane` identify, Yotpo `smsbump.identify`, Bloomreach
  `exponea.identify`.
- Cookie `_oirtrk`.

### 1.13 Userled

[FETCHED `userled_sdk.js`]
- Loads **FingerprintJS Pro** (commercial) through a proxy: `endpoint: "https://identity.userled.io"`,
  `scriptUrlPattern: "https://identity.userled.io/web/v<version>/<apiKey>/loader_v<loaderVersion>.js"`,
  stores the visitorId in a 7-day cookie.
- Loads **Vector** (`cdn.vector.co/pixel.js`) for person resolution; DDG shows
  `userled.io/api/vector/id/<app>` calls on hootsuite.com, elastic.co, synthesia.io [FETCHED-3P].
- Reads `hubspotutk` and Marketo `_mkto_trk`; URL params `ul_e`, `ul_fn`, `ul_ln`, `ul_li_acc_id`,
  `ul_li_acc_name`, `a`, `c` (personalised outbound links).

### 1.14 Ploy

Customer tag [NOT FOUND]. Ploy's own site loads Snitcher Radar under namespace `ployTwo` and
`@mesh-interactive/mesh-sdk`. The Mesh SDK (withmesh.com) [FETCHED] itself orchestrates RB2B and Vector
(it removes and re-injects their snippets), reads `m_email` URL param, captures form fills, carries a
`fullContactKey`, and fetches the visitor IP via `api.ipify.org`. Ploy's public privacy page says it
resolves only US visitors present in "an opted-in partner network" with no SDK on devices
[FETCHED page text] which is consistent with an IP plus third-party-graph server-side model.

### 1.15 Primis

Primis (`primis.tech`, owner McCann per DDG) is a video ad SSP, not a visitor-ID vendor. Its player sets
a third-party `csuuid` cookie on `.primis.tech` (25 days, seen in response headers) and its Prebid build
includes the standard ad-tech ID modules: `id5Id`, `identityLink` (LiveRamp ATS), `uid2`,
`liveIntentId`, `lotamePanoramaId`, `criteo`, `sharedId`/`pubCommonId`, `unifiedId`/`tdid` (The Trade
Desk), `connectId` (Yahoo) [FETCHED]. Useful as the contrast: this is how ad-tech syncs ids, and none of
the B2B visitor-ID vendors above use these modules except via LiveIntent.

---

## 2. Technique matrix

Legend: Y = present in client code, - = not seen, P = present via a partner script it injects.

| Vendor | 1P id cookie | Form sniffing | Email/HEM from URL | ESP / CRM cookie reuse | LiveIntent | usbrowserspeed ("FXF") | TowerData | Other 3P sync | Browser fingerprint | Client IP/geo call |
|---|---|---|---|---|---|---|---|---|---|---|
| RB2B | Y `_reb2buid` | - | Y `ec_b2b` md5 | Y hubspotutk, _fbp/_fbc | Y pub 72731 | Y | Y alocdn | - | - (bot checks only) | Y ip-api.com |
| Vector | Y `vector_visitor_id` | Y all forms + HubSpot/Drift | Y `v_e*`, LiveConnect email hashing | Y hubspotutk, partner cookies list | Y did-006l (proxied) | Y | - | Y ID5 collection | - | Y `/pixel/ip-info` |
| Warmly | Y session | Y every input `change` | - | Y hubspotutk | P did-008f | P | - | P RB2B, Vector | - (UUID only) | - |
| Leadpipe / AudienceLab (Delivr) | server 3P cookie | Y whole form on submit | - | - | - | - | - | Y Sovrn lijit, server redirects, rktad | - | Y company.leadpipe.com |
| Customers.ai | Y via CNAME | Y selector list + popups | Y `_kx` | Y Klaviyo `__kla_id`, _fbp/_fbc, _shopify_y | Y did-0014 | Y | - | - | - | - |
| Apollo | Y `apolloAnonId` | - | - | - | Y did-0091 | - | - | - | - | - |
| Koala | Y `ko_id` | Y on submit | Y `ko_e`, `utm_id` b64 | Y hubspotutk | - | - | - | - | - | - |
| Clearbit | Y `cb_*` | Y submit + fetch body scan | - | Y wraps Segment/Amplitude/Heap/Mixpanel identify | - | - | - | - | - | Y reveal (company) |
| HubSpot | Y `__hstc`, `hubspotutk` | Y collected forms | Y `__hs_email` | own | - | - | - | - | Y FingerprintJS OSS | - |
| Leadfeeder | Y `_lfa` | Y configured/all | - | - | - | - | - | - | - | Y lf-discover (company) |
| Snitcher | Y `radar_sn_*` | Y focus/change/submit | Y `sn_email`, `sn_eid` | Y _ga, hubspotutk, intercom | - | - | - | - | **Y canvas, WebGL, fonts, audio** | - |
| Opensend | Y `_oirtrk` | - | - | Y writes to Klaviyo/Sendlane/Yotpo/Bloomreach | - | - | - | **Y server-injected iframes/img** | - | - |
| Userled | Y | - | Y `ul_e` etc. | Y hubspotutk, _mkto_trk | P via Vector | P via Vector | - | - | **Y FingerprintJS Pro** | - |

---

## 3. Synthesis

**What is actually in the browser.** Across 13 readable scripts, person-level identity never comes from
clever client-side computation. It comes from four mechanisms, in this order of importance:

1. **Bought third-party-cookie to hashed-email lookups** [FETCHED]. LiveIntent is the backbone: RB2B,
   Vector, Warmly, Customers.ai and Apollo each hold their own LiveIntent distributor or publisher id
   (`did-006l`, `did-008f`, `did-0014`, `did-0091`, pub `72731`) and call `resolve(['md5','sha2'])`.
   The same pseudonymous `usbrowserspeed.com/cs` "FXF" endpoint appears in RB2B, Vector, Warmly and
   Customers.ai, returning `${HEM_SHA256_LOWERCASE}` and `${UP_ID}` via redirect macros. TowerData
   (`alocdn.com`) in RB2B and Sovrn (`lijit.com`, `md5/sha1/sha256_hem`) in the Delivr SDK are the
   other two. These are the "upstream graph": email-newsletter and publisher networks that observed the
   same browser cookie when the person was logged in or clicked an email elsewhere. Every call is
   `credentials:'include'`, so it **depends on third-party cookies** (Chrome still allows them; Safari
   ITP and Firefox ETP block most), which is why every vendor gates on US traffic and why match rates
   quoted publicly are in the 15 to 40 percent range [INFERRED].
2. **First-party form and identity capture** [FETCHED]. Vector, Warmly, Customers.ai, the Delivr SDK,
   Koala, Clearbit, HubSpot, Leadfeeder and Snitcher all listen to forms. The aggressive end is Warmly
   (every field `change`, before submit), Delivr (entire `FormData` on any submit) and Clearbit (wraps
   `window.fetch` and regex-scans request bodies for emails). Captured emails become the vendor's own
   cookie-to-email binding, which they can reuse when the same browser shows up on another customer's
   site [INFERRED: a co-op effect, explicitly so for vendors whose cookie lives on their own domain
   such as sitelytics.tech or aggle.net].
3. **ESP and CRM click identifiers** [FETCHED]: `hubspotutk` / `hs_email` (RB2B, Vector, Koala, Snitcher,
   Userled), Klaviyo `_kx` and `__kla_id` (Customers.ai), Meta `_fbp`/`_fbc`, Shopify `_shopify_y`,
   Marketo `_mkto_trk`, and vendor-specific email params (`ec_b2b`, `ko_e`, `utm_id`, `sn_email`, `ul_e`,
   `v_e`, `m_email`, `__hs_email`). These bind a visit to an email the customer already knows.
4. **IP** is used client-side only as a gate (RB2B calls ip-api for US/proxy/hosting; Vector has
   `/pixel/ip-info`; Mesh calls ipify) and server-side for company reveal.

**What is not there.** Browser fingerprinting is rare and not the identity source: only Snitcher
(canvas, WebGL, fonts, audio), HubSpot (OSS FingerprintJS for `__hsfp`) and Userled (FingerprintJS Pro)
fingerprint, and none of them send the fingerprint to an identity partner. No vendor uses the ad-tech ID
modules (ID5, UID2, LiveRamp ATS, Lotame, 33across, Tapad) directly; they appear only in Primis's Prebid
build. Vector's bundled LiveConnect has an ID5 collector and reads `_pubcid`/`_sharedid`, which is the
only overlap.

**What must happen server-side** [INFERRED]:
- A join table **hashed email (md5/sha256) to person**: name, title, employer, LinkedIn URL, business
  email. The bought lookups only return a HEM; the vendor's value is the HEM-to-B2B-profile graph,
  built from data brokers and, for RB2B and Vector, a LinkedIn-profile match.
- A **waterfall and confidence policy**: several HEM sources per visit (RB2B sends up to five hashes:
  `rb2b_md5, li_md5, li_sha256, td_md5, fxf_md5`), agreement scoring, LiveIntent `qf` thresholds,
  US-only reveal, proxy and hosting exclusion.
- **IP to company** (reverse-IP / ISP-ASN / Wi-Fi graphs) as the fallback when no HEM resolves, used by
  every vendor and the only mechanism in Leadfeeder, Clearbit Reveal and HubSpot.
- **Server-controlled sync chains** (Delivr `redirect_to` x3, Opensend injected iframes/img) whose
  partner list is invisible in client code and can change without a script release.
- **Resale and OEM layering**: Warmly and Mesh inject RB2B and Vector; Userled uses Vector; Leadpipe and
  AudienceLab are byte-identical Delivr white-labels; RB2B ships a build configured for retention.com.
  The market is a few graph owners (LiveIntent, the "FXF" operator, TowerData, Sovrn, plus each vendor's
  own form co-op) resold through many brands.

**Implication for Clue** [INFERRED]: client code we would ship is simple (first-party id, form capture,
ESP click-id capture, optional LiveIntent or similar HEM resolve). The hard and costly part is (a) a
licensed HEM source, which today means a LiveIntent-style distributor contract or equivalent, and (b) the
HEM-to-B2B-person graph. Fingerprinting and IP alone will not produce person-level identity.
