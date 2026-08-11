import { redirect } from "next/navigation";
import { isAuthenticationEnabled } from "@/auth/config";

/**
 * Superseded by the approved onboarding screens (FI-4 D-1, ratified 2026-08-12): the stock
 * Clerk widget is retired; the frozen designer-authored sign-in card at /onboarding/sign-in
 * drives Clerk headlessly. This route survives only as the redirect target Clerk env vars and
 * the session DAL still point at.
 */
export default function SignInPage() {
  if (!isAuthenticationEnabled()) {
    return (
      <main className="grid min-h-screen place-items-center p-6">
        <p>Authentication is not enabled for this frontend environment.</p>
      </main>
    );
  }
  redirect("/onboarding/sign-in");
}
