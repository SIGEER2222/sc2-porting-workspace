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
  const config = await readJson(join(repoRoot, "src", "config", "workspace.json"));
  const localPath = join(repoRoot, "src", "config", "local.sources.json");
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

// DeepCatalogStore 适配器：支持直接从 XML 内容加载
class DeepCatalogStore {
  constructor() {
    this.documents = new Map();
    this.entries = new Map(); // family -> id -> entry
  }

  loadXML(content, uri) {
    this.documents.set(uri, content);
    this._parseCatalog(content, uri);
  }

  _parseCatalog(content, uri) {
    const lines = content.split('\n');
    const reDataElement = /^\s*<C([A-Z][A-Za-z0-9]+)\s([^>]+)\/?>/;
    const reAttrs = /([\w-]+)\s?=\s?"([^"]+)"/g;
    const reSubwordSeparator = /(?=[A-Z])/;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const matchedElement = line.match(reDataElement);
      if (!matchedElement) continue;

      let family = null;
      const kindList = matchedElement[1].split(reSubwordSeparator);
      while (kindList.length > 0) {
        const familyName = kindList.join('');
        if (S2DataCatalogDomain[familyName] !== undefined) {
          family = S2DataCatalogDomain[familyName];
          break;
        }
        kindList.pop();
      }

      if (family === null) continue;

      const entry = {
        family,
        ctype: matchedElement[1],
        id: '',
        parent: null,
        sourceUri: uri,
        attributes: {},
        children: []
      };

      let matchedAttr;
      while ((matchedAttr = reAttrs.exec(matchedElement[2])) !== null) {
        entry.attributes[matchedAttr[1]] = matchedAttr[2];
        if (matchedAttr[1] === 'id') {
          entry.id = matchedAttr[2];
        } else if (matchedAttr[1] === 'parent') {
          entry.parent = matchedAttr[2];
        }
      }
      reAttrs.lastIndex = 0;

      if (!entry.id) continue;

      if (!this.entries.has(family)) {
        this.entries.set(family, new Map());
      }
      this.entries.get(family).set(entry.id, entry);
    }
  }

  getLoadedFamilies() {
    return [...this.entries.keys()];
  }

  *findEntry(family) {
    const familyEntries = this.entries.get(family);
    if (!familyEntries) return;
    yield* familyEntries.values();
  }

  get docCount() {
    return this.documents.size;
  }
}

// S2DataCatalogDomain 枚举（与 toolkit 保持一致）
const S2DataCatalogDomain = {
  Abil: 0,
  Actor: 1,
  Behavior: 2,
  Button: 3,
  Effect: 4,
  Model: 5,
  Mover: 6,
  Race: 7,
  Requirement: 8,
  TargetFind: 9,
  TargetPlan: 10,
  Tech: 11,
  Tower: 12,
  Unit: 13,
  Upgrade: 14,
  Weapon: 15,
  Validator: 16,
  ScoreSum: 17,
  ScoreV: 18,
  Tile: 19,
  Texture: 20,
  Turret: 21,
  Volume: 23,
};

// 反向映射：数字 -> 字符串
const S2DataCatalogDomainReverse = {};
for (const [key, value] of Object.entries(S2DataCatalogDomain)) {
  S2DataCatalogDomainReverse[value] = key;
}

async function analyze(sourceId, relativeRoot, patternText, outputPath) {
  const sourceRoot = await resolveRegistered(sourceId);
  const analysisRoot = resolve(sourceRoot, relativeRoot);
  if (!analysisRoot.startsWith(sourceRoot + sep) && analysisRoot !== sourceRoot) {
    throw new Error("Analysis root escapes the registered source");
  }
  if (!existsSync(analysisRoot)) throw new Error("Analysis root is missing: " + relativeRoot);

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
      const familyName = S2DataCatalogDomainReverse[family] ?? String(family);
      entries.push({ entry, family: familyName });
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

  // ===== 构建 nodes（符合 dependency-graph.schema.json）=====
  const nodes = entries.map(({ entry, family }) => ({
    id: family + ":" + entry.id,
    kind: "catalog-entry",
    path: entry.sourceUri,
    metadata: {
      family,
      ctype: entry.ctype,
      parent: entry.parent ?? null
    }
  }));

  // ===== 构建 edges（符合 dependency-graph.schema.json）=====
  const edges = [];

  // parent 继承边
  for (const { entry, family } of entries) {
    if (entry.parent) {
      edges.push({
        from: family + ":" + entry.id,
        to: family + ":" + entry.parent,
        relation: "depends-on",
        evidence: [`parent:${entry.parent}`]
      });
    }
  }

  // reverseReferences 边
  for (const ref of reverseReferences) {
    for (const r of ref.references) {
      for (const target of r.targets) {
        edges.push({
          from: ref.family + ":" + ref.id,
          to: ref.family + ":" + target,
          relation: "depends-on",
          evidence: [`${r.path}@${ref.source}`]
        });
      }
    }
  }

  // ===== 构建 unresolved（catalog 分析通常无 unresolved）=====
  const unresolved = [];

  const result = {
    schemaVersion: 1,
    composition: sourceId,
    nodes,
    edges,
    unresolved,

    // 保留向后兼容字段
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
  throw new Error("Usage: node tools/analysis/analyze-catalog.mjs <source-id> <relative-root> <pattern> <output-path>");
}
await analyze(sourceId, relativeRoot, patternText, outputPath);
