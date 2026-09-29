import { ClueApiError } from "@/features/accounts/data/clue-api-error";
import {
  fetchMutation,
  fetchMutationVoid,
} from "@/features/accounts/data/frontend-mutation";

import { PagesSettingsReadSchema, type PagesSettingsRead } from "../model/pages";

const BFF_PREFIX = "/api/clue/frontend/v1";

export interface PagesSettingsPatch {
  fallbackUrl?: string | null;
  pageTitle?: string | null;
  pageDescription?: string | null;
}

export async function updatePagesSettings(
  patch: PagesSettingsPatch,
): Promise<PagesSettingsRead> {
  return PagesSettingsReadSchema.parse(
    await fetchMutation("/settings/pages", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  );
}

export async function changeSystemLabel(
  label: string,
): Promise<PagesSettingsRead> {
  return PagesSettingsReadSchema.parse(
    await fetchMutation("/settings/pages/system-hostname", {
      method: "PATCH",
      body: JSON.stringify({ label }),
    }),
  );
}

export async function connectCustomHostname(
  hostname: string,
): Promise<PagesSettingsRead> {
  return PagesSettingsReadSchema.parse(
    await fetchMutation("/settings/pages/custom-hostname", {
      method: "POST",
      body: JSON.stringify({ hostname }),
    }),
  );
}

export async function checkCustomHostname(): Promise<PagesSettingsRead> {
  return PagesSettingsReadSchema.parse(
    await fetchMutation("/settings/pages/custom-hostname/check", {
      method: "POST",
    }),
  );
}

/** Removal answers `204 No Content`, so it goes through the body-less mutation. */
export async function removeCustomHostname(): Promise<void> {
  await fetchMutationVoid("/settings/pages/custom-hostname", { method: "DELETE" });
}

/**
 * Multipart upload: the browser sets the multipart boundary itself, so this bypasses
 * `fetchMutation`'s JSON content-type default and calls the BFF directly. The BFF
 * forwards the raw body and headers, so the boundary survives the hop.
 */
export async function uploadPagesImage(
  kind: "favicon" | "social-preview",
  file: File,
): Promise<PagesSettingsRead> {
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await fetch(`${BFF_PREFIX}/settings/pages/${kind}`, {
    method: "POST",
    body: form,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    let envelope: {
      code?: string;
      message?: string;
      requestId?: string | null;
    } = {};
    try {
      envelope = (await response.json()).error ?? {};
    } catch {
      // A proxy error page or truncated response is not a domain envelope.
    }
    throw new ClueApiError(
      envelope.message ?? `Upload failed (${response.status})`,
      {
        code: envelope.code ?? "HTTP_ERROR",
        requestId: envelope.requestId ?? null,
        status: response.status,
      },
    );
  }
  return PagesSettingsReadSchema.parse(await response.json());
}
