import { ChevronDown, Ellipsis } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { SettingsWorkspace } from "../model/settings";
import styles from "./settings.module.css";
import { SettingsInput } from "./settings-primitives";

export function MembersSettings({
  members,
}: {
  members: SettingsWorkspace["members"];
}) {
  return (
    <div className={styles.membersStack}>
      <div className={styles.inviteRow}>
        <SettingsInput
          ariaLabel="Member email addresses"
          className={styles.inviteInput}
          placeholder="name@company.com, separated by comma (,)"
        />
        <button className={styles.roleSelect} type="button">
          Member
          <ChevronDown size={12} strokeWidth={1.4} />
        </button>
        <Button size="md" variant="default">Invite</Button>
      </div>

      <div className={styles.memberTableFrame}>
        <table className={styles.memberTable}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Joined on</th>
              <th>Role</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {members.map((member) => (
              <tr key={member.id}>
                <td>
                  <span className={styles.memberIdentity}>
                    <span className={styles.memberAvatar}>{member.name.slice(0, 1)}</span>
                    {member.name}
                  </span>
                </td>
                <td>{member.email}</td>
                <td>{member.joinedOn}</td>
                <td>
                  <button className={styles.inlineRole} type="button">
                    {member.role}
                    <ChevronDown size={11} strokeWidth={1.4} />
                  </button>
                </td>
                <td>
                  <button aria-label={`More actions for ${member.name}`} className={styles.iconButton} type="button">
                    <Ellipsis size={14} strokeWidth={1.4} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
