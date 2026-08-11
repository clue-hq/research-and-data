import { redirect } from "next/navigation";
import { AuthenticateWithRedirectCallback } from "@clerk/nextjs";
import { isAuthenticationEnabled } from "@/auth/config";

/**
 * Headless OAuth landing (FI-4 D-1): Clerk finishes the Google redirect here — including the
 * sign-in ↔ sign-up transfer for first-time Google users — then continues to
 * /session/establish (a brand-new identity is bounced onward to /onboarding/profile by the
 * session DAL's membership-less repair). Every incomplete-flow exit is pinned to an in-house
 * screen so no branch can escape to Clerk-hosted UI (review finding FE8).
 */
export default function SsoCallbackPage() {
  if (!isAuthenticationEnabled()) redirect("/onboarding/sign-in");
  return (
    <>
      <div aria-label="Completing sign in" className="grid min-h-screen place-items-center" role="status">
        <span className="size-6 animate-spin rounded-full border-2 border-neutral-300 border-t-neutral-700" />
      </div>
      <AuthenticateWithRedirectCallback
        continueSignUpUrl="/onboarding/sign-up-email"
        firstFactorUrl="/onboarding/sign-in-email"
        signInFallbackRedirectUrl="/session/establish"
        signInUrl="/onboarding/sign-in"
        signUpFallbackRedirectUrl="/session/establish"
        signUpUrl="/onboarding/sign-up"
        verifyEmailAddressUrl="/onboarding/verify-email"
      />
    </>
  );
}
