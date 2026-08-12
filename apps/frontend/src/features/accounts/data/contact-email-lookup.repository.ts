import {
  ContactEmailLookupSchema,
  type ContactEmailLookup,
} from "../model/account-contact";
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

async function fetchMutation(
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

export async function startContactEmailLookup(
  accountId: string,
  contactId: string,
): Promise<ContactEmailLookup> {
  const body = await fetchMutation(
    `/accounts/${encodeURIComponent(accountId)}/contacts/${encodeURIComponent(contactId)}/email-lookup`,
    { method: "POST", body: "{}" },
  );
  return ContactEmailLookupSchema.parse(body);
}

export async function pollContactEmailLookup(
  accountId: string,
  contactId: string,
  lookupId: string,
): Promise<ContactEmailLookup> {
  const body = await fetchMutation(
    `/accounts/${encodeURIComponent(accountId)}/contacts/${encodeURIComponent(contactId)}/email-lookup/${encodeURIComponent(lookupId)}/poll`,
    { method: "POST", body: "{}" },
  );
  return ContactEmailLookupSchema.parse(body);
}
