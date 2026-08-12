"use client";

import type { AddToChatController } from "../hooks/use-add-to-chat-controller";
import { NEW_CHAT_DESTINATION } from "../hooks/use-add-to-chat-controller";
import { ProjectIcon } from "./project-icon";

export function AddToChatDialog({
  controller,
  selectedCount,
  subjectLabel,
}: {
  controller: AddToChatController;
  selectedCount: number;
  subjectLabel: "Accounts" | "Contacts";
}) {
  if (!controller.open) return null;

  return (
    <div
      className="fixed inset-0 z-[110] flex items-center justify-center bg-[#111827]/20 p-4 backdrop-blur-[1px]"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) controller.close();
      }}
    >
      <section
        aria-labelledby="add-to-chat-title"
        aria-modal="true"
        aria-busy={controller.loading || controller.submitting}
        className="flex max-h-[min(680px,calc(100vh-32px))] w-full max-w-[560px] flex-col overflow-hidden rounded-xl border-[0.5px] border-[var(--clue-border-neutral)] bg-white shadow-[0_18px_60px_rgba(0,24,62,0.18)]"
        onKeyDown={(event) => {
          if (event.key === "Escape") controller.close();
        }}
        role="dialog"
      >
        <header className="flex items-start justify-between gap-4 border-b-[0.5px] border-[var(--clue-border-neutral)] px-5 py-4">
          <div>
            <h2 className="text-[16px] font-medium" id="add-to-chat-title">
              Add {selectedCount} {subjectLabel} to chat
            </h2>
            <p className="mt-1 text-[13px] text-[var(--clue-content-subtle)]">
              Choose where to prepare the next message. Nothing runs until you send it.
            </p>
          </div>
          <button
            aria-label="Close Add to Chat"
            className="flex size-7 items-center justify-center rounded-md hover:bg-[var(--clue-background-hover)]"
            disabled={controller.submitting}
            onClick={controller.close}
            type="button"
          >
            <ProjectIcon name="close" size={14} />
          </button>
        </header>

        <div className="min-h-0 overflow-y-auto p-5">
          <label className="flex h-9 items-center gap-2 rounded-lg border-[0.5px] border-[var(--clue-border-input)] bg-[var(--clue-background-hover)] px-3">
            <ProjectIcon name="search" size={13} />
            <span className="sr-only">Search projects and chats</span>
            <input
              autoFocus
              className="min-w-0 flex-1 bg-transparent text-[13px] outline-none"
              onChange={(event) => controller.setQuery(event.target.value)}
              placeholder="Search projects and chats"
              value={controller.query}
            />
          </label>

          {controller.loading ? (
            <p className="py-8 text-center text-[13px] text-[var(--clue-content-subtle)]" role="status">
              Loading chat destinations…
            </p>
          ) : controller.projects.length ? (
            <div className="mt-4 grid gap-2">
              {controller.projects.map((project) => (
                <button
                  aria-pressed={controller.selectedProjectId === project.id}
                  className={`rounded-lg border-[0.5px] px-3 py-2.5 text-left transition-colors ${
                    controller.selectedProjectId === project.id
                      ? "border-[var(--clue-content-neutral)] bg-[var(--clue-background-hover)]"
                      : "border-[var(--clue-border-neutral)] hover:bg-[var(--clue-background-hover)]"
                  }`}
                  key={project.id}
                  onClick={() => controller.chooseProject(project.id)}
                  type="button"
                >
                  <span className="block text-[13px] font-medium">{project.title}</span>
                  <span className="mt-0.5 block text-[12px] text-[var(--clue-content-subtle)]">
                    {project.conversations.filter((thread) => thread.status !== "archived").length} active chats
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <p className="py-8 text-center text-[13px] text-[var(--clue-content-subtle)]">
              No writable project destination was found.
            </p>
          )}

          {controller.selectedProject ? (
            <fieldset className="mt-5">
              <legend className="mb-2 text-[12px] font-medium text-[var(--clue-content-subtle)]">
                Chat in {controller.selectedProject.title}
              </legend>
              <select
                aria-label="Chat destination"
                className="h-9 w-full rounded-lg border-[0.5px] border-[var(--clue-border-input)] bg-white px-3 text-[13px]"
                onChange={(event) => controller.setSelectedThreadId(event.target.value)}
                value={controller.selectedThreadId}
              >
                <option value={NEW_CHAT_DESTINATION}>New chat</option>
                {controller.selectedProject.conversations
                  .filter((thread) => thread.status !== "archived")
                  .map((thread) => (
                    <option key={thread.id} value={thread.id}>
                      {thread.title}
                    </option>
                  ))}
              </select>
            </fieldset>
          ) : null}

          {controller.error ? (
            <p className="mt-4 rounded-lg bg-[var(--clue-background-hover)] px-3 py-2 text-[13px]" role="alert">
              {controller.error}
            </p>
          ) : null}
        </div>

        <footer className="flex items-center justify-end gap-2 border-t-[0.5px] border-[var(--clue-border-neutral)] px-5 py-3">
          <button
            className="h-8 rounded-md px-3 text-[13px] hover:bg-[var(--clue-background-hover)]"
            disabled={controller.submitting}
            onClick={controller.close}
            type="button"
          >
            Cancel
          </button>
          <button
            className="h-8 rounded-md bg-[var(--clue-content-neutral)] px-3 text-[13px] text-white disabled:cursor-not-allowed disabled:opacity-50"
            disabled={
              controller.loading ||
              controller.submitting ||
              !controller.selectedProjectId
            }
            onClick={() => void controller.transfer()}
            type="button"
          >
            {controller.submitting ? "Preparing…" : "Add to chat"}
          </button>
        </footer>
      </section>
    </div>
  );
}
