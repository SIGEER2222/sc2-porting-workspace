import { mkdir, opendir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, extname, join, relative, resolve, sep } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "..", "..");

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

async function listXmlFiles(root) {
  const files = [];
  async function walk(path) {
    const directory = await opendir(path);
    for await (const entry of directory) {
      const child = join(path, entry.name);
      if (entry.isDirectory()) await walk(child);
      else if (entry.isFile() && extname(entry.name).toLowerCase() === ".xml") files.push(child);
    }
  }
  await walk(root);
  return files.sort((left, right) => left.localeCompare(right));
}

function normalizedPath(root, path) {
  return relative(root, path).split(sep).join("/");
}

function collectReferences(element, targetIds, path, references) {
  for (const [attribute, value] of Object.entries(element.attributes ?? {})) {
    const tokens = String(value).match(/[A-Za-z_][A-Za-z0-9_]*/g) ?? [];
    const matches = [...new Set(tokens.filter((token) => targetIds.has(token)))];
    if (matches.length > 0) references.push({ path, attribute, targets: matches });
  }
  for (let index = 0; index < (element.children ?? []).length; index += 1) {
    const child = element.children[index];
    collectReferences(child, targetIds, path + "/" + child.tag + "[" + index + "]", references);
  }
}

async function analyze(sourceId, relativeRoot, patternText, outputPath) {
  const sourceRoot = await resolveRegistered(sourceId);
  const analysisRoot = resolve(sourceRoot, relativeRoot);
  if (!analysisRoot.startsWith(sourceRoot + sep) && analysisRoot !== sourceRoot) {
    throw new Error("Analysis root escapes the registered source");
  }
  if (!existsSync(analysisRoot)) throw new Error("Analysis root is missing: " + relativeRoot);

  const toolkitRoot = await resolveRegistered("galaxy-toolkit");
  const dataModule = join(toolkitRoot, "packages", "sc2-data", "lib", "src", "index.js");
  const { DeepCatalogStore, S2DataCatalogDomain } = await import(pathToFileURL(dataModule));
  const files = await listXmlFiles(analysisRoot);
  const store = new DeepCatalogStore();
  const parseErrors = [];

  for (const absoluteFile of files) {
    const file = normalizedPath(sourceRoot, absoluteFile);
    try {
      store.loadXML(await readFile(absoluteFile, "utf8"), file);
    } catch (error) {
      parseErrors.push({ file, message: error.message });
    }
  }

  const entries = [];
  for (const family of store.getLoadedFamilies()) {
    for (const entry of store.findEntry(family)) {
      entries.push({ entry, family: S2DataCatalogDomain[family] });
    }
  }
  const pattern = new RegExp(patternText, "i");
  const selectedEntries = entries.filter(({ entry }) => pattern.test(entry.id) || pattern.test(entry.parent ?? ""));
  const selectedKeys = new Set(selectedEntries.map(({ family, entry }) => family + "\0" + entry.id));
  const targetIds = new Set(selectedEntries.map(({ entry }) => entry.id));
  const reverseReferences = [];

  for (const { entry, family } of entries) {
    if (selectedKeys.has(family + "\0" + entry.id)) continue;
    const references = [];
    collectReferences(entry, targetIds, entry.ctype, references);
    const parentTargets = entry.parent && targetIds.has(entry.parent) ? [entry.parent] : [];
    if (parentTargets.length > 0) references.unshift({ path: entry.ctype, attribute: "parent", targets: parentTargets });
    if (references.length > 0) {
      reverseReferences.push({ family, id: entry.id, source: entry.sourceUri, references });
    }
  }

  const caseGroups = new Map();
  for (const { entry, family } of entries) {
    const key = family + "\0" + entry.id.toLowerCase();
    const values = caseGroups.get(key) ?? new Set();
    values.add(entry.id);
    caseGroups.set(key, values);
  }

  const result = {
    schemaVersion: 1,
    analyzer: "sc2-data.DeepCatalogStore",
    sourceId,
    root: relativeRoot,
    selector: { field: ["id", "parent"], pattern: patternText, flags: "i" },
    summary: {
      xmlFiles: files.length,
      parsedDocuments: store.docCount,
      parseErrors: parseErrors.length,
      totalEntries: entries.length,
      selectedEntries: selectedEntries.length,
      reverseReferenceEntries: reverseReferences.length
    },
    selectedEntries: selectedEntries
      .map(({ entry, family }) => ({ family, ctype: entry.ctype, id: entry.id, parent: entry.parent ?? null, source: entry.sourceUri }))
      .sort((left, right) => left.family.localeCompare(right.family) || left.id.localeCompare(right.id)),
    reverseReferences,
    caseCollisionRisks: [...caseGroups.entries()]
      .filter(([, values]) => values.size > 1)
      .map(([key, values]) => ({ family: key.split("\0")[0], ids: [...values].sort() })),
    parseErrors
  };

  const absoluteOutput = resolve(repoRoot, outputPath);
  if (!absoluteOutput.startsWith(repoRoot + sep)) throw new Error("Output path escapes the repository");
  await mkdir(dirname(absoluteOutput), { recursive: true });
  await writeFile(absoluteOutput, JSON.stringify(result, null, 2) + "\n", "utf8");
  console.log(JSON.stringify(result.summary, null, 2));
}

const [sourceId, relativeRoot, patternText, outputPath] = process.argv.slice(2);
if (!sourceId || !relativeRoot || !patternText || !outputPath) {
  throw new Error("Usage: node scripts/analyze-catalog.mjs <source-id> <relative-root> <pattern> <output-path>");
}
await analyze(sourceId, relativeRoot, patternText, outputPath);
