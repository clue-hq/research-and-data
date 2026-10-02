import Link from "next/link";
import { redirect } from "next/navigation";
import { isAuthenticationEnabled } from "@/auth/config";
import { providerSessionToken } from "@/auth/server";
import { OnboardingAuthProvider } from "@/features/onboarding/data/onboarding-auth";
import {
  OnboardingHeader,
  OnboardingFooter,
} from "@/features/onboarding/components/onboarding-brand";
import { InvitationSignUp } from "@/features/settings/components/invitation-sign-up";
import { invitationErrorMessage } from "@/features/settings/model/invitation";
import styles from "@/features/onboarding/components/onboarding.module.css";

export default async function InvitationPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const token = typeof query.token === "string" ? query.token : "";
  const ticket =
    typeof query.__clerk_ticket === "string" ? query.__clerk_ticket : "";
  const code = typeof query.error === "string" ? query.error : "";
  const authenticated = Boolean(await providerSessionToken());
  if (authenticated && token && !code)
    redirect(`/session/establish?${new URLSearchParams({ invite: token })}`);
  const enabled = isAuthenticationEnabled();
  return (
    <div className={`${styles.page} ${styles.authPage}`}>
      <OnboardingHeader accountEmail="" />
      <main className={styles.centerStage}>
        {enabled && ticket && token && !code ? (
          <OnboardingAuthProvider authEnabled={enabled}>
            <InvitationSignUp ticket={ticket} token={token} />
          </OnboardingAuthProvider>
        ) : (
          <section className={styles.authCard}>
            <div className={styles.authHeading}>
              <h1>Workspace invitation</h1>
              <p role="alert">
                {code
                  ? invitationErrorMessage(code)
                  : !enabled
                    ? invitationErrorMessage("INVITATIONS_UNCONFIGURED")
                    : "Sign in with your invited email, or open the full invitation link from your email."}
              </p>
              <Link href={authenticated ? "/sign-out" : "/sign-in"}>
                {authenticated ? "Sign out" : "Sign in"}
              </Link>
              {authenticated && token ? (
                <Link
                  href={`/session/establish?${new URLSearchParams({ invite: token })}`}
                >
                  Try again
                </Link>
              ) : null}
            </div>
          </section>
        )}
      </main>
      <OnboardingFooter />
    </div>
  );
}
