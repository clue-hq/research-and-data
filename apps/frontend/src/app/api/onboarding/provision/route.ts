import {
  clueApiBaseUrl,
  clueAppOrigin,
  isAuthenticationEnabled,
} from "@/auth/config";
import { hasAllowedOrigin } from "@/auth/bff";
import { providerSessionToken } from "@/auth/server";
import { handleProvisionRequest } from "./provision-handler";
import { localProvisioningRefusal } from "@/auth/local-workspace";

/**
 * FI-4 D-2 transport: the provisioning call cannot ride the generic `/api/clue` BFF because
 * that proxy requires a resolved workspace membership before forwarding — and provisioning is
 * how the first membership comes to exist. This dedicated same-origin handler applies the same
 * discipline (server-resolved Clerk token, origin check, no browser credentials forwarded)
 * without the membership gate, and forwards only to the one backend provisioning route.
 */
export async function POST(request: Request): Promise<Response> {
  const refusal = localProvisioningRefusal();
  if (refusal) return refusal;
  const authenticationEnabled = isAuthenticationEnabled();
  const requestId = crypto.randomUUID();
  return handleProvisionRequest(request, {
    authenticationEnabled,
    originAllowed:
      authenticationEnabled && hasAllowedOrigin(request, clueAppOrigin()),
    providerToken: providerSessionToken,
    backendBaseUrl: authenticationEnabled ? clueApiBaseUrl() : "",
    requestId,
    log(event, fields) {
      console.info(event, fields);
    },
  });
}
