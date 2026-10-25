"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { FIXTURE_TRANSPORT, type ChatTransport } from "./chat-api";
import { createChatRepositories, type ChatRepositories } from "./chat-repositories";

/**
 * Carries the resolved transport from the server shell to the browser.
 *
 * The projects chat flow is driven from the browser — streaming, turn
 * submission, gate answers — so its repositories are constructed client-side,
 * and the fixture/HTTP decision has to reach them. It is *resolved* on the
 * server (`resolveChatTransport` reads the environment in the data layer) and
 * passed down as a serializable prop, so no component reads an environment
 * variable and no secret crosses the boundary: the value is an origin-relative
 * path such as `/api/clue`, and the credential stays in the BFF.
 */
const TransportContext = createContext<ChatTransport>(FIXTURE_TRANSPORT);

export interface ChatViewerIdentity {
  userId: string | null;
  workspaceId: string | null;
}

const ViewerIdentityContext = createContext<ChatViewerIdentity>({
  userId: null,
  workspaceId: null,
});

export function ProjectsTransportProvider({
  children,
  currentUserId = null,
  currentWorkspaceId = null,
  transport,
}: {
  children: ReactNode;
  currentUserId?: string | null;
  currentWorkspaceId?: string | null;
  transport: ChatTransport;
}) {
  const viewerIdentity = useMemo<ChatViewerIdentity>(() => {
    // Fixture mode has its own explicit principal, just as it has its own
    // repositories. HTTP mode never guesses an identity: a missing protected
    // session keeps every human gate non-interactive.
    if (transport.mode === "fixture") {
      return {
        userId: currentUserId ?? "usr_demo",
        workspaceId: currentWorkspaceId ?? "ws-demo",
      };
    }
    return { userId: currentUserId, workspaceId: currentWorkspaceId };
  }, [currentUserId, currentWorkspaceId, transport.mode]);

  // HTTP requests name the workspace this page was loaded for (L4-4).
  const pageTransport = useMemo<ChatTransport>(
    () =>
      transport.mode === "http" ? { ...transport, workspaceId: currentWorkspaceId } : transport,
    [currentWorkspaceId, transport],
  );

  return (
    <TransportContext.Provider value={pageTransport}>
      <ViewerIdentityContext.Provider value={viewerIdentity}>
        {children}
      </ViewerIdentityContext.Provider>
    </TransportContext.Provider>
  );
}

export function useChatTransport(): ChatTransport {
  return useContext(TransportContext);
}

/** Authenticated viewer scope used only to validate human-facing authority. */
export function useChatViewerIdentity(): ChatViewerIdentity {
  return useContext(ViewerIdentityContext);
}

/** One repository set per transport, memoised so adapters keep their state. */
export function useChatRepositories(): ChatRepositories {
  const transport = useChatTransport();
  return useMemo(() => createChatRepositories(transport), [transport]);
}
