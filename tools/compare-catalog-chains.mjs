import { mkdir, opendir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, extname, join, relative, resolve, sep } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "..");

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

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]));
}

function comparable(entry) {
  return stable({
    ctype: entry.ctype,
    id: entry.id,
    parent: entry.parent ?? null,
    attributes: entry.attributes,
    children: entry.children
  });
}

async function loadChain(root, modPaths, DeepCatalogStore, S2DataCatalogDomain) {
  const store = new DeepCatalogStore();
  for (const modPath of modPaths) {
    const gameData = resolve(root, modPath, "Base.SC2Data", "GameData");
    for (const file of await listXmlFiles(gameData)) {
      const uri = relative(root, file).split(sep).join("/");
      store.loadXML(await readFile(file, "utf8"), uri);
    }
  }
  const entries = new Map();
  for (const family of store.getLoadedFamilies()) {
    const familyName = S2DataCatalogDomain[family];
    for (const entry of store.findEntry(family)) entries.set(familyName + ":" + entry.id, comparable(entry));
  }
  return entries;
}

async function run(recipePath, generatedSourceId, outputPath) {
  const recipe = await readJson(resolve(repoRoot, recipePath));
  const sourceRoot = await resolveRegistered(recipe.source.sourceId);
  const generatedRoot = await resolveRegistered(generatedSourceId);
  const toolkitRoot = await resolveRegistered("galaxy-toolkit");
  const dataModule = join(toolkitRoot, "packages", "sc2-data", "lib", "src", "index.js");
  const { DeepCatalogStore, S2DataCatalogDomain } = await import(pathToFileURL(dataModule));
  const chain = [recipe.source.baseMod, recipe.source.targetMod];
  const left = await loadChain(sourceRoot, chain, DeepCatalogStore, S2DataCatalogDomain);
  const right = await loadChain(generatedRoot, chain, DeepCatalogStore, S2DataCatalogDomain);
  const keys = [...new Set([...left.keys(), ...right.keys()])].sort();
  const missingLeft = [];
  const missingRight = [];
  const changed = [];

  for (const key of keys) {
    if (!left.has(key)) missingLeft.push(key);
    else if (!right.has(key)) missingRight.push(key);
    else if (JSON.stringify(left.get(key)) !== JSON.stringify(right.get(key))) changed.push(key);
  }

  const result = {
    schemaVersion: 1,
    recipeId: recipe.id,
    left: { sourceId: recipe.source.sourceId, entries: left.size },
    right: { sourceId: generatedSourceId, entries: right.size },
    equivalent: missingLeft.length === 0 && missingRight.length === 0 && changed.length === 0,
    summary: { missingLeft: missingLeft.length, missingRight: missingRight.length, changed: changed.length },
    missingLeft,
    missingRight,
    changed
  };
  const absoluteOutput = resolve(repoRoot, outputPath);
  if (!absoluteOutput.startsWith(repoRoot + sep)) throw new Error("Output path escapes the repository");
  await mkdir(dirname(absoluteOutput), { recursive: true });
  await writeFile(absoluteOutput, JSON.stringify(result, null, 2) + "\n", "utf8");
  console.log(JSON.stringify({ equivalent: result.equivalent, entries: left.size, ...result.summary }, null, 2));
  if (!result.equivalent) process.exitCode = 1;
}

const [recipePath, generatedSourceId, outputPath] = process.argv.slice(2);
if (!recipePath || !generatedSourceId || !outputPath) {
  throw new Error("Usage: node scripts/compare-catalog-chains.mjs <recipe-path> <generated-source-id> <output-path>");
}
await run(recipePath, generatedSourceId, outputPath);
