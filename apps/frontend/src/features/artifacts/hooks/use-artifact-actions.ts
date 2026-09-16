"use client";

import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { projectChatHref } from "@/features/chat-shell/model/chat-shell-routes";
import type {
  ImageExportFormat,
  ImageExportScale,
} from "@/features/chat-shell/model/image-export";
import { useChatRepositories } from "@/features/projects/data/projects-transport";
import {
  exportAdArtifact,
  exportWebArtifact,
  renameArtifactDocument,
  setArtifactArchived,
} from "../data/artifact-document.repository";
import { recordArtifactViewed, setArtifactSaved } from "../data/artifact-marks.repository";
import type { LibraryArtifact } from "../model/artifact-library";

/**
 * Artifacts page (2026-09-15): every write the library screen makes, and the
 * one place any of them is caught. The screen itself never try/catches — it
 * reads `notice` and `busy` — so a refusal always reaches the operator as a
 * sentence and the console as `[artifacts] …` with the original error, never
 * as a silent no-op.
 *
 * The server component owns the rows, so a successful write refreshes the
 * route (`router.refresh()`) rather than mutating a client copy: the saved and
 * archived state a card renders is always the state the backend recorded.
 */
export function useArtifactActions() {
  const router = useRouter();
  const repositories = useChatRepositories();
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const run = useCallback(
    async (work: () => Promise<string>, failure: string) => {
      setBusy(true);
      try {
        setNotice(await work());
        router.refresh();
        return true;
      } catch (error) {
        console.warn("[artifacts] the change was refused:", error);
        setNotice(failure);
        return false;
      } finally {
        setBusy(false);
      }
    },
    [router],
  );

  return {
    busy,
    notice,
    dismissNotice: () => setNotice(""),
    save: (artifact: LibraryArtifact, saved: boolean) =>
      run(async () => {
        await setArtifactSaved(artifact.id, saved);
        return saved ? "Added to saved artifacts." : "Removed from saved artifacts.";
      }, "Your change couldn’t be saved. Please try again."),
    archive: (artifact: LibraryArtifact, archived: boolean) =>
      run(async () => {
        await setArtifactArchived(artifact.documentId, archived);
        return archived
          ? "Artifact archived. You can restore it from Archived."
          : "Artifact restored.";
      }, "Your change couldn’t be saved. Please try again."),
    rename: (artifact: LibraryArtifact, title: string) =>
      run(async () => {
        await renameArtifactDocument(artifact.documentId, title);
        return "Artifact renamed.";
      }, "The new name couldn’t be saved. Please try again."),
    /**
     * The saved-document ad export. Deliberately NOT wrapped in `run`: the
     * export menu owns its own status line, so a refusal has to reach the
     * controller as the design API's own error rather than being turned into
     * a toast here. The dialog cannot call the repository itself — a
     * presentation component may not import one.
     */
    exportAd: (
      artifact: LibraryArtifact,
      options: { format: ImageExportFormat; scale: ImageExportScale },
    ) =>
      exportAdArtifact({
        documentId: artifact.documentId,
        title: artifact.title,
        format: options.format,
        scale: options.scale,
      }),
    /**
     * The web artifact's export: the design API's static-site zip. Written out
     * rather than run through `run` because an export changes no row — there is
     * nothing for `router.refresh()` to re-read — but it is still caught here,
     * because the dialog may not import a repository.
     */
    exportWeb: async (artifact: LibraryArtifact) => {
      setBusy(true);
      try {
        await exportWebArtifact(artifact.documentId, artifact.title);
        setNotice("Export downloaded.");
        return true;
      } catch (error) {
        console.warn("[artifacts] the export was refused:", error);
        setNotice("Export couldn’t be prepared. Please try again.");
        return false;
      } finally {
        setBusy(false);
      }
    },
    viewed: (artifact: LibraryArtifact) => {
      // A last-viewed mark is a courtesy, not the operator's action: it is not
      // awaited and never blocks the preview it accompanies.
      void recordArtifactViewed(artifact.id).catch((error: unknown) => {
        console.warn("[artifacts] the viewed mark was refused:", error);
        setNotice("Preview opened. Last viewed couldn’t be saved.");
      });
    },
    openEditor: async (artifact: LibraryArtifact) => {
      setBusy(true);
      try {
        const thread = await repositories.threads.create({
          idempotencyKey: crypto.randomUUID(),
          projectId: artifact.projectId,
          title: artifact.title,
        });
        router.push(
          projectChatHref(artifact.projectId, thread.id, {
            open: artifact.id,
            surface: artifact.kind,
          }),
        );
      } catch (error) {
        console.warn("[artifacts] opening a new chat was refused:", error);
        setNotice("Couldn’t open a new chat for this artifact. Please try again.");
        setBusy(false);
      }
    },
  };
}

export type ArtifactActions = ReturnType<typeof useArtifactActions>;
