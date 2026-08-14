# Stage-0 durable official-site crawling — C2 policy contract

**Status:** C2 implemented and verified; C3-C5 acquisition and coordination are implemented

**Parent:** [durable official-site crawl implementation plan](./FI-stage0-durable-official-site-crawl-plan.md)

**Depends on:** C0 frozen seams and C1 PostgreSQL frontier/ledger

---

## 1. C2 outcome and boundary

C2 owns deterministic URL identity, link-graph admission, sitemap/robots parsing, alias
observations, and coordinator safety decisions. It performs no page acquisition and imports no
provider SDK. C3 places Firecrawl and Scrapling behind the one-page `PageFetcher` seam; C5 now
composes these C2 decisions around each claim/fetch/persist step.

The versioned V1 components are:

| Component | Version |
|---|---|
| Fetch-key policy | `official-site-url-v1` |
| Discovery/category policy | `official-site-discovery-v1` |
| Safety policy | `official-site-safety-v1` |
| Robots policy | `official-site-robots-v1` |
| Sitemap policy | `official-site-sitemap-v1` |

Changing an equivalence, allowlist, classifier pattern, or safety ceiling requires a policy version
bump and fixture review. Existing runs continue to use their pinned C0 URL/robots policy values.

## 2. Conservative URL identity

The URL policy resolves a reference against the exact source-page URL and then:

- accepts only HTTP(S), with no userinfo;
- refuses backslash-ambiguous spellings and ASCII/Unicode whitespace before parsing;
- lowercases scheme/host, strips a terminal host dot, and normalizes the host to ASCII IDNA;
- removes only default ports;
- decodes percent-encoded unreserved octets and uppercases retained escape hex;
- preserves path case, trailing slash, `/index.html`, nondefault ports, query order, repeated query
  keys, and every non-tracking parameter;
- removes only `utm_*`, `dclid`, `fbclid`, `gclid`, `gbraid`, `mc_cid`, `mc_eid`, `msclkid`,
  `twclid`, and `wbraid`;
- strips ordinary fragments while retaining `#/...` and `#!/...` as routing discriminators;
- refuses credential-bearing, malformed, oversized, non-HTTP, external-domain, disabled-subdomain,
  and configured auth/account URLs.

The exact discovered spelling remains in `official_site_url_observation`. A new page's
`representative_requested_url` is the absolute safe fetch key, so relative link provenance is
never accidentally handed to a provider as a request URL.

No canonical hint changes a fetch key. No redirect or canonical hint independently creates a page
node.

## 3. Discovery, priority, depth, and re-expansion

The deterministic scheduler categories remain the parent plan's ordered categories: homepage,
product/solution, pricing, customer proof, company, partner/integration, trust/compliance, selected
blog/resources, and remaining pages. The classifier uses URL path and bounded link text only; no
model runs in scheduling. An explicit path category wins before bounded link text is consulted;
link text is a fallback for opaque paths, not authority to relabel an explicit `/blog/` URL because
its article-card description happens to mention “plans.” Each bounded discovery batch is ordered
by category priority before the repository applies the crawl-wide page ceiling. The prefix uses
the same unique-URL category quotas as fast claiming, followed by every excess same-category URL,
remaining page, duplicate, and refusal. Equal-priority observations use a stable URL and
provenance ordering. This preserves every occurrence and background candidate while preventing
provider/DOM link order—or one large category—from consuming capacity before other observed
priority categories are admitted.

Depth rules are structural:

- root is depth `0`;
- a link from known depth `d < 2` is depth `d + 1`;
- a link from depth `2` is recorded as refused;
- sitemap discovery is always unknown depth;
- links found on an unknown-depth fetched page are retained as page nodes in `discovered`, not
  queued;
- an explicitly admitted sitemap page may be queued while remaining unknown-depth;
- aliases never assert graph depth.

The contract also fails closed if a link/redirect/canonical observation lacks its source page, if
a root/sitemap observation invents one, or if an admitted root is not depth zero. This prevents a
caller from bypassing graph provenance by constructing the transport model directly.

When a fetched unknown/deeper page later receives a shorter verified link path, the repository
keeps it fetched, updates its minimum depth, expands saved anchor edges at the new depth, and queues
only newly reachable unknown children. Expansion is generation-independent, transactionally
idempotent through existing edge/page keys, bounded at depth two, and may cascade through already
fetched children without another provider call. `expanded_min_depth` fences replay.

## 4. Provenance and the additive C2 contract delta

URL observations, graph edges, and aliases remain distinct records:

- every parser occurrence stays an `official_site_url_observation`;
- verified graph relationships stay `official_site_link_edge` rows;
- redirects/canonical hints stay `official_site_alias_observation` rows;
- an alias may point to an already-existing target page, but never creates or merges one;
- an external alias has `rejected_external` and no target page.

C2 found one transport omission in C0: the frozen table included `sitemap_url`, but the
`UrlObservation` payload did not carry the source sitemap. C2 adds one backward-compatible optional
`sitemap_url` field. C0 fixtures remain valid; every C2 sitemap planner populates the field, and the
repository now persists the actual source sitemap rather than incorrectly copying the discovered
page URL. This is the only C0 payload-shape delta; C2 also tightens origin/depth validation without
changing a field. It changes no table, enum, transition graph,
`PageFetcher`, materializer, or repository operation.

## 5. Robots and sitemap bounds

Robots parsing is byte/line/rule bounded, network-free, and fail-closed for unavailable or refused
HTTP statuses. It implements user-agent group selection, longest-path precedence, allow-on-tie,
wildcards, terminal `$`, host-local decisions, stable hashed decision references, and bounded
sitemap declarations.

V1 robots ceilings:

- 512,000 decompressed bytes;
- 20,000 lines and 4,096 characters per line;
- 10,000 allow/disallow rules;
- 32 sitemap declarations.

Sitemap parsing accepts bounded captured XML/plain responses, rejects DTD/entity declarations,
malformed/unsupported roots, unsupported MIME, oversized URLs/documents, recursive loops, external
indexes, and missing captured children. It never performs hidden network recursion.

V1 sitemap ceilings:

- 1,000,000 decompressed bytes per document;
- 10,000 URLs total/per document;
- 16 visited index documents;
- nested index depth `2`;
- 4,096 characters per URL.

Sitemap entries retain their source sitemap and always enter discovery with `graph_depth=NULL`.

## 6. Network and response safety

Before dispatch, the coordinator must run `preflight_target`. It resolves a bounded number of DNS
answers and refuses the target if any answer is non-public: private/RFC1918, loopback, link-local,
carrier-grade NAT, multicast, reserved, unspecified, documentation, metadata, or IPv4-mapped
private IPv6. IP literals receive the same checks.

Every redirect hop and final URL is revalidated for chain continuity, loops, redirect count,
domain policy, DNS/IP safety, and unreported terminal changes. Provider safety remains defense in
depth. C3's local provider must use the injected pinned-address connector seam so a second DNS
lookup cannot bypass the validated answers.

Response admission initially allows HTML, XHTML, and plain text; PDF is explicit opt-in. The policy
checks decompressed byte length, not transfer/compressed length. Outgoing anchors plus canonical
hints share one 200-link ceiling and the frozen 500-character link-text ceiling. Script, style, and
template contents are never interpreted as links.

## 7. Verification and next handoff

C2 acceptance covers:

- a 37-case JSON URL matrix plus explicit non-equivalence assertions;
- public/private IPv4/IPv6, IP literals, mixed DNS answers, answer ceilings/timeouts, and the
  pinned-address transport seam;
- same-domain, external, private, discontinuous, looping, mismatched, and excessive redirects;
- MIME, decompressed size, combined outgoing-link, and link-text ceilings;
- robots precedence/status and every parser ceiling;
- sitemap namespaces, source provenance, external indexes, bombs, entities, loops, depth, document,
  and URL ceilings;
- database-persisted unknown depth, parked unknown children, shorter-path re-expansion without
  refetch, alias separation/rejection, exact replay, and full-key protection under a forced hash
  collision.

C3 keeps these semantics outside provider code: adapters return one typed page result and add only
transport-level integrity checks. C5 now applies C2 authoritatively before dispatch and again to
provider-returned redirects, final URL, content metadata, and links. C6 composes the live bounded
robots implementation and production lifecycle.
