"use client";

import { useCallback, useState } from "react";
import { useChatRepositories } from "../data/projects-transport";
import type { ChatContextRef } from "../model/chat-context-handoff";
import type { ProjectEntity } from "../model/project-workspace";
import { addToChatFailureMessage } from "./use-add-to-chat-controller";

/**
 * "Add to chat" from a surface that already sits beside the chat it targets —
 * the project Target accounts tab.
 *
 * The global Accounts table's action (`useAddToChatController`) must ask WHERE:
 * it opens a destination picker, stores a handoff and navigates there. Here the
 * destination is the open project chat, so the same server preparation runs
 * (`composer-context/prepare` validates every reference and pins its version)
 * and the prepared entities go straight to the composer through `onAdded` — no
 * dialog, no handoff record, no navigation. A refusal is worded by the same
 * `addToChatFailureMessage` the dialog shows, handed to `onFailed`.
 */
export function useAddToOpenChatController({
  onAdded,
  onFailed,
  projectId,
  threadId,
}: {
  onAdded: (entities: readonly ProjectEntity[]) => void;
  onFailed: (message: string) => void;
  projectId: string;
  /** The open thread; absent on a threadless project page, where the composer's first send creates it. */
  threadId?: string;
}) {
  const repositories = useChatRepositories();
  const [submitting, setSubmitting] = useState(false);
  // Like the table's handoff, preparation exists only against the real backend.
  const available = repositories.transport.mode === "http";

  const add = useCallback(
    async (contextRefs: readonly ChatContextRef[]) => {
      if (!contextRefs.length || !available || submitting) return false;
      setSubmitting(true);
      try {
        const prepared = await repositories.composerContext.prepare({
          contextRefs,
          projectId,
          threadId,
        });
        onAdded(prepared.entities);
        return true;
      } catch (failure) {
        onFailed(addToChatFailureMessage(failure));
        return false;
      } finally {
        setSubmitting(false);
      }
    },
    [available, onAdded, onFailed, projectId, repositories.composerContext, submitting, threadId],
  );

  return { add, available, submitting };
}

export type AddToOpenChatController = ReturnType<typeof useAddToOpenChatController>;
