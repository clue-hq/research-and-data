export type ChatShellRouteQuery = Record<string, string | undefined>;

function routeSegment(value: string) {
  return encodeURIComponent(value);
}

function withQuery(pathname: string, query: ChatShellRouteQuery = {}) {
  const searchParams = new URLSearchParams();

  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      searchParams.set(key, value);
    }
  });

  const search = searchParams.toString();
  return search ? `${pathname}?${search}` : pathname;
}

// Phase R amendment (founder ruling R3): the source's `threadId ?? "thread-primary"`
// fallback is removed — "thread-primary" is a fixture id that must never reach a
// production URL. Callers resolve a real thread id first.
export function projectGalleryHref(projectId: string, threadId: string) {
  return projectChatHref(projectId, threadId, {
    surface: "gallery",
  });
}

// The target-accounts rail surface, addressable. Ruling R3 forbids the design
// build's `threadId ?? "thread-primary"` fallback in a production URL, and a
// caller like the `/projects/{id}/accounts` redirect genuinely may not know a
// thread id — so a threadless call points at the project landing route instead
// of inventing a thread. `/projects/{id}` is the legacy absorber (ruling R1):
// it carries the whole query — `surface` included — through its client-side
// canonicalization to `/chats/{resolved}`, so the surface survives the hop.
export function projectTargetAccountsHref(projectId: string, threadId?: string) {
  if (threadId) {
    return projectChatHref(projectId, threadId, { surface: "target-accounts" });
  }
  return withQuery(`/projects/${routeSegment(projectId)}`, {
    surface: "target-accounts",
  });
}

export function projectChatHref(
  projectId: string,
  chatId: string,
  query?: ChatShellRouteQuery,
) {
  return withQuery(
    `/projects/${routeSegment(projectId)}/chats/${routeSegment(chatId)}`,
    query,
  );
}

export function projectArtifactHref(
  projectId: string,
  artifactId: string,
  query?: ChatShellRouteQuery,
) {
  return withQuery(
    `/projects/${routeSegment(projectId)}/artifacts/${routeSegment(artifactId)}`,
    query,
  );
}
