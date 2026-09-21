import { Button } from "@/components/ui/button";
import type { OnboardingDraft, OnboardingFlow } from "../model/onboarding";
import styles from "./onboarding.module.css";

type AuthCopy = OnboardingFlow["auth"]["signIn"];

export function AuthScreen({
  busy = false,
  copy,
  draft,
  emailMode,
  error = null,
  onChooseEmail,
  onChooseGoogle,
  onDraftChange,
  onSubmit,
  onSwitchMode,
}: {
  busy?: boolean;
  copy: AuthCopy;
  draft: OnboardingDraft;
  emailMode: boolean;
  error?: string | null;
  onChooseEmail: () => void;
  onChooseGoogle: () => void;
  onDraftChange: <Key extends keyof OnboardingDraft>(
    key: Key,
    value: OnboardingDraft[Key],
  ) => void;
  onSubmit: () => void;
  onSwitchMode: () => void;
}) {
  return (
    <form
      className={`${styles.authCard} ${emailMode ? styles.authCardExpanded : ""}`}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className={styles.authHeading}>
        <h1>{copy.title}</h1>
        <p>
          {copy.accountPrompt}{" "}
          <button onClick={onSwitchMode} type="button">
            {copy.accountAction}
          </button>
        </p>
      </div>

      <Button
        aria-busy={busy}
        className={styles.authButton}
        disabled={busy}
        onClick={onChooseGoogle}
        size="lg"
        type="button"
        variant="secondary"
      >
        <GoogleMark />
        {copy.googleLabel}
      </Button>

      {emailMode ? (
        <>
          <AuthField label="Work email">
            <span className={styles.inputShell}>
              <MailIcon />
              <input
                aria-label="Work email"
                autoComplete="email"
                onChange={(event) => onDraftChange("email", event.target.value)}
                placeholder="name@company.com"
                type="email"
                value={draft.email}
              />
            </span>
          </AuthField>
          <AuthField label="Password">
            <span className={styles.inputShell}>
              <KeyIcon />
              <input
                aria-label="Password"
                autoComplete="current-password"
                onChange={(event) => onDraftChange("password", event.target.value)}
                placeholder="********"
                type="password"
                value={draft.password}
              />
            </span>
          </AuthField>
          <Button className={styles.authButton} disabled={busy} size="lg" type="submit">
            {copy.submitLabel}
          </Button>
        </>
      ) : (
        <Button
          className={styles.authButton}
          onClick={onChooseEmail}
          size="lg"
          type="button"
          variant="secondary"
        >
          <MailIcon />
          {copy.emailLabel}
        </Button>
      )}

      {error ? (
        <p className={styles.authError} role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}

function AuthField({
  children,
  label,
}: {
  children: React.ReactNode;
  label: string;
}) {
  return (
    <label className={styles.authField}>
      <span>{label}</span>
      {children}
    </label>
  );
}

function GoogleMark() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M23 12.245c0-.905-.075-1.565-.236-2.25h-10.54v4.083h6.186c-.124 1.014-.797 2.542-2.294 3.569l-.021.136 3.332 2.53.23.022C21.779 18.417 23 15.593 23 12.245z" fill="#4285F4" />
      <path d="M12.225 23c3.03 0 5.574-.978 7.433-2.665l-3.542-2.688c-.948.648-2.22 1.1-3.891 1.1a6.745 6.745 0 0 1-6.386-4.572l-.132.011-3.465 2.628-.045.124C4.043 20.531 7.835 23 12.225 23z" fill="#34A853" />
      <path d="M5.84 14.175A6.65 6.65 0 0 1 5.463 12c0-.758.138-1.491.361-2.175l-.006-.147-3.508-2.67-.115.054A10.831 10.831 0 0 0 1 12c0 1.772.436 3.447 1.197 4.938l3.642-2.763z" fill="#FBBC05" />
      <path d="M12.225 5.253c2.108 0 3.529.892 4.34 1.638l3.167-3.031C17.787 2.088 15.255 1 12.225 1 7.834 1 4.043 3.469 2.197 7.062l3.63 2.763a6.77 6.77 0 0 1 6.398-4.572z" fill="#EB4335" />
    </svg>
  );
}

function MailIcon() {
  return (
    <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
      <rect height="15" rx="2" stroke="currentColor" strokeWidth="1.5" width="19" x="2.5" y="4.5" />
      <path d="m4 7 8 6 8-6" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" />
    </svg>
  );
}

function KeyIcon() {
  return (
    <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
      <circle cx="8" cy="15" r="4" stroke="currentColor" strokeWidth="1.5" />
      <path d="m11 12 8-8m-3 3 2 2m-5 1 2 2" stroke="currentColor" strokeLinecap="round" strokeWidth="1.5" />
    </svg>
  );
}
