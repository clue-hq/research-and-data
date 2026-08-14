export type ProvisionLogFields = Readonly<{
  request_id: string;
  outcome: "auth_disabled" | "origin_forbidden" | "unauthenticated" | "forwarded";
  status: number;
}>;

export type ProvisionHandlerDependencies = Readonly<{
  authenticationEnabled: boolean;
  originAllowed: boolean;
  providerToken(): Promise<string | null>;
  backendBaseUrl: string;
  requestId: string;
  fetch?: typeof fetch;
  log?: (event: "onboarding.provision.bff", fields: ProvisionLogFields) => void;
}>;

function errorResponse(
  status: number,
  code: string,
  message: string,
  requestId: string,
): Response {
  return Response.json(
    { error: { code, message, requestId } },
    { status, headers: { "X-Request-Id": requestId } },
  );
}

function record(
  dependencies: ProvisionHandlerDependencies,
  outcome: ProvisionLogFields["outcome"],
  status: number,
): void {
  dependencies.log?.("onboarding.provision.bff", {
    request_id: dependencies.requestId,
    outcome,
    status,
  });
}

/** The testable same-origin BFF boundary; credentials are supplied only by server dependencies. */
export async function handleProvisionRequest(
  request: Request,
  dependencies: ProvisionHandlerDependencies,
): Promise<Response> {
  if (!dependencies.authenticationEnabled) {
    record(dependencies, "auth_disabled", 503);
    return errorResponse(
      503,
      "AUTHENTICATION_NOT_CONFIGURED",
      "Authentication is disabled",
      dependencies.requestId,
    );
  }
  if (!dependencies.originAllowed) {
    record(dependencies, "origin_forbidden", 403);
    return errorResponse(
      403,
      "REQUEST_ORIGIN_FORBIDDEN",
      "Mutation origin is not allowed",
      dependencies.requestId,
    );
  }
  const token = await dependencies.providerToken();
  if (!token) {
    record(dependencies, "unauthenticated", 401);
    return errorResponse(
      401,
      "AUTHENTICATION_REQUIRED",
      "Sign in to continue",
      dependencies.requestId,
    );
  }

  const body = await request.arrayBuffer();
  const response = await (dependencies.fetch ?? globalThis.fetch)(
    `${dependencies.backendBaseUrl.replace(/\/+$/, "")}/auth/v1/provision`,
    {
      method: "POST",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "X-Request-Id": dependencies.requestId,
      },
      body,
      cache: "no-store",
      redirect: "manual",
    },
  );
  const headers: Record<string, string> = {
    "content-type": response.headers.get("content-type") ?? "application/json",
    "cache-control": "no-store",
    "x-request-id": response.headers.get("x-request-id") ?? dependencies.requestId,
  };
  record(dependencies, "forwarded", response.status);
  return new Response(response.body, { status: response.status, headers });
}
