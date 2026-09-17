"use client";
import { Button } from "@/components/ui/button";
import { useInvitationSignUp } from "../hooks/use-invitation-sign-up";
import styles from "@/features/onboarding/components/onboarding.module.css";

export function InvitationSignUp({
  ticket,
  token,
}: {
  ticket: string;
  token: string;
}) {
  const controller = useInvitationSignUp(ticket, token);
  return (
    <form
      className={`${styles.authCard} ${styles.authCardExpanded}`}
      onSubmit={(event) => {
        event.preventDefault();
        void controller.submit(new FormData(event.currentTarget));
      }}
    >
      <div className={styles.authHeading}>
        <h1>Join your workspace</h1>
        <p>Set up your name and password to accept this invitation.</p>
      </div>
      <label className={styles.authField}>
        <span>First name</span>
        <span className={styles.inputShell}>
          <input
            name="firstName"
            autoComplete="given-name"
            maxLength={200}
            required
            disabled={controller.saving}
          />
        </span>
      </label>
      <label className={styles.authField}>
        <span>Last name</span>
        <span className={styles.inputShell}>
          <input
            name="lastName"
            autoComplete="family-name"
            maxLength={200}
            required
            disabled={controller.saving}
          />
        </span>
      </label>
      <label className={styles.authField}>
        <span>Password</span>
        <span className={styles.inputShell}>
          <input
            name="password"
            type="password"
            autoComplete="new-password"
            required
            disabled={controller.saving}
          />
        </span>
      </label>
      <div id="clerk-captcha" />
      <Button
        className={styles.authButton}
        size="lg"
        type="submit"
        disabled={controller.saving}
      >
        {controller.saving ? "Joining…" : "Accept invitation"}
      </Button>
      {controller.error ? (
        <p className={styles.authError} role="alert">
          {controller.error}
        </p>
      ) : null}
    </form>
  );
}
