"use client";

import { useCallback, useRef, useState } from "react";
import { SquareIcon } from "lucide-react";
import { composerAction, hasComposerDraft } from "../model/composer-action";
import { CHAT_ATTACHMENT_ACCEPT } from "../model/chat-attachments";
import { Attachments } from "@/components/ai-elements/attachments";
import type { ProjectComposerAttachment as ProjectComposerAttachmentData } from "../model/project-composer";
import type {
  ProjectEntity,
  ProjectModelOption,
} from "../model/project-workspace";
import { ModelPicker } from "./model-picker";
import { ChatAttachment } from "./chat-attachment";
import {
  ProjectComposerEditor,
  type ProjectComposerEditorHandle,
} from "./project-composer-editor";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

const NOOP = () => undefined;

export function ProjectComposer({
  attachmentAccept,
  attachmentError,
  attachmentInputDisabled = false,
  attachmentLabel = "Attach files",
  attachments = [],
  disabled = false,
  dropActive = false,
  entities = [],
  modelPickerOpen = false,
  models = [],
  onAttachmentFiles,
  onAttachmentRemove,
  onEntityRemove,
  onEntitySelect,
  onModelPickerToggle = NOOP,
  onMentionQueryChange,
  onModelSelect = NOOP,
  onPromptChange,
  onSubmit,
  onStop,
  running = false,
  stopping = false,
  prompt,
  sendDisabled = false,
  submittableWithoutPrompt = false,
  selectedEntities = [],
  selectedEntityIds = [],
  selectedModel,
  variant = "default",
}: {
  attachmentAccept?: string;
  attachmentError?: string | null;
  attachmentInputDisabled?: boolean;
  attachmentLabel?: string;
  attachments?: ProjectComposerAttachmentData[];
  disabled?: boolean;
  /** A file drag is over the surface that owns this composer (task 14, ruling
   * 5): the only feedback is the dashed outline the CSS draws off
   * `data-drop-target`. The drop itself is the owner's — this stays presentational. */
  dropActive?: boolean;
  entities?: ProjectEntity[];
  modelPickerOpen?: boolean;
  models?: ProjectModelOption[];
  onAttachmentFiles?: (files: File[]) => void;
  onAttachmentRemove?: (attachmentId: string) => void;
  onEntityRemove?: (entityId: string) => void;
  onEntitySelect?: (entityId: string) => void;
  /** Present when the @ directory was too large to load whole: the server is asked as the user types. */
  onMentionQueryChange?: (query: string) => void;
  onModelPickerToggle?: () => void;
  onModelSelect?: (modelId: string) => void;
  onPromptChange: (value: string) => void;
  onSubmit: (value: string, entityIds: string[]) => boolean | Promise<boolean>;
  onStop?: () => void;
  running?: boolean;
  stopping?: boolean;
  prompt: string;
  sendDisabled?: boolean;
  /** Web annotations (slice 2, R-A2): the caller is carrying context that IS
   * the message — numbered annotation chips above the composer — so an empty
   * box is a legitimate send, and the turn's text is the caller's to decide.
   * Defaults false: every other composer keeps its "type something" rule. */
  submittableWithoutPrompt?: boolean;
  selectedEntities?: ProjectEntity[];
  selectedEntityIds?: string[];
  selectedModel?: ProjectModelOption;
  // Presentation-only (C-4, from the design's chat-composer): "home" widens
  // and repositions the pickers for the Home composer card.
  variant?: "default" | "home";
}) {
  const editorRef = useRef<ProjectComposerEditorHandle>(null);
  const [submitting, setSubmitting] = useState(false);
  const action = composerAction({ running: running && Boolean(onStop), stopping,
    // An annotation-only turn (web lane) is a draft even with an empty prompt.
    hasDraft: hasComposerDraft(prompt, selectedEntityIds, attachments) || submittableWithoutPrompt,
    disabled, sendDisabled, submitting });
  const handleContextChange = useCallback(
    (entityIds: string[]) => {
      selectedEntityIds
        .filter((entityId) => !entityIds.includes(entityId))
        .forEach((entityId) => onEntityRemove?.(entityId));
      entityIds
        .filter((entityId) => !selectedEntityIds.includes(entityId))
        .forEach((entityId) => onEntitySelect?.(entityId));
    },
    [onEntityRemove, onEntitySelect, selectedEntityIds],
  );
  const submitCurrentDraft = useCallback(
    async (promptOverride?: string) => {
      if (disabled || sendDisabled || submitting || stopping) return;
      const currentPrompt =
        promptOverride ?? editorRef.current?.getPrompt() ?? prompt;
      const currentEntityIds = editorRef.current?.getEntityIds() ?? [];
      if (
        !hasComposerDraft(currentPrompt, currentEntityIds, attachments) &&
        !submittableWithoutPrompt
      ) {
        return;
      }

      setSubmitting(true);
      try {
        const accepted = await onSubmit(currentPrompt, currentEntityIds);
        if (!accepted) return;
        editorRef.current?.clearSubmittedDraft(currentPrompt, currentEntityIds);
      } finally {
        setSubmitting(false);
      }
    },
    [
      attachments,
      disabled,
      onSubmit,
      prompt,
      sendDisabled,
      stopping,
      submittableWithoutPrompt,
      submitting,
    ],
  );

  return (
    <form
      className={[
        styles.composer,
        attachments.length ? styles.composerWithAttachments : "",
        variant === "home" ? styles.composerHome : "",
      ]
        .filter(Boolean)
        .join(" ")}
      data-drop-target={dropActive || undefined}
      onSubmit={(event) => {
        event.preventDefault();
        void submitCurrentDraft();
      }}
    >
      <div className={styles.composerBody}>
        {attachments.length && onAttachmentRemove ? (
          <Attachments className={styles.composerAttachments} variant="inline">
            {attachments.map((attachment) => (
              <ChatAttachment
                attachment={attachment}
                key={attachment.id}
                onRemove={onAttachmentRemove}
              />
            ))}
          </Attachments>
        ) : null}
        {attachmentError ? (
          <p className={styles.composerAttachmentError} role="alert">
            {attachmentError}
          </p>
        ) : null}
        <ProjectComposerEditor
          categoriesEnabled={variant !== "home"}
          disabled={disabled || submitting}
          entities={entities}
          onContextChange={handleContextChange}
          onMentionQueryChange={onMentionQueryChange}
          onPromptChange={onPromptChange}
          onSubmit={(value) => {
            void submitCurrentDraft(value);
          }}
          prompt={prompt}
          ref={editorRef}
          selectedEntities={selectedEntities}
          selectedEntityIds={selectedEntityIds}
        />
      </div>
      <div className={styles.composerFooter}>
        <div className={styles.composerPickerAnchor}>
          {onAttachmentFiles ? (
            <label aria-label={attachmentLabel} className={styles.iconButton}>
              <input
                accept={attachmentAccept ?? CHAT_ATTACHMENT_ACCEPT}
                disabled={disabled || submitting || attachmentInputDisabled}
                multiple
                onChange={(event) => {
                  onAttachmentFiles(Array.from(event.target.files ?? []));
                  event.target.value = "";
                }}
                type="file"
              />
              <ProjectIcon name="plus" size={14} />
            </label>
          ) : null}
          {onEntitySelect ? (
            <button
              aria-label="Add context"
              aria-haspopup="listbox"
              className={styles.contextButton}
              disabled={disabled}
              onClick={() => editorRef.current?.openMentionPicker()}
              title="Add context"
              type="button"
            >
              @
            </button>
          ) : null}
        </div>
        <div className={styles.composerActions}>
          {selectedModel && models.length ? (
            <div className={styles.modelAnchor}>
              <button
                aria-expanded={modelPickerOpen}
                className={styles.modelButton}
                onClick={onModelPickerToggle}
                type="button"
              >
                {selectedModel.shortLabel}
                <ProjectIcon name="chevron-down" size={12} />
              </button>
              {modelPickerOpen ? (
                <ModelPicker
                  models={models}
                  onSelect={onModelSelect}
                  selectedModelId={selectedModel.id}
                />
              ) : null}
            </div>
          ) : null}
          <button
            aria-label={action.kind === "stop" ? "Stop response" : "Send message"}
            aria-busy={stopping || submitting || undefined}
            className={styles.sendButton}
            disabled={action.disabled}
            onClick={action.kind === "stop" ? onStop : undefined}
            type={action.kind === "stop" ? "button" : "submit"}
          >
            {action.kind === "stop" ? <SquareIcon aria-hidden="true" size={12} fill="currentColor" strokeWidth={0} /> : <ProjectIcon name="arrow-up" size={16} />}
          </button>
        </div>
      </div>
    </form>
  );
}
