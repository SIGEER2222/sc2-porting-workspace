import { cp, mkdir, opendir, readFile, rm, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
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

function applyRemovals(text, spans) {
  return [...spans]
    .sort((left, right) => right.start - left.start)
    .reduce((current, span) => current.slice(0, span.start) + (span.text ?? "") + current.slice(span.end), text);
}

function hashText(text) {
  return createHash("sha256").update(text).digest("hex");
}

function normalizedPath(root, path) {
  return relative(root, path).split(sep).join("/");
}

function getAttributeValue(element, name) {
  const attribute = element.attributes?.[name] ?? element.attributes?.[name.toLowerCase()];
  return attribute?.value ?? "";
}

function escapeXml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function serializeElement(element, indent) {
  const attributes = Object.entries(element.attributes ?? {})
    .map(([name, value]) => " " + name + '=\"' + escapeXml(value) + '\"')
    .join("");
  if ((element.children ?? []).length === 0) return indent + "<" + element.tag + attributes + "/>";
  const children = element.children.map((child) => serializeElement(child, indent + "    ")).join("\n");
  return indent + "<" + element.tag + attributes + ">\n" + children + "\n" + indent + "</" + element.tag + ">";
}

function serializeEntry(entry) {
  const attributes = { ...entry.attributes, id: entry.id };
  if (entry.parent) attributes.parent = entry.parent;
  const opening = "<" + entry.ctype + Object.entries(attributes)
    .map(([name, value]) => " " + name + '=\"' + escapeXml(value) + '\"')
    .join("");
  if (entry.children.length === 0) return opening + "/>";
  const children = entry.children.map((child) => serializeElement(child, "    ")).join("\n");
  return opening + ">\n" + children + "\n</" + entry.ctype + ">";
}

function mergeEntryXml(snippets, targetRaw, DeepCatalogStore) {
  const store = new DeepCatalogStore();
  store.loadXML("<Catalog>\n" + snippets.join("\n") + "\n" + targetRaw + "\n</Catalog>", "generated-merge.xml");
  const entries = [];
  for (const family of store.getLoadedFamilies()) entries.push(...store.findEntry(family));
  if (entries.length !== 1) throw new Error("Expected one merged Catalog entry, got " + entries.length);
  return serializeEntry(entries[0]);
}

async function run(recipePath) {
  const absoluteRecipe = resolve(repoRoot, recipePath);
  const recipe = await readJson(absoluteRecipe);
  const sourceRoot = await resolveRegistered(recipe.source.sourceId);
  const toolkitRoot = await resolveRegistered("galaxy-toolkit");
  const xmlModule = join(toolkitRoot, "packages", "sc2-xml", "lib", "src", "index.js");
  const { parse } = await import(pathToFileURL(xmlModule));
  const dataModule = join(toolkitRoot, "packages", "sc2-data", "lib", "src", "index.js");
  const { DeepCatalogStore } = await import(pathToFileURL(dataModule));
  const artifactRoot = resolve(repoRoot, recipe.output.artifactRoot);
  if (!artifactRoot.startsWith(resolve(repoRoot, "artifacts") + sep)) {
    throw new Error("Generated composition must stay under artifacts/");
  }

  await rm(artifactRoot, { recursive: true, force: true });
  await mkdir(artifactRoot, { recursive: true });
  for (const relativePath of recipe.copyPaths) {
    const source = resolve(sourceRoot, relativePath);
    const target = resolve(artifactRoot, relativePath);
    if (!source.startsWith(sourceRoot + sep) || !existsSync(source)) throw new Error("Copy input is unavailable: " + relativePath);
    await mkdir(dirname(target), { recursive: true });
    await cp(source, target, { recursive: true, force: true });
  }

  const sourceBaseGameData = resolve(sourceRoot, recipe.source.baseMod, recipe.source.gameDataRoot);
  const generatedBaseGameData = resolve(artifactRoot, recipe.source.baseMod, recipe.source.gameDataRoot);
  const generatedTargetGameData = resolve(artifactRoot, recipe.source.targetMod, recipe.source.gameDataRoot);
  const wholePattern = new RegExp(recipe.wholeEntries.idOrParentPattern, recipe.wholeEntries.flags);
  const excludeIds = new Set(recipe.wholeEntries.excludeIds);
  const includeIds = new Set(recipe.wholeEntries.includeIds);
  const fieldRules = recipe.fieldMoves.map((rule) => ({ ...rule, matcher: new RegExp(rule.pattern, rule.flags ?? "") }));
  const movedByFile = new Map();
  const sourceHashes = [];
  const xmlDiagnostics = [];
  const fieldMoveCounts = new Map();
  const movedEntries = [];
  const targetCollisions = [];
  const targetFieldMerges = [];
  let wholeEntryCount = 0;

  for (const generatedFile of await listXmlFiles(generatedBaseGameData)) {
    const relativeFile = normalizedPath(generatedBaseGameData, generatedFile);
    const sourceFile = resolve(sourceBaseGameData, relativeFile);
    const text = await readFile(generatedFile, "utf8");
    const sourceText = await readFile(sourceFile, "utf8");
    sourceHashes.push({ file: normalizedPath(sourceRoot, sourceFile), before: hashText(sourceText) });
    const parsed = parse(text);
    const catalog = parsed.root.getRootNode();
    if (!catalog || catalog.tag !== "Catalog") throw new Error("Catalog root is missing: " + relativeFile);
    if (parsed.diagnostics.length > 0) {
      xmlDiagnostics.push({ file: relativeFile, count: parsed.diagnostics.length, diagnostics: parsed.diagnostics });
    }
    const removals = [];
    const inserts = [];

    for (const entry of catalog.children) {
      const id = entry.getAttributeValue("id", "");
      const parent = entry.getAttributeValue("parent", "");
      const moveWhole = (wholePattern.test(id) || wholePattern.test(parent) || includeIds.has(id)) && !excludeIds.has(id);
      wholePattern.lastIndex = 0;
      if (moveWhole) {
        removals.push({ start: entry.start, end: entry.end });
        inserts.push({ kind: "whole", tag: entry.tag, id, text: text.slice(entry.start, entry.end) });
        movedEntries.push({ tag: entry.tag, id, parent: parent || null, source: relativeFile });
        wholeEntryCount += 1;
        continue;
      }

      for (const rule of fieldRules.filter((candidate) => candidate.entryId === id)) {
        const movedChildren = [];
        for (const child of entry.children) {
          if (child.tag !== rule.childTag) continue;
          const value = getAttributeValue(child, rule.attribute);
          if (!rule.matcher.test(value)) continue;
          rule.matcher.lastIndex = 0;
          removals.push({ start: child.start, end: child.end });
          movedChildren.push(text.slice(child.start, child.end));
        }
        if (movedChildren.length > 0) {
          const key = rule.entryId + ":" + rule.childTag + ":" + rule.attribute;
          fieldMoveCounts.set(key, (fieldMoveCounts.get(key) ?? 0) + movedChildren.length);
          inserts.push({ kind: "field", tag: entry.tag, id, children: movedChildren });
        }
      }
    }

    if (removals.length > 0) {
      await writeFile(generatedFile, applyRemovals(text, removals), "utf8");
      movedByFile.set(relativeFile, inserts);
    }
  }

  if (wholeEntryCount !== recipe.wholeEntries.expectedCount) {
    throw new Error("Whole-entry count mismatch: expected " + recipe.wholeEntries.expectedCount + ", got " + wholeEntryCount);
  }

  for (const [relativeFile, snippets] of movedByFile) {
    const targetFile = resolve(generatedTargetGameData, relativeFile);
    if (!existsSync(targetFile)) throw new Error("Target Catalog file is missing: " + relativeFile);
    const targetText = await readFile(targetFile, "utf8");
    const parsed = parse(targetText);
    const catalog = parsed.root.getRootNode();
    if (!catalog || catalog.tag !== "Catalog") throw new Error("Target Catalog root is missing: " + relativeFile);
    if (parsed.diagnostics.length > 0) {
      xmlDiagnostics.push({ file: "target:" + relativeFile, count: parsed.diagnostics.length, diagnostics: parsed.diagnostics });
    }
    const existingEntries = new Map(catalog.children.map((entry) => [entry.tag + ":" + entry.getAttributeValue("id", ""), entry]));
    const filtered = [];
    const collisions = [];
    const groups = new Map();
    const targetEdits = [];
    const newline = targetText.includes("\r\n") ? "\r\n" : "\n";
    for (const snippet of snippets) {
      const key = snippet.tag + ":" + snippet.id;
      const group = groups.get(key) ?? { tag: snippet.tag, id: snippet.id, whole: [], children: [] };
      if (snippet.kind === "field") {
        group.children.push(...snippet.children);
      } else {
        group.whole.push(snippet.text);
      }
      groups.set(key, group);
    }
    for (const [key, group] of groups) {
      const existing = existingEntries.get(key);
      if (!existing) {
        filtered.push(...group.whole);
        if (group.children.length > 0) {
          filtered.push("    <" + group.tag + " id=\"" + group.id + "\">" + newline + group.children.join(newline) + newline + "    </" + group.tag + ">");
        }
        continue;
      }
      const policy = recipe.wholeEntries.targetCollisionPolicy ?? "fail";
      if (group.whole.length > 0) {
        collisions.push({ file: relativeFile, tag: group.tag, id: group.id, policy });
        if (policy === "fail") throw new Error("Target Catalog collision: " + key + " in " + relativeFile);
      }
      const mergeInputs = policy === "retain-target-definition" ? [] : group.whole;
      if (group.children.length > 0) {
        mergeInputs.push("<" + group.tag + " id=\"" + group.id + "\">\n" + group.children.join("\n") + "\n</" + group.tag + ">");
        targetFieldMerges.push({ file: relativeFile, tag: group.tag, id: group.id, childCount: group.children.length });
      }
      if (mergeInputs.length > 0) {
        const targetRaw = targetText.slice(existing.start, existing.end);
        targetEdits.push({ start: existing.start, end: existing.end, text: mergeEntryXml(mergeInputs, targetRaw, DeepCatalogStore) });
      }
    }
    const insertion = filtered.length > 0 ? newline + filtered.join(newline) + newline : "";
    targetEdits.push({ start: catalog.startTagEnd, end: catalog.startTagEnd, text: insertion });
    const updated = applyRemovals(targetText, targetEdits);
    await writeFile(targetFile, updated, "utf8");
    targetCollisions.push(...collisions);
  }

  for (const item of sourceHashes) {
    const sourceFile = resolve(sourceRoot, item.file);
    item.after = hashText(await readFile(sourceFile, "utf8"));
    item.unchanged = item.before === item.after;
  }

  const report = {
    schemaVersion: 1,
    recipeId: recipe.id,
    artifactRoot: recipe.output.artifactRoot,
    wholeEntriesMoved: wholeEntryCount,
    wholeEntriesAddedToTarget: movedEntries.length - targetCollisions.length,
    targetCollisions,
    targetFieldMerges,
    movedEntries,
    fieldMoves: [...fieldMoveCounts.entries()].map(([selector, count]) => ({ selector, count })),
    modifiedCatalogFiles: [...movedByFile.keys()].sort(),
    toleratedXmlDiagnostics: xmlDiagnostics,
    sourceFilesUnchanged: sourceHashes.every((item) => item.unchanged),
    sourceHashes
  };
  const reportPath = resolve(repoRoot, recipe.output.report);
  await mkdir(dirname(reportPath), { recursive: true });
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  console.log(JSON.stringify({ wholeEntriesMoved: report.wholeEntriesMoved, fieldMoves: report.fieldMoves, modifiedCatalogFiles: report.modifiedCatalogFiles.length, sourceFilesUnchanged: report.sourceFilesUnchanged }, null, 2));
}

const [recipePath] = process.argv.slice(2);
if (!recipePath) throw new Error("Usage: node scripts/extract-catalog-boundary.mjs <recipe-path>");
await run(recipePath);
