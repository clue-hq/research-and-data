"use client";
import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { estimate, isDraft, readiness, type ApprovalResult, type Mailer } from "../model/direct-mail";
import type { DirectMailController } from "./use-direct-mail";

export const queueTabs = [{ id: "all", label: "All mailers" }, { id: "review", label: "Needs review" }, { id: "active", label: "In progress" }, { id: "attention", label: "Needs attention" }, { id: "delivered", label: "Delivered" }];
export function useMailerQueue(c: DirectMailController) {
  const router = useRouter();
  const params = useSearchParams();
  const search = params.get("q") ?? "", project = params.get("project") ?? "all", tab = params.get("status") ?? "all", sort = params.get("sort") ?? "recent";
  const campaign = params.get("campaign") ?? "all";
  const page = Math.max(1, Number(params.get("page")) || 1);
  const [selection, setSelection] = useState<string[]>([]);
  const [approval, setApproval] = useState<Mailer[] | null>(null);
  const [results, setResults] = useState<ApprovalResult[]>([]);
  const [creating, setCreating] = useState(false);
  const mailers = c.data?.mailers ?? [];
  const projects = Array.from(new Map(mailers.map((m) => [m.projectId, { value: m.projectId, label: m.projectName }])).values());
  const campaigns = Array.from(new Set(mailers.filter((m) => project === "all" || m.projectId === project).map((m) => m.campaign))).map((name) => ({ value: name, label: name }));
  const matching = mailers.filter((m) => (project === "all" || m.projectId === project) && (campaign === "all" || m.campaign === campaign) &&
    (tab === "all" || (tab === "review" && isDraft(m)) || (tab === "active" && !isDraft(m) && !["delivered", "canceled"].includes(m.stage)) || (tab === "attention" && !!m.exception) || (tab === "delivered" && m.stage === "delivered")) &&
    `${m.recipient.name} ${m.recipient.company} ${m.campaign}`.toLowerCase().includes(search.toLowerCase()));
  matching.sort((a, b) => sort === "name" ? a.recipient.name.localeCompare(b.recipient.name) : b.updatedAt.localeCompare(a.updatedAt));
  const pages = Math.max(1, Math.ceil(matching.length / 10));
  const currentPage = Math.min(page, pages);
  const visible = matching.slice((currentPage - 1) * 10, currentPage * 10);
  const selected = visible.filter((m) => selection.includes(m.id));
  const ready = selected.filter((m) => m.stage === "ready" && m.reviewedRevision === m.revision && c.data && readiness(m, c.data).length === 0);
  function filter(key: string, value: string) { const next = new URLSearchParams(params.toString()); if (value) next.set(key, value); else next.delete(key); if (key !== "page") next.delete("page"); if (key === "project") next.delete("campaign"); setSelection([]); router.replace(`/direct-mail?${next}`, { scroll: false }); }
  function toggle(id: string) { setSelection((ids) => ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id]); }
  async function approve() {
    if (!approval) return;
    const result = await c.run(() => c.repository.approve(approval.map(({ id, revision }) => ({ id, revision }))));
    if (result) { setResults(result.results); setApproval(null); setSelection([]); }
  }
  return { search, project, campaign, campaigns, tab, sort, currentPage, pages, visible, matching, projects, selected, ready, results, setResults, creating, setCreating,
    recordHref: (id: string) => `/direct-mail/${id}${params.size ? `?${params}` : ""}`,
    approval, setApproval, approve, total: ready.reduce((sum, m) => sum + (estimate(m) ?? 0), 0), filter, toggle,
    toggleAll: () => setSelection(selected.length === visible.length ? [] : visible.map((m) => m.id)) };
}
