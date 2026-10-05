"use client";

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
import {
  accountTreeRows,
  COMPOSER_CATEGORIES,
  contactCountsByAccount,
  detectMentionQuery,
  entityCategory,
  searchComposerCatalog,
  shouldAutoCloseMention,
  type ComposerCategory,
} from "../model/composer-context-catalog";
import type {
  ProjectComposerEditor as ProjectComposerEditorInstance,
  ProjectComposerMentionElement,
  ProjectComposerParagraphElement,
} from "../model/project-composer";
import {
  clearSubmittedComposerDraft,
  createComposerMention,
  createComposerValue,
  getComposerMentionIds,
  getComposerPromptText,
  removeSelectedComposerMention,
} from "../model/project-composer-editor";
import type { ProjectEntity } from "../model/project-workspace";
import { EntityPicker } from "./entity-picker";
import { ChatMentionVisual } from "./chat-mention";
import styles from "./project-flow.module.css";

export interface ProjectComposerEditorHandle {
  clearSubmittedDraft: (
    prompt: string,
    entityIds: readonly string[],
  ) => boolean;
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

const MENTION_TYPE_LABELS: Record<
  ProjectComposerMentionElement["entityType"],
  string
> = {
  account: "Account",
  contact: "Contact",
  design_document: "Design",
  project_document: "File",
};

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
      aria-label={`${MENTION_TYPE_LABELS[element.entityType]} context: ${element.label}`}
      className={[
        styles.chatMention,
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
        <ChatMentionVisual
          entityType={element.entityType}
          icon={element.icon}
          imagePath={element.imagePath}
          label={element.label}
        />
      </div>
    </span>
  );
}

export const ProjectComposerEditor = forwardRef<
  ProjectComposerEditorHandle,
  {
    categoriesEnabled?: boolean;
    disabled?: boolean;
    entities: ProjectEntity[];
    onContextChange: (entityIds: string[]) => void;
    onMentionQueryChange?: (query: string) => void;
    onPromptChange: (value: string) => void;
    onSubmit: (value: string) => void;
    prompt: string;
    selectedEntities: ProjectEntity[];
    selectedEntityIds: string[];
  }
>(function ProjectComposerEditor(
  {
    categoriesEnabled = true,
    disabled = false,
    entities,
    onContextChange,
    onMentionQueryChange,
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
  const [mentionCategory, setMentionCategory] = useState<ComposerCategory | null>(
    null,
  );
  // Accounts whose contacts are unfolded beneath them in the Accounts list. Tagging an account
  // never depends on this: open or closed, Enter on the account row tags the account.
  const [expandedAccountIds, setExpandedAccountIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const lastEmittedPrompt = useRef(prompt);
  const lastMentionIds = useRef(selectedEntityIds);

  const closeMentionPicker = useCallback(() => {
    setMentionTarget(null);
    setActiveIndex(0);
    setMentionQuery("");
    setMentionCategory(null);
    setExpandedAccountIds(new Set());
  }, []);

  const toggleAccount = useCallback((accountId: string) => {
    setExpandedAccountIds((current) => {
      const next = new Set(current);
      if (next.has(accountId)) next.delete(accountId);
      else next.add(accountId);
      return next;
    });
  }, []);

  const resolveEntities = useCallback(
    (
      rawQuery: string,
      category: ComposerCategory | null,
      expanded: ReadonlySet<string>,
    ) => {
      const trimmed = rawQuery.trim();
      if (!categoriesEnabled) {
        const accounts = entities.filter(
          (entity) => entityCategory(entity) === "accounts",
        );
        return trimmed
          ? searchComposerCatalog(accounts, trimmed)
          : accountTreeRows(accounts, expanded);
      }
      // Typing searches flat across every category; browsing the Accounts category shows
      // the tree (accounts, each with its contacts unfolded on demand).
      if (trimmed) return searchComposerCatalog(entities, trimmed);
      if (category === "accounts") {
        return accountTreeRows(
          entities.filter((entity) => entityCategory(entity) === "accounts"),
          expanded,
        );
      }
      if (category) {
        return entities.filter((entity) => entityCategory(entity) === category);
      }
      return [];
    },
    [categoriesEnabled, entities],
  );

  const query = mentionQuery.trim();
  // A directory too large to load whole is also searched on the server; its matches arrive
  // as new `entities` and are found by the same local search, after the local matches.
  useEffect(() => {
    if (mentionTarget) onMentionQueryChange?.(mentionQuery);
  }, [mentionQuery, mentionTarget, onMentionQueryChange]);
  const visibleEntities = useMemo(
    () => resolveEntities(mentionQuery, mentionCategory, expandedAccountIds),
    [expandedAccountIds, mentionCategory, mentionQuery, resolveEntities],
  );
  const contactCounts = useMemo(() => contactCountsByAccount(entities), [entities]);
  const browsingCategories = categoriesEnabled && !query && mentionCategory === null;

  const replaceDraft = useCallback(
    (nextPrompt: string, nextEntities: readonly ProjectEntity[]) => {
      const retainedMentions = nextEntities.map(createComposerMention);
      const children: ProjectComposerParagraphElement["children"] = [{ text: "" }];
      retainedMentions.forEach((mention) => {
        children.push(mention, { text: " " });
      });
      children.push({ text: nextPrompt });

      Editor.withoutNormalizing(editor, () => {
        Transforms.deselect(editor);
        while (editor.children.length) {
          Transforms.removeNodes(editor, { at: [0] });
        }
        Transforms.insertNodes(
          editor,
          { children, type: "paragraph" },
          { at: [0] },
        );
      });
      lastEmittedPrompt.current = nextPrompt;
      lastMentionIds.current = nextEntities.map((entity) => entity.id);
      setMentionIds(lastMentionIds.current);
    },
    [editor],
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
    const mentionQueryText = detectMentionQuery(beforeText);
    if (mentionQueryText === null) {
      closeMentionPicker();
      return;
    }

    // Prose recovers by itself: a query that matches nothing and just gained a
    // space is no longer a mention.
    if (
      shouldAutoCloseMention(
        mentionQueryText,
        resolveEntities(mentionQueryText, mentionCategory, expandedAccountIds).length,
      )
    ) {
      closeMentionPicker();
      return;
    }

    const mentionText = `@${mentionQueryText}`;
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
    setMentionQuery(mentionQueryText);
  }, [closeMentionPicker, editor, expandedAccountIds, mentionCategory, resolveEntities]);

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
      clearSubmittedDraft(submittedPrompt, submittedEntityIds) {
        const cleared = clearSubmittedComposerDraft(editor, {
          entityIds: submittedEntityIds,
          prompt: submittedPrompt,
        });
        if (!cleared) return false;

        lastEmittedPrompt.current = "";
        lastMentionIds.current = [];
        setMentionIds([]);
        closeMentionPicker();
        onPromptChange("");
        onContextChange([]);
        return true;
      },
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
    [
      closeMentionPicker,
      disabled,
      editor,
      onContextChange,
      onPromptChange,
    ],
  );

  useEffect(() => {
    if (ReactEditor.isFocused(editor)) return;
    const sameEntities =
      selectedEntityIds.length === lastMentionIds.current.length &&
      selectedEntityIds.every((id, index) => id === lastMentionIds.current[index]);
    if (prompt === lastEmittedPrompt.current && sameEntities) return;
    replaceDraft(prompt, selectedEntities);
  }, [editor, prompt, replaceDraft, selectedEntities, selectedEntityIds]);

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

          const promptChanged = nextPrompt !== lastEmittedPrompt.current;
          const contextChanged =
            lastMentionIds.current.length !== nextMentionIds.length ||
            lastMentionIds.current.some(
              (entityId, index) => entityId !== nextMentionIds[index],
            );

          lastMentionIds.current = nextMentionIds;
          setMentionIds((current) =>
            current.length === nextMentionIds.length &&
            current.every((id, index) => id === nextMentionIds[index])
              ? current
              : nextMentionIds,
          );

          if (promptChanged) {
            lastEmittedPrompt.current = nextPrompt;
            onPromptChange(nextPrompt);
          }
          if (contextChanged) onContextChange(nextMentionIds);
          detectMentionTarget();
        }}
      >
        <Editable
          aria-label="Project prompt"
          className={styles.composerEditor}
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
              if (browsingCategories) {
                const categories = COMPOSER_CATEGORIES;
                if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                  event.preventDefault();
                  const step = event.key === "ArrowDown" ? 1 : categories.length - 1;
                  setActiveIndex((current) => (current + step) % categories.length);
                  return;
                }
                if (
                  event.key === "Enter" ||
                  event.key === "Tab" ||
                  event.key === "ArrowRight"
                ) {
                  event.preventDefault();
                  setMentionCategory(categories[activeIndex]?.key ?? "files");
                  setActiveIndex(0);
                  return;
                }
              } else if (!query) {
                // Inside the Accounts tree: ArrowRight unfolds the highlighted account's
                // contacts, ArrowLeft folds them (from the account or from one of its
                // contacts, landing back on the account). Only then does ArrowLeft fall
                // through to "back to the categories".
                const active = visibleEntities[activeIndex];
                if (
                  event.key === "ArrowRight" &&
                  active?.type === "account" &&
                  (contactCounts.get(active.id) ?? 0) > 0 &&
                  !expandedAccountIds.has(active.id)
                ) {
                  event.preventDefault();
                  toggleAccount(active.id);
                  return;
                }
                if (event.key === "ArrowLeft" && active) {
                  const foldId =
                    active.type === "contact" && active.accountId
                      ? active.accountId
                      : active.type === "account"
                        ? active.id
                        : undefined;
                  if (foldId && expandedAccountIds.has(foldId)) {
                    event.preventDefault();
                    toggleAccount(foldId);
                    const parentIndex = visibleEntities.findIndex(
                      (entity) => entity.id === foldId,
                    );
                    if (parentIndex >= 0) setActiveIndex(parentIndex);
                    return;
                  }
                }
              }
              if (
                mentionCategory &&
                !query &&
                (event.key === "ArrowLeft" || event.key === "Backspace")
              ) {
                event.preventDefault();
                setMentionCategory(null);
                setActiveIndex(
                  COMPOSER_CATEGORIES.findIndex(
                    (item) => item.key === mentionCategory,
                  ),
                );
                return;
              }
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
          activeCategory={
            browsingCategories ? COMPOSER_CATEGORIES[activeIndex]?.key : undefined
          }
          activeId={browsingCategories ? undefined : visibleEntities[activeIndex]?.id}
          catalog={entities}
          categoriesEnabled={categoriesEnabled}
          category={mentionCategory}
          contactCounts={contactCounts}
          expandedAccountIds={expandedAccountIds}
          onActiveChange={(entityId) => {
            const index = visibleEntities.findIndex(
              (entity) => entity.id === entityId,
            );
            if (index >= 0) setActiveIndex(index);
          }}
          onBack={() => {
            setMentionCategory(null);
            setActiveIndex(0);
          }}
          onOpenCategory={(category) => {
            setMentionCategory(category);
            setActiveIndex(0);
          }}
          onSelect={(entityId) => {
            const entity = visibleEntities.find((item) => item.id === entityId);
            if (entity) insertMention(entity);
          }}
          onToggleAccount={toggleAccount}
          query={mentionQuery}
          results={visibleEntities}
          selectedIds={mentionIds}
        />
      ) : null}
    </div>
  );
});
