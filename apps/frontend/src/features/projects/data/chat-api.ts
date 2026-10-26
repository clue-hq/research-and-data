import { z } from "zod";

/**
 * The transport seam for the projects chat flow.
 *
 * Everything about how this flow reaches the backend lives here: the mount
 * prefix, the error envelope, the idempotency identity, and the same-origin
 * rule. The repositories above it choose fixture-or-HTTP; nothing below it
 * (models, hooks, components) knows a network exists.
 *
 * **Configuration — `CLUE_PROJECTS_API_BASE_URL`.** This remains a project-flow
 * switch until that flow completes its own cutover. Accounts/Contacts are
 * live-only and no longer share this fixture-selection pattern.
 *
 * **It is a same-origin path prefix, not an origin.** The chat surface is
 * driven from the browser (streaming, turn submission, gate answers), and Lane
 * B's rule is that a browser never calls FastAPI cross-origin and never touches
 * a provider token: every request rides the authenticated BFF at
 * `src/app/api/clue/[...path]`, which attaches the session bearer and the
 * workspace header server-side. So the value is normally `/api/clue`, and a
 * value that is not origin-relative is refused rather than silently producing
 * cross-origin requests with no credentials.
 */

export const PROJECTS_API_BASE_URL_VAR = "CLUE_PROJECTS_API_BASE_URL";

/** Where the chat surface is mounted behind the BFF. */
const CHAT_MOUNT = "/api/v1";

export type ChatTransport =
  | { mode: "fixture" }
  // `workspaceId` is the workspace the page was loaded for (set by the protected layout).
  | { mode: "http"; prefix: string; workspaceId?: string | null };

/**
 * The header a chat request names its page's workspace in. The BFF refuses the request with
 * `WORKSPACE_CHANGED` when the selected workspace has changed since the page loaded, and the
 * page reloads, so a page never shows one workspace with another's data (L4-4).
 */
export const PAGE_WORKSPACE_HEADER = "X-Clue-Page-Workspace";
export const WORKSPACE_CHANGED = "WORKSPACE_CHANGED";

/** What a page does when its workspace changed under it: load again, under the new one. */
let onWorkspaceChanged: () => void = () => window.location.reload();

/** For tests: replace the reload. */
export function setWorkspaceChangedHandler(handler: () => void): void {
  onWorkspaceChanged = handler;
}

/** Name the page's workspace on a chat request's headers. */
export function withPageWorkspace(
  transport: Extract<ChatTransport, { mode: "http" }>,
  headers: Headers,
): Headers {
  if (transport.workspaceId) headers.set(PAGE_WORKSPACE_HEADER, transport.workspaceId);
  return headers;
}

/** The refusal of ``response``; a workspace change also reloads the page. */
export async function chatRefusalOf(response: Response): Promise<ClueChatApiError> {
  const refusal = await refusalOf(response);
  if (refusal.code === WORKSPACE_CHANGED) onWorkspaceChanged();
  return refusal;
}

export const FIXTURE_TRANSPORT: ChatTransport = { mode: "fixture" };

/**
 * Resolve the transport from configuration.
 *
 * Called from the data layer only — a route may ask for the result and pass it
 * down as a serializable prop, but no component reads the environment.
 */
export function resolveChatTransport(
  value: string | undefined = process.env[PROJECTS_API_BASE_URL_VAR],
): ChatTransport {
  const configured = value?.trim();
  if (!configured) return FIXTURE_TRANSPORT;
  if (!configured.startsWith("/")) {
    throw new Error(
      `${PROJECTS_API_BASE_URL_VAR} must be an origin-relative path such as ` +
        "/api/clue: the projects chat flow runs in the browser and rides the " +
        "authenticated same-origin BFF, never a cross-origin backend.",
    );
  }
  return { mode: "http", prefix: configured.replace(/\/+$/, "") };
}

const ErrorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string().min(1),
    message: z.string().min(1),
    requestId: z.string().nullable().optional(),
  }),
});

/**
 * A backend refusal, carrying the code the surface branches on.
 *
 * The code set is OPEN — branch on what you know and fall back to the message.
 * The ones this flow cares about are Lane B contract §6's access states
 * (`AUTHENTICATION_REQUIRED`, `SESSION_INVALID`, `WORKSPACE_FORBIDDEN`,
 * `PERMISSION_DENIED`, `MEMBERSHIP_STATE_CHANGED`) and the chat surface's own
 * (`THREAD_NOT_FOUND`, `THREAD_ARCHIVED`, `GATE_*`, `IDEMPOTENCY_CONFLICT`).
 */
export class ClueChatApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId: string | null;

  constructor(
    message: string,
    options: { code: string; status: number; requestId: string | null },
  ) {
    super(message);
    this.name = "ClueChatApiError";
    this.code = options.code;
    this.status = options.status;
    this.requestId = options.requestId;
  }
}

/** Session expiry and access refusals map to states, never to an empty transcript. */
export const ACCESS_ERROR_CODES: ReadonlySet<string> = new Set([
  "AUTHENTICATION_REQUIRED",
  "SESSION_INVALID",
  "IDENTITY_NOT_PROVISIONED",
  "USER_DISABLED",
  "WORKSPACE_FORBIDDEN",
  "WORKSPACE_MEMBERSHIP_REQUIRED",
  "PERMISSION_DENIED",
  "MEMBERSHIP_STATE_CHANGED",
]);

export function isAccessError(error: unknown): error is ClueChatApiError {
  return error instanceof ClueChatApiError && ACCESS_ERROR_CODES.has(error.code);
}

export function chatUrl(
  transport: Extract<ChatTransport, { mode: "http" }>,
  path: string,
  query: Record<string, string | number | undefined> = {},
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const suffix = search.toString();
  return `${transport.prefix}${CHAT_MOUNT}${path}${suffix ? `?${suffix}` : ""}`;
}

async function envelopeOf(response: Response) {
  try {
    const parsed = ErrorEnvelopeSchema.safeParse(await response.json());
    if (parsed.success) return parsed.data.error;
  } catch {
    // A proxy error page or a truncated body is not an envelope.
  }
  return null;
}

export async function refusalOf(response: Response): Promise<ClueChatApiError> {
  const envelope = await envelopeOf(response);
  return new ClueChatApiError(
    envelope?.message ??
      `Clue chat API returned ${response.status} ${response.statusText}`,
    {
      code: envelope?.code ?? "HTTP_ERROR",
      status: response.status,
      requestId:
        envelope?.requestId ?? response.headers.get("X-Request-Id") ?? null,
    },
  );
}

export interface ChatRequestOptions {
  method?: "GET" | "POST" | "PATCH";
  body?: unknown;
  idempotencyKey?: string;
  query?: Record<string, string | number | undefined>;
  signal?: AbortSignal;
}

/** Issue one request against the chat surface and return its parsed JSON body. */
export async function chatRequest(
  transport: Extract<ChatTransport, { mode: "http" }>,
  path: string,
  {
    method = "GET",
    body,
    idempotencyKey,
    query,
    signal,
  }: ChatRequestOptions = {},
): Promise<unknown> {
  const headers = new Headers({ Accept: "application/json" });
  if (body !== undefined) headers.set("Content-Type", "application/json");
  // The BFF forwards exactly this header name; the chat surface requires it on
  // every turn submission, and a retried submission must reuse the same value
  // or it becomes a second turn rather than a replay.
  if (idempotencyKey) headers.set("Idempotency-Key", idempotencyKey);
  const response = await fetch(chatUrl(transport, path, query), {
    method,
    headers: withPageWorkspace(transport, headers),
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw await chatRefusalOf(response);
  if (response.status === 204) return null;
  return response.json();
}

/**
 * A stable idempotency identity for one user act.
 *
 * The turn id is *derived* from this value server-side, so it must be stable
 * across retries of the same act and different across two different acts. A
 * random value minted once at submission time is exactly that.
 */
export function newIdempotencyKey(prefix: string): string {
  const random =
    globalThis.crypto?.randomUUID?.() ??
    `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  return `${prefix}:${random}`;
}
