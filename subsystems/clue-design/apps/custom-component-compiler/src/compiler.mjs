import crypto from "node:crypto";

import {
  COMPILER_VERSION,
  CURATED_PACKAGE_VERSIONS,
  PROTOCOL_VERSION,
  TOOLCHAIN_PACKAGE_VERSIONS,
  hasErrors,
  sortDiagnostics,
} from "./contracts.mjs";
import { analyzeComponent } from "./analyze.mjs";
import {
  buildBrowserBundle,
  buildComponentCss,
  renderFirstFrame,
} from "./build.mjs";

function sha256(value) {
  return crypto.createHash("sha256").update(value, "utf8").digest("hex");
}

export async function compileComponent(input) {
  const analysis = analyzeComponent(input);
  if (hasErrors(analysis.diagnostics)) {
    return {
      protocol_version: PROTOCOL_VERSION,
      compiler_version: COMPILER_VERSION,
      status: "failed",
      diagnostics: sortDiagnostics(analysis.diagnostics),
    };
  }

  const [browser, css, firstFrame] = await Promise.all([
    buildBrowserBundle(input),
    buildComponentCss(input),
    renderFirstFrame(input),
  ]);
  const diagnostics = [
    ...analysis.diagnostics,
    ...browser.diagnostics,
    ...css.diagnostics,
    ...firstFrame.diagnostics,
  ];
  if (
    hasErrors(diagnostics) ||
    browser.bundle == null ||
    css.css == null ||
    firstFrame.html == null
  ) {
    return {
      protocol_version: PROTOCOL_VERSION,
      compiler_version: COMPILER_VERSION,
      status: "failed",
      diagnostics: sortDiagnostics(diagnostics),
    };
  }

  const warnings = sortDiagnostics(diagnostics).filter(
    (item) => item.severity === "warning",
  );
  const manifest = {
    schema_version: 2,
    compiler: {
      protocol_version: PROTOCOL_VERSION,
      version: COMPILER_VERSION,
    },
    entry: input.entry,
    source_files: Object.keys(input.files).sort(),
    meta: analysis.meta,
    props_schema: analysis.propsSchema,
    defaults: analysis.defaults,
    dependency_artifacts: analysis.dependencies,
    curated_package_versions: CURATED_PACKAGE_VERSIONS,
    toolchain_package_versions: TOOLCHAIN_PACKAGE_VERSIONS,
    browser: {
      format: "esm",
      react: "host-singleton",
      target: "es2020",
    },
    css: {
      contract_version: 1,
      strategy: "tailwind-static-source",
      dynamic_class_policy: "reject",
    },
    first_frame: {
      format: "html",
      render_contract_version: 1,
      dependency_strategy: "pinned-placeholder",
    },
    warnings,
  };
  return {
    protocol_version: PROTOCOL_VERSION,
    compiler_version: COMPILER_VERSION,
    status: "success",
    diagnostics: warnings,
    manifest,
    outputs: {
      browser_bundle: browser.bundle,
      component_css: css.css,
      first_frame_html: firstFrame.html,
    },
    digests: {
      browser_bundle_sha256: sha256(browser.bundle),
      component_css_sha256: sha256(css.css),
      first_frame_sha256: sha256(firstFrame.html),
    },
  };
}
