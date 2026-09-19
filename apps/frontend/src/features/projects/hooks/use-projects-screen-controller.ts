"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useChatRepositories } from "../data/projects-transport";
import { newIdempotencyKey } from "../data/chat-api";
import {
  filterDirectory,
  projectHomeHref,
  sortDirectory,
  type DirectoryProject,
  type DirectorySort,
} from "../model/project-directory";
import type { ProjectMemoryNote } from "../model/project-memory";
import type { ChatThread } from "../model/chat-thread";
import type { ProjectWorkspace } from "../model/project-workspace";
import { useProjectCatalogInvalidation } from "../model/project-catalog-invalidation";

/**
 * The projects directory and the project home, over the real seams.
 *
 * The dummy screen read one client-side `ProjectDirectory` blob that carried a
 * project's chats, instructions and memory inline. Nothing here does: the
 * directory listing, the workspace shell, the thread page, the instructions
 * document and the scope-memory notes are five independent reads through five
 * repositories, and this controller is the one place they are joined. The views
 * therefore read `chats`/`instructions`/`memory` off the controller rather than
 * off a project record — a binding change, never a render change.
 */

type DialogState = {
  kind: "create" | "details" | "instructions" | "memory";
  projectId?: string;
  entryId?: string;
} | null;

export const PAGE_SIZE = 12;

/** The grid's one visibility rule: the shelf, then the search, then the order. */
export function visibleProjects(
  all: readonly DirectoryProject[],
  view: { filter: string; query: string; sort: DirectorySort },
) {
  return sortDirectory(
    filterDirectory(
      all.filter((project) =>
        view.filter === "archived"
          ? project.status === "archived"
          : project.status === "active",
      ),
      view.query,
    ),
    view.sort,
  );
}

export function paginate<T>(items: readonly T[], page: number) {
  return items.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
}

export function useProjectsScreenController(projectId?: string) {
  const repositories = useChatRepositories();
  const router = useRouter();
  const catalog = useProjectCatalogInvalidation();
  const navigationPending = useRef(false);
  const [all, setAll] = useState<DirectoryProject[] | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [shell, setShell] = useState<ProjectWorkspace | null>(null);
  const [chats, setChats] = useState<ChatThread[]>([]);
  const [instructions, setInstructions] = useState("");
  const [instructionsRevision, setInstructionsRevision] = useState<number | null>(
    null,
  );
  const [memory, setMemory] = useState<ProjectMemoryNote[]>([]);
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [filter, setFilter] = useState("active");
  const [sort, setSort] = useState<DirectorySort>("updated");
  const [dialog, setDialog] = useState<DialogState>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [text, setText] = useState("");
  const [sourceChatId, setSourceChatId] = useState("");
  const [prompt, setPrompt] = useState("");
  const [modelId, setModelId] = useState("");
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const [page, setPage] = useState(1);

  const message = (failure: unknown) =>
    failure instanceof Error ? failure.message : "Projects could not be saved.";

  const load = useCallback(async () => {
    try {
      const [active, archived] = await Promise.all([
        repositories.directory.listAll("active"),
        repositories.directory.listAll("archived"),
      ]);
      setAll([...active, ...archived]);
      if (projectId) {
        const [workspace, threads, instr, notes] = await Promise.all([
          repositories.projects.get(projectId),
          repositories.threads.list({ projectId, status: "active", limit: 50 }),
          repositories.instructions.get(projectId),
          // A workspace with scoped memory switched off is not a failed read:
          // the rail shows its honest empty state. Every other failure is shown.
          repositories.memory
            .list(projectId)
            .catch((failure: Error & { code?: string }) =>
              failure.code === "MEMORY_DISABLED" ? [] : Promise.reject(failure),
            ),
        ]);
        setShell(workspace);
        setChats(
          [...threads.threads].sort((a, b) =>
            b.updatedAt.localeCompare(a.updatedAt),
          ),
        );
        setInstructions(instr?.body ?? "");
        setInstructionsRevision(instr?.revision ?? null);
        setMemory(notes);
      }
      setError(null);
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Projects could not be loaded. Please try again.",
      );
    } finally {
      setLoaded(true);
    }
  }, [projectId, repositories]);

  useEffect(() => {
    // Awaited inside the effect rather than called from its body: every write
    // `load` performs is behind its first await, which is also what
    // `react-hooks/set-state-in-effect` needs to see (the sidebar catalog's
    // reload does the same).
    void (async () => {
      await load();
    })();
  }, [load, catalog.revision]);

  const project = useMemo(
    () => all?.find((item) => item.id === projectId),
    [all, projectId],
  );
  const dialogProject = useMemo(
    () => all?.find((item) => item.id === dialog?.projectId),
    [all, dialog],
  );
  const visible = useMemo(
    () => visibleProjects(all ?? [], { filter, query, sort }),
    [all, filter, query, sort],
  );

  async function run<T>(act: () => Promise<T>): Promise<T> {
    if (busy) throw new Error("Please wait for the current project change to finish.");
    setBusy(true);
    setError(null);
    try {
      const result = await act();
      await load();
      catalog.invalidate();
      return result;
    } catch (failure) {
      setError(message(failure));
      throw failure;
    } finally {
      setBusy(false);
    }
  }

  function openDialog(
    kind: NonNullable<DialogState>["kind"],
    target?: DirectoryProject,
    entryId?: string,
  ) {
    setError(null);
    setDialog({ kind, projectId: target?.id, entryId });
    setName(target?.title ?? "");
    setDescription(target?.description ?? "");
    const entry = memory.find((note) => note.id === entryId);
    setText(kind === "instructions" ? instructions : (entry?.text ?? ""));
    setSourceChatId(entry?.sourceThreadId ?? "");
  }

  async function saveDialog() {
    if (!dialog || busy || navigationPending.current) return;
    try {
      if (dialog.kind === "create") {
        navigationPending.current = true;
        // One home read, not two: the brand a blank project is born under is
        // the open shell's, then the directory's, then the workspace default.
        const brandId =
          shell?.brandId ??
          all?.[0]?.brandId ??
          (await (async () => {
            const home = await repositories.home.get();
            return home.defaultBrandId ?? home.brands[0]?.id ?? "";
          })());
        const created = await run(() =>
          repositories.directory.create({
            brandId,
            title: name,
            description,
            idempotencyKey: newIdempotencyKey("blank-project"),
          }),
        );
        setDialog(null);
        router.push(projectHomeHref(created.id));
        return;
      }
      if (!dialog.projectId) return;
      const id = dialog.projectId;
      if (dialog.kind === "details") {
        await run(() => repositories.directory.update(id, { title: name, description }));
      }
      if (dialog.kind === "instructions") {
        await run(() =>
          repositories.instructions.save(id, {
            body: text,
            expectedRevision: instructionsRevision,
          }),
        );
      }
      if (dialog.kind === "memory") {
        await run(() =>
          dialog.entryId
            ? repositories.memory.edit(id, dialog.entryId, {
                text,
                sourceThreadId: sourceChatId || undefined,
              })
            : repositories.memory.add(id, {
                text,
                sourceThreadId: sourceChatId || undefined,
              }),
        );
      }
      setDialog(null);
    } catch {
      navigationPending.current = false;
      /* Preserve the draft and expose the save error. */
    }
  }

  async function newChat(id: string, draft = "", contextIds: string[] = []) {
    /* Task 12 */ void id;
    void draft;
    void contextIds;
  }

  function mutate(type: "pin" | "archive", id: string) {
    const target = all?.find((item) => item.id === id);
    if (!target) return;
    void run(() =>
      type === "pin"
        ? repositories.directory.update(id, { pinned: !target.pinned })
        : repositories.directory.setArchived(id, target.status !== "archived"),
    ).catch(() => undefined);
  }

  const models = shell?.models ?? [];
  return {
    loaded,
    data: all,
    error,
    busy,
    retry: load,
    clearError: () => setError(null),
    project,
    projectId,
    shell,
    chats,
    instructions,
    memory,
    dialog,
    dialogProject,
    name,
    description,
    text,
    sourceChatId,
    setName,
    setDescription,
    setText,
    setSourceChatId,
    openDialog,
    saveDialog,
    closeDialog() {
      if (!busy) setDialog(null);
    },
    projects: paginate(visible, page),
    total: visible.length,
    page,
    setPage,
    query,
    filter,
    sort,
    searchOpen,
    showSearch() {
      setSearchOpen(true);
    },
    setQuery(value: string) {
      setQuery(value);
      setPage(1);
    },
    setFilter(value: string) {
      setFilter(value);
      setPage(1);
    },
    setSort(value: string) {
      setSort(value as DirectorySort);
      setPage(1);
    },
    mutate,
    newChat,
    prompt,
    setPrompt,
    models,
    selectedModel: models.find((model) => model.id === modelId) ?? models[0],
    modelPickerOpen,
    selectModel(id: string) {
      setModelId(id);
      setModelPickerOpen(false);
    },
    toggleModelPicker() {
      setModelPickerOpen((open) => !open);
    },
    async removeMemory() {
      if (!dialog?.projectId || !dialog.entryId || busy) return;
      const { projectId: pid, entryId } = dialog;
      try {
        await run(() => repositories.memory.remove(pid, entryId));
        setDialog(null);
      } catch {
        /* Preserve the note and expose the save error. */
      }
    },
  };
}

export type ProjectsScreenController = ReturnType<
  typeof useProjectsScreenController
>;
