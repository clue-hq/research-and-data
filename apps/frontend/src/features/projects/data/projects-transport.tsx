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

export function ProjectsTransportProvider({
  children,
  transport,
}: {
  children: ReactNode;
  transport: ChatTransport;
}) {
  return (
    <TransportContext.Provider value={transport}>
      {children}
    </TransportContext.Provider>
  );
}

export function useChatTransport(): ChatTransport {
  return useContext(TransportContext);
}

/** One repository set per transport, memoised so adapters keep their state. */
export function useChatRepositories(): ChatRepositories {
  const transport = useChatTransport();
  return useMemo(() => createChatRepositories(transport), [transport]);
}
