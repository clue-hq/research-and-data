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

// Task-1 scaffolding for the target-accounts lift: the `/projects/{id}/accounts`
// redirect page needs this helper to type-check before Task 3 lands the real
// surface. It is carried over from the design build VERBATIM, including the
// `"thread-primary"` fallback that ruling R3 removed from `projectGalleryHref`
// directly above — so a caller that omits `threadId` puts a fixture thread id in
// a production URL. Task 3 owns resolving a real thread id and dropping the
// fallback; do not add a second caller before then.
export function projectTargetAccountsHref(projectId: string, threadId?: string) {
  return projectChatHref(projectId, threadId ?? "thread-primary", { surface: "target-accounts" });
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
