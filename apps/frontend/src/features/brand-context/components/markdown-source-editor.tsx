"use client";

import { markdown } from "@codemirror/lang-markdown";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { basicSetup } from "codemirror";
import { useEffect, useRef } from "react";
import styles from "./brand-context.module.css";

const clueMarkdownTheme = EditorView.theme({
  "&": {
    backgroundColor: "var(--clue-ds-color-bg-neutral)",
    color: "var(--clue-ds-color-content-neutral)",
    height: "100%",
  },
  "&.cm-focused": { outline: "none" },
  ".cm-content": {
    caretColor: "var(--clue-ds-color-content-neutral)",
    fontFamily: '"DM Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: "13px",
    lineHeight: "20px",
    padding: "0",
  },
  ".cm-cursor, .cm-dropCursor": {
    borderLeftColor: "var(--clue-ds-color-content-neutral)",
  },
  ".cm-gutters": {
    backgroundColor: "var(--clue-ds-color-bg-neutral)",
    borderRight: "0",
    color: "var(--clue-ds-color-content-disabled)",
    fontFamily: '"DM Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: "12px",
    lineHeight: "20px",
    marginRight: "24px",
    minWidth: "auto",
  },
  ".cm-foldGutter": { display: "none" },
  ".cm-lineNumbers .cm-gutterElement": {
    minWidth: "16px",
    padding: "0",
  },
  ".cm-scroller": {
    overflow: "auto",
    padding: "32px 32px 80px",
  },
  ".cm-selectionBackground, ::selection": {
    backgroundColor: "var(--clue-ds-color-primitives-brand-alpha-100) !important",
  },
});

const clueMarkdownHighlighting = HighlightStyle.define([
  { color: "#264dd9", fontWeight: "400", tag: tags.heading },
  { color: "#d95926", fontWeight: "400", tag: tags.strong },
  { color: "#737380", fontStyle: "normal", tag: tags.quote },
  { color: "#264dd9", tag: tags.list },
  { color: "#1a9980", textDecoration: "none", tag: [tags.link, tags.url] },
]);

export function MarkdownSourceEditor({
  label,
  onChange,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const editorRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  const initialValueRef = useRef(value);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  useEffect(() => {
    if (!containerRef.current) return;

    const view = new EditorView({
      parent: containerRef.current,
      state: EditorState.create({
        doc: initialValueRef.current,
        extensions: [
          basicSetup,
          markdown(),
          clueMarkdownTheme,
          syntaxHighlighting(clueMarkdownHighlighting),
          EditorView.contentAttributes.of({
            "aria-label": label,
            autocapitalize: "off",
            autocomplete: "off",
            spellcheck: "false",
          }),
          EditorView.lineWrapping,
          EditorView.updateListener.of((update) => {
            if (update.docChanged) onChangeRef.current(update.state.doc.toString());
          }),
        ],
      }),
    });

    editorRef.current = view;
    return () => {
      editorRef.current = null;
      view.destroy();
    };
  }, [label]);

  useEffect(() => {
    const view = editorRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current === value) return;
    view.dispatch({ changes: { from: 0, insert: value, to: current.length } });
  }, [value]);

  return <div className={styles.markdownCodeEditor} ref={containerRef} />;
}
