# AI builders evict generated code from editors

> **Status (2026-10-09).** Research report behind decision D2. Its recommendation for the editor
> (a sandboxed frame per AI section) was **not adopted**: the founder chose the separate-domain
> editor (the whole Puck editor on its own domain, embedded in app.cluehq.ai as one frame). See
> `2026-10-08-puck-production-readiness-map.md` §5 and §9 and the plan's "D2" section. The research
> notes behind this report are in `research_notes/Code first site builder isolation/` (not committed).

Every AI site and app builder examined here runs model- or user-written frontend code on an origin that the logged-in editor does not share. That includes Claude artifacts, ChatGPT canvas, v0, Lovable, Bolt, Replit, Gemini Canvas, Framer, Figma Make, Canva Code and Retool, and the separate origin is almost always a registrable domain listed on the Public Suffix List (PSL). None of them documents running such code next to the editor session. They isolate one whole surface per app, artifact, project or render, not one per component, because the isolation unit follows whoever wrote the code. Sandboxes per element appear only where authors who distrust each other share one host page: Shopify checkout extensions, Wix editor widgets, MCP Apps views. CSP on these preview origins limits where data can go while still allowing inline scripts and `eval`. At publish time, vendors build inside sandboxes or microVMs and then serve the output as the customer's own site with little or no CSP. The public incidents so far have been broken authorization, phishing abuse and server-side rendering bugs, not escapes from an editor. The declarative camp (Google's A2UI, Vercel's json-render, Puck's own design mode) avoids executing model code at all, at the price of a component catalog that critics say makes every UI look alike. A Puck canvas is the outlier. Puck mounts components through `createPortal`, so an AI section that appears to sit "in the iframe" actually executes in the editor's own JavaScript realm, with the marketer's cookies, storage, same-origin APIs and top window. Neither an iframe `sandbox` attribute nor CSP contains it. AI-written sections are occasional and sit beside trusted sections, which makes the industry's whole-canvas pattern the expensive answer here. Giving each AI section its own opaque-origin `srcdoc` iframe with a `<meta>` CSP buys browser-enforced containment at a per-frame cost that stays small while N stays small. The no-network container already proven in the spike remains the boundary for server rendering and publishing.

## Every AI builder runs generated code on an origin the editor cannot reach

The products split on *what* executes generated code. Some use a microVM dev server (v0, Lovable, Replit). Bolt uses a WebAssembly Node runtime inside the user's own tab. Claude, ChatGPT and Google run plain browser JavaScript inside a sandboxed frame. They agree on *where* it executes: somewhere the editor's session cannot be reached from.

| Product | Where generated code executes while editing | Preview / canvas origin | Isolation unit |
|---|---|---|---|
| Claude artifacts | Viewer's browser, sandboxed iframe | `<uuid>.frame.claudeusercontent.com` ([Pluto Security](https://pluto.security/blog/inside-claude-artifacts-how-your-agent-publishes-to-the-web/)) | Per artifact |
| ChatGPT canvas / Apps SDK | Browser "sandbox environment"; app widgets on per-app subdomains of `web-sandbox.oaiusercontent.com` | ([OpenAI Help](https://help.openai.com/en/articles/9930697-what-is-the-canvas-feature-in-chatgpt-and-how-do-i-use-it)); ([sunpeak](https://sunpeak.ai/blogs/mcp-app-resource-metadata)) | Per app (widgets) |
| v0 | Per-chat Firecracker microVM running a Node dev server | `*.vusercontent.net`, `*.vercel.run` ([v0 docs](https://v0.app/docs/sandbox)) | Per chat |
| Lovable | Per-project dev server in a cloud sandbox (fly.io, then Modal) | `*.lovableproject.com`, `*.lovable.app` ([PSL PR #2379](https://github.com/publicsuffix/list/pull/2379)) | Per project |
| Bolt.new | User's tab, via WebContainers | `*.webcontainer-api.io` ([StackBlitz](https://blog.stackblitz.com/posts/introducing-webcontainers/)) | Per project |
| Replit | Server-side workspace | `*.replit.dev` ([Replit docs](https://docs.replit.com/core-concepts/workspace/app-setup/development-urls)) | Per Repl |
| Gemini Canvas, AI Studio | Browser, via SafeContentFrame | `<hash>.scf.usercontent.goog` ([Google Bug Hunters](https://bughunters.google.com/blog/beyond-sandbox-domains-rendering-untrusted-web-content-with-safecontentframe)) | Per render |
| Framer | One canvas realm shared by all code components | `project-<id>.framercanvas.com` ([Framer bootstrap](https://framer.com/bootstrap.0da2bc6975aa3b93b16494c73adf47371e93864c.js)) | Per project |
| Figma Make / code layers | Preview iframe | `*.figmaiframepreview.figma.site` ([Figma forum](https://forum.figma.com/report-a-problem-6/figma-make-couldn-t-load-make-error-figma-alpha-s3-us-west-2-amazonaws-com-shown-as-blocked-but-domain-is-reachable-57540)) | Per session |
| Canva Code | Own subdomain per artefact | `<id>.canvacode.com`, `<id>.canva-hosted-embed.com` ([PSL PR #2617](https://github.com/publicsuffix/list/pull/2617)) | Per artefact |
| Retool React apps | Own hostname per app; opaque-origin iframe on custom domains | `<org>--<app>.retool.app` ([PSL PR #3283](https://github.com/publicsuffix/list/pull/3283)) | Per app |
| Puck (default) | The host app's own window, via React portal | Same origin as the editor ([Puck docs](https://puckeditor.com/docs/integrating-puck/viewports)) | None |

Where vendors explain the separation, the reason given is the editor session and tenant cookies. Anthropic described artifacts as iframe sandboxes with full-site process isolation, built specifically to protect the main claude.ai session from malicious artifacts, plus strict CSPs limiting network access ([Simon Willison](https://www.simonwillison.net/2024/Aug/28/how-anthropic-built-artifacts)). Vercel's embedding guide for v0 is the most prescriptive. Generated previews execute untrusted code, so they must not be served from the host application's origin **or from any other origin on the same site**. The guide asks for a preview-only registrable domain, plus a proxy that strips `Cookie`, `Authorization` and `Set-Cookie` ([v0 docs](https://v0.app/docs/api/v2/guides/accessing-previews)).

PSL pull requests are where companies give their reasons in their own words:

- **Framer (2021):** moved its canvas to a user-content domain per project because the canvas displays and executes untrusted content ([PSL PR #1217](https://github.com/publicsuffix/list/pull/1217)).
- **Retool (2026):** isolates each AI-assisted React app separately, because SameSite cookies give no protection between apps on one site and one app can evict another's cookies ([PSL PR #3283](https://github.com/publicsuffix/list/pull/3283)).
- **Canva:** provisions each Canva Code artefact on its own subdomain, at **over 1 million monthly users** ([PSL PR #2617](https://github.com/publicsuffix/list/pull/2617)).

Listing a domain on the PSL makes each of its subdomains a separate site for cookies and storage ([publicsuffix.org](https://publicsuffix.org/learn/)). claudeusercontent.com, vusercontent.net, lovable.app, framercanvas.com, figma.site, csb.app and bolt.host are all listed. StackBlitz's webcontainer-api.io is not ([PSL](https://publicsuffix.org/list/public_suffix_list.dat)).

Google's public record shows which way the industry is moving. In 2012 Google moved risky content to `*.googleusercontent.com` after finding that **content sanitization was insufficient** against content-sniffing XSS ([Google Security Blog](https://security.googleblog.com/2012/08/content-hosting-for-modern-web.html)). It later documented that a shared sandbox domain does not isolate one user's content from another's ([web.dev](https://web.dev/articles/securely-hosting-user-data)). In 2025 it replaced those domains with SafeContentFrame. This client-side library loads each render into a fresh origin on the PSL-listed `usercontent.goog` through a static shim, and it now serves **over 50 products, including Gemini Canvas and AI Studio** ([Google Bug Hunters](https://bughunters.google.com/blog/beyond-sandbox-domains-rendering-untrusted-web-content-with-safecontentframe)). Two details from that post matter for any builder. First, Google partly abandoned null-origin iframes (`sandbox` without `allow-same-origin`) because of the breakages they caused. Second, it pays for an origin per render with lost caching, and offers opt-in modes that trade isolation for cache hits. An earlier scheme of semi-random subdomains could be brute-forced and produced a Google Drive vulnerability ([same](https://bughunters.google.com/blog/beyond-sandbox-domains-rendering-untrusted-web-content-with-safecontentframe)).

CSP on these origins constrains where data goes, not what code runs. The policy on `www.claudeusercontent.com` allows `'unsafe-inline'` and `'unsafe-eval'`. It confines script and connect sources to a short CDN allowlist, and images to self, data, blob and map tiles ([claudeusercontent.com](https://www.claudeusercontent.com/)). Pluto Security found the per-artifact frames tighter still: `connect-src 'self'` blocked fetch, XHR, WebSockets, image beacons and `sendBeacon`. Connector calls there are made by the parent page through a bridge that holds no token ([Pluto Security](https://pluto.security/blog/inside-claude-artifacts-how-your-agent-publishes-to-the-web/)). A ChatGPT canvas that tries to reach the network triggers a Deny/Allow prompt ([Eye Security](https://research.eye.security/?p=5181)), and Enterprise workspaces turn canvas network access off by default ([OpenAI Help](https://help.openai.com/en/articles/9930697-what-is-the-canvas-feature-in-chatgpt-and-how-do-i-use-it)). The MCP Apps specification requires hosts to build a default-deny CSP from the domains each app declares ([ext-apps spec](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/draft/apps.mdx)). In a talk, Alpic's CTO reported production failures and App Store rejections when declared domains were missing, partly because ChatGPT developer mode did not enforce the CSP ([AI Engineer talk](https://ai.engineer/talks/why-mcp-and-chatgpt-apps-use-double-iframes-frederic-barthelet-alpic)). The CSP3 draft itself warns that a policy can only limit exfiltration as an allowlist that includes `default-src` ([W3C CSP3](https://w3c.github.io/webappsec-csp/)). The `webrtc 'block'` directive that Anthropic sends is reportedly implemented by no major browser ([CentralCSP](https://next.centralcsp.com/en/docs/web-security/policies/content-security-policy/directives/webrtc)).

Click-to-select and inline editing work across these origin boundaries because each product plants a script *inside* the preview:

- **Lovable:** a Vite plugin tags generated JSX with stable IDs and maps DOM nodes to `file:line:column`. Edits are applied to a client-side AST and written back as diffed source plus HMR ([Lovable engineering](https://lovable.dev/blog/visual-edits)). The published tagger turns on only on the dev server ([lovable-tagger](https://cdn.jsdelivr.net/npm/lovable-tagger@1.3.5/dist/index.js)).
- **WebContainers:** a `setPreviewScript` API injects a script into every preview ([WebContainer API](https://webcontainers.io/api)).
- **Onlook:** injects a preload script into the project and talks to it over penpal with `allowedOrigins: ['*']` ([Onlook source](https://github.com/onlook-dev/onlook/blob/main/apps/web/client/src/app/project/%5Bid%5D/_components/canvas/frame/view.tsx)).

Edits are then written back in one of two ways. Lovable and Replit patch source deterministically, and Replit's simple edits cost no credits. v0 and Bolt serialise the edits and send them to the model ([v0 Design Mode](https://v0.app/docs/design-mode); [Bolt blog](https://bolt.new/blog/visual-edits)).

The costs are mostly engineering costs:

- **Webflow** measured about **4 ms per postMessage round trip and a ~10 ms baseline per API call** for its Designer extensions, and had to add a batching API because of it ([Webflow Part 2](https://webflow.com/blog/powering-webflow-apps-how-we-built-designer-apis-part-2)).
- **Lovable** called sandbox infrastructure its biggest pain point. Moving to Modal cut its orchestration code from about 15,000 to about 700 lines, and a promotional weekend peaked at about 20,000 concurrent sandboxes ([Modal case study](https://modal.com/blog/lovable-case-study)).
- **Anthropic** named a robust sandbox as the hardest part of building artifacts ([Simon Willison](https://www.simonwillison.net/2024/Aug/28/how-anthropic-built-artifacts)).

Most of that heavy infrastructure exists to run backends and npm installs, not to isolate rendering. Products that render only client-side code, such as Claude and ChatGPT, manage with one cross-origin sandboxed frame and a CSP.

## Builders isolate one surface per author, and frames per component stay rare and costly

Visual builders with custom code components follow the same coarse pattern:

- **Framer:** its bootstrap script rewrites the canvas address to `project-<id>.framercanvas.com`. Code components are ES modules from `framerusercontent.com`. No sandbox per component was found, and a crashing component is simply hidden ([Framer bootstrap](https://framer.com/bootstrap.0da2bc6975aa3b93b16494c73adf47371e93864c.js); [Framer Help](https://www.framer.com/help/articles/how-to-troubleshoot-a-code-component-issue/)).
- **Figma:** its code-layer toolchain (esbuild, plus Tailwind v4 with Lightning CSS) runs in a Web Worker. Figma has not said on which origin code layers render on the Sites canvas ([Figma blog](https://www.figma.com/blog/building-figmas-code-layers/)).
- **Webflow:** each code component gets its own Shadow DOM and React root, inside the page's own realm. That is style and state isolation. Webflow's own FAQ warns that libraries which modify `window` or `document` may conflict ([Webflow architecture](https://developers.webflow.com/code-components/component-architecture); [Webflow FAQs](https://developers.webflow.com/code-components/faqs)).
- **Builder.io and Plasmic:** they sidestep the question. Components are the customer's own code on the customer's own origin, framed cross-origin by the vendor's editor. Plasmic keeps a list of trusted hosts because its Studio JavaScript runs inside the customer's host page ([Plasmic docs](https://docs.plasmic.app/learn/app-hosting/)).

Sandboxes per element exist exactly where several authors who distrust each other share one page:

- **Wix** (late 2024): sandboxes third-party custom elements and widgets without `allow-same-origin`, in the editor and preview only. Live sites run them as ordinary web components ([Wix Dev](https://dev.wix.com/docs/build-apps/develop-your-app/extensions/site-extensions/handle-sandboxing-in-the-editor.md)).
- **Retool:** runs builder-written JavaScript in null-origin frames. Its docs warn that without a separate sandbox domain, a malicious builder could act inside other builders' browsers ([Retool docs](https://docs.retool.com/self-hosted/guides/origin-sandbox)).
- **MCP Apps:** each app view must sit behind a sandbox proxy whose origin differs from the host's ([ext-apps spec](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/draft/apps.mdx)).
- **Shopify:** runs each checkout extension in a Web Worker and renders its output as host-owned components through Remote DOM ([shopify.dev](https://shopify.dev/docs/api/checkout-ui-extensions/latest)).
- **Salesforce:** sandboxes per vendor namespace ([Salesforce LWS](https://developer.salesforce.com/docs/platform/lightning-components-security/guide/lws-performance.html)).

**Granularity follows authorship.** Code from one author (one notebook, one artifact, one project) gets one isolated surface. Observable says outright that imported code shares the notebook's realm ([Observable docs](https://observablehq.com/documentation/security/data-security-and-privacy)).

Frames per unit carry real costs:

- **Figma (2019):** spent about a month on an iframe per plugin, then rejected it. The async API was hostile to designers, every round trip cost about 0.1 ms, and serialising a large file took **14 seconds** ([Figma blog](https://www.figma.com/blog/how-we-built-the-figma-plugin-system/)).
- **Streamlit:** mounted every component in its own same-origin iframe. A sandbox without `allow-same-origin` broke webcams and servers that expect a non-null origin, and adding the token made the sandbox moot. It spent **five months and nine releases** before letting components break the sandbox and moving its admin dashboard to another origin instead ([Streamlit blog](https://web.archive.org/web/2022/https://blog.streamlit.io/streamlit-components-security-and-a-five-month-quest-to-ship-a-single-line-of-code/)). Its v2 components have no iframe at all ([Streamlit docs](https://docs.streamlit.io/develop/concepts/custom-components/overview)).
- **Colab:** isolates each output and accepts that shared JS libraries reload in every one ([holoviews#3551](https://github.com/pyviz/holoviews/issues/3551)).
- **Drupal Experience Builder:** listed the bugs at its iframe boundary (events not bubbling, laggy panning, zoom that felt off, links navigating inside the frame, misplaced context menus) and moved selection and drop targets into a parent overlay ([Drupal #3475759](https://www.drupal.org/i/3475759); [Drupal #3512455](https://www.drupal.org/node/3512455)).
- **tldraw:** found iframes are black boxes in exports, and disables pointer events on generated frames except while editing ([tldraw blog](https://tldraw.dev/blog/make-real-the-story-so-far); [PreviewShape.tsx](https://github.com/tldraw/make-real/blob/main/app/PreviewShape/PreviewShape.tsx)).

Hard numbers are scarce. Chrome's site isolation cost about 10–13% memory on desktop in 2018 ([Chromium](https://www.chromium.org/Home/chromium-security/site-isolation/)). Since Chrome 127, desktop Chromium moves opaque-origin sandboxed documents out of their parent's process ([Chromium process model](https://chromium.googlesource.com/chromium/src/+/main/docs/process_model_and_site_isolation.md)). A 2014 Firefox page with 400+ iframes used about 370 MiB ([Mozilla blog](https://blog.mozilla.org/nnethercote/category/adblock-plus/)). No vendor publishes a current memory benchmark per iframe.

Sandboxes at the language level, which render untrusted components straight into the host DOM, have a poor record. Figma's Realms shim had several escapes and was replaced by QuickJS compiled to WebAssembly, which is slower but more secure by design ([Figma](https://www.figma.com/blog/an-update-on-plugin-security/)). Google retired the Caja-based modes of Apps Script in favour of iframes by 2016 ([Apps Script](https://developers.google.com/apps-script/reference/html/sandbox-mode)). Salesforce's LWS works, but proxy overhead becomes noticeable at tens of thousands of proxies ([Salesforce](https://developer.salesforce.com/docs/platform/lightning-components-security/guide/lws-performance.html)), and its near-membrane library disclaims any security guarantee and requires `'unsafe-eval'` ([near-membrane](https://github.com/salesforce/near-membrane)). Anthropic's 2026 containment post reaches the same conclusion: standard primitives such as hypervisors and syscall filters held up where custom code failed ([Anthropic](https://www.anthropic.com/engineering/how-we-contain-claude)).

A cheaper pattern runs alongside all of this: many editors simply do not run user scripts on the editing canvas.

- **Webflow:** classic Code Embed scripts run only in preview or on the staging site ([Webflow forum](https://discourse.webflow.com/t/when-custom-code-only-works-on-published-sites/225289)), and code components can read an `interactive` flag that is false while a designer works ([useWebflowContext](https://developers.webflow.com/code-components/reference/hooks/useWebflowContext.md)).
- **Framer:** draws code components as a static preview on the canvas and runs external scripts only on the live site ([Queen Raae](https://queen.raae.codes/2025-12-09-framer-render-modes/)).
- **Webstudio:** skips HTML Embed scripts in build mode unless a user switches on "Run scripts on canvas", which the product itself labels dangerous ([Webstudio source](https://github.com/webstudio-is/webstudio/blob/main/packages/sdk-components-react/src/html-embed.ws.ts)).
- **Squarespace:** hides some custom code while the owner is logged in ([Squarespace Help](https://support.squarespace.com/hc/en-us/articles/206543167-Code-blocks)).
- **Puck:** its AI design mode keeps scripts off by default. When they are enabled, they are appended to the preview iframe's document ([plugin-ai 0.8.3](https://registry.npmjs.org/@puckeditor/plugin-ai/-/plugin-ai-0.8.3.tgz)), which in Puck shares the editor's origin.

## Declarative generation removes execution but caps what pages can look like

The declarative camp has the model emit data that names components from a catalog the client trusts, and the client renders them with its own code.

- **Google's A2UI** describes itself as a data format rather than executable code, citing the security risk of running LLM-generated code. Critics say the catalog makes every UI look the same ([Google Developers Blog](https://developers.googleblog.com/introducing-a2ui-an-open-project-for-agent-driven-interfaces/); [InfoQ](https://www.infoq.com/news/2026/07/google-a2ui-genui)).
- **Vercel Labs' json-render** constrains the model to a Zod-defined catalog ([InfoQ](https://www.infoq.com/news/2026/03/vercel-json-render)).
- **Thesys** argues against generating code on reliability, token cost and design-system consistency, not security. Its one-query comparison: **610 versus 1,493 output tokens, and under 2 s versus 35 s to first render**, against Claude writing code ([Thesys](https://www.thesys.dev/blogs/generating-code-for-generative-ui-is-a-bad-idea)).
- **CopilotKit** advises keeping fully generated UI for build time or controlled experiments ([CopilotKit](https://www.copilotkit.ai/blog/the-three-kinds-of-generative-ui)).

The MCP Apps standard made the opposite bet: HTML inside mandatory sandboxed iframes, chosen for its simple security model ([SEP-1865](https://modelcontextprotocol.io/seps/1865-mcp-apps-interactive-user-interfaces-for-mcp)). Shopify admits the ceiling of rendering through a host. Developers who need browser APIs that Remote DOM lacks are told to fall back to the iframe-based App Home ([Shopify docs](https://shopify.dev/docs/api/app-home-ui-extension)).

The code camp has quality evidence on its side, though never head to head against a catalog. Google Research raters strongly preferred model-written HTML/CSS/JS to markdown and placed it close behind sites made by experts ([Google Research](https://research.google/blog/generative-ui-a-rich-custom-visual-interactive-user-experience-for-any-prompt/)).

Ploy, the code-first builder founded by Webflow's co-founder and former CTO, is the closest commercial analogue. Its agent maintains an Astro/React/TypeScript/Tailwind codebase for each site, with its own component library and design tokens, and the product markets private noindex ABM pages for named accounts ([Ploy docs](https://docs.ploy.ai/site-builder); [Ploy ABM Ploybook](https://ploy.ai/ploybooks/abm-page-sdrs-aes)). Ploy's trust model is procedural rather than enforced at runtime:

- publishing is gated by role;
- auto-publish defaults to preview only;
- every deploy is a versioned snapshot;
- code syncs to Git.

No CSP header appeared on any Ploy-served site inspected, and there is no isolation per section ([Ploy security](https://docs.ploy.ai/security); [raspire.com](https://raspire.com/)).

Puck sits between the two camps. Assembly mode composes only from config components. Design mode generates HTML strings plus fields, strips event-handler attributes, and leaves scripts off ([Puck design mode](https://puckeditor.com/docs/ai/design-mode)). This hybrid, catalog first and code only when nothing fits, is also the shape of Webflow's AI code components. No vendor publishes how often the fallback fires. For landing pages, where looking distinctive is the deliverable, the catalog ceiling bites harder than in chat widgets, and an occasional TSX section is exactly that fallback.

## Publishing moves the boundary to the build server and the visitor's page

At publish time, generated code runs inside vendor infrastructure, then ships as ordinary first-party code:

- **Ploy:** builds each tenant's Astro project in a sandbox per site on third-party compute (Blaxel and Daytona are listed subprocessors), wraps the tenant's config, forces a Cloudflare Workers build, and prerenders static routes ([Ploy BYO repo](https://docs.ploy.ai/cli/bring-your-own-repo); [Ploy subprocessors](https://trust.ploy.ai/subprocessors)).
- **v0:** deploys on infrastructure separate from the chat's sandbox ([v0 docs](https://v0.app/docs/sandbox)).
- **Framer:** prerenders pages on its servers without browser APIs, and hides components that crash ([Framer Help](https://www.framer.com/help/articles/how-to-fix-cannot-set-properties-of-undefined-optimization-error/)).
- **Webflow:** server-renders code components by default ([Webflow](https://developers.webflow.com/code-components/component-architecture)).

Rendering user-authored content on a server is itself a surface for code execution. Mintlify's 2025 disclosure covered two such holes. Malicious MDX rendered on the server achieved code execution. An SVG uploaded by one customer executed on another customer's domain, because static assets were not scoped per customer ([Mintlify](https://www.mintlify.com/blog/working-with-security-researchers-november-2025)).

The isolation options on the server differ more in latency and operations than in price. Illustrative per-render arithmetic from list prices:

| Option | Startup and footprint | Security posture | Cost per render |
|---|---|---|---|
| V8 isolate (Cloudflare Workers for Platforms, Dynamic Workers) | A few ms and a few MB ([Cloudflare](https://blog.cloudflare.com/dynamic-workers/)) | V8 bugs are more common than hypervisor bugs; Cloudflare adds a second sandbox layer and keeps its patch gap under 24 h ([Cloudflare](https://developers.cloudflare.com/workers/reference/security-model/)) | ~$0.0000023 for 100 ms CPU ([WfP pricing](https://developers.cloudflare.com/cloudflare-for-platforms/workers-for-platforms/platform/pricing/)) |
| Firecracker microVM (Vercel Sandbox, AWS Lambda) | ≤125 ms to guest init, ≤5 MiB VMM overhead ([Firecracker spec](https://github.com/firecracker-microvm/firecracker/blob/main/SPECIFICATION.md)) | Dedicated kernel per sandbox | ~$0.0001 with one Vercel Sandbox per render ([Vercel](https://vercel.com/docs/vercel-sandbox)); ~$0.000017 for Lambda at 1 GB for 1 s ([AWS](https://aws.amazon.com/lambda/pricing/)) |
| Container (optionally gVisor) | Hundreds of ms to boot (Cloudflare's figure) | Shares the host kernel; gVisor's own README says containers are not a sandbox ([gVisor](https://github.com/google/gvisor)) | Self-hosted |
| In the renderer's own process (`node:vm`, Node permission model, isolated-vm) | Negligible | Node documents that `node:vm` is not a security mechanism, and calls the permission model a seat belt with known bypasses ([Node vm](https://nodejs.org/api/vm.html); [Node permissions](https://nodejs.org/api/permissions.html)) | n/a |

Val Town's history shows what happens to options that run inside the process. It went through four runtimes in two years: `vm`, then vm2, then Deno Workers, and finally a pre-warmed pool of Deno subprocesses, which also trimmed about 100 ms from typical runs ([Val Town](https://blog.val.town/blog/first-four-val-town-runtimes)). In a local test on Node 24.4.1 run during this research, `--permission --allow-fs-read=<one workspace>` refused the spike's `process.getBuiltinModule('node:fs')` read of another workspace. It did not stop `fetch`, because Node gates network access only from version 25 ([Node permissions](https://nodejs.org/api/permissions.html)). Every server option costs orders of magnitude less per render than Thesys's $0.0224 for generating one code-written UI ([Thesys](https://www.thesys.dev/blogs/generating-code-for-generative-ui-is-a-bad-idea)). So the binding constraints are latency and operational effort, not dollars.

Published sites carry little or no CSP:

- a Lovable-hosted site: none;
- a bolt.host site: only `object-src` and `base-uri` ([todo.lovable.app](https://todo.lovable.app/); [bolt.host sample](https://fakturify-invoic-qwzr.bolt.host/));
- Framer- and Webflow-hosted sites: none ([mutinyhq.com](https://www.mutinyhq.com/); [flowbase.co](https://www.flowbase.co/));
- Ploy-served sites: none ([raspire.com](https://raspire.com/)).

In Next.js, a nonce-based CSP forces dynamic rendering. Static pages need hash-based policies instead ([Next.js](https://nextjs.org/docs/app/guides/content-security-policy); [web.dev](https://web.dev/articles/strict-csp)). Published AI code runs as first-party JavaScript on whatever origin serves the page. Ploy reverse-proxies its pages onto the customer's own domain next to the existing site ([Ploy hosting](https://ploy.ai/features/hosting)). Mutiny instead requires a subdomain dedicated to Mutiny ([Mutiny Help](https://help.mutinyhq.com/hc/en-us/articles/33630887872667-Setting-Up-Your-Custom-Subdomain)).

The incident record is about authorization and abuse, not sandbox escapes.

- **Lovable CVE-2025-48757:** missing row-level security behind a client-side Supabase key. A scan found **170 of 1,645** showcase apps exposed ([Superblocks](https://superblocks.com/blog/lovable-vulnerabilities)). A 2026 broken-object-level-authorization flaw then exposed other projects' source code, chats and credentials ([The Register](https://www.theregister.com/2026/04/20/lovable_denies_data_leak/)).
- **v0 phishing:** v0 was used to clone sign-in pages that were hosted on Vercel ([Okta](https://www.okta.com/blog/threat-intelligence/okta-observes-v0-ai-tool-used-to-build-phishing-sites/)).
- **CodeSandbox reputation:** Proofpoint counted over 1,000 phishing URLs on CodeSandbox domains in 90 days ([Proofpoint](https://www.proofpoint.com/us/blog/threat-insight/web-based-sandbox-environments-offer-minimal-friction-credential-phishers)). The registrar later suspended all of csb.app ([CodeSandbox #3751](https://github.com/codesandbox/codesandbox-client/issues/3751)).
- **Notion:** notion.so was put on hold after phishing complaints, taking the app offline for hours ([TechCrunch](https://techcrunch.com/2021/02/15/notions-hours-long-outage-was-caused-by-phishing-complaints)).
- **GitHub:** moved Pages to github.io after cookie-tossing attacks it could not fully fix on the server side ([GitHub](https://github.blog/engineering/yummy-cookies-across-domains/)).

The closest analogue to a same-origin editor preview is a CMS advisory: Sveltia's Markdown preview allowed unsandboxed iframes whose scripts reached the parent CMS window ([GitLab advisory](https://advisories.gitlab.com/npm/@sveltia/cms/GHSA-h5jc-78hr-3pc9/)). This research found no public incident of a site-builder canvas stealing sessions. That is an absence of reports, not proof of safety.

## A portal-rendered Puck canvas hands AI sections the editor's privileges

### The iframe separates DOM and CSS, not JavaScript

Puck's `AutoFrame` renders a `srcDoc` iframe and mounts the page into its `#frame-root` with `createPortal` ([Puck source](https://github.com/puckeditor/puck/blob/main/packages/core/components/AutoFrame/index.tsx)). Puck documents the result as a same-origin iframe for viewports and style isolation ([Puck docs](https://puckeditor.com/docs/integrating-puck/viewports)). Under the HTML spec, the `srcdoc` document takes its creator's origin ([WHATWG](https://html.spec.whatwg.org/multipage/document-sequences.html)). More importantly, the portal makes every component function, effect and imported module execute in the host window's realm, where `window`, `document.cookie`, `localStorage`, `fetch` and `top` all belong to the editor.

The spike measured exactly this. Section code that passed the stricter check still managed four things:

- it fired a network beacon from the editor;
- it reached `fetch` through `(()=>0).constructor`;
- it reached `top` and `parent` without ever naming `window`;
- during the server render, it read another workspace's compiled modules through `process.getBuiltinModule` ([spike notes](../../../../trials/puck-spike/RUNTIME-SECTIONS.md)).

The obvious fixes do not hold:

- **A `sandbox` attribute on `AutoFrame`** constrains nothing, because no section code executes inside that frame. Without `allow-same-origin` it also cuts off Puck's own `contentDocument` access. With that token, a same-origin frame can remove its own sandbox ([MDN](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe)).
- **The `credentialless` attribute** does not stop scripting between same-origin frames. Webstudio writes directly into its credentialless canvas's `contentWindow` ([Webstudio source](https://github.com/webstudio-is/webstudio/blob/main/apps/builder/app/shared/sync/sync-stores.ts)).
- **CSP** gives only partial cover. The `srcdoc` document inherits a copy of the host's policy, and added policies can only tighten it ([W3C CSP3](https://w3c.github.io/webappsec-csp/); [MDN](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy)). Because sections run in the host realm, the editor page's own policy is what governs them, and the table below shows how far that reaches.

| Spike behaviour | Host-page CSP (today's portal) | AI section in its own opaque-origin `srcdoc` frame with `<meta>` CSP | Server render container |
|---|---|---|---|
| `<img>` beacon to a collector | Blocked if `img-src` omits the host | Blocked by `default-src 'none'` plus an asset-host allowlist | n/a |
| `fetch` reached through the `Function` constructor | Blocked only without `'unsafe-eval'`, so in production builds only, since Next.js dev requires it ([Next.js](https://nextjs.org/docs/app/guides/content-security-policy)) | Nothing to steal: the opaque origin has no cookies or storage, and `connect-src` is `'none'` | `--disallow-code-generation-from-strings` |
| Same-origin API calls, cookies, `localStorage`, editor DOM | Not blockable: `connect-src 'self'` allows them | Blocked by the opaque origin | n/a |
| `top.location`, `window.open`, phishing overlay | Not blockable; `navigate-to` was dropped from the spec in 2022 ([Mozilla](https://source-hub.etos-pro.ru/mozilla/gecko-dev/commit/2f7c1c102466ec78ff77d45cfafa6ca3bb718d5d)) | Blocked without `allow-top-navigation` and `allow-popups` ([MDN](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe)) | n/a |
| Infinite loop | Freezes the editor's main thread | Desktop Chromium ≥127 runs it out of the editor's process ([Chromium](https://chromium.googlesource.com/chromium/src/+/main/docs/process_model_and_site_isolation.md)); other browsers unverified | `--init` plus a timeout and a memory cap |
| Reading another workspace's files | n/a | n/a | Read-only mount of one workspace; Node `--permission` also refused it in local testing |

The hostile author is realistically not the marketer. It is the model, steered by content it ingests (scraped sites, web research) or by another member of the workspace. Prompt injection succeeds often enough to matter: Pluto pushed Claude's artifact-publish path into leaking a `.env.local` file in **10 of 85 attempts** ([Pluto Security](https://pluto.security/blog/inside-claude-artifacts-how-your-agent-publishes-to-the-web/)). Anthropic's containment guidance treats defences at the model layer as probabilistic and puts containment in the environment ([Anthropic](https://www.anthropic.com/engineering/how-we-contain-claude)). Retool's docs describe the case of several members exactly: builder code on a shared origin lets one builder act in another's browser ([Retool docs](https://docs.retool.com/self-hosted/guides/origin-sandbox)). The spike's lint is a useful first gate, but four probes passed it ([spike notes](../../../../trials/puck-spike/RUNTIME-SECTIONS.md)). A denylist, like Google's 2012 sanitizer, is a filter, not a boundary.

### Rare untrusted sections make frames per section the cheap option

| Option for the editor | What it contains | Main costs | Precedent |
|---|---|---|---|
| Today's portal plus lint plus host CSP | Image beacons; string eval (production only) | Nothing new, but the session, APIs, DOM and navigation stay open | GrapesJS-style sanitizing ([GrapesJS](https://github.com/GrapesJS/grapesjs/blob/dev/packages/core/src/parser/config/config.ts)) |
| Inert, server-rendered HTML in the portal | All client-side execution | Sanitizer becomes the boundary inside the privileged origin; no live interactivity; a server round trip per edit | Framer's static canvas, Webflow's `interactive` flag |
| **An opaque-origin `srcdoc` frame for each AI section** | Session, storage, same-origin APIs, editor DOM, top navigation, network; main-thread hangs on desktop Chromium | A React copy per frame; height sync; CSS, fonts and tokens per frame; a selection wrapper; an inline-edit bridge or panel-only editing; null-origin quirks | Wix editor elements, Retool components, MCP Apps views, Datasette Apps |
| Whole canvas on a separate PSL domain | Everything, for every section | Replacing Puck's portal canvas with a cross-origin document driven by RPC; a second domain | Framer, Figma Make, v0, Lovable, Claude |
| Worker plus host-rendered allowlist (Remote DOM) | DOM and `window` access | DOM polyfill, async RPC, an element allowlist, constrained animation libraries | Shopify checkout |
| Catalog only | Execution entirely | A ceiling on expressiveness; upkeep of the catalog | A2UI, Puck assembly mode |

The industry's whole-canvas pattern exists because the whole canvas is untrusted. In this editor the platform's own sections are trusted and AI-written TSX is an occasional fallback, so the untrusted party is the section. Moving the whole canvas cross-origin would mean replacing Puck's portal canvas, for which Puck documents no cross-origin mode. Drag-and-drop, selection, inline editing and field sync would all have to run over RPC at Webflow-scale cost per call, with Drupal's list of boundary bugs. It would also isolate trusted sections for no gain.

Frames per section multiply frame costs by the number of components, which is what hurt Figma, Streamlit and Colab. But a page carrying one to three AI sections keeps N small. MCP Apps chose this same per-view shape for a trusted host that embeds untrusted views. Inert server-rendered HTML looks cheaper, but it makes an HTML sanitizer the boundary inside the editor's origin, which is the approach Google abandoned in 2012, and it still needs host CSP to stop image beacons.

A concrete design follows from the precedents.

**Frame and policy.** Each AI section renders inside an `<iframe srcdoc>` whose `sandbox` contains only `allow-scripts`, which yields an opaque origin ([WHATWG](https://html.spec.whatwg.org/multipage/browsers.html)). A `<meta>` CSP sits at the top of the srcdoc: `default-src 'none'`, inline script allowed as MCP Apps' default policy does, and image, font and style sources limited to the brand asset host. Simon Willison found such a policy enforced at parse time and immune to removal or replacement of the document ([Willison](https://simonwillison.net/2026/Apr/3/test-csp-iframe-escape/)). His Datasette Apps uses exactly this arrangement for LLM-written apps served from the same host ([Datasette Apps](https://simonwillison.net/2026/Jun/18/datasette-apps/)).

**What each frame loads.** Each frame boots its own React, the section module, the CSS that the spike already compiles per module in about 12 ms, and brand tokens passed as CSS custom properties, the theming route MCP Apps and Streamlit v2 use ([ext-apps spec](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/draft/apps.mdx); [Streamlit docs](https://docs.streamlit.io/develop/concepts/custom-components/overview)).

**Keep the module out of the host realm.** The AI module must never be imported into the editor's realm, not even to read its schema. The props JSON Schema should be extracted at compile time inside the bounded sandbox and stored as data. The spike's shared-host React (`globalThis.__clueSectionHost`) goes away for AI sections. That is the main loss in ergonomics, and it means React context cannot flow from trusted sections into AI ones, a limit Webflow already accepts with its separate roots ([Webflow](https://developers.webflow.com/code-components/component-architecture)).

**Height, selection and messaging.** Height syncs through a `ResizeObserver` inside the frame posting to the parent ([Willison](https://simonwillison.net/2026/Jan/18/iframe-resize/)). Measuring `body` should be avoided because it can cause resize loops ([Svix](https://www.svix.com/blog/you-dont-need-iframe-resizer/)). Note that iframe-resizer is GPL-3.0 licensed ([npm](https://npmjs.com/package/@iframe-resizer/core)). Setting `pointer-events: none` on the frame outside an explicit interact mode leaves Puck's own wrapper in charge of selection and dragging, which is tldraw's approach. Props go down over a `MessageChannel`. The parent validates `event.source`, because the frame's origin reads as `"null"`.

**Editing.** Version one edits AI sections through the fields panel, which the spike already derives from the zod schema. A bridge inside the frame for inline editing, on the Lovable/Onlook pattern, can follow later.

**Opaque-origin quirks.** The frame gets no storage or cookies, which is harmless for landing-page sections. Servers that expect a non-null origin break, as Streamlit found ([Streamlit blog](https://web.archive.org/web/2022/https://blog.streamlit.io/streamlit-components-security-and-a-five-month-quest-to-ship-a-single-line-of-code/)), so the asset and font host must answer CORS for any origin. Media queries inside a full-width section frame evaluate against the frame's width, which follows the canvas viewport. That conclusion is inferred from how iframes size, not tested.

**Host CSP hygiene.** Keep it regardless, because trusted code has bugs too: no `'unsafe-eval'` or `blob:` in production `script-src` (`blob:` effectively restores eval ([public-webappsec](https://lists.w3.org/Archives/Public/public-webappsec/2013Aug/0068.html))), allowlists for images and connections, `form-action`, `base-uri`, and HttpOnly session cookies. Puck's stylesheet sync has broken under a strict CSP before ([Puck #1157](https://github.com/puckeditor/puck/issues/1157)).

Three things would change this call:

- If AI-written code becomes most of the page, as in a Ploy-style codebase, the economics flip toward the whole canvas on a separate PSL-listed registrable domain, following v0's guidance, despite the Puck fork that requires.
- If inline editing of AI sections is a day-one requirement, the in-frame bridge has to be budgeted up front.
- No vendor publishes memory figures per frame, so a page with three real section frames should be measured on a mid-range laptop before committing.

### The server render and the published page need their own boundaries

**The server render.** The spike's container is the right boundary for both editor-time and publish-time renders: no network, read-only, one workspace's modules, `--init` and a timeout. It needs two additions: a memory cap and an output cap, since the 20k-row probe produced 32 MB of HTML ([spike notes](../../../../trials/puck-spike/RUNTIME-SECTIONS.md)). Node's `--permission` and `--disallow-code-generation-from-strings` flags add depth, not a boundary, and AI code should never be loaded into the renderer's own process. Latency is the real cost: about 1.6 s for the first container and about 0.35 s warm, per the spike. A pre-warmed subprocess pool (Val Town) or isolates such as Cloudflare Dynamic Workers, priced at $0.002 per unique Worker loaded per day ([Cloudflare](https://blog.cloudflare.com/dynamic-workers/)), are the scale paths.

**Publishing.** AI sections should default to static HTML with no hydration unless the section needs interactivity. This shrinks the visitor-facing exposure to markup and CSS.

When an AI section does hydrate, its JavaScript shares the published origin with every trusted section, lead-capture forms included. A static page can carry a hash-based CSP with allowlists for `connect-src`, `img-src` and `form-action` ([web.dev](https://web.dev/articles/strict-csp)). No builder sampled here does that by default.

Published pages belong on a PSL-listed registrable domain distinct from the editor app, for cookies (GitHub's cookie tossing) and for reputation (CodeSandbox, Notion). Customers who reverse-proxy pages onto their own domain, as Ploy encourages, put AI JavaScript on their main site's origin, and they should make that choice knowingly.

The publish step should re-run the check and the bounded render and refuse a missing module, as the spike recommends, with publishing gated by role as Ploy does.

## Conclusion

The research turns the usual intuition upside down. Builders isolate whole surfaces not because per-component isolation is wrong, but because their whole surface is untrusted. They avoid frames per component because the costs multiply with every component. A Puck page that mixes many trusted sections with a rare AI section flips both conditions, so the option the industry avoids becomes the cheap and honest one here. The deeper lesson is that containment is a question of **which realm executes the code**, not whether an iframe exists. Puck's canvas already has an iframe, and it contains nothing, because no section code runs inside it. Moving execution is the fix; adding attributes or headers is not.

Two further implications follow. Isolating each render costs fractions of a cent, orders of magnitude less than generating the section, so the binding constraints are editing ergonomics and latency, not infrastructure spend. And the most directly relevant precedent is still unknown. No vendor, Figma's code layers included, has published how it isolates AI-written code inside a canvas that also holds trusted components, and nobody publishes current memory numbers per iframe. This platform will be setting its own precedent, which argues for measuring the frame design on real pages before generalising it.
