"use client";

import { useEffect } from "react";
import { useCellValues } from "@mdxeditor/gurx";
import {
  UndoRedo, BlockTypeSelect, BoldItalicUnderlineToggles,
  StrikeThroughSupSubToggles, CodeToggle, ListsToggle, CreateLink, InsertTable,
  InsertCodeBlock, InsertThematicBreak, DiffSourceToggleWrapper, ConditionalContents,
  markdownProcessingError$, viewMode$,
} from "@mdxeditor/editor";
import type { MarkdownEditorStatus } from "./markdown-session";
import styles from "./markdown.module.css";

/** Library-owned controls, focus, history and serialization in every document context. */
export function MarkdownToolbar({ onState }: { onState: (state: MarkdownEditorStatus) => void }) {
  const [error, viewMode] = useCellValues(markdownProcessingError$, viewMode$);
  useEffect(() => onState({ error: error?.error ?? null, viewMode }), [error, viewMode, onState]);
  return <DiffSourceToggleWrapper options={["rich-text", "source"]} SourceToolbar={<span className={styles.sourceLabel}>Markdown source</span>}>
    <ConditionalContents options={[
      { when: (editor) => editor?.editorType === "codeblock", contents: () => <span className={styles.sourceLabel}>Monospace</span> },
      { fallback: () => <>
        <span className={styles.toolbarGroup}><UndoRedo /></span>
        <span className={styles.toolbarGroup}><BlockTypeSelect /></span>
        <span className={styles.toolbarGroup}><BoldItalicUnderlineToggles options={["Bold", "Italic"]} /><StrikeThroughSupSubToggles options={["Strikethrough"]} /><CodeToggle /></span>
        <span className={styles.toolbarGroup}><ListsToggle /></span>
        <span className={styles.toolbarGroup}><CreateLink /><InsertTable /><InsertCodeBlock /><InsertThematicBreak /></span>
      </> },
    ]} />
  </DiffSourceToggleWrapper>;
}
