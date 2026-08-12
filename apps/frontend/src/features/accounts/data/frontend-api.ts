import { ApiErrorEnvelopeSchema } from "../model/vocabulary";
import { ClueApiError } from "./clue-api-error";

export { ClueApiError } from "./clue-api-error";

/** Every data route on the Accounts read surface uses this backend prefix. */
const READ_PREFIX = "/frontend/v1";

/**
 * The two `404` codes that mean "no such record".
 *
 * Every other `404` is a misconfiguration, not an empty workspace: a wrong
 * prefix or a disabled read surface must fail loudly instead of masquerading
 * as a legitimate zero state.
 */
const RECORD_NOT_FOUND_CODES = new Set([
  "ACCOUNT_NOT_FOUND",
  "CONTACT_NOT_FOUND",
]);

function readPath(
  path: string,
  searchParams: Record<string, string | number | undefined>,
): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(searchParams)) {
    if (value !== undefined && value !== "") {
      query.set(key, String(value));
    }
  }
  const suffix = query.toString();
  return `${READ_PREFIX}${path}${suffix ? `?${suffix}` : ""}`;
}

export type AuthenticatedReadRequest = (
  path: string,
  init?: RequestInit,
) => Promise<Response>;

async function authenticatedReadRequest(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  // Lazy so the repository contracts remain unit-testable outside React's
  // `react-server` export condition. Runtime always loads the server-only
  // authenticated request before issuing a read.
  const { fetchAuthenticatedClueBackend } = await import(
    "@/auth/authenticated-backend"
  );
  return fetchAuthenticatedClueBackend(path, init);
}

async function readErrorEnvelope(response: Response) {
  try {
    const parsed = ApiErrorEnvelopeSchema.safeParse(await response.json());
    if (parsed.success) return parsed.data.error;
  } catch {
    // A proxy error page or truncated response is not a domain envelope.
  }
  return null;
}

/**
 * Fetch one authenticated read endpoint and return its parsed JSON body.
 *
 * There is no fixture mode and no static workspace configuration. The default
 * requester derives the provider session on the Next server, resolves the
 * selected Clue membership, and forwards `X-Clue-Workspace-Id` to FastAPI.
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
  request: AuthenticatedReadRequest = authenticatedReadRequest,
): Promise<unknown | null> {
  const response = await request(readPath(path, searchParams), {
    headers: { Accept: "application/json" },
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
            ? " — check the /frontend/v1 mount and that the read surface flag is on"
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
