import { BriefcaseBusiness } from "lucide-react";
import type { SettingsWorkspace } from "../model/settings";
import styles from "./settings.module.css";
import { SettingsCard, SettingsInput } from "./settings-primitives";

export function WorkspaceSettings({
  workspace,
}: {
  workspace: SettingsWorkspace["workspace"];
}) {
  return (
    <SettingsCard>
      <div className={styles.profileRow}>
        <p className={styles.rowLabel}>Logo</p>
        <span className={styles.workspaceLogo}>
          <BriefcaseBusiness size={20} strokeWidth={1.25} />
        </span>
      </div>
      <div className={styles.divider} />
      <div className={styles.profileRow}>
        <p className={styles.rowLabel}>Organization name</p>
        <SettingsInput
          ariaLabel="Organization name"
          className={styles.profileInput}
          defaultValue={workspace.name}
        />
      </div>
      <div className={styles.divider} />
      <div className={styles.profileRow}>
        <p className={styles.rowLabel}>Company Website</p>
        <SettingsInput
          ariaLabel="Company website"
          className={styles.profileInput}
          defaultValue={workspace.website}
        />
      </div>
    </SettingsCard>
  );
}
