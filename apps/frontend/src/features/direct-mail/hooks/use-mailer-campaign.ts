"use client";
import { useState } from "react";
import type { DirectMailController } from "./use-direct-mail";

export function useMailerCampaign(c: DirectMailController, close: () => void) {
  const [projectId, setProjectId] = useState(c.data?.mailers[0]?.projectId ?? "");
  const [name, setName] = useState("");
  const [budget, setBudget] = useState("100");
  const [recipients, setRecipients] = useState<string[]>([]);
  const [cardId, setCardId] = useState(c.data?.cards[0]?.id ?? "");
  const [styleId, setStyleId] = useState(c.data?.styles[0]?.id ?? "");
  const projects = Array.from(new Map(c.data?.mailers.map((m) => [m.projectId, { value: m.projectId, label: m.projectName }])).values());
  const people = Array.from(new Map(c.data?.mailers.filter((m) => m.projectId === projectId).map((m) => [m.contactId, m])).values());
  const valid = name.trim() && recipients.length > 0 && Number(budget) >= 1 && Number(budget) <= 10000;
  async function create() {
    if (!valid) return;
    if (await c.run(() => c.repository.create({ projectId, campaign: name, recipientIds: recipients, budgetCents: Math.round(Number(budget) * 100), cardId, styleId }))) close();
  }
  return { projectId, name, setName, budget, setBudget, recipients, cardId, setCardId, styleId, setStyleId, projects, people, valid, create,
    changeProject: (id: string) => { setProjectId(id); setRecipients([]); }, toggle: (id: string) => setRecipients((ids) => ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id]) };
}
