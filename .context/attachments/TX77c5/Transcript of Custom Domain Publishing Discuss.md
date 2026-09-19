## User

in the meanwhile, i wanted to discuss with you, so we have these website design edtor and all right, and right now we are publishing any website that's there in our site, and hosting it in our platform's sub-domain only right, that looks something like - <workspace-name>.pages.cluehq.ai/<route> 

but now, we have this added requirement of giving the user the ability to publish the website, in a custom domain that our provider can provide us. what are your thoughts on this?? how do you think, we can do it this way? i want you to throughly udnerstand the process over the internet, about how it can be done, and how existing companies like notion, mutiny and ploy do this... 

for your info, each workspace will have one common domain, to work from. can you tell me like how we can work on this? You can have a look at the dummy settings page's "Pages" page implementation, that contains all the things related to what hosting a website would cover. Some of those ooptions might also be unnecesary btw, and we need to do a detailed discussion on the fact btw.

## Assistant

[260 messages elided]

Codebase side is done. Waiting on the two research agents (products and infrastructure) before I write up the discussion.

[7 messages elided]

The product research is in. Still waiting on the infrastructure agent, which is also covering Railway specifically. I'll write up once it lands.

[13 messages elided]

Research and code reading are done. Here is the discussion, with my recommendation and one question at the end.

## Where we actually stand

One correction first. In this tree, nothing serves `<workspace>.pages.cluehq.ai/<route>` yet. What exists:

- **Public pages serve only at the interim path route** on the design API, `/w/{workspace_id}/p/{slug}`. That is the O6b dev-only scheme Part IV is meant to delete.
- **The share menu shows a fake host.** The copy-link chrome hardcodes `share.cluehq.ai/<slug>` in `use-artifact-sharing-controller.ts:14`, and that URL resolves to nothing.
- **The ruled tenant-subdomain v1 is unbuilt.** No workspace-slug registry, no host-to-workspace resolution seam, no wildcard DNS or certificate. Your 2026-08-17 ruling already decomposed it into five pieces and named custom domains as "the layered endgame, explicitly not v1".
- **There is no deployed page origin.** Only the frontend is on Railway. The platform API and design API run on your laptop behind ngrok tunnels, per `apps/frontend/docs/railway-deployment.md`.
- **Published HTML bakes absolute asset URLs at publish time.** The page's JS and CSS point at whatever host the publish request came in on, and the delivery CSP pins that origin (`web_export.py` around line 1519). Serving that HTML from a customer domain means the assets still load from our host. That works, but the public base must become configuration, not the request URL.

So the real prerequisite is not the custom domain. It is a deployed serving origin plus the subdomain v1 you already ruled. A custom domain is then one more row in the same host-resolution table.

## How the others do it

- **Mutiny** is the closest match to our product. One dedicated custom subdomain per workspace, like `go.company.com`. Two CNAMEs, one to CloudFront and one for certificate validation. No apex. Business plan and above. Their workspace-level Settings → Pages has exactly our dummy's fields: fallback URL, favicon, OG image, title, description, indexing, head and body snippets.
- **Notion Sites** is subdomain only too. CNAME to `external.notion.site` plus a TXT ownership record. Ten dollars per month per domain, up to 25 per workspace. No custom head or body code.
- **Ploy** goes further. Apex and www both work because they sit on Cloudflare for SaaS. They use Entri for one-click DNS, and path-based routing rules proxy the rest of the domain to the customer's existing site. Their "on the prospect's subdomain" ABM claim has no documentation behind it.

The industry protocol is the same everywhere: the customer adds a CNAME for a subdomain, adds a TXT record proving ownership, and the provider issues the certificate automatically. The TXT record is what stops one tenant claiming another company's hostname or taking over a dangling CNAME.

## The provider question and my recommendation

Railway is our provider, and it cannot host this directly. Custom domains are capped per service.

| Railway plan | Custom domains per service |
|---|---|
| Trial | 1 |
| Hobby | 2 |
| Pro | 20 |

A wildcard like `*.pages.cluehq.ai` counts as one domain there, so the subdomain v1 fits Railway fine. Customer domains do not.

Recommended shape:

1. **Build in this order.** Deploy the page-serving origin, then the ruled subdomain v1 with the host-resolution seam, then custom domains as another row in that seam. Publishing must also stop baking the request URL into the HTML.
2. **One dedicated subdomain per workspace, no apex in v1.** This is the Mutiny and Notion model, it avoids every apex DNS problem, and it matches your "one common domain per workspace" framing. Apex support is an Enterprise-only Cloudflare feature or a different vendor, so it is a later decision.
3. **Cloudflare for SaaS as the edge.** One hundred customer hostnames are included and each extra one costs ten cents a month. It has a mature API, TXT pre-validation, and automatic certificates. Our origin behind it is the page-serving service. The one known trap is Railway's edge returning a 404 for a Host it does not recognize, so the origin either runs outside Railway or a small Worker rewrites the Host to the workspace subdomain. The research agent flagged that Worker composition as an inference to validate with one real domain before committing.
4. **Fallback if we want zero edge code.** Approximated at twenty cents per domain per month, where the customer adds a single A record and apex works natively.

The customer-facing flow becomes: type `go.acme.com` in Settings, we show two records to add, we poll DNS and show observed versus required values, and the status walks pending DNS, verifying, issuing certificate, active, error. Active means both ownership and certificate are confirmed, never DNS alone.

## The Pages settings page, field by field

Keep:

- **Custom domain.** The ask itself, plus the status lifecycle and the two DNS records. The dummy input alone is not enough UI for this. That is a frame the co-founder will owe.
- **Fallback URL.** Where an unpublished or unknown route sends visitors. Mutiny has it, and for ABM pages it is genuinely useful. Default it to the workspace's company website.
- **Favicon, social preview, page title, page description.** Keep as workspace defaults that each page can override, sourced from the brand kit by default, matching your 2026-09-14 note.

Drop:

- **Allow indexing and allow following toggles.** They contradict ruling R-F1, where every ABM page is permanently noindex. A workspace toggle that cannot change the answer is misleading.
- **llms.txt and its autogenerate toggle.** Only Framer documents it among the seven products checked, and it makes no sense for pages we deliberately hide from crawlers.

Defer with a security review:

- **Head and body HTML snippets.** Marketers do want GTM and analytics on these pages, and Mutiny ships it. But it means arbitrary customer script inside pages our CSP currently locks down. Worth doing, not in the first slice.

Three points remain yours to rule: plan gating for the feature, whether the `pages.cluehq.ai` URL stays live and redirects once a custom domain is active, and the edge vendor. I recorded all of this in `_memory/2026-09-17-custom-domain-publishing-research.md`, nothing else changed.

The one question I need answered before anything else: do you accept subdomain-only for v1, one dedicated subdomain per workspace like `go.acme.com`, with apex support deferred?

[2 messages elided]

## User

no but like customer domain is also an important v1 requirement for us. And secondly, for your clarification, our cluehq domain is also bought and served by cloudflare, only for deployment we are using railway.

## Assistant

[3 messages elided]

Two clarifications back, then the plan simplifies a lot.

**I was not proposing to defer custom domains.** My question was narrower: whether v1 means a customer *subdomain* like `go.acme.com`, or also the *root* domain `acme.com`. Those are very different builds:

- **Subdomain** is what Mutiny and Notion ship. The customer adds one CNAME and one TXT record and we serve `go.acme.com/<slug>`. Their marketing site is untouched.
- **Root domain** means we become the origin for the customer's whole website. Their homepage would 404 unless we also reverse-proxy everything that is not ours back to their existing site. That is Ploy's routing-rules product, a separate system. Cloudflare also only supports apex custom hostnames when the customer is on Cloudflare themselves or we buy Enterprise apex proxying.

A seller never wants their root domain replaced by ABM pages, so I believe subdomain is the correct v1 definition of "customer domain", not a compromise. That is the ruling I need.

**Cloudflare holding the cluehq.ai zone removes the vendor question.** Cloudflare for SaaS is a feature of the zone we already own, and the first 100 customer hostnames are free. The shape becomes:

1. One proxied record in our zone, say `pages.cluehq.ai`, is the CNAME target we give customers and the fallback origin for every custom hostname.
2. A tiny Worker on that route forwards each request to the page origin on Railway with the original hostname in a trusted header. Railway then needs exactly one registered domain, and its unknown-Host 404 never fires. The same Worker serves `<workspace>.pages.cluehq.ai`, so tenant subdomains and customer domains are one path, not two.
3. The backend resolves that hostname through one table, hostname to workspace, kind subdomain or custom. That is the load-bearing seam your Part IV ruling already named. A custom domain is one more row.
4. Connecting a domain is one Cloudflare API call to create the custom hostname with HTTP certificate validation. The customer adds a CNAME to `pages.cluehq.ai` and one ownership TXT record. We poll until both hostname status and certificate status are active.
5. Second-level wildcards like `*.pages.cluehq.ai` are not covered by Cloudflare's free Universal certificate. Advanced Certificate Manager is about ten dollars a month for that. Worth verifying on the zone before planning.

Guardrails for v1: one custom hostname per workspace, subdomains only with a clear refusal message for apex, no hostnames under cluehq.ai, a remove-domain path that deletes the Cloudflare hostname before the row, and the `<workspace>.pages.cluehq.ai` URL stays live as the permanent fallback.

Two things still gate this regardless of the domain work: the page origin has to be deployed on Railway rather than served through your laptop's ngrok tunnel, and publishing has to stop baking the request URL into the HTML.

So the one ruling I need now: is "customer domain" in v1 a dedicated subdomain the customer picks, with root-domain hosting explicitly out, yes or no?

[2 messages elided]