#!/usr/bin/env node

import { existsSync } from "node:fs";
import { mkdir, opendir, readFile, writeFile } from "node:fs/promises";
import { dirname, extname, relative, resolve, sep } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "../../../../../");
const toolkitEntry = resolve(
  repoRoot,
  "reference/sc2-galaxy-toolkit/packages/sc2-galaxy-lang/lib/src/index.js",
);

function fail(message) {
  throw new Error(message);
}

function argumentValue(args, name) {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : null;
}

function sourceArguments(args) {
  const sources = [];
  for (let i = 0; i < args.length; i += 1) {
    if (args[i] !== "--source") continue;
    const value = args[i + 1] ?? "";
    const separator = value.indexOf("=");
    if (separator <= 0) fail(`Invalid --source value: ${value}`);
    sources.push({
      id: value.slice(0, separator),
      root: resolve(value.slice(separator + 1)),
    });
    i += 1;
  }
  return sources;
}

async function listGalaxyFiles(root) {
  const files = [];
  async function walk(directory) {
    const handle = await opendir(directory);
    for await (const entry of handle) {
      const child = resolve(directory, entry.name);
      if (entry.isDirectory()) await walk(child);
      else if (entry.isFile() && extname(entry.name).toLowerCase() === ".galaxy") {
        files.push(child);
      }
    }
  }
  await walk(root);
  return files.sort((a, b) => a.localeCompare(b));
}

function relativePath(root, path) {
  return relative(root, path).split(sep).join("/");
}

function nodeText(printer, node) {
  if (!node) return "";
  try {
    return printer.printNode(node).replace(/\s+/g, " ").trim();
  } catch {
    return "";
  }
}

function expressionName(node, SyntaxKind) {
  if (!node) return "";
  if (node.kind === SyntaxKind.Identifier) return node.name ?? "";
  if (node.kind === SyntaxKind.PropertyAccessExpression) {
    const left = expressionName(node.expression, SyntaxKind);
    const right = node.name?.name ?? "";
    return left && right ? `${left}.${right}` : left || right;
  }
  return "";
}

function hasStaticModifier(node, SyntaxKind) {
  return Boolean(node.modifiers?.some((modifier) => modifier.kind === SyntaxKind.StaticKeyword));
}

function classifyFunction(name, returnType, parameters) {
  if ((name.includes("_gt_") || name.startsWith("gt_")) &&
      returnType === "bool" && parameters.length === 2 &&
      parameters.every((parameter) => parameter.type === "bool")) {
    return "trigger-handler";
  }
  if (name.endsWith("_Init") || name.endsWith("InitLib") || name === "InitMap") {
    return "initializer";
  }
  if (/^lib[0-9A-Fa-f]+_gf_/.test(name)) return "library-function";
  if (/^gf_/.test(name)) return "map-function";
  return "helper";
}

function effectForCall(name) {
  const effects = [
    [/(^|\.)Wait$|Wait$|TriggerExecute|TriggerCreate|TriggerAddEvent/, "trigger"],
    [/^Bank|Bank/, "bank"],
    [/Catalog/, "catalog"],
    [/Dialog|Frame|UI/, "ui"],
    [/Unit(Create|Kill|Issue|Group)|PlayerSet|Order/, "game-state"],
    [/DataTable/, "data-table"],
    [/Objective|GameOver|Victory|Defeat/, "mission"],
  ];
  return effects.filter(([pattern]) => pattern.test(name)).map(([, effect]) => effect);
}

async function loadRegistryHandlers() {
  const path = resolve(repoRoot, "tools/galaxy-vibe/kernel/function-registry.json");
  if (!existsSync(path)) return new Set();
  const data = JSON.parse(await readFile(path, "utf8"));
  return new Set(Object.values(data.functions ?? {}).map((entry) => entry.handler).filter(Boolean));
}

async function main() {
  const args = process.argv.slice(2);
  const outputArgument = argumentValue(args, "--out");
  const sources = sourceArguments(args);
  if (!outputArgument || sources.length === 0) {
    fail("Usage: discover_function_catalog.mjs --out <repo-relative-path> --source <id>=<path> [...]");
  }
  const outputPath = resolve(repoRoot, outputArgument);
  if (!outputPath.startsWith(`${repoRoot}${sep}`)) fail("--out must stay inside the repository");
  for (const source of sources) {
    if (!existsSync(source.root)) fail(`Source root is missing: ${source.root}`);
  }

  const { Parser, Printer, SyntaxKind, forEachChild } = await import(pathToFileURL(toolkitEntry));
  const printer = new Printer();
  const registeredHandlers = await loadRegistryHandlers();
  const functions = [];
  const summaries = [];

  for (const source of sources) {
    const files = await listGalaxyFiles(source.root);
    let parseErrors = 0;
    for (const absoluteFile of files) {
      const sourceText = await readFile(absoluteFile, "utf8");
      const ast = new Parser().parseFile(relativePath(source.root, absoluteFile), sourceText);
      const diagnostics = [
        ...(ast.parseDiagnostics ?? []),
        ...(ast.additionalSyntacticDiagnostics ?? []),
      ];
      parseErrors += diagnostics.length;
      const filePath = relativePath(source.root, absoluteFile);

      function visit(node) {
        if (node.kind === SyntaxKind.FunctionDeclaration && node.name?.name) {
          const name = node.name.name;
          const returnType = node.type ? nodeText(printer, node.type) : "void";
          const parameters = [...(node.parameters ?? [])].map((parameter) => ({
            name: parameter.name?.name ?? "",
            type: nodeText(printer, parameter.type),
          }));
          const calls = new Set();
          forEachChild(node.body, (child) => {
            function collect(inner) {
              if (inner.kind === SyntaxKind.CallExpression) {
                const callee = expressionName(inner.expression, SyntaxKind);
                if (callee) calls.add(callee);
              }
              forEachChild(inner, collect);
            }
            collect(child);
          });
          const effects = new Set();
          for (const call of calls) for (const effect of effectForCall(call)) effects.add(effect);
          const registered = registeredHandlers.has(name);
          functions.push({
            id: `${source.id}:${filePath}:${(node.line ?? 0) + 1}:${name}`,
            source_id: source.id,
            path: filePath,
            line: (node.line ?? 0) + 1,
            name,
            kind: classifyFunction(name, returnType, parameters),
            return_type: returnType,
            parameters,
            has_body: Boolean(node.body),
            static: hasStaticModifier(node, SyntaxKind),
            effects: [...effects].sort(),
            registered_handler: registered,
            disposition: registered ? "callable-adapter" : "inventory-only",
          });
        }
        forEachChild(node, visit);
      }
      visit(ast);
    }
    summaries.push({
      source_id: source.id,
      root: source.root.startsWith(repoRoot) ? relativePath(repoRoot, source.root) : null,
      files: files.length,
      parse_errors: parseErrors,
      functions: functions.filter((entry) => entry.source_id === source.id).length,
    });
  }

  const byKind = {};
  const byDisposition = {};
  const byEffect = {};
  for (const entry of functions) {
    byKind[entry.kind] = (byKind[entry.kind] ?? 0) + 1;
    byDisposition[entry.disposition] = (byDisposition[entry.disposition] ?? 0) + 1;
    for (const effect of entry.effects) byEffect[effect] = (byEffect[effect] ?? 0) + 1;
  }

  const result = {
    schemaVersion: 1,
    catalog: "cmre-galaxy-function-catalog",
    generated_by: "stage25-ai-ally-capability-completion/discover_function_catalog.mjs",
    policy: {
      callable_functions_require_explicit_registry_adapters: true,
      inventory_only_functions_are_not_runtime_callable: true,
      arbitrary_reflection: false,
    },
    sources: summaries,
    summary: {
      functions: functions.length,
      by_kind: byKind,
      by_disposition: byDisposition,
      functions_with_effects: functions.filter((entry) => entry.effects.length > 0).length,
      by_effect: byEffect,
    },
    functions,
  };
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  console.log(JSON.stringify({ ...result.summary, output: relativePath(repoRoot, outputPath) }, null, 2));
}

await main();
