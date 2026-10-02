import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/select-field";
import type { OnboardingDraft, OnboardingFlow } from "../model/onboarding";
import styles from "./onboarding.module.css";

export function ProfileScreen({
  busy = false,
  draft,
  error = null,
  profile,
  onDraftChange,
  onSubmit,
}: {
  busy?: boolean;
  draft: OnboardingDraft;
  error?: string | null;
  profile: OnboardingFlow["profile"];
  onDraftChange: <Key extends keyof OnboardingDraft>(
    key: Key,
    value: OnboardingDraft[Key],
  ) => void;
  onSubmit: () => void;
}) {
  return (
    <form
      className={styles.profileCard}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className={styles.profileHeading}>
        <h1>{profile.title}</h1>
        <p>{profile.subtitle}</p>
      </div>

      <ProfileField label="Name">
        <span className={styles.nameGrid}>
          <input
            aria-label="First name"
            onChange={(event) => onDraftChange("firstName", event.target.value)}
            placeholder="First name"
            value={draft.firstName}
          />
          <input
            aria-label="Last name"
            onChange={(event) => onDraftChange("lastName", event.target.value)}
            placeholder="Last name"
            value={draft.lastName}
          />
        </span>
      </ProfileField>

      <ProfileField label="What's your role?">
        <SelectField
          ariaLabel="Role"
          className={styles.roleSelect}
          onValueChange={(value) => onDraftChange("role", value)}
          options={[
            { value: "", label: "Select" },
            ...profile.roleOptions.map((role) => ({ value: role, label: role })),
          ]}
          value={draft.role}
        />
      </ProfileField>

      <ProfileField hint="Leave blank to use your website's name" label="Company name">
        <input
          aria-label="Company name"
          onChange={(event) => onDraftChange("companyName", event.target.value)}
          placeholder="Company"
          value={draft.companyName}
        />
      </ProfileField>

      <ProfileField label="Company website">
        <input
          aria-label="Company website"
          onChange={(event) => onDraftChange("companyWebsite", event.target.value)}
          placeholder="www.company.com"
          value={draft.companyWebsite}
        />
      </ProfileField>

      {error ? (
        <p className={styles.authError} role="alert">
          {error}
        </p>
      ) : null}

      <Button className={styles.profileSubmit} disabled={busy} size="lg" type="submit">
        Continue
        <ArrowRight />
      </Button>
    </form>
  );
}

function ProfileField({
  children,
  hint,
  label,
}: {
  children: React.ReactNode;
  hint?: string;
  label: string;
}) {
  return (
    <label className={styles.profileField}>
      <span>{label}</span>
      {children}
      {hint ? <small className={styles.profileFieldHint}>{hint}</small> : null}
    </label>
  );
}

function ArrowRight() {
  return (
    <svg aria-hidden="true" fill="none" viewBox="0 0 20 20">
      <path d="M4 10h12m-4-4 4 4-4 4" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" />
    </svg>
  );
}
