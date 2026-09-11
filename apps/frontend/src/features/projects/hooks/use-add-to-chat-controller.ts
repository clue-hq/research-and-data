"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { projectChatHref } from "@/features/chat-shell/model/chat-shell-routes";
import { ClueChatApiError, newIdempotencyKey } from "../data/chat-api";
import { useChatRepositories } from "../data/projects-transport";
import {
  createChatContextHandoff,
  writeChatContextHandoff,
  type ChatContextHandoff,
  type ChatContextRef,
} from "../model/chat-context-handoff";
import type { SidebarProject } from "../model/sidebar-project";

export const NEW_CHAT_DESTINATION = "__new_chat__";

export function addToChatFailureMessage(error: unknown) {
  if (error instanceof ClueChatApiError) {
    if (error.code === "CONTEXT_REF_STALE") {
      return "One or more selected records changed. Refresh the table and select them again.";
    }
    if (error.code === "CONTEXT_REF_NOT_FOUND") {
      return "One or more selected records are no longer available in this workspace.";
    }
    if (error.code === "THREAD_ARCHIVED") {
      return "That chat was archived. Choose another chat or start a new one.";
    }
    if (error.code === "PERMISSION_DENIED") {
      return "You no longer have permission to add context to a chat.";
    }
  }
  return "The selected records could not be transferred. Your table selection is unchanged.";
}

export function useAddToChatController({
  contextRefs,
  onTransferred,
  source,
}: {
  contextRefs: readonly ChatContextRef[];
  onTransferred: () => void;
  source: ChatContextHandoff["source"];
}) {
  const repositories = useChatRepositories();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [projects, setProjects] = useState<SidebarProject[]>([]);
  const [query, setQuery] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedThreadId, setSelectedThreadId] = useState(NEW_CHAT_DESTINATION);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );
  const visibleProjects = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return projects;
    return projects.filter((project) =>
      [project.title, ...project.conversations.map((thread) => thread.title)]
        .join(" ")
        .toLocaleLowerCase()
        .includes(normalized),
    );
  }, [projects, query]);

  const loadDestinations = useCallback(async () => {
    const collected: SidebarProject[] = [];
    let cursor: string | undefined;
    do {
      const page = await repositories.sidebar.list({ cursor, limit: 100 });
      collected.push(...page.data);
      cursor = page.meta.nextCursor ?? undefined;
    } while (cursor);
    setProjects(collected);
    const first = collected[0];
    setSelectedProjectId(first?.id ?? "");
    setSelectedThreadId(
      first?.conversations.find((thread) => thread.status !== "archived")?.id ??
        NEW_CHAT_DESTINATION,
    );
  }, [repositories.sidebar]);

  const show = useCallback(() => {
    if (!contextRefs.length || repositories.transport.mode !== "http") return;
    setOpen(true);
    setError(null);
    setLoading(true);
    void loadDestinations()
      .catch((failure) => setError(addToChatFailureMessage(failure)))
      .finally(() => setLoading(false));
  }, [contextRefs.length, loadDestinations, repositories.transport.mode]);

  const close = useCallback(() => {
    if (submitting) return;
    setOpen(false);
    setError(null);
    setQuery("");
  }, [submitting]);

  const chooseProject = useCallback(
    (projectId: string) => {
      setSelectedProjectId(projectId);
      const project = projects.find((item) => item.id === projectId);
      setSelectedThreadId(
        project?.conversations.find((thread) => thread.status !== "archived")?.id ??
          NEW_CHAT_DESTINATION,
      );
      setError(null);
    },
    [projects],
  );

  const transfer = useCallback(async () => {
    if (!selectedProjectId || !contextRefs.length || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const existingThreadId =
        selectedThreadId === NEW_CHAT_DESTINATION ? undefined : selectedThreadId;
      const prepared = await repositories.composerContext.prepare({
        projectId: selectedProjectId,
        threadId: existingThreadId,
        contextRefs,
      });
      const thread = existingThreadId
        ? selectedProject?.conversations.find((item) => item.id === existingThreadId)
        : await repositories.threads.create({
            idempotencyKey: newIdempotencyKey("add-to-chat-thread"),
            projectId: selectedProjectId,
            title: null,
          });
      const threadId = existingThreadId ?? thread?.id;
      if (!threadId) throw new Error("the selected chat destination is unavailable");
      const handoff = createChatContextHandoff({
        entities: prepared.entities,
        projectId: selectedProjectId,
        source,
        threadId,
      });
      writeChatContextHandoff(window.sessionStorage, handoff);

      // This is the transfer commit point: from here the restorable composer draft, not the
      // originating table, is the visible source of truth.
      onTransferred();
      setOpen(false);
      router.push(
        projectChatHref(selectedProjectId, threadId, {
          handoff: handoff.handoffId,
        }),
      );
    } catch (failure) {
      setError(addToChatFailureMessage(failure));
    } finally {
      setSubmitting(false);
    }
  }, [
    contextRefs,
    onTransferred,
    repositories.composerContext,
    repositories.threads,
    router,
    selectedProject,
    selectedProjectId,
    selectedThreadId,
    source,
    submitting,
  ]);

  return {
    chooseProject,
    close,
    error,
    loading,
    open,
    projects: visibleProjects,
    query,
    selectedProject,
    selectedProjectId,
    selectedThreadId,
    setQuery,
    setSelectedThreadId,
    show,
    submitting,
    transfer,
  };
}

export type AddToChatController = ReturnType<typeof useAddToChatController>;
