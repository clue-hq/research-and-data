"use client";
import Image from "next/image";
import { BriefcaseBusiness } from "lucide-react";
import type { SettingsOrganization } from "../model/workspace";
import { useSettingsWorkspace } from "../hooks/use-settings-profile";
import styles from "./settings.module.css";
import { SettingsCard, SettingsInput } from "./settings-primitives";

export function WorkspaceSettings({
  workspace,
  canManage,
}: {
  workspace: SettingsOrganization;
  canManage: boolean;
}) {
  const controller = useSettingsWorkspace(workspace);
  return (
    <SettingsCard>
      <div className={styles.profileRow}>
        <p className={styles.rowLabel}>Logo</p>
        <span className={styles.workspaceLogo}>
          {workspace.logo_url ? (
            <Image
              src={workspace.logo_url}
              alt="Organization logo"
              width={24}
              height={24}
              unoptimized
            />
          ) : (
            <BriefcaseBusiness size={20} strokeWidth={1.25} />
          )}
        </span>
      </div>
      <div className={styles.divider} />
      <div className={styles.profileRow}>
        <p className={styles.rowLabel}>Organization name</p>
        <SettingsInput
          ariaLabel="Organization name"
          className={styles.profileInput}
          {...controller.name}
          readOnly={!canManage || controller.name.readOnly}
          maxLength={200}
        />
      </div>
      <div className={styles.divider} />
      <div className={styles.profileRow}>
        <p className={styles.rowLabel}>Company Website</p>
        <SettingsInput
          ariaLabel="Company website"
          className={styles.profileInput}
          value={workspace.website ?? ""}
          readOnly
        />
      </div>
    </SettingsCard>
  );
}
