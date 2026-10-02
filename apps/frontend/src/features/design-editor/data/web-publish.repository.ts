import { defaultDesignFetch, type DesignEditorConfig } from "../engine/config";
import {
  fetchWebPublishInfo,
  publishWebDocument,
  unpublishWebSite,
  type WebPublishState,
} from "../engine/webDocuments";

/** What a publish just put on the air.
 *
 * Deliberately narrower than the engine's `WebPublishResult`: the sharing
 * surface needs the slug it got, the address to show, and the address of every
 * route — the digests and versions are the editor's publish dialog's business.
 */
export interface WebPublishOutcome {
  slug: string;
  url: string;
  /** Every route the site now serves, absolute. Keyed by route (`"/"` is the
   * site root). */
  pageUrls: Record<string, string>;
  /** The site root on the workspace's active custom hostname; `null` when the
   * workspace has none. */
  customUrl: string | null;
  /** Every route on that custom hostname, built by the server. Empty when the
   * workspace has no active custom hostname. */
  customPageUrls: Record<string, string>;
}

/**
 * The publishing seam for a web document (F5 task 13).
 *
 * The platform shell talks to publishing ONLY through this interface, so the
 * chat shell's Share menu has no idea whether it is driving the real design
 * API or an in-memory fixture — the same fixture/HTTP split the artifact read
 * seam uses.
 */
export interface WebPublishRepository {
  /** The document's durable publish state (`GET /documents/{id}/web/publish`). */
  state(documentId: string): Promise<WebPublishState>;
  /** Publish or republish (`POST /documents/{id}/web/publish`). */
  publish(
    documentId: string,
    input: { slug: string; noindex: boolean },
  ): Promise<WebPublishOutcome>;
  /** Take the site offline (`DELETE /web/publishes/{slug}`). */
  unpublish(slug: string): Promise<void>;
  /**
   * The whole site as a static-site ZIP (`GET /documents/{id}/web/export`) —
   * one folder per page since F5. The `filename` is the server's own
   * `Content-Disposition` name, so the download is named the way every other
   * consumer of that route names it.
   */
  exportZip(documentId: string): Promise<{ blob: Blob; filename: string }>;
  /**
   * The whole site as one PDF (`GET /documents/{id}/web/export.pdf`) — every
   * page of the site printed by the server's own browser, in document order.
   * The `filename` is the server's `Content-Disposition` name, as for the ZIP.
   */
  exportPdf(documentId: string): Promise<{ blob: Blob; filename: string }>;
}

/** The empty-ZIP end-of-central-directory record: a 22-byte archive that is a
 * real, openable (if empty) zip. The fixture serves this so a fixture-mode
 * download produces a genuine `.zip`, never a text file wearing the suffix. */
const EMPTY_ZIP_BYTES = new Uint8Array([
  0x50, 0x4b, 0x05, 0x06, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
]);

/** A minimal one-page PDF, for the same reason the empty zip above exists: a
 * fixture-mode download must produce a genuine `.pdf`, not a text file wearing
 * the suffix. */
const TINY_PDF = `%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj
trailer<</Root 1 0 R>>
%%EOF
`;

/**
 * The download name to use, read off a `Content-Disposition` header.
 *
 * Pure and header-shaped: it accepts both the quoted (`filename="a.zip"`) and
 * the bare (`filename=a.zip`) forms servers send, drops any directory part a
 * header might carry, and falls back when there is no header or no usable name
 * in it — the caller then still gets a sane file rather than an empty name.
 */
export function downloadFilenameFrom(
  contentDisposition: string | null,
  fallback: string,
): string {
  if (!contentDisposition) return fallback;
  const match = /filename\s*=\s*(?:"([^"]*)"|([^;]*))/i.exec(contentDisposition);
  const raw = (match?.[1] ?? match?.[2] ?? "").trim();
  const name = raw.split(/[\\/]/).pop()?.trim() ?? "";
  return name || fallback;
}

const UNPUBLISHED: WebPublishState = {
  customOrigin: null,
  customPageUrls: {},
  customUrl: null,
  docVersion: null,
  htmlDigest: null,
  manifestDigest: null,
  packageDigest: null,
  pageUrls: {},
  pages: [],
  previousAvailable: false,
  publishId: null,
  publicOrigin: null,
  published: false,
  slug: null,
  status: null,
  updatedAt: null,
  url: null,
};

/** The fixture host. It is deliberately a `.test` name that resolves nowhere:
 * a fixture URL must never be mistaken for a real published site. */
const FIXTURE_ORIGIN = "https://fixture.pages.test";

/**
 * An in-memory publish seam for tests and fixture mode. One publish per
 * document, exactly like the server (a document has at most one live site).
 */
export function createFixtureWebPublishRepository(): WebPublishRepository {
  const published = new Map<string, WebPublishState>();
  return {
    async exportPdf(documentId) {
      const slug = published.get(documentId)?.slug ?? "site";
      return {
        blob: new Blob([TINY_PDF], { type: "application/pdf" }),
        filename: `${slug}.pdf`,
      };
    },
    async exportZip(documentId) {
      const slug = published.get(documentId)?.slug ?? "site";
      return {
        blob: new Blob([EMPTY_ZIP_BYTES], { type: "application/zip" }),
        filename: `${slug}.zip`,
      };
    },
    async publish(documentId, { slug }) {
      const url = `${FIXTURE_ORIGIN}/${slug}`;
      published.set(documentId, {
        ...UNPUBLISHED,
        docVersion: (published.get(documentId)?.docVersion ?? 0) + 1,
        pageUrls: { "/": url },
        pages: [{ htmlDigest: null, pageId: null, route: "/" }],
        published: true,
        slug,
        status: "active",
        updatedAt: new Date(0).toISOString(),
        url,
      });
      return {
        customPageUrls: {},
        customUrl: null,
        pageUrls: { "/": url },
        slug,
        url,
      };
    },
    async state(documentId) {
      return published.get(documentId) ?? UNPUBLISHED;
    },
    async unpublish(slug) {
      for (const [documentId, state] of published) {
        if (state.slug === slug) published.delete(documentId);
      }
    },
  };
}

/**
 * The real seam, over the three design-API publish routes through the BFF.
 *
 * Pass `designBffConfig()` in the browser: `apiBaseUrl` is the page origin and
 * its `fetchImpl` re-mounts every engine URL under `/api/clue/design`, where
 * the proxy stamps the workspace header server-side.
 */
export function createHttpWebPublishRepository(
  config: DesignEditorConfig,
): WebPublishRepository {
  async function download(
    documentId: string,
    path: string,
    fallbackFilename: string,
  ): Promise<{ blob: Blob; filename: string }> {
    const { apiBaseUrl, fetchImpl = defaultDesignFetch } = config;
    const response = await fetchImpl(
      new URL(
        `/documents/${encodeURIComponent(documentId)}/${path}`,
        apiBaseUrl,
      ),
    );
    if (!response.ok) {
      throw new Error(`Site export failed (HTTP ${response.status}).`);
    }
    return {
      blob: await response.blob(),
      filename: downloadFilenameFrom(
        response.headers.get("content-disposition"),
        fallbackFilename,
      ),
    };
  }

  return {
    async exportPdf(documentId) {
      return download(documentId, "web/export.pdf", "site.pdf");
    },
    async exportZip(documentId) {
      return download(documentId, "web/export", "site.zip");
    },
    async publish(documentId, { noindex, slug }) {
      const result = await publishWebDocument(config, documentId, slug, {
        noindex,
      });
      return {
        // A custom hostname's addresses come only from the server; there is no
        // local join for them, so an empty map means "no custom hostname".
        customPageUrls: result.customPageUrls,
        customUrl: result.customUrl,
        // The server's own map wins (F5 task 14): it is the only side that
        // knows whether this workspace's sites are served from its handle's
        // host or from the interim tenant path, so joining a root to a route
        // here can only ever be a guess that happens to agree. The join below
        // survives for a server that predates `page_urls`.
        pageUrls:
          Object.keys(result.pageUrls).length > 0
            ? result.pageUrls
            : pageUrlsFor(result.url, result.routes),
        slug: result.slug,
        url: result.url,
      };
    },
    async state(documentId) {
      return fetchWebPublishInfo(config, documentId);
    },
    async unpublish(slug) {
      await unpublishWebSite(config, slug);
    },
  };
}

/**
 * The FALLBACK join, for a server that answers a publish without `page_urls`.
 *
 * It joins them the one way the server itself does — site root + route, with
 * `/` being the root — so no host, tenant path or slug shape is ever invented
 * here (R-F5-1: the client owns no public-URL constant). A server that sends
 * `page_urls` is believed instead, since it alone knows the site's real origin.
 */
function pageUrlsFor(
  siteRootUrl: string,
  routes: readonly string[],
): Record<string, string> {
  if (!siteRootUrl) return {};
  const urls: Record<string, string> = {};
  for (const route of routes.length > 0 ? routes : ["/"]) {
    urls[route] = route === "/" ? siteRootUrl : `${siteRootUrl}${route}`;
  }
  return urls;
}
