import { useEffect, useRef } from "react";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { basicSetup } from "codemirror";

/** React owns the Markdown string; CodeMirror owns source editing and its history. */
export function useMarkdownSourceEditor(value: string, onChange: (value: string) => void) {
  const container = useRef<HTMLDivElement>(null);
  const editor = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  const initialValue = useRef(value);
  const syncing = useRef(false);

  useEffect(() => { onChangeRef.current = onChange; }, [onChange]);

  useEffect(() => {
    if (!container.current) return;
    const view = new EditorView({
      parent: container.current,
      state: EditorState.create({
        doc: initialValue.current,
        extensions: [
          basicSetup,
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
