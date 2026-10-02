import "server-only";

import { z } from "zod";
import { clueApiBaseUrl } from "./config";
import { ClueAuthenticationError } from "./errors";

export { ClueAuthenticationError } from "./errors";

const ErrorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string().min(1),
    message: z.string().min(1),
    requestId: z.string().nullable().optional(),
  }),
});

function backendUrl(path: string): URL {
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("Clue backend paths must be origin-relative");
  }
  return new URL(`${clueApiBaseUrl()}${path}`);
}

async function errorFrom(response: Response): Promise<ClueAuthenticationError> {
  try {
    const parsed = ErrorEnvelopeSchema.safeParse(await response.clone().json());
    if (parsed.success) {
      return new ClueAuthenticationError(parsed.data.error.message, {
        code: parsed.data.error.code,
        requestId:
          parsed.data.error.requestId ??
          response.headers.get("X-Request-Id") ??
          null,
        status: response.status,
      });
    }
  } catch {
    // A gateway HTML/error body has no safe domain detail; use the status fallback.
  }
  return new ClueAuthenticationError(
    `Clue authentication API returned ${response.status}`,
    {
      code: "HTTP_ERROR",
      requestId: response.headers.get("X-Request-Id"),
      status: response.status,
    },
  );
}

export async function fetchClueAuthentication(
  path: string,
  { token, workspaceId }: Readonly<{ token: string; workspaceId?: string }>,
  mutation?: Readonly<{ method: "POST"; body: unknown }>,
): Promise<unknown> {
  const headers = new Headers({
    Accept: "application/json",
    Authorization: `Bearer ${token}`,
  });
  if (workspaceId) headers.set("X-Clue-Workspace-Id", workspaceId);
  if (mutation) headers.set("Content-Type", "application/json");
  const response = await fetch(backendUrl(path), {
    cache: "no-store",
    headers,
    ...(mutation
      ? { method: mutation.method, body: JSON.stringify(mutation.body) }
      : {}),
  });
  if (!response.ok) throw await errorFrom(response);
  return response.json();
}
