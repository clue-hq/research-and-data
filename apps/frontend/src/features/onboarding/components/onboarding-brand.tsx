import Image from "next/image";
import styles from "./onboarding.module.css";

export function OnboardingLogo({ large = false }: { large?: boolean }) {
  return (
    <Image
      alt="Clue"
      className={large ? styles.largeLogo : styles.smallLogo}
      height={large ? 24 : 12}
      priority
      src="/logos/clue-sidebar.svg"
      width={large ? 98 : 49}
    />
  );
}

export function OnboardingHeader({
  accountEmail,
  onLogOut,
  showAccount = false,
}: {
  accountEmail: string;
  onLogOut?: () => void;
  showAccount?: boolean;
}) {
  return (
    <header className={styles.header}>
      <OnboardingLogo />
      {showAccount ? (
        <div className={styles.accountActions}>
          <span>{accountEmail}</span>
          <button onClick={onLogOut} type="button">
            Log out
          </button>
        </div>
      ) : null}
    </header>
  );
}

export function OnboardingFooter() {
  return (
    <footer className={styles.footer}>
      <a href="#privacy">Privacy</a>
      <a href="#support">Support</a>
      <a href="#terms">Terms</a>
    </footer>
  );
}
