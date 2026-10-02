import { z } from "zod";

export const InvitationAcceptanceSchema = z
  .object({
    accepted: z.number().int().nonnegative(),
    workspace_id: z.string().min(1).optional(),
    membership_id: z.string().min(1).optional(),
  })
  .refine(
    (value) =>
      value.accepted === 0 ||
      Boolean(value.workspace_id && value.membership_id),
  );

export function invitationErrorMessage(code: string): string {
  switch (code) {
    case "ADDRESS_MISMATCH":
      return "Sign in with the email address this invitation was sent to.";
    case "VERIFIED_EMAIL_REQUIRED":
      return "Verify your primary email, then open the invitation again.";
    case "INVITATION_UNAVAILABLE":
      return "This invitation has expired, been revoked, or is no longer available. Ask an administrator for a new invitation.";
    case "INVITATIONS_UNCONFIGURED":
      return "Invitation acceptance is not configured. Contact your administrator.";
    default:
      return "We could not accept your invitation. Open the invitation again to retry.";
  }
}
