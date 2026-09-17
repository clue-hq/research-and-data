"use client";
import { shellProfile, type SettingsProfile } from "../model/profile";
import { useSettingsProfile } from "../hooks/use-settings-profile";
import styles from "./settings.module.css";
import { SettingsCard, SettingsInput } from "./settings-primitives";

export function ProfileSettings({
  profile: initial,
}: {
  profile: SettingsProfile;
}) {
  const controller = useSettingsProfile(initial);
  const profile = shellProfile(controller.profile);
  return (
    <SettingsCard>
      <div className={styles.profileRow}>
        <p className={styles.rowLabel}>Profile picture</p>
        <span
          aria-label={`${profile.fullName} avatar`}
          className={styles.profileAvatar}
          style={{ backgroundColor: profile.avatarColor }}
        >
          {profile.initials}
        </span>
      </div>
      <div className={styles.divider} />
      <div className={styles.profileRow}>
        <p className={styles.rowLabel}>Full name</p>
        <SettingsInput
          ariaLabel="Full name"
          className={styles.profileInput}
          {...controller.fullName}
          maxLength={200}
        />
      </div>
      <div className={styles.divider} />
      <div className={styles.profileRow}>
        <div className={styles.rowCopy}>
          <p className={styles.rowLabel}>Display name</p>
          <p>Nick name or first name, however you want to be called on Clue</p>
        </div>
        <SettingsInput
          ariaLabel="Display name"
          className={styles.profileInput}
          {...controller.displayName}
          maxLength={200}
        />
      </div>
    </SettingsCard>
  );
}
