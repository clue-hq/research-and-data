import type { OnboardingFlow, SetupItem } from "../model/onboarding";
import { OnboardingLogo } from "./onboarding-brand";
import styles from "./onboarding.module.css";

export function SetupScreen({
  setup,
  compact,
}: {
  setup: OnboardingFlow["setup"];
  compact: boolean;
}) {
  if (compact) {
    return (
      <section aria-live="polite" className={styles.finalizingState}>
        <Spinner />
        <h1>{setup.title}</h1>
        <p>{setup.finalizingDetail}</p>
      </section>
    );
  }

  return (
    <section aria-live="polite" className={styles.setupState}>
      <OnboardingLogo large />
      <h1>{setup.title}</h1>
      <div className={styles.setupList}>
        {setup.items.map((item) => (
          <SetupRow item={item} key={item.id} />
        ))}
      </div>
    </section>
  );
}

function SetupRow({ item }: { item: SetupItem }) {
  return (
    <div className={`${styles.setupRow} ${styles[`setupRow_${item.status}`]}`}>
      <span className={styles.setupStatus}>
        {item.status === "complete" ? <CheckMark /> : null}
        {item.status === "running" ? <Spinner /> : null}
      </span>
      <span>
        <strong>{item.label}</strong>
        {item.detail ? <small>{item.detail}</small> : null}
      </span>
    </div>
  );
}

function Spinner() {
  return <span aria-hidden="true" className={styles.spinner} />;
}

function CheckMark() {
  return (
    <svg aria-hidden="true" fill="none" viewBox="0 0 20 20">
      <path d="m4 10 4 4 8-9" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" />
    </svg>
  );
}
