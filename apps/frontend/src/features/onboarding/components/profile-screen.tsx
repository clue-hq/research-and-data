import { Button } from "@/components/ui/button";
import type { OnboardingFlow } from "../model/onboarding";
import type { OnboardingDraft } from "../hooks/use-onboarding-controller";
import styles from "./onboarding.module.css";

export function ProfileScreen({
  draft,
  profile,
  onDraftChange,
  onSubmit,
}: {
  draft: OnboardingDraft;
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
        <span className={styles.selectShell}>
          <select
            aria-label="Role"
            onChange={(event) => onDraftChange("role", event.target.value)}
            value={draft.role}
          >
            <option value="">Select</option>
            {profile.roleOptions.map((role) => (
              <option key={role} value={role}>{role}</option>
            ))}
          </select>
          <ChevronDown />
        </span>
      </ProfileField>

      <ProfileField label="Company name">
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

      <Button className={styles.profileSubmit} size="lg" type="submit">
        Continue
        <ArrowRight />
      </Button>
    </form>
  );
}

function ProfileField({
  children,
  label,
}: {
  children: React.ReactNode;
  label: string;
}) {
  return (
    <label className={styles.profileField}>
      <span>{label}</span>
      {children}
    </label>
  );
}

function ChevronDown() {
  return (
    <svg aria-hidden="true" fill="none" viewBox="0 0 20 20">
      <path d="m6 8 4 4 4-4" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" />
    </svg>
  );
}

function ArrowRight() {
  return (
    <svg aria-hidden="true" fill="none" viewBox="0 0 20 20">
      <path d="M4 10h12m-4-4 4 4-4 4" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" />
    </svg>
  );
}
