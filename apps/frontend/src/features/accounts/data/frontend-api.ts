import { ApiErrorEnvelopeSchema } from "../model/vocabulary";

/**
 * Transport seam for the backend read layer.
 *
 * Everything about how the accounts flow reaches the backend lives here:
 * the base URL, the tenant header, the error envelope, and the 404 rule. The
 * repositories above it choose fixture-or-HTTP; nothing below it (models,
 * hooks, components) knows a network exists.
 *
 * Configuration (server-side only — never `NEXT_PUBLIC_*`, because the
 * workspace header is tenancy):
 *
 * - `CLUE_ACCOUNTS_API_BASE_URL` — the backend origin serving `/frontend/v1`.
 *   Unset means fixtures. It is deliberately NOT the app-wide
 *   `CLUE_API_BASE_URL`: the projects repositories key off that one and call
 *   `api/v1/home` and `api/v1/projects/*`, which slice 1 serves nothing for, so
 *   one shared switch would flip the accounts flow live and break the home
 *   route in the same breath. The projects repositories stay pinned to fixtures
 *   until phase 2 gives them a real surface, and this flow owns its own switch.
 * - `CLUE_WORKSPACE_ID` — the workspace every request is scoped to. Required
 *   whenever the base URL is set; the backend answers `401 UNAUTHORIZED`
 *   without it, so we fail loudly at the seam instead of shipping the 401 to a
 *   screen. This is the MVP stand-in for a real session/tenant surface: when
 *   one exists, this is the single function that changes.
 */

/** Every data route on this surface is mounted under one prefix. */
const READ_PREFIX = "/frontend/v1";

/**
 * The two `404` codes that mean "no such record".
 *
 * Every other `404` is a misconfiguration, not an empty workspace: a wrong
 * base URL, a wrong prefix, or the read surface flag being off all produce the
 * framework's generic `NOT_FOUND`, and silently rendering those as "this
 * account has nothing yet" is the difference between a bug you see in five
 * minutes and one you ship.
 */
const RECORD_NOT_FOUND_CODES = new Set(["ACCOUNT_NOT_FOUND", "CONTACT_NOT_FOUND"]);

export class ClueApiError extends Error {
  /**
   * The backend error code. An OPEN set — branch on the codes you know and
   * fall back to the message; never switch exhaustively.
   */
  readonly code: string;
  readonly status: number;
  readonly requestId: string | null;

  constructor(
    message: string,
    options: { code: string; requestId: string | null; status: number },
  ) {
    super(message);
    this.name = "ClueApiError";
    this.code = options.code;
    this.status = options.status;
    this.requestId = options.requestId;
  }
}

/** The configured backend origin, or `null` when the accounts flow runs on fixtures. */
export function apiBaseUrl(): string | null {
  const configured = process.env.CLUE_ACCOUNTS_API_BASE_URL?.trim();
  return configured ? configured.replace(/\/+$/, "") : null;
}

function workspaceId(): string {
  const configured = process.env.CLUE_WORKSPACE_ID?.trim();
  if (!configured) {
    throw new Error(
      "CLUE_WORKSPACE_ID must be set whenever CLUE_ACCOUNTS_API_BASE_URL is set: " +
        "every /frontend/v1 data request is workspace-scoped through the X-Workspace-Id header.",
    );
  }
  return configured;
}

function readUrl(
  baseUrl: string,
  path: string,
  searchParams: Record<string, string | number | undefined>,
) {
  // A base that already carries the mount prefix is honoured as-is, so an
  // operator can point at either the origin or the mounted surface.
  const prefixed = baseUrl.endsWith(READ_PREFIX)
    ? baseUrl
    : `${baseUrl}${READ_PREFIX}`;
  const url = new URL(`${prefixed}${path}`);

  for (const [key, value] of Object.entries(searchParams)) {
    if (value !== undefined && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }

  return url;
}

async function readErrorEnvelope(response: Response) {
  try {
    const parsed = ApiErrorEnvelopeSchema.safeParse(await response.json());
    if (parsed.success) return parsed.data.error;
  } catch {
    // A non-JSON body (a proxy error page, a truncated response) is not an
    // envelope; fall through to the status-only error.
  }
  return null;
}

/**
 * Fetches one read endpoint and returns its parsed JSON body.
 *
 * A `404` resolves to `null` ONLY when the envelope names a record-level code
 * and the caller says this endpoint has one (`recordNotFoundAllowed`). The list
 * endpoint has no domain `404` by contract — an unknown project is an empty
 * page — so a `404` there always throws. Every other failure raises
 * {@link ClueApiError} carrying the backend's code and `requestId`.
 */
export async function fetchRead(
  path: string,
  {
    recordNotFoundAllowed = false,
    searchParams = {},
  }: {
    recordNotFoundAllowed?: boolean;
    searchParams?: Record<string, string | number | undefined>;
  } = {},
): Promise<unknown | null> {
  const baseUrl = apiBaseUrl();
  if (!baseUrl) {
    throw new Error(
      "fetchRead called without CLUE_ACCOUNTS_API_BASE_URL configured",
    );
  }

  const response = await fetch(readUrl(baseUrl, path, searchParams), {
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "X-Workspace-Id": workspaceId(),
    },
  });

  if (!response.ok) {
    const envelope = await readErrorEnvelope(response);

    if (
      response.status === 404 &&
      recordNotFoundAllowed &&
      envelope !== null &&
      RECORD_NOT_FOUND_CODES.has(envelope.code)
    ) {
      return null;
    }

    throw new ClueApiError(
      envelope?.message ??
        `Clue read API returned ${response.status} ${response.statusText} for ${path}` +
          (response.status === 404
            ? " — check CLUE_ACCOUNTS_API_BASE_URL, the /frontend/v1 mount, and that the read surface flag is on"
            : ""),
      {
        code: envelope?.code ?? "HTTP_ERROR",
        requestId:
          envelope?.requestId ?? response.headers.get("X-Request-Id") ?? null,
        status: response.status,
      },
    );
  }

  return response.json();
}
