/**
 * W4.7 fixtures: the REAL custom-component artifact + instance node, exactly as
 * the design API serves them — NOT hand-written shapes. Same discipline as
 * `web-nodes.ts` / `web-rich-text.ts`.
 *
 * Harvest provenance (workspace `ws_8040294627e146ae93f753ec0d3e1726`, lane
 * design API 127.0.0.1:8013, captured 2026-08-18):
 *   • artifact — `GET /web/accounts/acc_403fa12213464a9cbb2a9a1dab3663db
 *     /custom-component-artifacts/ccart_765fe726…0925c` → 200, the `artifact`
 *     key verbatim. Its `props_schema` deliberately covers ALL FOUR control
 *     kinds the form dispatches over: `accent` (string + enum → select),
 *     `headline` (string → text), `planCount` (number → number), `showBadge`
 *     (boolean → checkbox), with a default for each.
 *   • node — `GET /documents/doc_b778a805381c4831844c490e30701719` → 200, the
 *     account-bound "Lane C custom-component test doc" at v1; node `cclanec1`
 *     (kind `custom_component`) inside section `secc` on page `home`.
 *
 * The manifest carries more keys than `CustomComponentManifest` declares
 * (`css`, `entry`, `compiler`, `first_frame`, `source_files`,
 * `curated_package_versions`, …). That is on purpose: this is the wire body,
 * and the engine's own parser ends with `artifact as unknown as
 * CustomComponentArtifact` (`webDocuments.ts:2286`) — it validates, it does not
 * strip. The cast below is the same one, so the props form is exercised against
 * exactly the object it receives at runtime.
 */
import type {
  CustomComponentArtifact,
  WebNode,
} from "../../engine/webDocuments";

const RAW_ARTIFACT = {
  artifact_id:
    "ccart_765fe726e17be4859452c9ff3293ec8d1149689f7b786f9834a2ec20c210925c",
  account_id: "acc_403fa12213464a9cbb2a9a1dab3663db",
  slug: "lane-c-pricing-card",
  source: {
    algorithm: "sha256",
    value: "e2a787bfdfd1fc106b37cf2bca14a45fe74b9d7da93f700e68527c0387782f1f",
    opaque_ref:
      "ws_8040294627e146ae93f753ec0d3e1726/design/e2a787bfdfd1fc106b37cf2bca14a45fe74b9d7da93f700e68527c0387782f1f",
    byte_length: 970,
  },
  bundle: {
    algorithm: "sha256",
    value: "631a71a2d768178042599f7460a75b60592ea6d1d192eda8f661210aaafabac7",
    opaque_ref:
      "ws_8040294627e146ae93f753ec0d3e1726/design/631a71a2d768178042599f7460a75b60592ea6d1d192eda8f661210aaafabac7",
    byte_length: 396,
  },
  css: {
    algorithm: "sha256",
    value: "c01917ac9e01c1e6fcc2632175054cf017cb9fb11e8946295be7f9f05f5da200",
    opaque_ref:
      "ws_8040294627e146ae93f753ec0d3e1726/design/c01917ac9e01c1e6fcc2632175054cf017cb9fb11e8946295be7f9f05f5da200",
    byte_length: 362,
  },
  first_frame: {
    algorithm: "sha256",
    value: "c8c073f852beb09527bd6dddcbf551b01d2672d448e25f256b89e62694203848",
    opaque_ref:
      "ws_8040294627e146ae93f753ec0d3e1726/design/c8c073f852beb09527bd6dddcbf551b01d2672d448e25f256b89e62694203848",
    byte_length: 133,
  },
  manifest: {
    css: {
      strategy: "tailwind-static-source",
      contract_version: 1,
      dynamic_class_policy: "reject",
    },
    meta: {
      name: "Lane C Pricing Card",
      description:
        "A compact pricing callout for the Lane C props-form verification.",
    },
    entry: "lane-c-pricing-card.tsx",
    browser: {
      react: "host-singleton",
      format: "esm",
      target: "es2020",
    },
    compiler: {
      version: "lumen-custom-component-compiler/1",
      protocol_version: 1,
    },
    defaults: {
      accent: "blue",
      headline: "Pricing",
      planCount: 3,
      showBadge: true,
    },
    warnings: [],
    first_frame: {
      format: "html",
      dependency_strategy: "pinned-placeholder",
      render_contract_version: 1,
    },
    props_schema: {
      type: "object",
      properties: {
        accent: {
          enum: ["blue", "green"],
          type: "string",
          default: "blue",
        },
        headline: {
          type: "string",
          default: "Pricing",
        },
        planCount: {
          type: "number",
          default: 3,
        },
        showBadge: {
          type: "boolean",
          default: true,
        },
      },
      additionalProperties: false,
    },
    source_files: ["lane-c-pricing-card.tsx"],
    schema_version: 2,
    dependency_artifacts: {},
    curated_package_versions: {
      gsap: "3.13.0",
      react: "18.3.1",
      motion: "12.23.12",
      "@gsap/react": "2.1.2",
      "@visx/curve": "3.12.0",
      "@visx/group": "3.12.0",
      "@visx/scale": "3.12.0",
      "@visx/shape": "3.12.0",
    },
    toolchain_package_versions: {
      esbuild: "0.25.8",
      postcss: "8.5.25",
      "react-dom": "18.3.1",
      typescript: "5.8.3",
      tailwindcss: "3.4.17",
    },
  },
  provenance: {
    kind: "lumen_custom_component_compiler",
    actor: { id: null, kind: "human" },
    source_version: 1,
    compiler_version: "lumen-custom-component-compiler/1",
    source_revision_id:
      "ccsrc_31ae23579783bd637376cd93a4e9f121c944de8edbbf7f923eb4cdece2592d72",
    dependency_artifacts: {},
    compiler_protocol_version: 1,
  },
  created_at: "2026-08-18T16:41:31.133715+00:00",
};

/** The pinned artifact whose `props_schema` the form renders from. */
export const CUSTOM_COMPONENT_ARTIFACT =
  RAW_ARTIFACT as unknown as CustomComponentArtifact;

/** The seeded document's page id — what the commit op must address. */
export const CUSTOM_COMPONENT_PAGE_ID = "home";

/** The instance node: the artifact pin (`slug` + `artifact_id`) plus the props
 * currently on the wire. A prop commit RESENDS this whole object with one key
 * changed (the W3.2 lesson: `set_node_props` replaces wholesale). */
export const CUSTOM_COMPONENT_NODE: WebNode = {
  id: "cclanec1",
  kind: "custom_component",
  slug: "lane-c-pricing-card",
  props: {
    accent: "blue",
    headline: "Pricing",
    planCount: 3,
    showBadge: true,
  },
  classes: "w-full min-h-[160px]",
  artifact_id:
    "ccart_765fe726e17be4859452c9ff3293ec8d1149689f7b786f9834a2ec20c210925c",
};

/** The page the node actually belongs to, as served — the node-membership
 * resolution the commit path performs before addressing an op.
 *
 * Every id below resolves: `root` → `secc` → `cclanec1`, the chain the harvest
 * note above attests. An earlier draft also carried a `boxc` container whose
 * `children` named `txthead`/`txtbody` — copy residue from the rich-text
 * fixture's own seeded document (`web-rich-text.ts`, a DIFFERENT doc), and
 * dangling here because this page serves no such nodes. It is dropped rather
 * than filled in: inventing two text nodes would put hand-written shapes into a
 * fixture whose whole claim is that it is the wire body verbatim, and a
 * tree-walking consumer would follow the invention off a cliff either way.
 */
export const CUSTOM_COMPONENT_PAGE: {
  page_root: string;
  nodes: Record<string, WebNode>;
} = {
  page_root: "root",
  nodes: {
    root: {
      id: "root",
      tag: "div",
      kind: "container",
      classes: "",
      children: ["secc"],
    },
    secc: {
      id: "secc",
      tag: "section",
      kind: "section",
      classes: "",
      children: ["cclanec1"],
    },
    cclanec1: CUSTOM_COMPONENT_NODE,
  },
};
