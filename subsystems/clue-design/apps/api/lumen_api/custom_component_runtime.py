"""P6.3 custom-component runtime frame assembly.

Compiled component bytes never execute in the API process. This module resolves
one account-local immutable artifact graph, verifies every content-addressed
member, and produces a nested ``srcdoc`` document. The browser executes that
document in an opaque-origin iframe with scripts but without same-origin,
network, navigation, workers, plugins, or child frames.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit
from uuid import uuid4

from .custom_components import resolve_custom_component_artifact_blob
from .database import NotFoundError
from .design_store import DesignBlobStore, HybridRepository


JsonObject = Dict[str, Any]
RUNTIME_CONTRACT_VERSION = 1
MAX_RUNTIME_ARTIFACTS = 32
MAX_RUNTIME_GRAPH_BYTES = 8 * 1024 * 1024
MAX_RUNTIME_HTML_BYTES = 12 * 1024 * 1024
MAX_RUNTIME_HEIGHT_PX = 10_000
_ARTIFACT_PATTERN = re.compile(r"^ccart_[0-9a-f]{64}$")
_FIXED_HEIGHT_CLASS = re.compile(
    r"(?:^|\s)(?:(?:[a-z0-9-]+):)*(?:h-|size-)(?!auto(?:\s|$))"
)
_STYLE_END = re.compile(r"</style", re.IGNORECASE)

_REACT_EXPORTS = (
    "Children",
    "Component",
    "Fragment",
    "Profiler",
    "PureComponent",
    "StrictMode",
    "Suspense",
    "__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED",
    "cloneElement",
    "createContext",
    "createElement",
    "createFactory",
    "createRef",
    "forwardRef",
    "isValidElement",
    "lazy",
    "memo",
    "startTransition",
    "unstable_act",
    "useCallback",
    "useContext",
    "useDebugValue",
    "useDeferredValue",
    "useEffect",
    "useId",
    "useImperativeHandle",
    "useInsertionEffect",
    "useLayoutEffect",
    "useMemo",
    "useReducer",
    "useRef",
    "useState",
    "useSyncExternalStore",
    "useTransition",
    "version",
)


class CustomComponentRuntimeError(RuntimeError):
    """An artifact cannot be mounted under the P6.3 runtime contract."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class CustomComponentDeliveryPackage:
    """One immutable, registry-independent custom-component delivery package.

    ``frames`` is passed to ``lumen-web`` exactly like editor preview frames.
    ``assets`` contains every byte needed by those frames, keyed by digest.
    The manifest contains only digests, immutable URLs, artifact pins, and
    compiler/runtime provenance; it never consults mutable ``latest`` state.
    """

    frames: Dict[str, JsonObject] = field(default_factory=dict)
    assets: Dict[str, bytes] = field(default_factory=dict)
    manifest: JsonObject = field(default_factory=dict)


@dataclass
class _DeliveryAssetCatalog:
    url_for: Callable[[str, str], str]
    assets: Dict[str, bytes] = field(default_factory=dict)
    records: Dict[str, JsonObject] = field(default_factory=dict)

    def add(
        self,
        data: bytes | str,
        *,
        media_type: str,
        extension: str,
        role: str,
    ) -> JsonObject:
        raw = data.encode("utf-8") if isinstance(data, str) else data
        digest = hashlib.sha256(raw).hexdigest()
        existing = self.assets.get(digest)
        if existing is not None and existing != raw:
            raise CustomComponentRuntimeError(
                "custom_component.delivery_digest_collision",
                "two delivery assets produced the same content digest",
            )
        self.assets[digest] = raw
        record = self.records.setdefault(
            digest,
            {
                "algorithm": "sha256",
                "digest": digest,
                "byte_length": len(raw),
                "media_type": media_type,
                "extension": extension,
                "url": self.url_for(digest, extension),
                "roles": [],
            },
        )
        if role not in record["roles"]:
            record["roles"].append(role)
            record["roles"].sort()
        return record


def default_runtime_host_path() -> Path:
    return (
        Path(__file__).resolve().parent
        / "runtime_assets"
        / "custom-component-react-host-v1.js"
    )


@lru_cache(maxsize=4)
def _read_runtime_host(path_text: str) -> bytes:
    path = Path(path_text)
    data = path.read_bytes()
    if not data or len(data) > 1024 * 1024:
        raise CustomComponentRuntimeError(
            "custom_component.runtime_host_invalid",
            "the trusted React runtime host is missing or exceeds its size limit",
        )
    return data


def _data_javascript(data: bytes | str) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return "data:text/javascript;base64," + base64.b64encode(raw).decode("ascii")


def _json_for_html(value: Any) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _style_text(value: str) -> str:
    # Raw-text HTML parsing treats a literal </style as markup regardless of
    # CSS quoting. Tailwind output is trusted compiler output, but escaping the
    # delimiter keeps even arbitrary-value utilities inside this style block.
    return _STYLE_END.sub(r"<\\/style", value)


def _react_adapter() -> str:
    declarations = "\n".join(
        f"export const {name} = React.{name};" for name in _REACT_EXPORTS
    )
    return (
        "const React=globalThis.__LumenReact;\n"
        "if(!React)throw new Error('Lumen React host is unavailable');\n"
        "export default React;\n"
        f"{declarations}\n"
    )


_JSX_ADAPTER = """
const runtime=globalThis.__LumenReactJsxRuntime;
if(!runtime)throw new Error("Lumen JSX runtime is unavailable");
export const Fragment=runtime.Fragment;
export const jsx=runtime.jsx;
export const jsxs=runtime.jsxs;
""".strip()

_JSX_DEV_ADAPTER = """
const runtime=globalThis.__LumenReactJsxDevRuntime;
if(!runtime)throw new Error("Lumen JSX development runtime is unavailable");
export const Fragment=runtime.Fragment;
export const jsxDEV=runtime.jsxDEV;
""".strip()


def _runtime_bootstrap(config: JsonObject) -> str:
    return f"""
import Component from "lumen:root";
const config={_json_for_html(config)};
const React=globalThis.__LumenReact;
const ReactDOM=globalThis.__LumenReactDOMClient;
const root=document.getElementById("lumen-custom-component-root");
const report=(type,payload={{}})=>parent.postMessage({{
  channel:"lumen-custom-component-runtime",
  contractVersion:{RUNTIME_CONTRACT_VERSION},
  runtimeNonce:config.runtimeNonce,
  nodeId:config.nodeId,
  artifactId:config.artifactId,
  type,
  ...payload
}},"*");
const fail=(error)=>{{
  const message=String(error&&error.message?error.message:error||"Unknown runtime error").slice(0,500);
  root.replaceChildren();
  const panel=document.createElement("div");
  panel.className="lumen-runtime-error";
  panel.setAttribute("role","alert");
  const title=document.createElement("strong");
  title.textContent="Custom component failed";
  const detail=document.createElement("span");
  detail.textContent=message;
  panel.append(title,detail);
  root.append(panel);
  report("error",{{message}});
}};
globalThis.__lumenCustomComponentFail=fail;
class RuntimeBoundary extends React.Component {{
  constructor(props){{super(props);this.state={{error:null}};}}
  static getDerivedStateFromError(error){{return {{error}};}}
  componentDidCatch(error){{fail(error);}}
  render(){{
    return this.state.error
      ? null
      : React.createElement(React.Fragment,null,this.props.children);
  }}
}}
try {{
  if(typeof Component!=="function"&&typeof Component!=="object"){{
    throw new Error("Artifact default export is not a React component");
  }}
  const tree=React.createElement(
    RuntimeBoundary,
    null,
    React.createElement(Component,{{
      props:config.props,
      theme:config.theme,
      overrideVariables:config.overrideVariables
    }})
  );
  ReactDOM.hydrateRoot(root,tree,{{
    onRecoverableError(error){{
      report("recoverable-error",{{
        message:String(error&&error.message?error.message:error).slice(0,500)
      }});
    }}
  }});
  const postHeight=()=>{{
    const height=Math.max(
      1,
      Math.min(
        {MAX_RUNTIME_HEIGHT_PX},
        Math.ceil(Math.max(
          document.documentElement.scrollHeight,
          document.body?document.body.scrollHeight:0
        ))
      )
    );
    report("height",{{height}});
  }};
  requestAnimationFrame(()=>{{
    report("ready");
    postHeight();
  }});
  if(typeof ResizeObserver!=="undefined"){{
    new ResizeObserver(postHeight).observe(root);
  }}
  addEventListener("resize",postHeight);
}} catch(error) {{
  fail(error);
}}
""".strip()


def _runtime_prelude(config: JsonObject) -> str:
    return f"""
(function(){{
  var config={_json_for_html(config)};
  function fail(error){{
    var root=document.getElementById("lumen-custom-component-root");
    if(!root)return;
    var message=String(error&&error.message?error.message:error||"Unknown runtime error").slice(0,500);
    root.replaceChildren();
    var panel=document.createElement("div");
    panel.className="lumen-runtime-error";
    panel.setAttribute("role","alert");
    var title=document.createElement("strong");
    title.textContent="Custom component failed";
    var detail=document.createElement("span");
    detail.textContent=message;
    panel.append(title,detail);
    root.append(panel);
    parent.postMessage({{
      channel:"lumen-custom-component-runtime",
      contractVersion:{RUNTIME_CONTRACT_VERSION},
      runtimeNonce:config.runtimeNonce,
      nodeId:config.nodeId,
      artifactId:config.artifactId,
      type:"error",
      message:message
    }},"*");
  }}
  globalThis.__lumenCustomComponentFail=fail;
  addEventListener("error",function(event){{fail(event.error||event.message);}});
  addEventListener("unhandledrejection",function(event){{fail(event.reason);}});
  document.addEventListener("click",function(event){{
    var anchor=event.target&&event.target.closest?event.target.closest("a[href]"):null;
    if(!anchor)return;
    var href=anchor.getAttribute("href")||"";
    if(href&&href.charAt(0)!=="#")event.preventDefault();
  }},true);
  document.addEventListener("submit",function(event){{event.preventDefault();}},true);
  if(matchMedia("(prefers-reduced-motion: reduce)").matches){{
    document.documentElement.dataset.reducedMotion="true";
  }}
}})();
""".strip()


def _require_runtime_artifact(
    repository: HybridRepository,
    *,
    account_id: str,
    artifact_id: str,
) -> JsonObject:
    if not _ARTIFACT_PATTERN.fullmatch(artifact_id):
        raise CustomComponentRuntimeError(
            "custom_component.artifact_invalid",
            f"artifact pin {artifact_id!r} is invalid",
        )
    try:
        artifact = repository.require_custom_component_artifact(
            account_id, artifact_id
        )
    except NotFoundError as error:
        raise CustomComponentRuntimeError(
            "custom_component.artifact_missing",
            f"pinned artifact {artifact_id!r} is missing",
        ) from error
    manifest = artifact.get("manifest")
    browser = manifest.get("browser") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 2
        or not isinstance(browser, dict)
        or browser.get("format") != "esm"
        or browser.get("react") != "host-singleton"
        or artifact.get("css") is None
        or artifact.get("first_frame") is None
    ):
        raise CustomComponentRuntimeError(
            "custom_component.artifact_runtime_unsupported",
            "the pinned artifact predates or violates runtime contract 1",
        )
    return artifact


def _resolve_artifact_graph(
    repository: HybridRepository,
    blobs: DesignBlobStore,
    *,
    account_id: str,
    root_artifact_id: str,
) -> Tuple[JsonObject, Dict[str, bytes], List[bytes], List[JsonObject]]:
    by_id: Dict[str, JsonObject] = {}
    slug_pins: Dict[str, str] = {}
    bundles: Dict[str, bytes] = {}
    css_parts: List[bytes] = []
    active: set[str] = set()
    total_bytes = 0

    def visit(artifact_id: str, import_name: Optional[str]) -> JsonObject:
        nonlocal total_bytes
        if artifact_id in active:
            raise CustomComponentRuntimeError(
                "custom_component.dependency_cycle",
                "custom-component artifact dependencies contain a cycle",
            )
        if artifact_id in by_id:
            artifact = by_id[artifact_id]
            if import_name is not None:
                bundles[import_name] = bundles[f"artifact:{artifact_id}"]
            return artifact
        if len(by_id) >= MAX_RUNTIME_ARTIFACTS:
            raise CustomComponentRuntimeError(
                "custom_component.dependency_limit",
                f"runtime dependency graph exceeds {MAX_RUNTIME_ARTIFACTS} artifacts",
            )
        active.add(artifact_id)
        artifact = _require_runtime_artifact(
            repository, account_id=account_id, artifact_id=artifact_id
        )
        slug = str(artifact["slug"])
        pinned = slug_pins.get(slug)
        if pinned is not None and pinned != artifact_id:
            raise CustomComponentRuntimeError(
                "custom_component.dependency_version_conflict",
                f"runtime graph pins two artifacts for component slug {slug!r}",
            )
        slug_pins[slug] = artifact_id
        manifest = artifact["manifest"]
        dependencies = manifest.get("dependency_artifacts", {})
        if not isinstance(dependencies, dict):
            raise CustomComponentRuntimeError(
                "custom_component.dependency_manifest_invalid",
                f"artifact {artifact_id!r} has an invalid dependency manifest",
            )
        for dependency_slug, dependency_id in sorted(dependencies.items()):
            if not isinstance(dependency_slug, str) or not isinstance(
                dependency_id, str
            ):
                raise CustomComponentRuntimeError(
                    "custom_component.dependency_manifest_invalid",
                    f"artifact {artifact_id!r} has a malformed dependency pin",
                )
            dependency = visit(
                dependency_id, f"components/{dependency_slug}"
            )
            if dependency["slug"] != dependency_slug:
                raise CustomComponentRuntimeError(
                    "custom_component.dependency_slug_mismatch",
                    (
                        f"dependency pin {dependency_id!r} belongs to "
                        f"{dependency['slug']!r}, not {dependency_slug!r}"
                    ),
                )
        _, bundle = resolve_custom_component_artifact_blob(
            repository,
            blobs,
            account_id=account_id,
            artifact_id=artifact_id,
            member="bundle",
        )
        _, css = resolve_custom_component_artifact_blob(
            repository,
            blobs,
            account_id=account_id,
            artifact_id=artifact_id,
            member="css",
        )
        total_bytes += len(bundle) + len(css)
        if total_bytes > MAX_RUNTIME_GRAPH_BYTES:
            raise CustomComponentRuntimeError(
                "custom_component.runtime_size_limit",
                f"runtime graph exceeds {MAX_RUNTIME_GRAPH_BYTES} bytes",
            )
        by_id[artifact_id] = artifact
        bundles[f"artifact:{artifact_id}"] = bundle
        if import_name is not None:
            bundles[import_name] = bundle
        css_parts.append(css)
        active.remove(artifact_id)
        return artifact

    root = visit(root_artifact_id, "lumen:root")
    artifacts = [by_id[artifact_id] for artifact_id in sorted(by_id)]
    return root, bundles, css_parts, artifacts


def _runtime_theme(theme: Optional[JsonObject]) -> JsonObject:
    record = theme if isinstance(theme, dict) else {}
    tokens = record.get("tokens")
    colors = {
        str(key): str(value)
        for key, value in (tokens.items() if isinstance(tokens, dict) else [])
        if isinstance(key, str) and isinstance(value, str)
    }
    colors.setdefault("primary", "#335cff")
    colors.setdefault("secondary", "#7c3aed")
    colors.setdefault("dark", "#111827")
    colors.setdefault("light", "#ffffff")
    display = record.get("display_family")
    body = record.get("body_family")
    return {
        "colors": colors,
        "fonts": {
            "heading": display if isinstance(display, str) else "system-ui",
            "body": body if isinstance(body, str) else "system-ui",
        },
        "shadows": {},
        "breakpoints": {
            "sm": "640px",
            "md": "768px",
            "lg": "1024px",
            "xl": "1280px",
        },
    }


def _theme_css(theme: JsonObject) -> str:
    colors = theme["colors"]
    fonts = theme["fonts"]
    declarations = [
        f"--lumen-color-{name}:{value}"
        for name, value in sorted(colors.items())
        if re.fullmatch(r"[a-zA-Z0-9_-]+", name)
        and not any(char in value for char in "{};")
    ]
    declarations.extend(
        [
            f"--lumen-font-heading:{fonts['heading']}",
            f"--lumen-font-body:{fonts['body']}",
        ]
    )
    return ":root{" + ";".join(declarations) + "}"


def _build_runtime_srcdoc(
    *,
    host_javascript: bytes,
    node_id: str,
    artifact: JsonObject,
    bundles: Dict[str, bytes],
    css_parts: Iterable[bytes],
    first_frame: bytes,
    props: JsonObject,
    theme: JsonObject,
    override_variables: Dict[str, str],
    runtime_nonce: str,
    delivery_assets: Optional[_DeliveryAssetCatalog] = None,
) -> str:
    config = {
        "runtimeNonce": runtime_nonce,
        "nodeId": node_id,
        "artifactId": artifact["artifact_id"],
        "props": props,
        "theme": theme,
        "overrideVariables": override_variables,
    }
    component_css = "\n".join(
        part.decode("utf-8") for part in css_parts
    )
    base_css = """
html,body{margin:0;min-width:0;background:transparent;color:inherit}
body{font-family:var(--lumen-font-body,system-ui)}
#lumen-custom-component-root{display:flow-root;min-width:0}
.lumen-runtime-error{box-sizing:border-box;display:flex;min-height:96px;flex-direction:column;gap:6px;justify-content:center;padding:16px;border:1px solid #dc2626;border-radius:10px;background:#fef2f2;color:#7f1d1d;font:14px/1.4 system-ui}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
""".strip()
    combined_css = base_css + _theme_css(theme) + component_css

    if delivery_assets is None:
        imports = {
            "react": _data_javascript(_react_adapter()),
            "react/jsx-runtime": _data_javascript(_JSX_ADAPTER),
            "react/jsx-dev-runtime": _data_javascript(_JSX_DEV_ADAPTER),
        }
        imports.update(
            {
                specifier: _data_javascript(bundle)
                for specifier, bundle in sorted(bundles.items())
                if not specifier.startswith("artifact:")
            }
        )
        prelude_url = _data_javascript(_runtime_prelude(config))
        bootstrap_url = _data_javascript(_runtime_bootstrap(config))
        host_url = _data_javascript(host_javascript)
        style_markup = f"<style>{_style_text(combined_css)}</style>"
        script_sources = "'unsafe-inline' data:"
        style_sources = "'unsafe-inline'"
        script_crossorigin = ""
    else:
        def add_javascript(data: bytes | str, role: str) -> str:
            return str(
                delivery_assets.add(
                    data,
                    media_type="text/javascript; charset=utf-8",
                    extension="js",
                    role=role,
                )["url"]
            )

        imports = {
            "react": add_javascript(_react_adapter(), "react-adapter"),
            "react/jsx-runtime": add_javascript(
                _JSX_ADAPTER, "react-jsx-runtime-adapter"
            ),
            "react/jsx-dev-runtime": add_javascript(
                _JSX_DEV_ADAPTER, "react-jsx-development-runtime-adapter"
            ),
        }
        imports.update(
            {
                specifier: add_javascript(
                    bundle,
                    (
                        f"artifact-bundle:{artifact['artifact_id']}:{specifier}"
                    ),
                )
                for specifier, bundle in sorted(bundles.items())
                if not specifier.startswith("artifact:")
            }
        )
        prelude_url = add_javascript(
            _runtime_prelude(config), f"runtime-prelude:{node_id}"
        )
        bootstrap_url = add_javascript(
            _runtime_bootstrap(config), f"runtime-bootstrap:{node_id}"
        )
        host_url = add_javascript(host_javascript, "react-runtime-host")
        css_record = delivery_assets.add(
            combined_css,
            media_type="text/css; charset=utf-8",
            extension="css",
            role=f"component-styles:{node_id}",
        )
        style_markup = (
            '<link rel="stylesheet" href="'
            f'{html.escape(str(css_record["url"]), quote=True)}">'
        )
        origins = sorted(
            {
                f"{parts.scheme}://{parts.netloc}"
                for url in (
                    list(imports.values())
                    + [prelude_url, bootstrap_url, host_url, str(css_record["url"])]
                )
                for parts in [urlsplit(url)]
                if parts.scheme in {"http", "https"} and parts.netloc
            }
        )
        allowed_origins = " ".join(origins)
        script_sources = (
            "'unsafe-inline' " + allowed_origins
        ).strip()
        style_sources = ("'unsafe-inline' " + allowed_origins).strip()
        script_crossorigin = ' crossorigin="anonymous"'

    first_frame_text = first_frame.decode("utf-8")
    if delivery_assets is not None:
        delivery_assets.add(
            first_frame,
            media_type="text/html; charset=utf-8",
            extension="html",
            role=f"server-first-frame:{node_id}",
        )
    srcdoc = (
        "<!doctype html><html lang=\"en\"><head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta name=\"referrer\" content=\"no-referrer\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\""
        f"default-src 'none'; script-src {script_sources}; "
        f"style-src {style_sources}; img-src data: blob:; font-src data:; "
        "connect-src 'none'; media-src data: blob:; object-src 'none'; "
        "frame-src 'none'; worker-src 'none'; base-uri 'none'; form-action 'none'; "
        "navigate-to 'none'"
        "\">"
        f"{style_markup}"
        f"<script src=\"{html.escape(host_url, quote=True)}\"{script_crossorigin}></script>"
        f"<script src=\"{html.escape(prelude_url, quote=True)}\"{script_crossorigin}></script>"
        f"<script type=\"importmap\">{_json_for_html({'imports': imports})}</script>"
        "</head><body>"
        f"<div id=\"lumen-custom-component-root\">{first_frame_text}</div>"
        f"<script type=\"module\" src=\"{html.escape(bootstrap_url, quote=True)}\"{script_crossorigin}></script>"
        "</body></html>"
    )
    if len(srcdoc.encode("utf-8")) > MAX_RUNTIME_HTML_BYTES:
        raise CustomComponentRuntimeError(
            "custom_component.runtime_html_limit",
            f"runtime document exceeds {MAX_RUNTIME_HTML_BYTES} bytes",
        )
    return srcdoc


def _custom_component_nodes(
    web_doc: JsonObject, page_id: str
) -> List[Tuple[str, JsonObject]]:
    pages = web_doc.get("pages")
    if not isinstance(pages, list):
        return []
    page = next(
        (
            item
            for item in pages
            if isinstance(item, dict) and item.get("id") == page_id
        ),
        None,
    )
    if page is None:
        page = next((item for item in pages if isinstance(item, dict)), None)
    if not isinstance(page, dict):
        return []
    nodes = page.get("nodes")
    if not isinstance(nodes, dict):
        return []
    root = page.get("root") if isinstance(page.get("root"), str) else "root"
    pending = [root]
    seen: set[str] = set()
    result: List[Tuple[str, JsonObject]] = []
    while pending:
        node_id = pending.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        node = nodes.get(node_id)
        if not isinstance(node, dict):
            continue
        if node.get("kind") == "custom_component":
            result.append((node_id, node))
        children = node.get("children")
        if isinstance(children, list):
            pending.extend(
                reversed([child for child in children if isinstance(child, str)])
            )
    return result


def web_doc_uses_custom_components(web_doc: JsonObject, page_id: str) -> bool:
    return bool(_custom_component_nodes(web_doc, page_id))


def _artifact_publish_record(
    artifact: JsonObject,
    catalog: _DeliveryAssetCatalog,
) -> JsonObject:
    manifest = artifact.get("manifest")
    compiler = manifest.get("compiler") if isinstance(manifest, dict) else None
    dependencies = (
        manifest.get("dependency_artifacts")
        if isinstance(manifest, dict)
        else None
    )

    def blob_record(name: str) -> Optional[JsonObject]:
        blob = artifact.get(name)
        if not isinstance(blob, dict):
            return None
        digest = blob.get("value")
        packaged = catalog.records.get(digest) if isinstance(digest, str) else None
        return {
            "algorithm": blob.get("algorithm"),
            "digest": digest,
            "byte_length": blob.get("byte_length"),
            "url": packaged.get("url") if packaged else None,
        }

    return {
        "artifact_id": artifact["artifact_id"],
        "slug": artifact["slug"],
        "source": blob_record("source"),
        "bundle": blob_record("bundle"),
        "css": blob_record("css"),
        "first_frame": blob_record("first_frame"),
        "dependency_artifacts": (
            dict(sorted(dependencies.items()))
            if isinstance(dependencies, dict)
            else {}
        ),
        "compiler": compiler if isinstance(compiler, dict) else {},
        "provenance": (
            artifact.get("provenance")
            if isinstance(artifact.get("provenance"), dict)
            else {}
        ),
    }


def _assemble_custom_component_runtime(
    repository: HybridRepository,
    blobs: DesignBlobStore,
    *,
    account_id: Optional[str],
    web_doc: JsonObject,
    page_id: str,
    theme: Optional[JsonObject],
    override_variables: Dict[str, str],
    runtime_host_path: Path,
    delivery_asset_url_for: Optional[Callable[[str, str], str]] = None,
    deterministic_seed: Optional[str] = None,
    strict: bool = False,
) -> CustomComponentDeliveryPackage:
    """Resolve reachable custom components into frames and optional assets."""

    package = CustomComponentDeliveryPackage()
    frames = package.frames
    nodes = _custom_component_nodes(web_doc, page_id)
    if not nodes:
        package.manifest = {
            "schema_version": 1,
            "runtime_contract_version": RUNTIME_CONTRACT_VERSION,
            "components": [],
            "artifacts": [],
            "assets": [],
        }
        return package
    runtime_theme = _runtime_theme(theme)
    delivery_assets = (
        _DeliveryAssetCatalog(delivery_asset_url_for)
        if delivery_asset_url_for is not None
        else None
    )
    artifact_records: Dict[str, JsonObject] = {}
    component_records: List[JsonObject] = []
    try:
        host_javascript = _read_runtime_host(str(runtime_host_path.resolve()))
    except (OSError, CustomComponentRuntimeError) as error:
        host_javascript = b""
        host_failure = (
            error
            if isinstance(error, CustomComponentRuntimeError)
            else CustomComponentRuntimeError(
                "custom_component.runtime_host_missing",
                "the trusted React runtime host could not be loaded",
            )
        )
    else:
        host_failure = None

    for node_id, node in nodes:
        slug = node.get("slug") if isinstance(node.get("slug"), str) else "unknown"
        artifact_id = (
            node.get("artifact_id")
            if isinstance(node.get("artifact_id"), str)
            else ""
        )
        unavailable: Optional[CustomComponentRuntimeError] = host_failure
        if account_id is None:
            unavailable = CustomComponentRuntimeError(
                "custom_component.account_required",
                "this website has no account-scoped component registry",
            )
        if unavailable is None:
            try:
                artifact, bundles, css_parts, artifacts = _resolve_artifact_graph(
                    repository,
                    blobs,
                    account_id=account_id or "",
                    root_artifact_id=artifact_id,
                )
                if artifact["slug"] != slug:
                    raise CustomComponentRuntimeError(
                        "custom_component.artifact_slug_mismatch",
                        f"artifact {artifact_id!r} does not belong to {slug!r}",
                    )
                _, first_frame = resolve_custom_component_artifact_blob(
                    repository,
                    blobs,
                    account_id=account_id or "",
                    artifact_id=artifact_id,
                    member="first_frame",
                )
                manifest = artifact["manifest"]
                name = manifest.get("meta", {}).get("name")
                if not isinstance(name, str) or not name.strip():
                    name = slug
                runtime_nonce = (
                    hashlib.sha256(
                        (
                            f"{deterministic_seed}:{node_id}:"
                            f"{artifact['artifact_id']}"
                        ).encode("utf-8")
                    ).hexdigest()[:32]
                    if deterministic_seed is not None
                    else uuid4().hex
                )
                if delivery_assets is not None:
                    for graph_artifact in artifacts:
                        graph_artifact_id = str(graph_artifact["artifact_id"])
                        for member, media_type, extension in (
                            (
                                "bundle",
                                "text/javascript; charset=utf-8",
                                "js",
                            ),
                            ("css", "text/css; charset=utf-8", "css"),
                            (
                                "first_frame",
                                "text/html; charset=utf-8",
                                "html",
                            ),
                        ):
                            _, member_bytes = resolve_custom_component_artifact_blob(
                                repository,
                                blobs,
                                account_id=account_id or "",
                                artifact_id=graph_artifact_id,
                                member=member,
                            )
                            delivery_assets.add(
                                member_bytes,
                                media_type=media_type,
                                extension=extension,
                                role=f"artifact-{member}:{graph_artifact_id}",
                            )
                srcdoc = _build_runtime_srcdoc(
                    host_javascript=host_javascript,
                    node_id=node_id,
                    artifact=artifact,
                    bundles=bundles,
                    css_parts=css_parts,
                    first_frame=first_frame,
                    props=(
                        node.get("props")
                        if isinstance(node.get("props"), dict)
                        else {}
                    ),
                    theme=runtime_theme,
                    override_variables=override_variables,
                    runtime_nonce=runtime_nonce,
                    delivery_assets=delivery_assets,
                )
                frames[node_id] = {
                    "state": "ready",
                    "artifact_id": artifact_id,
                    "name": name,
                    "srcdoc": srcdoc,
                    "runtime_nonce": runtime_nonce,
                    "intrinsic_height": not _FIXED_HEIGHT_CLASS.search(
                        str(node.get("classes") or "")
                    ),
                    "warning_count": len(manifest.get("warnings") or []),
                }
                component_records.append(
                    {
                        "node_id": node_id,
                        "slug": slug,
                        "artifact_id": artifact_id,
                        "props_digest": hashlib.sha256(
                            json.dumps(
                                (
                                    node.get("props")
                                    if isinstance(node.get("props"), dict)
                                    else {}
                                ),
                                ensure_ascii=True,
                                separators=(",", ":"),
                                sort_keys=True,
                            ).encode("utf-8")
                        ).hexdigest(),
                        "runtime_nonce": runtime_nonce,
                    }
                )
                if delivery_assets is not None:
                    for graph_artifact in artifacts:
                        artifact_records[str(graph_artifact["artifact_id"])] = (
                            _artifact_publish_record(
                                graph_artifact,
                                delivery_assets,
                            )
                        )
                continue
            except (
                CustomComponentRuntimeError,
                NotFoundError,
                OSError,
                RuntimeError,
                UnicodeDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ) as error:
                unavailable = (
                    error
                    if isinstance(error, CustomComponentRuntimeError)
                    else CustomComponentRuntimeError(
                        "custom_component.runtime_unavailable",
                        "the pinned artifact could not be assembled safely",
                    )
                )
        assert unavailable is not None
        frames[node_id] = {
            "state": "unavailable",
            "artifact_id": artifact_id,
            "name": slug,
            "message": str(unavailable),
            "error_code": unavailable.code,
            "intrinsic_height": not _FIXED_HEIGHT_CLASS.search(
                str(node.get("classes") or "")
            ),
            "warning_count": 0,
        }
        if strict:
            raise unavailable

    if delivery_assets is not None:
        package.assets = delivery_assets.assets
        host_digest = hashlib.sha256(host_javascript).hexdigest()
        package.manifest = {
            "schema_version": 1,
            "runtime_contract_version": RUNTIME_CONTRACT_VERSION,
            "runtime_host": delivery_assets.records.get(host_digest),
            "components": sorted(
                component_records, key=lambda record: str(record["node_id"])
            ),
            "artifacts": [
                artifact_records[key] for key in sorted(artifact_records)
            ],
            "assets": [
                delivery_assets.records[key]
                for key in sorted(delivery_assets.records)
            ],
        }
    else:
        package.manifest = {
            "schema_version": 1,
            "runtime_contract_version": RUNTIME_CONTRACT_VERSION,
            "components": sorted(
                component_records, key=lambda record: str(record["node_id"])
            ),
            "artifacts": [],
            "assets": [],
        }
    return package


def build_custom_component_runtime_frames(
    repository: HybridRepository,
    blobs: DesignBlobStore,
    *,
    account_id: Optional[str],
    web_doc: JsonObject,
    page_id: str,
    theme: Optional[JsonObject],
    override_variables: Dict[str, str],
    runtime_host_path: Path,
) -> Dict[str, JsonObject]:
    """Resolve every reachable custom-component node into an editor frame."""

    return _assemble_custom_component_runtime(
        repository,
        blobs,
        account_id=account_id,
        web_doc=web_doc,
        page_id=page_id,
        theme=theme,
        override_variables=override_variables,
        runtime_host_path=runtime_host_path,
    ).frames


def build_custom_component_delivery_package(
    repository: HybridRepository,
    blobs: DesignBlobStore,
    *,
    account_id: Optional[str],
    web_doc: JsonObject,
    page_id: str,
    theme: Optional[JsonObject],
    override_variables: Dict[str, str],
    runtime_host_path: Path,
    asset_url_for: Callable[[str, str], str],
    deterministic_seed: str,
) -> CustomComponentDeliveryPackage:
    """Build a strict immutable delivery package for publish.

    Unlike editor preview, delivery fails if any pinned node cannot be
    assembled. A publish therefore never degrades into a placeholder while
    claiming success.
    """

    return _assemble_custom_component_runtime(
        repository,
        blobs,
        account_id=account_id,
        web_doc=web_doc,
        page_id=page_id,
        theme=theme,
        override_variables=override_variables,
        runtime_host_path=runtime_host_path,
        delivery_asset_url_for=asset_url_for,
        deterministic_seed=deterministic_seed,
        strict=True,
    )
