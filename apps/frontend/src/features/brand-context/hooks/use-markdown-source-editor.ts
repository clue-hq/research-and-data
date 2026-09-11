import { useEffect, useRef } from "react";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { Compartment, EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { tags } from "@lezer/highlight";
import { minimalSetup } from "codemirror";

const markdownHighlight = HighlightStyle.define([
  { tag: [tags.heading, tags.strong], fontWeight: "600", color: "var(--clue-ds-color-content-neutral)" },
  { tag: tags.emphasis, fontStyle: "italic" },
  { tag: [tags.link, tags.url], color: "var(--clue-ds-color-content-subtle)", textDecoration: "underline" },
  { tag: [tags.processingInstruction, tags.meta, tags.monospace], color: "var(--clue-ds-color-content-subtle)" },
]);

/** React owns the Markdown string; CodeMirror owns source editing and its history. */
export function useMarkdownSourceEditor(value: string, onChange: (value: string) => void, readOnly: boolean) {
  const container = useRef<HTMLDivElement>(null);
  const editor = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  const initialValue = useRef(value);
  const syncing = useRef(false);
  const access = useRef(new Compartment());

  useEffect(() => { onChangeRef.current = onChange; }, [onChange]);

  useEffect(() => {
    if (!container.current) return;
    const view = new EditorView({
      parent: container.current,
      state: EditorState.create({
        doc: initialValue.current,
        extensions: [
          minimalSetup,
          access.current.of(EditorState.readOnly.of(false)),
          syntaxHighlighting(markdownHighlight),
          markdown({ base: markdownLanguage }),
          EditorView.lineWrapping,
          EditorView.contentAttributes.of({ "aria-label": "Markdown source" }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged && !syncing.current) {
              onChangeRef.current(update.state.doc.toString());
            }
          }),
        ],
      }),
    });
    editor.current = view;
    return () => {
      editor.current = null;
      view.destroy();
    };
  }, []);

  useEffect(() => {
    editor.current?.dispatch({ effects: access.current.reconfigure(EditorState.readOnly.of(readOnly)) });
  }, [readOnly]);

  useEffect(() => {
    const view = editor.current;
    if (view && value !== view.state.doc.toString()) {
      syncing.current = true;
      try {
        view.dispatch({
          changes: { from: 0, to: view.state.doc.length, insert: value },
          selection: { anchor: 0 },
          scrollIntoView: true,
        });
      } finally {
        syncing.current = false;
      }
    }
  }, [value]);

  return container;
}
