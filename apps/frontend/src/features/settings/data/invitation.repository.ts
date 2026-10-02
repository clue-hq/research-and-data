import "server-only";
import { fetchClueAuthentication } from "@/auth/backend";
import { InvitationAcceptanceSchema } from "../model/invitation";

export async function acceptSettingsInvitations(
  sessionToken: string,
  token?: string,
) {
  return InvitationAcceptanceSchema.parse(
    await fetchClueAuthentication(
      "/auth/v1/invitations/accept",
      { token: sessionToken },
      { method: "POST", body: token ? { token } : {} },
    ),
  );
}
