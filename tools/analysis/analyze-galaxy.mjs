import { mkdir, opendir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, extname, join, relative, resolve, sep } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "..", "..");

// SC2 built-in trigger libraries. Calls into these are never flagged as
// unresolved because they are provided by the engine regardless of which
// mods are mounted.
const OFFICIAL_LIB_PREFIX = /^(libNtve|libLbty|libHots|libVoi)/;

async function readJson(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

async function resolveRegistered(id) {
  const config = await readJson(join(repoRoot, "config", "workspace.json"));
  const localPath = join(repoRoot, "config", "local.sources.json");
  const local = existsSync(localPath) ? await readJson(localPath) : { bindings: {} };
  const entry = [...(config.tools ?? []), ...(config.sources ?? [])].find((item) => item.id === id);
  if (!entry) throw new Error("Unknown registered id: " + id);
  const path = entry.path ? resolve(repoRoot, entry.path) : local.bindings?.[id];
  if (!path || !existsSync(path)) throw new Error("Registered path is unavailable: " + id);
  return resolve(path);
}

async function listGalaxyFiles(root) {
  const files = [];
  async function walk(path) {
    const directory = await opendir(path);
    for await (const entry of directory) {
      const child = join(path, entry.name);
      if (entry.isDirectory()) await walk(child);
      else if (entry.isFile() && extname(entry.name).toLowerCase() === ".galaxy") files.push(child);
    }
  }
  await walk(root);
  return files.sort((left, right) => left.localeCompare(right));
}

function normalizedPath(root, path) {
  return relative(root, path).split(sep).join("/");
}

function expressionName(node, SyntaxKind) {
  if (!node) return null;
  if (node.kind === SyntaxKind.Identifier) return node.name;
  if (node.kind === SyntaxKind.PropertyAccessExpression) {
    const left = expressionName(node.expression, SyntaxKind);
    const right = node.name?.name;
    return left && right ? left + "." + right : right ?? left;
  }
  return null;
}

function location(file, node) {
  return { file, line: (node.line ?? 0) + 1 };
}

function classifyCall(name) {
  if (name === "TriggerCreate" || name.startsWith("TriggerAddEvent") || name === "TriggerExecute") return "trigger";
  if (name.startsWith("Bank")) return "bank";
  if (/Objective/i.test(name)) return "objective";
  if (/Reward/i.test(name)) return "reward";
  if (/Init(Lib|Map)/.test(name) || /_Init$/.test(name)) return "initializer";
  return null;
}

function resolveInclude(fromFile, includePath, fileIndex, suffixIndex) {
  const fromDir = dirname(fromFile).split(sep).join("/");
  const candidates = [
    includePath,
    includePath + ".galaxy",
    join(fromDir, includePath).split(sep).join("/"),
    join(fromDir, includePath + ".galaxy").split(sep).join("/")
  ];
  for (const candidate of candidates) {
    const key = candidate.replace(/^\.\//, "").toLowerCase();
    if (fileIndex.has(key)) return fileIndex.get(key);
    const suffixMatches = suffixIndex.get(key) ?? [];
    if (suffixMatches.length === 1) return suffixMatches[0];
  }
  return null;
}

async function loadToolkit() {
  const toolkitRoot = await resolveRegistered("galaxy-toolkit");
  const galaxyModule = join(toolkitRoot, "packages", "sc2-galaxy-lang", "lib", "src", "index.js");
  return await import(pathToFileURL(galaxyModule));
}

function resolvePackageRoot(pkg) {
  return (async () => {
    const sourceRoot = await resolveRegistered(pkg.sourceId);
    const pkgRoot = resolve(sourceRoot, pkg.path ?? ".");
    if (!pkgRoot.startsWith(sourceRoot + sep) && pkgRoot !== sourceRoot) {
      throw new Error("Package path escapes its source: " + (pkg.packageId ?? pkg.sourceId));
    }
    if (!existsSync(pkgRoot)) {
      throw new Error("Package root is missing: " + (pkg.packageId ?? pkg.sourceId) + " -> " + pkg.path);
    }
    return { packageId: pkg.packageId ?? pkg.sourceId, sourceId: pkg.sourceId, root: pkgRoot, sourceRoot };
  })();
}

async function runAnalysis(packages, outputPath, meta) {
  const { Parser, SyntaxKind, forEachChild } = await loadToolkit();
  const records = [];
  const definitions = new Map();
  const calls = [];

  for (const pkg of packages) {
    const absoluteFiles = await listGalaxyFiles(pkg.root);
    for (const absoluteFile of absoluteFiles) {
      const file = normalizedPath(pkg.sourceRoot, absoluteFile);
      const text = await readFile(absoluteFile, "utf8");
      const ast = new Parser().parseFile(file, text);
      const record = {
        path: file,
        packageId: pkg.packageId,
        bytes: Buffer.byteLength(text),
        parseErrors: [...(ast.parseDiagnostics ?? []), ...(ast.additionalSyntacticDiagnostics ?? [])].length,
        parseDiagnostics: [...(ast.parseDiagnostics ?? []), ...(ast.additionalSyntacticDiagnostics ?? [])].map((d) => ({
          message: d.messageText ?? String(d.message ?? ""),
          line: (d.line ?? 0) + 1
        })),
        includes: [],
        functions: 0,
        calls: 0,
        apiCalls: { trigger: [], bank: [], objective: [], reward: [], initializer: [] }
      };

      function visit(node, caller = null) {
        let activeCaller = caller;
        if (node.kind === SyntaxKind.IncludeStatement) {
          record.includes.push({ target: node.path?.value ?? "", ...location(file, node) });
        } else if (node.kind === SyntaxKind.FunctionDeclaration) {
          activeCaller = node.name?.name ?? null;
          record.functions += 1;
          if (activeCaller && node.body) {
            const entries = definitions.get(activeCaller) ?? [];
            entries.push({ ...location(file, node), packageId: pkg.packageId });
            definitions.set(activeCaller, entries);
          }
        } else if (node.kind === SyntaxKind.CallExpression) {
          const callee = expressionName(node.expression, SyntaxKind);
          if (callee) {
            record.calls += 1;
            calls.push({ caller: activeCaller, callee, ...location(file, node), packageId: pkg.packageId });
            const category = classifyCall(callee);
            if (category) record.apiCalls[category].push({ name: callee, ...location(file, node) });
          }
        }
        forEachChild(node, (child) => {
          visit(child, activeCaller);
          return undefined;
        });
      }

      visit(ast);
      records.push(record);
    }
  }

  const fileIndex = new Map();
  const suffixIndex = new Map();
  for (const record of records) {
    fileIndex.set(record.path.toLowerCase(), record.path);
    fileIndex.set(record.path.replace(/\.galaxy$/i, "").toLowerCase(), record.path);
    const normalized = record.path.toLowerCase();
    const candidates = [
      normalized,
      normalized.replace(/\.galaxy$/i, ""),
      normalized.split("/base.sc2data/").at(-1),
      normalized.split("/base.sc2data/").at(-1).replace(/\.galaxy$/i, "")
    ];
    for (const candidate of new Set(candidates)) {
      const entries = suffixIndex.get(candidate) ?? [];
      entries.push(record.path);
      suffixIndex.set(candidate, entries);
    }
  }

  const includeEdges = [];
  const unresolvedIncludes = [];
  const includeByPackage = new Map();
  for (const record of records) {
    for (const include of record.includes) {
      const target = resolveInclude(record.path, include.target, fileIndex, suffixIndex);
      const edge = {
        from: record.path,
        fromPackageId: record.packageId,
        include: include.target,
        line: include.line
      };
      if (target) {
        const targetRecord = records.find((r) => r.path === target);
        includeEdges.push({ ...edge, to: target, toPackageId: targetRecord?.packageId ?? null });
      } else {
        unresolvedIncludes.push(edge);
        const key = record.packageId + "\0" + include.target;
        includeByPackage.set(key, (includeByPackage.get(key) ?? 0) + 1);
      }
    }
  }

  const crossFile = new Map();
  const unresolvedProjectCalls = new Map();
  for (const call of calls) {
    const targets = definitions.get(call.callee) ?? [];
    const otherFiles = [...new Set(targets.map((target) => target.file).filter((file) => file !== call.file))];
    for (const target of otherFiles) {
      const key = call.file + "\0" + target;
      const edge = crossFile.get(key) ?? { from: call.file, to: target, callCount: 0, symbols: new Set() };
      edge.callCount += 1;
      edge.symbols.add(call.callee);
      crossFile.set(key, edge);
    }
    // Flag any call into a custom lib (not official) that has no definition in
    // the analyzed composition. Hashed lib names (e.g. libDF8E6945_*) are
    // included so missing-include downstream errors are surfaced statically.
    if (targets.length === 0 && /^lib/i.test(call.callee) && !OFFICIAL_LIB_PREFIX.test(call.callee)) {
      const key = call.file + "\0" + call.callee;
      const item = unresolvedProjectCalls.get(key) ?? {
        file: call.file,
        packageId: call.packageId,
        symbol: call.callee,
        count: 0
      };
      item.count += 1;
      unresolvedProjectCalls.set(key, item);
    }
  }

  const unresolvedByPackage = new Map();
  for (const item of unresolvedProjectCalls.values()) {
    const entries = unresolvedByPackage.get(item.packageId) ?? [];
    entries.push(item);
    unresolvedByPackage.set(item.packageId, entries);
  }

  const result = {
    schemaVersion: 1,
    analyzer: "sc2-galaxy-lang.Parser",
    compositionId: meta.compositionId,
    sourceId: meta.sourceId ?? null,
    root: meta.root || ".",
    packages: packages.map((p) => ({ packageId: p.packageId, sourceId: p.sourceId })),
    summary: {
      packages: packages.length,
      files: records.length,
      bytes: records.reduce((sum, record) => sum + record.bytes, 0),
      parseErrors: records.reduce((sum, record) => sum + record.parseErrors, 0),
      functions: records.reduce((sum, record) => sum + record.functions, 0),
      calls: records.reduce((sum, record) => sum + record.calls, 0),
      includeEdges: includeEdges.length,
      unresolvedIncludes: unresolvedIncludes.length,
      crossFileCallEdges: crossFile.size,
      unresolvedProjectCalls: unresolvedProjectCalls.size
    },
    files: records,
    includeEdges,
    unresolvedIncludes,
    crossFileCalls: [...crossFile.values()].map((edge) => ({ ...edge, symbols: [...edge.symbols].sort() })),
    unresolvedProjectCalls: [...unresolvedProjectCalls.values()].sort((left, right) => right.count - left.count),
    unresolvedProjectCallsByPackage: [...unresolvedByPackage.entries()]
      .map(([packageId, items]) => ({
        packageId,
        unresolvedCount: items.length,
        callSiteCount: items.reduce((sum, i) => sum + i.count, 0),
        symbols: items.map((i) => ({ symbol: i.symbol, count: i.count })).sort((a, b) => b.count - a.count)
      }))
      .sort((a, b) => b.unresolvedCount - a.unresolvedCount)
  };

  const absoluteOutput = resolve(repoRoot, outputPath);
  if (!absoluteOutput.startsWith(repoRoot + sep)) throw new Error("Output path escapes the repository");
  await mkdir(dirname(absoluteOutput), { recursive: true });
  await writeFile(absoluteOutput, JSON.stringify(result, null, 2) + "\n", "utf8");
  console.log(JSON.stringify(result.summary, null, 2));
}

async function analyzeSingle(sourceId, relativeRoot, outputPath) {
  const sourceRoot = await resolveRegistered(sourceId);
  const analysisRoot = resolve(sourceRoot, relativeRoot || ".");
  if (!analysisRoot.startsWith(sourceRoot + sep) && analysisRoot !== sourceRoot) {
    throw new Error("Analysis root escapes the registered source");
  }
  if (!existsSync(analysisRoot)) throw new Error("Analysis root is missing: " + relativeRoot);
  const packages = [{ packageId: sourceId, sourceId, root: analysisRoot, sourceRoot }];
  await runAnalysis(packages, outputPath, { compositionId: sourceId, sourceId, root: relativeRoot || "." });
}

async function analyzeComposition(manifestPath, outputPath) {
  const manifest = await readJson(manifestPath);
  if (!Array.isArray(manifest.packages) || manifest.packages.length === 0) {
    throw new Error("Composition manifest must define a non-empty packages array");
  }
  const packages = [];
  for (const pkg of manifest.packages) {
    if (!pkg.sourceId || !pkg.path) {
      throw new Error("Each composition package needs sourceId and path; got: " + JSON.stringify(pkg));
    }
    packages.push(await resolvePackageRoot(pkg));
  }
  await runAnalysis(packages, outputPath, {
    compositionId: manifest.compositionId ?? "unnamed-composition",
    root: "."
  });
}

const args = process.argv.slice(2);
if (args[0] === "--composition") {
  const manifestPath = args[1];
  const outputPath = args[2];
  if (!manifestPath || !outputPath) {
    throw new Error("Usage: node scripts/analyze-galaxy.mjs --composition <manifest.json> <output-path>");
  }
  await analyzeComposition(manifestPath, outputPath);
} else {
  const [sourceId, relativeRoot = ".", outputPath] = args;
  if (!sourceId || !outputPath) {
    throw new Error("Usage: node scripts/analyze-galaxy.mjs <source-id> <relative-root> <output-path>");
  }
  await analyzeSingle(sourceId, relativeRoot, outputPath);
}
