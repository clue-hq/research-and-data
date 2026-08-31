import { isAuthenticationEnabled } from "@/auth/config";
import { OnboardingAuthProvider } from "@/features/onboarding/data/onboarding-auth";
import { OnboardingDraftProvider } from "@/features/onboarding/data/onboarding-draft";

/**
 * Mounts the two onboarding providers above the per-step routes: the draft (so typed input
 * survives step navigation) and the headless auth adapter (Clerk when authentication is
 * enabled, the design-review fixture otherwise). `authEnabled` is resolved here, server-side —
 * no client component reads an environment variable.
 */
export default function OnboardingLayout({ children }: { children: React.ReactNode }) {
  return (
    <OnboardingDraftProvider>
      <OnboardingAuthProvider authEnabled={isAuthenticationEnabled()}>
        {children}
      </OnboardingAuthProvider>
    </OnboardingDraftProvider>
  );
}
