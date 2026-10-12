"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import {
  acceptFrameMessage,
  appToFrame,
  type AppToFramePayloads,
  type AppToFrameType,
  type FrameToAppMessage,
} from "@clue/site-kit/editor-protocol";

export interface SiteFrameHost {
  /** Bumps each time the frame boots (posts `ready`); 0 until the first boot. */
  boot: number;
  iframeRef: RefObject<HTMLIFrameElement | null>;
  post: <T extends AppToFrameType>(type: T, payload: AppToFramePayloads[T], documentId: string) => void;
  src: string | null;
}

/** One editor frame per editor origin. A fresh nonce rides in the URL fragment (never sent to a
 * server); every inbound message is checked by `acceptFrameMessage` (exact origin, the iframe's own
 * window, the nonce, the document the last `init` named); every outbound message is posted to the
 * exact editor origin — never "*". */
export function useSiteFrameHost({
  editorOrigin,
  onMessage,
}: {
  editorOrigin: string | null;
  onMessage: (message: FrameToAppMessage) => void;
}): SiteFrameHost {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const nonce = useMemo(() => (editorOrigin ? globalThis.crypto.randomUUID() : null), [editorOrigin]);
  const documentIdRef = useRef<string | null>(null);
  const [boot, setBoot] = useState(0);
  const onMessageRef = useRef(onMessage);
  useEffect(() => {
    onMessageRef.current = onMessage;
  });

  useEffect(() => {
    if (!editorOrigin || !nonce) return;
    const listener = (event: MessageEvent) => {
      const message = acceptFrameMessage(
        { data: event.data, origin: event.origin, source: event.source },
        { documentId: documentIdRef.current, editorOrigin, nonce, source: iframeRef.current?.contentWindow ?? null },
      );
      if (!message) return;
      if (message.type === "ready") {
        documentIdRef.current = null;
        setBoot((count) => count + 1);
      }
      onMessageRef.current(message);
    };
    window.addEventListener("message", listener);
    return () => window.removeEventListener("message", listener);
  }, [editorOrigin, nonce]);

  const post = useCallback(
    <T extends AppToFrameType>(type: T, payload: AppToFramePayloads[T], documentId: string) => {
      const target = iframeRef.current?.contentWindow;
      if (!editorOrigin || !nonce || !target) return;
      if (type === "init") documentIdRef.current = documentId;
      target.postMessage(appToFrame(type, payload, { documentId, nonce }), editorOrigin);
    },
    [editorOrigin, nonce],
  );

  return { boot, iframeRef, post, src: editorOrigin && nonce ? `${editorOrigin}/#n=${nonce}` : null };
}
