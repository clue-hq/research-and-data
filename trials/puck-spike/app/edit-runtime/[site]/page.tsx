// D2 spike (Task 4): the editor with this site's agent sections loaded at runtime, not imported.
//
// /edit-runtime/<site>?route=/more. The site's JSON names its workspace and {name: digest}; the
// client imports each module from /compiled/<workspace>/<digest>.mjs. The existing /edit route is
// unchanged.
import "@puckeditor/core/puck.css";
import type { Data } from "@puckeditor/core";
import { loadBrand } from "@/lib/brands";
import { basePathOf, readSite, type Site } from "@/lib/store";
import { RuntimeEditor } from "./client";

const EMPTY: Data = { content: [], root: { props: {} } };

// A compiled section keeps three imports: react, react/jsx-runtime and zod. The import map points
// each at a one-line module that re-exports the editor's own copy, which the client puts on
// globalThis.__clueSectionHost before it imports any section. So a section runs on the editor's
// React (one React: hooks and context work) and on the editor's zod.
const REACT_EXPORTS = [
  "Children", "Component", "Fragment", "PureComponent", "StrictMode", "Suspense", "cloneElement",
  "createContext", "createElement", "createRef", "forwardRef", "isValidElement", "lazy", "memo",
  "startTransition", "use", "useActionState", "useCallback", "useContext", "useDebugValue",
  "useDeferredValue", "useEffect", "useId", "useImperativeHandle", "useInsertionEffect",
  "useLayoutEffect", "useMemo", "useOptimistic", "useReducer", "useRef", "useState",
  "useSyncExternalStore", "useTransition", "version",
];
const shim = (specifier: string, names: string[]) =>
  "data:text/javascript," +
  encodeURIComponent(
    `const m = globalThis.__clueSectionHost[${JSON.stringify(specifier)}];` +
      `export default m.default ?? m; export const { ${names.join(", ")} } = m;`,
  );
const IMPORT_MAP = {
  imports: {
    react: shim("react", REACT_EXPORTS),
    "react/jsx-runtime": shim("react/jsx-runtime", ["jsx", "jsxs", "Fragment"]),
    zod: shim("zod", ["z"]),
  },
};

export default async function EditRuntimePage({
  params,
  searchParams,
}: {
  params: Promise<{ site: string }>;
  searchParams: Promise<{ route?: string }>;
}) {
  const { site } = await params;
  const { route = "/" } = await searchParams;
  const stored = readSite(site) as Site & { workspace?: string; agentSections?: Record<string, string> };
  return (
    <>
      <script type="importmap" dangerouslySetInnerHTML={{ __html: JSON.stringify(IMPORT_MAP) }} />
      <RuntimeEditor
        workspace={stored.workspace ?? ""}
        sections={stored.agentSections ?? {}}
        data={stored.pages[route] ?? EMPTY}
        brand={loadBrand(stored.brand)}
        // `site` names no static agent sections, so every agent section here comes from a module.
        options={{ basePath: basePathOf(site), shell: stored.shell, mode: "page", site }}
      />
    </>
  );
}

export const dynamic = "force-dynamic";
