"use client";

import { useMemo } from "react";
import { EditorView } from "@codemirror/view";
import {
  MDXEditor,
  headingsPlugin, quotePlugin, listsPlugin, linkPlugin,
  linkDialogPlugin, tablePlugin, thematicBreakPlugin, codeBlockPlugin, codeMirrorPlugin,
  diffSourcePlugin, toolbarPlugin, markdownShortcutPlugin, imagePlugin,
  type MDXEditorProps, type IconKey, type ViewMode,
} from "@mdxeditor/editor";
import {
  Undo2, Redo2, Bold, Italic, Underline, Code, Strikethrough, Superscript, Subscript,
  List, ListOrdered, ListTodo, Highlighter, Link, ImagePlus, Table, Minus, FileText,
  SquareCode, ChevronDown, MessageSquare, Text, Diff, FileCode, ExternalLink, Unlink,
  Pencil, Copy, Ellipsis, EllipsisVertical, X, Settings, Trash2, AlignCenter, AlignLeft,
  AlignRight, Rows3, Columns3, BetweenHorizontalStart, BetweenHorizontalEnd,
  BetweenVerticalStart, BetweenVerticalEnd, Check, type LucideIcon,
} from "lucide-react";
import "@mdxeditor/editor/style.css";
import styles from "./markdown.module.css";
import { MarkdownToolbar } from "./markdown-toolbar";

export type EditorState = { error: string | null; viewMode: ViewMode };
export type EditorProps = Pick<MDXEditorProps, "markdown" | "onChange" | "onError" | "readOnly"> & {
  onState: (state: EditorState) => void;
  initialViewMode?: ViewMode;
};

const icons: Record<IconKey, LucideIcon> = {
  undo: Undo2, redo: Redo2, format_bold: Bold, format_italic: Italic,
  format_underlined: Underline, code: Code, strikeThrough: Strikethrough,
  superscript: Superscript, subscript: Subscript, format_list_bulleted: List,
  format_list_numbered: ListOrdered, format_list_checked: ListTodo,
  format_highlight: Highlighter, link: Link, add_photo: ImagePlus, table: Table,
  horizontal_rule: Minus, frontmatter: FileText, frame_source: SquareCode,
  arrow_drop_down: ChevronDown, admonition: MessageSquare, rich_text: Text,
  difference: Diff, markdown: FileCode, open_in_new: ExternalLink, link_off: Unlink,
  edit: Pencil, content_copy: Copy, more_horiz: Ellipsis, more_vert: EllipsisVertical,
  close: X, settings: Settings, delete_big: Trash2, delete_small: Trash2,
  format_align_center: AlignCenter, format_align_left: AlignLeft,
  format_align_right: AlignRight, add_row: Rows3, add_column: Columns3,
  insert_col_left: BetweenVerticalStart, insert_col_right: BetweenVerticalEnd,
  insert_row_above: BetweenHorizontalStart, insert_row_below: BetweenHorizontalEnd,
  check: Check,
};

const codeExtensions = [EditorView.lineWrapping, EditorView.theme({
  "&": { backgroundColor: "var(--clue-ds-color-bg-subtle)", color: "var(--clue-ds-color-content-neutral)" },
  ".cm-scroller": { fontFamily: "var(--clue-ds-typography-code-font-family)", fontSize: "var(--clue-ds-typography-code-font-size)", lineHeight: "var(--clue-ds-typography-code-line-height)" },
  ".cm-gutters": { display: "none" },
  ".cm-activeLine": { backgroundColor: "transparent" },
  ".cm-content": { padding: "16px", overflowWrap: "anywhere" },
  ".cm-line": { padding: "0", overflowWrap: "anywhere", wordBreak: "break-word" },
  "&.cm-focused": { outline: "none" },
})];

/** Imported only through next/dynamic(ssr: false), including every editor plugin. */
export default function MarkdownEditorClient({ onState, initialViewMode = "rich-text", ...props }: EditorProps) {
  // Keep plugin/toolbar component identities stable while the parent tracks a draft.
  const plugins = useMemo(() => [
      headingsPlugin(), quotePlugin(), listsPlugin(), linkPlugin({ disableAutoLink: true }), linkDialogPlugin(),
      tablePlugin(), thematicBreakPlugin(), imagePlugin(),
      codeBlockPlugin({ defaultCodeBlockLanguage: "text" }),
      codeMirrorPlugin({ codeBlockLanguages: { text: "Plain text" }, autoLoadLanguageSupport: false, codeMirrorExtensions: codeExtensions }),
      diffSourcePlugin({ viewMode: initialViewMode, codeMirrorExtensions: codeExtensions }),
      markdownShortcutPlugin(),
      toolbarPlugin({ toolbarClassName: styles.toolbar, toolbarContents: () => <MarkdownToolbar onState={onState} /> }),
    ], [onState, initialViewMode]);
  return <MDXEditor {...props} className={`${styles.editor}${props.readOnly ? ` ${styles.readOnly}` : ""}`} contentEditableClassName={styles.prose}
    placeholder="Start writing…"
    iconComponentFor={editorIcon}
    plugins={plugins}
  />;
}

function editorIcon(name: IconKey) {
  const Icon = icons[name];
  return <Icon size={16} strokeWidth={1.6} aria-hidden="true" />;
}
