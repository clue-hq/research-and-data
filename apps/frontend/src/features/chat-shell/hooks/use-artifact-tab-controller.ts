"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export function useArtifactTabController({
  onRename,
  title,
}: {
  onRename: (title: string) => void;
  title: string;
}) {
  const [draftTitle, setDraftTitle] = useState(title);
  const [renaming, setRenaming] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!renaming) return;
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [renaming]);

  const cancelRename = useCallback(() => {
    setDraftTitle(title);
    setRenaming(false);
  }, [title]);

  const commitRename = useCallback(() => {
    const nextTitle = draftTitle.trim();
    if (nextTitle) onRename(nextTitle);
    else setDraftTitle(title);
    setRenaming(false);
  }, [draftTitle, onRename, title]);

  const startRename = useCallback(() => {
    setDraftTitle(title);
    setRenaming(true);
  }, [title]);

  return {
    cancelRename,
    commitRename,
    draftTitle,
    inputRef,
    renaming,
    setDraftTitle,
    startRename,
  };
}
