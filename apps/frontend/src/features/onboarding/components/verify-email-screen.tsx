import { Button } from "@/components/ui/button";
import type { OnboardingFlow } from "../model/onboarding";
import styles from "./onboarding.module.css";

/**
 * The verification-code step (FI-4 §9 ruling 2026-08-12): an addition to the approved screen
 * set, composed entirely from the frozen visual vocabulary — the auth card, heading, field
 * shell, and button styles the designer-authored screens already use. No approved screen is
 * modified by this component's existence.
 */
export function VerifyEmailScreen({
  busy,
  copy,
  email,
  error,
  onCodeChange,
  onResend,
  onSubmit,
  code,
}: {
  busy: boolean;
  copy: OnboardingFlow["auth"]["verifyEmail"];
  email: string;
  error: string | null;
  onCodeChange: (value: string) => void;
  onResend: () => void;
  onSubmit: () => void;
  code: string;
}) {
  return (
    <form
      className={`${styles.authCard} ${styles.authCardExpanded}`}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className={styles.authHeading}>
        <h1>{copy.title}</h1>
        <p>
          {copy.subtitle} <strong>{email}</strong>
        </p>
      </div>

      <label className={styles.authField}>
        <span>{copy.codeLabel}</span>
        <span className={styles.inputShell}>
          <ShieldIcon />
          <input
            aria-label={copy.codeLabel}
            autoComplete="one-time-code"
            inputMode="numeric"
            onChange={(event) => onCodeChange(event.target.value)}
            placeholder="000000"
            value={code}
          />
        </span>
      </label>

      {error ? (
        <p className={styles.authError} role="alert">
          {error}
        </p>
      ) : null}

      <Button className={styles.authButton} disabled={busy} size="lg" type="submit">
        {copy.submitLabel}
      </Button>

      <div className={styles.authHeading}>
        <p>
          {copy.resendPrompt}{" "}
          <button disabled={busy} onClick={onResend} type="button">
            {copy.resendAction}
          </button>
        </p>
      </div>
    </form>
  );
}

function ShieldIcon() {
  return (
    <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
      <path
        d="M12 3 5 6v5c0 4.5 3 8.2 7 9.5 4-1.3 7-5 7-9.5V6l-7-3Z"
        stroke="currentColor"
        strokeLinejoin="round"
        strokeWidth="1.5"
      />
      <path
        d="m9.2 12 2 2 3.6-4"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
      />
    </svg>
  );
}
