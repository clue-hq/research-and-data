import type { BrandData } from "@clue/site-kit";
import { SiteDocumentSchema, type SectionLink, type SiteDocument } from "@clue/site-kit/site-document";
import { DESIGN_API_BFF_PREFIX } from "@/features/design-editor/data/design-bff";
import {
  LoadedSiteWireSchema,
  SITE_UNDO_CAP,
  SectionLinksWireSchema,
  SiteBrandWireSchema,
  SiteRefusalSchema,
  SiteVersionsWireSchema,
  SiteWriteResultSchema,
  type LoadedSite,
  type SiteVersion,
  type SiteWriteResult,
} from "../model/site-wire";

/** A typed refusal from the site seam: the design API's code, the HTTP status, and on a CAS
 * conflict the server's version; on a 422 the validator's messages. */
export class SiteRepositoryError extends Error {
  readonly code: string;
  readonly status: number;
  readonly currentVersion: number | null;
  readonly errors: readonly string[];

  constructor(
    message: string,
    options: { code: string; status: number; currentVersion?: number | null; errors?: readonly string[] },
  ) {
    super(message);
    this.name = "SiteRepositoryError";
    this.code = options.code;
    this.status = options.status;
    this.currentVersion = options.currentVersion ?? null;
    this.errors = options.errors ?? [];
  }
}

export interface SiteSaveRequest {
  site: SiteDocument;
  baseVersion: number;
  intent?: string;
}

/** Contract 2 (writes, undo, versions) + K3/K4 (reads) + Contract 4 (section links). */
export interface SiteRepository {
  get(documentId: string): Promise<LoadedSite>;
  getBrand(documentId: string): Promise<BrandData>;
  sectionLinks(documentId: string): Promise<SectionLink[]>;
  save(documentId: string, request: SiteSaveRequest): Promise<SiteWriteResult>;
  undo(documentId: string, baseVersion: number): Promise<SiteWriteResult>;
  redo(documentId: string, baseVersion: number): Promise<SiteWriteResult>;
  versions(documentId: string, limit?: number): Promise<SiteVersion[]>;
  restore(documentId: string, batchId: string, baseVersion: number): Promise<SiteWriteResult>;
}

async function refusalOf(response: Response): Promise<SiteRepositoryError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // A non-JSON refusal keeps the status-shaped message below.
  }
  const parsed = SiteRefusalSchema.safeParse(body);
  const detail = parsed.success ? parsed.data.detail : null;
  if (typeof detail === "string") {
    return new SiteRepositoryError(detail, { code: "site.request_failed", status: response.status });
  }
  return new SiteRepositoryError(detail?.message ?? `Website request failed (HTTP ${response.status}).`, {
    code: detail?.code ?? "site.request_failed",
    currentVersion: detail?.current_version ?? null,
    errors: detail?.errors ?? [],
    status: response.status,
  });
}

/** Browser adapter: every call goes through the same-origin design BFF, which proves the
 * session and stamps the workspace header server-side (`app/api/clue/design/[...path]`). */
export function httpSiteRepository({
  baseUrl = DESIGN_API_BFF_PREFIX,
  fetchImpl,
}: { baseUrl?: string; fetchImpl?: typeof fetch } = {}): SiteRepository {
  const doFetch: typeof fetch = fetchImpl ?? ((input, init) => fetch(input, init));
  const call = async (path: string, init?: RequestInit): Promise<unknown> => {
    const response = await doFetch(`${baseUrl}${path}`, { cache: "no-store", ...init });
    if (!response.ok) throw await refusalOf(response);
    return response.json();
  };
  const post = (body: unknown, method = "POST"): RequestInit => ({
    body: JSON.stringify(body),
    headers: { "content-type": "application/json" },
    method,
  });
  const documentPath = (documentId: string) => `/documents/${encodeURIComponent(documentId)}`;
  return {
    async get(documentId) {
      return LoadedSiteWireSchema.parse(await call(documentPath(documentId)));
    },
    async getBrand(documentId) {
      return SiteBrandWireSchema.parse(await call(`${documentPath(documentId)}/site/brand`));
    },
    async sectionLinks(documentId) {
      return SectionLinksWireSchema.parse(await call(`${documentPath(documentId)}/site/section-links`, post({})));
    },
    async save(documentId, { site, baseVersion, intent }) {
      const body = { site, base_version: baseVersion, ...(intent ? { intent } : {}) };
      return SiteWriteResultSchema.parse(await call(`${documentPath(documentId)}/site`, post(body, "PUT")));
    },
    async undo(documentId, baseVersion) {
      return SiteWriteResultSchema.parse(
        await call(`${documentPath(documentId)}/site/undo`, post({ base_version: baseVersion })),
      );
    },
    async redo(documentId, baseVersion) {
      return SiteWriteResultSchema.parse(
        await call(`${documentPath(documentId)}/site/redo`, post({ base_version: baseVersion })),
      );
    },
    async versions(documentId, limit = 50) {
      return SiteVersionsWireSchema.parse(await call(`${documentPath(documentId)}/site/versions?limit=${limit}`));
    },
    async restore(documentId, batchId, baseVersion) {
      return SiteWriteResultSchema.parse(
        await call(
          `${documentPath(documentId)}/site/versions/${encodeURIComponent(batchId)}/restore`,
          post({ base_version: baseVersion }),
        ),
      );
    },
  };
}

export const SITE_FIXTURE_DOCUMENT_ID = "doc_site_fixture";

const FIXTURE_BRAND = {
  slug: "fixture",
  measured: null,
  kit: { tokens: {} },
  fonts: [],
  assets: {},
  clones: {},
} as unknown as BrandData;

const FIXTURE_SITE: SiteDocument = SiteDocumentSchema.parse({
  id: SITE_FIXTURE_DOCUMENT_ID,
  title: "Fixture site",
  theme: {},
  pages: {
    "/": {
      root: { props: { title: "Home" } },
      content: [
        {
          type: "CtaBand",
          props: { id: "cta", surface: "brand", heading: "The one next step", body: "", buttonLabel: "Get started", buttonHref: "" },
        },
      ],
    },
  },
  shell: null,
  agent_sections: {},
});

/** In-memory adapter with the real compare-and-swap and stack rules, for local design work
 * and tests. Never a fallback: nothing selects it implicitly. */
export function fixtureSiteRepository({
  brand = FIXTURE_BRAND,
  site = FIXTURE_SITE,
}: { brand?: BrandData; site?: SiteDocument } = {}): SiteRepository {
  type HistoryRow = SiteVersion & { site: SiteDocument };
  let version = 1;
  let batch = 1;
  let current = site;
  const undoStack: SiteDocument[] = [];
  const redoStack: SiteDocument[] = [];
  const history: HistoryRow[] = [
    { batchId: "batch_1", version: 1, actorKind: "agent", intent: null, createdAt: "2026-10-11T09:01:00.000Z", site },
  ];
  const known = (documentId: string) => {
    if (documentId !== site.id) {
      throw new SiteRepositoryError("No such website.", { code: "document.not_found", status: 404 });
    }
  };
  const compareAndSwap = (baseVersion: number) => {
    if (baseVersion !== version) {
      throw new SiteRepositoryError("The document moved on.", {
        code: "edits.base_version_mismatch",
        currentVersion: version,
        status: 409,
      });
    }
  };
  const commit = (next: SiteDocument, intent: string | null): SiteWriteResult => {
    batch += 1;
    version += 1;
    current = next;
    history.unshift({
      batchId: `batch_${batch}`,
      version,
      actorKind: "human",
      intent,
      createdAt: new Date(Date.UTC(2026, 9, 11, 9, batch)).toISOString(),
      site: next,
    });
    return { version };
  };
  const pushUndo = (snapshot: SiteDocument) => {
    undoStack.push(snapshot);
    if (undoStack.length > SITE_UNDO_CAP) undoStack.shift();
  };
  return {
    async get(documentId) {
      known(documentId);
      return { documentId, title: current.title, site: current, version, undoDepth: undoStack.length, redoDepth: redoStack.length };
    },
    async getBrand(documentId) {
      known(documentId);
      return brand;
    },
    async sectionLinks(documentId) {
      known(documentId);
      return [];
    },
    async save(documentId, request) {
      known(documentId);
      compareAndSwap(request.baseVersion);
      pushUndo(current);
      redoStack.length = 0;
      return commit(request.site, request.intent ?? null);
    },
    async undo(documentId, baseVersion) {
      known(documentId);
      compareAndSwap(baseVersion);
      const previous = undoStack.pop();
      if (!previous) throw new SiteRepositoryError("Nothing to undo.", { code: "undo.empty", status: 409 });
      redoStack.push(current);
      return commit(previous, "undo");
    },
    async redo(documentId, baseVersion) {
      known(documentId);
      compareAndSwap(baseVersion);
      const next = redoStack.pop();
      if (!next) throw new SiteRepositoryError("Nothing to redo.", { code: "redo.empty", status: 409 });
      pushUndo(current);
      return commit(next, "redo");
    },
    async versions(documentId, limit = 50) {
      known(documentId);
      return history.slice(0, limit).map((row) => ({
        batchId: row.batchId,
        version: row.version,
        actorKind: row.actorKind,
        intent: row.intent,
        createdAt: row.createdAt,
      }));
    },
    async restore(documentId, batchId, baseVersion) {
      known(documentId);
      compareAndSwap(baseVersion);
      const target = history.find((row) => row.batchId === batchId);
      if (!target) throw new SiteRepositoryError("No such version.", { code: "version.not_found", status: 404 });
      pushUndo(current);
      redoStack.length = 0;
      return commit(target.site, "restore");
    },
  };
}
