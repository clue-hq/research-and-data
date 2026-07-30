import path from "node:path";
import { createRequire } from "node:module";

import ts from "typescript";

import {
  ALLOWED_BARE_IMPORTS,
  MAX_FILE_BYTES,
  MAX_FILE_COUNT,
  MAX_SOURCE_BYTES,
  diagnostic,
  hasErrors,
  slugIsValid,
  sourcePathIsValid,
} from "./contracts.mjs";

const require = createRequire(import.meta.url);
const COMPILER_ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const VIRTUAL_ROOT = "/__lumen_custom_components__";

function nodeLocation(sourceFile, node) {
  const position = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile));
  return {
    file: sourceFile.fileName,
    line: position.line + 1,
    column: position.character + 1,
  };
}

function issue(sourceFile, node, values) {
  return diagnostic({ ...values, ...nodeLocation(sourceFile, node) });
}

function isExported(node) {
  return Boolean(
    node.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword),
  );
}

function isDefaultExport(node) {
  return Boolean(
    node.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.DefaultKeyword),
  );
}

function expressionHasName(node, name) {
  return (
    (ts.isIdentifier(node) && node.text === name) ||
    (ts.isPropertyAccessExpression(node) && node.name.text === name)
  );
}

function literalValue(node) {
  if (
    ts.isStringLiteral(node) ||
    ts.isNoSubstitutionTemplateLiteral(node) ||
    ts.isNumericLiteral(node)
  ) {
    return ts.isNumericLiteral(node) ? Number(node.text) : node.text;
  }
  if (node.kind === ts.SyntaxKind.TrueKeyword) return true;
  if (node.kind === ts.SyntaxKind.FalseKeyword) return false;
  if (
    ts.isPrefixUnaryExpression(node) &&
    node.operator === ts.SyntaxKind.MinusToken &&
    ts.isNumericLiteral(node.operand)
  ) {
    return -Number(node.operand.text);
  }
  return undefined;
}

function staticClassExpression(node) {
  if (
    ts.isStringLiteral(node) ||
    ts.isNoSubstitutionTemplateLiteral(node)
  ) {
    return true;
  }
  if (ts.isParenthesizedExpression(node)) {
    return staticClassExpression(node.expression);
  }
  if (ts.isConditionalExpression(node)) {
    return (
      staticClassExpression(node.whenTrue) &&
      staticClassExpression(node.whenFalse)
    );
  }
  if (
    ts.isBinaryExpression(node) &&
    node.operatorToken.kind === ts.SyntaxKind.PlusToken
  ) {
    return staticClassExpression(node.left) && staticClassExpression(node.right);
  }
  if (ts.isArrayLiteralExpression(node)) {
    return node.elements.every((element) => staticClassExpression(element));
  }
  return false;
}

function resolveRelativePath(importer, specifier, files) {
  const base = path.posix.normalize(
    path.posix.join(path.posix.dirname(importer), specifier),
  );
  if (base === ".." || base.startsWith("../") || path.posix.isAbsolute(base)) {
    return { error: "escape" };
  }
  if (path.posix.extname(base).toLowerCase() === ".css") {
    return { error: "css" };
  }
  const candidates = path.posix.extname(base)
    ? [base]
    : [
        base,
        ...[".ts", ".tsx", ".js", ".jsx"].map((extension) => `${base}${extension}`),
        ...[".ts", ".tsx", ".js", ".jsx"].map((extension) =>
          path.posix.join(base, `index${extension}`),
        ),
      ];
  const found = candidates.find((candidate) =>
    Object.prototype.hasOwnProperty.call(files, candidate),
  );
  return found ? { path: found } : { error: "missing" };
}

function validateRequest(input) {
  const diagnostics = [];
  if (input?.protocol_version !== 1) {
    diagnostics.push(
      diagnostic({
        code: "CCC0001",
        category: "contract",
        message: "compiler protocol_version must be 1",
      }),
    );
  }
  if (!slugIsValid(input?.slug)) {
    diagnostics.push(
      diagnostic({
        code: "CCC0002",
        category: "contract",
        message: "slug must be 1–64 lowercase kebab-case characters",
      }),
    );
  }
  if (!input?.files || typeof input.files !== "object" || Array.isArray(input.files)) {
    diagnostics.push(
      diagnostic({
        code: "CCC0003",
        category: "contract",
        message: "files must be an object of relative paths to UTF-8 source strings",
      }),
    );
    return diagnostics;
  }
  const entries = Object.entries(input.files);
  if (entries.length === 0 || entries.length > MAX_FILE_COUNT) {
    diagnostics.push(
      diagnostic({
        code: "CCC0004",
        category: "contract",
        message: `a component must contain 1–${MAX_FILE_COUNT} source files`,
      }),
    );
  }
  let totalBytes = 0;
  for (const [file, source] of entries) {
    if (!sourcePathIsValid(file)) {
      diagnostics.push(
        diagnostic({
          code: "CCC0005",
          category: "contract",
          message: `source path is invalid or escapes the component directory: ${file}`,
          file,
        }),
      );
      continue;
    }
    if (typeof source !== "string") {
      diagnostics.push(
        diagnostic({
          code: "CCC0006",
          category: "contract",
          message: "source file content must be a string",
          file,
        }),
      );
      continue;
    }
    const byteLength = Buffer.byteLength(source, "utf8");
    totalBytes += byteLength;
    if (byteLength > MAX_FILE_BYTES) {
      diagnostics.push(
        diagnostic({
          code: "CCC0007",
          category: "contract",
          message: `source file exceeds ${MAX_FILE_BYTES} bytes`,
          file,
        }),
      );
    }
  }
  if (totalBytes > MAX_SOURCE_BYTES) {
    diagnostics.push(
      diagnostic({
        code: "CCC0008",
        category: "contract",
        message: `component source exceeds ${MAX_SOURCE_BYTES} bytes`,
      }),
    );
  }
  const expectedEntry = `${input?.slug}.tsx`;
  if (input?.entry !== expectedEntry || !(expectedEntry in input.files)) {
    diagnostics.push(
      diagnostic({
        code: "CCC0009",
        category: "contract",
        message: `entry must be the existing file ${expectedEntry}`,
        file: input?.entry ?? null,
      }),
    );
  }
  if (
    input?.component_artifacts == null ||
    typeof input.component_artifacts !== "object" ||
    Array.isArray(input.component_artifacts)
  ) {
    diagnostics.push(
      diagnostic({
        code: "CCC0010",
        category: "contract",
        message: "component_artifacts must be an object of slug-to-artifact pins",
      }),
    );
  }
  return diagnostics;
}

function analyzeImportsAndPolicy(input, sourceFiles, diagnostics) {
  const dependencySlugs = new Set();
  const relativeImports = new Map();

  for (const [file, sourceFile] of sourceFiles) {
    const fileImports = new Map();
    relativeImports.set(file, fileImports);
    const visit = (node) => {
      if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
        const specifier = node.moduleSpecifier.text;
        if (specifier.endsWith(".css")) {
          diagnostics.push(
            issue(sourceFile, node.moduleSpecifier, {
              code: "CCC0101",
              category: "imports",
              message: "CSS imports are forbidden; use Tailwind classes",
            }),
          );
        } else if (specifier.startsWith(".")) {
          const resolved = resolveRelativePath(file, specifier, input.files);
          if (resolved.error === "escape") {
            diagnostics.push(
              issue(sourceFile, node.moduleSpecifier, {
                code: "CCC0102",
                category: "imports",
                message: "relative imports may not escape the component directory",
              }),
            );
          } else if (resolved.error === "css") {
            diagnostics.push(
              issue(sourceFile, node.moduleSpecifier, {
                code: "CCC0101",
                category: "imports",
                message: "CSS imports are forbidden; use Tailwind classes",
              }),
            );
          } else if (resolved.error === "missing") {
            diagnostics.push(
              issue(sourceFile, node.moduleSpecifier, {
                code: "CCC0103",
                category: "imports",
                message: `relative import does not resolve: ${specifier}`,
              }),
            );
          } else {
            fileImports.set(specifier, resolved.path);
          }
        } else if (specifier.startsWith("components/")) {
          const dependency = specifier.slice("components/".length);
          if (
            !slugIsValid(dependency) ||
            dependency.includes("/") ||
            dependency === input.slug
          ) {
            diagnostics.push(
              issue(sourceFile, node.moduleSpecifier, {
                code: "CCC0104",
                category: "imports",
                message: `component import is invalid: ${specifier}`,
              }),
            );
          } else if (!input.component_artifacts[dependency]) {
            diagnostics.push(
              issue(sourceFile, node.moduleSpecifier, {
                code: "CCC0105",
                category: "imports",
                message: `component dependency is not attachable for this account: ${dependency}`,
              }),
            );
          } else {
            dependencySlugs.add(dependency);
          }
        } else if (!ALLOWED_BARE_IMPORTS.has(specifier)) {
          diagnostics.push(
            issue(sourceFile, node.moduleSpecifier, {
              code: "CCC0106",
              category: "imports",
              message: `bare import is not allowed: ${specifier}`,
            }),
          );
        }
      }

      if (
        ts.isCallExpression(node) &&
        node.expression.kind === ts.SyntaxKind.ImportKeyword
      ) {
        diagnostics.push(
          issue(sourceFile, node, {
            code: "CCC0110",
            category: "policy",
            message: "dynamic import() is forbidden",
          }),
        );
      }
      if (
        ts.isCallExpression(node) &&
        expressionHasName(node.expression, "eval")
      ) {
        diagnostics.push(
          issue(sourceFile, node, {
            code: "CCC0111",
            category: "policy",
            message: "eval() is forbidden",
          }),
        );
      }
      if (
        ts.isCallExpression(node) &&
        ts.isIdentifier(node.expression) &&
        node.expression.text === "require"
      ) {
        diagnostics.push(
          issue(sourceFile, node, {
            code: "CCC0112",
            category: "policy",
            message: "CommonJS require() is forbidden",
          }),
        );
      }
      if (
        (ts.isNewExpression(node) || ts.isCallExpression(node)) &&
        expressionHasName(node.expression, "Function")
      ) {
        diagnostics.push(
          issue(sourceFile, node, {
            code: "CCC0113",
            category: "policy",
            message: "new Function() is forbidden",
          }),
        );
      }
      if (
        ts.isCallExpression(node) &&
        ts.isPropertyAccessExpression(node.expression) &&
        ts.isIdentifier(node.expression.expression) &&
        node.expression.expression.text === "document" &&
        node.expression.name.text === "write"
      ) {
        diagnostics.push(
          issue(sourceFile, node, {
            code: "CCC0114",
            category: "policy",
            message: "document.write() is forbidden",
          }),
        );
      }
      if (
        (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) &&
        ts.isIdentifier(node.tagName) &&
        node.tagName.text.toLowerCase() === "script"
      ) {
        diagnostics.push(
          issue(sourceFile, node, {
            code: "CCC0115",
            category: "policy",
            message: "script elements are forbidden in component output",
          }),
        );
      }
      if (
        ts.isJsxAttribute(node) &&
        ts.isIdentifier(node.name) &&
        node.name.text === "dangerouslySetInnerHTML"
      ) {
        diagnostics.push(
          issue(sourceFile, node, {
            code: "CCC0116",
            category: "policy",
            message: "dangerouslySetInnerHTML is forbidden",
          }),
        );
      }
      if (
        ts.isJsxAttribute(node) &&
        node.name.text === "className" &&
        node.initializer &&
        ts.isJsxExpression(node.initializer) &&
        node.initializer.expression &&
        !staticClassExpression(node.initializer.expression)
      ) {
        diagnostics.push(
          issue(sourceFile, node, {
            code: "CCC0120",
            category: "tailwind",
            message:
              "dynamic className values are not compiled; use complete static class strings in each branch",
          }),
        );
      }
      ts.forEachChild(node, visit);
    };
    visit(sourceFile);
  }

  return {
    dependencies: Object.fromEntries(
      [...dependencySlugs]
        .sort()
        .map((slug) => [slug, input.component_artifacts[slug]]),
    ),
    relativeImports,
  };
}

function propTypeSchema(typeNode) {
  if (!typeNode) return null;
  if (typeNode.kind === ts.SyntaxKind.StringKeyword) return { type: "string" };
  if (typeNode.kind === ts.SyntaxKind.NumberKeyword) return { type: "number" };
  if (typeNode.kind === ts.SyntaxKind.BooleanKeyword) return { type: "boolean" };
  if (ts.isUnionTypeNode(typeNode)) {
    const values = typeNode.types.map((member) =>
      ts.isLiteralTypeNode(member) && ts.isStringLiteral(member.literal)
        ? member.literal.text
        : null,
    );
    if (values.every((value) => value !== null)) {
      return { type: "string", enum: values };
    }
  }
  return null;
}

function extractProps(sourceFile, diagnostics) {
  const properties = {};
  const required = [];
  let declaration = null;
  for (const statement of sourceFile.statements) {
    if (
      (ts.isTypeAliasDeclaration(statement) ||
        ts.isInterfaceDeclaration(statement)) &&
      statement.name.text === "Props"
    ) {
      declaration = statement;
      break;
    }
  }
  if (!declaration) {
    return {
      type: "object",
      properties,
      additionalProperties: false,
    };
  }
  const members = ts.isTypeAliasDeclaration(declaration)
    ? ts.isTypeLiteralNode(declaration.type)
      ? declaration.type.members
      : []
    : declaration.members;
  if (ts.isTypeAliasDeclaration(declaration) && !ts.isTypeLiteralNode(declaration.type)) {
    diagnostics.push(
      issue(sourceFile, declaration, {
        code: "CCW0201",
        severity: "warning",
        category: "props",
        message: "Props must be an object type literal or interface to generate controls",
      }),
    );
  }
  for (const member of members) {
    if (!ts.isPropertySignature(member) || !member.name) continue;
    const name =
      ts.isIdentifier(member.name) || ts.isStringLiteral(member.name)
        ? member.name.text
        : null;
    if (!name) {
      diagnostics.push(
        issue(sourceFile, member, {
          code: "CCW0202",
          severity: "warning",
          category: "props",
          message: "computed Props fields are omitted from generated controls",
        }),
      );
      continue;
    }
    if (!/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name)) {
      diagnostics.push(
        issue(sourceFile, member, {
          code: "CCW0206",
          severity: "warning",
          category: "props",
          message: `prop ${name} is not a supported runtime identifier and was omitted`,
        }),
      );
      continue;
    }
    const schema = propTypeSchema(member.type);
    if (!schema) {
      diagnostics.push(
        issue(sourceFile, member, {
          code: "CCW0203",
          severity: "warning",
          category: "props",
          message: `unsupported prop type for ${name}; generated controls support string, number, boolean, and string-literal unions`,
        }),
      );
      continue;
    }
    properties[name] = schema;
    if (!member.questionToken) required.push(name);
  }
  const schema = {
    type: "object",
    properties: Object.fromEntries(
      Object.entries(properties).sort(([left], [right]) =>
        left.localeCompare(right),
      ),
    ),
    additionalProperties: false,
  };
  if (required.length) schema.required = required.sort();
  return schema;
}

function resolveDefaultFunction(sourceFile) {
  const declarations = new Map();
  for (const statement of sourceFile.statements) {
    if (
      (ts.isFunctionDeclaration(statement) ||
        ts.isClassDeclaration(statement)) &&
      statement.name
    ) {
      declarations.set(statement.name.text, statement);
    } else if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        if (ts.isIdentifier(declaration.name) && declaration.initializer) {
          declarations.set(declaration.name.text, declaration.initializer);
        }
      }
    }
  }
  for (const statement of sourceFile.statements) {
    if (
      (ts.isFunctionDeclaration(statement) ||
        ts.isClassDeclaration(statement)) &&
      isExported(statement) &&
      isDefaultExport(statement)
    ) {
      return statement;
    }
    if (ts.isExportAssignment(statement) && !statement.isExportEquals) {
      if (ts.isIdentifier(statement.expression)) {
        return declarations.get(statement.expression.text) ?? statement.expression;
      }
      return statement.expression;
    }
    if (
      ts.isExportDeclaration(statement) &&
      statement.exportClause &&
      ts.isNamedExports(statement.exportClause) &&
      statement.exportClause.elements.some(
        (element) => element.name.text === "default",
      )
    ) {
      return statement;
    }
  }
  return null;
}

function extractDefaults(sourceFile, componentNode, propsSchema, diagnostics) {
  const defaults = {};
  if (
    !componentNode ||
    (!ts.isFunctionDeclaration(componentNode) &&
      !ts.isFunctionExpression(componentNode) &&
      !ts.isArrowFunction(componentNode))
  ) {
    return defaults;
  }
  const parameter = componentNode.parameters[0];
  if (!parameter || !ts.isObjectBindingPattern(parameter.name)) return defaults;
  const propsElement = parameter.name.elements.find(
    (element) =>
      (element.propertyName &&
        ts.isIdentifier(element.propertyName) &&
        element.propertyName.text === "props") ||
      (!element.propertyName &&
        ts.isIdentifier(element.name) &&
        element.name.text === "props"),
  );
  if (!propsElement || !ts.isObjectBindingPattern(propsElement.name)) return defaults;
  for (const element of propsElement.name.elements) {
    if (!ts.isIdentifier(element.name) || !element.initializer) continue;
    const name = element.name.text;
    const value = literalValue(element.initializer);
    if (value === undefined || !propsSchema.properties[name]) {
      diagnostics.push(
        issue(sourceFile, element, {
          code: "CCW0204",
          severity: "warning",
          category: "props",
          message: `default for ${name} is not a supported static prop default`,
        }),
      );
      continue;
    }
    const schema = propsSchema.properties[name];
    const validType =
      typeof value === schema.type &&
      (!schema.enum || schema.enum.includes(value));
    if (!validType) {
      diagnostics.push(
        issue(sourceFile, element, {
          code: "CCW0205",
          severity: "warning",
          category: "props",
          message: `default for ${name} does not match its generated prop schema`,
        }),
      );
      continue;
    }
    defaults[name] = value;
    schema.default = value;
  }
  return Object.fromEntries(
    Object.entries(defaults).sort(([left], [right]) => left.localeCompare(right)),
  );
}

function extractMeta(input, sourceFile, diagnostics) {
  const fallback = input.slug
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
  const meta = { name: fallback, description: "" };
  for (const statement of sourceFile.statements) {
    if (!ts.isVariableStatement(statement) || !isExported(statement)) continue;
    const declaration = statement.declarationList.declarations.find(
      (item) => ts.isIdentifier(item.name) && item.name.text === "meta",
    );
    if (!declaration) continue;
    if (!declaration.initializer || !ts.isObjectLiteralExpression(declaration.initializer)) {
      diagnostics.push(
        issue(sourceFile, declaration, {
          code: "CCW0210",
          severity: "warning",
          category: "meta",
          message: "meta must be a static object literal; slug-derived metadata was used",
        }),
      );
      return meta;
    }
    for (const property of declaration.initializer.properties) {
      if (!ts.isPropertyAssignment(property)) continue;
      const key =
        ts.isIdentifier(property.name) || ts.isStringLiteral(property.name)
          ? property.name.text
          : null;
      if (
        (key === "name" || key === "description") &&
        ts.isStringLiteralLike(property.initializer)
      ) {
        meta[key] = property.initializer.text.trim();
      }
    }
    if (!meta.name) meta.name = fallback;
    return meta;
  }
  return meta;
}

function typeScriptDiagnostics(input, sourceFiles) {
  const options = {
    allowJs: true,
    checkJs: true,
    esModuleInterop: true,
    allowSyntheticDefaultImports: true,
    jsx: ts.JsxEmit.React,
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
    noEmit: true,
    skipLibCheck: true,
    strict: true,
    target: ts.ScriptTarget.ES2020,
  };
  const defaultHost = ts.createCompilerHost(options, true);
  const virtualFiles = new Map(
    [...sourceFiles].map(([file, sourceFile]) => [
      path.posix.join(VIRTUAL_ROOT, input.slug, file),
      sourceFile.text,
    ]),
  );
  const ambientPath = path.posix.join(VIRTUAL_ROOT, "__components.d.ts");
  virtualFiles.set(
    ambientPath,
    "declare module 'components/*' { import type { ComponentType } from 'react'; const Component: ComponentType<any>; export default Component; }",
  );
  const host = {
    ...defaultHost,
    fileExists(fileName) {
      return virtualFiles.has(fileName) || defaultHost.fileExists(fileName);
    },
    readFile(fileName) {
      return virtualFiles.get(fileName) ?? defaultHost.readFile(fileName);
    },
    getSourceFile(fileName, languageVersion) {
      const source = virtualFiles.get(fileName);
      if (source !== undefined) {
        return ts.createSourceFile(fileName, source, languageVersion, true);
      }
      return defaultHost.getSourceFile(fileName, languageVersion);
    },
    resolveModuleNames(moduleNames, containingFile) {
      return moduleNames.map((moduleName) => {
        if (moduleName.startsWith(".")) {
          const relativeContaining = path.posix.relative(
            path.posix.join(VIRTUAL_ROOT, input.slug),
            containingFile,
          );
          const resolved = resolveRelativePath(
            relativeContaining,
            moduleName,
            input.files,
          );
          if (resolved.path) {
            const extension = path.posix.extname(resolved.path);
            return {
              resolvedFileName: path.posix.join(
                VIRTUAL_ROOT,
                input.slug,
                resolved.path,
              ),
              extension:
                extension === ".tsx"
                  ? ts.Extension.Tsx
                  : extension === ".ts"
                    ? ts.Extension.Ts
                    : extension === ".jsx"
                      ? ts.Extension.Jsx
                      : ts.Extension.Js,
            };
          }
          return undefined;
        }
        if (moduleName.startsWith("components/")) return undefined;
        return ts.resolveModuleName(
          moduleName,
          path.join(COMPILER_ROOT, "__entry__.tsx"),
          options,
          defaultHost,
        ).resolvedModule;
      });
    },
  };
  const program = ts.createProgram({
    rootNames: [...virtualFiles.keys()],
    options,
    host,
  });
  return ts
    .getPreEmitDiagnostics(program)
    .filter((item) => !item.file || item.file.fileName.startsWith(VIRTUAL_ROOT))
    .map((item) => {
      let file = null;
      let line = null;
      let column = null;
      if (item.file && item.start != null) {
        file = path.posix.relative(
          path.posix.join(VIRTUAL_ROOT, input.slug),
          item.file.fileName,
        );
        const location = item.file.getLineAndCharacterOfPosition(item.start);
        line = location.line + 1;
        column = location.character + 1;
      }
      return diagnostic({
        code: `TS${item.code}`,
        category: "typescript",
        message: ts.flattenDiagnosticMessageText(item.messageText, "\n"),
        file,
        line,
        column,
      });
    });
}

export function analyzeComponent(input) {
  const diagnostics = validateRequest(input);
  if (hasErrors(diagnostics)) {
    return { diagnostics, sourceFiles: new Map() };
  }
  const sourceFiles = new Map();
  for (const [file, source] of Object.entries(input.files).sort(([a], [b]) =>
    a.localeCompare(b),
  )) {
    const scriptKind =
      file.endsWith(".tsx")
        ? ts.ScriptKind.TSX
        : file.endsWith(".ts")
          ? ts.ScriptKind.TS
          : file.endsWith(".jsx")
            ? ts.ScriptKind.JSX
            : ts.ScriptKind.JS;
    const sourceFile = ts.createSourceFile(
      file,
      source,
      ts.ScriptTarget.Latest,
      true,
      scriptKind,
    );
    sourceFiles.set(file, sourceFile);
    for (const parseIssue of sourceFile.parseDiagnostics) {
      const location =
        parseIssue.start == null
          ? { line: null, column: null }
          : (() => {
              const value = sourceFile.getLineAndCharacterOfPosition(parseIssue.start);
              return { line: value.line + 1, column: value.character + 1 };
            })();
      diagnostics.push(
        diagnostic({
          code: `TS${parseIssue.code}`,
          category: "typescript",
          message: ts.flattenDiagnosticMessageText(parseIssue.messageText, "\n"),
          file,
          ...location,
        }),
      );
    }
  }
  const imports = analyzeImportsAndPolicy(input, sourceFiles, diagnostics);
  const entry = sourceFiles.get(input.entry);
  const defaultComponent = entry ? resolveDefaultFunction(entry) : null;
  if (entry && !defaultComponent) {
    diagnostics.push(
      diagnostic({
        code: "CCC0301",
        category: "exports",
        message: "the component entry must have a default export",
        file: input.entry,
      }),
    );
  }
  const propsSchema = entry
    ? extractProps(entry, diagnostics)
    : { type: "object", properties: {}, additionalProperties: false };
  const defaults = entry
    ? extractDefaults(entry, defaultComponent, propsSchema, diagnostics)
    : {};
  const meta = entry
    ? extractMeta(input, entry, diagnostics)
    : { name: input.slug, description: "" };

  if (!hasErrors(diagnostics)) {
    diagnostics.push(...typeScriptDiagnostics(input, sourceFiles));
  }
  return {
    diagnostics,
    sourceFiles,
    relativeImports: imports.relativeImports,
    dependencies: imports.dependencies,
    propsSchema,
    defaults,
    meta,
  };
}

export function resolveComponentRelative(importer, specifier, files) {
  return resolveRelativePath(importer, specifier, files);
}

export function compilerRoot() {
  return COMPILER_ROOT;
}

export function resolvePackage(specifier) {
  return require.resolve(specifier, { paths: [COMPILER_ROOT] });
}
