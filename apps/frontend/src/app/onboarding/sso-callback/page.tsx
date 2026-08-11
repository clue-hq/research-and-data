import { redirect } from "next/navigation";
import { AuthenticateWithRedirectCallback } from "@clerk/nextjs";
import { isAuthenticationEnabled } from "@/auth/config";

/**
 * Headless OAuth landing (FI-4 D-1): Clerk finishes the Google redirect here — including the
 * sign-in ↔ sign-up transfer for first-time Google users — then continues to
 * /session/establish. A brand-new identity is bounced onward to /onboarding/profile by the
 * session DAL's membership-less repair, so one completion URL serves both cases. Renders
 * nothing visual beyond the shared onboarding loading state.
 */
export default function SsoCallbackPage() {
  if (!isAuthenticationEnabled()) redirect("/onboarding/sign-in");
  return (
    <AuthenticateWithRedirectCallback
      signInFallbackRedirectUrl="/session/establish"
      signUpFallbackRedirectUrl="/session/establish"
    />
  );
}
