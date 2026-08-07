"use client";

import { useCallback, useRef } from "react";
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

export function ProjectComposer({
  attachments = [],
  disabled = false,
  entities = [],
  modelPickerOpen,
  models,
  onAttachmentFiles,
  onAttachmentRemove,
  onEntityRemove,
  onEntitySelect,
  onModelPickerToggle,
  onModelSelect,
  onPromptChange,
  onSubmit,
  prompt,
  selectedEntities = [],
  selectedEntityIds = [],
  selectedModel,
}: {
  attachments?: ProjectComposerAttachmentData[];
  disabled?: boolean;
  entities?: ProjectEntity[];
  modelPickerOpen: boolean;
  models: ProjectModelOption[];
  onAttachmentFiles?: (files: File[]) => void;
  onAttachmentRemove?: (attachmentId: string) => void;
  onEntityRemove?: (entityId: string) => void;
  onEntitySelect?: (entityId: string) => void;
  onModelPickerToggle: () => void;
  onModelSelect: (modelId: string) => void;
  onPromptChange: (value: string) => void;
  onSubmit: (value?: string, entityIds?: string[]) => void;
  prompt: string;
  selectedEntities?: ProjectEntity[];
  selectedEntityIds?: string[];
  selectedModel: ProjectModelOption;
}) {
  const editorRef = useRef<ProjectComposerEditorHandle>(null);
  const sendButtonRef = useRef<HTMLButtonElement>(null);
  const handleDraftChange = useCallback((hasContent: boolean) => {
    if (sendButtonRef.current) {
      sendButtonRef.current.disabled = disabled || !hasContent;
    }
  }, [disabled]);
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

  return (
    <form
      className={[
        styles.composer,
        attachments.length ? styles.composerWithAttachments : "",
      ]
        .filter(Boolean)
        .join(" ")}
      onSubmit={(event) => {
        event.preventDefault();
        const currentPrompt = editorRef.current?.getPrompt() ?? prompt;
        const currentEntityIds = editorRef.current?.getEntityIds() ?? [];
        if (!currentPrompt.trim() && !currentEntityIds.length) return;
        onSubmit(currentPrompt, currentEntityIds);
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
        <ProjectComposerEditor
          disabled={disabled}
          entities={entities}
          onContextChange={handleContextChange}
          onDraftChange={handleDraftChange}
          onPromptChange={onPromptChange}
          onSubmit={(value) =>
            onSubmit(value, editorRef.current?.getEntityIds() ?? [])
          }
          prompt={prompt}
          ref={editorRef}
          selectedEntities={selectedEntities}
          selectedEntityIds={selectedEntityIds}
        />
      </div>
      <div className={styles.composerFooter}>
        <div className={styles.composerPickerAnchor}>
          <label aria-label="Attach files" className={styles.iconButton}>
            <input
              accept=".csv,.doc,.docx,.gif,.jpeg,.jpg,.pdf,.png,.webp,.xls,.xlsx"
              disabled={disabled || !onAttachmentFiles}
              multiple
              onChange={(event) => {
                onAttachmentFiles?.(Array.from(event.target.files ?? []));
                event.target.value = "";
              }}
              type="file"
            />
            <ProjectIcon name="plus" size={14} />
          </label>
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
          <button
            aria-label="Send"
            className={styles.sendButton}
            disabled={disabled || (!prompt.trim() && !selectedEntities.length)}
            ref={sendButtonRef}
            type="submit"
          >
            <ProjectIcon name="arrow-up" size={16} />
          </button>
        </div>
      </div>
    </form>
  );
}
