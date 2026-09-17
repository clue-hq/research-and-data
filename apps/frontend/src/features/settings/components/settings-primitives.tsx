import type { ReactNode } from "react";
import styles from "./settings.module.css";

export function SettingsCard({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`${styles.card} ${className}`}>{children}</div>;
}

export function SettingsInput({
  ariaLabel,
  className = "",
  defaultValue,
  placeholder,
}: {
  ariaLabel: string;
  className?: string;
  defaultValue?: string;
  placeholder?: string;
}) {
  return (
    <input
      aria-label={ariaLabel}
      className={`${styles.input} ${className}`}
      defaultValue={defaultValue}
      placeholder={placeholder}
    />
  );
}

export function SettingsTextarea({
  ariaLabel,
  defaultValue,
  placeholder,
  rows = 4,
}: {
  ariaLabel: string;
  defaultValue?: string;
  placeholder?: string;
  rows?: number;
}) {
  return (
    <textarea
      aria-label={ariaLabel}
      className={styles.textarea}
      defaultValue={defaultValue}
      placeholder={placeholder}
      rows={rows}
    />
  );
}

export function SettingsToggle({
  defaultChecked,
  label,
}: {
  defaultChecked: boolean;
  label: string;
}) {
  return (
    <label className={styles.toggleRow}>
      <span>{label}</span>
      <input defaultChecked={defaultChecked} type="checkbox" />
      <span aria-hidden="true" className={styles.toggleTrack} />
    </label>
  );
}

export function SectionLead({
  children,
  description,
}: {
  children: ReactNode;
  description?: string;
}) {
  return (
    <div className={styles.sectionLead}>
      <h2>{children}</h2>
      {description ? <p>{description}</p> : null}
    </div>
  );
}
