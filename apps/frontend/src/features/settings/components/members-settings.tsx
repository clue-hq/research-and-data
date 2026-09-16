"use client";
import { ChevronDown, Ellipsis } from "lucide-react";
import { Menu } from "@base-ui/react/menu";
import { Button } from "@/components/ui/button";
import { useSettingsMembers } from "../hooks/use-settings-members";
import {
  memberJoinedLabel,
  memberRoleLabel,
  type SettingsMembers,
} from "../model/members";
import styles from "./settings.module.css";
import { SettingsInput } from "./settings-primitives";

export function MembersSettings({
  members,
  canManage,
}: {
  members: SettingsMembers;
  canManage: boolean;
}) {
  const controller = useSettingsMembers(members);
  const editable = canManage && controller.members.invitations_configured;
  return (
    <div className={styles.membersStack}>
      {canManage ? (
        <div className={styles.inviteRow}>
          <SettingsInput
            ariaLabel="Member email addresses"
            className={styles.inviteInput}
            placeholder="name@company.com, separated by comma (,)"
            value={controller.emails}
            onChange={(event) => controller.setEmails(event.target.value)}
            disabled={!editable || controller.saving}
          />
          <Menu.Root>
            <Menu.Trigger
              className={styles.roleSelect}
              disabled={!editable || controller.saving}
            >
              {memberRoleLabel(controller.role)}
              <ChevronDown size={12} strokeWidth={1.4} />
            </Menu.Trigger>
            <Menu.Portal>
              <Menu.Positioner sideOffset={4}>
                <Menu.Popup className={styles.memberMenu}>
                  <Menu.Item onClick={() => controller.setRole("operator")}>
                    Member
                  </Menu.Item>
                  <Menu.Item onClick={() => controller.setRole("admin")}>
                    Admin
                  </Menu.Item>
                </Menu.Popup>
              </Menu.Positioner>
            </Menu.Portal>
          </Menu.Root>
          <Button
            size="md"
            variant="primary"
            disabled={
              !editable || controller.saving || !controller.emails.trim()
            }
            onClick={controller.invite}
          >
            Invite
          </Button>
        </div>
      ) : null}
      {canManage && !members.invitations_configured ? (
        <p role="status">
          Invitation delivery is not configured. Members are read-only.
        </p>
      ) : null}
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
            {controller.members.rows.map((member) => {
              const name = member.name || member.email || "—";
              const canChangeRole =
                editable &&
                member.kind === "member" &&
                member.role_key !== "owner" &&
                member.state === "active";
              const action =
                member.kind === "invitation"
                  ? "revoke"
                  : member.state === "removed"
                    ? "readmit"
                    : member.state === "active" &&
                        !member.is_self &&
                        member.role_key !== "owner"
                      ? "remove"
                      : null;
              return (
                <tr key={`${member.kind}:${member.id}`}>
                  <td>
                    <span className={styles.memberIdentity}>
                      <span className={styles.memberAvatar}>
                        {name.slice(0, 1)}
                      </span>
                      <span className={styles.memberName}>{name}</span>
                    </span>
                  </td>
                  <td>{member.email ?? "—"}</td>
                  <td>{memberJoinedLabel(member)}</td>
                  <td>
                    {canChangeRole ? (
                      <Menu.Root>
                        <Menu.Trigger
                          className={styles.inlineRole}
                          aria-label={`Role for ${name}`}
                          disabled={controller.saving}
                        >
                          {memberRoleLabel(member.role_key)}
                          <ChevronDown size={11} strokeWidth={1.4} />
                        </Menu.Trigger>
                        <Menu.Portal>
                          <Menu.Positioner sideOffset={4}>
                            <Menu.Popup className={styles.memberMenu}>
                              <Menu.Item
                                onClick={() =>
                                  controller.change(
                                    member.id,
                                    "role",
                                    "operator",
                                  )
                                }
                              >
                                Member
                              </Menu.Item>
                              <Menu.Item
                                onClick={() =>
                                  controller.change(member.id, "role", "admin")
                                }
                              >
                                Admin
                              </Menu.Item>
                            </Menu.Popup>
                          </Menu.Positioner>
                        </Menu.Portal>
                      </Menu.Root>
                    ) : !canManage ? (
                      <span>{memberRoleLabel(member.role_key)}</span>
                    ) : (
                      <button
                        className={styles.inlineRole}
                        disabled
                        aria-label={`Role for ${name}`}
                      >
                        {memberRoleLabel(member.role_key)}
                        <ChevronDown size={11} strokeWidth={1.4} />
                      </button>
                    )}
                  </td>
                  <td>
                    {editable && action ? (
                      <Menu.Root>
                        <Menu.Trigger
                          aria-label={`More actions for ${name}`}
                          className={styles.iconButton}
                          disabled={controller.saving}
                        >
                          <Ellipsis size={14} strokeWidth={1.4} />
                        </Menu.Trigger>
                        <Menu.Portal>
                          <Menu.Positioner sideOffset={4}>
                            <Menu.Popup className={styles.memberMenu}>
                              <Menu.Item
                                onClick={() =>
                                  controller.change(member.id, action)
                                }
                              >
                                {action === "revoke"
                                  ? "Revoke invitation"
                                  : action === "readmit"
                                    ? "Re-admit"
                                    : "Remove from workspace"}
                              </Menu.Item>
                            </Menu.Popup>
                          </Menu.Positioner>
                        </Menu.Portal>
                      </Menu.Root>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
