"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatShellArtifactKind } from "../model/chat-shell";
import type { ArtifactActionRequest } from "../model/artifact-actions";

export function useArtifactActionMenuController(kind: ChatShellArtifactKind) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [selectedVersionId, setSelectedVersionId] = useState("current");
  const menuRef = useRef<HTMLDivElement>(null);

  const closeMenu = useCallback(() => {
    setMenuOpen(false);
    setVersionsOpen(false);
  }, []);

  useEffect(() => {
    const dismissOnPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) closeMenu();
    };

    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeMenu();
    };

    document.addEventListener("pointerdown", dismissOnPointerDown);
    document.addEventListener("keydown", dismissOnEscape);
    return () => {
      document.removeEventListener("pointerdown", dismissOnPointerDown);
      document.removeEventListener("keydown", dismissOnEscape);
    };
  }, [closeMenu]);

  const toggleMenu = useCallback(() => {
    setMenuOpen((current) => {
      if (current) setVersionsOpen(false);
      return !current;
    });
  }, []);

  const requestAction = useCallback(
    (action: ArtifactActionRequest) => {
      window.dispatchEvent(
        new CustomEvent("clue:artifact-action-request", {
          detail: { action, kind },
        }),
      );
      closeMenu();
    },
    [closeMenu, kind],
  );

  const selectVersion = useCallback(
    (versionId: string) => {
      setSelectedVersionId(versionId);
      window.dispatchEvent(
        new CustomEvent("clue:artifact-version-select", {
          detail: { kind, versionId },
        }),
      );
    },
    [kind],
  );

  return {
    closeMenu,
    menuOpen,
    menuRef,
    requestAction,
    selectVersion,
    selectedVersionId,
    setVersionsOpen,
    toggleMenu,
    versionsOpen,
  };
}
