"use client";

import dynamic from "next/dynamic";
import { useCallback, useRef, useState } from "react";
import type { EditorProps } from "./markdown-editor-client";
import { bodyAfterMarkdownChange, type MarkdownEditorStatus } from "./markdown-session";
import styles from "./markdown.module.css";

const EditorClient = dynamic(() => import("./markdown-editor-client"), {
  ssr: false, loading: () => <p className={styles.loading} role="status">Loading editor…</p>,
});

export type MarkdownEditorProps = {
  documentKey: string;
  value: string;
  resetKey: number;
  onChange: (value: string) => void;
  readOnly: boolean;
  onStatusChange?: (status: MarkdownEditorStatus) => void;
};

/** A document/reset boundary, never keyed by an immutable version UUID or by typing. */
export function MarkdownEditor(props: MarkdownEditorProps) {
  return <EditorSession key={JSON.stringify([props.documentKey, props.resetKey])} {...props} />;
}

function EditorSession({ value, onChange, readOnly, onStatusChange }: MarkdownEditorProps) {
  const [raw] = useState(value);
  const [access, setAccess] = useState({ readOnly, epoch: 0, initial: value, view: "rich-text" as MarkdownEditorStatus["viewMode"] });
  const [status, setStatus] = useState<MarkdownEditorStatus>({ error: null, viewMode: "rich-text" });
  const normalized = useRef<string | null>(null);
  const view = useRef<MarkdownEditorStatus["viewMode"]>("rich-text");

  if (access.readOnly !== readOnly) {
    // Source mode reconstructs on readOnly changes. Remount from the retained draft, not its
    // last visual serialization. Busy saves use an inert wrapper instead of changing access.
    setAccess({ readOnly, epoch: access.epoch + 1, initial: value, view: status.viewMode });
  }

  const changed = useCallback<NonNullable<EditorProps["onChange"]>>((next, initialNormalization) => {
    if (initialNormalization && view.current !== "source") {
      if (access.initial === raw) normalized.current = next;
      return;
    }
    onChange(bodyAfterMarkdownChange(raw, normalized.current, next));
  }, [access.initial, raw, onChange]);

  const error = useCallback<NonNullable<EditorProps["onError"]>>(() => {
    // The original or source draft is already held by the feature. Never accept parser-error
    // replacement bytes. The native recovery UI remains available to correct the source.
  }, []);
  const stateChanged = useCallback((next: MarkdownEditorStatus) => {
    view.current = next.viewMode;
    setStatus((previous) => previous.error === next.error && previous.viewMode === next.viewMode ? previous : next);
    onStatusChange?.(next);
  }, [onStatusChange]);

  return <div className={styles.frame}>
    {status.viewMode === "source" && !readOnly ? <p className={styles.notice}>Switch to Rich text to check your changes before saving.</p> : null}
    <EditorClient key={access.epoch} markdown={access.initial} initialViewMode={access.view}
      readOnly={readOnly} onChange={changed} onError={error} onState={stateChanged} />
  </div>;
}
