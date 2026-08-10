"use client";

import Image from "next/image";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  createEditor,
  Editor,
  Element as SlateElement,
  Range as SlateRange,
  Transforms,
} from "slate";
import { withHistory } from "slate-history";
import {
  Editable,
  ReactEditor,
  Slate,
  type RenderElementProps,
  useFocused,
  useSelected,
  withReact,
} from "slate-react";
import type {
  ProjectComposerEditor as ProjectComposerEditorInstance,
  ProjectComposerMentionElement,
  ProjectComposerParagraphElement,
} from "../model/project-composer";
import {
  createComposerMention,
  createComposerValue,
  getComposerMentionIds,
  getComposerPromptText,
  removeSelectedComposerMention,
} from "../model/project-composer-editor";
import type { ProjectEntity } from "../model/project-workspace";
import { EntityPicker } from "./entity-picker";
import styles from "./project-flow.module.css";

export interface ProjectComposerEditorHandle {
  focus: () => void;
  getEntityIds: () => string[];
  getPrompt: () => string;
  openMentionPicker: () => void;
}

function withMentions(editor: ProjectComposerEditorInstance) {
  const { insertData, isInline, isVoid, markableVoid } = editor;

  editor.isInline = (element) =>
    element.type === "mention" ? true : isInline(element);
  editor.isVoid = (element) =>
    element.type === "mention" ? true : isVoid(element);
  editor.markableVoid = (element) =>
    element.type === "mention" ? true : markableVoid(element);
  editor.insertData = (data) => {
    const plainText = data.getData("text/plain");
    if (plainText) {
      Transforms.insertText(editor, plainText);
      return;
    }
    insertData(data);
  };

  return editor;
}

function ComposerMention({
  attributes,
  children,
  element,
}: RenderElementProps & { element: ProjectComposerMentionElement }) {
  const focused = useFocused();
  const selected = useSelected();

  return (
    <span
      {...attributes}
      aria-label={`${element.entityType === "account" ? "Account" : "Contact"} context: ${element.label}`}
      className={[
        styles.composerMention,
        selected && focused ? styles.composerMentionSelected : "",
      ]
        .filter(Boolean)
        .join(" ")}
      data-entity-id={element.entityId}
      data-entity-type={element.entityType}
      title={`${element.label} · ${element.secondaryLabel}`}
    >
      <div className={styles.composerMentionContent} contentEditable={false}>
        {children}
        <span className={styles.composerMentionVisual}>
          <Image
            alt=""
            aria-hidden="true"
            className={
              element.entityType === "contact" ? styles.composerMentionAvatar : ""
            }
            height={16}
            src={element.imagePath}
            width={16}
          />
          <span>{element.label}</span>
        </span>
      </div>
    </span>
  );
}

export const ProjectComposerEditor = forwardRef<
  ProjectComposerEditorHandle,
  {
    disabled?: boolean;
    entities: ProjectEntity[];
    onContextChange: (entityIds: string[]) => void;
    onDraftChange: (hasContent: boolean) => void;
    onPromptChange: (value: string) => void;
    onSubmit: (value: string) => void;
    prompt: string;
    selectedEntities: ProjectEntity[];
    selectedEntityIds: string[];
  }
>(function ProjectComposerEditor(
  {
    disabled = false,
    entities,
    onContextChange,
    onDraftChange,
    onPromptChange,
    onSubmit,
    prompt,
    selectedEntities,
    selectedEntityIds,
  },
  ref,
) {
  const [editor] = useState(() =>
    withMentions(withReact(withHistory(createEditor()))),
  );
  const initialValue = useMemo(
    () => createComposerValue(prompt, selectedEntities),
    // Slate reads this value only when the editor mounts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const [activeIndex, setActiveIndex] = useState(0);
  const [mentionIds, setMentionIds] = useState(selectedEntityIds);
  const [mentionTarget, setMentionTarget] = useState<SlateRange | null>(null);
  const [mentionQuery, setMentionQuery] = useState("");
  const lastEmittedPrompt = useRef(prompt);
  const lastMentionIds = useRef(selectedEntityIds);

  const closeMentionPicker = useCallback(() => {
    setMentionTarget(null);
    setActiveIndex(0);
    setMentionQuery("");
  }, []);

  const visibleEntities = useMemo(() => {
    const query = mentionQuery.trim().toLocaleLowerCase();
    if (!query) return entities;
    return entities.filter((entity) =>
      `${entity.label} ${entity.secondaryLabel} ${entity.accountName ?? ""}`
        .toLocaleLowerCase()
        .includes(query),
    );
  }, [entities, mentionQuery]);

  const replacePromptText = useCallback(
    (nextPrompt: string) => {
      const retainedMentions = Array.from(
        Editor.nodes(editor, {
          at: [],
          match: (node) =>
            SlateElement.isElement(node) && node.type === "mention",
        }),
        ([node]) => node as ProjectComposerMentionElement,
      );
      const children: ProjectComposerParagraphElement["children"] = [{ text: "" }];
      retainedMentions.forEach((mention) => {
        children.push(mention, { text: " " });
      });
      children.push({ text: nextPrompt });

      Editor.withoutNormalizing(editor, () => {
        Transforms.deselect(editor);
        if (editor.children.length) {
          Transforms.removeNodes(editor, { at: [0] });
        }
        Transforms.insertNodes(
          editor,
          { children, type: "paragraph" },
          { at: [0] },
        );
      });
      lastEmittedPrompt.current = nextPrompt;
      onDraftChange(Boolean(nextPrompt.trim() || retainedMentions.length));
    },
    [editor, onDraftChange],
  );

  const detectMentionTarget = useCallback(() => {
    const { selection } = editor;
    if (!selection || !SlateRange.isCollapsed(selection)) {
      closeMentionPicker();
      return;
    }

    const caret = selection.anchor;
    const paragraph = Editor.above(editor, {
      at: caret,
      match: (node) =>
        SlateElement.isElement(node) && node.type === "paragraph",
    });
    if (!paragraph) {
      closeMentionPicker();
      return;
    }

    const [, paragraphPath] = paragraph;
    const paragraphStart = Editor.start(editor, paragraphPath);
    const beforeRange = Editor.range(editor, paragraphStart, caret);
    const beforeText = Editor.string(editor, beforeRange);
    const mentionMatch = beforeText.match(/(?:^|\s)@([^\s@]*)$/);

    if (!mentionMatch) {
      closeMentionPicker();
      return;
    }

    const mentionText = `@${mentionMatch[1]}`;
    const targetStart = Editor.before(editor, caret, {
      distance: mentionText.length,
      unit: "character",
    });
    if (!targetStart) {
      closeMentionPicker();
      return;
    }

    setMentionTarget(Editor.range(editor, targetStart, caret));
    setActiveIndex(0);
    setMentionQuery(mentionMatch[1]);
  }, [closeMentionPicker, editor]);

  const insertMention = useCallback(
    (entity: ProjectEntity) => {
      ReactEditor.focus(editor);
      if (mentionTarget) {
        Transforms.select(editor, mentionTarget);
      } else if (!editor.selection) {
        Transforms.select(editor, Editor.end(editor, []));
      }

      if (lastMentionIds.current.includes(entity.id)) {
        if (mentionTarget) Transforms.delete(editor);
        closeMentionPicker();
        return;
      }

      Transforms.insertNodes(editor, createComposerMention(entity));
      Transforms.move(editor);
      Transforms.insertText(editor, " ");
      closeMentionPicker();
    },
    [closeMentionPicker, editor, mentionTarget],
  );

  useImperativeHandle(
    ref,
    () => ({
      focus() {
        ReactEditor.focus(editor);
      },
      getEntityIds() {
        return lastMentionIds.current;
      },
      getPrompt() {
        return lastEmittedPrompt.current;
      },
      openMentionPicker() {
        if (disabled) return;
        ReactEditor.focus(editor);
        if (!editor.selection) {
          Transforms.select(editor, Editor.end(editor, []));
        }
        Transforms.insertText(editor, "@");
      },
    }),
    [disabled, editor],
  );

  useEffect(() => {
    if (prompt === lastEmittedPrompt.current || ReactEditor.isFocused(editor)) {
      return;
    }
    replacePromptText(prompt);
  }, [editor, prompt, replacePromptText]);

  const renderElement = useCallback((props: RenderElementProps) => {
    if (props.element.type === "mention") {
      return (
        <ComposerMention
          {...props}
          element={props.element as ProjectComposerMentionElement}
        />
      );
    }

    return (
      <div {...props.attributes} className={styles.composerParagraph}>
        {props.children}
      </div>
    );
  }, []);

  return (
    <div className={styles.composerEditorShell}>
      <Slate
        editor={editor}
        initialValue={initialValue}
        onChange={(value) => {
          const nextPrompt = getComposerPromptText(value);
          const nextMentionIds = getComposerMentionIds(value);

          onDraftChange(Boolean(nextPrompt.trim() || nextMentionIds.length));
          lastMentionIds.current = nextMentionIds;
          setMentionIds((current) =>
            current.length === nextMentionIds.length &&
            current.every((id, index) => id === nextMentionIds[index])
              ? current
              : nextMentionIds,
          );

          if (nextPrompt !== lastEmittedPrompt.current) {
            lastEmittedPrompt.current = nextPrompt;
          }
          detectMentionTarget();
        }}
      >
        <Editable
          aria-label="Project prompt"
          className={styles.composerEditor}
          onBlur={() => {
            onPromptChange(lastEmittedPrompt.current);
            onContextChange(lastMentionIds.current);
          }}
          onKeyDown={(event) => {
            if (
              (event.key === "Backspace" || event.key === "Delete") &&
              editor.selection
            ) {
              if (removeSelectedComposerMention(editor)) {
                event.preventDefault();
                return;
              }
            }

            if (mentionTarget) {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setActiveIndex((current) =>
                  visibleEntities.length
                    ? (current + 1) % visibleEntities.length
                    : 0,
                );
                return;
              }
              if (event.key === "ArrowUp") {
                event.preventDefault();
                setActiveIndex((current) =>
                  visibleEntities.length
                    ? (current - 1 + visibleEntities.length) %
                      visibleEntities.length
                    : 0,
                );
                return;
              }
              if (
                (event.key === "Enter" || event.key === "Tab") &&
                visibleEntities[activeIndex]
              ) {
                event.preventDefault();
                insertMention(visibleEntities[activeIndex]);
                return;
              }
              if (event.key === "Escape") {
                event.preventDefault();
                closeMentionPicker();
                return;
              }
            }

            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              if (
                lastEmittedPrompt.current.trim() ||
                lastMentionIds.current.length
              ) {
                onSubmit(lastEmittedPrompt.current);
              }
            }
          }}
          placeholder="How can I help you?"
          readOnly={disabled}
          renderElement={renderElement}
          spellCheck
        />
      </Slate>
      {mentionTarget ? (
        <EntityPicker
          activeId={visibleEntities[activeIndex]?.id}
          entities={visibleEntities}
          onActiveChange={(entityId) => {
            const index = visibleEntities.findIndex(
              (entity) => entity.id === entityId,
            );
            if (index >= 0) setActiveIndex(index);
          }}
          onSelect={(entityId) => {
            const entity = visibleEntities.find((item) => item.id === entityId);
            if (entity) insertMention(entity);
          }}
          query={mentionQuery}
          selectedIds={mentionIds}
          showSearch={false}
        />
      ) : null}
    </div>
  );
});
