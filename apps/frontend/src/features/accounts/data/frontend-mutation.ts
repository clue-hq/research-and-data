import { ApiErrorEnvelopeSchema } from "../model/vocabulary";
import { ClueApiError } from "./clue-api-error";

const BFF_PREFIX = "/api/clue/frontend/v1";

async function readErrorEnvelope(response: Response) {
  try {
    const parsed = ApiErrorEnvelopeSchema.safeParse(await response.json());
    if (parsed.success) return parsed.data.error;
  } catch {
    // A proxy error page or truncated response is not a domain envelope.
  }
  return null;
}

/** Issue one authenticated browser mutation through the same-origin BFF. */
export async function fetchMutation(
  path: string,
  init: RequestInit,
  request: typeof fetch = fetch,
): Promise<unknown> {
  const response = await request(`${BFF_PREFIX}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
  if (!response.ok) {
    const envelope = await readErrorEnvelope(response);
    throw new ClueApiError(
      envelope?.message ??
        `Clue API returned ${response.status} ${response.statusText} for ${path}`,
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
