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
  /** The frame on the canvas has not said `ready` within the wait (review finding S7-2). */
  timedOut: boolean;
}

/** How long a frame may take to say `ready` before the canvas says the editor did not answer: its
 * bundle on a slow network, never a frame that cannot load at all. */
export const SITE_EDITOR_READY_TIMEOUT_MS = 30_000;

/** One editor frame per site document shown (and per editor origin). A fresh nonce rides in the URL
 * fragment (never sent to a server); every inbound message is checked by `acceptFrameMessage` (exact
 * origin, the iframe's own window, the nonce, the document the last `init` named); every outbound
 * message is posted to the exact editor origin — never "*".
 *
 * Review K3-1 (fix 2): agent-written section code runs in the frame, so a frame that has shown one
 * site is never handed another. Opening a different site mints a new frame address (a new nonce),
 * which the canvas keys its iframe on, so the old frame — and any code it loaded — is thrown away.
 * Leaving a site and coming back to the same one keeps its frame (and its warmth). */
export function useSiteFrameHost({
  documentId,
  editorOrigin,
  onMessage,
  readyTimeoutMs = SITE_EDITOR_READY_TIMEOUT_MS,
}: {
  /** The site the canvas shows (null: none, e.g. a web or ad tab). */
  documentId: string | null;
  editorOrigin: string | null;
  onMessage: (message: FrameToAppMessage) => void;
  readyTimeoutMs?: number;
}): SiteFrameHost {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  // Which document the current frame belongs to, and its generation. React's adjust-state-on-prop
  // pattern (a render-time comparison), never a setState inside an effect.
  const [frameFor, setFrameFor] = useState<{ documentId: string | null; generation: number }>({ documentId: null, generation: 0 });
  if (documentId !== null && documentId !== frameFor.documentId) {
    setFrameFor({ documentId, generation: frameFor.documentId === null ? frameFor.generation : frameFor.generation + 1 });
  }
  const generation = frameFor.generation;
  const nonce = useMemo(
    () => (editorOrigin ? globalThis.crypto.randomUUID() : null),
    // `generation` is the reason this re-runs: a new frame gets a new nonce.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [editorOrigin, generation],
  );
  const documentIdRef = useRef<string | null>(null);
  const [boot, setBoot] = useState(0);
  // Review finding S7-2: which frame (by its nonce) has said `ready`, and which ran out of time
  // first. Per frame, because a different site gets a fresh frame.
  const [answered, setAnswered] = useState<string | null>(null);
  const [lateNonce, setLateNonce] = useState<string | null>(null);
  useEffect(() => {
    if (!nonce) return;
    const timer = setTimeout(() => setLateNonce(nonce), readyTimeoutMs);
    return () => clearTimeout(timer);
  }, [nonce, readyTimeoutMs]);
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
        setAnswered(nonce);
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

  return {
    boot,
    iframeRef,
    post,
    src: editorOrigin && nonce ? `${editorOrigin}/#n=${nonce}` : null,
    timedOut: nonce !== null && lateNonce === nonce && answered !== nonce,
  };
}
