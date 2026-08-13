import { NextResponse } from "next/server";
import { clueApiBaseUrl, isAuthenticationEnabled } from "@/auth/config";
import { hasAllowedOrigin } from "@/auth/bff";
import { providerSessionToken } from "@/auth/server";

/**
 * FI-4 D-2 transport: the provisioning call cannot ride the generic `/api/clue` BFF because
 * that proxy requires a resolved workspace membership before forwarding — and provisioning is
 * how the first membership comes to exist. This dedicated same-origin handler applies the same
 * discipline (server-resolved Clerk token, origin check, no browser credentials forwarded)
 * without the membership gate, and forwards only to the one backend provisioning route.
 */
export async function POST(request: Request): Promise<Response> {
  if (!isAuthenticationEnabled()) {
    return errorResponse(503, "AUTHENTICATION_NOT_CONFIGURED", "Authentication is disabled");
  }
  if (!hasAllowedOrigin(request)) {
    return errorResponse(403, "REQUEST_ORIGIN_FORBIDDEN", "Mutation origin is not allowed");
  }
  const token = await providerSessionToken();
  if (!token) {
    return errorResponse(401, "AUTHENTICATION_REQUIRED", "Sign in to continue");
  }
  const body = await request.arrayBuffer();
  // Path-prefix-preserving join, same discipline as src/auth/backend.ts:backendUrl.
  const response = await fetch(`${clueApiBaseUrl()}/auth/v1/provision`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body,
    cache: "no-store",
    redirect: "manual",
  });
  const headers: Record<string, string> = {
    "content-type": response.headers.get("content-type") ?? "application/json",
    "cache-control": "no-store",
  };
  const requestId = response.headers.get("x-request-id");
  if (requestId) headers["x-request-id"] = requestId;
  return new Response(response.body, { status: response.status, headers });
}

function errorResponse(status: number, code: string, message: string): NextResponse {
  return NextResponse.json({ error: { code, message } }, { status });
}
