"use client";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useConfirmation } from "@/components/ui/confirmation-card";
import {
  changeSettingsMember,
  inviteSettingsMembers,
  refreshSettingsMembers,
} from "../data/settings.actions";
import {
  invitationSummary,
  type SettingsMembers,
  type MemberRole,
} from "../model/members";

export function useSettingsMembers(initial: SettingsMembers) {
  const [members, setMembers] = useState(initial);
  const [emails, setEmails] = useState("");
  const [role, setRole] = useState<MemberRole>("operator");
  const busy = useRef(false);
  const [saving, setSaving] = useState(false);
  const notify = useConfirmation();
  const router = useRouter();
  async function run(
    action: () => Promise<{ message: string; error?: boolean }>,
  ) {
    if (busy.current) return;
    busy.current = true;
    setSaving(true);
    try {
      const result = await action();
      notify(result.message, result.error);
    } catch (error) {
      notify(
        error instanceof Error
          ? error.message
          : "This change could not be saved.",
        true,
      );
    } finally {
      try {
        setMembers(await refreshSettingsMembers());
      } catch (error) {
        notify(
          error instanceof Error
            ? error.message
            : "Members could not be refreshed.",
          true,
        );
      }
      busy.current = false;
      setSaving(false);
      router.refresh();
    }
  }
  function invite() {
    void run(async () => {
      const result = await inviteSettingsMembers(emails.split(","), role);
      if (
        result.outcomes.every((item) =>
          [
            "sent",
            "created_no_email",
            "already_member",
            "already_invited",
          ].includes(item.outcome),
        )
      )
        setEmails("");
      return {
        message: invitationSummary(result),
        error: result.outcomes.some((item) =>
          ["invalid", "rate_limited", "delivery_failed"].includes(item.outcome),
        ),
      };
    });
  }
  function change(
    id: string,
    action: "role" | "remove" | "readmit" | "revoke",
    nextRole: MemberRole = "operator",
  ) {
    void run(async () => {
      await changeSettingsMember(id, action, nextRole);
      return {
        message: {
          role: "Role updated",
          remove: "Member removed",
          readmit: "Member re-admitted",
          revoke: "Invitation revoked",
        }[action],
      };
    });
  }
  return { members, emails, setEmails, role, setRole, saving, invite, change };
}
