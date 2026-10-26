"use client";
import { useState } from "react";
import type { EmailDraft } from "../model/workspace";

export function useEmailDialogs(email?: EmailDraft) {
  const [editing, setEditing] = useState<EmailDraft>();
  const [approving, setApproving] = useState<EmailDraft>();
  return {
    editing, approving,
    openEdit: () => setEditing(email ? structuredClone(email) : undefined), closeEdit: () => setEditing(undefined),
    openApproval: () => setApproving(email ? structuredClone(email) : undefined), closeApproval: () => setApproving(undefined),
  };
}
