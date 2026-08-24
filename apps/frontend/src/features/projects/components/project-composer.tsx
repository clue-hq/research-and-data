"use client";

import { useCallback, useRef, useState } from "react";
import { Attachments } from "@/components/ai-elements/attachments";
import type { ProjectComposerAttachment as ProjectComposerAttachmentData } from "../model/project-composer";
import type {
  ProjectEntity,
  ProjectModelOption,
} from "../model/project-workspace";
import { ModelPicker } from "./model-picker";
import { ProjectComposerAttachment } from "./project-composer-attachment";
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
  entities = [],
  modelPickerOpen = false,
  models = [],
  onAttachmentFiles,
  onAttachmentRemove,
  onEntityRemove,
  onEntitySelect,
  onModelPickerToggle = NOOP,
  onModelSelect = NOOP,
  onPromptChange,
  onSubmit,
  prompt,
  sendDisabled = false,
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
  entities?: ProjectEntity[];
  modelPickerOpen?: boolean;
  models?: ProjectModelOption[];
  onAttachmentFiles?: (files: File[]) => void;
  onAttachmentRemove?: (attachmentId: string) => void;
  onEntityRemove?: (entityId: string) => void;
  onEntitySelect?: (entityId: string) => void;
  onModelPickerToggle?: () => void;
  onModelSelect?: (modelId: string) => void;
  onPromptChange: (value: string) => void;
  onSubmit: (value: string, entityIds: string[]) => boolean | Promise<boolean>;
  prompt: string;
  sendDisabled?: boolean;
  selectedEntities?: ProjectEntity[];
  selectedEntityIds?: string[];
  selectedModel?: ProjectModelOption;
  // Presentation-only (C-4, from the design's chat-composer): "home" widens
  // and repositions the pickers for the Home composer card.
  variant?: "default" | "home";
}) {
  const editorRef = useRef<ProjectComposerEditorHandle>(null);
  const [submitting, setSubmitting] = useState(false);
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
      if (disabled || sendDisabled || submitting) return;
      const currentPrompt =
        promptOverride ?? editorRef.current?.getPrompt() ?? prompt;
      const currentEntityIds = editorRef.current?.getEntityIds() ?? [];
      if (!currentPrompt.trim() && !currentEntityIds.length && !attachments.length) {
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
    [attachments.length, disabled, onSubmit, prompt, sendDisabled, submitting],
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
      onSubmit={(event) => {
        event.preventDefault();
        void submitCurrentDraft();
      }}
    >
      <div className={styles.composerBody}>
        {attachments.length && onAttachmentRemove ? (
          <Attachments className={styles.composerAttachments} variant="inline">
            {attachments.map((attachment) => (
              <ProjectComposerAttachment
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
          disabled={disabled || submitting}
          entities={entities}
          onContextChange={handleContextChange}
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
                accept={
                  attachmentAccept ??
                  ".csv,.doc,.docx,.gif,.jpeg,.jpg,.pdf,.png,.webp,.xls,.xlsx"
                }
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
              aria-label="Add account or contact context"
              aria-haspopup="listbox"
              className={styles.contextButton}
              disabled={disabled}
              onClick={() => editorRef.current?.openMentionPicker()}
              title="Add account or contact context"
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
            aria-label="Send"
            className={styles.sendButton}
            disabled={
              disabled ||
              sendDisabled ||
              submitting ||
              (!prompt.trim() && !selectedEntities.length && !attachments.length)
            }
            type="submit"
          >
            <ProjectIcon name="arrow-up" size={16} />
          </button>
        </div>
      </div>
    </form>
  );
}
